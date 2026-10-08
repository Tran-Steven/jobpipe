"""Isolated browser fixture: question context must not be invented."""
import pytest
from tools.ats_field_labels import extract_field_labels

@pytest.mark.asyncio
async def test_grouped_yes_no_and_unlabeled_fields():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        try:
            page=await browser.new_page()
            await page.set_content("""<form>
              <fieldset><legend>Will you require sponsorship?</legend>
                <label><input type="radio" name="sponsor" required>Yes</label>
                <label><input type="radio" name="sponsor">No</label>
              </fieldset>
              <label for="mail">Email</label><input id="mail" type="email" required>
              <input type="checkbox" aria-label="Yes" required>
              <input type="hidden" value="private-secret">
              </form>""")
            fields=await extract_field_labels(page)
            assert len(fields)==4
            assert fields[0]["question"]=="Will you require sponsorship?"
            assert fields[0]["label"]=="Yes" and not fields[0]["ambiguous"]
            assert fields[1]["question"]=="Will you require sponsorship?"
            assert fields[2]["label"]=="Email" and not fields[2]["ambiguous"]
            assert fields[3]["ambiguous"] and fields[3]["question"]==""
            assert "private-secret" not in str(fields)
        finally:
            await browser.close()
