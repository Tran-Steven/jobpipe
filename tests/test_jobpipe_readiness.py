from __future__ import annotations

import json
from pathlib import Path

from core.private_home import PrivateHome
from jobpipe_readiness import application_readiness


def test_readiness_reports_missing_private_profile_files(tmp_path: Path) -> None:
    result = application_readiness(str(tmp_path / "private-home"))

    assert result["ready"] is False
    assert "missing private profile file: facts.json" in result["blockers"]
    assert "missing private profile file: verified-answers.json" in result["blockers"]
    assert "missing private profile file: policy.json" in result["blockers"]


def test_readiness_accepts_minimal_verified_profile(tmp_path: Path) -> None:
    home = PrivateHome(tmp_path / "private-home")
    paths = home.ensure()
    resume = paths.master_documents / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4\n%%EOF\n")

    home.write_text(
        paths.profile_facts,
        json.dumps(
            {
                "schema_version": 1,
                "normalized": {
                    "personal": {
                        "first_name": "Test",
                        "last_name": "Candidate",
                        "email": "candidate@example.test",
                    },
                    "default_resume": str(resume),
                },
            }
        ),
    )
    home.write_text(
        paths.verified_answers,
        json.dumps({"schema_version": 1, "answers": {}}),
    )
    home.write_text(
        paths.policy,
        json.dumps(
            {
                "schema_version": 1,
                "autonomy": {
                    "mode": "LOW_RISK_AUTOPILOT",
                    "email_verification_agent_enabled": False,
                    "allow_keychain_login": True,
                    "allow_account_registration": True,
                },
            }
        ),
    )

    result = application_readiness(str(home.root))

    assert result["ready"] is True
    assert result["resume_configured"] is True
    assert result["verified_answer_count"] == 0
