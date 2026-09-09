"""Public counters only; response bodies and post/media objects are discarded."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import UTC, datetime
from html.parser import HTMLParser

import httpx

from booruradar import __version__
from booruradar.adapters.base import (
    AdapterResponseError, BooruAdapter, SourceAccessBlockedError,
    UnsupportedCapabilityError,
)
from booruradar.adapters.evidence import ResponseEvidence, fingerprint_response
from booruradar.adapters.schemas import (
    AdapterCapability, CapabilityDiscovery, HealthCheck, PublicStatistics,
    RecentPostMetadata, SiteDetection, TagStatistic,
)
from booruradar.core.enums import AdapterFamily, MetricProvenance
from booruradar.models.metrics import MetricEnvelope


class AggregateAdapter(BooruAdapter):
    adapter_version = __version__
    statistics_path: str
    total_posts_provenance = MetricProvenance.OBSERVED

    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        super().__init__(base_url, client)
        self._evidence: list[ResponseEvidence] = []
        self._statistics: PublicStatistics | None = None

    @property
    def request_evidence(self) -> tuple[ResponseEvidence, ...]:
        return tuple(self._evidence)

    def clear_request_evidence(self) -> None:
        self._evidence.clear()
        self._statistics = None

    @classmethod
    async def detect(cls, base_url: str, client: httpx.AsyncClient) -> SiteDetection:
        try:
            await cls(base_url, client).fetch_public_statistics()
        except (httpx.HTTPError, AdapterResponseError, SourceAccessBlockedError):
            detected = False
        else:
            detected = True
        return SiteDetection(
            detected=detected, family=cls.family,
            confidence=1.0 if detected else 0.0,
            evidence=("matched aggregate counter" if detected else "counter unavailable",),
        )

    async def health_check(self) -> HealthCheck:
        # Reuse this validated counter during the same inspection. Failures propagate
        # once, so access blocks never cause a second request in this collection.
        statistics = await self.fetch_public_statistics()
        return HealthCheck(healthy=True, status="ok", checked_at=statistics.collected_at)

    async def discover_capabilities(self) -> CapabilityDiscovery:
        return CapabilityDiscovery(
            capabilities=frozenset({AdapterCapability.SITE_DETECTION,
                                    AdapterCapability.HEALTH_CHECK,
                                    AdapterCapability.PUBLIC_STATISTICS}),
            discovered_at=datetime.now(UTC),
        )

    async def fetch_public_statistics(self) -> PublicStatistics:
        if self._statistics is not None:
            return self._statistics
        response = await self._get_counter_response(self.statistics_path, "total_posts")
        value = self.parse_count(response)
        if type(value) is not int or value < 0:
            raise AdapterResponseError("counter must be a non-negative integer")
        self._statistics = PublicStatistics(
            collected_at=datetime.now(UTC),
            metrics={"total_posts": MetricEnvelope(value=value, unit="posts",
                                                  provenance=self.total_posts_provenance)},
        )
        return self._statistics

    async def _get_counter_response(self, path: str, identifier: str) -> httpx.Response:
        response = await self.client.get(f"{self.base_url}{path}")
        self._evidence.append(fingerprint_response(response, identifier))
        if response.status_code == 403 or response.headers.get("cf-mitigated", "").lower() == "challenge":
            raise SourceAccessBlockedError("source access was blocked")
        response.raise_for_status()
        return response

    def parse_count(self, response: httpx.Response) -> int:
        raise NotImplementedError

    async def fetch_recent_posts(self, *, limit: int = 50) -> Sequence[RecentPostMetadata]:
        raise UnsupportedCapabilityError("aggregate-only adapter")

    async def fetch_tag_statistics(self, *, tag_names: Sequence[str] | None = None) -> Sequence[TagStatistic]:
        raise UnsupportedCapabilityError("aggregate-only adapter")


class MoebooruAdapter(AggregateAdapter):
    adapter_name = "moebooru"
    family = AdapterFamily.MOEBOORU
    statistics_path = "/post.xml?limit=1"

    def parse_count(self, response: httpx.Response) -> int:
        if b"<!DOCTYPE" in response.content or b"<!ENTITY" in response.content:
            raise AdapterResponseError("XML declarations are unsupported")
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as error:
            raise AdapterResponseError("counter was not valid XML") from error
        count = root.get("count", "")
        if root.tag != "posts" or not re.fullmatch(r"[0-9]+", count):
            raise AdapterResponseError("posts counter is missing or invalid")
        return int(count)


class _HomeCounterParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.containers = 0
        self.digits: list[str] = []
        self.invalid = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "div":
            if "home-footer-counter" in (attributes.get("class") or "").split():
                self.containers += 1
                self.depth = 1
            elif self.depth:
                self.depth += 1
        if tag == "img" and self.depth:
            digit = attributes.get("alt") or ""
            if not re.fullmatch(r"[0-9]", digit):
                self.invalid = True
            self.digits.append(digit)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.depth:
            self.depth -= 1


class E621Adapter(AggregateAdapter):
    adapter_name = "e621-counter"
    family = AdapterFamily.E621
    statistics_path = "/"

    def parse_count(self, response: httpx.Response) -> int:
        # /posts/count.json is capped. The homepage reports Post.fast_count instead.
        parser = _HomeCounterParser()
        parser.feed(response.text)
        if parser.containers != 1 or parser.depth or parser.invalid or not 1 <= len(parser.digits) <= 18:
            raise AdapterResponseError("homepage counter is missing or invalid")
        return int("".join(parser.digits))


class PhilomenaAdapter(AggregateAdapter):
    adapter_name = "philomena"
    family = AdapterFamily.PHILOMENA
    # Derpibooru's public Everything filter has no hidden or spoilered tags.
    statistics_path = "/api/v1/json/search/images?q=*&per_page=1&filter_id=56027"

    def parse_count(self, response: httpx.Response) -> int:
        try:
            payload = response.json()
        except ValueError as error:
            raise AdapterResponseError("counter was not valid JSON") from error
        if not isinstance(payload, dict) or type(payload.get("total")) is not int:
            raise AdapterResponseError("total counter is missing or invalid")
        return payload["total"]
