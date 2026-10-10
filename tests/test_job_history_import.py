from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from core.job_history import JobHistoryState, PrivateJobHistory
from core.job_history_import import import_job_history_csv
from core.private_home import PrivateHome
from core.submission_reconciliation import inspect_submission, ReconciliationStatus


FIRST = "https://boards.greenhouse.io/acme/jobs/1001?utm_source=linkedin"
ALIAS = "https://job-boards.greenhouse.io/acme/jobs/1001"
SECOND = "https://jobs.lever.co/example/req-1002"


def _csv(path: Path, records: list[tuple[str, str]], *, columns=None) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(columns or ["job_url", "status"])
        writer.writerows(records)


def test_preview_is_read_only_and_import_requires_explicit_commit(
    tmp_path: Path,
) -> None:
    home = PrivateHome(tmp_path / "private")
    source = tmp_path / "history.csv"
    _csv(source, [(FIRST, "APPLIED"), (ALIAS, "APPLIED_SELF_REPORTED"), (SECOND, "DISMISSED")])
    preview = import_job_history_csv(source, home=home)
    assert preview == {
        "committed": False,
        "input_rows": 3,
        "unique_postings": 2,
        "unchanged": 0,
        "new_marks": 2,
        "upgraded_to_applied": 0,
        "raw_urls_retained": False,
    }
    assert not home.paths.state.exists()
    assert not PrivateJobHistory(home).path.exists()

    result = import_job_history_csv(source, home=home, commit=True)
    assert result["committed"] is True
    assert result["new_marks"] == 2
    assert result["unique_postings"] == 2
    assert PrivateJobHistory(home).state_for(ALIAS) is JobHistoryState.APPLIED_SELF_REPORTED
    assert PrivateJobHistory(home).state_for(SECOND) is JobHistoryState.DISMISSED
    assert PrivateJobHistory(home).path.stat().st_mode & 0o077 == 0
    assert inspect_submission(ALIAS, home=home)["status"] == ReconciliationStatus.MANUALLY_REPORTED.value
    after = import_job_history_csv(source, home=home)
    assert after["new_marks"] == 0
    assert after["unchanged"] == 2
    assert FIRST not in json.dumps(result)


def test_import_collision_never_erases_existing_applied_or_partially_imports(
    tmp_path: Path,
) -> None:
    home = PrivateHome(tmp_path / "private")
    history = PrivateJobHistory(home)
    history.mark(FIRST, JobHistoryState.APPLIED_SELF_REPORTED)
    source = tmp_path / "history.csv"
    _csv(source, [(SECOND, "APPLIED"), (ALIAS, "DISMISSED")])
    with pytest.raises(ValueError, match="cannot be downgraded"):
        import_job_history_csv(source, home=home)
    with pytest.raises(ValueError, match="cannot be downgraded"):
        import_job_history_csv(source, home=home, commit=True)
    assert history.state_for(FIRST) is JobHistoryState.APPLIED_SELF_REPORTED
    assert history.state_for(SECOND) is None


def test_import_explicit_applied_upgrades_dismissal_but_does_not_downgrade(
    tmp_path: Path,
) -> None:
    home = PrivateHome(tmp_path / "private")
    history = PrivateJobHistory(home)
    history.mark(FIRST, JobHistoryState.DISMISSED)
    source = tmp_path / "history.csv"
    _csv(source, [(ALIAS, "APPLIED")])
    preview = import_job_history_csv(source, home=home)
    assert preview["upgraded_to_applied"] == 1
    assert history.state_for(FIRST) is JobHistoryState.DISMISSED
    assert import_job_history_csv(source, home=home, commit=True)["upgraded_to_applied"] == 1
    assert history.state_for(FIRST) is JobHistoryState.APPLIED_SELF_REPORTED


@pytest.mark.parametrize(
    "rows",
    [
        [(FIRST, "DISMISSED"), (ALIAS, "APPLIED")],
        [(SECOND, "APPLIED"), ("file:///etc/passwd", "DISMISSED")],
        [(SECOND, "APPLIED"), ("https://user:pass@example.com/jobs/1", "APPLIED")],
        [(SECOND, "APPLIED"), (FIRST, "UNKNOWN")],
        [(SECOND, "APPLIED"), (FIRST, "")],
    ],
)
def test_malformed_or_conflicting_import_has_no_partial_writes(
    tmp_path: Path, rows
) -> None:
    source = tmp_path / "history.csv"
    home = PrivateHome(tmp_path / "private")
    _csv(source, rows)
    with pytest.raises(ValueError):
        import_job_history_csv(source, home=home, commit=True)
    assert not PrivateJobHistory(home).path.exists()


def test_import_rejects_unknown_schema_symlink_and_empty_csv(
    tmp_path: Path,
) -> None:
    home = PrivateHome(tmp_path / "private")
    source = tmp_path / "history.csv"
    _csv(source, [(FIRST, "APPLIED")], columns=["url", "status"])
    with pytest.raises(ValueError, match="columns"):
        import_job_history_csv(source, home=home)
    _csv(source, [])
    with pytest.raises(ValueError, match="no entries"):
        import_job_history_csv(source, home=home)
    _csv(source, [(FIRST, "APPLIED")])
    link = tmp_path / "link.csv"
    link.symlink_to(source)
    with pytest.raises(ValueError, match="non-symlink"):
        import_job_history_csv(link, home=home)
    assert not home.paths.state.exists()


def test_import_cli_requires_explicit_commit_and_never_prints_urls(
    tmp_path: Path, capsys
) -> None:
    from argparse import Namespace
    from jobctl import build_parser, cmd_job_history_import

    source = tmp_path / "history.csv"
    _csv(source, [(FIRST, "APPLIED")])
    parsed = build_parser().parse_args(["job-history-import", "--csv", str(source)])
    assert parsed.commit is False
    home = PrivateHome(tmp_path / "private")
    assert cmd_job_history_import(
        Namespace(home=str(home.root), csv=str(source), commit=False)
    ) == 0
    printed = capsys.readouterr().out
    assert FIRST not in printed
    assert json.loads(printed)["committed"] is False
    assert not home.paths.state.exists()


def test_verified_cross_site_import_is_one_posting_and_handles_existing_marks(
    tmp_path: Path,
) -> None:
    from core.verified_posting_aliases import VerifiedPostingAliases
    from source_connectors.contract import ReadJobResult
    from tests.test_posting_verification import ATS, EXTERNAL, _external
    from tests.test_job_library_refresh import _observation

    home = PrivateHome(tmp_path / "private")
    links = VerifiedPostingAliases(home)
    links.record_verified(
        source=_external(),
        employer_url=ATS,
        employer_read=ReadJobResult.succeeded(_observation(ATS)),
    )
    source = tmp_path / "history.csv"
    _csv(source, [(EXTERNAL, "APPLIED"), (ATS, "APPLIED")])
    preview = import_job_history_csv(source, home=home)
    assert preview["input_rows"] == 2
    assert preview["unique_postings"] == 1
    assert preview["new_marks"] == 1
    assert import_job_history_csv(source, home=home, commit=True)["new_marks"] == 1
    assert PrivateJobHistory(home).state_for(EXTERNAL) is JobHistoryState.APPLIED_SELF_REPORTED
    assert PrivateJobHistory(home).state_for(ATS) is JobHistoryState.APPLIED_SELF_REPORTED
    assert import_job_history_csv(source, home=home)["unchanged"] == 1

    _csv(source, [(EXTERNAL, "DISMISSED")])
    with pytest.raises(ValueError, match="cannot be downgraded"):
        import_job_history_csv(source, home=home, commit=True)
    assert PrivateJobHistory(home).state_for(EXTERNAL) is JobHistoryState.APPLIED_SELF_REPORTED


def test_verified_external_url_conflicts_fail_before_mutation(tmp_path: Path) -> None:
    from core.verified_posting_aliases import VerifiedPostingAliases
    from source_connectors.contract import ReadJobResult
    from tests.test_posting_verification import ATS, EXTERNAL, _external
    from tests.test_job_library_refresh import _observation

    home = PrivateHome(tmp_path / "private")
    links = VerifiedPostingAliases(home)
    links.record_verified(
        source=_external(), employer_url=ATS,
        employer_read=ReadJobResult.succeeded(_observation(ATS)),
    )
    source = tmp_path / "history.csv"
    _csv(source, [(EXTERNAL, "APPLIED"), (ATS, "DISMISSED")])
    with pytest.raises(ValueError, match="conflicting history statuses"):
        import_job_history_csv(source, home=home)
    with pytest.raises(ValueError, match="conflicting history statuses"):
        import_job_history_csv(source, home=home, commit=True)
    assert not PrivateJobHistory(home).path.exists()


def test_existing_external_application_prevents_import_downgrade_at_employer_url(
    tmp_path: Path,
) -> None:
    from core.verified_posting_aliases import VerifiedPostingAliases
    from source_connectors.contract import ReadJobResult
    from tests.test_posting_verification import ATS, EXTERNAL, _external
    from tests.test_job_library_refresh import _observation

    home = PrivateHome(tmp_path / "private")
    history = PrivateJobHistory(home)
    history.mark(EXTERNAL, JobHistoryState.APPLIED_SELF_REPORTED)
    VerifiedPostingAliases(home).record_verified(
        source=_external(), employer_url=ATS,
        employer_read=ReadJobResult.succeeded(_observation(ATS)),
    )
    source = tmp_path / "history.csv"
    _csv(source, [(SECOND, "APPLIED"), (ATS, "DISMISSED")])
    with pytest.raises(ValueError, match="cannot be downgraded"):
        import_job_history_csv(source, home=home, commit=True)
    assert history.state_for(EXTERNAL) is JobHistoryState.APPLIED_SELF_REPORTED
    assert history.state_for(SECOND) is None
