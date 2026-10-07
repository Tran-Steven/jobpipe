from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from core.private_home import PrivateHome
from core.profile_store import CandidateVault, ProfileStoreError


def application_readiness(home_path: str = "") -> dict[str, Any]:
    home = (
        PrivateHome(Path(home_path).expanduser().resolve())
        if home_path
        else PrivateHome.discover()
    )
    paths = home.ensure()
    blockers: list[str] = []
    warnings: list[str] = []

    required = (
        paths.profile_facts,
        paths.verified_answers,
        paths.policy,
    )
    missing = [path.name for path in required if not path.is_file()]
    for name in missing:
        blockers.append(f"missing private profile file: {name}")

    resume_path = ""
    verified_answer_count = 0
    if not missing:
        try:
            vault = CandidateVault.load(home)
            profile = vault.application_profile()
            resume_path = str(profile.get("resume_path") or "").strip()
            if not resume_path:
                blockers.append("no default resume is configured")
            elif not Path(resume_path).expanduser().is_file():
                blockers.append("configured default resume file is missing")
            verified_answer_count = len(vault.answer_trust_report().accepted_keys)
            if verified_answer_count == 0:
                warnings.append("no verified application answers are available yet")
        except ProfileStoreError as exc:
            blockers.append(str(exc))

    pending = 0
    if paths.job_queue.is_file() and paths.job_queue.stat().st_size:
        with paths.job_queue.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if str(row.get("status") or "").strip().casefold() == "pending":
                    pending += 1
    if pending == 0:
        warnings.append("application queue has no pending rows")

    return {
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "private_home": str(paths.root),
        "queue": str(paths.job_queue),
        "pending": pending,
        "resume_configured": bool(resume_path),
        "verified_answer_count": verified_answer_count,
    }
