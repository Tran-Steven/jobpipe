"""P0 Review admission: malformed adapter statuses are not qualification evidence."""

from dataclasses import replace

import pytest

from core.outcomes import (
    ApplicationOutcome, EvidenceKind, EvidenceRef, OutcomePhase, OutcomeStatus,
    ReasonCode,
)
from core.review_integrity import validated_review_fingerprint


def _review():
    return ApplicationOutcome.review_ready(
        run_id="run-review-integrity", job_id="job-review-integrity",
        adapter="synthetic", checkpoint="review.stage",
        details={
            "review": {"fingerprint": "a" * 64, "unresolved_required": []}
        },
    )


def test_known_good_coherent_review_fingerprint_and_snapshot():
    good = _review()
    assert validated_review_fingerprint(good) == "a" * 64
    with_snapshot = replace(
        good, evidence_refs=(EvidenceRef(
            kind=EvidenceKind.FORM_SNAPSHOT, sha256="a" * 64,
        ),)
    )
    assert validated_review_fingerprint(with_snapshot) == "a" * 64


@pytest.mark.parametrize("invalid", [
    lambda r: replace(r, phase=OutcomePhase.FILL),
    lambda r: replace(r, phase=OutcomePhase.SUBMIT),
    lambda r: replace(r, reason_code=ReasonCode.NONE),
    lambda r: replace(r, reason_code=ReasonCode.GATE_B_REQUIRED),
    lambda r: replace(r, status=OutcomeStatus.IN_PROGRESS),
    lambda r: replace(r, retryable=True),
    lambda r: replace(r, details={"review": {
        "fingerprint": "a" * 64, "unresolved_required": ["sensitive_answer"]
    }}),
    lambda r: replace(r, details={"review": {
        "fingerprint": "a" * 64, "unresolved_required": "unknown"
    }}),
    lambda r: replace(r, details={"review": "untrusted"}),
    lambda r: replace(r, details={"review": {"fingerprint": "NOT_A_HASH"}}),
    lambda r: replace(r, details={"review_fingerprint": "b" * 64},
                      evidence_refs=(EvidenceRef(
                          kind=EvidenceKind.FORM_SNAPSHOT, sha256="a" * 64,
                      ),)),
    lambda r: replace(r, checkpoint="b" * 64),
    lambda r: replace(r, details={}),
    lambda r: replace(r, evidence_refs=(EvidenceRef(
        kind=EvidenceKind.CONFIRMATION_TEXT, sha256="a" * 64,
    ),)),
    lambda r: replace(r, evidence_refs=(EvidenceRef(
        kind=EvidenceKind.NETWORK_RESPONSE, sha256="a" * 64,
    ),)),
])
def test_malformed_or_submission_contaminated_review_is_not_admitted(invalid):
    assert validated_review_fingerprint(invalid(_review())) == ""


def test_legacy_checkpoint_hash_still_works_for_non_submit_fixture():
    outcome = ApplicationOutcome.review_ready(
        run_id="legacy-run", job_id="legacy-job", adapter="synthetic",
        checkpoint="f" * 64,
        details={"review": {"unresolved_required": []}},
    )
    assert validated_review_fingerprint(outcome) == "f" * 64
