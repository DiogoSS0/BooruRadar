from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from booruradar.adapters.base import BooruAdapter
from booruradar.adapters.schemas import (
    AdapterCapability,
    CapabilityDiscovery,
    HealthCheck,
    PublicStatistics,
    RecentPostMetadata,
    TagStatistic,
)


class InspectionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    health: HealthCheck
    capability_discovery: CapabilityDiscovery
    public_statistics: PublicStatistics | None = None
    recent_posts: tuple[RecentPostMetadata, ...] = ()
    tag_statistics: tuple[TagStatistic, ...] = ()


class BooruInspectionService:
    """Coordinates supported metadata calls without knowing an adapter family."""

    async def inspect(
        self,
        adapter: BooruAdapter,
        *,
        recent_post_limit: int = 50,
        tag_names: Sequence[str] | None = None,
    ) -> InspectionResult:
        if recent_post_limit < 1:
            raise ValueError("recent_post_limit must be positive")

        health = await adapter.health_check()
        discovery = await adapter.discover_capabilities()

        public_statistics = None
        if discovery.supports(AdapterCapability.PUBLIC_STATISTICS):
            public_statistics = await adapter.fetch_public_statistics()

        recent_posts: Sequence[RecentPostMetadata] = ()
        if discovery.supports(AdapterCapability.RECENT_POST_METADATA):
            recent_posts = await adapter.fetch_recent_posts(limit=recent_post_limit)

        tag_statistics: Sequence[TagStatistic] = ()
        if discovery.supports(AdapterCapability.TAG_STATISTICS):
            tag_statistics = await adapter.fetch_tag_statistics(tag_names=tag_names)

        return InspectionResult(
            health=health,
            capability_discovery=discovery,
            public_statistics=public_statistics,
            recent_posts=tuple(recent_posts),
            tag_statistics=tuple(tag_statistics),
        )
