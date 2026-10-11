"""Trusted Review-arrival contract shared by engine and non-submit execution.

A status string is not evidence that an ATS Review state was reached. Only
deterministic, bounded Review fingerprints with no unresolved required controls
may be admitted to the durable Review/qualification projection. The validator
does not navigate, submit, inspect credentials, or authorize Gate B.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from .outcomes import (
    SUBMISSION_EVIDENCE_KINDS,
    ApplicationOutcome, EvidenceKind, OutcomePhase, OutcomeStatus, ReasonCode,
)

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def validated_review_fingerprint(outcome: ApplicationOutcome | None) -> str:
    """Return a trustworthy *structured* Review digest, or fail closed.

    Fingerprint equality to a later live form remains a separate Gate B check.
    The digest only proves the adapter returned a coherent observation; it
    does NOT prove a live employer page or create submission permission.
    """
    if (
        not isinstance(outcome, ApplicationOutcome)
        or outcome.status is not OutcomeStatus.REVIEW_READY
        or outcome.phase is not OutcomePhase.REVIEW
        or outcome.reason_code is not ReasonCode.REVIEW_COMPLETE
        or outcome.retryable
        or any(ref.kind in SUBMISSION_EVIDENCE_KINDS for ref in outcome.evidence_refs)
    ):
        return ""
    review = outcome.details.get("review")
    if review is not None:
        if not isinstance(review, Mapping):
            return ""
        unresolved = review.get("unresolved_required")
        if unresolved is not None and (
            not isinstance(unresolved, (list, tuple)) or bool(unresolved)
        ):
            return ""
    candidates: list[object] = []
    if isinstance(review, Mapping) and "fingerprint" in review:
        candidates.append(review["fingerprint"])
    for key in ("review_fingerprint", "form_fingerprint"):
        if key in outcome.details:
            candidates.append(outcome.details[key])
    candidates.extend(
        ref.sha256
        for ref in outcome.evidence_refs
        if ref.kind is EvidenceKind.FORM_SNAPSHOT and ref.sha256 is not None
    )
    if isinstance(outcome.checkpoint, str) and len(outcome.checkpoint) == 64:
        candidates.append(outcome.checkpoint)
    if not candidates or any(
        not isinstance(value, str) or _SHA256.fullmatch(value) is None
        for value in candidates
    ):
        return ""
    # If multiple full-length hashes claim to fingerprint the same review,
    # require agreement. A generic engine checkpoint may be a separate stage
    # label, but a 64-byte claimed checkpoint is itself a Review digest.
    if len(set(candidates)) != 1:
        return ""
    return candidates[0]


__all__ = ["validated_review_fingerprint"]
