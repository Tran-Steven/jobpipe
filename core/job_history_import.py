"""Conservative, private, atomic import of explicitly confirmed job-history CSV.

Required columns: job_url,status. Accepted statuses are APPLIED and DISMISSED
(or APPLIED_SELF_REPORTED). Title/company/source text cannot establish
submission history. Preview is read-only, commit is explicit and atomic.
"""

from __future__ import annotations

import csv
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .job_history import JobHistoryState, PrivateJobHistory
from .private_home import PrivateHome

_MAX_BYTES = 2_000_000
_MAX_ROWS = 10_000
_COLUMNS = frozenset({"job_url", "status"})
_HASH_COLUMNS = frozenset({"identity_hash", "status"})
_OPTIONAL_COLUMNS = frozenset({"source", "company", "title", "recorded_at"})
_HASH_PATTERN = re.compile(r"[a-f0-9]{64}")
_STATUS = {
    "APPLIED": JobHistoryState.APPLIED_SELF_REPORTED,
    "APPLIED_SELF_REPORTED": JobHistoryState.APPLIED_SELF_REPORTED,
    "DISMISSED": JobHistoryState.DISMISSED,
}


def _validated_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("history CSV recorded_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("history CSV recorded_at is invalid") from exc
    if parsed.tzinfo is None:
        raise ValueError("history CSV recorded_at requires timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _load_csv(
    path: Path,
) -> tuple[int, dict[str, JobHistoryState], dict[str, str], int]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("history CSV must be a regular, non-symlink file")
    if path.stat().st_size > _MAX_BYTES:
        raise ValueError("history CSV exceeds the size limit")
    identities: dict[str, JobHistoryState] = {}
    timestamps: dict[str, str] = {}
    rows = unmatched = 0
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, strict=True)
            columns = reader.fieldnames or []
            if len(columns) != len(set(columns)):
                raise ValueError("history CSV columns are invalid")
            url_schema = _COLUMNS.issubset(columns) and not ("identity_hash" in columns)
            hash_schema = _HASH_COLUMNS.issubset(columns) and not ("job_url" in columns)
            if not (url_schema or hash_schema) or (
                set(columns) - ((_COLUMNS if url_schema else _HASH_COLUMNS) | _OPTIONAL_COLUMNS)
            ):
                raise ValueError("history CSV columns are invalid")
            for record in reader:
                rows += 1
                if rows > _MAX_ROWS:
                    raise ValueError("history CSV exceeds the row limit")
                if None in record:
                    raise ValueError("history CSV row is malformed")
                raw_status = record.get("status")
                if not isinstance(raw_status, str):
                    raise ValueError("history CSV requires an explicit status")
                status = _STATUS.get(raw_status.strip().upper())
                if status is None:
                    raise ValueError("history CSV status must be APPLIED or DISMISSED")
                timestamp = _validated_timestamp(record.get("recorded_at"))
                raw_id = record.get("job_url" if url_schema else "identity_hash")
                if not isinstance(raw_id, str):
                    raise ValueError("history CSV row is malformed")
                raw_id = raw_id.strip()
                if url_schema:
                    if not raw_id:
                        unmatched += 1
                        continue  # Never guess a URL from company or title.
                    identity = PrivateJobHistory._identity(raw_id)
                else:
                    if _HASH_PATTERN.fullmatch(raw_id) is None:
                        raise ValueError("history identity_hash must be 64 lowercase hex chars")
                    identity = raw_id
                old = identities.get(identity)
                if old is not None and old is not status:
                    raise ValueError("conflicting history statuses for one posting identity")
                identities[identity] = status
                if timestamp is not None:
                    timestamps[identity] = max(timestamps.get(identity, timestamp), timestamp)
    except (csv.Error, UnicodeError) as exc:
        raise ValueError("history CSV could not be parsed safely") from exc
    if not rows:
        raise ValueError("history CSV contains no entries")
    return rows, identities, timestamps, unmatched


def _summary(
    items: dict[str, JobHistoryState],
    existing: dict[str, JobHistoryState],
    *,
    rows: int,
    committed: bool,
    unmatched: int,
) -> dict[str, Any]:
    conflicts = [
        key for key, state in items.items()
        if existing.get(key) is JobHistoryState.APPLIED_SELF_REPORTED
        and state is JobHistoryState.DISMISSED
    ]
    if conflicts:
        raise ValueError(
            "an existing confirmed application cannot be downgraded "
            "to dismissed; clear that mark explicitly first"
        )
    return {
        "committed": committed,
        "input_rows": rows,
        "unmatched_needs_review": unmatched,
        "unique_postings": len(items),
        "unchanged": sum(existing.get(k) is v for k, v in items.items()),
        "new_marks": sum(k not in existing for k in items),
        "upgraded_to_applied": sum(
            existing.get(k) is JobHistoryState.DISMISSED
            and v is JobHistoryState.APPLIED_SELF_REPORTED
            for k, v in items.items()
        ),
        "raw_urls_retained": False,
    }


def import_job_history_csv(
    csv_path: str | Path,
    *,
    home: PrivateHome | None = None,
    commit: bool = False,
) -> dict[str, Any]:
    if type(commit) is not bool:
        raise TypeError("commit must be a boolean")
    rows, original_identities, original_timestamps, unmatched = _load_csv(
        Path(csv_path).expanduser()
    )
    history = PrivateJobHistory(home)
    # Both discovery-stage and historically imported URLs can be linked to
    # the same independently verified employer requisition. Group by the ATS
    # hash before reporting counts, checking conflicts, or writing a mark.
    identities: dict[str, JobHistoryState] = {}
    groups: dict[str, set[str]] = {}
    group_timestamps: dict[str, str] = {}
    for identity_hash, state in original_identities.items():
        employer_hash, related = history.aliases.resolve_hash(identity_hash)
        existing_in_input = identities.get(employer_hash)
        if existing_in_input is not None and existing_in_input is not state:
            raise ValueError(
                "conflicting history statuses for one verified posting"
            )
        identities[employer_hash] = state
        imported_at = original_timestamps.get(identity_hash)
        if imported_at is not None:
            group_timestamps[employer_hash] = max(
                group_timestamps.get(employer_hash, imported_at), imported_at
            )
        groups.setdefault(employer_hash, set()).update(related)
    path = history.path
    if commit and not identities:
        raise ValueError("history CSV has no matchable postings; review missing URLs first")
    if path.is_symlink():
        raise ValueError("job history database cannot be a symlink")
    def _existing_states(connection: sqlite3.Connection) -> dict[str, JobHistoryState]:
        existing: dict[str, JobHistoryState] = {}
        for identity, related in groups.items():
            # A confirmed application anywhere in the linked group always wins.
            connected = tuple(sorted(related))
            states = {
                JobHistoryState(row[0])
                for row in connection.execute(
                    "SELECT state FROM job_history WHERE identity_hash IN ("
                    + ",".join("?" for _ in connected) + ")",
                    connected,
                ).fetchall()
            }
            if JobHistoryState.APPLIED_SELF_REPORTED in states:
                existing[identity] = JobHistoryState.APPLIED_SELF_REPORTED
            elif JobHistoryState.DISMISSED in states:
                existing[identity] = JobHistoryState.DISMISSED
        return existing

    if not commit:
        current: dict[str, JobHistoryState] = {}
        if path.is_file():
            # Query existing entries without initializing or writing anything.
            with sqlite3.connect(
                path.resolve().as_uri() + "?mode=ro", uri=True
            ) as conn:
                current = _existing_states(conn)
        return _summary(
            identities, current, rows=rows, committed=False, unmatched=unmatched
        )

    # The collision check is repeated *inside* the write transaction; another
    # importer cannot race a check and overwrite a confirmed application.
    with history._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = _existing_states(connection)
        result = _summary(
            identities, existing, rows=rows, committed=True, unmatched=unmatched
        )
        recorded_at = datetime.now(timezone.utc).isoformat()
        for identity, state in identities.items():
            if existing.get(identity) is state:
                continue
            connection.execute(
                "INSERT INTO job_history(identity_hash, state, recorded_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(identity_hash) DO UPDATE SET "
                "state=excluded.state, recorded_at=excluded.recorded_at",
                (identity, state.value, group_timestamps.get(identity, recorded_at)),
            )
    return result


def export_job_history_csv(
    csv_path: str | Path, *, home: PrivateHome | None = None
) -> dict[str, Any]:
    """Atomically export hash-only portable self-reported history, never URLs.

    The destination must not exist. No database or directory is created during
    export, and the created file is mode 0600. This is private user data even
    though the job URLs cannot be reconstructed from the hashes.
    """
    history = PrivateJobHistory(home)
    database = history.path
    if database.is_symlink():
        raise ValueError("job history database cannot be a symlink")
    if not database.is_file():
        raise ValueError("no job history database exists")
    target = Path(csv_path).expanduser()
    if target.is_symlink() or target.exists():
        raise ValueError("history export destination already exists")
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("history export directory is unavailable")
    with sqlite3.connect(
        database.resolve().as_uri() + "?mode=ro", uri=True, timeout=5
    ) as connection:
        rows = connection.execute(
            "SELECT identity_hash, state, recorded_at FROM job_history "
            "ORDER BY identity_hash LIMIT ?", (_MAX_ROWS + 1,)
        ).fetchall()
    if len(rows) > _MAX_ROWS:
        raise ValueError("history export exceeds the supported row limit")
    for identity, state, recorded_at in rows:
        if not isinstance(identity, str) or _HASH_PATTERN.fullmatch(identity) is None:
            raise ValueError("job history has an invalid identity")
        JobHistoryState(state)
        if _validated_timestamp(recorded_at) is None:
            raise ValueError("job history has an invalid timestamp")
    descriptor, temporary = tempfile.mkstemp(
        prefix=".job-history-export-", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            os.fchmod(handle.fileno(), 0o600)
            writer = csv.writer(handle)
            writer.writerow(("identity_hash", "status", "recorded_at"))
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        # Atomic, exclusive publish: never overwrite an existing user's backup,
        # even if another process creates it after the initial check.
        os.link(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {
        "exported_rows": len(rows),
        "raw_urls_retained": False,
        "contains_private_history": True,
    }


__all__ = ["import_job_history_csv", "export_job_history_csv"]
