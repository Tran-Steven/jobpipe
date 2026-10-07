from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import yaml

from utils.discovery import discover_all_jobs
from utils.tracker import get_all_jobs, is_already_seen, log_discovered


def load_search_profile(path: str) -> dict[str, Any]:
    profile_path = Path(path).expanduser().resolve()
    if not profile_path.is_file():
        raise FileNotFoundError(f"search profile not found: {profile_path}")
    data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("search profile must be a YAML object")
    preferences = data.get("preferences")
    if not isinstance(preferences, dict) or not preferences.get("roles"):
        raise ValueError("search profile requires preferences.roles")
    return data


async def scout(profile_path: str, limit: int = 0) -> dict[str, Any]:
    profile = load_search_profile(profile_path)
    jobs = await discover_all_jobs(profile)
    if limit > 0:
        jobs = jobs[:limit]
    discovered = 0
    existing = 0
    for job in jobs:
        if is_already_seen(job.id):
            existing += 1
            continue
        log_discovered(job)
        discovered += 1
    return {
        "found": len(jobs),
        "new": discovered,
        "existing": existing,
        "profile": str(Path(profile_path).expanduser().resolve()),
    }


def list_jobs(status: str = "", limit: int = 50) -> dict[str, Any]:
    jobs, total = get_all_jobs(status=status or None, limit=limit)
    return {"total": total, "jobs": jobs}


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, default=str))
