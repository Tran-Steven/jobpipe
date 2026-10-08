"""Explicit human answer verification with scoped persistence; never submits applications."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from tools.ats_verified_answer_bank import load_bank,save_bank,normalize_question

def approve_answer(bank_path:Path,review_items:list[dict[str,Any]],*,review_id:str,
                   answer:str,scope:str,employer:str,human_confirmed:bool)->dict[str,Any]:
    """No implicit confirmation; ensure review item exists, then save only after opt-in."""
    if human_confirmed is not True:
        raise ValueError("explicit human confirmation required")
    if scope not in {"employer","global"}:
        raise ValueError("invalid answer scope")
    if not isinstance(answer,str) or not answer.strip():
        raise ValueError("answer required")
    if not isinstance(review_id,str) or not review_id:
        raise ValueError("review id required")
    matches=[item for item in review_items if item.get("id")==review_id and item.get("status")=="human_review"]
    if len(matches)!=1:raise ValueError("review id not uniquely found")
    item=matches[0]
    question=str(item.get("question") or "").strip()
    if not question or question=="Unlabeled field":
        raise ValueError("ambiguous question cannot be verified")
    if scope=="employer" and not employer.strip():
        raise ValueError("employer name required")
    records=load_bank(bank_path)
    normalized=normalize_question(question)
    for record in records:
        if normalize_question(str(record.get("question","")))!=normalized:continue
        if record.get("scope")!=scope:continue
        if scope=="employer" and str(record.get("employer","")).casefold().strip()!=employer.casefold().strip():continue
        raise ValueError("answer already exists; update requires separate reviewed workflow")
    records.append({"question":question,"answer":answer.strip(),"scope":scope,
                    "employer":employer.strip() if scope=="employer" else "",
                    "human_verified":True})
    save_bank(bank_path,records)
    return {"saved":True,"review_id":review_id,"scope":scope,"submission":"not_attempted"}
