"""Read-only, answer-free annotations on deduplicated ATS human review items."""
from __future__ import annotations
from typing import Any
from tools.ats_verified_answer_bank import lookup_answer
from tools.ats_review_batch import build_review_batch

def build_review_with_verified_matches(fields: list[dict[str,Any]], verified_profile_keys: set[str], bank_records: list[dict[str,Any]], employer: str) -> dict[str,Any]:
    """Annotate exact scoped reuse; do not expose answers in output or change approval."""
    batch=build_review_batch(fields,verified_profile_keys)
    for item in batch["human_review"]:
        match=lookup_answer(bank_records,item["question"],employer)
        item["verified_answer_available"]=match is not None
        item["verified_answer_scope"]=match["scope"] if match else None
        # Even verified answers require the existing human-review gate.
        item["status"]="human_review"
    batch["verified_answer_match_count"]=sum(x["verified_answer_available"] for x in batch["human_review"])
    return batch
