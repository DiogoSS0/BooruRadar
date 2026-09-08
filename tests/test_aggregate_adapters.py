from __future__ import annotations

import asyncio

import httpx
import pytest

from booruradar.adapters.aggregate import E621Adapter, MoebooruAdapter, PhilomenaAdapter
from booruradar.adapters.base import AdapterResponseError, SourceAccessBlockedError, UnsupportedCapabilityError
from booruradar.adapters.schemas import AdapterCapability
from booruradar.services.inspection import BooruInspectionService


@pytest.mark.parametrize(("adapter_type", "body", "expected"), [
    (MoebooruAdapter, '<posts count="12345"><post file_url="discard-me" /></posts>', 12345),
    (PhilomenaAdapter, '{"total":12345,"images":[{"representations":"discard-me"}]}', 12345),
    (E621Adapter, '<div class="home-footer-counter"><img alt="1"><img alt="2"><img alt="3"></div><img alt="9">', 123),
    (MoebooruAdapter, '<posts count="0"/>', 0),
    (PhilomenaAdapter, '{"total":0,"images":[]}', 0),
])
def test_collects_only_validated_counter_once(adapter_type, body, expected):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=body)
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter = adapter_type("https://counter.example", client)
            result = await BooruInspectionService().inspect(adapter, recent_post_limit=1)
            assert result.public_statistics.metrics["total_posts"].value == expected
            assert result.public_statistics.metrics["total_posts"].provenance == "observed"
            assert result.recent_posts == result.tag_statistics == ()
            assert "discard-me" not in result.model_dump_json()
            assert "discard-me" not in repr(adapter.request_evidence)
            assert len(adapter.request_evidence) == 1
            assert len(calls) == 1
            assert not result.capability_discovery.supports(AdapterCapability.RECENT_POST_METADATA)
            if adapter_type is PhilomenaAdapter:
                assert calls[0].url.params["filter_id"] == "56027"
                assert calls[0].url.params["per_page"] == "1"
            if adapter_type is E621Adapter:
                assert calls[0].url.path == "/"
            with pytest.raises(UnsupportedCapabilityError):
                await adapter.fetch_recent_posts()
            adapter.clear_request_evidence()
            await adapter.fetch_public_statistics()
            assert len(calls) == 2
            assert len(adapter.request_evidence) == 1
    asyncio.run(exercise())


@pytest.mark.parametrize(("adapter_type", "body"), [
    (MoebooruAdapter, '<posts count="-1"/>'),
    (MoebooruAdapter, '<posts count="1.2"/>'),
    (MoebooruAdapter, '<posts/>'),
    (MoebooruAdapter, '<error count="1"/>'),
    (MoebooruAdapter, '<html>broken'),
    (MoebooruAdapter, '<!DOCTYPE posts><posts count="1"/>'),
    (PhilomenaAdapter, '{"total":true}'),
    (PhilomenaAdapter, '{"total":-1}'),
    (PhilomenaAdapter, '{"total":1.2}'),
    (PhilomenaAdapter, '{"total":"1"}'),
    (PhilomenaAdapter, '{"images":[]}'),
    (PhilomenaAdapter, '[]'),
    (PhilomenaAdapter, '<html>Unavailable</html>'),
    (E621Adapter, '{"count":240001,"capped":true}'),
    (E621Adapter, '<div><img alt="1"></div>'),
    (E621Adapter, '<div class="home-footer-counter"><img alt="1.5"></div>'),
    (E621Adapter, '<div class="home-footer-counter"><img alt="1">'),
    (E621Adapter, '<div class="home-footer-counter"><img alt="1"></div><div class="home-footer-counter"><img alt="2"></div>'),
])
def test_rejects_missing_malformed_or_capped_counter(adapter_type, body):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=body))) as client:
            with pytest.raises(AdapterResponseError):
                await adapter_type("https://counter.example", client).fetch_public_statistics()
    asyncio.run(exercise())


@pytest.mark.parametrize("adapter_type", [MoebooruAdapter, E621Adapter, PhilomenaAdapter])
@pytest.mark.parametrize(("status", "headers"), [(403, {}), (200, {"cf-mitigated": "challenge"})])
def test_access_block_is_one_attempt_with_bounded_evidence(adapter_type, status, headers):
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(status, headers=headers, text="private challenge content")
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            adapter = adapter_type("https://counter.example", client)
            with pytest.raises(SourceAccessBlockedError):
                await BooruInspectionService().inspect(adapter)
            assert len(calls) == 1
            assert adapter.request_evidence[0].http_status == status
            assert "private challenge" not in repr(adapter.request_evidence)
    asyncio.run(exercise())
