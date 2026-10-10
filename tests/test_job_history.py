from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

import pytest

import jobpipe_queue
from core.application_engine import JobApplicationEngine
from core.job_history import JobHistoryState, PrivateJobHistory
from core.outcomes import OutcomeStatus, ReasonCode
from core.private_home import PrivateHome
from utils.discovery import Job, deduplicate_jobs


FIRST = "https://jobs.lever.co/synthetic/req-001"
FIRST_APPLY = "https://jobs.lever.co/synthetic/req-001/apply"
SECOND = "https://jobs.lever.co/synthetic/req-002"


def test_job_history_persists_and_recognizes_native_ats_aliases(tmp_path: Path) -> None:
    home = PrivateHome(tmp_path / "private")
    one = PrivateJobHistory(home)
    assert one.state_for(FIRST) is None
    assert one.mark(FIRST, JobHistoryState.APPLIED_SELF_REPORTED) is JobHistoryState.APPLIED_SELF_REPORTED
    assert PrivateJobHistory(home).state_for(FIRST_APPLY) is JobHistoryState.APPLIED_SELF_REPORTED
    assert one.state_for(SECOND) is None
    assert one.path.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="clear"):
        one.mark(FIRST_APPLY, JobHistoryState.DISMISSED)
    one.clear(FIRST_APPLY)
    assert one.state_for(FIRST) is None
    assert one.mark(FIRST, JobHistoryState.DISMISSED) is JobHistoryState.DISMISSED


def test_self_reported_application_never_reaches_submission_ledger(tmp_path: Path) -> None:
    history = PrivateJobHistory(PrivateHome(tmp_path / "private"))
    history.mark(FIRST, JobHistoryState.APPLIED_SELF_REPORTED)
    engine = object.__new__(JobApplicationEngine)
    engine.history = history

    class _ForbiddenLedger:
        def find_submission_intent_for_url(self, *args, **kwargs):
            raise AssertionError("known application must stop before ledger or browser")

    engine.ledger = _ForbiddenLedger()
    bundle = SimpleNamespace(
        run_id="run-synthetic",
        job=SimpleNamespace(job_id="synthetic-job", url=FIRST_APPLY),
    )
    result = engine.submission_preflight(bundle)
    assert result.status is OutcomeStatus.SKIPPED_POLICY
    assert result.reason_code is ReasonCode.DUPLICATE_SUBMISSION
    assert result.details["history_state"] == JobHistoryState.APPLIED_SELF_REPORTED.value


def test_posting_dedup_keeps_distinct_requisitions() -> None:
    def job(ident: str, url: str) -> Job:
        return Job(ident, "Software Engineer", "Synthetic Co", "Remote", url, url, "lever")

    jobs = [
        job("1", FIRST),
        job("2", FIRST_APPLY),
        job("3", SECOND),
    ]
    assert [item.id for item in deduplicate_jobs(jobs)] == ["1", "3"]


def test_regenerated_queue_preserves_applied_and_review_rows(tmp_path: Path, monkeypatch) -> None:
    home = PrivateHome(tmp_path / "private")
    paths = home.ensure()
    monkeypatch.setattr(jobpipe_queue.PrivateHome, "discover", lambda: home)
    PrivateJobHistory(home).mark(SECOND, JobHistoryState.DISMISSED)
    with paths.job_queue.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=jobpipe_queue.FIELDS)
        writer.writeheader()
        writer.writerow({
            "company": "Synthetic Co",
            "job_title": "Software Engineer",
            "job_url": FIRST,
            "status": "Applied",
            "priority": "High",
        })

    rows = [
        {
            "id": "repeat",
            "company": "Synthetic Co",
            "title": "Software Engineer",
            "apply_url": FIRST_APPLY,
            "match_score": 99,
        },
        {
            "id": "dismissed",
            "company": "Synthetic Co",
            "title": "Software Engineer",
            "apply_url": SECOND,
            "match_score": 98,
        },
        {
            "id": "distinct",
            "company": "Synthetic Co",
            "title": "Software Engineer",
            "apply_url": "https://jobs.lever.co/synthetic/req-003",
            "match_score": 93,
        },
    ]
    monkeypatch.setattr(jobpipe_queue, "get_all_jobs", lambda **kwargs: (rows, len(rows)))
    result = jobpipe_queue.enqueue_matched()
    assert result["pending_rows"] == 1
    assert result["preserved_non_pending"] == 1
    with paths.job_queue.open(newline="", encoding="utf-8") as handle:
        saved = list(csv.DictReader(handle))
    assert len(saved) == 2
    assert saved[0]["status"] == "Applied"
    assert saved[1]["job_url"].endswith("/req-003")
    assert saved[1]["status"] == "Pending"


def test_history_rejects_invalid_or_credential_bearing_urls(tmp_path: Path) -> None:
    history = PrivateJobHistory(PrivateHome(tmp_path / "private"))
    for url in ("not a url", "file:///tmp/job", "https://name:password@example.com/job"):
        with pytest.raises(ValueError, match="URL|credentials"):
            history.mark(url, JobHistoryState.APPLIED_SELF_REPORTED)


def test_job_history_cli_is_explicit_and_non_submitting() -> None:
    import jobctl

    for command in ("mark-applied", "dismiss-job", "clear-job-mark", "job-history"):
        args = jobctl.build_parser().parse_args([command, "--url", FIRST])
        assert args.command == command
        assert args.url == FIRST


def test_intermediary_urls_cannot_enter_legacy_application_queue() -> None:
    from jobpipe_queue import _runnable_url

    for domain in ("jobgether.com", "lensa.com", "swooped.co", "jobright.ai"):
        assert not _runnable_url(f"https://{domain}/jobs/synthetic")
    assert _runnable_url(FIRST)


def test_queue_limit_counts_eligible_unique_jobs_after_filtering(
    tmp_path: Path, monkeypatch
) -> None:
    from core.company_preferences import PrivateCompanyPreferences

    home = PrivateHome(tmp_path / "private")
    monkeypatch.setattr(jobpipe_queue.PrivateHome, "discover", lambda: home)
    prefs = PrivateCompanyPreferences(home)
    prefs.set_enabled(True)
    prefs.edit("block", "Blocked Firm")
    PrivateJobHistory(home).mark(
        "https://jobs.lever.co/synthetic/dismissed",
        JobHistoryState.DISMISSED,
    )
    jobs = [
        {
            "company": "Blocked Firm",
            "title": "Software Engineer",
            "apply_url": "https://jobs.lever.co/synthetic/blocked",
            "match_score": 99,
        },
        {
            "company": "Synthetic Firm",
            "title": "Software Engineer",
            "apply_url": "https://jobs.lever.co/synthetic/dismissed",
            "match_score": 98,
        },
        {
            "company": "Synthetic Firm",
            "title": "Software Engineer",
            "apply_url": "https://jobs.lever.co/synthetic/eligible",
            "match_score": 90,
        },
    ]
    calls = []

    def get_all_jobs(**kwargs):
        calls.append(kwargs)
        return jobs[:kwargs["limit"]], len(jobs)

    monkeypatch.setattr(jobpipe_queue, "get_all_jobs", get_all_jobs)
    result = jobpipe_queue.enqueue_matched(limit=1)
    assert calls[0]["limit"] == 10000
    assert result["pending_rows"] == 1
    with home.paths.job_queue.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["job_url"].endswith("/eligible")


def test_legacy_queue_collapses_persistently_verified_external_ats_aliases(
    tmp_path: Path, monkeypatch
) -> None:
    from dataclasses import replace
    from core.verified_posting_aliases import VerifiedPostingAliases
    from source_connectors.contract import ReadJobResult
    from tests.test_posting_verification import ATS, EXTERNAL, _external
    from tests.test_job_library_refresh import _observation

    home = PrivateHome(tmp_path / "private")
    paths = home.ensure()
    monkeypatch.setattr(jobpipe_queue.PrivateHome, "discover", lambda: home)
    VerifiedPostingAliases(home).record_verified(
        source=_external(), employer_url=ATS,
        employer_read=ReadJobResult.succeeded(_observation(ATS)),
    )
    with paths.job_queue.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=jobpipe_queue.FIELDS)
        writer.writeheader()
        writer.writerow({
            "company": "Example Labs",
            "job_title": "Engineer",
            "job_url": EXTERNAL,
            "status": "Applied",
            "priority": "High",
        })
    rows = [
        {"id": "same-employer", "company": "Example Labs",
         "title": "Engineer", "apply_url": ATS, "match_score": 98},
        {"id": "other-requisition", "company": "Example Labs",
         "title": "Engineer",
         "apply_url": "https://job-boards.greenhouse.io/example/jobs/1002",
         "match_score": 90},
    ]
    monkeypatch.setattr(jobpipe_queue, "get_all_jobs",
                        lambda **kwargs: (rows, len(rows)))
    result = jobpipe_queue.enqueue_matched()
    assert result["pending_rows"] == 1
    assert result["preserved_non_pending"] == 1
    with paths.job_queue.open(newline="", encoding="utf-8") as handle:
        saved = list(csv.DictReader(handle))
    assert len(saved) == 2
    assert saved[0]["status"] == "Applied"
    assert saved[1]["job_url"].endswith("/1002")


def test_legacy_queue_deduplicates_two_links_to_verified_employer(
    tmp_path: Path, monkeypatch
) -> None:
    from dataclasses import replace
    from core.verified_posting_aliases import VerifiedPostingAliases
    from source_connectors.contract import ReadJobResult
    from tests.test_posting_verification import ATS, EXTERNAL, _external
    from tests.test_job_library_refresh import _observation

    home = PrivateHome(tmp_path / "private")
    home.ensure()
    monkeypatch.setattr(jobpipe_queue.PrivateHome, "discover", lambda: home)
    VerifiedPostingAliases(home).record_verified(
        source=_external(), employer_url=ATS,
        employer_read=ReadJobResult.succeeded(_observation(ATS)),
    )
    rows = [
        {"id": "board", "company": "Example Labs", "title": "Engineer",
         "apply_url": EXTERNAL, "match_score": 95},
        {"id": "employer", "company": "Example Labs", "title": "Engineer",
         "apply_url": ATS, "match_score": 97},
    ]
    monkeypatch.setattr(jobpipe_queue, "get_all_jobs",
                        lambda **kwargs: (rows, len(rows)))
    result = jobpipe_queue.enqueue_matched()
    assert result["pending_rows"] == 1
    with home.paths.job_queue.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["job_url"] == ATS
