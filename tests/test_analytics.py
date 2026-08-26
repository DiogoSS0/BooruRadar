import uuid
from datetime import UTC, datetime, timedelta

import pytest

from booruradar.models.snapshot import BooruSnapshot
from booruradar.services.analytics import calculate_growth_metrics, IncompatibleSnapshotsError, InvalidTimeIntervalError

def snapshot(posts: int, captured_at: datetime, provenance: str = "estimated", unit: str = "posts") -> BooruSnapshot:
    return BooruSnapshot(
        id=uuid.uuid4(),
        booru_id=uuid.uuid4(),
        crawl_run_id=uuid.uuid4(),
        captured_at=captured_at,
        health_status="ok",
        health_provenance="observed",
        capabilities=[],
        capabilities_provenance="estimated",
        metrics={"total_posts": {"value": posts, "provenance": provenance, "unit": unit}},
        source_url="https://danbooru.donmai.us",
    )

def test_24h_positive_growth():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    prev = snapshot(1000, t1)
    curr = snapshot(1100, t2)
    metrics = calculate_growth_metrics(prev, curr)
    assert metrics.posts_delta == 100
    assert metrics.elapsed_hours == 24.0
    assert metrics.posts_per_day == 100.0

def test_non_24h_interval_normalization():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 18, 0, tzinfo=UTC)
    prev = snapshot(1000, t1)
    curr = snapshot(1050, t2)
    metrics = calculate_growth_metrics(prev, curr)
    assert metrics.posts_delta == 50
    assert metrics.elapsed_hours == 6.0
    assert metrics.posts_per_day == 200.0

def test_negative_delta_allowed():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    prev = snapshot(1000, t1)
    curr = snapshot(900, t2)
    metrics = calculate_growth_metrics(prev, curr)
    assert metrics.posts_delta == -100
    assert metrics.posts_per_day == -100.0

def test_zero_delta():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    prev = snapshot(1000, t1)
    curr = snapshot(1000, t2)
    metrics = calculate_growth_metrics(prev, curr)
    assert metrics.posts_delta == 0
    assert metrics.posts_per_day == 0.0

def test_equal_timestamps_rejected():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    prev = snapshot(1000, t1)
    curr = snapshot(1100, t1)
    with pytest.raises(InvalidTimeIntervalError):
        calculate_growth_metrics(prev, curr)

def test_reversed_timestamps_rejected():
    t1 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    prev = snapshot(1000, t1)
    curr = snapshot(1100, t2)
    with pytest.raises(InvalidTimeIntervalError):
        calculate_growth_metrics(prev, curr)

def test_incompatible_provenance_rejected():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    prev = snapshot(1000, t1, provenance="observed")
    curr = snapshot(1100, t2)
    with pytest.raises(IncompatibleSnapshotsError):
        calculate_growth_metrics(prev, curr)

def test_incompatible_unit_rejected():
    t1 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    t2 = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    prev = snapshot(1000, t1, unit="images")
    curr = snapshot(1100, t2)
    with pytest.raises(IncompatibleSnapshotsError):
        calculate_growth_metrics(prev, curr)
