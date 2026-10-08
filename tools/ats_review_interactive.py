"""Human-only terminal review; explicit confirmation required before private answer save."""
from __future__ import annotations
from pathlib import Path
from typing import Any,Callable
from tools.ats_review_batch_approval import approve_batch

def review_interactively(bank_path:Path,review_items:list[dict[str,Any]],employer:str,
                         *,input_fn:Callable[[str],str]=input,print_fn:Callable[[str],None]=print)->dict[str,Any]:
    """Optional answers may be skipped; approvals cannot be inferred from keystrokes."""
    decisions=[]
    ordered=sorted(review_items,key=lambda x:(not bool(x.get("required")),str(x.get("question") or "")))
    for item in ordered:
        if item.get("status")!="human_review":continue
        q=str(item.get("question") or "")
        print_fn(("[Required] " if item.get("required") else "[Optional] ")+q)
        answer=input_fn("Answer (blank to skip): ")
        if not answer.strip():continue
        scope=input_fn("Reuse scope [employer/global] (blank to skip): ").strip().lower()
        if scope not in {"employer","global"}:
            print_fn("Skipped: invalid or absent scope")
            continue
        verified=input_fn("Verify THIS answer? Type VERIFY: ").strip()
        if verified!="VERIFY":
            print_fn("Skipped: not individually verified")
            continue
        decisions.append({"review_id":item.get("id"),"answer":answer,"scope":scope,
                          "employer":employer if scope=="employer" else "",
                          "human_verified":True})
    if not decisions:
        return {"saved_count":0,"submission":"not_attempted"}
    if input_fn("Save this verified answer batch? Type SAVE: ").strip()!="SAVE":
        return {"saved_count":0,"submission":"not_attempted"}
    return approve_batch(bank_path,review_items,decisions,human_confirmed=True)
