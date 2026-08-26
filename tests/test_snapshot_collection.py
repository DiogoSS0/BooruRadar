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
    HardInvalidObservationError,
    InspectionResult,
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
        self.rollbacks = 0

    def add(self, instance: object) -> None:
        if instance not in self.objects:
            self.objects.append(instance)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def get(self, model: type[object], identity: uuid.UUID) -> object | None:
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


def transport_for_count(total_posts: object) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/posts.json":
            return httpx.Response(200, json=POSTS)
        if request.url.path == "/counts/posts.json":
            return httpx.Response(200, json={"counts": {"posts": total_posts}})
        raise AssertionError(f"unexpected request path: {request.url.path}")

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
