from __future__ import annotations

import argparse

import pytest

import jobctl
from core.outcomes import ExitCode


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        home="",
        profile="config/jobpipe.search.yaml",
        scout_limit=5,
        resolve_limit=5,
        csv="",
        resume_dir="",
        priorities="High,Medium,Low",
        statuses="Needs user,Pending,Ready to apply",
        apply_limit=1,
        submit=False,
        approve_gate_a=False,
        continue_on_user=True,
        semantic_mapper=False,
        headless=True,
        lease_ttl=1800.0,
    )


@pytest.mark.asyncio
async def test_autopilot_stops_before_apply_when_not_ready(monkeypatch) -> None:
    async def fake_pipeline(*args):
        return {"summary": {"queued": 2}}

    applied = False

    async def fake_apply(args):
        nonlocal applied
        applied = True
        return 0

    monkeypatch.setattr(jobctl, "jobpipe_run_pipeline", fake_pipeline)
    monkeypatch.setattr(
        jobctl,
        "jobpipe_application_readiness",
        lambda home: {"ready": False, "blockers": ["missing facts.json"]},
    )
    monkeypatch.setattr(jobctl, "cmd_apply_csv", fake_apply)

    result = await jobctl.cmd_autopilot(_args())

    assert result == int(ExitCode.NEEDS_USER)
    assert applied is False


@pytest.mark.asyncio
async def test_autopilot_invokes_apply_when_ready(monkeypatch) -> None:
    async def fake_pipeline(*args):
        return {"summary": {"queued": 2}}

    captured = {}

    async def fake_apply(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(jobctl, "jobpipe_run_pipeline", fake_pipeline)
    monkeypatch.setattr(
        jobctl,
        "jobpipe_application_readiness",
        lambda home: {"ready": True, "blockers": []},
    )
    monkeypatch.setattr(jobctl, "cmd_apply_csv", fake_apply)

    result = await jobctl.cmd_autopilot(_args())

    assert result == 0
    assert captured["args"].limit == 1
    assert captured["args"].headless is True
    assert captured["args"].continue_on_user is True
