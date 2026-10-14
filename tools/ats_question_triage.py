"""Conservative triage of read-only ATS field metadata (never answers or submits)."""
from __future__ import annotations

import re
from typing import Any, Mapping

_CONTACT = {
    "full_name": re.compile(r"^full\s+name\s*[*✱]?$",re.I),
    "email": re.compile(r"^(?:e-?mail|email address)\s*[*✱]?$",re.I),
    "phone": re.compile(r"^(?:phone|phone number|mobile|telephone)\s*[*✱]?$",re.I),
    "linkedin": re.compile(r"^(?:linkedin(?: url| profile)?)\s*[*✱]?$",re.I),
    "github": re.compile(r"^(?:github(?: url| profile)?)\s*[*✱]?$",re.I),
}
def classify_field(field: Mapping[str, Any], verified_keys: set[str] | frozenset[str]) -> dict[str, str]:
    """Return a routing decision, not an answer. Unknowns always require review.

    Verified keys grant only *candidate mapping*, never automatic form filling.
    """
    for metadata_key in ('question', 'label'):
        if metadata_key in field and not isinstance(field[metadata_key], str):
            return {'status': 'human_review', 'reason': 'invalid_field_metadata'}
    if 'label' in field and field['label'] and not field['label'].strip():
        return {'status': 'human_review', 'reason': 'invalid_field_metadata'}
    question = re.sub(r"\s+", " ", str(field.get("question") or field.get("label") or "")).strip()
    label = re.sub(r"\s+", " ", str(field.get("label") or "")).strip()
    kind = str(field.get("type") or "").lower()
    if field.get("ambiguous", False) is not False or not question:
        return {"status":"human_review","reason":"ambiguous_question"}
    if kind not in {"text", "email", "tel", "url"}:
        return {"status":"human_review","reason":"nontrivial_control"}
    expected_kinds = {
        "full_name": "text",
        "email": "email",
        "phone": "tel",
        "linkedin": "url",
        "github": "url",
    }
    for key, pattern in _CONTACT.items():
        if pattern.fullmatch(question) and (not label or pattern.fullmatch(label)):
            if kind not in {"text", expected_kinds[key]}:
                return {"status":"human_review","reason":"mismatched_contact_control"}
            if key in verified_keys:
                return {"status":"verified_candidate","profile_key":key}
            return {"status":"human_review","reason":"unverified_profile_fact"}
    return {"status":"human_review","reason":"unknown_question"}

def triage_fields(fields: list[Mapping[str, Any]], verified_keys: set[str] | frozenset[str]) -> list[dict[str, str]]:
    return [classify_field(field,verified_keys) for field in fields]
