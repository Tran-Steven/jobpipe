"""Explicitly verified, scoped local answer bank. No autonomous approval or submission."""
from __future__ import annotations
import json,os,re,tempfile
from pathlib import Path
from typing import Any

def normalize_question(question: str) -> str:
    return re.sub(r"\\s+"," ",question).strip().casefold()

def lookup_answer(records: list[dict[str,Any]], question: str, employer: str) -> dict[str,str] | None:
    """No fuzzy matching; global reuse requires explicit global scope and verification."""
    normalized=normalize_question(question)
    employer=employer.strip().casefold()
    for record in records:
        if not record.get("human_verified") or not record.get("answer"):
            continue
        if normalize_question(str(record.get("question","")))!=normalized:
            continue
        scope=record.get("scope")
        if scope=="employer" and str(record.get("employer","")).strip().casefold()!=employer:
            continue
        if scope!="global" and scope!="employer":
            continue
        return {"status":"verified_candidate","answer":str(record["answer"]),"scope":scope}
    return None

def save_bank(path: Path, records: list[dict[str,Any]]) -> None:
    """Atomic private file write. Caller supplies path outside repository."""
    path=Path(path)
    if path.exists() and path.is_symlink():raise ValueError("symlink bank forbidden")
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix=".answers-",dir=str(path.parent))
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump({"version":1,"answers":records},stream,ensure_ascii=False)
            stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def load_bank(path: Path) -> list[dict[str,Any]]:
    path=Path(path)
    if path.is_symlink():raise ValueError("symlink bank forbidden")
    if not path.exists():return []
    payload=json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version")!=1 or not isinstance(payload.get("answers"),list):
        raise ValueError("invalid answer bank schema")
    return payload["answers"]
