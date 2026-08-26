from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from booruradar.models.snapshot import BooruSnapshot
from booruradar.core.enums import MetricProvenance

class IncompatibleSnapshotsError(ValueError):
    """Raised when snapshots cannot be compared for growth analytics."""

class InvalidTimeIntervalError(ValueError):
    """Raised when elapsed time is zero or negative."""

@dataclass(frozen=True)
class GrowthMetrics:
    previous_captured_at: datetime
    current_captured_at: datetime
    previous_total_posts: int
    current_total_posts: int
    posts_delta: int
    elapsed_hours: float
    posts_per_day: float
    provenance: str

def calculate_growth_metrics(previous: BooruSnapshot, current: BooruSnapshot) -> GrowthMetrics:
    prev_metric = previous.metrics.get("total_posts")
    curr_metric = current.metrics.get("total_posts")

    if not prev_metric or not curr_metric:
        raise IncompatibleSnapshotsError("Both snapshots must contain total_posts metric.")

    if prev_metric.get("provenance") != MetricProvenance.ESTIMATED or curr_metric.get("provenance") != MetricProvenance.ESTIMATED:
        raise IncompatibleSnapshotsError("Only ESTIMATED provenance is supported.")

    if prev_metric.get("unit") != "posts" or curr_metric.get("unit") != "posts":
        raise IncompatibleSnapshotsError("Only 'posts' unit is supported.")

    if current.captured_at <= previous.captured_at:
        raise InvalidTimeIntervalError("Current snapshot must be strictly after previous snapshot.")

    elapsed_seconds = (current.captured_at - previous.captured_at).total_seconds()
    elapsed_hours = elapsed_seconds / 3600.0
    
    prev_value = prev_metric.get("value")
    curr_value = curr_metric.get("value")
    
    if not isinstance(prev_value, int) or not isinstance(curr_value, int):
        raise IncompatibleSnapshotsError("total_posts values must be integers.")

    posts_delta = curr_value - prev_value
    posts_per_day = posts_delta * 24.0 / elapsed_hours

    return GrowthMetrics(
        previous_captured_at=previous.captured_at,
        current_captured_at=current.captured_at,
        previous_total_posts=prev_value,
        current_total_posts=curr_value,
        posts_delta=posts_delta,
        elapsed_hours=elapsed_hours,
        posts_per_day=posts_per_day,
        provenance=str(MetricProvenance.ESTIMATED),
    )
