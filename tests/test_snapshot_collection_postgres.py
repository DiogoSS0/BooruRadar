from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
from typing import Any
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from booruradar.adapters.danbooru import DanbooruAdapter, DanbooruResponseError
from booruradar.adapters.gelbooru import GelbooruAdapter
from booruradar.core.enums import AdapterFamily, CrawlRunStatus, MetricProvenance
from booruradar.models import Booru, BooruSnapshot, CrawlRun
from booruradar.services import (
    DanbooruSnapshotCollectionService,
    GELBOORU_SNAPSHOT_POLICY,
    collection_lock,
    HardInvalidObservationError,
    SnapshotCollectionService,
    SuspiciousObservationError,
)


pytestmark = pytest.mark.skipif(
    os.environ.get("BOORURADAR_RUN_POSTGRES_TESTS") != "1",
    reason="PostgreSQL integration tests require BOORURADAR_RUN_POSTGRES_TESTS=1",
)

DEFAULT_TEST_DATABASE_URL = "postgresql+psycopg:///booruradar_integration"
DANBOORU_BASE_URL = "https://danbooru.test"
GELBOORU_BASE_URL = "https://safebooru.test"

FIXTURES = Path(__file__).parent / "fixtures"
POSTS = json.loads((FIXTURES / "danbooru_posts.json").read_text(encoding="utf-8"))


def _assert_intended_test_database_name(name: str | None, *, source: str) -> str:
    if not name:
        raise RuntimeError(f"{source} did not identify a database")

    normalized = name.strip().lower()
    if normalized == "booruradar_history":
        raise RuntimeError("refusing to run tests against booruradar_history")
    if "history" in normalized or "prod" in normalized:
        raise RuntimeError(f"refusing {source} with a history/production-looking name")
    if "test" not in normalized and "integration" not in normalized:
        raise RuntimeError(f"{source} must name an explicit test/integration database")
    return normalized


def _configured_test_database() -> tuple[str, str]:
    database_url = os.environ.get("BOORURADAR_DATABASE_URL", DEFAULT_TEST_DATABASE_URL)
    parsed_url = make_url(database_url)
    if parsed_url.drivername != "postgresql+psycopg":
        raise RuntimeError("PostgreSQL tests require the postgresql+psycopg driver")
    database_name = _assert_intended_test_database_name(
        parsed_url.database,
        source="BOORURADAR_DATABASE_URL",
    )
    return database_url, database_name


@dataclass
class PostgresTestDatabase:
    url: str
    expected_name: str
    engine: AsyncEngine
    booru_ids: set[uuid.UUID] = field(default_factory=set)

    async def verify_current_database(self) -> None:
        async with self.engine.connect() as connection:
            resolved_name = await connection.scalar(text("SELECT current_database()"))
        normalized = _assert_intended_test_database_name(
            resolved_name,
            source="current_database()",
        )
        if normalized != self.expected_name:
            raise RuntimeError(
                "current_database() did not match BOORURADAR_DATABASE_URL"
            )

    def make_booru(self, family: AdapterFamily, *, adapter_name: str) -> Booru:
        booru_id = uuid.uuid4()
        self.booru_ids.add(booru_id)
        return Booru(
            id=booru_id,
            name=f"{family.value.title()} PostgreSQL Integration",
            canonical_url=f"https://{adapter_name}-{booru_id}.integration.test",
            adapter_family=family.value,
            adapter_name=adapter_name,
        )

    async def cleanup(self) -> None:
        if not self.booru_ids:
            return

        # Resolve and validate again immediately before the only cleanup DML.
        await self.verify_current_database()
        async with self.engine.begin() as connection:
            await connection.execute(
                delete(Booru).where(Booru.id.in_(tuple(self.booru_ids)))
            )


@asynccontextmanager
async def postgres_test_database() -> AsyncIterator[PostgresTestDatabase]:
    database_url, expected_name = _configured_test_database()
    database = PostgresTestDatabase(
        url=database_url,
        expected_name=expected_name,
        engine=create_async_engine(database_url),
    )
    verified = False
    try:
        # This read-only check must succeed before a test can issue any DML.
        await database.verify_current_database()
        verified = True
        yield database
    finally:
        try:
            if verified:
                await database.cleanup()
        finally:
            await database.engine.dispose()


class EstimatedTotalPostsGelbooruAdapter(GelbooruAdapter):
    async def fetch_public_statistics(self):
        statistics = await super().fetch_public_statistics()
        metric = statistics.metrics["total_posts"].model_copy(
            update={"provenance": MetricProvenance.ESTIMATED}
        )
        return statistics.model_copy(update={"metrics": {"total_posts": metric}})


class OverlongHealthGelbooruAdapter(GelbooruAdapter):
    async def health_check(self):
        health = await super().health_check()
        return health.model_copy(update={"status": "x" * 51})


def transport_for_count(total_posts: object) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/posts.json":
            return httpx.Response(200, json=POSTS)
        if request.url.path == "/counts/posts.json":
            return httpx.Response(200, json={"counts": {"posts": total_posts}})
        raise AssertionError(f"unexpected request path: {request.url.path}")

    return httpx.MockTransport(handler)


def gelbooru_transport(
    total_posts: int,
    *,
    before_response: Callable[[httpx.Request], None] | None = None,
) -> httpx.MockTransport:
    content = (
        f'<posts count="{total_posts}"><post id="1" change="123" rating="s" '
        'tags="cat" file_url="https://cdn.example.invalid/private.jpg" /></posts>'
    ).encode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/index.php"
        if before_response is not None:
            before_response(request)
        return httpx.Response(
            200,
            content=content,
            headers={"content-type": "text/xml"},
        )

    return httpx.MockTransport(handler)


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


async def persist_booru(database: PostgresTestDatabase, booru: Booru) -> None:
    async with AsyncSession(database.engine, expire_on_commit=False) as session:
        session.add(booru)
        await session.commit()


async def persist_previous_snapshot(
    database: PostgresTestDatabase,
    booru: Booru,
    *,
    total_posts: int,
    provenance: MetricProvenance,
) -> None:
    crawl_run_id = uuid.uuid4()
    captured_at = datetime.now(UTC)
    async with AsyncSession(database.engine, expire_on_commit=False) as session:
        session.add(booru)
        session.add(
            CrawlRun(
                id=crawl_run_id,
                booru_id=booru.id,
                adapter_name=booru.adapter_name or booru.adapter_family,
                started_at=captured_at,
                finished_at=captured_at,
                status=CrawlRunStatus.SUCCEEDED,
                details={"quality_status": "accepted"},
            )
        )
        session.add(
            BooruSnapshot(
                id=uuid.uuid4(),
                booru_id=booru.id,
                crawl_run_id=crawl_run_id,
                captured_at=captured_at,
                health_status="ok",
                health_provenance=MetricProvenance.OBSERVED,
                capabilities=[],
                capabilities_provenance=MetricProvenance.OBSERVED,
                metrics={
                    "total_posts": {
                        "value": total_posts,
                        "provenance": provenance.value,
                        "unit": "posts",
                    }
                },
                source_url=booru.canonical_url,
            )
        )
        await session.commit()


async def records_for_booru(
    database: PostgresTestDatabase,
    booru_id: uuid.UUID,
) -> tuple[list[CrawlRun], list[BooruSnapshot]]:
    async with AsyncSession(database.engine) as session:
        crawl_runs = (
            await session.execute(
                select(CrawlRun)
                .where(CrawlRun.booru_id == booru_id)
                .order_by(CrawlRun.started_at, CrawlRun.id)
            )
        ).scalars().all()
        snapshots = (
            await session.execute(
                select(BooruSnapshot)
                .where(BooruSnapshot.booru_id == booru_id)
                .order_by(BooruSnapshot.captured_at, BooruSnapshot.id)
            )
        ).scalars().all()
    return list(crawl_runs), list(snapshots)


def _assert_safe_response_evidence(details: dict[str, object]) -> None:
    assert details["source_endpoints"] == ["recent_posts", "total_posts"]
    responses = details["responses"]
    assert isinstance(responses, list)
    assert responses
    assert all(item["http_status"] == 200 for item in responses)
    assert all(len(item["response_sha256"]) == 64 for item in responses)
    serialized = json.dumps(details)
    assert "cdn.example.invalid" not in serialized
    assert "file_url" not in serialized


@pytest.mark.parametrize(
    "name",
    [
        "booruradar_history",
        "booruradar_integration_history",
        "booruradar_production",
        "booruradar_prod",
        "booruradarprod_test",
        "booruradar",
    ],
)
def test_database_name_guard_rejects_unsafe_names(name: str) -> None:
    with pytest.raises(RuntimeError):
        _assert_intended_test_database_name(name, source="test")


@pytest.mark.parametrize("name", ["booruradar_test", "booruradar_integration"])
def test_database_name_guard_accepts_explicit_test_names(name: str) -> None:
    assert _assert_intended_test_database_name(name, source="test") == name


def test_scenario_1_success() -> None:
    async def exercise() -> None:
        async with postgres_test_database() as database:
            test_booru = database.make_booru(
                AdapterFamily.DANBOORU,
                adapter_name="danbooru",
            )
            await persist_booru(database, test_booru)

            async with AsyncSession(database.engine, expire_on_commit=False) as session:
                booru = await session.get(Booru, test_booru.id)
                assert booru is not None
                async with httpx.AsyncClient(
                    transport=transport_for_count(12_022_661)
                ) as client:
                    await DanbooruSnapshotCollectionService().collect(
                        session,
                        booru,
                        DanbooruAdapter(DANBOORU_BASE_URL, client),
                    )

            crawl_runs, snapshots = await records_for_booru(database, test_booru.id)
            assert len(crawl_runs) == 1
            run_rec = crawl_runs[0]
            assert run_rec.status is CrawlRunStatus.SUCCEEDED

            assert len(snapshots) == 1
            snapshot = snapshots[0]
            assert snapshot.crawl_run_id == run_rec.id
            assert snapshot.metrics["total_posts"] == {
                "value": 12_022_661,
                "provenance": "estimated",
                "unit": "posts",
            }

            assert run_rec.details["quality_status"] == "accepted"
            _assert_safe_response_evidence(run_rec.details)

    run(exercise())


def test_scenario_2_hard_invalid() -> None:
    async def exercise() -> None:
        async with postgres_test_database() as database:
            test_booru = database.make_booru(
                AdapterFamily.DANBOORU,
                adapter_name="danbooru",
            )
            await persist_booru(database, test_booru)

            async with AsyncSession(database.engine, expire_on_commit=False) as session:
                booru = await session.get(Booru, test_booru.id)
                assert booru is not None
                async with httpx.AsyncClient(transport=transport_for_count(-1)) as client:
                    with pytest.raises(DanbooruResponseError):
                        await DanbooruSnapshotCollectionService().collect(
                            session,
                            booru,
                            DanbooruAdapter(DANBOORU_BASE_URL, client),
                        )

            crawl_runs, snapshots = await records_for_booru(database, test_booru.id)
            assert len(crawl_runs) == 1
            assert crawl_runs[0].status is CrawlRunStatus.FAILED
            assert crawl_runs[0].details["quality_status"] == "hard_invalid"
            assert snapshots == []

    run(exercise())


def test_scenario_3_suspicious() -> None:
    async def exercise() -> None:
        async with postgres_test_database() as database:
            test_booru = database.make_booru(
                AdapterFamily.DANBOORU,
                adapter_name="danbooru",
            )
            await persist_previous_snapshot(
                database,
                test_booru,
                total_posts=12_000_000,
                provenance=MetricProvenance.ESTIMATED,
            )

            async with AsyncSession(database.engine, expire_on_commit=False) as session:
                booru = await session.get(Booru, test_booru.id)
                assert booru is not None
                async with httpx.AsyncClient(
                    transport=transport_for_count(1_000_000)
                ) as client:
                    with pytest.raises(SuspiciousObservationError):
                        await DanbooruSnapshotCollectionService().collect(
                            session,
                            booru,
                            DanbooruAdapter(DANBOORU_BASE_URL, client),
                        )

            crawl_runs, snapshots = await records_for_booru(database, test_booru.id)
            failed_runs = [
                item for item in crawl_runs if item.status is CrawlRunStatus.FAILED
            ]
            assert len(crawl_runs) == 2
            assert len(failed_runs) == 1
            assert failed_runs[0].details["quality_status"] == "suspicious"
            assert "health_status" not in failed_runs[0].details
            assert len(snapshots) == 1
            assert snapshots[0].metrics["total_posts"]["value"] == 12_000_000

    run(exercise())


def test_transaction_verification() -> None:
    async def exercise() -> None:
        async with postgres_test_database() as database:
            test_booru = database.make_booru(
                AdapterFamily.DANBOORU,
                adapter_name="danbooru",
            )
            await persist_booru(database, test_booru)
            visible_statuses: list[str] = []
            sync_engine = create_engine(database.url)

            def handler(request: httpx.Request) -> httpx.Response:
                with sync_engine.connect() as connection:
                    statuses = connection.execute(
                        text(
                            "SELECT status FROM crawl_runs "
                            "WHERE booru_id = :booru_id"
                        ),
                        {"booru_id": test_booru.id},
                    ).scalars().all()
                assert statuses == [CrawlRunStatus.RUNNING.value]
                visible_statuses.extend(statuses)

                if request.url.path == "/counts/posts.json":
                    return httpx.Response(500, text="Internal Server Error")
                if request.url.path == "/posts.json":
                    return httpx.Response(200, json=POSTS)
                raise AssertionError(f"unexpected request path: {request.url.path}")

            try:
                async with AsyncSession(database.engine, expire_on_commit=False) as session:
                    booru = await session.get(Booru, test_booru.id)
                    assert booru is not None
                    async with httpx.AsyncClient(
                        transport=httpx.MockTransport(handler)
                    ) as client:
                        with pytest.raises(httpx.HTTPError):
                            await DanbooruSnapshotCollectionService().collect(
                                session,
                                booru,
                                DanbooruAdapter(DANBOORU_BASE_URL, client),
                            )
            finally:
                sync_engine.dispose()

            assert visible_statuses
            crawl_runs, snapshots = await records_for_booru(database, test_booru.id)
            assert len(crawl_runs) == 1
            assert crawl_runs[0].status is CrawlRunStatus.FAILED
            assert snapshots == []

    run(exercise())


def test_gelbooru_observed_success_evidence_and_atomic_visibility() -> None:
    async def exercise() -> None:
        async with postgres_test_database() as database:
            test_booru = database.make_booru(
                AdapterFamily.GELBOORU,
                adapter_name="gelbooru",
            )
            await persist_booru(database, test_booru)
            visible_statuses: list[str] = []
            sync_engine = create_engine(database.url)

            def assert_running_is_visible(_request: httpx.Request) -> None:
                with sync_engine.connect() as connection:
                    statuses = connection.execute(
                        text(
                            "SELECT status FROM crawl_runs "
                            "WHERE booru_id = :booru_id"
                        ),
                        {"booru_id": test_booru.id},
                    ).scalars().all()
                assert statuses == [CrawlRunStatus.RUNNING.value]
                visible_statuses.extend(statuses)

            try:
                async with AsyncSession(database.engine, expire_on_commit=False) as session:
                    booru = await session.get(Booru, test_booru.id)
                    assert booru is not None
                    async with httpx.AsyncClient(
                        transport=gelbooru_transport(
                            6_852_898,
                            before_response=assert_running_is_visible,
                        )
                    ) as client:
                        await SnapshotCollectionService(
                            policy=GELBOORU_SNAPSHOT_POLICY
                        ).collect(
                            session,
                            booru,
                            GelbooruAdapter(GELBOORU_BASE_URL, client),
                        )
            finally:
                sync_engine.dispose()

            assert visible_statuses == [CrawlRunStatus.RUNNING.value] * 3
            crawl_runs, snapshots = await records_for_booru(database, test_booru.id)
            assert len(crawl_runs) == 1
            run_rec = crawl_runs[0]
            assert run_rec.status is CrawlRunStatus.SUCCEEDED
            assert run_rec.details["quality_status"] == "accepted"
            assert run_rec.details["quality_flags"] == []
            _assert_safe_response_evidence(run_rec.details)

            assert len(snapshots) == 1
            snapshot = snapshots[0]
            assert snapshot.crawl_run_id == run_rec.id
            assert snapshot.metrics["total_posts"] == {
                "value": 6_852_898,
                "provenance": "observed",
                "unit": "posts",
            }
            assert snapshot.source_url == (
                "https://safebooru.test/index.php?page=dapi&s=post&q=index&limit=1"
            )
            persisted = json.dumps(
                {
                    "details": run_rec.details,
                    "metrics": snapshot.metrics,
                    "source_url": snapshot.source_url,
                }
            )
            assert "file_url" not in persisted
            assert "cdn.example.invalid" not in persisted

    run(exercise())


def test_gelbooru_wrong_provenance_is_hard_invalid_without_snapshot() -> None:
    async def exercise() -> None:
        async with postgres_test_database() as database:
            test_booru = database.make_booru(
                AdapterFamily.GELBOORU,
                adapter_name="gelbooru",
            )
            await persist_booru(database, test_booru)

            async with AsyncSession(database.engine, expire_on_commit=False) as session:
                booru = await session.get(Booru, test_booru.id)
                assert booru is not None
                async with httpx.AsyncClient(
                    transport=gelbooru_transport(6_852_898)
                ) as client:
                    with pytest.raises(HardInvalidObservationError, match="observed"):
                        await SnapshotCollectionService(
                            policy=GELBOORU_SNAPSHOT_POLICY
                        ).collect(
                            session,
                            booru,
                            EstimatedTotalPostsGelbooruAdapter(
                                GELBOORU_BASE_URL,
                                client,
                            ),
                        )

            crawl_runs, snapshots = await records_for_booru(database, test_booru.id)
            assert len(crawl_runs) == 1
            failed_run = crawl_runs[0]
            assert failed_run.status is CrawlRunStatus.FAILED
            assert failed_run.details["quality_status"] == "hard_invalid"
            assert failed_run.details["quality_flags"] == ["hard_invalid"]
            _assert_safe_response_evidence(failed_run.details)
            assert snapshots == []

    run(exercise())


@pytest.mark.parametrize(
    ("previous_total", "candidate_total", "expected_flag"),
    [
        (6_852_898, 1_000_000, "total_posts_catastrophic_drop"),
        (1_000_000, 6_000_001, "total_posts_catastrophic_growth"),
    ],
    ids=["drop", "growth"],
)
def test_gelbooru_suspicious_change_is_blocked_without_snapshot(
    previous_total: int,
    candidate_total: int,
    expected_flag: str,
) -> None:
    async def exercise() -> None:
        async with postgres_test_database() as database:
            test_booru = database.make_booru(
                AdapterFamily.GELBOORU,
                adapter_name="gelbooru",
            )
            await persist_previous_snapshot(
                database,
                test_booru,
                total_posts=previous_total,
                provenance=MetricProvenance.OBSERVED,
            )

            async with AsyncSession(database.engine, expire_on_commit=False) as session:
                booru = await session.get(Booru, test_booru.id)
                assert booru is not None
                async with httpx.AsyncClient(
                    transport=gelbooru_transport(candidate_total)
                ) as client:
                    with pytest.raises(SuspiciousObservationError):
                        await SnapshotCollectionService(
                            policy=GELBOORU_SNAPSHOT_POLICY
                        ).collect(
                            session,
                            booru,
                            GelbooruAdapter(GELBOORU_BASE_URL, client),
                        )

            crawl_runs, snapshots = await records_for_booru(database, test_booru.id)
            failed_runs = [
                item for item in crawl_runs if item.status is CrawlRunStatus.FAILED
            ]
            assert len(crawl_runs) == 2
            assert len(failed_runs) == 1
            failed_run = failed_runs[0]
            assert failed_run.details["quality_status"] == "suspicious"
            assert failed_run.details["quality_flags"] == [expected_flag]
            _assert_safe_response_evidence(failed_run.details)
            assert len(snapshots) == 1
            assert snapshots[0].metrics["total_posts"]["value"] == previous_total

    run(exercise())


def test_gelbooru_snapshot_commit_failure_rolls_back_atomic_state_with_evidence() -> None:
    async def exercise() -> None:
        async with postgres_test_database() as database:
            test_booru = database.make_booru(
                AdapterFamily.GELBOORU,
                adapter_name="gelbooru",
            )
            await persist_booru(database, test_booru)

            async with AsyncSession(database.engine, expire_on_commit=False) as session:
                booru = await session.get(Booru, test_booru.id)
                assert booru is not None
                async with httpx.AsyncClient(
                    transport=gelbooru_transport(6_852_898)
                ) as client:
                    with pytest.raises(DataError):
                        await SnapshotCollectionService(
                            policy=GELBOORU_SNAPSHOT_POLICY
                        ).collect(
                            session,
                            booru,
                            OverlongHealthGelbooruAdapter(GELBOORU_BASE_URL, client),
                        )

            crawl_runs, snapshots = await records_for_booru(database, test_booru.id)
            assert len(crawl_runs) == 1
            failed_run = crawl_runs[0]
            assert failed_run.status is CrawlRunStatus.FAILED
            assert failed_run.finished_at is not None
            assert failed_run.error_message == "DataError: collection failed"
            assert failed_run.details["quality_status"] == "collection_failed"
            assert failed_run.details["quality_flags"] == ["unexpected_error"]
            _assert_safe_response_evidence(failed_run.details)
            assert snapshots == []

    run(exercise())


def test_target_scoped_advisory_lock_excludes_only_the_same_target() -> None:
    async def exercise() -> None:
        async with postgres_test_database() as database:
            async with collection_lock(database.engine, "danbooru") as first:
                assert first is True

                async with collection_lock(database.engine, "danbooru") as second:
                    assert second is False

                async with collection_lock(database.engine, "safebooru") as other:
                    assert other is True

            async with collection_lock(database.engine, "danbooru") as reacquired:
                assert reacquired is True

    run(exercise())
