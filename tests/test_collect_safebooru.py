import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from io import StringIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from booruradar.adapters.gelbooru import GelbooruAdapter
from booruradar.collect import run_collection
from booruradar.core.enums import AdapterFamily, CrawlRunStatus, MetricProvenance
from booruradar.models import Booru, BooruSnapshot, CrawlRun
from booruradar.services.quality import (
    GELBOORU_SNAPSHOT_POLICY,
    SuspiciousObservationError,
)
from booruradar.services.snapshot_collection import SnapshotCollectionResult
from booruradar.targets import get_collection_target


@asynccontextmanager
async def _acquired_collection_lock(_engine, _target_key):
    yield True


@pytest.fixture(autouse=True)
def acquire_collection_lock_for_cli_unit_tests():
    with patch("booruradar.collect.collection_lock", _acquired_collection_lock):
        yield


SAFEBOORU_URL = "https://safebooru.org"


def make_booru() -> Booru:
    return Booru(
        id=uuid.uuid4(),
        name="Safebooru",
        canonical_url=SAFEBOORU_URL,
        adapter_family=AdapterFamily.GELBOORU.value,
        adapter_name=GelbooruAdapter.adapter_name,
    )


def make_snapshot(
    booru_id: uuid.UUID,
    *,
    captured_at: datetime | None = None,
    total_posts: int = 12_345_678,
) -> BooruSnapshot:
    return BooruSnapshot(
        id=uuid.uuid4(),
        booru_id=booru_id,
        crawl_run_id=uuid.uuid4(),
        captured_at=captured_at or datetime.now(UTC),
        health_status="ok",
        health_provenance=MetricProvenance.OBSERVED.value,
        capabilities=[],
        capabilities_provenance=MetricProvenance.OBSERVED.value,
        metrics={
            "total_posts": {
                "value": total_posts,
                "provenance": MetricProvenance.OBSERVED.value,
                "unit": "posts",
            }
        },
        source_url=(
            f"{SAFEBOORU_URL}/index.php?page=dapi&s=post&q=index"
        ),
    )


def make_result(booru: Booru) -> SnapshotCollectionResult:
    snapshot = make_snapshot(booru.id)
    return SnapshotCollectionResult(
        crawl_run=CrawlRun(
            id=snapshot.crawl_run_id,
            booru_id=booru.id,
            adapter_name=GelbooruAdapter.adapter_name,
            status=CrawlRunStatus.SUCCEEDED,
            started_at=datetime.now(UTC),
            details={},
        ),
        snapshot=snapshot,
    )


class FakeEngine:
    def __init__(self) -> None:
        self.disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class FakeSessionContextManager:
    def __init__(
        self,
        *,
        booru: Booru | None,
        latest_snapshot: BooruSnapshot | None,
    ) -> None:
        self.booru = booru
        self.latest_snapshot = latest_snapshot
        self.scalar_statements = []
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def add(self, instance) -> None:
        self.added.append(instance)

    async def commit(self) -> None:
        return None

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        statement_text = str(statement)
        if "FROM boorus" in statement_text:
            return self.booru
        if "FROM booru_snapshots" in statement_text:
            return self.latest_snapshot
        raise AssertionError(f"unexpected scalar query: {statement_text}")


def test_safebooru_target_has_canonical_gelbooru_observed_configuration():
    target = get_collection_target("SAFEBOORU")

    assert target is not None
    assert target.key == "safebooru"
    assert target.name == "Safebooru"
    assert target.canonical_url == SAFEBOORU_URL
    assert target.adapter_family is AdapterFamily.GELBOORU
    assert target.adapter_name == GelbooruAdapter.adapter_name
    assert target.adapter_type is GelbooruAdapter
    assert target.policy is GELBOORU_SNAPSHOT_POLICY
    assert target.policy.total_posts_provenance is MetricProvenance.OBSERVED


def test_safebooru_cli_uses_canonical_adapter_and_observed_policy():
    booru = make_booru()
    session = FakeSessionContextManager(booru=booru, latest_snapshot=None)
    engine = FakeEngine()
    service = MagicMock()
    service.collect = AsyncMock(return_value=make_result(booru))
    client = MagicMock(name="http_client")

    with (
        patch("booruradar.collect.AsyncSession", return_value=session),
        patch("booruradar.collect.create_async_engine", return_value=engine),
        patch("booruradar.collect.httpx.AsyncClient") as client_class,
        patch("booruradar.collect.SnapshotCollectionService", return_value=service) as service_class,
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        client_class.return_value.__aenter__.return_value = client

        asyncio.run(run_collection(["safebooru"]))

    service_class.assert_called_once_with(policy=GELBOORU_SNAPSHOT_POLICY)
    service.collect.assert_awaited_once()
    session_arg, booru_arg, adapter_arg = service.collect.await_args.args
    assert session_arg is session
    assert booru_arg is booru
    assert isinstance(adapter_arg, GelbooruAdapter)
    assert adapter_arg.base_url == SAFEBOORU_URL
    assert adapter_arg.client is client
    assert "TARGET=safebooru" in stdout.getvalue().splitlines()
    assert "PROVENANCE=observed" in stdout.getvalue().splitlines()
    assert engine.disposed is True


def test_recent_safebooru_snapshot_query_is_scoped_and_skips_all_collection_io():
    booru = make_booru()
    recent_snapshot = make_snapshot(
        booru.id,
        captured_at=datetime.now(UTC) - timedelta(hours=1),
    )
    session = FakeSessionContextManager(
        booru=booru,
        latest_snapshot=recent_snapshot,
    )

    with (
        patch("booruradar.collect.AsyncSession", return_value=session),
        patch("booruradar.collect.create_async_engine", return_value=FakeEngine()),
        patch("booruradar.collect.httpx.AsyncClient") as client_class,
        patch("booruradar.collect.SnapshotCollectionService") as service_class,
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(run_collection(["safebooru"]))

    assert exc_info.value.code == 0
    snapshot_queries = [
        statement
        for statement in session.scalar_statements
        if "FROM booru_snapshots" in str(statement)
    ]
    assert len(snapshot_queries) == 1
    snapshot_query = snapshot_queries[0]
    assert "booru_snapshots.booru_id =" in str(snapshot_query)
    assert booru.id in snapshot_query.compile().params.values()
    client_class.assert_not_called()
    service_class.assert_not_called()
    assert stdout.getvalue().splitlines()[:3] == [
        "COLLECTION=SKIPPED",
        "TARGET=safebooru",
        "REASON=minimum_interval",
    ]


def test_safebooru_force_bypasses_interval_but_not_quality_failure():
    booru = make_booru()
    recent_snapshot = make_snapshot(
        booru.id,
        captured_at=datetime.now(UTC) - timedelta(hours=1),
    )
    session = FakeSessionContextManager(
        booru=booru,
        latest_snapshot=recent_snapshot,
    )
    service = MagicMock()
    service.collect = AsyncMock(
        side_effect=SuspiciousObservationError(("total_posts_catastrophic_drop",))
    )

    with (
        patch("booruradar.collect.AsyncSession", return_value=session),
        patch("booruradar.collect.create_async_engine", return_value=FakeEngine()),
        patch("booruradar.collect.httpx.AsyncClient"),
        patch("booruradar.collect.SnapshotCollectionService", return_value=service) as service_class,
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(run_collection(["safebooru", "--force"]))

    assert exc_info.value.code == 1
    service_class.assert_called_once_with(policy=GELBOORU_SNAPSHOT_POLICY)
    service.collect.assert_awaited_once()
    output = stdout.getvalue().splitlines()
    assert "COLLECTION=FAILED" in output
    assert "TARGET=safebooru" in output
    assert any("SuspiciousObservationError" in line for line in output)
    assert "COLLECTION=SKIPPED" not in output


def test_safebooru_failure_output_never_echoes_raw_or_media_data():
    booru = make_booru()
    session = FakeSessionContextManager(booru=booru, latest_snapshot=None)
    service = MagicMock()
    service.collect = AsyncMock(
        side_effect=RuntimeError(
            '{"file_url":"https://safebooru.org/images/secret.jpg",'
            '"media":"raw response bytes"}'
        )
    )

    with (
        patch("booruradar.collect.AsyncSession", return_value=session),
        patch("booruradar.collect.create_async_engine", return_value=FakeEngine()),
        patch("booruradar.collect.httpx.AsyncClient"),
        patch("booruradar.collect.SnapshotCollectionService", return_value=service),
        patch("sys.stdout", new_callable=StringIO) as stdout,
    ):
        with pytest.raises(SystemExit) as exc_info:
            asyncio.run(run_collection(["safebooru"]))

    assert exc_info.value.code == 1
    output = stdout.getvalue().lower()
    assert "collection=failed" in output
    assert "target=safebooru" in output
    assert "file_url" not in output
    assert "media" not in output
    assert "raw response" not in output
    assert "secret.jpg" not in output
    assert "https://" not in output
