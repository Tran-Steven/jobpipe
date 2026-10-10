"""Synthetic persistent cross-site posting identity tests (never touch real ATS)."""

from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from core.event_ledger import (
    DuplicateSubmissionError,
    EventLedger,
    SubmissionStatus,
    hash_job_url,
)
from core.job_history import JobHistoryState, PrivateJobHistory
from core.private_home import PrivateHome
from core.submission_reconciliation import (
    ReconciliationStatus,
    ReviewAction,
    inspect_submission,
    record_submission_review,
)
from core.verified_posting_aliases import VerifiedPostingAliases
from source_connectors.contract import ReadJobReason, ReadJobResult
from tests.test_job_library_refresh import _observation
from tests.test_posting_verification import ATS, EXTERNAL, _external


SECOND_EXTERNAL = "https://www.indeed.com/viewjob?jk=synthetic-002"
SECOND_ATS = "https://job-boards.greenhouse.io/example/jobs/1002"


def _read(url=ATS):
    return ReadJobResult.succeeded(_observation(url))


def _record(aliases, source=None, target=ATS):
    return aliases.record_verified(
        source=source or _external(),
        employer_url=target,
        employer_read=_read(target),
    )


def _new_intent(ledger: EventLedger, url: str, *, run="run-synthetic", job="job-synthetic"):
    ledger.create_run(run_id=run, job_id=job)
    return ledger.create_submission_intent(
        run_id=run,
        job_id=job,
        job_url=url,
        material_hash="material-private",
        answer_hash="answer-private",
        review_hash="review-private",
        policy_hash="policy-private",
    )


def test_only_independently_verified_ats_link_is_persisted_privately(tmp_path: Path):
    home = PrivateHome(tmp_path / "private")
    aliases = VerifiedPostingAliases(home)
    assert hash_job_url(EXTERNAL) in aliases.identity_hashes(EXTERNAL)
    assert not aliases.path.exists()
    assert _record(aliases) is True
    assert _record(aliases) is False  # idempotent, not a second write
    assert aliases.path.stat().st_mode & 0o077 == 0
    assert hash_job_url(EXTERNAL) in VerifiedPostingAliases(home).identity_hashes(ATS)
    assert hash_job_url(ATS) in aliases.identity_hashes(EXTERNAL)
    with sqlite3.connect(aliases.path) as conn:
        columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(verified_aliases)"))
        rows = conn.execute("SELECT source_hash, employer_hash FROM verified_aliases").fetchall()
    assert columns == ("source_hash", "employer_hash", "recorded_at")
    assert rows == [(hash_job_url(EXTERNAL), hash_job_url(ATS))]
    assert EXTERNAL not in aliases.path.read_bytes().decode("utf-8", errors="ignore")
    assert ATS not in aliases.path.read_bytes().decode("utf-8", errors="ignore")


def test_two_external_job_boards_share_one_employer_identity(tmp_path: Path):
    aliases = VerifiedPostingAliases(PrivateHome(tmp_path / "private"))
    another = replace(
        _external(), source_url=SECOND_EXTERNAL, source_job_id="synthetic-002",
    )
    assert _record(aliases)
    assert _record(aliases, another)
    resolved = set(aliases.identity_hashes(SECOND_EXTERNAL))
    assert {hash_job_url(EXTERNAL), hash_job_url(SECOND_EXTERNAL), hash_job_url(ATS)} <= resolved
    assert hash_job_url(SECOND_EXTERNAL) in aliases.identity_hashes(EXTERNAL)
    assert hash_job_url(SECOND_ATS) not in resolved


def test_conflicting_employer_target_cannot_overwrite_original_link(tmp_path: Path):
    aliases = VerifiedPostingAliases(PrivateHome(tmp_path / "private"))
    assert _record(aliases)
    swapped = replace(_external(), application_url=SECOND_ATS)
    with pytest.raises(ValueError, match="conflicts with earlier employer"):
        _record(aliases, swapped, SECOND_ATS)
    assert hash_job_url(ATS) in aliases.identity_hashes(EXTERNAL)
    assert hash_job_url(SECOND_ATS) not in aliases.identity_hashes(EXTERNAL)
    with sqlite3.connect(aliases.path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM verified_aliases").fetchone()[0] == 1


@pytest.mark.parametrize(
    "read",
    [
        ReadJobResult.failed(ReadJobReason.JOB_CLOSED),
        ReadJobResult.failed(ReadJobReason.SOURCE_TIMEOUT),
        ReadJobResult.succeeded(replace(_observation(ATS), title="Different job")),
        ReadJobResult.succeeded(replace(_observation(ATS), company="Different company")),
    ],
)
def test_failed_or_conflicting_ats_evidence_can_never_create_link(tmp_path: Path, read):
    aliases = VerifiedPostingAliases(PrivateHome(tmp_path / "private"))
    with pytest.raises(ValueError, match="no corroborated ATS evidence"):
        aliases.record_verified(source=_external(), employer_url=ATS, employer_read=read)
    assert not aliases.path.exists()


def test_unverified_site_cannot_be_used_as_employer_authority(tmp_path: Path):
    aliases = VerifiedPostingAliases(PrivateHome(tmp_path / "private"))
    with pytest.raises(ValueError):
        aliases.record_verified(
            source=replace(_external(), application_url=SECOND_EXTERNAL),
            employer_url=SECOND_EXTERNAL,
            employer_read=ReadJobResult.succeeded(
                replace(_observation(SECOND_EXTERNAL), company="Example Labs")
            ),
        )
    assert not aliases.path.exists()


def test_private_homes_never_share_posting_aliases(tmp_path: Path):
    a = VerifiedPostingAliases(PrivateHome(tmp_path / "a"))
    b = VerifiedPostingAliases(PrivateHome(tmp_path / "b"))
    _record(a)
    assert hash_job_url(EXTERNAL) in a.identity_hashes(ATS)
    assert hash_job_url(EXTERNAL) not in b.identity_hashes(ATS)


def test_existing_external_submission_blocks_new_employer_reservation(tmp_path: Path):
    home = PrivateHome(tmp_path / "private")
    home.ensure()
    ledger = EventLedger(home.paths.event_ledger)
    original = _new_intent(ledger, EXTERNAL)
    ledger.mark_submission_started(original.intent_id)
    ledger.mark_submission_unknown(original.intent_id)
    aliases = VerifiedPostingAliases(home)
    _record(aliases)  # discovered after the original intent

    guarded = EventLedger(home.paths.event_ledger, posting_aliases=aliases)
    assert guarded.find_submission_intent_for_url(ATS).intent_id == original.intent_id
    with pytest.raises(DuplicateSubmissionError):
        _new_intent(guarded, ATS, run="run-second", job="job-second")
    assert guarded.get_submission_intent(original.intent_id).status is SubmissionStatus.UNKNOWN

    audit = inspect_submission(ATS, home=home)
    assert audit["status"] == ReconciliationStatus.UNRESOLVED.value
    assert audit["submission"]["intent_id"] == original.intent_id
    assert audit["prior_submission_blocks_retry"] is True
    note = record_submission_review(
        ATS, action=ReviewAction.EVIDENCE_REQUESTED, home=home,
    )
    assert note["intent_id"] == original.intent_id
    assert inspect_submission(EXTERNAL, home=home)["review_actions"][0]["action"] == "EVIDENCE_REQUESTED"
    assert guarded.get_submission_intent(original.intent_id).status is SubmissionStatus.UNKNOWN


def test_verified_employer_submission_blocks_external_url_later(tmp_path: Path):
    home = PrivateHome(tmp_path / "private")
    home.ensure()
    ledger = EventLedger(home.paths.event_ledger)
    original = _new_intent(ledger, ATS)
    ledger.mark_submission_started(original.intent_id)
    _record(VerifiedPostingAliases(home))

    guarded = EventLedger(
        home.paths.event_ledger,
        posting_aliases=VerifiedPostingAliases(home),
    )
    assert guarded.find_submission_intent_for_url(EXTERNAL).intent_id == original.intent_id
    with pytest.raises(DuplicateSubmissionError):
        _new_intent(guarded, EXTERNAL, run="run-again", job="job-again")
    assert guarded.get_submission_intent(original.intent_id).status is SubmissionStatus.SUBMITTING


def test_history_applied_and_dismissed_propagate_and_clear_across_links(tmp_path: Path):
    home = PrivateHome(tmp_path / "private")
    history = PrivateJobHistory(home)
    history.mark(EXTERNAL, JobHistoryState.APPLIED_SELF_REPORTED)
    assert history.state_for(ATS) is None  # not verified yet
    _record(VerifiedPostingAliases(home))
    assert history.state_for(ATS) is JobHistoryState.APPLIED_SELF_REPORTED
    with pytest.raises(ValueError, match="clear"):
        history.mark(ATS, JobHistoryState.DISMISSED)
    history.clear(ATS)
    assert history.state_for(EXTERNAL) is None
    history.mark(ATS, JobHistoryState.DISMISSED)
    assert history.state_for(EXTERNAL) is JobHistoryState.DISMISSED
    assert history.state_for(SECOND_ATS) is None


def test_alias_database_symlink_does_not_get_followed(tmp_path: Path):
    home = PrivateHome(tmp_path / "private")
    home.ensure()
    aliases = VerifiedPostingAliases(home)
    aliases.path.symlink_to(tmp_path / "outside.sqlite3")
    with pytest.raises(ValueError, match="symlink"):
        aliases.identity_hashes(EXTERNAL)
    with pytest.raises(ValueError, match="symlink"):
        _record(aliases)
