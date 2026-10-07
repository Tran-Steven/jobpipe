from __future__ import annotations

from typing import Any, Awaitable, Callable

from jobpipe_discovery import scout, triage_jobs
from jobpipe_queue import enqueue_matched
from jobpipe_resolve import resolve_matched


async def run_pipeline(
    profile_path: str,
    scout_limit: int = 0,
    resolve_limit: int = 0,
    queue_csv: str = "",
    scout_fn: Callable[[str, int], Awaitable[dict[str, Any]]] = scout,
    triage_fn: Callable[[str, int], dict[str, Any]] = triage_jobs,
    resolve_fn: Callable[[int], Awaitable[dict[str, Any]]] = resolve_matched,
    enqueue_fn: Callable[[str, int], dict[str, Any]] = enqueue_matched,
) -> dict[str, Any]:
    discovery = await scout_fn(profile_path, scout_limit)
    triage = triage_fn(profile_path, 0)
    resolution = await resolve_fn(resolve_limit)
    queue = enqueue_fn(queue_csv, 0)
    considered = int(resolution.get("considered", 0))
    archived = int(resolution.get("archived", 0))
    unresolved = int(resolution.get("unresolved", 0))
    failed = int(resolution.get("failed", 0))
    matched = int(triage.get("matched", 0))
    queued = int(queue.get("pending_rows", 0))
    resolved = max(0, considered - archived - unresolved - failed)
    return {
        "discovery": discovery,
        "triage": triage,
        "resolution": resolution,
        "queue": queue,
        "summary": {
            "found": int(discovery.get("found", 0)),
            "new": int(discovery.get("new", 0)),
            "matched": matched,
            "skipped": int(triage.get("skipped", 0)),
            "resolved": resolved,
            "archived": archived,
            "unresolved": unresolved,
            "failed": failed,
            "queued": queued,
            "queue_blocked": max(0, matched - queued),
        },
    }
