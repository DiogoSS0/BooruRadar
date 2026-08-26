import asyncio
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from booruradar.adapters.danbooru import DanbooruAdapter, DanbooruResponseError
from booruradar.core.enums import AdapterFamily, CrawlRunStatus
from booruradar.models import Booru, BooruSnapshot, CrawlRun, Tag, TagSnapshot
from booruradar.services import (
    DanbooruSnapshotCollectionService,
    SuspiciousObservationError,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("BOORURADAR_RUN_POSTGRES_TESTS") != "1",
    reason="PostgreSQL integration tests require BOORURADAR_RUN_POSTGRES_TESTS=1",
)

FIXTURES = Path(__file__).parent / "fixtures"
POSTS = json.loads((FIXTURES / "danbooru_posts.json").read_text(encoding="utf-8"))

def transport_for_count(total_posts: object) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/posts.json":
            return httpx.Response(200, json=POSTS)
        if request.url.path == "/counts/posts.json":
            return httpx.Response(200, json={"counts": {"posts": total_posts}})
        raise AssertionError(f"unexpected request path: {request.url.path}")

    return httpx.MockTransport(handler)

def run(awaitable):
    return asyncio.run(awaitable)

async def clean_database(engine):
    async with engine.begin() as conn:
        await conn.execute(delete(TagSnapshot))
        await conn.execute(delete(Tag))
        await conn.execute(delete(BooruSnapshot))
        await conn.execute(delete(CrawlRun))
        await conn.execute(delete(Booru))

def make_booru() -> Booru:
    return Booru(
        id=uuid.uuid4(),
        name="Danbooru Integration",
        canonical_url="https://danbooru.test",
        adapter_family=AdapterFamily.DANBOORU.value,
        adapter_name="danbooru",
    )

def test_scenario_1_success():
    async def exercise():
        db_url = os.environ.get("BOORURADAR_DATABASE_URL", "postgresql+psycopg:///booruradar_integration")
        engine = create_async_engine(db_url)
        await clean_database(engine)
        
        test_booru_id = uuid.uuid4()
        test_booru = Booru(
            id=test_booru_id,
            name="Danbooru Integration",
            canonical_url="https://danbooru.test",
            adapter_family=AdapterFamily.DANBOORU.value,
            adapter_name="danbooru",
        )
        
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(test_booru)
            await session.commit()
            
        async with AsyncSession(engine, expire_on_commit=False) as session:
            booru = await session.get(Booru, test_booru_id)
            async with httpx.AsyncClient(transport=transport_for_count(12022661)) as client:
                await DanbooruSnapshotCollectionService().collect(
                    session,
                    booru,
                    DanbooruAdapter("https://danbooru.test", client),
                )
        
        # Verify physically from PostgreSQL after commit
        async with AsyncSession(engine) as session:
            crawl_runs = (await session.execute(select(CrawlRun))).scalars().all()
            assert len(crawl_runs) == 1
            run_rec = crawl_runs[0]
            assert run_rec.status == CrawlRunStatus.SUCCEEDED
            
            snapshots = (await session.execute(select(BooruSnapshot))).scalars().all()
            assert len(snapshots) == 1
            snap = snapshots[0]
            
            assert "total_posts" in snap.metrics
            assert snap.metrics["total_posts"]["provenance"] == "estimated"
            assert snap.metrics["total_posts"]["unit"] == "posts"
            
            # Verify CrawlRun.details survived serialization
            details = run_rec.details
            assert "quality_status" in details
            assert "source_endpoints" in details
            assert isinstance(details.get("responses"), list)
            assert len(details["responses"]) > 0
            assert "response_sha256" in details["responses"][0]
            
            # Verify no complete raw response body is persisted
            details_json = json.dumps(details)
            assert "cdn.example.invalid" not in details_json
            assert "file_url" not in details_json
            
        await engine.dispose()
    run(exercise())

def test_scenario_2_hard_invalid():
    async def exercise():
        db_url = os.environ.get("BOORURADAR_DATABASE_URL", "postgresql+psycopg:///booruradar_integration")
        engine = create_async_engine(db_url)
        await clean_database(engine)
        
        test_booru_id = uuid.uuid4()
        test_booru = Booru(
            id=test_booru_id,
            name="Danbooru Integration",
            canonical_url="https://danbooru.test",
            adapter_family=AdapterFamily.DANBOORU.value,
            adapter_name="danbooru",
        )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(test_booru)
            await session.commit()
            
        async with AsyncSession(engine, expire_on_commit=False) as session:
            booru = await session.get(Booru, test_booru_id)
            async with httpx.AsyncClient(transport=transport_for_count(-1)) as client:
                with pytest.raises(DanbooruResponseError):
                    await DanbooruSnapshotCollectionService().collect(
                        session,
                        booru,
                        DanbooruAdapter("https://danbooru.test", client),
                    )
        
        async with AsyncSession(engine) as session:
            crawl_runs = (await session.execute(select(CrawlRun))).scalars().all()
            assert len(crawl_runs) == 1
            run_rec = crawl_runs[0]
            assert run_rec.status == CrawlRunStatus.FAILED
            assert run_rec.details["quality_status"] == "hard_invalid"
            
            snapshots = (await session.execute(select(BooruSnapshot))).scalars().all()
            assert len(snapshots) == 0
            
        await engine.dispose()
    run(exercise())

def test_scenario_3_suspicious():
    async def exercise():
        db_url = os.environ.get("BOORURADAR_DATABASE_URL", "postgresql+psycopg:///booruradar_integration")
        engine = create_async_engine(db_url)
        await clean_database(engine)
        
        test_booru_id = uuid.uuid4()
        test_booru = Booru(
            id=test_booru_id,
            name="Danbooru Integration",
            canonical_url="https://danbooru.test",
            adapter_family=AdapterFamily.DANBOORU.value,
            adapter_name="danbooru",
        )
        async with AsyncSession(engine, expire_on_commit=False) as session:
            session.add(test_booru)
            # Create a previous valid snapshot to trigger SuspiciousObservationError
            dummy_run_id = uuid.uuid4()
            dummy_run = CrawlRun(
                id=dummy_run_id,
                booru_id=test_booru_id,
                adapter_name="danbooru",
                started_at=datetime.now(UTC),
                status=CrawlRunStatus.SUCCEEDED,
                details={}
            )
            snap = BooruSnapshot(
                id=uuid.uuid4(),
                booru_id=test_booru_id,
                captured_at=datetime.now(UTC),
                health_status="ok",
                health_provenance="observed",
                capabilities=[],
                capabilities_provenance="estimated",
                metrics={
                    "total_posts": {
                        "value": 12_000_000,
                        "provenance": "estimated",
                        "unit": "posts",
                    }
                },
                source_url="https://danbooru.test",
                crawl_run_id=dummy_run_id
            )
            session.add(dummy_run)
            session.add(snap)
            await session.commit()
            
        async with AsyncSession(engine, expire_on_commit=False) as session:
            booru = await session.get(Booru, test_booru_id)
            async with httpx.AsyncClient(transport=transport_for_count(1_000_000)) as client:
                with pytest.raises(SuspiciousObservationError):
                    await DanbooruSnapshotCollectionService().collect(
                        session,
                        booru,
                        DanbooruAdapter("https://danbooru.test", client),
                    )
        
        async with AsyncSession(engine) as session:
            crawl_runs = (await session.execute(select(CrawlRun))).scalars().all()
            assert len(crawl_runs) == 2 # 1 dummy, 1 failed
            failed_runs = [r for r in crawl_runs if r.status == CrawlRunStatus.FAILED]
            assert len(failed_runs) == 1
            assert failed_runs[0].details["quality_status"] == "suspicious"
            assert "health_status" not in failed_runs[0].details
            
            snapshots = (await session.execute(select(BooruSnapshot))).scalars().all()
            assert len(snapshots) == 1 # only the dummy remains
            assert snapshots[0].metrics["total_posts"]["value"] == 12_000_000
            
        await engine.dispose()
    run(exercise())
