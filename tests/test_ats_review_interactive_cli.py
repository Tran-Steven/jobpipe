"""End-to-end offline tests for attended, explicitly verified ATS answer review."""
from __future__ import annotations

import io
import json
import os
import sys
from pathlib import Path

import pytest

import jobctl
from tools.ats_verified_answer_bank import load_bank


class _AttendedInput(io.StringIO):
    def isatty(self) -> bool:
        return True


def _invoke(monkeypatch, capsys, tmp_path: Path, answers: str):
    fields = tmp_path / "fields.json"
    fields.write_text(
        json.dumps([
            {"question": "Do you use AI in your role?", "type": "radio", "required": True},
        ]),
        encoding="utf-8",
    )
    bank = tmp_path / "private-answers.json"
    args = [
        "jobctl", "ats-review-interactive", "--fields", str(fields),
        "--bank", str(bank), "--employer", "Synthetic Co",
    ]
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setattr(sys, "stdin", _AttendedInput(answers))
    assert jobctl.main() == 0
    output = capsys.readouterr()
    return bank, json.loads(output.out), output


def test_attended_cli_verifies_saves_private_answers_without_leaking(monkeypatch, capsys, tmp_path):
    secret = "SYNTHETIC_PRIVATE_ANSWER_NEVER_PRINT"
    bank, result, output = _invoke(
        monkeypatch, capsys, tmp_path,
        secret + "\nemployer\nVERIFY\nSAVE\n",
    )
    assert result["saved_count"] == 1
    assert result["submission"] == "not_attempted"
    assert result["scope_counts"] == {"global": 0, "employer": 1}
    assert secret not in output.out and secret not in output.err
    assert "Verify THIS answer" in output.err
    assert "Answer (blank to skip):" in output.err
    assert bank.is_file()
    assert os.stat(bank).st_mode & 0o777 == 0o600
    records = load_bank(bank)
    assert records[0]["answer"] == secret
    assert records[0]["human_verified"] is True
    assert records[0]["employer"] == "Synthetic Co"


def test_attended_cli_cancel_never_persists_answers(monkeypatch, capsys, tmp_path):
    bank, result, output = _invoke(
        monkeypatch, capsys, tmp_path,
        "SYNTHETIC_CANCEL_ME\nglobal\nVERIFY\nCANCEL\n",
    )
    assert result == {"saved_count": 0, "submission": "not_attempted"}
    assert not bank.exists()
    assert "SYNTHETIC_CANCEL_ME" not in output.out
    assert "SYNTHETIC_CANCEL_ME" not in output.err


def test_attended_cli_rejects_unattended_stdin_without_write(monkeypatch, capsys, tmp_path):
    fields = tmp_path / "fields.json"
    fields.write_text(json.dumps([
        {"question": "Unverified", "type": "textarea", "required": True}
    ]), encoding="utf-8")
    bank = tmp_path / "private.json"
    monkeypatch.setattr(sys, "argv", [
        "jobctl", "ats-review-interactive", "--fields", str(fields),
        "--bank", str(bank), "--employer", "Synthetic Co",
    ])
    monkeypatch.setattr(sys, "stdin", io.StringIO("SECRET\nglobal\nVERIFY\nSAVE\n"))
    with pytest.raises(SystemExit) as caught:
        jobctl.main()
    assert caught.value.code != 0
    assert not bank.exists()
    assert "attended terminal" in capsys.readouterr().err


def test_attended_cli_rejects_bad_metadata_before_any_bank_write(monkeypatch, capsys, tmp_path):
    fields = tmp_path / "fields.json"
    fields.write_text('{"not": "a list"}', encoding="utf-8")
    bank = tmp_path / "private.json"
    monkeypatch.setattr(sys, "argv", [
        "jobctl", "ats-review-interactive", "--fields", str(fields),
        "--bank", str(bank), "--employer", "Synthetic Co",
    ])
    monkeypatch.setattr(sys, "stdin", _AttendedInput(""))
    with pytest.raises(SystemExit) as caught:
        jobctl.main()
    assert caught.value.code != 0
    assert not bank.exists()
    assert "metadata array" in capsys.readouterr().err
