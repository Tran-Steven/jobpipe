"""Safe, portable, URL-free private application history backups."""

from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

import pytest

from core.job_history import JobHistoryState, PrivateJobHistory
from core.job_history_import import (
    export_job_history_csv, import_job_history_csv,
)
from core.private_home import PrivateHome

FIRST = "https://boards.greenhouse.io/acme/jobs/101?utm_source=linkedin"
SECOND = "https://jobs.lever.co/acme/position-102"


def _csv(path: Path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def test_hash_only_private_export_roundtrip_and_timestamp_preserved(tmp_path: Path):
    home = PrivateHome(tmp_path / "private-source")
    original = PrivateJobHistory(home)
    original.mark(FIRST, JobHistoryState.APPLIED_SELF_REPORTED)
    original.mark(SECOND, JobHistoryState.DISMISSED)
    before = original.path.read_bytes()
    backup = tmp_path / "portable.csv"
    exported = export_job_history_csv(backup, home=home)
    assert exported == {
        "exported_rows": 2,
        "raw_urls_retained": False,
        "contains_private_history": True,
    }
    assert backup.stat().st_mode & 0o077 == 0
    content = backup.read_text()
    assert FIRST not in content and SECOND not in content
    assert "http" not in content and "acme" not in content
    with backup.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 2
    assert set(rows[0]) == {"identity_hash", "status", "recorded_at"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", row["identity_hash"]) for row in rows)
    assert {row["status"] for row in rows} == {
        "APPLIED_SELF_REPORTED", "DISMISSED"
    }

    destination_home = PrivateHome(tmp_path / "private-destination")
    preview = import_job_history_csv(backup, home=destination_home)
    assert preview["input_rows"] == 2
    assert preview["unmatched_needs_review"] == 0
    assert preview["new_marks"] == 2
    assert preview["committed"] is False
    assert not destination_home.paths.state.exists()
    result = import_job_history_csv(backup, home=destination_home, commit=True)
    assert result["committed"] is True
    restored = PrivateJobHistory(destination_home)
    assert restored.state_for(FIRST) is JobHistoryState.APPLIED_SELF_REPORTED
    assert restored.state_for(SECOND) is JobHistoryState.DISMISSED
    with __import__("sqlite3").connect(restored.path) as connection:
        restored_dates = sorted(r[0] for r in connection.execute(
            "SELECT recorded_at FROM job_history"
        ).fetchall())
    assert restored_dates == sorted(row["recorded_at"] for row in rows)
    assert original.path.read_bytes() == before
    assert import_job_history_csv(backup, home=destination_home)["unchanged"] == 2


def test_export_is_exclusive_and_does_not_follow_symlink(tmp_path: Path):
    home = PrivateHome(tmp_path / "private")
    history = PrivateJobHistory(home)
    history.mark(FIRST, JobHistoryState.APPLIED_SELF_REPORTED)
    destination = tmp_path / "export.csv"
    export_job_history_csv(destination, home=home)
    existing_bytes = destination.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        export_job_history_csv(destination, home=home)
    assert destination.read_bytes() == existing_bytes
    attacker = tmp_path / "attacker.csv"
    attacker.write_text("DO NOT OVERWRITE")
    symlink = tmp_path / "symlink.csv"
    symlink.symlink_to(attacker)
    with pytest.raises(ValueError, match="already exists"):
        export_job_history_csv(symlink, home=home)
    assert attacker.read_text() == "DO NOT OVERWRITE"


def test_export_without_database_fails_read_only(tmp_path: Path):
    home = PrivateHome(tmp_path / "private")
    target = tmp_path / "export.csv"
    with pytest.raises(ValueError, match="no job history database"):
        export_job_history_csv(target, home=home)
    assert not target.exists()
    assert not home.paths.state.exists()


@pytest.mark.parametrize("identity", ["bad", "0" * 63, "A" * 64, "", "f" * 65])
def test_bad_hash_only_import_never_writes(tmp_path: Path, identity: str):
    home = PrivateHome(tmp_path / "private")
    inp = tmp_path / "bad.csv"
    _csv(inp, ["identity_hash", "status"], [
        ["a" * 64, "APPLIED"],
        [identity, "DISMISSED"],
    ])
    with pytest.raises(ValueError):
        import_job_history_csv(inp, home=home, commit=True)
    assert not PrivateJobHistory(home).path.exists()


def test_mixed_url_hash_columns_are_ambiguous_and_rejected(tmp_path: Path):
    home = PrivateHome(tmp_path / "private")
    inp = tmp_path / "ambiguous.csv"
    _csv(inp, ["job_url", "identity_hash", "status"], [
        [FIRST, "a" * 64, "APPLIED"],
    ])
    with pytest.raises(ValueError, match="columns"):
        import_job_history_csv(inp, home=home)
    assert not PrivateJobHistory(home).path.exists()


def test_missing_url_is_review_only_and_never_guess_from_employer_title(
    tmp_path: Path,
):
    home = PrivateHome(tmp_path / "private")
    inp = tmp_path / "partial.csv"
    _csv(inp, ["job_url", "status", "company", "title"], [
        ["", "APPLIED", "Same Company", "Software Engineer"],
        [FIRST, "DISMISSED", "Same Company", "Software Engineer"],
    ])
    preview = import_job_history_csv(inp, home=home)
    assert preview["unmatched_needs_review"] == 1
    assert preview["input_rows"] == 2
    assert preview["unique_postings"] == 1
    assert preview["new_marks"] == 1
    assert not PrivateJobHistory(home).path.exists()
    actual = import_job_history_csv(inp, home=home, commit=True)
    assert actual["unmatched_needs_review"] == 1
    assert PrivateJobHistory(home).state_for(FIRST) is JobHistoryState.DISMISSED
    only_missing = tmp_path / "only-missing.csv"
    _csv(only_missing, ["job_url", "status", "company", "title"], [
        ["", "APPLIED", "Same Company", "Software Engineer"],
    ])
    assert import_job_history_csv(only_missing, home=home)["unique_postings"] == 0
    with pytest.raises(ValueError, match="no matchable postings"):
        import_job_history_csv(only_missing, home=home, commit=True)
    assert PrivateJobHistory(home).state_for(FIRST) is JobHistoryState.DISMISSED


def test_import_records_timezone_aware_dates_and_rolls_back_bad_timestamp(
    tmp_path: Path,
):
    home = PrivateHome(tmp_path / "private")
    inp = tmp_path / "dated.csv"
    _csv(inp, ["job_url", "status", "recorded_at"], [
        [FIRST, "APPLIED", "2026-09-01T10:00:00-07:00"],
        [SECOND, "DISMISSED", "not a timestamp"],
    ])
    with pytest.raises(ValueError, match="recorded_at"):
        import_job_history_csv(inp, home=home, commit=True)
    assert not PrivateJobHistory(home).path.exists()
    _csv(inp, ["job_url", "status", "recorded_at"], [
        [FIRST, "APPLIED", "2026-09-01T10:00:00-07:00"],
    ])
    assert import_job_history_csv(inp, home=home, commit=True)["new_marks"] == 1
    exported = tmp_path / "dated-out.csv"
    export_job_history_csv(exported, home=home)
    assert "2026-09-01T17:00:00+00:00" in exported.read_text()


def test_cli_export_is_opt_in_and_no_urls_or_secrets_are_logged(
    tmp_path: Path, capsys,
):
    from jobctl import build_parser, cmd_job_history_export
    from argparse import Namespace
    home = PrivateHome(tmp_path / "private")
    PrivateJobHistory(home).mark(FIRST, JobHistoryState.APPLIED_SELF_REPORTED)
    out = tmp_path / "snapshot.csv"
    arguments = build_parser().parse_args(["job-history-export", "--csv", str(out)])
    assert arguments.command == "job-history-export"
    assert cmd_job_history_export(Namespace(home=str(home.root), csv=str(out))) == 0
    output = capsys.readouterr().out
    assert FIRST not in output
    assert json.loads(output)["exported_rows"] == 1
    assert "job_url" not in out.read_text()
