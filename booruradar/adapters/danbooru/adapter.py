from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, ClassVar

import httpx
from pydantic import ValidationError

from booruradar import __version__
from booruradar.adapters.base import BooruAdapter
from booruradar.adapters.evidence import ResponseEvidence, fingerprint_response
from booruradar.adapters.schemas import (
    AdapterCapability,
    CapabilityDiscovery,
    HealthCheck,
    PublicStatistics,
    RecentPostMetadata,
    SiteDetection,
    TagStatistic,
)
from booruradar.core.enums import AdapterFamily, MetricProvenance
from booruradar.models.metrics import MetricEnvelope


class DanbooruResponseError(ValueError):
    """Raised when a modern Danbooru response cannot be normalized safely."""


class DanbooruAdapter(BooruAdapter):
    adapter_name = "danbooru"
    adapter_version = __version__
    family = AdapterFamily.DANBOORU

    MAX_RECENT_POST_LIMIT: ClassVar[int] = 100
    MAX_TAG_NAMES: ClassVar[int] = 25

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        super().__init__(base_url, client)
        self._request_evidence: list[ResponseEvidence] = []

    @property
    def request_evidence(self) -> tuple[ResponseEvidence, ...]:
        return tuple(self._request_evidence)

    def clear_request_evidence(self) -> None:
        self._request_evidence.clear()

    @classmethod
    async def detect(cls, base_url: str, client: httpx.AsyncClient) -> SiteDetection:
        try:
            response = await client.get(f"{base_url.rstrip('/')}/posts.json", params={"limit": 1})
            if not response.is_success:
                return cls._detection_result(False, "posts.json returned a non-success status")
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return cls._detection_result(False, "posts.json was not a compatible JSON response")

        if not cls._has_modern_post_shape(payload):
            return cls._detection_result(False, "posts.json did not match the modern post shape")
        return cls._detection_result(True, "posts.json matched the modern post shape")

    async def health_check(self) -> HealthCheck:
        started_at = perf_counter()
        checked_at = datetime.now(UTC)
        try:
            payload = await self._get_json("recent_posts", "/posts.json", params={"limit": 1})
            if not self._has_modern_post_shape(payload):
                raise DanbooruResponseError("recent_posts did not match the modern post shape")
        except httpx.HTTPStatusError as error:
            status = f"http_{error.response.status_code}"
            healthy = False
        except (httpx.HTTPError, DanbooruResponseError):
            status = "invalid_response"
            healthy = False
        else:
            status = "ok"
            healthy = True

        latency_ms = round((perf_counter() - started_at) * 1000, 3)
        return HealthCheck(
            healthy=healthy,
            checked_at=checked_at,
            status=status,
            latency_ms=MetricEnvelope(
                value=latency_ms,
                provenance=MetricProvenance.OBSERVED,
                unit="ms",
            ),
        )

    async def discover_capabilities(self) -> CapabilityDiscovery:
        return CapabilityDiscovery(
            capabilities=frozenset(AdapterCapability),
            discovered_at=datetime.now(UTC),
        )

    async def fetch_public_statistics(self) -> PublicStatistics:
        payload = await self._get_json("total_posts", "/counts/posts.json")
        if not isinstance(payload, Mapping):
            raise DanbooruResponseError("total_posts response must be an object")
        counts = payload.get("counts")
        if not isinstance(counts, Mapping) or "posts" not in counts:
            raise DanbooruResponseError("total_posts response is missing counts.posts")

        total_posts = self._require_non_negative_int(counts["posts"], "counts.posts")
        return PublicStatistics(
            collected_at=datetime.now(UTC),
            metrics={
                "total_posts": MetricEnvelope(
                    value=total_posts,
                    provenance=MetricProvenance.ESTIMATED,
                    unit="posts",
                )
            },
        )

    async def fetch_recent_posts(self, *, limit: int = 50) -> Sequence[RecentPostMetadata]:
        self._validate_recent_post_limit(limit)
        payload = await self._get_json("recent_posts", "/posts.json", params={"limit": limit})
        if not isinstance(payload, list):
            raise DanbooruResponseError("recent_posts response must be a list")

        posts: list[RecentPostMetadata] = []
        for raw_post in payload:
            if not isinstance(raw_post, Mapping):
                raise DanbooruResponseError("recent_posts entries must be objects")
            post_id = self._require_positive_int(raw_post.get("id"), "post.id")
            created_at = raw_post.get("created_at")
            rating = raw_post.get("rating")
            tag_string = raw_post.get("tag_string")
            if not isinstance(created_at, str) or not created_at:
                raise DanbooruResponseError("post.created_at must be a non-empty string")
            if not isinstance(rating, str) or not rating:
                raise DanbooruResponseError("post.rating must be a non-empty string")
            if not isinstance(tag_string, str):
                raise DanbooruResponseError("post.tag_string must be a string")

            try:
                posts.append(
                    RecentPostMetadata(
                        external_id=str(post_id),
                        created_at=created_at,
                        rating=rating,
                        tags=tuple(tag_string.split()),
                        post_url=f"{self.base_url}/posts/{post_id}",
                        provenance=MetricProvenance.OBSERVED,
                    )
                )
            except ValidationError as error:
                raise DanbooruResponseError("recent_posts contained malformed metadata") from error
        return tuple(posts)

    async def fetch_tag_statistics(
        self,
        *,
        tag_names: Sequence[str] | None = None,
    ) -> Sequence[TagStatistic]:
        if tag_names is None:
            return ()
        if isinstance(tag_names, (str, bytes)):
            raise ValueError("tag_names must be a sequence of names, not a string")
        if len(tag_names) > self.MAX_TAG_NAMES:
            raise ValueError(f"at most {self.MAX_TAG_NAMES} tag names may be requested")

        normalized_names: list[str] = []
        for tag_name in tag_names:
            if not isinstance(tag_name, str) or not tag_name.strip():
                raise ValueError("tag names must be non-empty strings")
            stripped_name = tag_name.strip()
            if stripped_name not in normalized_names:
                normalized_names.append(stripped_name)

        statistics: list[TagStatistic] = []
        for tag_name in normalized_names:
            payload = await self._get_json(
                "tag_statistics",
                "/tags.json",
                params={"search[name]": tag_name, "limit": 1},
            )
            if not isinstance(payload, list):
                raise DanbooruResponseError("tag_statistics response must be a list")

            raw_tag = next(
                (
                    item
                    for item in payload
                    if isinstance(item, Mapping) and item.get("name") == tag_name
                ),
                None,
            )
            if raw_tag is None:
                continue
            post_count = self._require_non_negative_int(raw_tag.get("post_count"), "tag.post_count")
            category = self._require_non_negative_int(raw_tag.get("category"), "tag.category")
            statistics.append(
                TagStatistic(
                    name=tag_name,
                    post_count=MetricEnvelope(
                        value=post_count,
                        provenance=MetricProvenance.OBSERVED,
                        unit="posts",
                    ),
                    category=str(category),
                    collected_at=datetime.now(UTC),
                )
            )
        return tuple(statistics)

    async def _get_json(
        self,
        endpoint_identifier: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> Any:
        response = await self.client.get(f"{self.base_url}{path}", params=params)
        self._request_evidence.append(fingerprint_response(response, endpoint_identifier))
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as error:
            raise DanbooruResponseError(f"{endpoint_identifier} response was not valid JSON") from error

    @classmethod
    def _detection_result(cls, detected: bool, evidence: str) -> SiteDetection:
        return SiteDetection(
            detected=detected,
            family=cls.family,
            confidence=1.0 if detected else 0.0,
            evidence=(evidence,),
        )

    @staticmethod
    def _has_modern_post_shape(payload: Any) -> bool:
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], Mapping):
            return False
        post = payload[0]
        post_id = post.get("id")
        return (
            isinstance(post_id, int)
            and not isinstance(post_id, bool)
            and post_id > 0
            and isinstance(post.get("created_at"), str)
            and isinstance(post.get("rating"), str)
            and isinstance(post.get("tag_string"), str)
        )

    @classmethod
    def _validate_recent_post_limit(cls, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= cls.MAX_RECENT_POST_LIMIT:
            raise ValueError(f"limit must be between 1 and {cls.MAX_RECENT_POST_LIMIT}")

    @staticmethod
    def _require_non_negative_int(value: Any, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DanbooruResponseError(f"{field_name} must be a non-negative integer")
        return value

    @classmethod
    def _require_positive_int(cls, value: Any, field_name: str) -> int:
        parsed = cls._require_non_negative_int(value, field_name)
        if parsed == 0:
            raise DanbooruResponseError(f"{field_name} must be positive")
        return parsed
