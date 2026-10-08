"""Extract browser-visible question context for public ATS controls; never read values."""
from __future__ import annotations

# Evaluation reads labels and nearby question text only, never field values.
_FIELD_SCRIPT = r"""els => els.filter(e => !['hidden', 'password'].includes((e.type||'').toLowerCase())).map(e => {
  const clean = s => (s||'').replace(/\\s+/g,' ').trim().slice(0,240);
  const direct = clean((e.labels && Array.from(e.labels).map(l=>l.innerText).join(' ')) || e.getAttribute('aria-label') || '');
  const referenced = (e.getAttribute('aria-labelledby')||'').split(/\\s+/).map(id => document.getElementById(id)).filter(Boolean).map(x=>x.innerText).join(' ');
  const group = e.closest('fieldset,[role="group"],[role="radiogroup"]');
  const legend = group && group.querySelector('legend,[role="heading"],[data-question]');
  const leverQuestion = e.closest('li.application-question');
  // Restrict to the containing question; never traverse sibling questions.
  const leverLabel = leverQuestion && leverQuestion.querySelector('.application-label');
  const question = clean(referenced || (legend && legend.innerText) || (leverLabel && leverLabel.innerText) || '');
  return {type:(e.type||e.tagName).toLowerCase(), required:!!e.required || e.getAttribute('aria-required')==='true',
    label:direct,question:question,ambiguous:!question && (!direct || /^(yes|no)$/i.test(direct))};
})"""

async def extract_field_labels(page):
    """Read-only field metadata. Ambiguous Yes/No never becomes its own question."""
    return await page.locator("input,select,textarea").evaluate_all(_FIELD_SCRIPT)
