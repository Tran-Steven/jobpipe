"""Conservative, private, atomic import of explicitly confirmed job-history CSV.

Required columns: job_url,status. Accepted statuses are APPLIED and DISMISSED
(or APPLIED_SELF_REPORTED). Title/company/source text cannot establish
submission history. Preview is read-only, commit is explicit and atomic.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any

from .job_history import JobHistoryState, PrivateJobHistory
from .private_home import PrivateHome

_MAX_BYTES = 2_000_000
_MAX_ROWS = 10_000
_COLUMNS = frozenset({"job_url", "status"})
_OPTIONAL_COLUMNS = frozenset({"source", "company", "title"})
_STATUS = {
    "APPLIED": JobHistoryState.APPLIED_SELF_REPORTED,
    "APPLIED_SELF_REPORTED": JobHistoryState.APPLIED_SELF_REPORTED,
    "DISMISSED": JobHistoryState.DISMISSED,
}


def _load_csv(path: Path) -> tuple[int, dict[str, JobHistoryState]]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("history CSV must be a regular, non-symlink file")
    if path.stat().st_size > _MAX_BYTES:
        raise ValueError("history CSV exceeds the size limit")
    identities: dict[str, JobHistoryState] = {}
    rows = 0
    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle, strict=True)
            columns = reader.fieldnames or []
            if (
                len(columns) != len(set(columns))
                or not _COLUMNS.issubset(columns)
                or set(columns) - (_COLUMNS | _OPTIONAL_COLUMNS)
            ):
                raise ValueError("history CSV columns are invalid")
            for record in reader:
                rows += 1
                if rows > _MAX_ROWS:
                    raise ValueError("history CSV exceeds the row limit")
                if None in record or not isinstance(record.get("job_url"), str):
                    raise ValueError("history CSV row is malformed")
                raw_status = record.get("status")
                if not isinstance(raw_status, str):
                    raise ValueError("history CSV requires an explicit status")
                status = _STATUS.get(raw_status.strip().upper())
                if status is None:
                    raise ValueError(
                        "history CSV status must be APPLIED or DISMISSED"
                    )
                identity = PrivateJobHistory._identity(record["job_url"])
                old = identities.get(identity)
                if old is not None and old is not status:
                    raise ValueError(
                        "conflicting history statuses for one posting identity"
                    )
                identities[identity] = status
    except (csv.Error, UnicodeError) as exc:
        raise ValueError("history CSV could not be parsed safely") from exc
    if not rows:
        raise ValueError("history CSV contains no entries")
    return rows, identities


def _summary(
    items: dict[str, JobHistoryState],
    existing: dict[str, JobHistoryState],
    *,
    rows: int,
    committed: bool,
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
    rows, original_identities = _load_csv(Path(csv_path).expanduser())
    history = PrivateJobHistory(home)
    # Both discovery-stage and historically imported URLs can be linked to
    # the same independently verified employer requisition. Group by the ATS
    # hash before reporting counts, checking conflicts, or writing a mark.
    identities: dict[str, JobHistoryState] = {}
    groups: dict[str, set[str]] = {}
    for identity_hash, state in original_identities.items():
        employer_hash, related = history.aliases.resolve_hash(identity_hash)
        existing_in_input = identities.get(employer_hash)
        if existing_in_input is not None and existing_in_input is not state:
            raise ValueError(
                "conflicting history statuses for one verified posting"
            )
        identities[employer_hash] = state
        groups.setdefault(employer_hash, set()).update(related)
    path = history.path
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
        return _summary(identities, current, rows=rows, committed=False)

    # The collision check is repeated *inside* the write transaction; another
    # importer cannot race a check and overwrite a confirmed application.
    from datetime import datetime, timezone

    with history._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        existing = _existing_states(connection)
        result = _summary(identities, existing, rows=rows, committed=True)
        recorded_at = datetime.now(timezone.utc).isoformat()
        for identity, state in identities.items():
            if existing.get(identity) is state:
                continue
            connection.execute(
                "INSERT INTO job_history(identity_hash, state, recorded_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(identity_hash) DO UPDATE SET "
                "state=excluded.state, recorded_at=excluded.recorded_at",
                (identity, state.value, recorded_at),
            )
    return result


__all__ = ["import_job_history_csv"]
