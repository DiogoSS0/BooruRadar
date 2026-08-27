from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, ValidationError, model_validator

from booruradar.core.enums import AdapterFamily, MetricProvenance
from booruradar.models.metrics import MetricMap
from booruradar.services.inspection import InspectionResult


class HardInvalidObservationError(ValueError):
    """The candidate cannot safely represent a historical observation."""

    def __init__(self, message: str, *, flags: tuple[str, ...] = ("hard_invalid",)) -> None:
        super().__init__(message)
        self.flags = flags


class SuspiciousObservationError(ValueError):
    """The candidate is valid in isolation but catastrophically unlike history."""

    def __init__(self, flags: tuple[str, ...]) -> None:
        super().__init__("candidate was blocked by historical anomaly protection")
        self.flags = flags


class SnapshotCandidate(BaseModel):
    """Validated data allowed to cross the historical persistence boundary."""

    model_config = ConfigDict(frozen=True)

    captured_at: datetime
    health_status: str
    health_provenance: MetricProvenance
    capabilities: tuple[str, ...]
    capabilities_provenance: MetricProvenance
    metrics: MetricMap
    source_url: AnyHttpUrl

    @model_validator(mode="after")
    def validate_total_posts(self) -> SnapshotCandidate:
        metric = self.metrics.root.get("total_posts")
        if metric is None:
            raise ValueError("total_posts metric is required")
        if isinstance(metric.value, bool) or not isinstance(metric.value, int):
            raise ValueError("total_posts must be an integer")
        if metric.value < 0:
            raise ValueError("total_posts must be non-negative")
        return self

    @property
    def total_posts(self) -> int:
        value = self.metrics.root["total_posts"].value
        assert isinstance(value, int) and not isinstance(value, bool)
        return value


@dataclass(frozen=True)
class TotalPostsAnomalyPolicy:
    """Conservative bootstrap guard, injectable rather than architectural truth."""

    catastrophic_drop_ratio: float = 0.5
    catastrophic_drop_minimum: int = 100_000
    catastrophic_growth_multiplier: float = 5.0
    catastrophic_growth_minimum: int = 1_000_000

    def suspicious_flags(self, previous: int | None, candidate: int) -> tuple[str, ...]:
        if previous is None or previous <= 0:
            return ()

        drop = previous - candidate
        if drop >= self.catastrophic_drop_minimum and candidate < previous * self.catastrophic_drop_ratio:
            return ("total_posts_catastrophic_drop",)

        growth = candidate - previous
        if (
            growth >= self.catastrophic_growth_minimum
            and candidate > previous * self.catastrophic_growth_multiplier
        ):
            return ("total_posts_catastrophic_growth",)
        return ()


@dataclass(frozen=True)
class SnapshotCollectionPolicy:
    """Family-specific rules for accepting a normalized historical snapshot."""

    adapter_family: AdapterFamily
    total_posts_provenance: MetricProvenance
    total_posts_unit: str
    statistics_path: str
    anomaly_policy: TotalPostsAnomalyPolicy = TotalPostsAnomalyPolicy()

    def __post_init__(self) -> None:
        if not self.total_posts_unit:
            raise ValueError("total_posts_unit must be non-empty")
        if not self.statistics_path.startswith("/"):
            raise ValueError("statistics_path must be absolute")

    def validate_candidate(self, candidate: SnapshotCandidate) -> None:
        metric = candidate.metrics.root["total_posts"]
        if metric.provenance is not self.total_posts_provenance:
            raise HardInvalidObservationError(
                f"{self.adapter_family.value} total_posts must be "
                f"{self.total_posts_provenance.value}"
            )
        if metric.unit != self.total_posts_unit:
            raise HardInvalidObservationError(
                f"{self.adapter_family.value} total_posts unit must be "
                f"{self.total_posts_unit}"
            )

    def statistics_url(self, base_url: str) -> str:
        return f"{base_url.rstrip('/')}{self.statistics_path}"

    def previous_total_posts(self, metrics: object) -> int | None:
        return previous_total_posts(
            metrics,
            provenance=self.total_posts_provenance,
            unit=self.total_posts_unit,
        )


DANBOORU_SNAPSHOT_POLICY = SnapshotCollectionPolicy(
    adapter_family=AdapterFamily.DANBOORU,
    total_posts_provenance=MetricProvenance.ESTIMATED,
    total_posts_unit="posts",
    statistics_path="/counts/posts.json",
)

GELBOORU_SNAPSHOT_POLICY = SnapshotCollectionPolicy(
    adapter_family=AdapterFamily.GELBOORU,
    total_posts_provenance=MetricProvenance.OBSERVED,
    total_posts_unit="posts",
    statistics_path="/index.php?page=dapi&s=post&q=index&limit=1",
)


def build_snapshot_candidate(
    inspection: InspectionResult,
    source_url: str,
    *,
    policy: SnapshotCollectionPolicy = DANBOORU_SNAPSHOT_POLICY,
) -> SnapshotCandidate:
    statistics = inspection.public_statistics
    if statistics is None:
        raise HardInvalidObservationError("public statistics were not collected")

    try:
        candidate = SnapshotCandidate(
            captured_at=statistics.collected_at,
            health_status=inspection.health.status,
            health_provenance=inspection.health.provenance,
            capabilities=tuple(
                sorted(capability.value for capability in inspection.capability_discovery.capabilities)
            ),
            capabilities_provenance=inspection.capability_discovery.provenance,
            metrics=MetricMap.model_validate(statistics.metrics),
            source_url=source_url,
        )
    except ValidationError as error:
        raise HardInvalidObservationError("normalized snapshot candidate failed validation") from error
    policy.validate_candidate(candidate)
    return candidate


def previous_total_posts(
    metrics: object,
    *,
    provenance: MetricProvenance = MetricProvenance.ESTIMATED,
    unit: str = "posts",
) -> int | None:
    try:
        metric_map = MetricMap.model_validate(metrics)
    except ValidationError:
        return None
    metric = metric_map.root.get("total_posts")
    if metric is None or isinstance(metric.value, bool) or not isinstance(metric.value, int):
        return None
    if metric.value < 0:
        return None
    if metric.provenance is not provenance:
        return None
    if metric.unit != unit:
        return None
    return metric.value
