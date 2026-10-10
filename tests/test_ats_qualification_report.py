"""Attended non-submit acceptance metrics never grant submission authority."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tools.ats_qualification_report import assess, read_receipts


ATS = ("greenhouse", "lever", "ashby", "jobvite", "workday")


def receipt(
    number: int,
    *,
    ats: str = "greenhouse",
    environment: str = "ATTENDED_LIVE_NON_SUBMIT",
    status: str = "REVIEW_READY",
    reason_code: str | None = None,
):
    return {
        "attempt_id": f"attempt-{number:08d}",
        "ats": ats,
        "environment": environment,
        "status": status,
        "review_reference_hash": (
            f"{number:064x}" if status == "REVIEW_READY" else None
        ),
        "human_interventions": 0,
        "observed_at": "2026-10-10T14:00:00-07:00",
        "submission_attempted": False,
        "reason_code": reason_code or (
            "NONE" if status == "REVIEW_READY" else "NAVIGATION"
        ),
    }


def _fifty_per_ats(*, samples_per_ats=20):
    return [
        receipt(i + k * samples_per_ats, ats=ats)
        for k, ats in enumerate(ATS)
        for i in range(samples_per_ats)
    ]


def test_all_ats_95_percent_attested_gate_never_authorizes_production():
    samples = _fifty_per_ats()
    for at in range(5):
        samples[at * 20] = receipt(
            at * 20, ats=ATS[at], status="FAILED", reason_code="NAVIGATION"
        )
    report = assess(samples)
    assert report["qualification_gate"] == "MEASURED_PASS"
    assert report["live_attended_non_submit_attempts"] == 100
    assert report["review_reached_attested"] == 95
    assert report["attested_review_arrival_rate"] == .95
    assert all(item["review_arrival_rate"] == .95 for item in report["per_ats"].values())
    assert report["independently_verified"] is False
    assert report["production_submission_authorized"] is False


def test_one_underperforming_ats_fails_even_when_overall_rate_is_high():
    samples = _fifty_per_ats()
    for index in range(3):
        samples[80 + index] = receipt(
            80 + index, ats="workday",
            status="NEEDS_HUMAN", reason_code="CAPTCHA",
        )
        samples[80 + index]["human_interventions"] = 2
    report = assess(samples)
    assert report["qualification_gate"] == "MEASURED_FAIL"
    assert report["per_ats"]["workday"]["review_arrival_rate"] == .85
    assert report["per_ats"]["workday"]["reasons"] == {"CAPTCHA": 3}
    assert report["per_ats"]["workday"]["human_interventions"] == 6
    assert report["per_ats"]["workday"]["interventions_per_attempt"] == .3


def test_fixture_results_never_raise_live_denominator_or_prove_readiness():
    samples = [
        receipt(i, environment="FIXTURE")
        for i in range(100)
    ]
    report = assess(samples)
    assert report["fixture_attempts_excluded"] == 100
    assert report["live_attended_non_submit_attempts"] == 0
    assert report["attested_review_arrival_rate"] is None
    assert report["qualification_gate"] == "NOT_MEASURED"
    assert report["production_submission_authorized"] is False


def test_missing_ats_sample_fails_closed():
    samples = [receipt(i, ats="greenhouse") for i in range(40)]
    report = assess(samples)
    assert report["qualification_gate"] == "INSUFFICIENT_SAMPLE"
    assert report["per_ats"]["greenhouse"]["review_arrival_rate"] == 1.0
    assert report["per_ats"]["workday"]["review_arrival_rate"] is None
    assert report["per_ats"]["workday"]["minimum_sample_met"] is False


@pytest.mark.parametrize("changes", [
    {"attempt_id": "../passwords.json"},
    {"ats": "unknown"},
    {"environment": "UNATTENDED_LIVE"},
    {"status": "SUBMITTED_VERIFIED"},
    {"review_reference_hash": None},
    {"review_reference_hash": "fake"},
    {"human_interventions": True},
    {"human_interventions": -1},
    {"human_interventions": 999},
    {"observed_at": "2026-10-10"},
    {"submission_attempted": True},
    {"submission_attempted": 0},
    {"reason_code": "raw password material"},
    {"reason_code": "CAPTCHA"},
])
def test_invalid_or_sensitive_receipts_refused(changes):
    with pytest.raises((ValueError, TypeError)):
        assess([{**receipt(1), **changes}])


@pytest.mark.parametrize("changes", [
    {"status": "NEEDS_HUMAN", "review_reference_hash": "f" * 64},
    {"status": "FAILED", "review_reference_hash": None, "reason_code": "NONE"},
    {"status": "INCOMPLETE", "review_reference_hash": "f" * 64},
])
def test_no_review_evidence_can_be_smuggled_into_failure(changes):
    with pytest.raises(ValueError):
        assess([{**receipt(1), **changes}])


def test_extra_fields_urls_personal_data_cannot_enter_report():
    bad = receipt(1)
    bad["job_url"] = "https://example.com/private?token=secret"
    with pytest.raises(ValueError, match="schema"):
        assess([bad])


def test_repeated_attempt_cannot_inflate_success_rate():
    with pytest.raises(ValueError, match="duplicate"):
        assess([receipt(1), receipt(1)])


def test_bounded_external_json_lines_import(tmp_path: Path):
    path = tmp_path / "attended.jsonl"
    items = [receipt(i) for i in range(3)]
    path.write_text("".join(json.dumps(item) + "\n" for item in items))
    assert read_receipts(path) == items
    assert assess(read_receipts(path))["qualification_gate"] == "INSUFFICIENT_SAMPLE"


def test_malformed_and_symlink_input_fail_closed(tmp_path: Path):
    path = tmp_path / "attended.jsonl"
    path.write_text(json.dumps(receipt(1)) + "\n" + "not-json\n")
    with pytest.raises(ValueError):
        read_receipts(path)
    link = tmp_path / "alias.jsonl"
    link.symlink_to(path)
    with pytest.raises(ValueError, match="regular external file"):
        read_receipts(link)


def test_duplicate_input_and_large_input_fail_closed(tmp_path: Path):
    path = tmp_path / "attended.jsonl"
    line = json.dumps(receipt(1))
    path.write_text(line + "\n" + line + "\n")
    with pytest.raises(ValueError, match="duplicate attempt"):
        read_receipts(path)
    path.write_text("x" * 2_000_001)
    with pytest.raises(ValueError, match="maximum size"):
        read_receipts(path)


def test_bad_config_and_blank_rows_fail_closed(tmp_path: Path):
    with pytest.raises(ValueError):
        assess([receipt(1)], minimum_per_ats=0)
    with pytest.raises(ValueError):
        assess([receipt(1)], minimum_per_ats=True)
    path = tmp_path / "attended.jsonl"
    path.write_text(json.dumps(receipt(1)) + "\n\n")
    with pytest.raises(ValueError, match="blank"):
        read_receipts(path)


def test_jobctl_exposes_local_non_submit_metrics_without_writing(tmp_path: Path, monkeypatch, capsys):
    from jobctl import main
    path = tmp_path / "attended.jsonl"
    path.write_text(json.dumps(receipt(1)) + "\n")
    before = {item.name for item in tmp_path.iterdir()}
    monkeypatch.setattr(sys, "argv", [
        "jobctl", "ats-qualification-report",
        "--input", str(path), "--minimum-per-ats", "1",
    ])
    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["qualification_gate"] == "INSUFFICIENT_SAMPLE"
    assert report["live_attended_non_submit_attempts"] == 1
    assert report["production_submission_authorized"] is False
    assert {item.name for item in tmp_path.iterdir()} == before
