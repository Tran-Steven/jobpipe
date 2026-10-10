"""Synthetic Chromium verification of local-only LinkedIn visual hiding.

No request to LinkedIn, network authentication, job application, or site
dismissal endpoint is performed in these tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1] / "extensions" / "linkedin-hide"

HTML = """
<html><body>
<button id="site-submit" type="button">Submit application</button>
<ol id="results">
  <li class="jobs-search-results__list-item" id="job-101" data-job-id="101">
    <div class="job-card-container__company-name">Acme</div>
    <a href="/jobs/view/101">Role One</a>
  </li>
  <li class="jobs-search-results__list-item" id="job-102" data-job-id="102">
    <div class="job-card-container__company-name">Other Company</div>
    <a href="/jobs/view/102">Role Two</a>
  </li>
  <li class="jobs-search-results__list-item" id="job-103" data-job-id="103">
    <div class="job-card-container__company-name">Acme</div>
    <a href="/jobs/view/103">Role Three</a>
  </li>
  <li class="jobs-search-results__list-item" id="no-posting-id">
    <div class="job-card-container__company-name">Unidentified</div>
    <span>Unknown ID role</span>
  </li>
</ol>
</body></html>
"""
MOCK_STORAGE = """
window.__localHistory = {};
window.__storageListeners = [];
window.browser = {
  storage: {
    local: {
      async get(key) { return { [key]: window.__localHistory[key] }; },
      async set(value) {
        for (const [key, val] of Object.entries(value)) {
          const previous = window.__localHistory[key];
          window.__localHistory[key] = structuredClone(val);
          const changes = { [key]: { oldValue: previous, newValue: val } };
          for (const listener of window.__storageListeners) listener(changes, "local");
        }
      }
    },
    onChanged: { addListener(fn) { window.__storageListeners.push(fn); } }
  }
};
"""


@pytest.mark.asyncio
async def test_linkedin_extension_fixture_hide_block_undo_spa_and_no_submit():
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(HTML)
            await page.evaluate(MOCK_STORAGE)
            await page.add_style_tag(path=str(ROOT / "style.css"))
            await page.add_script_tag(path=str(ROOT / "rules.js"))
            await page.add_script_tag(path=str(ROOT / "content.js"))
            panel = page.locator("#jobpipe-visual-hide-panel")
            await panel.wait_for()
            assert await panel.is_visible()

            no_id = page.locator("#no-posting-id")
            assert await no_id.get_by_role("button", name="Hide posting").is_disabled()

            await page.locator("#job-101").get_by_role("button", name="Hide posting").click()
            await page.wait_for_function(
                "() => document.querySelector('#job-101').classList.contains('jobpipe-visual-hidden')"
            )
            assert await page.locator("#job-102").is_visible()
            stored = await page.evaluate("window.__localHistory['jobpipe.linkedin.hide.v1']")
            assert stored["hiddenPostingIds"] == ["101"]
            assert stored["blockedCompanies"] == []
            assert "linkedin.com" not in str(stored)

            await panel.get_by_role("button", name="Undo").click()
            await page.wait_for_function(
                "() => !document.querySelector('#job-101').classList.contains('jobpipe-visual-hidden')"
            )
            stored = await page.evaluate("window.__localHistory['jobpipe.linkedin.hide.v1']")
            assert stored["hiddenPostingIds"] == []

            await page.locator("#job-101").get_by_role("button", name="Block employer").click()
            await page.wait_for_function(
                "() => document.querySelector('#job-103').classList.contains('jobpipe-visual-hidden')"
            )
            assert await page.locator("#job-102").is_visible()
            await panel.get_by_role("button", name="Review blocked").click()
            assert await panel.get_by_text("acme", exact=True).is_visible()
            await panel.get_by_role("button", name="Unblock").click()
            await page.wait_for_function(
                "() => !document.querySelector('#job-103').classList.contains('jobpipe-visual-hidden')"
            )

            await page.locator("#job-101").get_by_role("button", name="Hide posting").click()
            await page.wait_for_function(
                "() => document.querySelector('#job-101').classList.contains('jobpipe-visual-hidden')"
            )
            await page.evaluate("""() => {
              const cloned = document.querySelector('#job-101').cloneNode(true);
              cloned.id = 'job-101-spa';
              document.querySelector('#results').append(cloned);
            }""")
            await page.wait_for_function(
                "() => document.querySelector('#job-101-spa').classList.contains('jobpipe-visual-hidden')"
            )
            await panel.get_by_role("button", name="Show matched").click()
            assert await page.locator("#job-101").is_visible()
            assert await page.locator("#job-101-spa").is_visible()
            await panel.get_by_role("button", name="Hide matched").click()
            assert not await page.locator("#job-101").is_visible()
            assert not await page.locator("#job-101-spa").is_visible()

            # The extension only manipulates local DOM visibility; it never
            # clicks a site's real submit/dismiss controls.
            assert await page.locator("#site-submit").is_visible()
            assert await page.locator("#site-submit").evaluate(
                "(element) => element.dataset.clicked || ''"
            ) == ""
        finally:
            await browser.close()
