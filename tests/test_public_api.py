from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from apps.api.main import create_app
from apps.api.routes.boorus import get_catalog_service
from booruradar.core.config import Settings
from booruradar.core.enums import MetricProvenance
from booruradar.discovery import CatalogFilters
from booruradar.models.booru import Booru
from booruradar.models.snapshot import BooruSnapshot
from booruradar.services.catalog import (
    BooruRecord,
    CatalogNotFoundError,
    CatalogReadService,
    ComparisonRecord,
    GrowthAvailableRecord,
    GrowthRankingEligibleRecord,
    GrowthUnavailableReason,
    GrowthUnavailableRecord,
    LargestRankingEligibleRecord,
    RankingIneligibleReason,
    RankingIneligibleRecord,
    RankingMode,
    RankingResult,
    SnapshotRecord,
    TotalPostsRecord,
)


BOORU_A_ID = uuid.UUID("00000000-0000-0000-0000-00000000000a")
BOORU_B_ID = uuid.UUID("00000000-0000-0000-0000-00000000000b")
MISSING_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")
CAPTURED_AT = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


def snapshot_record(
    booru_id: uuid.UUID,
    *,
    value: int,
    captured_at: datetime = CAPTURED_AT,
    provenance: MetricProvenance = MetricProvenance.OBSERVED,
) -> SnapshotRecord:
    return SnapshotRecord(
        id=uuid.uuid5(booru_id, captured_at.isoformat()),
        booru_id=booru_id,
        captured_at=captured_at,
        total_posts=TotalPostsRecord(value=value, provenance=provenance),
    )


SNAPSHOT_A_CURRENT = snapshot_record(BOORU_A_ID, value=1_100)
SNAPSHOT_A_PREVIOUS = snapshot_record(
    BOORU_A_ID,
    value=1_000,
    captured_at=CAPTURED_AT - timedelta(days=1),
)
SNAPSHOT_B_CURRENT = snapshot_record(BOORU_B_ID, value=2_000)

BOORU_A = BooruRecord(
    id=BOORU_A_ID,
    name="Alpha Booru",
    canonical_url="https://alpha.example",
    adapter_family="danbooru",
    adapter_name="danbooru-v1",
    latest_snapshot=SNAPSHOT_A_CURRENT,
)
BOORU_B = BooruRecord(
    id=BOORU_B_ID,
    name="Beta Booru",
    canonical_url="https://beta.example",
    adapter_family="gelbooru",
    adapter_name=None,
    latest_snapshot=SNAPSHOT_B_CURRENT,
)

GROWTH_A = GrowthAvailableRecord(
    booru_id=BOORU_A_ID,
    previous_snapshot=SNAPSHOT_A_PREVIOUS,
    current_snapshot=SNAPSHOT_A_CURRENT,
    posts_delta=100,
    elapsed_hours=24.0,
    posts_per_day=100.0,
    provenance=MetricProvenance.OBSERVED,
)
GROWTH_B = GrowthUnavailableRecord(
    booru_id=BOORU_B_ID,
    reason=GrowthUnavailableReason.INSUFFICIENT_HISTORY,
    detail="At least two snapshots are required.",
)

LARGEST_A = LargestRankingEligibleRecord(
    rank=2,
    booru_id=BOORU_A_ID,
    name=BOORU_A.name,
    canonical_url=BOORU_A.canonical_url,
    adapter_family=BOORU_A.adapter_family,
    adapter_name=BOORU_A.adapter_name,
    value=1_100,
    provenance=MetricProvenance.OBSERVED,
    latest_snapshot_id=SNAPSHOT_A_CURRENT.id,
    latest_captured_at=SNAPSHOT_A_CURRENT.captured_at,
)
LARGEST_B = LargestRankingEligibleRecord(
    rank=1,
    booru_id=BOORU_B_ID,
    name=BOORU_B.name,
    canonical_url=BOORU_B.canonical_url,
    adapter_family=BOORU_B.adapter_family,
    adapter_name=BOORU_B.adapter_name,
    value=2_000,
    provenance=MetricProvenance.OBSERVED,
    latest_snapshot_id=SNAPSHOT_B_CURRENT.id,
    latest_captured_at=SNAPSHOT_B_CURRENT.captured_at,
)
GROWTH_RANK_A = GrowthRankingEligibleRecord(
    rank=1,
    booru_id=BOORU_A_ID,
    name=BOORU_A.name,
    canonical_url=BOORU_A.canonical_url,
    adapter_family=BOORU_A.adapter_family,
    adapter_name=BOORU_A.adapter_name,
    value=100.0,
    unit="posts/day",
    provenance=MetricProvenance.OBSERVED,
    latest_snapshot_id=SNAPSHOT_A_CURRENT.id,
    latest_captured_at=SNAPSHOT_A_CURRENT.captured_at,
    previous_snapshot_id=SNAPSHOT_A_PREVIOUS.id,
    previous_captured_at=SNAPSHOT_A_PREVIOUS.captured_at,
    elapsed_hours=24.0,
    posts_delta=100,
)
RANKING_B_INELIGIBLE = RankingIneligibleRecord(
    booru_id=BOORU_B_ID,
    name=BOORU_B.name,
    canonical_url=BOORU_B.canonical_url,
    adapter_family=BOORU_B.adapter_family,
    adapter_name=BOORU_B.adapter_name,
    reason=RankingIneligibleReason.INSUFFICIENT_HISTORY,
)


class IsolatedCatalog:
    """A read seam with no database writer or outbound HTTP dependency."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def list_boorus(self, *, limit: int, offset: int, filters: CatalogFilters = CatalogFilters()) -> tuple[BooruRecord, ...]:
        self.calls.append(("list_boorus", limit, offset))
        return (BOORU_A, BOORU_B)

    async def get_booru(self, booru_id: uuid.UUID) -> BooruRecord:
        self.calls.append(("get_booru", booru_id))
        if booru_id == BOORU_A_ID:
            return BOORU_A
        if booru_id == BOORU_B_ID:
            return BOORU_B
        raise CatalogNotFoundError(booru_id)

    async def list_snapshots(
        self,
        booru_id: uuid.UUID,
        *,
        limit: int,
    ) -> tuple[SnapshotRecord, ...]:
        self.calls.append(("list_snapshots", booru_id, limit))
        if booru_id == BOORU_A_ID:
            return (SNAPSHOT_A_CURRENT, SNAPSHOT_A_PREVIOUS)[:limit]
        if booru_id == BOORU_B_ID:
            return (SNAPSHOT_B_CURRENT,)
        raise CatalogNotFoundError(booru_id)

    async def get_growth(
        self,
        booru_id: uuid.UUID,
    ) -> GrowthAvailableRecord | GrowthUnavailableRecord:
        self.calls.append(("get_growth", booru_id))
        if booru_id == BOORU_A_ID:
            return GROWTH_A
        if booru_id == BOORU_B_ID:
            return GROWTH_B
        raise CatalogNotFoundError(booru_id)

    async def compare(
        self,
        booru_ids: tuple[uuid.UUID, ...],
    ) -> tuple[ComparisonRecord, ...]:
        self.calls.append(("compare", booru_ids))
        records = {
            BOORU_A_ID: ComparisonRecord(booru=BOORU_A, growth=GROWTH_A),
            BOORU_B_ID: ComparisonRecord(booru=BOORU_B, growth=GROWTH_B),
        }
        try:
            return tuple(records[booru_id] for booru_id in booru_ids)
        except KeyError as error:
            raise CatalogNotFoundError(error.args[0]) from error

    async def rank_boorus(
        self,
        *,
        mode: RankingMode,
        limit: int,
        offset: int,
        filters: CatalogFilters = CatalogFilters(),
    ) -> RankingResult:
        self.calls.append(("rank_boorus", mode, limit, offset))
        if mode is RankingMode.LARGEST:
            items = (LARGEST_B, LARGEST_A)
            eligible_count = 2
            unit = "posts"
        else:
            eligible = GROWTH_RANK_A
            if mode is RankingMode.RELATIVE_GROWTH:
                eligible = replace(
                    eligible,
                    value=10.0,
                    unit="percent/day",
                )
            items = (eligible, RANKING_B_INELIGIBLE)
            eligible_count = 1
            unit = "posts/day" if mode is RankingMode.FASTEST_GROWTH else "percent/day"
        return RankingResult(
            mode=mode,
            unit=unit,
            total=2,
            eligible_count=eligible_count,
            limit=limit,
            offset=offset,
            items=items[offset : offset + limit],
        )


def request(
    path: str,
    *,
    catalog: IsolatedCatalog | None = None,
) -> tuple[httpx.Response, IsolatedCatalog]:
    isolated_catalog = catalog or IsolatedCatalog()

    async def exercise() -> httpx.Response:
        application = create_app(Settings(environment="test"))

        async def override_catalog_service() -> IsolatedCatalog:
            return isolated_catalog

        application.dependency_overrides[get_catalog_service] = override_catalog_service
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.get(path)

    return asyncio.run(exercise()), isolated_catalog


def nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(nested_keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(nested_keys(item) for item in value))
    return set()


def test_booru_list_is_bounded_and_projects_only_safe_public_fields() -> None:
    response, catalog = request("/api/v1/boorus?limit=2&offset=4")

    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 2
    assert payload["offset"] == 4
    assert [item["id"] for item in payload["items"]] == [
        str(BOORU_A_ID),
        str(BOORU_B_ID),
    ]
    assert payload["items"][0]["latest_snapshot"]["total_posts"] == {
        "value": 1_100,
        "provenance": "observed",
        "unit": "posts",
    }
    assert payload["items"][0]["adapter_name"] == "danbooru-v1"
    assert {
        "metrics",
        "crawl_run_id",
        "crawl_runs",
        "capabilities",
        "media_url",
    }.isdisjoint(nested_keys(payload))
    assert catalog.calls == [("list_boorus", 2, 4)]


def test_detail_treats_an_unavailable_booru_as_not_found() -> None:
    response, catalog = request(f"/api/v1/boorus/{MISSING_ID}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Booru not found"}
    assert catalog.calls == [("get_booru", MISSING_ID)]


def test_snapshots_are_newest_first_and_limit_is_capped() -> None:
    response, catalog = request(
        f"/api/v1/boorus/{BOORU_A_ID}/snapshots?limit=2",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["booru_id"] == str(BOORU_A_ID)
    assert payload["limit"] == 2
    assert [item["total_posts"]["value"] for item in payload["items"]] == [
        1_100,
        1_000,
    ]
    assert catalog.calls == [("list_snapshots", BOORU_A_ID, 2)]

    invalid_response, untouched_catalog = request(
        f"/api/v1/boorus/{BOORU_A_ID}/snapshots?limit=101",
    )
    assert invalid_response.status_code == 422
    assert untouched_catalog.calls == []


def test_growth_has_typed_available_and_unavailable_results() -> None:
    available, _ = request(f"/api/v1/boorus/{BOORU_A_ID}/growth")
    unavailable, _ = request(f"/api/v1/boorus/{BOORU_B_ID}/growth")

    assert available.status_code == 200
    assert available.json() == {
        "status": "available",
        "booru_id": str(BOORU_A_ID),
        "previous_snapshot": {
            "source_url": None,
            "id": str(SNAPSHOT_A_PREVIOUS.id),
            "booru_id": str(BOORU_A_ID),
            "captured_at": SNAPSHOT_A_PREVIOUS.captured_at.isoformat().replace(
                "+00:00",
                "Z",
            ),
            "total_posts": {
                "value": 1_000,
                "provenance": "observed",
                "unit": "posts",
            },
        },
        "current_snapshot": {
            "source_url": None,
            "id": str(SNAPSHOT_A_CURRENT.id),
            "booru_id": str(BOORU_A_ID),
            "captured_at": SNAPSHOT_A_CURRENT.captured_at.isoformat().replace(
                "+00:00",
                "Z",
            ),
            "total_posts": {
                "value": 1_100,
                "provenance": "observed",
                "unit": "posts",
            },
        },
        "posts_delta": 100,
        "posts_delta_unit": "posts",
        "elapsed_hours": 24.0,
        "posts_per_day": 100.0,
        "posts_per_day_unit": "posts/day",
        "provenance": "observed",
    }
    assert unavailable.status_code == 200
    assert unavailable.json() == {
        "status": "unavailable",
        "booru_id": str(BOORU_B_ID),
        "reason": "insufficient_history",
        "detail": "At least two snapshots are required.",
    }


def test_compare_requires_two_to_eight_unique_ids_and_preserves_order() -> None:
    response, catalog = request(
        f"/api/v1/compare?booru_id={BOORU_B_ID}&booru_id={BOORU_A_ID}",
    )

    assert response.status_code == 200
    assert [item["booru"]["id"] for item in response.json()["items"]] == [
        str(BOORU_B_ID),
        str(BOORU_A_ID),
    ]
    assert response.json()["items"][0]["growth"]["status"] == "unavailable"
    assert response.json()["items"][1]["growth"]["status"] == "available"
    assert catalog.calls == [("compare", (BOORU_B_ID, BOORU_A_ID))]

    one_id, one_id_catalog = request(f"/api/v1/compare?booru_id={BOORU_A_ID}")
    duplicate, duplicate_catalog = request(
        f"/api/v1/compare?booru_id={BOORU_A_ID}&booru_id={BOORU_A_ID}",
    )
    assert one_id.status_code == 422
    assert duplicate.status_code == 422
    assert one_id_catalog.calls == []
    assert duplicate_catalog.calls == []


def test_ranking_response_is_typed_paginated_and_excludes_internal_fields() -> None:
    response, catalog = request(
        "/api/v1/rankings?mode=fastest_growth&limit=2&offset=0"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "fastest_growth"
    assert payload["unit"] == "posts/day"
    assert payload["total"] == 2
    assert payload["eligible_count"] == 1
    assert payload["items"][0]["rank"] == 1
    assert payload["items"][0]["eligible"] is True
    assert payload["items"][0]["value"] == 100.0
    assert payload["items"][0]["provenance"] == "observed"
    assert payload["items"][1] == {
        "booru_id": str(BOORU_B_ID),
        "name": BOORU_B.name,
        "canonical_url": BOORU_B.canonical_url,
        "adapter_family": BOORU_B.adapter_family,
        "adapter_name": BOORU_B.adapter_name,
        "classification": None,
        "rank": None,
        "eligible": False,
        "reason": "insufficient_history",
    }
    assert "value" not in payload["items"][1]
    assert {
        "metrics",
        "crawl_run_id",
        "details",
        "responses",
        "response_sha256",
        "media_url",
    }.isdisjoint(nested_keys(payload))
    assert catalog.calls == [
        ("rank_boorus", RankingMode.FASTEST_GROWTH, 2, 0)
    ]


def test_ranking_modes_units_and_global_rank_survive_pagination() -> None:
    expected_units = {
        "largest": "posts",
        "fastest_growth": "posts/day",
        "relative_growth": "percent/day",
    }
    for mode, unit in expected_units.items():
        response, _ = request(f"/api/v1/rankings?mode={mode}")
        assert response.status_code == 200
        assert response.json()["unit"] == unit

    paged, _ = request("/api/v1/rankings?mode=largest&limit=1&offset=1")
    assert paged.status_code == 200
    assert paged.json()["items"][0]["rank"] == 2
    assert paged.json()["total"] == 2
    assert paged.json()["eligible_count"] == 2


def test_ranking_query_validation_fails_before_service_execution() -> None:
    for query in (
        "mode=unknown",
        "limit=0",
        "limit=101",
        "offset=-1",
        "offset=10001",
    ):
        response, catalog = request(f"/api/v1/rankings?{query}")
        assert response.status_code == 422
        assert catalog.calls == []


def test_openapi_documents_typed_get_only_public_endpoints() -> None:
    application = create_app(Settings(environment="test"))
    openapi = application.openapi()
    paths = openapi["paths"]
    public_paths = {path: operations for path, operations in paths.items() if path.startswith("/api/v1")}

    assert set(public_paths) == {
        "/api/v1/categories",
        "/api/v1/boorus",
        "/api/v1/boorus/{booru_id}",
        "/api/v1/boorus/{booru_id}/snapshots",
        "/api/v1/boorus/{booru_id}/growth",
        "/api/v1/compare",
        "/api/v1/rankings",
    }
    assert all(set(operations) == {"get"} for operations in public_paths.values())
    growth_schema = public_paths["/api/v1/boorus/{booru_id}/growth"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert "oneOf" in growth_schema
    assert growth_schema["discriminator"]["propertyName"] == "status"

    ranking_operation = public_paths["/api/v1/rankings"]["get"]
    ranking_schema = ranking_operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert "oneOf" in ranking_schema
    assert ranking_schema["discriminator"]["propertyName"] == "mode"
    assert openapi["components"]["schemas"]["RankingMode"]["enum"] == [
        "largest",
        "fastest_growth",
        "relative_growth",
    ]


class RowsResult:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, ...]]:
        return self._rows


class ExecuteOnlySession:
    """Only execute exists: accidental add/commit/HTTP calls fail the test."""

    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.statements: list[object] = []

    async def execute(self, statement: object) -> RowsResult:
        self.statements.append(statement)
        return RowsResult(self.rows)


def orm_snapshot(
    booru_id: uuid.UUID,
    *,
    posts: int,
    captured_at: datetime,
) -> BooruSnapshot:
    return BooruSnapshot(
        id=uuid.uuid4(),
        booru_id=booru_id,
        crawl_run_id=uuid.uuid4(),
        captured_at=captured_at,
        metrics={
            "total_posts": {
                "value": posts,
                "provenance": "observed",
                "unit": "posts",
            },
            "private_future_metric": {
                "value": "must-not-leak",
                "provenance": "estimated",
            },
        },
        source_url="https://api.example/private-crawl-endpoint",
    )


def test_snapshot_service_is_one_deterministic_read_and_redacts_raw_metrics() -> None:
    booru = Booru(
        id=BOORU_A_ID,
        name="Alpha Booru",
        canonical_url="https://alpha.example",
        adapter_family="danbooru",
        is_enabled=True,
    )
    current = orm_snapshot(BOORU_A_ID, posts=1_100, captured_at=CAPTURED_AT)
    previous = orm_snapshot(
        BOORU_A_ID,
        posts=1_000,
        captured_at=CAPTURED_AT - timedelta(days=1),
    )
    session = ExecuteOnlySession([(booru, current), (booru, previous)])
    service = CatalogReadService(session)  # type: ignore[arg-type]

    records = asyncio.run(service.list_snapshots(BOORU_A_ID, limit=2))

    assert [record.total_posts.value for record in records if record.total_posts] == [
        1_100,
        1_000,
    ]
    assert len(session.statements) == 1
    sql = str(session.statements[0])
    assert "boorus.is_enabled IS true" in sql
    assert "booru_snapshots.captured_at DESC NULLS LAST" in sql
    assert "booru_snapshots.id DESC NULLS LAST" in sql
    assert "LIMIT" in sql
    assert "private_future_metric" not in repr(records)
    assert all(record.source_url is None for record in records)
    assert "private-crawl-endpoint" not in repr(records)
