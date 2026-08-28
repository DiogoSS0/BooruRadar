from __future__ import annotations

import asyncio

import httpx

from apps.api.main import create_app
from booruradar.core.config import Settings


KNOWN_FAKE_MOCKUP_VALUES = (
    "80+",
    "1.2B",
    "127,842",
    "24/7 scanning",
    "2.4K",
    "Global Ranking",
    "Top Boorus",
)


def request(path: str, *, method: str = "GET") -> httpx.Response:
    async def exercise() -> httpx.Response:
        application = create_app(Settings(environment="test"))
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            return await client.request(method, path)

    return asyncio.run(exercise())


def assert_security_headers(response: httpx.Response) -> None:
    content_security_policy = response.headers["content-security-policy"]
    assert content_security_policy.startswith("default-src 'none'")
    assert "img-src 'self'" in content_security_policy
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["permissions-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_homepage_is_public_product_html_with_real_destinations() -> None:
    response = request("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert_security_headers(response)
    assert "BooruRadar" in response.text
    assert "Discover what’s happening across the booru ecosystem." in response.text
    assert response.text.count("<h1") == 1
    assert 'href="/assets/styles.css"' in response.text
    assert 'src="/assets/app.js"' in response.text
    assert 'src="/assets/booruradar-mascot.png"' in response.text
    assert 'alt="BooruRadar mascot holding a scanner and pointing ahead"' in response.text
    assert 'href="/docs"' in response.text
    assert 'href="https://github.com/DiogoSS0/BooruRadar"' in response.text
    assert 'id="catalog-empty"' in response.text
    assert 'id="catalog-error"' in response.text
    assert "Live ecosystem data is temporarily unavailable." in response.text
    assert request("/", method="POST").status_code == 405


def test_homepage_contains_no_mockup_metrics_or_external_booru_media() -> None:
    response = request("/")

    for fake_value in KNOWN_FAKE_MOCKUP_VALUES:
        assert fake_value not in response.text
    for unsafe_media_reference in (
        "cdn.donmai.us",
        "file_url",
        "preview_url",
        "sample_url",
        "media_asset",
    ):
        assert unsafe_media_reference not in response.text
    assert "/api/v1/rankings" not in response.text
    assert "newsletter" not in response.text.lower()
    assert "Privacy Policy" not in response.text
    assert "Terms of Service" not in response.text


def test_homepage_assets_are_local_fixed_responses() -> None:
    stylesheet = request("/assets/styles.css")
    script = request("/assets/app.js")
    mascot = request("/assets/booruradar-mascot.png")
    missing = request("/assets/not-present.js")

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert stylesheet.headers["cache-control"] == "public, max-age=3600"
    assert_security_headers(stylesheet)
    assert "@import" not in stylesheet.text
    assert "url(" not in stylesheet.text
    assert "prefers-reduced-motion" in stylesheet.text

    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert script.headers["cache-control"] == "public, max-age=3600"
    assert_security_headers(script)
    assert '"/api/v1/boorus?limit=100&offset=0"' in script.text
    assert "`/api/v1/boorus/${encodedId}`" in script.text
    assert "`/api/v1/boorus/${encodedId}/snapshots?limit=30`" in script.text
    assert "`/api/v1/boorus/${encodedId}/growth`" in script.text
    assert "`/api/v1/compare?${query.toString()}`" in script.text
    assert "/api/v1/rankings" not in script.text
    assert "aggregatePosts" not in script.text
    assert "innerHTML" not in script.text
    assert "https://" not in script.text
    assert 'fetch("http' not in script.text
    assert "fetch('http" not in script.text

    assert mascot.status_code == 200
    assert mascot.headers["content-type"].startswith("image/png")
    assert mascot.headers["cache-control"] == "public, max-age=86400"
    assert_security_headers(mascot)
    assert mascot.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(mascot.content) > 100_000

    assert missing.status_code == 404


def test_docs_and_openapi_remain_available() -> None:
    docs = request("/docs")
    openapi = request("/openapi.json")

    assert docs.status_code == 200
    assert "swagger-ui" in docs.text
    assert openapi.status_code == 200
    assert "/api/v1/boorus" in openapi.json()["paths"]
    assert "/api/v1/rankings" not in openapi.json()["paths"]
