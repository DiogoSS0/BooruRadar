"""Read-only browser acceptance checks against a running API with real history.

Run with a Python environment containing playwright:
    python tests/browser/discovery.py http://127.0.0.1:8019 /tmp/booruradar-preview
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

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
        return payload

    page.goto(base)
    expect(page.locator("#discovery-categories input")).to_have_count(10)
    initial = verify_view()
    count = initial["total"]
    expect(page.locator("#snapshot-tracked")).to_have_text(str(count))
    checks.append(f"{count} real sources; browser rows and global ranks match the API")
    page.screenshot(path=str(output / "discovery-desktop.png"), full_page=True)

    page.locator("#discovery-rating").select_option("safe")
    page.wait_for_url("**content_rating=safe*")
    safe = verify_view()
    assert all(item["classification"]["content_rating"] == "safe" for item in safe["items"])
    expect(page.locator("#snapshot-tracked")).to_have_text(str(count))
    checks.append("Safe excludes mixed communities; ecosystem summary remains global")

    page.locator("#discovery-clear").click()
    verify_view()
    page.locator("#discovery-rating").select_option("nsfw")
    page.locator('#discovery-categories input[value="anime"]').check()
    page.locator("#discovery-advanced summary").click()
    page.locator('#discovery-exclusions input[value="ai-generated"]').check()
    filtered = verify_view()
    page.reload()
    expect(page.locator('#discovery-categories input[value="anime"]')).to_be_checked()
    expect(page.locator('#discovery-exclusions input[value="ai-generated"]')).to_be_checked()
    assert verify_view()["total"] == filtered["total"]
    for mode in ("fastest_growth", "relative_growth", "largest"):
        page.locator(f'[data-ranking-mode="{mode}"]').click()
        verify_view()
    checks.append("Combined categories and exclusions persist across reloads and ranking modes")

    page.locator("#discovery-clear").click()
    verify_view()
    page.locator('#discovery-categories input[value="anime"]').check()
    page.locator('#discovery-categories input[value="furry"]').check()
    assert verify_view()["total"] == 0
    page.locator("#discovery-advanced summary").click()
    page.locator("#discovery-match").select_option("any")
    assert verify_view()["total"] > 0
    page.go_back()
    assert verify_view()["total"] == 0
    checks.append("All/any matching, empty state and browser history")

    page.locator("#discovery-query").fill("no-matching-community-829317")
    page.wait_for_url("**q=no-matching-community-829317*")
    assert verify_view()["total"] == 0
    expect(page.locator("#ranking-empty")).to_be_visible()
    page.locator("#discovery-clear").click()
    verify_view()
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

    for width in (320, 390, 768, 1366):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.set_viewport_size({"width": 390, "height": 844})
    page.screenshot(path=str(output / "discovery-mobile.png"), full_page=True)
    page.locator("#discovery-query").focus()
    page.keyboard.press("Tab")
    expect(page.locator("#discovery-rating")).to_be_focused()
    checks.append("No horizontal page overflow at 320/390/768/1366 px; keyboard navigation")
    assert not errors, errors
    browser.close()

report = {"base_url": base, "checks": checks, "javascript_errors": errors, "data": "Real accepted history; no database writes or synthetic observations."}
(output / "discovery-validation.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
