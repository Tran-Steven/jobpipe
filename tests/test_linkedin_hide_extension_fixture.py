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
window.__siteSubmitClicks = 0;
document.querySelector("#site-submit").addEventListener("click", () => window.__siteSubmitClicks++);
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
async def test_linkedin_extension_fixture_hide_block_undo_spa_and_no_submit(tmp_path: Path):
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(HTML)
            await page.add_script_tag(content=MOCK_STORAGE)
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
              cloned.classList.remove('jobpipe-visual-hidden');
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

            # No export occurs until a real user explicitly presses the
            # extension button. Exported records mean DISMISSED, never APPLIED.
            from core.job_history_import import import_job_history_csv
            from core.job_history import PrivateJobHistory, JobHistoryState
            from core.private_home import PrivateHome

            export_button = panel.get_by_role("button", name="Export dismissals")
            assert await export_button.is_enabled()
            async with page.expect_download() as download_event:
                await export_button.click()
            downloaded = await download_event.value
            assert downloaded.suggested_filename == "jobpipe-linkedin-dismissed.csv"
            csv_file = tmp_path / "browser-dismissals.csv"
            await downloaded.save_as(str(csv_file))
            data = csv_file.read_text(encoding="utf-8")
            assert "https://www.linkedin.com/jobs/view/101,DISMISSED" in data
            assert "APPLIED" not in data
            assert "acme" not in data.casefold()
            assert "102," not in data

            private = PrivateHome(tmp_path / "private-home")
            preview = import_job_history_csv(csv_file, home=private)
            assert preview["committed"] is False
            assert preview["unique_postings"] == 1
            assert not PrivateJobHistory(private).path.exists()
            committed = import_job_history_csv(csv_file, home=private, commit=True)
            assert committed["new_marks"] == 1
            assert PrivateJobHistory(private).state_for(
                "https://www.linkedin.com/jobs/view/101"
            ) is JobHistoryState.DISMISSED
            assert PrivateJobHistory(private).state_for(
                "https://www.linkedin.com/jobs/view/102"
            ) is None

            # The extension only changes local visibility/downloads its own CSV;
            # it never clicks a site's real submit/dismiss controls.
            applied_csv = tmp_path / "self-reported-applied.csv"
            applied_csv.write_text(
                "job_url,status\nhttps://www.linkedin.com/jobs/view/102,APPLIED\n",
                encoding="utf-8",
            )
            async with page.expect_file_chooser() as chooser:
                await panel.get_by_role("button", name="Import applied CSV").click()
            await (await chooser.value).set_files(str(applied_csv))
            await page.wait_for_function(
                "() => document.querySelector('#job-102').classList.contains('jobpipe-visual-hidden')"
            )
            imported = await page.evaluate("window.__localHistory['jobpipe.linkedin.hide.v1']")
            assert imported["appliedPostingIds"] == ["102"]
            assert imported["hiddenPostingIds"] == ["101"]
            assert PrivateJobHistory(private).state_for(
                "https://www.linkedin.com/jobs/view/102"
            ) is None

            applied_csv.write_text(
                "job_url,status\nhttps://evil.test/jobs/view/102,APPLIED\n",
                encoding="utf-8",
            )
            async with page.expect_file_chooser() as chooser:
                await panel.get_by_role("button", name="Import applied CSV").click()
            await (await chooser.value).set_files(str(applied_csv))
            await panel.get_by_text("CSV rejected.", exact=False).wait_for()
            unchanged = await page.evaluate("window.__localHistory['jobpipe.linkedin.hide.v1']")
            assert unchanged == imported

            await panel.get_by_role("button", name="Clear applied imports").click()
            await page.wait_for_function(
                "() => !document.querySelector('#job-102').classList.contains('jobpipe-visual-hidden')"
            )
            cleared = await page.evaluate("window.__localHistory['jobpipe.linkedin.hide.v1']")
            assert cleared["appliedPostingIds"] == []
            assert cleared["hiddenPostingIds"] == ["101"]

            from core.job_history_import import export_job_history_csv
            PrivateJobHistory(private).mark(
                "https://www.linkedin.com/jobs/view/102",
                JobHistoryState.APPLIED_SELF_REPORTED,
            )
            backup_file = tmp_path / "jobpipe-private-backup.csv"
            export_job_history_csv(backup_file, home=private)
            backup_text = backup_file.read_text(encoding="utf-8")
            assert "identity_hash,status,recorded_at" in backup_text
            assert "https://www.linkedin.com" not in backup_text
            async with page.expect_file_chooser() as chooser:
                await panel.get_by_role("button", name="Import Jobpipe backup").click()
            await (await chooser.value).set_files(str(backup_file))
            await page.wait_for_function(
                "() => document.querySelector('#job-102').dataset.jobpipeVisualHideReason === 'private-history-applied'"
            )
            imported_hashes = await page.evaluate("window.__localHistory['jobpipe.linkedin.hide.v1']")
            assert len(imported_hashes["historyAppliedHashes"]) == 1
            assert len(imported_hashes["historyDismissedHashes"]) == 1
            assert imported_hashes["appliedPostingIds"] == []
            assert imported_hashes["hiddenPostingIds"] == ["101"]

            bad_backup = tmp_path / "bad-private-backup.csv"
            bad_backup.write_text(
                backup_text.replace("APPLIED_SELF_REPORTED", "SUBMITTED_VERIFIED"),
                encoding="utf-8",
            )
            async with page.expect_file_chooser() as chooser:
                await panel.get_by_role("button", name="Import Jobpipe backup").click()
            await (await chooser.value).set_files(str(bad_backup))
            await panel.get_by_text("Jobpipe backup rejected.", exact=False).wait_for()
            after_bad = await page.evaluate("window.__localHistory['jobpipe.linkedin.hide.v1']")
            assert after_bad == imported_hashes

            await panel.get_by_role("button", name="Clear Jobpipe backup").click()
            await page.wait_for_function(
                "() => !document.querySelector('#job-102').classList.contains('jobpipe-visual-hidden')"
            )
            assert PrivateJobHistory(private).state_for(
                "https://www.linkedin.com/jobs/view/102"
            ) is JobHistoryState.APPLIED_SELF_REPORTED

            assert await page.locator("#site-submit").is_visible()
            assert await page.evaluate("window.__siteSubmitClicks") == 0
        finally:
            await browser.close()
