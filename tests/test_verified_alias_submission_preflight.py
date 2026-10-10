"""Non-submitting, end-to-end application preflight tests for verified ATS aliases."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.application_engine import JobApplicationEngine
from core.event_ledger import EventLedger, SubmissionStatus
from core.job_history import PrivateJobHistory, JobHistoryState
from core.outcomes import (
    EvidenceKind, EvidenceRef, OutcomeStatus, ReasonCode,
)
from core.private_home import PrivateHome
from core.verified_posting_aliases import VerifiedPostingAliases
from source_connectors.contract import ReadJobResult
from tests.test_job_library_refresh import _observation
from tests.test_posting_verification import ATS, EXTERNAL, _external


def _setup(tmp_path):
    home = PrivateHome(tmp_path / "private")
    home.ensure()
    aliases = VerifiedPostingAliases(home)
    ledger = EventLedger(home.paths.event_ledger, posting_aliases=aliases)
    ledger.create_run(run_id="run-original", job_id="job-original")
    intent = ledger.create_submission_intent(
        run_id="run-original", job_id="job-original",
        job_url=ATS, material_hash="material", answer_hash="answers",
        review_hash="review", policy_hash="policy",
    )
    aliases.record_verified(
        source=_external(), employer_url=ATS,
        employer_read=ReadJobResult.succeeded(_observation(ATS)),
    )
    engine = object.__new__(JobApplicationEngine)
    engine.ledger = ledger
    engine.history = PrivateJobHistory(home)
    bundle = SimpleNamespace(
        run_id="run-second",
        job=SimpleNamespace(job_id="job-second", url=EXTERNAL),
    )
    return home, engine, intent, bundle


@pytest.mark.parametrize("submission_state", ["PENDING", "SUBMITTING", "UNKNOWN"])
def test_cross_url_preflight_never_retries_unresolved_intent(
    tmp_path: Path, submission_state: str,
) -> None:
    home, engine, intent, bundle = _setup(tmp_path)
    if submission_state != "PENDING":
        engine.ledger.mark_submission_started(intent.intent_id)
    if submission_state == "UNKNOWN":
        engine.ledger.mark_submission_unknown(intent.intent_id)
    before = engine.ledger.get_submission_intent(intent.intent_id)
    outcome = engine.submission_preflight(bundle)
    assert outcome is not None
    assert outcome.status is OutcomeStatus.SUBMIT_UNKNOWN
    assert outcome.reason_code is ReasonCode.SUBMISSION_CONFIRMATION_MISSING
    assert outcome.details["do_not_retry_submit"] is True
    assert outcome.checkpoint == f"submission-intent:{intent.intent_id}"
    assert engine.ledger.get_submission_intent(intent.intent_id) == before


def test_verified_cross_url_intent_is_a_complete_duplicate_guard(tmp_path: Path):
    home, engine, intent, bundle = _setup(tmp_path)
    engine.ledger.mark_submission_started(intent.intent_id)
    engine.ledger.mark_submission_verified(
        intent_id=intent.intent_id,
        evidence=EvidenceRef(kind=EvidenceKind.CONFIRMATION_TEXT, sha256="b" * 64),
    )
    outcome = engine.submission_preflight(bundle)
    assert outcome is not None
    assert outcome.status is OutcomeStatus.SKIPPED_POLICY
    assert outcome.reason_code is ReasonCode.DUPLICATE_SUBMISSION
    assert outcome.checkpoint == f"submission-intent:{intent.intent_id}"
    assert engine.ledger.get_submission_intent(intent.intent_id).status is SubmissionStatus.VERIFIED


def test_private_history_guard_has_priority_over_ledger_lookup(tmp_path: Path):
    home, engine, intent, bundle = _setup(tmp_path)
    engine.history.mark(ATS, JobHistoryState.APPLIED_SELF_REPORTED)

    class _ForbiddenLedger:
        def find_submission_intent_for_url(self, *_args, **_kwargs):
            raise AssertionError("imported applied job must block before ledger or browser")

    engine.ledger = _ForbiddenLedger()
    outcome = engine.submission_preflight(bundle)
    assert outcome.status is OutcomeStatus.SKIPPED_POLICY
    assert outcome.reason_code is ReasonCode.DUPLICATE_SUBMISSION
    assert outcome.details["history_state"] == JobHistoryState.APPLIED_SELF_REPORTED.value
