from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from core.company_filters import CompanyTreatment
from core.company_preferences import PrivateCompanyPreferences, effective_company_treatment
from core.event_ledger import hash_job_url
from core.job_history import PrivateJobHistory
from core.job_quality import assess_job_quality
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
    history = PrivateJobHistory(home)
    company_preferences = PrivateCompanyPreferences(home).read()
    target = Path(csv_path).expanduser().resolve() if csv_path else paths.job_queue
    target.parent.mkdir(parents=True, exist_ok=True)

    preserved: list[dict[str, str]] = []
    protected_identities: set[str] = set()
    if target.is_file() and target.stat().st_size:
        with target.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if row.get("status", "").strip().casefold() == "pending":
                    continue
                preserved.append(dict(row))
                url = str(row.get("job_url") or "").strip()
                if url:
                    try:
                        protected_identities.add(hash_job_url(url))
                    except ValueError:
                        continue

    jobs, _ = get_all_jobs(
        status="matched",
        sort_by="match_score",
        sort_order="desc",
        limit=10000,
    )
    current: dict[str, dict[str, str]] = {}
    for job in jobs:
        company = str(job.get("company") or "").strip()
        title = str(job.get("title") or "").strip()
        url = str(job.get("apply_url") or job.get("url") or "").strip()
        if not company or company.casefold() == "unknown" or not title or not url or not _runnable_url(url):
            continue
        if effective_company_treatment(company, preferences=company_preferences) is CompanyTreatment.BLOCK:
            continue
        if assess_job_quality(title, str(job.get("description") or "")).requires_review:
            continue
        identity = hash_job_url(url)
        if identity in protected_identities or history.state_for(url) is not None:
            continue
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
        previous = current.get(identity)
        if previous is None or score > int(previous.get("match_score") or 0):
            current[identity] = candidate

    if limit > 0:
        current = dict(list(current.items())[:limit])

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
