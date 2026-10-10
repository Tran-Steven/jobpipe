"""Offline evidence-aware submission audit; does not perform application actions."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.event_ledger import EventLedger, SubmissionStatus
from core.job_history import JobHistoryState, PrivateJobHistory
from core.outcomes import EvidenceKind, EvidenceRef
from core.private_home import PrivateHome
from core.submission_reconciliation import ReconciliationStatus, inspect_submission


URL = "https://boards.greenhouse.io/example/jobs/1024?utm_source=board"
ALIAS = "https://job-boards.greenhouse.io/example/jobs/1024?gh_src=referral"


def _intent(ledger: EventLedger) -> str:
    ledger.create_run(run_id="run-audit-1", job_id="job-audit-1")
    record = ledger.create_submission_intent(
        run_id="run-audit-1",
        job_id="job-audit-1",
        job_url=URL,
        material_hash="private-material-value",
        answer_hash="private-answer-value",
        review_hash="private-review-value",
        policy_hash="private-policy-value",
    )
    return record.intent_id


def test_unseen_submission_does_not_initialize_or_mutate_private_state(
    tmp_path: Path,
) -> None:
    home = PrivateHome(tmp_path / "private")
    result = inspect_submission(URL, home=home)
    assert result["status"] == ReconciliationStatus.NEVER_SUBMITTED.value
    assert result["prior_submission_blocks_retry"] is False
    assert result["submission"] is None
    assert not home.paths.event_ledger.exists()
    assert not PrivateJobHistory(home).path.exists()


def test_manual_history_dismissal_and_confirmed_submission_are_distinct(
    tmp_path: Path,
) -> None:
    home = PrivateHome(tmp_path / "private")
    history = PrivateJobHistory(home)
    history.mark(URL, JobHistoryState.DISMISSED)
    dismissed = inspect_submission(ALIAS, home=home)
    assert dismissed["status"] == ReconciliationStatus.DISMISSED.value
    assert dismissed["prior_submission_blocks_retry"] is True
    history.mark(URL, JobHistoryState.APPLIED_SELF_REPORTED)
    reported = inspect_submission(ALIAS, home=home)
    assert reported["status"] == ReconciliationStatus.MANUALLY_REPORTED.value
    assert reported["prior_submission_blocks_retry"] is True
    assert not home.paths.event_ledger.exists()


def test_unknown_submission_requires_evidence_and_never_retries(
    tmp_path: Path,
) -> None:
    home = PrivateHome(tmp_path / "private")
    home.ensure()
    ledger = EventLedger(home.paths.event_ledger)
    intent_id = _intent(ledger)
    ledger.mark_submission_started(intent_id)
    ledger.mark_submission_unknown(intent_id)
    before = ledger.get_submission_intent(intent_id)
    events_before = ledger.list_events(run_id="run-audit-1")
    report = inspect_submission(ALIAS, home=home)
    assert report["status"] == ReconciliationStatus.UNRESOLVED.value
    assert report["prior_submission_blocks_retry"] is True
    assert report["submission"]["status"] == SubmissionStatus.UNKNOWN.value
    assert report["submission"]["intent_id"] == intent_id
    assert ledger.get_submission_intent(intent_id) == before
    assert ledger.list_events(run_id="run-audit-1") == events_before
    safe_output = json.dumps(report)
    assert "private-material-value" not in safe_output
    assert "private-answer-value" not in safe_output
    assert URL not in safe_output


def test_confirmed_submission_is_reported_but_not_resubmitted(
    tmp_path: Path,
) -> None:
    home = PrivateHome(tmp_path / "private")
    home.ensure()
    ledger = EventLedger(home.paths.event_ledger)
    intent_id = _intent(ledger)
    ledger.mark_submission_started(intent_id)
    ledger.mark_submission_verified(
        intent_id=intent_id,
        evidence=EvidenceRef(
            kind=EvidenceKind.CONFIRMATION_TEXT,
            sha256="b" * 64,
            metadata={"matched_phrase": "synthetic confirmation"},
        ),
    )
    before = ledger.get_submission_intent(intent_id)
    report = inspect_submission(ALIAS, home=home)
    assert report["status"] == ReconciliationStatus.VERIFIED.value
    assert report["prior_submission_blocks_retry"] is True
    assert report["submission"]["status"] == "VERIFIED"
    assert ledger.get_submission_intent(intent_id) == before
    assert len(ledger.list_submission_evidence(intent_id)) == 1


def test_invalid_urls_and_symlink_ledger_are_rejected(tmp_path: Path) -> None:
    home = PrivateHome(tmp_path / "private")
    for url in ("file:///etc/passwd", "https://user:secret@example.com/jobs/1"):
        with pytest.raises(ValueError):
            inspect_submission(url, home=home)
    home.ensure()
    home.paths.event_ledger.symlink_to(tmp_path / "outside.sqlite3")
    with pytest.raises(ValueError, match="symlink"):
        inspect_submission(URL, home=home)


def test_submission_status_cli_is_read_only_and_explicit(
    tmp_path: Path, capsys
) -> None:
    from argparse import Namespace
    from jobctl import build_parser, cmd_submission_inspect

    args = build_parser().parse_args(["submission-status", "--url", URL])
    assert args.command == "submission-status"
    assert args.url == URL
    home = PrivateHome(tmp_path / "private")
    assert cmd_submission_inspect(Namespace(home=str(home.root), url=URL)) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == ReconciliationStatus.NEVER_SUBMITTED.value
    assert not home.paths.event_ledger.exists()


def test_human_review_note_is_append_only_and_never_unblocks_unknown(
    tmp_path: Path,
) -> None:
    from core.submission_reconciliation import ReviewAction, record_submission_review

    home = PrivateHome(tmp_path / "private")
    home.ensure()
    ledger = EventLedger(home.paths.event_ledger)
    intent_id = _intent(ledger)
    ledger.mark_submission_started(intent_id)
    ledger.mark_submission_unknown(intent_id)
    before = ledger.get_submission_intent(intent_id)
    record = record_submission_review(
        ALIAS, action=ReviewAction.NO_CONFIRMATION_FOUND, home=home
    )
    assert record["intent_id"] == intent_id
    assert record["prior_submission_blocks_retry"] is True
    assert ledger.get_submission_intent(intent_id) == before
    assert ledger.list_submission_evidence(intent_id) == []
    events = ledger.list_events(run_id="run-audit-1")
    assert events[-1].event_type == "SUBMISSION_REVIEW_NOTE"
    assert events[-1].payload == {
        "intent_id": intent_id,
        "review_action": ReviewAction.NO_CONFIRMATION_FOUND.value,
    }
    report = inspect_submission(URL, home=home)
    assert report["status"] == ReconciliationStatus.UNRESOLVED.value
    assert report["prior_submission_blocks_retry"] is True
    assert len(report["review_actions"]) == 1
    assert report["review_actions"][0]["action"] == "NO_CONFIRMATION_FOUND"


def test_review_note_rejects_never_submitted_or_verified_without_mutation(
    tmp_path: Path,
) -> None:
    from core.submission_reconciliation import ReviewAction, record_submission_review

    home = PrivateHome(tmp_path / "private")
    with pytest.raises(ValueError, match="existing private"):
        record_submission_review(URL, action=ReviewAction.ESCALATED, home=home)
    assert not home.paths.event_ledger.exists()
    home.ensure()
    ledger = EventLedger(home.paths.event_ledger)
    intent_id = _intent(ledger)
    ledger.mark_submission_started(intent_id)
    ledger.mark_submission_verified(
        intent_id=intent_id,
        evidence=EvidenceRef(kind=EvidenceKind.CONFIRMATION_TEXT, sha256="b" * 64),
    )
    before = ledger.list_events(run_id="run-audit-1")
    with pytest.raises(ValueError, match="no unresolved"):
        record_submission_review(ALIAS, action=ReviewAction.ESCALATED, home=home)
    with pytest.raises(ValueError):
        record_submission_review(ALIAS, action="MARK_VERIFIED", home=home)
    assert ledger.list_events(run_id="run-audit-1") == before


def test_review_cli_requires_known_action(tmp_path: Path, capsys) -> None:
    from argparse import Namespace
    from jobctl import build_parser, cmd_submission_review

    url = URL
    args = build_parser().parse_args([
        "submission-review", "--url", url, "--action", "EVIDENCE_REQUESTED"
    ])
    assert args.action == "EVIDENCE_REQUESTED"
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "submission-review", "--url", url, "--action", "MARK_VERIFIED"
        ])
    home = PrivateHome(tmp_path / "private")
    home.ensure()
    ledger = EventLedger(home.paths.event_ledger)
    intent_id = _intent(ledger)
    ledger.mark_submission_started(intent_id)
    ledger.mark_submission_unknown(intent_id)
    assert cmd_submission_review(Namespace(
        home=str(home.root), url=url, action=args.action
    )) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["intent_id"] == intent_id
    assert output["submission_status"] == "UNKNOWN"
    assert output["review_action"] == "EVIDENCE_REQUESTED"
