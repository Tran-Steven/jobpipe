from __future__ import annotations

import pytest

from jobpipe_orchestrator import run_pipeline


@pytest.mark.asyncio
async def test_run_pipeline_connects_all_stages() -> None:
    calls = []

    async def scout(profile: str, limit: int):
        calls.append(("scout", profile, limit))
        return {"found": 10, "new": 4}

    def triage(profile: str, limit: int):
        calls.append(("triage", profile, limit))
        return {"matched": 3, "skipped": 7}

    async def resolve(limit: int):
        calls.append(("resolve", limit))
        return {"ats_direct": 2, "updated": 1, "archived": 1, "unresolved": 0}

    def enqueue(path: str, limit: int):
        calls.append(("enqueue", path, limit))
        return {"pending_rows": 3}

    result = await run_pipeline(
        "config/test.yaml",
        scout_limit=25,
        resolve_limit=10,
        queue_csv="/tmp/test.csv",
        scout_fn=scout,
        triage_fn=triage,
        resolve_fn=resolve,
        enqueue_fn=enqueue,
    )

    assert calls == [
        ("scout", "config/test.yaml", 25),
        ("triage", "config/test.yaml", 0),
        ("resolve", 10),
        ("enqueue", "/tmp/test.csv", 0),
    ]
    assert result["summary"] == {
        "found": 10,
        "new": 4,
        "matched": 3,
        "skipped": 7,
        "resolved": 3,
        "archived": 1,
        "unresolved": 0,
        "queued": 3,
    }
