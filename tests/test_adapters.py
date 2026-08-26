from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

import httpx
import pytest

from booruradar.adapters import AdapterRegistry, BooruAdapter
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
from booruradar.services import BooruInspectionService


NOW = datetime(2026, 8, 26, tzinfo=UTC)


class ExampleAdapter(BooruAdapter):
    adapter_name = "example"
    family = AdapterFamily.CUSTOM

    @classmethod
    async def detect(cls, base_url: str, client: httpx.AsyncClient) -> SiteDetection:
        return SiteDetection(
            detected=True,
            family=cls.family,
            confidence=1.0,
            evidence=(base_url,),
        )

    async def health_check(self) -> HealthCheck:
        return HealthCheck(healthy=True, checked_at=NOW, status="ok")

    async def discover_capabilities(self) -> CapabilityDiscovery:
        return CapabilityDiscovery(
            capabilities=frozenset(
                {
                    AdapterCapability.SITE_DETECTION,
                    AdapterCapability.HEALTH_CHECK,
                    AdapterCapability.PUBLIC_STATISTICS,
                    AdapterCapability.RECENT_POST_METADATA,
                    AdapterCapability.TAG_STATISTICS,
                }
            ),
            discovered_at=NOW,
        )

    async def fetch_public_statistics(self) -> PublicStatistics:
        return PublicStatistics(
            collected_at=NOW,
            metrics={
                "total_posts": MetricEnvelope(
                    value=10,
                    provenance=MetricProvenance.OBSERVED,
                    unit="posts",
                )
            },
        )

    async def fetch_recent_posts(self, *, limit: int = 50) -> Sequence[RecentPostMetadata]:
        return (RecentPostMetadata(external_id="post-1", created_at=NOW),)[:limit]

    async def fetch_tag_statistics(
        self,
        *,
        tag_names: Sequence[str] | None = None,
    ) -> Sequence[TagStatistic]:
        name = tag_names[0] if tag_names else "example_tag"
        return (
            TagStatistic(
                name=name,
                post_count=MetricEnvelope(value=7, provenance=MetricProvenance.OBSERVED),
                collected_at=NOW,
            ),
        )


def test_registry_registers_creates_and_detects_adapter() -> None:
    async def exercise() -> None:
        registry = AdapterRegistry()
        registry.register(ExampleAdapter)

        async with httpx.AsyncClient() as client:
            adapter = registry.create("example", "https://example.test/", client)
            matches = await registry.detect("https://example.test", client)

        assert adapter.base_url == "https://example.test"
        assert registry.registered_names == ("example",)
        assert matches[0].family is AdapterFamily.CUSTOM

    asyncio.run(exercise())


def test_registry_rejects_duplicate_adapter_names() -> None:
    registry = AdapterRegistry()
    registry.register(ExampleAdapter)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(ExampleAdapter)


def test_inspection_service_uses_discovered_capabilities() -> None:
    async def exercise() -> None:
        async with httpx.AsyncClient() as client:
            adapter = ExampleAdapter("https://example.test", client)
            result = await BooruInspectionService().inspect(
                adapter,
                recent_post_limit=1,
                tag_names=("wanted_tag",),
            )

        assert result.health.healthy is True
        assert result.public_statistics is not None
        assert result.public_statistics.metrics["total_posts"].value == 10
        assert result.recent_posts[0].external_id == "post-1"
        assert result.tag_statistics[0].name == "wanted_tag"

    asyncio.run(exercise())


def test_recent_post_contract_has_no_media_fields() -> None:
    field_names = set(RecentPostMetadata.model_fields)

    assert "image" not in field_names
    assert "image_url" not in field_names
    assert "file_url" not in field_names
