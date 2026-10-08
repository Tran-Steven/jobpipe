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


@pytest.mark.asyncio
async def test_realistic_lever_custom_question_grouping():
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        try:
            page=await browser.new_page()
            await page.set_content("""<ul>
              <li class="application-question custom-question">
                <div class="application-label full-width">Do you use AI in your role? ✱</div>
                <div class="application-field full-width required-field"><ul>
                  <li><label><input type="radio" name="ai" required><span class="application-answer-alternative">Yes</span></label></li>
                  <li><label><input type="radio" name="ai"><span class="application-answer-alternative">No</span></label></li>
                </ul></div>
              </li>
              <li class="application-question custom-question">
                <div class="application-label full-width textarea">How have you used AI in your role? ✱</div>
                <div class="application-field full-width required-field"><textarea required></textarea></div>
              </li>
              <li class="application-question custom-question">
                <div class="application-label full-width dropdown">Which location are you based in? ✱</div>
                <div class="application-field full-width required-field"><select required><option>Select...</option></select></div>
              </li>
              <li class="application-question custom-question">
                <div class="application-field full-width required-field"><label><input type="radio" name="unknown">Yes</label></div>
              </li>
              </ul>""")
            data=await extract_field_labels(page)
            assert len(data)==5
            assert all(x['question'].startswith("Do you use AI") for x in data[:2])
            assert not any(x['ambiguous'] for x in data[:4])
            assert data[2]['question'].startswith("How have you used AI")
            assert data[3]['question'].startswith("Which location")
            assert data[4]['question']=="" and data[4]['ambiguous']
            assert "How have you used AI" not in data[0]['question']
        finally:
            await browser.close()
