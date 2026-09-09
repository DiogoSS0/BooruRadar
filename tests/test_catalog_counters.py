from __future__ import annotations

import asyncio

import httpx
import pytest

from booruradar.adapters.aggregate import E621Adapter, MoebooruAdapter
from booruradar.adapters import registry
from booruradar.adapters.base import AdapterResponseError, SourceAccessBlockedError
from booruradar.adapters.counters import (
    DanbooruCounterAdapter, GelbooruHomeCounterAdapter, GelbooruXmlCounterAdapter,
    PhilomenaStatisticsAdapter, ShimmieHomeCounterAdapter, ShuushuuAdapter,
    UnfilteredPhilomenaAdapter,
)
from booruradar.discovery import public_snapshot_source_url
from booruradar.services.inspection import BooruInspectionService
from booruradar.services.quality import build_snapshot_candidate
from booruradar.targets import COLLECTION_TARGETS, EXPANSION_TARGETS


FILTER = {"filter": {"id": 2, "system": True, "public": False, "hidden_tag_ids": [],
                      "spoilered_tag_ids": [], "hidden_complex": None, "spoilered_complex": None}}
BODIES = {
    MoebooruAdapter: '<posts count="123"><post file_url="discard-me"/></posts>',
    GelbooruXmlCounterAdapter: '<posts count="123"><post file_url="discard-me"/></posts>',
    DanbooruCounterAdapter: '{"counts":{"posts":123}}',
    ShuushuuAdapter: '{"total":123,"per_page":1,"images":[{"media":"discard-me"}]}',
    UnfilteredPhilomenaAdapter: '{"total":123,"images":[{"representations":"discard-me"}]}',
    E621Adapter: '<div class="home-footer-counter"><img alt="1"><img alt="2"><img alt="3"></div>',
    GelbooruHomeCounterAdapter: '<p>Visitors: 999,999</p><img src="./counter/1.gif" alt="1"/><img src="./counter/2.gif" alt="2"/><img src="./counter/3.gif" alt="3"/>',
    PhilomenaStatisticsAdapter: '<p><strong>123</strong> non-deleted images total in our database. Of these, <b>10</b> are hidden.</p><p>This net total excludes the 900 images that have been deleted or marked as duplicates.</p>',
    ShimmieHomeCounterAdapter: '<p>Serving <strong>123</strong> posts — Running Shimmie2</p>',
}


@pytest.mark.parametrize("target", EXPANSION_TARGETS, ids=lambda target: target.key)
def test_every_new_target_produces_a_compatible_candidate_and_discards_payload(target):
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.path.endswith("/filters/2"):
            return httpx.Response(200, json=FILTER)
        assert str(request.url) == target.policy.statistics_url(target.canonical_url)
        return httpx.Response(200, text=BODIES[target.adapter_type])
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter = target.create_adapter(client)
            assert type(registry.create(target.adapter_name, target.canonical_url, client)) is target.adapter_type
            inspection = await BooruInspectionService().inspect(adapter)
            source = target.policy.statistics_url(target.canonical_url)
            candidate = build_snapshot_candidate(inspection, source, policy=target.policy)
            assert candidate.total_posts == 123
            assert public_snapshot_source_url(source) == source
            assert inspection.recent_posts == inspection.tag_statistics == ()
            assert "discard-me" not in inspection.model_dump_json()
            assert "discard-me" not in repr(adapter.request_evidence)
            assert len(calls) == (2 if target.adapter_type is UnfilteredPhilomenaAdapter else 1)
            assert target.classification.reference_urls
            assert target.classification.reviewed_at.isoformat() == "2026-09-09"
    asyncio.run(exercise())


@pytest.mark.parametrize(("adapter_type", "body"), [
    (GelbooruXmlCounterAdapter, '<error>Missing authentication</error>'),
    (GelbooruXmlCounterAdapter, '<response success="false" reason="access denied"/>'),
    (DanbooruCounterAdapter, '{"counts":{"posts":true}}'),
    (DanbooruCounterAdapter, '{"counts":{"posts":-1}}'),
    (DanbooruCounterAdapter, '{"counts":{"posts":"123"}}'),
    (DanbooruCounterAdapter, '{"counts":{"posts":123,"capped":true}}'),
    (DanbooruCounterAdapter, '{"counts":{"posts":123},"capped":true}'),
    (DanbooruCounterAdapter, '{"posts":123}'),
    (DanbooruCounterAdapter, '<html>Blocked</html>'),
    (ShuushuuAdapter, '{"total":true}'),
    (ShuushuuAdapter, '{"total":-1}'),
    (ShuushuuAdapter, '{"total":3.5}'),
    (PhilomenaStatisticsAdapter, '<p>123 deleted images total in our database.</p>'),
    (PhilomenaStatisticsAdapter, '<p>1,23 non-deleted images total in our database.</p>'),
    (PhilomenaStatisticsAdapter, '<p>-123 non-deleted images total in our database.</p>'),
    (PhilomenaStatisticsAdapter, '<p>123.5 non-deleted images total in our database.</p>'),
    (PhilomenaStatisticsAdapter, '<script>123 non-deleted images total in our database.</script>'),
    (PhilomenaStatisticsAdapter, '<p>123 non-deleted images total in our database.</p>' * 2),
    (ShimmieHomeCounterAdapter, '<p>Serving 1,23 posts</p>'),
    (ShimmieHomeCounterAdapter, '<p>Serving -1 posts</p>'),
    (ShimmieHomeCounterAdapter, '<p>Serving 1.5 posts</p>'),
    (GelbooruHomeCounterAdapter, '<img src="./counter/1.gif" alt="2">'),
    (GelbooruHomeCounterAdapter, '<img src="./counter/a.gif" alt="1">'),
    (GelbooruHomeCounterAdapter, '<p>Total visitors 123</p><img src="/other/1.gif" alt="1">'),
    (GelbooruHomeCounterAdapter, '<img src="./counter/1.gif" alt="1"><p>Visitors</p><img src="./counter/2.gif" alt="2">'),
])
def test_new_counters_reject_errors_partial_counts_and_ambiguous_markup(adapter_type, body):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))) as client:
            with pytest.raises(AdapterResponseError):
                await adapter_type("https://counter.example", client).fetch_public_statistics()
    asyncio.run(exercise())


@pytest.mark.parametrize("change", [
    {"id": 3}, {"id": True}, {"hidden_tag_ids": [123]}, {"spoilered_tag_ids": [123]},
    {"hidden_complex": "hidden"}, {"spoilered_complex": "hidden"}, {"system": False, "public": False},
])
def test_filter_drift_stops_before_querying_a_partial_total(change):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"filter": FILTER["filter"] | change})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            with pytest.raises(AdapterResponseError):
                await UnfilteredPhilomenaAdapter("https://counter.example", client).fetch_public_statistics()
            assert len(calls) == 1
    asyncio.run(exercise())


def test_filter_is_checked_again_after_inspection_cache_is_cleared():
    calls = []
    def respond(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=FILTER if request.url.path.endswith("/filters/2") else {"total":123})
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter = UnfilteredPhilomenaAdapter("https://counter.example", client)
            await adapter.health_check()
            await adapter.fetch_public_statistics()
            assert len(calls) == 2
            adapter.clear_request_evidence()
            await adapter.fetch_public_statistics()
            assert len(calls) == 4
            assert len(adapter.request_evidence) == 2
    asyncio.run(exercise())


@pytest.mark.parametrize("adapter_type", list(BODIES))
def test_new_counter_access_blocks_are_not_retried(adapter_type):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(403, text="private challenge")
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter = adapter_type("https://counter.example", client)
            with pytest.raises(SourceAccessBlockedError):
                await BooruInspectionService().inspect(adapter)
            assert len(calls) == 1
            assert "private challenge" not in repr(adapter.request_evidence)
    asyncio.run(exercise())


def test_registry_has_distinct_sources_and_explicit_variant_relationship():
    assert len(COLLECTION_TARGETS) == 22
    assert len({target.canonical_url for target in COLLECTION_TARGETS.values()}) == 22
    assert COLLECTION_TARGETS["konachan-safe"].classification.subset_of == "konachan"
    assert "e926" not in COLLECTION_TARGETS
