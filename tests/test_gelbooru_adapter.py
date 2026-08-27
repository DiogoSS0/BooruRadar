import json
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
from datetime import UTC, datetime

import httpx

from booruradar.adapters import registry
from booruradar.adapters.gelbooru import GelbooruAdapter, GelbooruResponseError
from booruradar.core.enums import AdapterFamily, MetricProvenance
from booruradar.adapters.schemas import RecentPostMetadata


def make_adapter(client: httpx.AsyncClient) -> GelbooruAdapter:
    return GelbooruAdapter("https://safebooru.org", client)


def _mock_transport(content: bytes, status_code: int = 200, content_type: str = "text/xml") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=content, headers={"Content-Type": content_type})
    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_correct_gelbooru_detection():
    # 1. correct GELBOORU detection
    xml = b'<?xml version="1.0" encoding="UTF-8"?><posts count="6852898" offset="0"><post id="7090572" change="1787776246" rating="q" tags="cat" /></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        detection = await GelbooruAdapter.detect("https://safebooru.org", client)
        assert detection.detected is True
        assert detection.family == AdapterFamily.GELBOORU
        assert detection.confidence == 1.0


@pytest.mark.anyio
async def test_reject_modern_danbooru_like_json_shape():
    # 2. reject modern-Danbooru-like JSON/non-XML shape
    payload = json.dumps([{"id": 123, "created_at": "2026-08-26", "rating": "s", "tag_string": "cat"}]).encode()
    async with httpx.AsyncClient(transport=_mock_transport(payload, content_type="application/json")) as client:
        detection = await GelbooruAdapter.detect("https://safebooru.org", client)
        assert detection.detected is False


@pytest.mark.anyio
async def test_reject_wrong_xml_root():
    # 3. reject wrong XML root
    xml = b'<?xml version="1.0"?><wrongroot count="10"></wrongroot>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        detection = await GelbooruAdapter.detect("https://safebooru.org", client)
        assert detection.detected is False


@pytest.mark.anyio
async def test_health_success():
    # 4. health success
    xml = b'<posts count="6852898" offset="0"></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        health = await adapter.health_check()
        assert health.healthy is True
        assert health.status == "ok"


@pytest.mark.anyio
async def test_malformed_payload_health_failure():
    # 5. malformed payload health failure
    async with httpx.AsyncClient(transport=_mock_transport(b"not xml")) as client:
        adapter = make_adapter(client)
        health = await adapter.health_check()
        assert health.healthy is False
        assert health.status == "invalid_response"


@pytest.mark.anyio
async def test_total_posts_parsed_from_xml_count():
    # 6. total_posts parsed from XML count
    xml = b'<posts count="12345" offset="0"></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        stats = await adapter.fetch_public_statistics()
        assert stats.metrics["total_posts"].value == 12345


@pytest.mark.anyio
async def test_total_posts_provenance_is_observed():
    # 7. total_posts provenance is OBSERVED
    xml = b'<posts count="1000" offset="0"></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        stats = await adapter.fetch_public_statistics()
        assert stats.metrics["total_posts"].provenance == MetricProvenance.OBSERVED


@pytest.mark.anyio
async def test_missing_count_rejected():
    # 8. missing count rejected
    xml = b'<posts offset="0"></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        with pytest.raises(GelbooruResponseError, match="missing count attribute"):
            await adapter.fetch_public_statistics()


@pytest.mark.anyio
async def test_malformed_count_rejected():
    # 9. malformed count rejected
    xml = b'<posts count="abc"></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        with pytest.raises(GelbooruResponseError, match="count must be an integer"):
            await adapter.fetch_public_statistics()


@pytest.mark.anyio
async def test_negative_count_rejected():
    # 10. negative count rejected
    xml = b'<posts count="-5"></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        with pytest.raises(GelbooruResponseError, match="count must be non-negative"):
            await adapter.fetch_public_statistics()


@pytest.mark.anyio
async def test_recent_metadata_normalized_correctly():
    # 11. recent metadata normalized correctly
    xml = b'<posts count="1"><post id="7090572" change="1787776246" rating="q" tags="cat dog" /></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        posts = await adapter.fetch_recent_posts(limit=1)
        assert len(posts) == 1
        post = posts[0]
        assert post.external_id == "7090572"
        assert post.rating == "q"
        assert post.tags == ("cat", "dog")
        assert str(post.post_url) == "https://safebooru.org/index.php?page=post&s=view&id=7090572"


@pytest.mark.anyio
async def test_change_timestamp_is_not_mislabeled_as_created_at():
    # 12. Change timestamp is not mislabeled as created_at
    xml = b'<posts><post id="1" change="1787776246" rating="q" tags="cat" /></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        posts = await adapter.fetch_recent_posts(limit=1)
        assert posts[0].created_at is None


@pytest.mark.anyio
async def test_media_fields_never_enter_recentpostmetadata():
    # 13. media fields never enter RecentPostMetadata
    xml = b'''<posts>
      <post id="1" change="123" rating="q" tags="cat" file_url="https://cdn/file.jpg" sample_url="https://cdn/sample.jpg" preview_url="https://cdn/prev.jpg" image="file.jpg" directory="123" hash="abc" />
    </posts>'''
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        posts = await adapter.fetch_recent_posts(limit=1)
        post = posts[0]
        # Pydantic schema RecentPostMetadata strictly validates fields.
        # Ensure the object does not contain these extra fields dynamically.
        assert not hasattr(post, "file_url")
        assert not hasattr(post, "sample_url")
        assert not hasattr(post, "preview_url")
        # Ensure it didn't crash
        assert post.external_id == "1"


@pytest.mark.anyio
async def test_recent_limit_validation():
    # 14. recent limit validation
    async with httpx.AsyncClient(transport=_mock_transport(b"")) as client:
        adapter = make_adapter(client)
        with pytest.raises(ValueError, match="limit must be between 1 and"):
            await adapter.fetch_recent_posts(limit=1500)


@pytest.mark.anyio
async def test_none_tag_names_makes_zero_requests():
    # 15. None tag_names makes zero tag HTTP requests
    def exploding_handler(request):
        raise AssertionError("Should not make HTTP requests")
    async with httpx.AsyncClient(transport=httpx.MockTransport(exploding_handler)) as client:
        adapter = make_adapter(client)
        res = await adapter.fetch_tag_statistics(tag_names=None)
        assert res == ()


@pytest.mark.anyio
async def test_exact_tag_name_parsed():
    # 16. exact tag name parsed
    xml = b'<tags type="array"><tag type="0" count="88272" name="cat" ambiguous="false" id="644"/></tags>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        stats = await adapter.fetch_tag_statistics(tag_names=["cat"])
        assert len(stats) == 1
        assert stats[0].name == "cat"
        assert stats[0].post_count.value == 88272


@pytest.mark.anyio
async def test_tag_count_provenance_observed():
    # 17. tag count provenance OBSERVED
    xml = b'<tags type="array"><tag type="0" count="88272" name="cat" ambiguous="false" id="644"/></tags>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        stats = await adapter.fetch_tag_statistics(tag_names=["cat"])
        assert stats[0].post_count.provenance == MetricProvenance.OBSERVED


@pytest.mark.anyio
async def test_missing_tag_returns_empty_tuple():
    # 18. missing tag returns empty tuple
    xml = b'<tags type="array"></tags>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        stats = await adapter.fetch_tag_statistics(tag_names=["missing"])
        assert stats == ()


@pytest.mark.anyio
async def test_malformed_tag_count_rejected():
    # 19. malformed tag count rejected
    xml = b'<tags type="array"><tag type="0" count="abc" name="cat" ambiguous="false" id="644"/></tags>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        with pytest.raises(GelbooruResponseError, match="malformed metadata"):
            await adapter.fetch_tag_statistics(tag_names=["cat"])


@pytest.mark.anyio
async def test_valid_posts_count_0_accepted():
    # 20. valid <posts count="0"> accepted
    xml = b'<posts count="0" offset="0"></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        stats = await adapter.fetch_public_statistics()
        assert stats.metrics["total_posts"].value == 0


@pytest.mark.anyio
async def test_evidence_accumulates_across_multiple_requests():
    # 21. evidence accumulates across multiple requests
    xml = b'<posts count="0" offset="0"></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        await adapter.fetch_public_statistics()
        await adapter.fetch_recent_posts(limit=1)
        evidence = adapter.request_evidence
        assert len(evidence) == 2


@pytest.mark.anyio
async def test_evidence_contains_hash_status_content_type_endpoint():
    # 22. evidence contains hash/status/content type/endpoint
    xml = b'<posts count="0" offset="0"></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        await adapter.fetch_public_statistics()
        ev = adapter.request_evidence[0]
        assert ev.endpoint_identifier == "total_posts"
        assert ev.http_status == 200
        assert ev.content_type == "text/xml"
        assert len(ev.response_sha256) == 64


@pytest.mark.anyio
async def test_evidence_contains_no_raw_body_media_url():
    # 23. evidence contains no raw body/media URL
    xml = b'<posts count="1"><post id="1" change="123" rating="q" tags="cat" file_url="https://evil/media.jpg" /></posts>'
    async with httpx.AsyncClient(transport=_mock_transport(xml)) as client:
        adapter = make_adapter(client)
        await adapter.fetch_recent_posts(limit=1)
        ev = adapter.request_evidence[0]
        # Pydantic schema for evidence does not even have a body field.
        assert not hasattr(ev, "body")
        assert not hasattr(ev, "file_url")
        # Ensure string representation doesn't leak it
        assert "https://evil/media.jpg" not in str(ev.model_dump())


def test_global_registry_contains_gelbooru_adapter():
    assert "gelbooru" in registry.registered_names
