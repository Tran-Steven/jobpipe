"""Non-mutating, evidence-aware reconciliation report for posting submissions.

Never infers success from a page dismissal, an email subject, or a timeout.
Unresolved submission intents remain blocked by the application's preflight.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from .event_ledger import EventLedger, SubmissionStatus, hash_job_url
from .job_history import JobHistoryState, PrivateJobHistory
from .private_home import PrivateHome


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
    if ledger_path.is_file():
        ledger = EventLedger(ledger_path)
        intent = ledger.find_submission_intent_for_url(
            url,
            statuses=(
                SubmissionStatus.PENDING,
                SubmissionStatus.SUBMITTING,
                SubmissionStatus.UNKNOWN,
                SubmissionStatus.VERIFIED,
            ),
        )
    result: dict[str, Any] = {
        "posting_identity_hash": identity,
        "self_reported_state": history_state.value if history_state else None,
        "submission": None,
        "status": ReconciliationStatus.NEVER_SUBMITTED.value,
        "automatic_retry_allowed": True,
        "next_action": "No recorded submission; normal authorization still required.",
    }
    if intent is not None:
        result["submission"] = intent.to_safe_dict()
        result["automatic_retry_allowed"] = False
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
        result["automatic_retry_allowed"] = False
        result["next_action"] = "Already reported applied. Do not submit again."
    elif history_state is JobHistoryState.DISMISSED:
        result["status"] = ReconciliationStatus.DISMISSED.value
        result["automatic_retry_allowed"] = False
        result["next_action"] = "Dismissed by user. Undo dismissal to reconsider."
    return result


__all__ = ["ReconciliationStatus", "inspect_submission"]
