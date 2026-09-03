from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import ValidationError

from booruradar.models.metrics import MetricMap
from booruradar.models.snapshot import BooruSnapshot


class IncompatibleSnapshotsError(ValueError):
    """Raised when snapshots cannot be compared for growth analytics."""


class InvalidTimeIntervalError(ValueError):
    """Raised when elapsed time is zero or negative."""


class ZeroBaselineError(ValueError):
    """Raised when relative growth has no non-zero denominator."""


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
    if previous.booru_id != current.booru_id:
        raise IncompatibleSnapshotsError("snapshots must belong to the same booru")

    try:
        previous_metrics = MetricMap.model_validate(previous.metrics)
        current_metrics = MetricMap.model_validate(current.metrics)
    except ValidationError as error:
        raise IncompatibleSnapshotsError("snapshots contain malformed metrics") from error

    prev_metric = previous_metrics.root.get("total_posts")
    curr_metric = current_metrics.root.get("total_posts")
    if prev_metric is None or curr_metric is None:
        raise IncompatibleSnapshotsError("both snapshots must contain total_posts")

    if prev_metric.provenance is not curr_metric.provenance:
        raise IncompatibleSnapshotsError("total_posts provenance must match")
    if prev_metric.unit != "posts" or curr_metric.unit != "posts":
        raise IncompatibleSnapshotsError("total_posts unit must be posts")

    prev_value = prev_metric.value
    curr_value = curr_metric.value
    if (
        isinstance(prev_value, bool)
        or isinstance(curr_value, bool)
        or not isinstance(prev_value, int)
        or not isinstance(curr_value, int)
        or prev_value < 0
        or curr_value < 0
    ):
        raise IncompatibleSnapshotsError("total_posts values must be non-negative integers")

    try:
        valid_interval = current.captured_at > previous.captured_at
    except TypeError as error:
        raise InvalidTimeIntervalError("snapshot timestamps must use compatible timezones") from error
    if not valid_interval:
        raise InvalidTimeIntervalError("current snapshot must be strictly after previous snapshot")

    elapsed_hours = (current.captured_at - previous.captured_at).total_seconds() / 3600.0
    posts_delta = curr_value - prev_value
    return GrowthMetrics(
        previous_captured_at=previous.captured_at,
        current_captured_at=current.captured_at,
        previous_total_posts=prev_value,
        current_total_posts=curr_value,
        posts_delta=posts_delta,
        elapsed_hours=elapsed_hours,
        posts_per_day=posts_delta * 24.0 / elapsed_hours,
        provenance=prev_metric.provenance.value,
    )


def calculate_relative_growth_percent_per_day(metrics: GrowthMetrics) -> float:
    """Return elapsed-window relative growth without rounding or clamping."""

    if metrics.previous_total_posts == 0:
        raise ZeroBaselineError("relative growth requires a non-zero previous total")
    return (
        (metrics.posts_delta / metrics.previous_total_posts)
        * (24.0 / metrics.elapsed_hours)
        * 100.0
    )
