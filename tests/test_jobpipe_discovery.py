from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from jobpipe_discovery import _score_job, load_search_profile


def test_load_search_profile(tmp_path: Path) -> None:
    path = tmp_path / "search.yaml"
    path.write_text(yaml.safe_dump({"preferences": {"roles": ["Software Engineer"]}}), encoding="utf-8")
    profile = load_search_profile(str(path))
    assert profile["preferences"]["roles"] == ["Software Engineer"]


def test_load_search_profile_requires_roles(tmp_path: Path) -> None:
    path = tmp_path / "search.yaml"
    path.write_text(yaml.safe_dump({"preferences": {}}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_search_profile(str(path))


def _profile() -> dict:
    return {
        "preferences": {
            "roles": ["Software Engineer", "Backend Engineer"],
            "keywords": ["Java", "Spring Boot", "PostgreSQL"],
            "years_experience": 2,
        }
    }


def test_score_job_rejects_remote_outside_us() -> None:
    score, reasons = _score_job(
        {
            "title": "Backend Engineer",
            "company": "Example",
            "location": "Remote, Europe",
            "description": "Java and PostgreSQL",
        },
        _profile(),
    )

    assert score < 70
    assert "remote outside US" in reasons


def test_score_job_accepts_us_remote() -> None:
    score, reasons = _score_job(
        {
            "title": "Backend Engineer",
            "company": "Example",
            "location": "Remote, US",
            "description": "Java and PostgreSQL",
        },
        _profile(),
    )

    assert score >= 70
    assert "US remote" in reasons


def test_score_job_non_us_evidence_overrides_generic_us_remote_label() -> None:
    score, reasons = _score_job(
        {
            "title": "Backend Engineer",
            "company": "Example",
            "location": "Remote, US",
            "apply_url": "https://example.test/careers/remote-europe/backend-engineer",
            "url": "https://example.test/job",
            "description": "Remote, Europe. Java and PostgreSQL.",
        },
        _profile(),
    )

    assert score < 70
    assert "remote outside US" in reasons


def test_score_job_uses_strongest_years_requirement() -> None:
    score, reasons = _score_job(
        {
            "title": "Backend Engineer",
            "company": "Example",
            "location": "Remote, US",
            "description": "Requires 5+ years of software development and 3+ years of Java.",
        },
        _profile(),
    )

    assert score < 70
    assert "5+ YOE stretch" in reasons
