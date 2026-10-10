"""Local-only, explicitly human-verified and narrowly scoped ATS answer candidates.

Matching is exact after whitespace/case normalization. Reuse never authorizes a
browser fill or Submit: existing human review remains mandatory. Conflicting
active answers fail closed rather than depending on record insertion order.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

_BANK_VERSION = 1
_MAX_BANK_BYTES = 2_000_000
_MAX_RECORDS = 10_000
_INACTIVE_STATUSES = frozenset({"withdrawn", "expired", "revoked"})


def normalize_question(question: str) -> str:
    if not isinstance(question, str):
        raise TypeError("question must be text")
    return re.sub(r"\s+", " ", question).strip().casefold()


def _eligible_now(record: Mapping[str, Any], now: datetime) -> bool:
    """Unknown, revoked or malformed answer evidence is never reusable."""
    answer = record.get("answer")
    if (
        record.get("human_verified") is not True
        or not isinstance(answer, str)
        or not answer.strip()
        or record.get("withdrawn") is not None
        and record.get("withdrawn") is not False
        or record.get("withdrawn_at") is not None
        or not isinstance(record.get("question"), str)
    ):
        return False
    status = record.get("status")
    if status is not None and (
        not isinstance(status, str)
        or status.strip().casefold() in _INACTIVE_STATUSES
    ):
        return False
    expires = record.get("expires_at")
    if expires is None:
        return True
    if not isinstance(expires, str):
        return False
    try:
        expiry = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except ValueError:
        return False
    return expiry.tzinfo is not None and expiry > now


def lookup_answer(
    records: list[dict[str, Any]],
    question: str,
    employer: str,
    *,
    now: datetime | None = None,
) -> dict[str, str] | None:
    """Find an unambiguous verified candidate; never guess from conflicting scopes.

    Exact employer matches outrank identical global answers for provenance
    display, but differing active values in either scope force human review.
    """
    current = datetime.now(timezone.utc) if now is None else now
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise ValueError("answer lookup time must be timezone-aware")
    normalized = normalize_question(question)
    if not isinstance(employer, str):
        raise TypeError("employer must be text")
    employer_key = employer.strip().casefold()
    if not normalized or not isinstance(records, list):
        return None
    matches: list[tuple[str, str]] = []
    for record in records:
        if not isinstance(record, dict) or not _eligible_now(record, current):
            continue
        if normalize_question(record["question"]) != normalized:
            continue
        scope = record.get("scope")
        if scope == "employer":
            stored_employer = record.get("employer")
            if (
                not isinstance(stored_employer, str)
                or not stored_employer.strip()
                or stored_employer.strip().casefold() != employer_key
            ):
                continue
        elif scope != "global":
            continue
        matches.append((scope, record["answer"].strip()))
    if not matches or len({answer for _, answer in matches}) != 1:
        # Never silently choose an earlier answer when two verified records
        # disagree, including across global and employer-specific scopes.
        return None
    scope = "employer" if any(s == "employer" for s, _ in matches) else "global"
    return {
        "status": "verified_candidate",
        "answer": matches[0][1],
        "scope": scope,
    }


def _validated_document(records: list[dict[str, Any]]) -> bytes:
    if not isinstance(records, list) or len(records) > _MAX_RECORDS:
        raise ValueError("answer bank must be a bounded list")
    if not all(
        isinstance(row, dict)
        and all(isinstance(key, str) for key in row)
        for row in records
    ):
        raise ValueError("answer bank entries must be objects with string keys")
    try:
        payload = (
            json.dumps({"version": _BANK_VERSION, "answers": records},
                       ensure_ascii=False, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("answer bank contains unsupported values") from exc
    if len(payload) > _MAX_BANK_BYTES:
        raise ValueError("answer bank exceeds private storage limit")
    return payload


def save_bank(path: Path, records: list[dict[str, Any]]) -> None:
    """Atomic, permission-restricted private file write (not an approval)."""
    path = Path(path)
    data = _validated_document(records)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("symlink answer bank forbidden")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("symlink answer bank forbidden")
    fd, name = tempfile.mkstemp(prefix=".answers-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise ValueError("symlink answer bank forbidden")
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_bank(path: Path) -> list[dict[str, Any]]:
    """Bounded private read, rejecting malformed entries and symlinks."""
    path = Path(path)
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("symlink answer bank forbidden")
    if not path.exists():
        return []
    if not path.is_file() or path.stat().st_size > _MAX_BANK_BYTES:
        raise ValueError("invalid answer bank file")
    try:
        # An additional size bound protects against a racing replacement.
        with path.open("rb") as stream:
            data = stream.read(_MAX_BANK_BYTES + 1)
        if len(data) > _MAX_BANK_BYTES:
            raise ValueError("answer bank exceeds private storage limit")
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid answer bank JSON") from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"version", "answers"}
        or type(document["version"]) is not int
        or document["version"] != _BANK_VERSION
    ):
        raise ValueError("invalid answer bank schema")
    records = document["answers"]
    _validated_document(records)
    return records
