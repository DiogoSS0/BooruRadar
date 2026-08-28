from __future__ import annotations

import asyncio
import base64
from hashlib import sha256
import json
from pathlib import Path
from typing import Any
import uuid

import httpx
import pytest

from booruradar.adapters import (
    AdapterRequestError,
    SourceAccessBlockedError,
    registry,
)
from booruradar.adapters.danbooru import DanbooruAdapter, DanbooruResponseError
from booruradar.adapters.evidence import fingerprint_response
from booruradar.adapters.schemas import AdapterCapability
from booruradar.core.enums import AdapterFamily, MetricProvenance


FIXTURES = Path(__file__).parent / "fixtures"
POSTS = json.loads((FIXTURES / "danbooru_posts.json").read_text(encoding="utf-8"))
COUNTS = json.loads((FIXTURES / "danbooru_counts.json").read_text(encoding="utf-8"))
TAG = json.loads((FIXTURES / "danbooru_tag.json").read_text(encoding="utf-8"))


def run(awaitable: Any) -> Any:
    return asyncio.run(awaitable)


def json_client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


def test_modern_danbooru_detection_success() -> None:
    async def exercise() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/posts.json"
            assert request.url.params["limit"] == "1"
            return httpx.Response(200, json=POSTS)

        async with json_client(httpx.MockTransport(handler)) as client:
            result = await DanbooruAdapter.detect("https://danbooru.test", client)

        assert result.detected is True
        assert result.family is AdapterFamily.DANBOORU
        assert result.confidence == 1.0

    run(exercise())


def test_incompatible_detection_returns_false() -> None:
    async def exercise() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"posts": POSTS})
        )
        async with json_client(transport) as client:
            result = await DanbooruAdapter.detect("https://legacy.test", client)

        assert result.detected is False
        assert result.confidence == 0.0

    run(exercise())


def test_health_success_records_latency_and_response_evidence() -> None:
    async def exercise() -> None:
        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=POSTS))
        async with json_client(transport) as client:
            adapter = DanbooruAdapter("https://danbooru.test", client)
            result = await adapter.health_check()

        assert result.healthy is True
        assert result.status == "ok"
        assert result.latency_ms is not None
        assert result.latency_ms.provenance is MetricProvenance.OBSERVED
        assert isinstance(result.latency_ms.value, float)
        assert result.latency_ms.value >= 0
        assert adapter.request_evidence[0].endpoint_identifier == "recent_posts"
        assert adapter.request_evidence[0].http_status == 200

    run(exercise())


def test_static_capability_discovery_exposes_verified_operations() -> None:
    async def exercise() -> None:
        async with httpx.AsyncClient() as client:
            capabilities = await DanbooruAdapter(
                "https://danbooru.test",
                client,
            ).discover_capabilities()

        assert capabilities.capabilities == frozenset(AdapterCapability)

    run(exercise())


def test_total_posts_is_parsed_as_estimated() -> None:
    async def exercise() -> None:
        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=COUNTS))
        async with json_client(transport) as client:
            result = await DanbooruAdapter(
                "https://danbooru.test",
                client,
            ).fetch_public_statistics()

        metric = result.metrics["total_posts"]
        assert metric.value == 12022661
        assert metric.unit == "posts"
        assert metric.provenance is MetricProvenance.ESTIMATED

    run(exercise())


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"counts": {}},
        {"counts": {"posts": True}},
        {"counts": {"posts": "12022661"}},
        {"counts": {"posts": 12.5}},
    ],
)
def test_malformed_total_posts_is_rejected(payload: object) -> None:
    async def exercise() -> None:
        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=payload))
        async with json_client(transport) as client:
            with pytest.raises(DanbooruResponseError):
                await DanbooruAdapter(
                    "https://danbooru.test",
                    client,
                ).fetch_public_statistics()

    run(exercise())


def test_negative_total_posts_is_rejected() -> None:
    async def exercise() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"counts": {"posts": -1}})
        )
        async with json_client(transport) as client:
            with pytest.raises(DanbooruResponseError, match="non-negative integer"):
                await DanbooruAdapter(
                    "https://danbooru.test",
                    client,
                ).fetch_public_statistics()

    run(exercise())


def test_recent_post_mapping_retains_rating_without_media_leakage() -> None:
    async def exercise() -> None:
        transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=POSTS))
        async with json_client(transport) as client:
            posts = await DanbooruAdapter(
                "https://danbooru.test",
                client,
            ).fetch_recent_posts(limit=1)

        post = posts[0]
        assert post.external_id == "987654"
        assert post.rating == "q"
        assert post.tags == ("cat", "blue_eyes", "solo")
        assert str(post.post_url) == "https://danbooru.test/posts/987654"
        serialized = post.model_dump_json()
        assert "cdn.example.invalid" not in serialized
        assert "file_url" not in serialized
        assert "media_asset" not in serialized

    run(exercise())


@pytest.mark.parametrize("limit", [0, 101, True])
def test_recent_post_request_limit_is_enforced_before_io(limit: object) -> None:
    async def exercise() -> None:
        request_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(200, json=POSTS)

        async with json_client(httpx.MockTransport(handler)) as client:
            adapter = DanbooruAdapter("https://danbooru.test", client)
            with pytest.raises(ValueError, match="between 1 and 100"):
                await adapter.fetch_recent_posts(limit=limit)  # type: ignore[arg-type]
        assert request_count == 0

    run(exercise())


def test_tag_parsing_uses_observed_count_and_raw_category_string() -> None:
    async def exercise() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/tags.json"
            assert request.url.params["search[name]"] == "cat"
            assert request.url.params["limit"] == "1"
            return httpx.Response(200, json=TAG)

        async with json_client(httpx.MockTransport(handler)) as client:
            statistics = await DanbooruAdapter(
                "https://danbooru.test",
                client,
            ).fetch_tag_statistics(tag_names=("cat",))

        statistic = statistics[0]
        assert statistic.name == "cat"
        assert statistic.post_count.value == 117821
        assert statistic.post_count.unit == "posts"
        assert statistic.post_count.provenance is MetricProvenance.OBSERVED
        assert statistic.category == "0"

    run(exercise())


def test_missing_tag_names_performs_no_full_tag_crawl() -> None:
    async def exercise() -> None:
        request_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(200, json=TAG)

        async with json_client(httpx.MockTransport(handler)) as client:
            result = await DanbooruAdapter(
                "https://danbooru.test",
                client,
            ).fetch_tag_statistics(tag_names=None)

        assert result == ()
        assert request_count == 0

    run(exercise())


@pytest.mark.parametrize("tag_names", ["cat", tuple(f"tag_{index}" for index in range(26))])
def test_tag_request_limits_are_enforced_before_io(tag_names: object) -> None:
    async def exercise() -> None:
        request_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(200, json=TAG)

        async with json_client(httpx.MockTransport(handler)) as client:
            adapter = DanbooruAdapter("https://danbooru.test", client)
            with pytest.raises(ValueError):
                await adapter.fetch_tag_statistics(
                    tag_names=tag_names  # type: ignore[arg-type]
                )
        assert request_count == 0

    run(exercise())


def test_response_fingerprint_does_not_retain_response_body() -> None:
    content = b'{"counts":{"posts":12022661}}'
    response = httpx.Response(
        200,
        content=content,
        headers={"content-type": "application/json; charset=utf-8"},
    )

    evidence = fingerprint_response(response, "total_posts")

    assert evidence.response_sha256 == sha256(content).hexdigest()
    assert evidence.content_type == "application/json; charset=utf-8"
    serialized = evidence.model_dump_json()
    assert "12022661" not in serialized
    assert "counts" not in serialized


def test_global_registry_contains_modern_danbooru_adapter() -> None:
    assert "danbooru" in registry.registered_names


@pytest.mark.parametrize(
    ("status_code", "mitigation"),
    [
        (403, None),
        (403, "challenge"),
        (200, " ChAlLeNgE "),
    ],
    ids=("forbidden", "forbidden-challenge", "header-only-challenge"),
)
def test_source_access_block_is_explicit_and_payload_free(
    status_code: int,
    mitigation: str | None,
) -> None:
    async def exercise() -> None:
        marker = f"challenge-body-{uuid.uuid4().hex}"
        challenge_body = f"<html><body>{marker}</body></html>".encode()
        request_count = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            headers = {
                "content-type": "text/html",
                "server": "cloudflare",
            }
            if mitigation is not None:
                headers["CF-Mitigated"] = mitigation
            return httpx.Response(status_code, content=challenge_body, headers=headers)

        async with json_client(httpx.MockTransport(handler)) as client:
            adapter = DanbooruAdapter("https://danbooru.test", client)
            with pytest.raises(SourceAccessBlockedError) as exc_info:
                await adapter.health_check()

        assert request_count == 1
        assert exc_info.value.__context__ is None
        assert exc_info.value.__cause__ is None
        evidence = adapter.request_evidence
        assert len(evidence) == 1
        assert evidence[0].model_dump() == {
            "endpoint_identifier": "recent_posts",
            "http_status": status_code,
            "content_type": "text/html",
            "response_sha256": sha256(challenge_body).hexdigest(),
        }
        rendered = evidence[0].model_dump_json() + str(exc_info.value) + repr(exc_info.value)
        assert marker not in rendered
        assert "<html" not in rendered

    run(exercise())


def test_detection_reports_source_access_block_instead_of_bad_api_shape() -> None:
    async def exercise() -> None:
        transport = httpx.MockTransport(
            lambda _request: httpx.Response(
                403,
                content=b"<html>challenge</html>",
                headers={"cf-mitigated": "challenge", "content-type": "text/html"},
            )
        )
        async with json_client(transport) as client:
            result = await DanbooruAdapter.detect("https://danbooru.test", client)

        assert result.detected is False
        assert result.evidence == ("source access was blocked",)

    run(exercise())


def test_unauthenticated_http_status_error_preserves_existing_exception() -> None:
    async def exercise() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "authorization" not in request.headers
            return httpx.Response(500, content=b"upstream failure")

        async with json_client(httpx.MockTransport(handler)) as client:
            adapter = DanbooruAdapter("https://danbooru.test", client)
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await adapter.fetch_public_statistics()

        assert type(exc_info.value) is httpx.HTTPStatusError
        assert exc_info.value.response.status_code == 500

    run(exercise())


def test_unauthenticated_transport_error_preserves_existing_exception() -> None:
    async def exercise() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "authorization" not in request.headers
            raise httpx.ConnectError(
                "unauthenticated transport failure",
                request=request,
            )

        async with json_client(httpx.MockTransport(handler)) as client:
            adapter = DanbooruAdapter("https://danbooru.test", client)
            with pytest.raises(httpx.ConnectError) as exc_info:
                await adapter.fetch_public_statistics()

        assert type(exc_info.value) is httpx.ConnectError
        assert str(exc_info.value) == "unauthenticated transport failure"

    run(exercise())


def test_unauthenticated_json_error_preserves_existing_parse_cause() -> None:
    async def exercise() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "authorization" not in request.headers
            return httpx.Response(
                200,
                content=b"not-json",
                headers={"content-type": "application/json"},
            )

        async with json_client(httpx.MockTransport(handler)) as client:
            adapter = DanbooruAdapter("https://danbooru.test", client)
            with pytest.raises(DanbooruResponseError) as exc_info:
                await adapter.fetch_public_statistics()

        assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)

    run(exercise())


def test_authenticated_json_error_drops_parse_body_and_credentials() -> None:
    async def exercise() -> None:
        login = f"test-login-{uuid.uuid4().hex}"
        api_key = f"test-key-{uuid.uuid4().hex}"
        body = f"invalid JSON containing {login} {api_key}".encode()

        def handler(request: httpx.Request) -> httpx.Response:
            assert "authorization" in request.headers
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "application/json"},
            )

        async with httpx.AsyncClient(
            auth=httpx.BasicAuth(login, api_key),
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = DanbooruAdapter("https://danbooru.test", client)
            with pytest.raises(DanbooruResponseError) as exc_info:
                await adapter.fetch_public_statistics()

        error = exc_info.value
        assert error.__context__ is None
        assert error.__cause__ is None
        rendered = str(error) + repr(error) + repr(error.__dict__)
        assert login not in rendered
        assert api_key not in rendered
        assert body.decode() not in rendered

    run(exercise())


def test_authenticated_http_status_error_drops_request_and_secret_data() -> None:
    async def exercise() -> None:
        login = f"test-login-{uuid.uuid4().hex}"
        api_key = f"test-key-{uuid.uuid4().hex}"
        authorization = "Basic " + base64.b64encode(
            f"{login}:{api_key}".encode()
        ).decode()
        body = f"remote error must not retain {login} {api_key}".encode()

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["authorization"] == authorization
            return httpx.Response(500, content=body, headers={"content-type": "text/plain"})

        async with httpx.AsyncClient(
            auth=httpx.BasicAuth(login, api_key),
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = DanbooruAdapter("https://danbooru.test", client)
            with pytest.raises(AdapterRequestError) as exc_info:
                await adapter.fetch_public_statistics()

        error = exc_info.value
        assert error.status_code == 500
        assert error.__context__ is None
        assert error.__cause__ is None
        assert "request" not in error.__dict__
        assert "response" not in error.__dict__
        rendered = repr(error) + repr(error.__dict__)
        assert login not in rendered
        assert api_key not in rendered
        assert authorization not in rendered
        assert body.decode() not in rendered

    run(exercise())


def test_authenticated_transport_error_is_translated_without_exception_context() -> None:
    async def exercise() -> None:
        login = f"test-login-{uuid.uuid4().hex}"
        api_key = f"test-key-{uuid.uuid4().hex}"

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(
                f"transport failure containing {login} {api_key}",
                request=request,
            )

        async with httpx.AsyncClient(
            auth=httpx.BasicAuth(login, api_key),
            transport=httpx.MockTransport(handler),
        ) as client:
            adapter = DanbooruAdapter("https://danbooru.test", client)
            with pytest.raises(AdapterRequestError) as exc_info:
                await adapter.fetch_public_statistics()

        error = exc_info.value
        assert error.status_code is None
        assert error.__context__ is None
        assert error.__cause__ is None
        rendered = repr(error) + repr(error.__dict__)
        assert login not in rendered
        assert api_key not in rendered

    run(exercise())
