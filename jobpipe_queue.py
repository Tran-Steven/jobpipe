from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from core.company_filters import CompanyTreatment, company_treatment
from core.private_home import PrivateHome
from utils.tracker import get_all_jobs
from utils.url_resolver import is_aggregator_url
from urllib.parse import urlparse


FIELDS = [
    "company",
    "job_title",
    "job_url",
    "priority",
    "status",
    "resume_variant",
    "source",
    "match_score",
    "notes",
]


def _priority(score: int) -> str:
    if score >= 85:
        return "High"
    if score >= 75:
        return "Medium"
    return "Low"


def _runnable_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    lowered = url.casefold()
    if not parsed.scheme.startswith("http") or not host:
        return False
    if is_aggregator_url(url) or host == "grnh.se":
        return False
    if any(token in lowered for token in ("/sign_in", "/signin", "/login", "auth/login")):
        return False
    return True


def _role_key(company: str, title: str) -> tuple[str, str]:
    def normalize(value: str) -> str:
        return (
            value.casefold()
            .replace("’", "'")
            .replace("‘", "'")
            .replace("–", "-")
            .replace("—", "-")
            .strip()
        )
    return normalize(company), normalize(title)


def enqueue_matched(csv_path: str = "", limit: int = 0) -> dict[str, Any]:
    home = PrivateHome.discover()
    paths = home.ensure()
    target = Path(csv_path).expanduser().resolve() if csv_path else paths.job_queue
    target.parent.mkdir(parents=True, exist_ok=True)

    jobs, _ = get_all_jobs(status="matched", sort_by="match_score", sort_order="desc", limit=limit or 10000)
    current = {}
    for job in jobs:
        company = str(job.get("company") or "").strip()
        title = str(job.get("title") or "").strip()
        url = str(job.get("apply_url") or job.get("url") or "").strip()
        if not company or company.casefold() == "unknown" or not title or not url or not _runnable_url(url):
            continue
        if company_treatment(company) is CompanyTreatment.BLOCK:
            continue
        key = _role_key(company, title)
        score = int(job.get("match_score") or 0)
        candidate = {
            "company": company,
            "job_title": title,
            "job_url": url,
            "priority": _priority(score),
            "status": "Pending",
            "resume_variant": "",
            "source": str(job.get("source") or job.get("platform") or ""),
            "match_score": str(score),
            "notes": str(job.get("reasoning") or ""),
        }
        previous = current.get(key)
        if previous is None or score > int(previous.get("match_score") or 0):
            current[key] = candidate

    preserved: list[dict[str, str]] = []
    if target.is_file() and target.stat().st_size:
        with target.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if company_treatment(str(row.get("company") or "")) is CompanyTreatment.BLOCK:
                    continue
                if row.get("status", "").strip().casefold() != "pending":
                    preserved.append(dict(row))

    rows = preserved + list(current.values())
    with target.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    target.chmod(0o600)
    return {
        "queue": str(target),
        "matched_considered": len(jobs),
        "pending_rows": len(current),
        "preserved_non_pending": len(preserved),
        "total_rows": len(rows),
    }
