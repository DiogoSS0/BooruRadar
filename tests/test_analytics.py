import uuid
from datetime import UTC, datetime

import pytest

from booruradar.models.snapshot import BooruSnapshot
from booruradar.services.analytics import (
    IncompatibleSnapshotsError,
    InvalidTimeIntervalError,
    calculate_growth_metrics,
)


BOORU_ID = uuid.uuid4()


def snapshot(
    posts: object,
    captured_at: datetime,
    provenance: str = "estimated",
    unit: str = "posts",
    *,
    booru_id: uuid.UUID = BOORU_ID,
) -> BooruSnapshot:
    return BooruSnapshot(
        id=uuid.uuid4(),
        booru_id=booru_id,
        crawl_run_id=uuid.uuid4(),
        captured_at=captured_at,
        health_status="ok",
        health_provenance="observed",
        capabilities=[],
        capabilities_provenance="observed",
        metrics={"total_posts": {"value": posts, "provenance": provenance, "unit": unit}},
        source_url="https://example.test/statistics",
    )


def test_24h_positive_growth():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    metrics = calculate_growth_metrics(snapshot(1000, t1), snapshot(1100, t2))
    assert metrics.posts_delta == 100
    assert metrics.elapsed_hours == 24.0
    assert metrics.posts_per_day == 100.0
    assert metrics.provenance == "estimated"


def test_non_24h_interval_normalization():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 18, 0, tzinfo=UTC)
    metrics = calculate_growth_metrics(snapshot(1000, t1), snapshot(1050, t2))
    assert metrics.posts_delta == 50
    assert metrics.elapsed_hours == 6.0
    assert metrics.posts_per_day == 200.0


def test_negative_delta_allowed():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    metrics = calculate_growth_metrics(snapshot(1000, t1), snapshot(900, t2))
    assert metrics.posts_delta == -100
    assert metrics.posts_per_day == -100.0


def test_zero_delta():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    metrics = calculate_growth_metrics(snapshot(1000, t1), snapshot(1000, t2))
    assert metrics.posts_delta == 0
    assert metrics.posts_per_day == 0.0


def test_observed_pair_is_compatible():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    metrics = calculate_growth_metrics(
        snapshot(1000, t1, provenance="observed"),
        snapshot(1120, t2, provenance="observed"),
    )
    assert metrics.posts_delta == 120
    assert metrics.provenance == "observed"


def test_equal_timestamps_rejected():
    captured_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    with pytest.raises(InvalidTimeIntervalError):
        calculate_growth_metrics(snapshot(1000, captured_at), snapshot(1100, captured_at))


def test_reversed_timestamps_rejected():
    previous_at = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    current_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    with pytest.raises(InvalidTimeIntervalError):
        calculate_growth_metrics(snapshot(1000, previous_at), snapshot(1100, current_at))


def test_incompatible_provenance_rejected():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    with pytest.raises(IncompatibleSnapshotsError):
        calculate_growth_metrics(
            snapshot(1000, t1, provenance="observed"),
            snapshot(1100, t2, provenance="estimated"),
        )


def test_incompatible_unit_rejected():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    with pytest.raises(IncompatibleSnapshotsError):
        calculate_growth_metrics(snapshot(1000, t1, unit="images"), snapshot(1100, t2))


@pytest.mark.parametrize("value", [True, -1, 1.5, "1000"])
def test_invalid_total_posts_value_rejected(value: object):
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    with pytest.raises(IncompatibleSnapshotsError):
        calculate_growth_metrics(snapshot(value, t1), snapshot(1100, t2))


def test_malformed_metric_envelope_rejected():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    previous = snapshot(1000, t1)
    previous.metrics = {"total_posts": "raw-payload"}
    with pytest.raises(IncompatibleSnapshotsError):
        calculate_growth_metrics(previous, snapshot(1100, t2))


def test_cross_booru_comparison_rejected():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    with pytest.raises(IncompatibleSnapshotsError):
        calculate_growth_metrics(
            snapshot(1000, t1),
            snapshot(1100, t2, booru_id=uuid.uuid4()),
        )
