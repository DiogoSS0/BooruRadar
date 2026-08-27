from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any
import uuid

import httpx
import pytest

from booruradar.adapters.base import BooruAdapter
from booruradar.adapters.danbooru import DanbooruAdapter, DanbooruResponseError
from booruradar.adapters.gelbooru import GelbooruAdapter, GelbooruResponseError
from booruradar.adapters.schemas import (
    AdapterCapability,
    CapabilityDiscovery,
    HealthCheck,
    PublicStatistics,
)
from booruradar.core.enums import AdapterFamily, CrawlRunStatus, MetricProvenance
from booruradar.models import Booru, BooruSnapshot, CrawlRun
from booruradar.models.metrics import MetricEnvelope
from booruradar.services import (
    BooruInspectionService,
    DanbooruSnapshotCollectionService,
    GELBOORU_SNAPSHOT_POLICY,
    HardInvalidObservationError,
    InspectionResult,
    SnapshotCollectionService,
    SuspiciousObservationError,
    TotalPostsAnomalyPolicy,
)


FIXTURES = Path(__file__).parent / "fixtures"
POSTS = json.loads((FIXTURES / "danbooru_posts.json").read_text(encoding="utf-8"))


class FakeAsyncSession:
    def __init__(self, previous_metrics: dict[str, object] | None = None) -> None:
        self.objects: list[object] = []
        self.previous_metrics = previous_metrics
        self.commits = 0
        self.gets = 0
        self.rollbacks = 0

    def add(self, instance: object) -> None:
        if instance not in self.objects:
            self.objects.append(instance)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def get(self, model: type[object], identity: uuid.UUID) -> object | None:
        self.gets += 1
        return next(
            (
                item
                for item in self.objects
                if isinstance(item, model) and getattr(item, "id", None) == identity
            ),
            None,
        )

    async def scalar(self, _statement: object) -> dict[str, object] | None:
        return self.previous_metrics


class FinalCommitFailureSession(FakeAsyncSession):
    async def commit(self) -> None:
        self.commits += 1
        if self.commits == 2:
            raise RuntimeError(
                "https://secret.test/?token=raw file_url=https://cdn.test/private.jpg"
            )

    async def rollback(self) -> None:
        await super().rollback()
        self.objects = [item for item in self.objects if not isinstance(item, BooruSnapshot)]
        crawl_run = next(item for item in self.objects if isinstance(item, CrawlRun))
        crawl_run.status = CrawlRunStatus.RUNNING
        crawl_run.finished_at = None
        crawl_run.error_message = None


class InvalidNormalizedInspectionService(BooruInspectionService):
    async def inspect(
        self,
        adapter: BooruAdapter,
        *,
        recent_post_limit: int = 50,
        tag_names: Sequence[str] | None = None,
    ) -> InspectionResult:
        now = datetime.now(UTC)
        return InspectionResult(
            health=HealthCheck(healthy=True, checked_at=now, status="ok"),
            capability_discovery=CapabilityDiscovery(
                capabilities=frozenset(AdapterCapability),
                discovered_at=now,
            ),
            public_statistics=PublicStatistics(
                collected_at=now,
                metrics={
                    "total_posts": MetricEnvelope(
                        value=12022661,
                        provenance=MetricProvenance.OBSERVED,
                        unit="posts",
                    )
                },
            ),
        )


def booru() -> Booru:
    return Booru(
        id=uuid.uuid4(),
        name="Danbooru",
        canonical_url="https://danbooru.test",
        adapter_family=AdapterFamily.DANBOORU.value,
        adapter_name="danbooru",
    )


def gelbooru() -> Booru:
    return Booru(
        id=uuid.uuid4(),
        name="Safebooru",
        canonical_url="https://safebooru.test",
        adapter_family=AdapterFamily.GELBOORU.value,
        adapter_name="gelbooru",
    )


def transport_for_count(total_posts: object) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/posts.json":
            return httpx.Response(200, json=POSTS)
        if request.url.path == "/counts/posts.json":
            return httpx.Response(200, json={"counts": {"posts": total_posts}})
        raise AssertionError(f"unexpected request path: {request.url.path}")

    return httpx.MockTransport(handler)


def gelbooru_transport(total_posts: int) -> httpx.MockTransport:
    content = (
        f'<posts count="{total_posts}"><post id="1" change="123" rating="s" '
        'tags="cat" file_url="https://cdn.example.invalid/private.jpg" /></posts>'
    ).encode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=content, headers={"content-type": "text/xml"})

    return httpx.MockTransport(handler)


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def test_successful_candidate_persists_snapshot_and_succeeds_crawl_run() -> None:
    async def exercise() -> None:
        session = FakeAsyncSession()
        async with httpx.AsyncClient(transport=transport_for_count(12022661)) as client:
            result = await DanbooruSnapshotCollectionService().collect(
                session,  # type: ignore[arg-type]
                booru(),
                DanbooruAdapter("https://danbooru.test", client),
            )

        snapshots = [item for item in session.objects if isinstance(item, BooruSnapshot)]
        assert snapshots == [result.snapshot]
        assert result.crawl_run.status is CrawlRunStatus.SUCCEEDED
        assert result.snapshot.metrics["total_posts"] == {
            "value": 12022661,
            "provenance": "estimated",
            "unit": "posts",
        }
        assert result.snapshot.health_status == "ok"
        assert result.crawl_run.details["quality_status"] == "accepted"
        assert result.crawl_run.details["quality_flags"] == []
        assert result.crawl_run.details["source_endpoints"] == [
            "recent_posts",
            "total_posts",
        ]
        responses = result.crawl_run.details["responses"]
        assert isinstance(responses, list)
        assert all(item["http_status"] == 200 for item in responses)
        assert all(item["content_type"] == "application/json" for item in responses)
        assert all(len(item["response_sha256"]) == 64 for item in responses)
        evidence_json = json.dumps(result.crawl_run.details)
        assert "cdn.example.invalid" not in evidence_json
        assert "file_url" not in evidence_json
        assert session.commits == 2
        assert session.rollbacks == 0

    run(exercise())


def test_invalid_candidate_fails_run_without_snapshot() -> None:
    async def exercise() -> None:
        session = FakeAsyncSession()
        async with httpx.AsyncClient(transport=transport_for_count(-1)) as client:
            with pytest.raises(DanbooruResponseError, match="non-negative integer"):
                await DanbooruSnapshotCollectionService().collect(
                    session,  # type: ignore[arg-type]
                    booru(),
                    DanbooruAdapter("https://danbooru.test", client),
                )

        assert not any(isinstance(item, BooruSnapshot) for item in session.objects)
        crawl_run = next(item for item in session.objects if isinstance(item, CrawlRun))
        assert crawl_run.status is CrawlRunStatus.FAILED
        assert crawl_run.details["quality_status"] == "hard_invalid"
        assert crawl_run.details["quality_flags"] == ["hard_invalid"]
        assert "DanbooruResponseError" in str(crawl_run.error_message)
        assert session.commits == 2
        assert session.rollbacks == 1

    run(exercise())


def test_invalid_normalized_candidate_cannot_cross_persistence_boundary() -> None:
    async def exercise() -> None:
        session = FakeAsyncSession()
        service = DanbooruSnapshotCollectionService(
            inspection_service=InvalidNormalizedInspectionService()
        )
        async with httpx.AsyncClient(transport=transport_for_count(12022661)) as client:
            with pytest.raises(HardInvalidObservationError):
                await service.collect(
                    session,  # type: ignore[arg-type]
                    booru(),
                    DanbooruAdapter("https://danbooru.test", client),
                )

        assert not any(isinstance(item, BooruSnapshot) for item in session.objects)
        crawl_run = next(item for item in session.objects if isinstance(item, CrawlRun))
        assert crawl_run.status is CrawlRunStatus.FAILED
        assert crawl_run.details["quality_status"] == "hard_invalid"

    run(exercise())


def test_suspicious_candidate_is_blocked_without_reusing_health_status() -> None:
    async def exercise() -> None:
        session = FakeAsyncSession(
            previous_metrics={
                "total_posts": {
                    "value": 12_000_000,
                    "provenance": "estimated",
                    "unit": "posts",
                }
            }
        )
        async with httpx.AsyncClient(transport=transport_for_count(1_000_000)) as client:
            with pytest.raises(SuspiciousObservationError):
                await DanbooruSnapshotCollectionService().collect(
                    session,  # type: ignore[arg-type]
                    booru(),
                    DanbooruAdapter("https://danbooru.test", client),
                )

        assert not any(isinstance(item, BooruSnapshot) for item in session.objects)
        crawl_run = next(item for item in session.objects if isinstance(item, CrawlRun))
        assert crawl_run.status is CrawlRunStatus.FAILED
        assert crawl_run.details["quality_status"] == "suspicious"
        assert crawl_run.details["quality_flags"] == ["total_posts_catastrophic_drop"]
        assert "health_status" not in crawl_run.details

    run(exercise())


def test_estimated_count_allows_non_catastrophic_decrease() -> None:
    policy = TotalPostsAnomalyPolicy()

    assert policy.suspicious_flags(12_000_000, 11_500_000) == ()


def test_generic_gelbooru_collection_persists_observed_posts_without_media() -> None:
    async def exercise() -> None:
        session = FakeAsyncSession()
        service = SnapshotCollectionService(policy=GELBOORU_SNAPSHOT_POLICY)
        async with httpx.AsyncClient(transport=gelbooru_transport(6_852_898)) as client:
            result = await service.collect(
                session,  # type: ignore[arg-type]
                gelbooru(),
                GelbooruAdapter("https://safebooru.test", client),
            )

        assert result.crawl_run.status is CrawlRunStatus.SUCCEEDED
        assert result.snapshot.metrics["total_posts"] == {
            "value": 6_852_898,
            "provenance": "observed",
            "unit": "posts",
        }
        assert result.snapshot.source_url == (
            "https://safebooru.test/index.php?page=dapi&s=post&q=index&limit=1"
        )
        assert isinstance(result.crawl_run.details["responses"], list)
        assert isinstance(result.crawl_run.details["source_endpoints"], list)
        persisted = json.dumps(
            {
                "details": result.crawl_run.details,
                "metrics": result.snapshot.metrics,
                "source_url": result.snapshot.source_url,
            }
        )
        assert "file_url" not in persisted
        assert "cdn.example.invalid" not in persisted
        assert session.commits == 2

    run(exercise())


def test_latest_incompatible_history_is_not_compared_for_gelbooru() -> None:
    async def exercise() -> None:
        session = FakeAsyncSession(
            previous_metrics={
                "total_posts": {
                    "value": 12_000_000,
                    "provenance": "estimated",
                    "unit": "posts",
                }
            }
        )
        service = SnapshotCollectionService(policy=GELBOORU_SNAPSHOT_POLICY)
        async with httpx.AsyncClient(transport=gelbooru_transport(1_000_000)) as client:
            result = await service.collect(
                session,  # type: ignore[arg-type]
                gelbooru(),
                GelbooruAdapter("https://safebooru.test", client),
            )

        assert result.crawl_run.status is CrawlRunStatus.SUCCEEDED
        assert result.crawl_run.details["quality_flags"] == []

    run(exercise())


def test_gelbooru_parser_error_is_hard_invalid_and_persisted_safely() -> None:
    async def exercise() -> None:
        session = FakeAsyncSession()
        unsafe_payload = (
            b'<posts count="https://secret.test/?token=raw&file_url=private.jpg">'
        )

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=unsafe_payload,
                headers={"content-type": "text/xml"},
            )

        service = SnapshotCollectionService(policy=GELBOORU_SNAPSHOT_POLICY)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(GelbooruResponseError):
                await service.collect(
                    session,  # type: ignore[arg-type]
                    gelbooru(),
                    GelbooruAdapter("https://safebooru.test", client),
                )

        crawl_run = next(item for item in session.objects if isinstance(item, CrawlRun))
        assert crawl_run.status is CrawlRunStatus.FAILED
        assert crawl_run.details["quality_status"] == "hard_invalid"
        assert crawl_run.details["quality_flags"] == ["hard_invalid"]
        assert crawl_run.error_message == (
            "GelbooruResponseError: response could not be normalized safely"
        )
        persisted = json.dumps(
            {"details": crawl_run.details, "error_message": crawl_run.error_message}
        )
        assert "secret.test" not in persisted
        assert "file_url" not in persisted
        assert "token" not in persisted
        assert session.rollbacks == 1
        assert session.gets == 1

    run(exercise())


def test_failed_final_commit_rolls_back_reloads_and_marks_durable_run_failed() -> None:
    async def exercise() -> None:
        session = FinalCommitFailureSession()
        async with httpx.AsyncClient(transport=transport_for_count(12_022_661)) as client:
            with pytest.raises(RuntimeError, match="secret.test"):
                await DanbooruSnapshotCollectionService().collect(
                    session,  # type: ignore[arg-type]
                    booru(),
                    DanbooruAdapter("https://danbooru.test", client),
                )

        assert not any(isinstance(item, BooruSnapshot) for item in session.objects)
        crawl_run = next(item for item in session.objects if isinstance(item, CrawlRun))
        assert crawl_run.status is CrawlRunStatus.FAILED
        assert crawl_run.error_message == "RuntimeError: collection failed"
        assert "secret.test" not in crawl_run.error_message
        assert "file_url" not in crawl_run.error_message
        assert session.commits == 3
        assert session.rollbacks == 1
        assert session.gets == 2

    run(exercise())
