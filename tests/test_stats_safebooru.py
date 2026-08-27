import asyncio
import uuid
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

import pytest

from booruradar.core.enums import AdapterFamily, MetricProvenance
from booruradar.models import Booru, BooruSnapshot
from booruradar.stats import run_stats


def make_booru() -> Booru:
    return Booru(
        id=uuid.uuid4(),
        name="Safebooru",
        canonical_url="https://safebooru.org",
        adapter_family=AdapterFamily.GELBOORU.value,
        adapter_name="gelbooru",
    )


def make_snapshot(
    booru_id: uuid.UUID,
    posts: int,
    captured_at: datetime,
    *,
    provenance: MetricProvenance,
) -> BooruSnapshot:
    return BooruSnapshot(
        id=uuid.uuid4(),
        booru_id=booru_id,
        crawl_run_id=uuid.uuid4(),
        captured_at=captured_at,
        health_status="ok",
        health_provenance=MetricProvenance.OBSERVED.value,
        capabilities=[],
        capabilities_provenance=MetricProvenance.OBSERVED.value,
        metrics={
            "total_posts": {
                "value": posts,
                "provenance": provenance.value,
                "unit": "posts",
            }
        },
        source_url=(
            "https://safebooru.org/index.php?page=dapi&s=post&q=index"
        ),
    )


class FakeEngine:
    async def dispose(self) -> None:
        return None


class ReadOnlySessionContextManager:
    def __init__(self, *, booru: Booru, snapshots: list[BooruSnapshot]) -> None:
        self.booru = booru
        self.snapshots = snapshots
        self.scalar_statements = []
        self.executed_statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def add(self, instance) -> None:
        raise AssertionError("stats must remain read-only: add() was called")

    async def commit(self) -> None:
        raise AssertionError("stats must remain read-only: commit() was called")

    async def flush(self) -> None:
        raise AssertionError("stats must remain read-only: flush() was called")

    async def rollback(self) -> None:
        raise AssertionError("stats must remain read-only: rollback() was called")

    async def delete(self, instance) -> None:
        raise AssertionError("stats must remain read-only: delete() was called")

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.booru

    async def execute(self, statement):
        self.executed_statements.append(statement)
        snapshots = self.snapshots

        class Result:
            def scalars(self):
                return self

            def all(self):
                return snapshots

        return Result()


def test_safebooru_observed_snapshots_produce_observed_stats_read_only():
    booru = make_booru()
    previous = make_snapshot(
        booru.id,
        20_000,
        datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        provenance=MetricProvenance.OBSERVED,
    )
    current = make_snapshot(
        booru.id,
        20_240,
        datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
        provenance=MetricProvenance.OBSERVED,
    )
    session = ReadOnlySessionContextManager(
        booru=booru,
        snapshots=[current, previous],
    )

    with (
        patch("booruradar.stats.AsyncSession", return_value=session),
        patch("booruradar.stats.create_async_engine", return_value=FakeEngine()),
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        asyncio.run(run_stats(["safebooru"]))

    output = stdout.getvalue().splitlines()
    assert "ANALYTICS=AVAILABLE" in output
    assert "TARGET=safebooru" in output
    assert "BOORU=Safebooru" in output
    assert "PREVIOUS_TOTAL_POSTS=20000" in output
    assert "CURRENT_TOTAL_POSTS=20240" in output
    assert "POSTS_DELTA=240" in output
    assert "POSTS_PER_DAY=240.0" in output
    assert "PROVENANCE=observed" in output

    assert len(session.executed_statements) == 1
    snapshot_query = session.executed_statements[0]
    assert "booru_snapshots.booru_id =" in str(snapshot_query)
    assert booru.id in snapshot_query.compile().params.values()


def test_safebooru_mixed_provenance_is_unavailable_and_read_only():
    booru = make_booru()
    previous = make_snapshot(
        booru.id,
        20_000,
        datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        provenance=MetricProvenance.OBSERVED,
    )
    current = make_snapshot(
        booru.id,
        20_240,
        datetime(2026, 1, 2, 12, 0, tzinfo=UTC),
        provenance=MetricProvenance.ESTIMATED,
    )
    session = ReadOnlySessionContextManager(
        booru=booru,
        snapshots=[current, previous],
    )

    with (
        patch("booruradar.stats.AsyncSession", return_value=session),
        patch("booruradar.stats.create_async_engine", return_value=FakeEngine()),
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(run_stats(["safebooru"]))

    assert exc_info.value.code == 0
    assert stdout.getvalue().splitlines() == [
        "ANALYTICS=UNAVAILABLE",
        "TARGET=safebooru",
        "REASON=IncompatibleSnapshotsError",
    ]
