from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from booruradar.core.enums import MetricProvenance
from booruradar.models.booru import Booru
from booruradar.models.snapshot import BooruSnapshot
from booruradar.services.catalog import (
    CatalogReadService,
    GrowthRankingEligibleRecord,
    LargestRankingEligibleRecord,
    RankingIneligibleReason,
    RankingIneligibleRecord,
    RankingMode,
)


NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)


class RowsResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class ExecuteOnlySession:
    """A read seam where a second query or any write method is observable."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def execute(self, statement: object) -> RowsResult:
        self.statements.append(statement)
        return RowsResult(self.rows)


def booru(
    name: str,
    identifier: int,
    *,
    enabled: bool = True,
    family: str = "danbooru",
) -> Booru:
    return Booru(
        id=uuid.UUID(int=identifier),
        name=name,
        canonical_url=f"https://{identifier}.example",
        adapter_family=family,
        adapter_name=f"{family}-v1",
        is_enabled=enabled,
    )


def total_metric(
    value: object,
    *,
    provenance: str = "observed",
    unit: str = "posts",
) -> dict[str, object]:
    return {
        "total_posts": {
            "value": value,
            "provenance": provenance,
            "unit": unit,
        }
    }


def snapshot(
    owner: Booru,
    identifier: int,
    *,
    metrics: object,
    captured_at: datetime = NOW,
) -> BooruSnapshot:
    return BooruSnapshot(
        id=uuid.UUID(int=identifier),
        booru_id=owner.id,
        crawl_run_id=uuid.uuid4(),
        captured_at=captured_at,
        metrics=metrics,
        source_url="https://private.example/api",
    )


def run_ranking(
    rows: list[tuple[Any, ...]],
    *,
    mode: RankingMode,
    limit: int = 50,
    offset: int = 0,
):
    session = ExecuteOnlySession(rows)
    result = asyncio.run(
        CatalogReadService(session).rank_boorus(  # type: ignore[arg-type]
            mode=mode,
            limit=limit,
            offset=offset,
        )
    )
    return result, session


def test_largest_is_global_deterministic_and_paginated_after_ranking() -> None:
    alpha = booru("alpha", 2)
    beta = booru("Alpha", 1)
    gamma = booru("Gamma", 3)
    missing = booru("Missing", 4)
    disabled = booru("Disabled", 5, enabled=False)
    rows = [
        (beta, snapshot(beta, 21, metrics=total_metric(500)), 1),
        (disabled, snapshot(disabled, 51, metrics=total_metric(999_999)), 1),
        (missing, snapshot(missing, 41, metrics={}), 1),
        (gamma, snapshot(gamma, 31, metrics=total_metric(900)), 1),
        (alpha, snapshot(alpha, 11, metrics=total_metric(500)), 1),
    ]

    result, session = run_ranking(
        rows,
        mode=RankingMode.LARGEST,
        limit=2,
        offset=1,
    )

    assert result.mode is RankingMode.LARGEST
    assert result.unit == "posts"
    assert result.total == 4
    assert result.eligible_count == 3
    assert [(item.name, item.rank) for item in result.items] == [
        ("Alpha", 2),
        ("alpha", 3),
    ]
    assert all(isinstance(item, LargestRankingEligibleRecord) for item in result.items)
    assert len(session.statements) == 1
    sql = str(session.statements[0])
    assert "row_number() OVER" in sql
    assert "booru_snapshots.captured_at DESC" in sql
    assert "booru_snapshots.id DESC" in sql
    assert "snapshot_rank <=" in sql
    assert "boorus.is_enabled IS true" in sql


def test_fastest_growth_orders_positive_zero_negative_and_preserves_provenance() -> None:
    fast = booru("Fast", 10)
    flat = booru("Flat", 11, family="gelbooru")
    falling = booru("Falling", 12)
    one = booru("One", 13)
    rows = [
        (
            fast,
            snapshot(
                fast,
                102,
                metrics=total_metric(1_200, provenance="estimated"),
            ),
            1,
        ),
        (
            fast,
            snapshot(
                fast,
                101,
                metrics=total_metric(1_000, provenance="estimated"),
                captured_at=NOW - timedelta(hours=12),
            ),
            2,
        ),
        (flat, snapshot(flat, 112, metrics=total_metric(700)), 1),
        (
            flat,
            snapshot(flat, 111, metrics=total_metric(700), captured_at=NOW - timedelta(days=1)),
            2,
        ),
        (falling, snapshot(falling, 122, metrics=total_metric(900)), 1),
        (
            falling,
            snapshot(
                falling,
                121,
                metrics=total_metric(1_000),
                captured_at=NOW - timedelta(days=1),
            ),
            2,
        ),
        (one, snapshot(one, 131, metrics=total_metric(50)), 1),
    ]

    result, _ = run_ranking(rows, mode=RankingMode.FASTEST_GROWTH)

    assert result.unit == "posts/day"
    assert result.total == 4
    assert result.eligible_count == 3
    assert [item.name for item in result.items] == ["Fast", "Flat", "Falling", "One"]
    assert [item.value for item in result.items[:3]] == [400.0, 0.0, -100.0]
    assert result.items[0].provenance is MetricProvenance.ESTIMATED
    assert result.items[1].provenance is MetricProvenance.OBSERVED
    assert isinstance(result.items[3], RankingIneligibleRecord)
    assert result.items[3].reason is RankingIneligibleReason.INSUFFICIENT_HISTORY
    assert not hasattr(result.items[3], "value")


def test_relative_growth_uses_full_precision_and_rejects_zero_baseline() -> None:
    quicker = booru("Quicker", 20)
    slower = booru("Slower", 21)
    falling = booru("Falling", 22)
    zero = booru("Zero", 23)

    def pair(owner: Booru, previous: int, current: int, hours: int) -> list[tuple[Any, ...]]:
        return [
            (owner, snapshot(owner, owner.id.int * 10 + 2, metrics=total_metric(current)), 1),
            (
                owner,
                snapshot(
                    owner,
                    owner.id.int * 10 + 1,
                    metrics=total_metric(previous),
                    captured_at=NOW - timedelta(hours=hours),
                ),
                2,
            ),
        ]

    rows = [
        *pair(quicker, 100, 110, 12),
        *pair(slower, 1_000, 1_100, 24),
        *pair(falling, 1_000, 900, 24),
        *pair(zero, 0, 10, 24),
    ]

    result, _ = run_ranking(rows, mode=RankingMode.RELATIVE_GROWTH)

    assert result.unit == "percent/day"
    assert result.eligible_count == 3
    assert [item.name for item in result.items] == [
        "Quicker",
        "Slower",
        "Falling",
        "Zero",
    ]
    assert [item.value for item in result.items[:3]] == pytest.approx([20.0, 10.0, -10.0])
    assert result.items[3].reason is RankingIneligibleReason.ZERO_BASELINE


@pytest.mark.parametrize(
    ("current_metrics", "previous_metrics", "expected_reason"),
    [
        ({}, total_metric(100), RankingIneligibleReason.MISSING_TOTAL_POSTS),
        (
            total_metric(True),
            total_metric(100),
            RankingIneligibleReason.INVALID_TOTAL_POSTS,
        ),
        (
            total_metric(110, unit="images"),
            total_metric(100),
            RankingIneligibleReason.INCOMPATIBLE_UNIT,
        ),
        (
            total_metric(110, provenance="observed"),
            total_metric(100, provenance="estimated"),
            RankingIneligibleReason.INCOMPATIBLE_PROVENANCE,
        ),
    ],
)
def test_growth_validation_returns_stable_reasons_without_parsing_exceptions(
    current_metrics: object,
    previous_metrics: object,
    expected_reason: RankingIneligibleReason,
) -> None:
    owner = booru("Invalid", 30)
    rows = [
        (owner, snapshot(owner, 302, metrics=current_metrics), 1),
        (
            owner,
            snapshot(
                owner,
                301,
                metrics=previous_metrics,
                captured_at=NOW - timedelta(days=1),
            ),
            2,
        ),
    ]

    result, _ = run_ranking(rows, mode=RankingMode.FASTEST_GROWTH)

    assert result.eligible_count == 0
    assert result.items[0].reason is expected_reason


def test_growth_invalid_interval_is_explicit() -> None:
    owner = booru("Bad Time", 40)
    rows = [
        (owner, snapshot(owner, 402, metrics=total_metric(110)), 1),
        (owner, snapshot(owner, 401, metrics=total_metric(100)), 2),
    ]

    result, _ = run_ranking(rows, mode=RankingMode.FASTEST_GROWTH)

    assert result.items[0].reason is RankingIneligibleReason.INVALID_TIME_INTERVAL


def test_single_snapshot_is_largest_eligible_but_growth_ineligible() -> None:
    owner = booru("New", 50)
    rows = [(owner, snapshot(owner, 501, metrics=total_metric(42)), 1)]

    largest, _ = run_ranking(rows, mode=RankingMode.LARGEST)
    growth, _ = run_ranking(rows, mode=RankingMode.FASTEST_GROWTH)

    assert largest.eligible_count == 1
    assert largest.items[0].value == 42
    assert largest.items[0].provenance is MetricProvenance.OBSERVED
    assert growth.eligible_count == 0
    assert growth.items[0].reason is RankingIneligibleReason.INSUFFICIENT_HISTORY


def test_newest_incompatible_pair_never_falls_back_to_older_history() -> None:
    owner = booru("No Cherry Picking", 60)
    rows = [
        (
            owner,
            snapshot(owner, 603, metrics=total_metric(1_200, provenance="observed")),
            1,
        ),
        (
            owner,
            snapshot(
                owner,
                602,
                metrics=total_metric(1_100, provenance="estimated"),
                captured_at=NOW - timedelta(days=1),
            ),
            2,
        ),
        (
            owner,
            snapshot(
                owner,
                601,
                metrics=total_metric(1_000, provenance="observed"),
                captured_at=NOW - timedelta(days=2),
            ),
            3,
        ),
    ]

    result, _ = run_ranking(rows, mode=RankingMode.FASTEST_GROWTH)

    assert result.eligible_count == 0
    assert result.items[0].reason is RankingIneligibleReason.INCOMPATIBLE_PROVENANCE


def test_ineligible_sources_sort_by_reason_name_and_uuid() -> None:
    zulu = booru("Zulu", 72)
    alpha_high = booru("alpha", 73)
    alpha_low = booru("Alpha", 71)
    malformed = booru("Malformed", 70)
    rows = [
        (zulu, None, None),
        (alpha_high, None, None),
        (malformed, snapshot(malformed, 701, metrics=total_metric("bad")), 1),
        (alpha_low, None, None),
    ]

    result, _ = run_ranking(rows, mode=RankingMode.LARGEST)

    assert result.total == 4
    assert result.eligible_count == 0
    assert [(item.reason.value, item.name, item.booru_id) for item in result.items] == [
        ("invalid_total_posts", "Malformed", malformed.id),
        ("missing_total_posts", "Alpha", alpha_low.id),
        ("missing_total_posts", "alpha", alpha_high.id),
        ("missing_total_posts", "Zulu", zulu.id),
    ]
