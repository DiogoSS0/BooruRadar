"""Read-only browser acceptance checks against a running API with real history.

Run with a Python environment containing playwright:
    python tests/browser/discovery.py http://127.0.0.1:8019 /tmp/booruradar-preview
"""
import json
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit

from playwright.sync_api import expect, sync_playwright


base = sys.argv[1].rstrip("/")
output = Path(sys.argv[2])
output.mkdir(parents=True, exist_ok=True)
checks = []
errors = []

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1366, "height": 900}, reduced_motion="reduce")
    page.on("pageerror", lambda error: errors.append(str(error)))

    def verify_view():
        expect(page.locator("#ranking-panel")).to_have_attribute("aria-busy", "false")
        query = urlsplit(page.url).query
        response = page.request.get(base + "/api/v1/rankings?limit=20&" + query)
        assert response.ok
        payload = response.json()
        expect(page.locator("#ranking-body tr")).to_have_count(len(payload["items"]))
        assert page.locator("#ranking-body .entity-button").all_text_contents() == [item["name"] for item in payload["items"]]
        ranks = page.locator("#ranking-body .rank-number").all_text_contents()
        for text, item in zip(ranks, payload["items"]):
            if item["eligible"]: assert text == f"#{item['rank']}"
        filters = [(key, value) for key, value in parse_qsl(query) if key not in ("offset", "mode", "limit")]
        all_query = urlencode([*filters, ("limit", "100")])
        catalog = page.request.get(base + "/api/v1/boorus?" + all_query).json()
        ranking = page.request.get(base + "/api/v1/rankings?" + all_query).json()
        assert {item["id"] for item in catalog["items"]} == {item["booru_id"] for item in ranking["items"]}
        return payload

    page.goto(base)
    taxonomy = page.request.get(base + "/api/v1/categories").json()["items"]
    expect(page.locator("#discovery-categories input")).to_have_count(len(taxonomy))
    expect(page.locator("#discovery-exclusions input")).to_have_count(len(taxonomy))
    expect(page.locator("#discovery-exclusions input").first).to_be_visible()
    expect(page.locator("#category-count")).to_have_text("0 selected")
    expect(page.locator("#exclusion-count")).to_have_text("0 selected")
    initial = verify_view()
    count = initial["total"]
    expect(page.locator("#snapshot-tracked")).to_have_text(str(count))
    checks.append(f"{count} real sources; browser rows and global ranks match the API")
    page.screenshot(path=str(output / "discovery-desktop.png"), full_page=True)

    if count > 20:
        page.locator("#ranking-next").click()
        page.wait_for_url("**offset=20*")
        second = verify_view()
        assert second["offset"] == 20
        assert not {item["booru_id"] for item in initial["items"]}.intersection(item["booru_id"] for item in second["items"])
        page.reload()
        assert verify_view()["offset"] == 20
        checks.append("Second page, global ranks and pagination restored from URL")

    page.locator("#discovery-rating").select_option("safe")
    page.wait_for_url("**content_rating=safe*")
    safe = verify_view()
    assert safe["offset"] == 0
    assert "offset=" not in page.url
    assert all(item["classification"]["content_rating"] == "safe" for item in safe["items"])
    expect(page.locator("#snapshot-tracked")).to_have_text(str(count))
    checks.append("Safe excludes mixed communities; ecosystem summary remains global")

    page.locator("#discovery-clear").click()
    verify_view()
    page.locator("#discovery-rating").select_option("nsfw")
    page.locator('#discovery-categories input[value="anime"]').check()
    page.locator('#discovery-exclusions input[value="ai-generated"]').check()
    expect(page.locator("#category-count")).to_have_text("1 selected")
    expect(page.locator("#exclusion-count")).to_have_text("1 selected")
    filtered = verify_view()
    page.reload()
    expect(page.locator('#discovery-categories input[value="anime"]')).to_be_checked()
    expect(page.locator('#discovery-exclusions input[value="ai-generated"]')).to_be_checked()
    expect(page.locator("#category-count")).to_have_text("1 selected")
    expect(page.locator("#exclusion-count")).to_have_text("1 selected")
    assert verify_view()["total"] == filtered["total"]
    for mode in ("fastest_growth", "relative_growth", "largest"):
        page.locator(f'[data-ranking-mode="{mode}"]').click()
        verify_view()
    checks.append("Combined categories and exclusions persist across reloads and ranking modes")

    page.locator("#discovery-clear").click()
    verify_view()
    page.locator('#discovery-categories input[value="anime"]').check()
    page.locator('#discovery-categories input[value="furry"]').check()
    all_total = verify_view()["total"]
    page.locator("#discovery-match").select_option("any")
    assert verify_view()["total"] >= all_total
    page.go_back()
    assert verify_view()["total"] == all_total
    checks.append("All/any matching, empty state and browser history")

    page.locator("#discovery-query").fill("no-matching-community-829317")
    page.locator("#discovery-query").press("Enter")
    page.wait_for_url("**q=no-matching-community-829317*")
    assert verify_view()["total"] == 0
    expect(page.locator("#ranking-empty")).to_be_visible()
    page.locator("#discovery-clear").click()
    verify_view()
    expect(page.locator("#category-count")).to_have_text("0 selected")
    expect(page.locator("#exclusion-count")).to_have_text("0 selected")
    page.locator("#ranking-body .entity-button").first.click()
    expect(page.locator("#detail-content")).to_be_visible()
    expect(page.locator("#detail-classification")).to_contain_text("Editorial classification")
    page.locator("#detail-close").click()
    if count >= 2:
        page.locator("[data-compare-id]").nth(0).check()
        page.locator("[data-compare-id]").nth(1).check()
        page.locator("#compare-button").click()
        expect(page.locator("#compare-body tr")).to_have_count(2)
        page.locator("#compare-close").click()
    checks.append("Search, clear, source detail, evidence and comparison")

    page.locator("#discovery-query").fill("e-shuushuu.net")
    page.wait_for_url("**q=e-shuushuu.net*")
    if verify_view()["total"]:
        page.locator("#ranking-body .entity-button").first.click()
        expect(page.locator("#detail-classification")).to_contain_text("artistic nudity")
        page.locator("#detail-close").click()
        checks.append("Editorial classification note is visible for a new source")
    page.locator("#discovery-clear").click()
    verify_view()

    for width in (320, 390, 768, 1100, 1101, 1366):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("() => document.documentElement.scrollWidth <= window.innerWidth")
        expect(page.locator("#discovery-exclusions input").first).to_be_visible()
        if width <= 390:
            assert page.locator(".category-option").evaluate_all("options => options.every(option => option.getBoundingClientRect().height >= 44)")
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator("#discovery-query").evaluate("input => input.blur()")
    page.evaluate("() => window.scrollTo(0, 0)")
    page.screenshot(path=str(output / "discovery-mobile.png"), full_page=True)
    category = page.locator('#discovery-categories input[value="anime"]')
    category.focus()
    page.keyboard.press("Space")
    expect(category).to_be_checked()
    expect(page.locator("#category-count")).to_have_text("1 selected")
    verify_view()
    page.locator(".filter-results-link").click()
    expect(page.locator("#ranking-results-start")).to_be_focused()
    page.locator("#discovery-clear").click()
    verify_view()
    page.locator("#discovery-query").focus()
    page.keyboard.press("Tab")
    expect(page.locator("#discovery-rating")).to_be_focused()
    checks.append("Both category groups visible at 320/390/768/1100/1101/1366 px; no page overflow; 44 px mobile targets")
    checks.append("Selection counts, keyboard toggles, search submission, clear and mobile result shortcut")

    page.route("**/api/v1/categories", lambda route: route.fulfill(status=503, content_type="application/json", body='{"detail":"temporarily unavailable"}'))
    page.goto(base + "/?category=anime&exclude_category=ai-generated")
    expect(page.locator("#discovery-error")).to_be_visible()
    expect(page.locator("#discovery-exclusions")).to_have_attribute("aria-busy", "false")
    page.unroute("**/api/v1/categories")
    page.locator("#discovery-retry").click()
    expect(page.locator("#discovery-error")).to_be_hidden()
    expect(page.locator("#category-count")).to_have_text("1 selected")
    expect(page.locator("#exclusion-count")).to_have_text("1 selected")
    verify_view()
    checks.append("Category failure and retry restore both groups and their URL selections")
    assert not errors, errors
    browser.close()

report = {"base_url": base, "checks": checks, "javascript_errors": errors, "data": "Real accepted history; no database writes or synthetic observations."}
(output / "discovery-validation.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
