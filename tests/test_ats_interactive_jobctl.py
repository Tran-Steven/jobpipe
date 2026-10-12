"""Real CLI plumbing and explicit human confirmation; never authorizes submission."""
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import jobctl
from tools.ats_review_snapshot import save_snapshot
from tools.ats_verified_answer_bank import load_bank


def invoke(fields: Path, bank: Path, replies: str, employer: str = "Example") -> int:
    argv = [
        "jobctl.py", "ats-review-interactive", "--fields", str(fields),
        "--bank", str(bank), "--employer", employer,
    ]
    with patch.object(sys, "argv", argv), patch.object(sys, "stdin", io.StringIO(replies)):
        return jobctl.main()


def test_command_registered():
    args = jobctl.build_parser().parse_args([
        "ats-review-interactive", "--fields", "fields.json",
        "--bank", "answers.json", "--employer", "Example",
    ])
    assert args.command == "ats-review-interactive"


def test_approved_answer_saved_and_stdout_is_json_only(tmp_path, capsys):
    fields = tmp_path / "fields.json"
    bank = tmp_path / "bank.json"
    save_snapshot(fields, [
        {"question": "Do you use AI?", "type": "radio", "label": "Yes", "required": True},
        {"question": "Do you use AI?", "type": "radio", "label": "No", "required": True},
    ])
    assert invoke(fields, bank, "SYNTHETIC_PRIVATE\nemployer\nVERIFY\nSAVE\n") == 0
    io_output = capsys.readouterr()
    summary = json.loads(io_output.out)
    assert summary["saved_count"] == 1
    assert summary["submission"] == "not_attempted"
    assert "SYNTHETIC_PRIVATE" not in io_output.out + io_output.err
    assert "[Required]" in io_output.err
    assert "Answer (blank to skip):" in io_output.err
    assert load_bank(bank)[0]["answer"] == "SYNTHETIC_PRIVATE"
    assert bank.stat().st_mode & 0o777 == 0o600


def test_cancelled_review_does_not_persist(tmp_path, capsys):
    fields = tmp_path / "fields.json"
    bank = tmp_path / "bank.json"
    save_snapshot(fields, [{"question": "Why this role?", "type": "textarea", "required": True}])
    assert invoke(fields, bank, "SYNTHETIC_CANCEL\nglobal\nVERIFY\nCANCEL\n") == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["saved_count"] == 0
    assert summary["submission"] == "not_attempted"
    assert not bank.exists()


def test_incomplete_input_fails_closed(tmp_path, capsys):
    fields = tmp_path / "fields.json"
    bank = tmp_path / "bank.json"
    save_snapshot(fields, [{"question": "Why this role?", "type": "textarea", "required": True}])
    with pytest.raises(SystemExit):
        invoke(fields, bank, "SYNTHETIC_PARTIAL\nemployer\nVERIFY\n")
    assert not bank.exists()


def test_unverified_answer_not_saved(tmp_path, capsys):
    fields = tmp_path / "fields.json"
    bank = tmp_path / "bank.json"
    save_snapshot(fields, [{"question": "Why this role?", "type": "textarea", "required": True}])
    assert invoke(fields, bank, "SYNTHETIC_UNVERIFIED\nglobal\nyes\n") == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["saved_count"] == 0
    assert not bank.exists()
