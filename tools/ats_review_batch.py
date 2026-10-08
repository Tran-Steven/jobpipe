"""Build a local human-review queue from read-only ATS metadata; no answers stored."""
from __future__ import annotations
import hashlib
import json
import re
from typing import Any,Mapping
from tools.ats_question_triage import triage_fields

def _clean(value: Any) -> str:
    return re.sub(r"\\s+"," ",str(value or "")).strip()[:240]

def build_review_batch(fields: list[Mapping[str,Any]], verified_keys: set[str] | frozenset[str]) -> dict[str,Any]:
    """Deduplicate same-question controls; required unknowns before optional items.

    No DOM values, names, emails, raw input attrs, or other candidate answers are copied.
    A verified_candidate is only a proposed mapping, never permission to fill.
    """
    routed=triage_fields(fields,verified_keys)
    groups={}
    candidates=[]
    for field,route in zip(fields,routed):
        question=_clean(field.get("question") or field.get("label")) or "Unlabeled field"
        required=bool(field.get("required"))
        if route["status"]=="verified_candidate":
            candidates.append({"profile_key":route["profile_key"],"question":question,"required":required})
            continue
        # Identical Yes/No radios are a single human decision, not two questions.
        key=(question.casefold(),str(field.get("type") or "").lower() if question=="Unlabeled field" else "")
        if key not in groups:
            fingerprint=hashlib.sha256(json.dumps(key).encode()).hexdigest()[:16]
            groups[key]={"id":fingerprint,"question":question,"required":required,"reason":route["reason"],"control_count":0}
        groups[key]["required"] |= required
        groups[key]["control_count"] += 1
    review=sorted(groups.values(),key=lambda x:(not x["required"],x["question"].casefold(),x["id"]))
    return {"verified_candidates":candidates,"human_review":review,"input_field_count":len(fields),
            "review_item_count":len(review),"submission":"not_attempted"}
