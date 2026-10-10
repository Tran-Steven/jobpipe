"""Adversarial answer-bank and privacy boundaries: human review remains required."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from tools.ats_verified_answer_bank import (
    load_bank, lookup_answer, normalize_question, save_bank,
)
from tools.ats_review_answer_matches import build_review_with_verified_matches

NOW = datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
QUESTION = "Do you require sponsorship?"


def answer(value="No", *, scope="global", employer="", **extras):
    return {
        "question": QUESTION,
        "answer": value,
        "scope": scope,
        "employer": employer,
        "human_verified": True,
        **extras,
    }


@pytest.mark.parametrize("records", [
    [answer("Yes"), answer("No")],
    [answer("Yes", scope="employer", employer="Acme"), answer("No")],
    [answer("Yes"), answer("No", scope="employer", employer="Acme")],
    [answer("No"), answer(" Yes "), answer("No")],
])
def test_conflicting_global_and_employer_approved_answers_never_auto_select(records):
    assert lookup_answer(records, QUESTION, "Acme", now=NOW) is None
    assert lookup_answer(list(reversed(records)), QUESTION, "Acme", now=NOW) is None


def test_employer_match_takes_provenance_precedence_only_when_values_agree():
    values = [answer("No"), answer("No", scope="employer", employer="Acme")]
    matched = lookup_answer(values, QUESTION, "acme", now=NOW)
    assert matched == {"status": "verified_candidate", "answer": "No", "scope": "employer"}
    assert lookup_answer(values, QUESTION, "Another", now=NOW)["scope"] == "global"


def test_other_employer_conflicts_never_affect_exact_employer():
    values = [answer("No"), answer("Yes", scope="employer", employer="Elsewhere")]
    assert lookup_answer(values, QUESTION, "Acme", now=NOW)["answer"] == "No"
    assert lookup_answer(values, QUESTION, "Elsewhere", now=NOW) is None


def test_expired_and_revoked_records_do_not_create_false_conflicts():
    values = [answer("No"), answer("Yes", status=" REVOKED "),
              answer("Yes", expires_at="2026-10-01T00:00:00Z")]
    assert lookup_answer(values, QUESTION, "Acme", now=NOW)["answer"] == "No"


@pytest.mark.parametrize("values", [
    [answer(123)], [answer(True)], [answer("  ")],
    [answer("No", withdrawn_at="")],
    [answer("No", expires_at="2026-10-11")],
    [answer("No", status="WITHDRAWN")],
    [answer("No", human_verified="true")],
])
def test_malformed_or_withdrawn_entries_never_advertised(values):
    assert lookup_answer(values, QUESTION, "Acme", now=NOW) is None


def test_ui_announces_no_reuse_and_never_reveals_conflicting_answers():
    fields = [{"question": QUESTION, "type": "radio", "required": True}]
    bank = [answer("DO_NOT_LEAK_GLOBAL"), answer("DO_NOT_LEAK_EMPLOYER",
              scope="employer", employer="Acme")]
    result = build_review_with_verified_matches(fields, set(), bank, "Acme")
    assert result["verified_answer_match_count"] == 0
    assert result["human_review"][0]["verified_answer_available"] is False
    assert "DO_NOT_LEAK" not in str(result)
    assert result["submission"] == "not_attempted"


def test_private_roundtrip_atomic_permissions(tmp_path):
    path = tmp_path / "private" / "answers.json"
    save_bank(path, [answer("No")])
    assert load_bank(path) == [answer("No")]
    assert os.stat(path).st_mode & 0o777 == 0o600
    save_bank(path, [answer("Yes")])
    assert load_bank(path) == [answer("Yes")]
    assert not list(path.parent.glob(".answers-*"))


@pytest.mark.parametrize("bad", [
    "null", "[]", "{}", '"oops"',
    '{"version":true,"answers":[]}',
    '{"version":1,"answers":{"bad":1}}',
    '{"version":2,"answers":[]}',
    '{"version":1,"answers":[],"secret":"should-not-load"}',
    '{"version":1,"answers":[123]}',
])
def test_private_read_rejects_invalid_schema(tmp_path, bad):
    path = tmp_path / "private" / "answers.json"
    path.parent.mkdir()
    path.write_text(bad)
    with pytest.raises(ValueError):
        load_bank(path)


def test_large_file_and_too_many_records_are_refused(tmp_path):
    path = tmp_path / "private" / "answers.json"
    path.parent.mkdir()
    path.write_bytes(b"x" * (2_000_001))
    with pytest.raises(ValueError):
        load_bank(path)
    with pytest.raises(ValueError):
        save_bank(path, [answer()] * 10_001)
    assert path.stat().st_size == 2_000_001


def test_symlink_file_and_parent_rejected_for_read_and_write(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    target = real / "answers.json"
    target.write_text('{"version":1,"answers":[]}')
    linked = tmp_path / "linked.json"
    linked.symlink_to(target)
    linked_dir = tmp_path / "linked-dir"
    linked_dir.symlink_to(real, target_is_directory=True)
    for path in (linked, linked_dir / "answers.json"):
        with pytest.raises(ValueError):
            load_bank(path)
        with pytest.raises(ValueError):
            save_bank(path, [answer()])


def test_input_type_guardrails():
    with pytest.raises(TypeError):
        normalize_question(None)
    with pytest.raises(TypeError):
        lookup_answer([], QUESTION, None, now=NOW)
    with pytest.raises(ValueError):
        lookup_answer([], QUESTION, "Acme", now=datetime(2026, 10, 10))
