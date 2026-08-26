from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from booruradar.core.enums import AdapterFamily, MetricProvenance
from booruradar.models.metrics import MetricEnvelope


class AdapterCapability(StrEnum):
    SITE_DETECTION = "site_detection"
    HEALTH_CHECK = "health_check"
    PUBLIC_STATISTICS = "public_statistics"
    RECENT_POST_METADATA = "recent_post_metadata"
    TAG_STATISTICS = "tag_statistics"


class AdapterResult(BaseModel):
    model_config = ConfigDict(frozen=True)


class SiteDetection(AdapterResult):
    detected: bool
    family: AdapterFamily
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: tuple[str, ...] = ()
    provenance: MetricProvenance = MetricProvenance.OBSERVED


class HealthCheck(AdapterResult):
    healthy: bool
    checked_at: datetime
    status: str
    latency_ms: MetricEnvelope | None = None
    provenance: MetricProvenance = MetricProvenance.OBSERVED


class CapabilityDiscovery(AdapterResult):
    capabilities: frozenset[AdapterCapability]
    discovered_at: datetime
    provenance: MetricProvenance = MetricProvenance.OBSERVED

    def supports(self, capability: AdapterCapability) -> bool:
        return capability in self.capabilities


class PublicStatistics(AdapterResult):
    collected_at: datetime
    metrics: dict[str, MetricEnvelope]


class RecentPostMetadata(AdapterResult):
    external_id: str
    created_at: datetime | None = None
    rating: str | None = None
    tags: tuple[str, ...] = ()
    post_url: AnyHttpUrl | None = None
    provenance: MetricProvenance = MetricProvenance.OBSERVED


class TagStatistic(AdapterResult):
    name: str
    post_count: MetricEnvelope
    category: str | None = None
    collected_at: datetime

    @field_validator("post_count")
    @classmethod
    def validate_post_count(cls, metric: MetricEnvelope) -> MetricEnvelope:
        if isinstance(metric.value, bool) or not isinstance(metric.value, int) or metric.value < 0:
            raise ValueError("post_count must contain a non-negative integer value")
        return metric
