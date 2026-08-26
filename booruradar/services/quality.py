from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, ValidationError, model_validator

from booruradar.core.enums import MetricProvenance
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
        if metric.provenance is not MetricProvenance.ESTIMATED:
            raise ValueError("Danbooru total_posts must be estimated")
        if metric.unit != "posts":
            raise ValueError("total_posts unit must be posts")
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


def build_snapshot_candidate(inspection: InspectionResult, source_url: str) -> SnapshotCandidate:
    statistics = inspection.public_statistics
    if statistics is None:
        raise HardInvalidObservationError("public statistics were not collected")

    try:
        return SnapshotCandidate(
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


def previous_total_posts(metrics: object) -> int | None:
    try:
        metric_map = MetricMap.model_validate(metrics)
    except ValidationError:
        return None
    metric = metric_map.root.get("total_posts")
    if metric is None or isinstance(metric.value, bool) or not isinstance(metric.value, int):
        return None
    if metric.value < 0:
        return None
    if metric.provenance is not MetricProvenance.ESTIMATED:
        return None
    if metric.unit != "posts":
        return None
    return metric.value
