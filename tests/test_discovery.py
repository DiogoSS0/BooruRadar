from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from apps.api.main import create_app
from apps.api.routes.boorus import get_catalog_service
from booruradar.discovery import CatalogFilters, Category, CategoryMatch, ContentRating, public_snapshot_source_url
from booruradar.models import Booru, BooruSnapshot
from booruradar.services.catalog import CatalogReadService, RankingMode
from booruradar.targets import COLLECTION_TARGETS


class CatalogSession:
    def __init__(self, targets=None):
        self.rows = []
        now = datetime(2026, 9, 8, tzinfo=UTC)
        # Keep the original contract fixture stable as new real sources are added.
        if targets is None:
            targets = [COLLECTION_TARGETS[key] for key in (
                "danbooru", "safebooru", "konachan", "konachan-safe",
                "yandere", "e621", "derpibooru", "aibooru",
            )]
        for index, target in enumerate(targets):
            booru = Booru(id=uuid.UUID(int=index + 1), name=target.name, canonical_url=target.canonical_url,
                          adapter_family=target.adapter_family, adapter_name=target.adapter_name, is_enabled=True)
            for rank in (1, 2):
                snapshot = BooruSnapshot(id=uuid.uuid4(), booru_id=booru.id, crawl_run_id=uuid.uuid4(),
                                        captured_at=now - timedelta(days=rank - 1),
                                        source_url=target.policy.statistics_url(target.canonical_url),
                                        metrics={"total_posts": {"value": 100000 - index * 70 - (rank - 1) * 10,
                                                                 "unit": "posts", "provenance": target.policy.total_posts_provenance}})
                self.rows.append((booru, snapshot, rank))

    async def execute(self, statement):
        if "snapshot_rank" in str(statement):
            rows = self.rows
        else:
            rows = sorted([(booru, snapshot) for booru, snapshot, rank in self.rows if rank == 1], key=lambda row: row[0].name.lower())
        class Result:
            def all(self): return rows
        return Result()


def rank(filters, mode=RankingMode.LARGEST, limit=50, offset=0):
    return asyncio.run(CatalogReadService(CatalogSession()).rank_boorus(
        mode=mode, limit=limit, offset=offset, filters=filters))


def test_safe_is_exclusive_and_global_ranks_survive_filter_and_pagination():
    result = rank(CatalogFilters(content_rating=ContentRating.SAFE), limit=1, offset=1)
    assert result.total == result.eligible_count == 2
    assert result.items[0].name == "Konachan Safe"
    assert result.items[0].rank == 4
    assert result.items[0].classification.subset_of == "konachan"


@pytest.mark.parametrize("mode", list(RankingMode))
def test_all_ranking_modes_share_discovery_and_global_ranks(mode):
    all_sources = rank(CatalogFilters(), mode)
    filtered = rank(CatalogFilters(content_rating=ContentRating.NSFW, category=(Category.ANIME,), exclude_category=(Category.AI_GENERATED,)), mode)
    expected = [item for item in all_sources.items if item.name in ("Danbooru", "Konachan", "Yande.re")]
    assert [(item.name, item.rank, item.value) for item in filtered.items] == [(item.name, item.rank, item.value) for item in expected]
    assert filtered.total == filtered.eligible_count == 3


def test_all_any_exclusions_and_case_insensitive_name_or_domain():
    assert [r.name for r in rank(CatalogFilters(category=(Category.FURRY, Category.ANTHRO))).items] == ["e621"]
    assert rank(CatalogFilters(category=(Category.FURRY, Category.ANIME))).total == 0
    assert rank(CatalogFilters(category=(Category.FURRY, Category.ANIME), category_match=CategoryMatch.ANY)).total == 7
    assert rank(CatalogFilters(category=(Category.FURRY,), exclude_category=(Category.FURRY,))).total == 0
    assert [r.name for r in rank(CatalogFilters(q=" DONMAI.US ")).items] == ["Danbooru"]
    assert [r.name for r in rank(CatalogFilters(q="konachan safe")).items] == ["Konachan Safe"]
    assert rank(CatalogFilters(q="https")).total == 0


def test_unknown_classification_is_not_assumed_safe():
    assert not CatalogFilters(content_rating=ContentRating.SAFE).matches("Unknown", "https://unknown.example")
    assert CatalogFilters().matches("Unknown", "https://unknown.example")


def test_filtered_catalog_matches_ranking_and_paginates_after_filtering():
    filters = CatalogFilters(content_rating=ContentRating.SAFE)
    records = asyncio.run(CatalogReadService(CatalogSession()).list_boorus(limit=1, offset=1, filters=filters))
    assert [record.name for record in records] == ["Safebooru"]
    assert records[0].latest_snapshot.source_url.startswith("https://safebooru.org/")


def request(path):
    async def exercise():
        app = create_app()
        async def catalog(): return CatalogReadService(CatalogSession())
        app.dependency_overrides[get_catalog_service] = catalog
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
            return await client.get(path)
    return asyncio.run(exercise())


def test_api_documents_and_applies_identical_filters():
    query = "content_rating=nsfw&category=anime&exclude_category=ai-generated&category_match=all"
    catalog = request(f"/api/v1/boorus?{query}")
    ranking = request(f"/api/v1/rankings?{query}")
    assert catalog.status_code == ranking.status_code == 200
    assert {item["name"] for item in catalog.json()["items"]} == {item["name"] for item in ranking.json()["items"]}
    item = ranking.json()["items"][0]
    assert item["classification"]["basis"] == "editorial"
    assert item["classification"]["reference_urls"]
    assert item["source_url"] == "https://danbooru.donmai.us/counts/posts.json"
    assert len(request("/api/v1/categories").json()["items"]) == len(Category)
    paths = create_app().openapi()["paths"]
    for path in ("/api/v1/boorus", "/api/v1/rankings"):
        names = {parameter["name"] for parameter in paths[path]["get"]["parameters"]}
        assert {"q", "content_rating", "category", "exclude_category", "category_match"} <= names


@pytest.mark.parametrize("query", ["category=unsupported", "exclude_category=unsupported", "content_rating=mixed", "category_match=invalid", "q=" + "a" * 101, "&".join(["category=anime"] * (len(Category) + 1))])
def test_api_rejects_invalid_filters(query):
    assert request("/api/v1/rankings?" + query).status_code == 422
    assert request("/api/v1/boorus?" + query).status_code == 422


def test_source_url_is_allowlisted_not_a_raw_crawl_url():
    assert public_snapshot_source_url("https://example.com/private?api_key=secret") is None
    assert public_snapshot_source_url("https://e621.net/") == "https://e621.net/"


def test_expanded_catalog_paginates_and_keeps_global_ranks_after_filtering():
    async def exercise():
        service = CatalogReadService(CatalogSession(COLLECTION_TARGETS.values()))
        first = await service.rank_boorus(limit=20, offset=0, mode=RankingMode.LARGEST)
        second = await service.rank_boorus(limit=20, offset=20, mode=RankingMode.LARGEST)
        assert first.total == second.total == len(COLLECTION_TARGETS)
        assert len(first.items) == 20
        combined = [*first.items, *second.items]
        assert [item.rank for item in combined] == list(range(1, len(COLLECTION_TARGETS) + 1))
        assert len({item.booru_id for item in combined}) == len(COLLECTION_TARGETS)
        furry = await service.rank_boorus(limit=20, offset=0, mode=RankingMode.LARGEST,
                                         filters=CatalogFilters(category=(Category.FURRY,), exclude_category=(Category.AI_GENERATED,)))
        assert [item.name for item in furry.items] == ["e621", "Furbooru"]
        assert [item.rank for item in furry.items] == [item.rank for item in combined if item.name in ("e621", "Furbooru")]
    asyncio.run(exercise())


def test_new_categories_and_conservative_safe_classification():
    assert CatalogFilters(category=(Category.ANIMATION,)).matches("Sakugabooru", "https://www.sakugabooru.com")
    assert CatalogFilters(category=(Category.COSPLAY, Category.PHOTOGRAPHY)).matches("Cosbooru", "https://cos.lycore.co")
    assert not CatalogFilters(content_rating=ContentRating.SAFE).matches("e-shuushuu", "https://e-shuushuu.net")
    assert "artistic nudity" in COLLECTION_TARGETS["e-shuushuu"].classification.notes
    assert {item["key"] for item in request("/api/v1/categories").json()["items"]} >= {"animation", "cosplay", "photography"}
