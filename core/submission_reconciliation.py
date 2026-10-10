"""Non-mutating, evidence-aware reconciliation report for posting submissions.

Never infers success from a page dismissal, an email subject, or a timeout.
Unresolved submission intents remain blocked by the application's preflight.
"""

from __future__ import annotations

from enum import StrEnum
import json
import sqlite3
from typing import Any

from .event_ledger import (
    EventLedger,
    SubmissionStatus,
    hash_job_url,
)
from .job_history import JobHistoryState, PrivateJobHistory
from .private_home import PrivateHome
from .verified_posting_aliases import VerifiedPostingAliases


class ReviewAction(StrEnum):
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    AWAITING_EMPLOYER = "AWAITING_EMPLOYER"
    ESCALATED = "ESCALATED"
    NO_CONFIRMATION_FOUND = "NO_CONFIRMATION_FOUND"


class ReconciliationStatus(StrEnum):
    NEVER_SUBMITTED = "NEVER_SUBMITTED"
    MANUALLY_REPORTED = "MANUALLY_REPORTED"
    DISMISSED = "DISMISSED"
    VERIFIED = "VERIFIED"
    UNRESOLVED = "UNRESOLVED"


def inspect_submission(
    url: str, *, home: PrivateHome | None = None
) -> dict[str, Any]:
    """Read durable state without changing submission intent or issuing permits."""
    root = home or PrivateHome.discover()
    # Validate before reading anything or disclosing a hash.
    PrivateJobHistory._identity(url)
    identity = hash_job_url(url)
    ledger_path = root.paths.event_ledger
    history_state = PrivateJobHistory(root).state_for(url)

    if ledger_path.is_symlink():
        raise ValueError("submission ledger cannot be a symlink")
    intent = None
    review_actions: list[dict[str, str]] = []
    if ledger_path.is_file():
        # SQLite URI mode=ro prevents creating or modifying the event ledger.
        # This command is an inspection only, never a reconciliation mutation.
        hashes = VerifiedPostingAliases(root).identity_hashes(url)
        placeholders = ", ".join("?" for _ in hashes)
        statuses = (
            SubmissionStatus.PENDING.value,
            SubmissionStatus.SUBMITTING.value,
            SubmissionStatus.UNKNOWN.value,
            SubmissionStatus.VERIFIED.value,
        )
        uri = ledger_path.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True, timeout=5) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                f"SELECT * FROM submission_intents "
                f"WHERE application_key IN ({placeholders}) "
                f"AND status IN (?, ?, ?, ?) "
                f"ORDER BY created_at DESC, intent_id DESC LIMIT 1",
                (*hashes, *statuses),
            ).fetchone()
            if row is not None:
                rows = connection.execute(
                    "SELECT event_id, payload_json, created_at FROM events "
                    "WHERE run_id = ? AND job_id = ? "
                    "AND event_type = 'SUBMISSION_REVIEW_NOTE' "
                    "ORDER BY sequence DESC LIMIT 50",
                    (row["run_id"], row["job_id"]),
                ).fetchall()
                for entry in rows:
                    payload = json.loads(entry["payload_json"])
                    if (
                        payload.get("intent_id") == row["intent_id"]
                        and payload.get("review_action") in ReviewAction._value2member_map_
                    ):
                        review_actions.append({
                            "event_id": entry["event_id"],
                            "action": payload["review_action"],
                            "recorded_at": entry["created_at"],
                        })
        intent = EventLedger._intent_from_row(row) if row is not None else None
    result: dict[str, Any] = {
        "posting_identity_hash": identity,
        "self_reported_state": history_state.value if history_state else None,
        "submission": None,
        "review_actions": review_actions,
        "status": ReconciliationStatus.NEVER_SUBMITTED.value,
        "prior_submission_blocks_retry": False,
        "next_action": "No recorded submission; normal authorization still required.",
    }
    if intent is not None:
        result["submission"] = intent.to_safe_dict()
        result["prior_submission_blocks_retry"] = True
        if intent.status is SubmissionStatus.VERIFIED:
            result["status"] = ReconciliationStatus.VERIFIED.value
            result["next_action"] = "Already verified. Do not submit again."
        else:
            result["status"] = ReconciliationStatus.UNRESOLVED.value
            result["next_action"] = (
                "Review trusted confirmation evidence for this intent; "
                "never retry or mark verified without eligible evidence."
            )
    elif history_state is JobHistoryState.APPLIED_SELF_REPORTED:
        result["status"] = ReconciliationStatus.MANUALLY_REPORTED.value
        result["prior_submission_blocks_retry"] = True
        result["next_action"] = "Already reported applied. Do not submit again."
    elif history_state is JobHistoryState.DISMISSED:
        result["status"] = ReconciliationStatus.DISMISSED.value
        result["prior_submission_blocks_retry"] = True
        result["next_action"] = "Dismissed by user. Undo dismissal to reconsider."
    return result


def record_submission_review(
    url: str,
    *,
    action: ReviewAction,
    home: PrivateHome | None = None,
) -> dict[str, Any]:
    """Append a coded review note; never modify submission state or evidence.

    This is a human-review audit entry, NOT a verification or retry permit.
    """
    root = home or PrivateHome.discover()
    PrivateJobHistory._identity(url)
    action = ReviewAction(action)
    path = root.paths.event_ledger
    if path.is_symlink() or not path.is_file():
        raise ValueError("an existing private submission ledger is required")
    ledger = EventLedger(path, posting_aliases=VerifiedPostingAliases(root))
    hashed = ledger._posting_identity_hashes(url)
    placeholders = ", ".join("?" for _ in hashed)
    # Check and append under one transaction. Verification racing this review
    # cannot cause an apparent new unresolved case after it was verified.
    with ledger.transaction() as connection:
        row = connection.execute(
            f"SELECT * FROM submission_intents "
            f"WHERE application_key IN ({placeholders}) "
            f"AND status IN ('PENDING','SUBMITTING','UNKNOWN') "
            f"ORDER BY created_at DESC, intent_id DESC LIMIT 1",
            hashed,
        ).fetchone()
        if row is None:
            raise ValueError("no unresolved submission intent exists for this job")
        intent = EventLedger._intent_from_row(row)
        record = ledger._insert_event(
            connection,
            run_id=intent.run_id,
            job_id=intent.job_id,
            event_type="SUBMISSION_REVIEW_NOTE",
            payload={"intent_id": intent.intent_id, "review_action": action.value},
        )
    return {
        "review_event_id": record.event_id,
        "review_action": action.value,
        "intent_id": intent.intent_id,
        "submission_status": intent.status.value,
        "prior_submission_blocks_retry": True,
    }


__all__ = [
    "ReconciliationStatus", "ReviewAction",
    "inspect_submission", "record_submission_review",
]
