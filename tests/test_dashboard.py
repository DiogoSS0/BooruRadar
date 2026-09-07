from __future__ import annotations

import asyncio
import re
from xml.etree import ElementTree

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
    assert "The booru ecosystem,<br> at a glance." in response.text
    assert response.text.count("<h1") == 1
    assert 'href="/assets/styles.css?v=editorial-v1"' in response.text
    assert 'src="/assets/app.js?v=editorial-v1"' in response.text
    assert 'src="/assets/booruradar-mascot.png"' in response.text
    assert 'alt="BooruRadar mascot holding a scanner"' in response.text
    assert 'href="/docs"' in response.text
    assert 'href="https://github.com/DiogoSS0/BooruRadar"' in response.text
    assert 'id="ranking-panel"' in response.text
    assert 'id="ranking-loading"' in response.text
    assert 'id="ranking-empty"' in response.text
    assert 'id="ranking-error"' in response.text
    assert 'id="ranking-body"' in response.text
    assert 'id="ranking-pagination"' in response.text
    assert '<table class="ranking-table">' in response.text
    assert "Ranking data temporarily unavailable." in response.text
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
    assert 'data-ranking-mode="largest"' in response.text
    assert 'data-ranking-mode="fastest_growth"' in response.text
    assert 'data-ranking-mode="relative_growth"' in response.text
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
    # Font loading is local; external assets remain disallowed.
    assert re.findall(r"url\(['\"]?([^)'\"]+)", stylesheet.text) == [
        "/assets/manrope-latin.woff2"
    ]
    assert "prefers-reduced-motion" in stylesheet.text

    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert script.headers["cache-control"] == "public, max-age=3600"
    assert_security_headers(script)
    assert "`/api/v1/rankings?${query.toString()}`" in script.text
    assert "`/api/v1/boorus/${encodedId}`" in script.text
    assert "`/api/v1/boorus/${encodedId}/snapshots?limit=30`" in script.text
    assert "`/api/v1/boorus/${encodedId}/growth`" in script.text
    assert "`/api/v1/compare?${query.toString()}`" in script.text
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


def test_identity_assets_are_self_hosted_and_font_policy_is_scoped() -> None:
    page = request("/")
    assert "font-src 'self';" in page.headers["content-security-policy"]
    assert "style-src 'self';" in page.headers["content-security-policy"]
    for filename in ("booruradar-wordmark.svg", "booruradar-icon.svg"):
        response = request(f"/assets/{filename}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/svg+xml")
        assert_security_headers(response)
        svg = ElementTree.fromstring(response.content)
        assert svg.tag == "{http://www.w3.org/2000/svg}svg"
        assert svg.find(".//{http://www.w3.org/2000/svg}path") is not None
        assert 'href="http' not in response.text
        assert "<script" not in response.text
    font = request("/assets/manrope-latin.woff2")
    assert font.status_code == 200
    assert font.headers["content-type"] == "font/woff2"
    assert font.content.startswith(b"wOF2")
    assert_security_headers(font)
    assert 'as="font" type="font/woff2" crossorigin' in page.text


def test_frontend_bindings_and_local_anchors_resolve_after_relayout() -> None:
    page = request("/").text
    script = request("/assets/app.js").text
    ids = re.findall(r'\bid="([^"]+)"', page)
    assert len(ids) == len(set(ids))
    for identifier in re.findall(r'document.querySelector\("#([^" ]+)"\)', script):
        assert identifier in ids, identifier
    for anchor in re.findall(r'href="#([^" ]+)"', page):
        assert anchor in ids, anchor


def test_ranking_frontend_preserves_backend_order_rank_and_pagination() -> None:
    script = request("/assets/app.js").text
    render_ranking = script.split("function renderRanking(payload)", maxsplit=1)[1].split(
        "function updateEcosystemSnapshot()", maxsplit=1
    )[0]

    assert "API order and rank are canonical" in render_ranking
    assert "payload.items.map(createRankingRow)" in render_ranking
    assert ".sort(" not in render_ranking
    assert "`#${item.rank}`" in script
    assert "state.rankingOffset += RANKING_LIMIT" in script
    assert "offset: String(offset)" in script
    assert "item.rank" in script


def test_ranking_frontend_keeps_unavailable_distinct_from_zero() -> None:
    script = request("/assets/app.js").text

    for reason in (
        "missing_total_posts",
        "invalid_total_posts",
        "insufficient_history",
        "incompatible_provenance",
        "incompatible_unit",
        "invalid_time_interval",
        "zero_baseline",
    ):
        assert reason in script
    assert 'Object.hasOwn(item, field)' in script
    assert '"No numeric substitute"' in script
    assert "value || 0" not in script
    assert "normalized === 0" not in script


def test_ranking_frontend_uses_api_metrics_without_formula_duplication() -> None:
    script = request("/assets/app.js").text

    assert 'item.unit === "posts/day"' in script
    assert 'item.unit === "posts"' in script
    assert "previous_total_posts" not in script
    assert "posts_per_day /" not in script
    assert "posts_delta /" not in script
    assert "relative_growth =" not in script


def test_ranking_frontend_exposes_provenance_and_accessible_states() -> None:
    page = request("/").text
    script = request("/assets/app.js").text

    for provenance in ("observed", "estimated", "owner_verified"):
        assert provenance in script
    assert 'href = "#methodology"' in script
    assert 'role="tablist"' in page
    assert 'role="tabpanel"' in page
    assert 'aria-live="polite"' in page
    assert 'id="ranking-retry"' in page


def test_docs_and_openapi_remain_available() -> None:
    docs = request("/docs")
    openapi = request("/openapi.json")

    assert docs.status_code == 200
    assert "swagger-ui" in docs.text
    assert openapi.status_code == 200
    assert "/api/v1/boorus" in openapi.json()["paths"]
    assert "/api/v1/rankings" in openapi.json()["paths"]
