"""Sanitize read-only ATS field metadata for offline review snapshots."""
from __future__ import annotations
import json,os,tempfile
from pathlib import Path
from typing import Any,Mapping

_ALLOWED={"type","question","label","required","ambiguous"}

def sanitized_fields(fields:list[Mapping[str,Any]])->list[dict[str,Any]]:
    """Explicit allowlist excludes values, IDs, contact data and DOM attributes."""
    result=[]
    for field in fields:
        if not isinstance(field,Mapping):raise ValueError("field must be mapping")
        result.append({
          "type":str(field.get("type") or "")[:50],
          "question":str(field.get("question") or "")[:240],
          "label":str(field.get("label") or "")[:240],
          "required":field.get("required") is True,
          "ambiguous":field.get("ambiguous") is True,
        })
    return result

def save_snapshot(path:Path,fields:list[Mapping[str,Any]])->None:
    """Atomic, mode-0600 snapshot; refuse symlink target and directory."""
    path=Path(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("unsafe snapshot target")
    items=sanitized_fields(fields)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(prefix=".ats-fields-",dir=str(path.parent))
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(items,out,ensure_ascii=False)
            out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
