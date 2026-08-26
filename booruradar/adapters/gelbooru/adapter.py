from __future__ import annotations

import xml.etree.ElementTree as ET
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


class GelbooruResponseError(ValueError):
    """Raised when a Gelbooru response cannot be normalized safely."""


class GelbooruAdapter(BooruAdapter):
    adapter_name = "gelbooru"
    adapter_version = __version__
    family = AdapterFamily.GELBOORU

    MAX_RECENT_POST_LIMIT: ClassVar[int] = 1000
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
            response = await client.get(
                f"{base_url.rstrip('/')}/index.php",
                params={"page": "dapi", "s": "post", "q": "index", "limit": 1}
            )
            if not response.is_success:
                return cls._detection_result(False, "posts returned a non-success status")
            content = response.content
        except httpx.HTTPError:
            return cls._detection_result(False, "posts request failed")
            
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return cls._detection_result(False, "response was not valid XML")
            
        if root.tag != "posts":
            return cls._detection_result(False, "root XML element was not <posts>")
            
        count_attr = root.get("count")
        if count_attr is None:
            return cls._detection_result(False, "root <posts> missing count attribute")
            
        try:
            count = int(count_attr)
            if count < 0:
                return cls._detection_result(False, "count attribute was negative")
        except ValueError:
            return cls._detection_result(False, "count attribute was not an integer")
            
        posts = root.findall("post")
        if posts:
            post = posts[0]
            if not all(k in post.attrib for k in ("id", "change", "rating", "tags")):
                return cls._detection_result(False, "post element missing required attributes")

        return cls._detection_result(True, "matched GELBOORU DAPI XML shape")

    async def health_check(self) -> HealthCheck:
        started_at = perf_counter()
        checked_at = datetime.now(UTC)
        try:
            root = await self._get_xml(
                "recent_posts", 
                "/index.php", 
                params={"page": "dapi", "s": "post", "q": "index", "limit": 1}
            )
            if root.tag != "posts":
                raise GelbooruResponseError("root XML element was not <posts>")
        except httpx.HTTPStatusError as error:
            status = f"http_{error.response.status_code}"
            healthy = False
        except (httpx.HTTPError, GelbooruResponseError):
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
        root = await self._get_xml(
            "total_posts", 
            "/index.php", 
            params={"page": "dapi", "s": "post", "q": "index", "limit": 1}
        )
        if root.tag != "posts":
            raise GelbooruResponseError("total_posts response must have <posts> root")
            
        count_attr = root.get("count")
        if count_attr is None:
            raise GelbooruResponseError("total_posts response is missing count attribute")
            
        try:
            total_posts = int(count_attr)
        except ValueError as error:
            raise GelbooruResponseError("count must be an integer") from error
            
        if total_posts < 0:
            raise GelbooruResponseError("count must be non-negative")
            
        return PublicStatistics(
            collected_at=datetime.now(UTC),
            metrics={
                "total_posts": MetricEnvelope(
                    value=total_posts,
                    provenance=MetricProvenance.OBSERVED,
                    unit="posts",
                )
            },
        )

    async def fetch_recent_posts(self, *, limit: int = 50) -> Sequence[RecentPostMetadata]:
        self._validate_recent_post_limit(limit)
        root = await self._get_xml(
            "recent_posts", 
            "/index.php", 
            params={"page": "dapi", "s": "post", "q": "index", "limit": limit}
        )
        if root.tag != "posts":
            raise GelbooruResponseError("recent_posts response must have <posts> root")

        posts: list[RecentPostMetadata] = []
        for raw_post in root.findall("post"):
            try:
                post_id = int(raw_post.attrib["id"])
                if post_id <= 0:
                    raise GelbooruResponseError("id must be positive")
                    
                # The XML 'change' field is a change ID, not the upload timestamp.
                created_at = None
                
                rating = raw_post.attrib["rating"]
                if not rating:
                    raise GelbooruResponseError("rating must be non-empty")
                    
                tags = tuple(raw_post.attrib["tags"].split())
            except (KeyError, ValueError) as error:
                raise GelbooruResponseError("recent_posts contained malformed metadata") from error

            try:
                posts.append(
                    RecentPostMetadata(
                        external_id=str(post_id),
                        created_at=created_at,
                        rating=rating,
                        tags=tags,
                        post_url=f"{self.base_url}/index.php?page=post&s=view&id={post_id}",
                        provenance=MetricProvenance.OBSERVED,
                    )
                )
            except ValidationError as error:
                raise GelbooruResponseError("recent_posts contained invalid metadata") from error
                
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
            root = await self._get_xml(
                "tag_statistics",
                "/index.php",
                params={"page": "dapi", "s": "tag", "q": "index", "name": tag_name},
            )
            if root.tag != "tags":
                raise GelbooruResponseError("tag_statistics response must have <tags> root")

            for tag_elem in root.findall("tag"):
                if tag_elem.get("name") == tag_name:
                    try:
                        post_count = int(tag_elem.attrib["count"])
                        if post_count < 0:
                            raise ValueError("count must be non-negative")
                        category = tag_elem.attrib.get("type", "0")
                    except (KeyError, ValueError) as error:
                        raise GelbooruResponseError("tag contained malformed metadata") from error
                        
                    statistics.append(
                        TagStatistic(
                            name=tag_name,
                            post_count=MetricEnvelope(
                                value=post_count,
                                provenance=MetricProvenance.OBSERVED,
                                unit="posts",
                            ),
                            category=category,
                            collected_at=datetime.now(UTC),
                        )
                    )
                    break
        return tuple(statistics)

    async def _get_xml(
        self,
        endpoint_identifier: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> ET.Element:
        response = await self.client.get(f"{self.base_url}{path}", params=params)
        self._request_evidence.append(fingerprint_response(response, endpoint_identifier))
        # Do not raise for status yet. Wait, we shouldn't rely on HTTP status alone.
        # But if it's 404 or 500, httpx will give HTTPStatusError if we call raise_for_status().
        # Actually, the spec says "do not use HTTP status alone as response validation".
        # But we still want to raise if it's a 500 error probably.
        # Wait, the spec says "Safebooru may return HTTP 200 for no-result and some invalid searches. Therefore: do not use HTTP status alone as response validation."
        # This implies we can call `raise_for_status()`, but it won't catch everything.
        response.raise_for_status()
        try:
            return ET.fromstring(response.content)
        except ET.ParseError as error:
            raise GelbooruResponseError(f"{endpoint_identifier} response was not valid XML") from error

    @classmethod
    def _detection_result(cls, detected: bool, evidence: str) -> SiteDetection:
        return SiteDetection(
            detected=detected,
            family=cls.family,
            confidence=1.0 if detected else 0.0,
            evidence=(evidence,),
        )

    @classmethod
    def _validate_recent_post_limit(cls, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= cls.MAX_RECENT_POST_LIMIT:
            raise ValueError(f"limit must be between 1 and {cls.MAX_RECENT_POST_LIMIT}")
