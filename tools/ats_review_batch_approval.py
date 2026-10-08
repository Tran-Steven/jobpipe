"""Explicit, all-or-nothing human-confirmed batch answer verification; no submissions."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from tools.ats_verified_answer_bank import load_bank,save_bank,normalize_question

def approve_batch(bank_path:Path,review_items:list[dict[str,Any]],decisions:list[dict[str,Any]],*,human_confirmed:bool)->dict[str,Any]:
    """Validate *every* decision before one private atomic write.

    Each item requires its own affirmative human_verified flag, not only a batch flag.
    No stored answer values are returned in summaries.
    """
    if human_confirmed is not True:raise ValueError("explicit batch confirmation required")
    if not decisions:raise ValueError("no decisions")
    records=load_bank(bank_path)
    seen=set()
    staged=[]
    for d in decisions:
        if d.get("human_verified") is not True:raise ValueError("each answer requires explicit human verification")
        rid=d.get("review_id")
        if not isinstance(rid,str) or not rid or rid in seen:raise ValueError("duplicate or invalid review id")
        seen.add(rid)
        matches=[x for x in review_items if x.get("id")==rid and x.get("status")=="human_review"]
        if len(matches)!=1:raise ValueError("review id must uniquely exist")
        question=str(matches[0].get("question") or "").strip()
        if not question or question=="Unlabeled field":raise ValueError("ambiguous question")
        answer=d.get("answer")
        if not isinstance(answer,str) or not answer.strip():raise ValueError("answer required")
        scope=d.get("scope");employer=str(d.get("employer") or "").strip()
        if scope not in {"employer","global"} or (scope=="employer" and not employer):raise ValueError("invalid answer scope")
        candidate={"question":question,"answer":answer.strip(),"scope":scope,"employer":employer if scope=="employer" else "","human_verified":True}
        def key(rec):
            return (normalize_question(str(rec.get("question") or "")),rec.get("scope"),str(rec.get("employer") or "").casefold().strip() if rec.get("scope")=="employer" else "")
        if any(key(x)==key(candidate) for x in records+staged):raise ValueError("duplicate scoped answer")
        staged.append(candidate)
    save_bank(bank_path,records+staged)
    return {"saved_count":len(staged),"scope_counts":{"global":sum(x["scope"]=="global" for x in staged),"employer":sum(x["scope"]=="employer" for x in staged)},"submission":"not_attempted"}
