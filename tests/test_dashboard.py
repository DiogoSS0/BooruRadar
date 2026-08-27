from __future__ import annotations

import asyncio

import httpx

from apps.api.main import create_app
from booruradar.core.config import Settings


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
    assert response.headers["content-security-policy"].startswith("default-src 'none'")
    assert response.headers["cross-origin-opener-policy"] == "same-origin"
    assert response.headers["permissions-policy"]
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"


def test_dashboard_is_local_get_only_html_with_defensive_headers() -> None:
    response = request("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert_security_headers(response)
    assert "Discover what's happening across the booru ecosystem." in response.text
    assert 'href="/assets/styles.css"' in response.text
    assert 'src="/assets/app.js"' in response.text
    assert "https://" not in response.text
    assert "http://" not in response.text
    assert "<img" not in response.text
    assert request("/", method="POST").status_code == 405


def test_dashboard_assets_are_fixed_local_responses() -> None:
    stylesheet = request("/assets/styles.css")
    script = request("/assets/app.js")
    missing = request("/assets/not-present.js")

    assert stylesheet.status_code == 200
    assert stylesheet.headers["content-type"].startswith("text/css")
    assert stylesheet.headers["cache-control"] == "public, max-age=3600"
    assert_security_headers(stylesheet)
    assert "@import" not in stylesheet.text
    assert "url(" not in stylesheet.text

    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert script.headers["cache-control"] == "public, max-age=3600"
    assert_security_headers(script)
    assert '"/api/v1/boorus?limit=100&offset=0"' in script.text
    assert "`/api/v1/boorus/${encodedId}`" in script.text
    assert "`/api/v1/compare?${query.toString()}`" in script.text
    assert "More history required" in script.text
    assert "Mixed provenance:" in script.text
    assert "innerHTML" not in script.text
    assert "https://" not in script.text
    assert "http://" not in script.text

    assert missing.status_code == 404


def test_docs_and_openapi_remain_available() -> None:
    docs = request("/docs")
    openapi = request("/openapi.json")

    assert docs.status_code == 200
    assert "swagger-ui" in docs.text
    assert openapi.status_code == 200
    assert "/api/v1/boorus" in openapi.json()["paths"]
