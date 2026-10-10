from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

import yaml

from core.company_filters import CompanyTreatment, company_treatment
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
    jobs = await discover_all_jobs(profile, limit=limit)
    discovered = 0
    existing = 0
    for job in jobs:
        seen = is_already_seen(job.id)
        log_discovered(job)
        if seen:
            existing += 1
        else:
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


def _remote_scope(*values: str) -> str:
    normalized_values = [
        re.sub(r"[^a-z]+", " ", str(value or "").casefold()).strip()
        for value in values
    ]
    joined = " ".join(value for value in normalized_values if value)
    padded = f" {joined} "
    if " remote " not in padded:
        return "not_remote"
    non_us = (
        " remote europe ",
        " remote european union ",
        " remote emea ",
        " remote united kingdom ",
        " remote uk ",
        " remote canada ",
        " remote latam ",
        " remote latin america ",
        " remote apac ",
        " remote india ",
        " remote australia ",
        " remote germany ",
        " remote france ",
        " remote netherlands ",
        " remote ireland ",
    )
    if any(value in padded for value in non_us):
        return "non_us"
    us = (
        " remote united states ",
        " remote usa ",
        " remote us ",
        " remote u s ",
        " remote north america ",
    )
    if any(value in padded for value in us):
        return "us"
    return "unspecified"


def _score_job(job: dict[str, Any], profile: dict[str, Any]) -> tuple[int, list[str]]:
    title = str(job.get("title") or "").casefold()
    desc = str(job.get("description") or "").casefold()
    location = str(job.get("location") or "").casefold()
    company = str(job.get("company") or "").strip()
    prefs = profile.get("preferences", {})
    roles = [str(v).casefold() for v in prefs.get("roles", [])]
    keywords = [str(v).casefold() for v in prefs.get("keywords", [])]
    candidate_years = int(prefs.get("years_experience", 2))

    if not company or company.casefold() == "unknown":
        return 0, ["missing company identity"]

    treatment = company_treatment(
        company, additional_blocked=prefs.get("exclude_companies", [])
    )
    if treatment is CompanyTreatment.BLOCK:
        return 0, ["company blocked by preference"]

    score = 45
    reasons: list[str] = []
    if treatment is CompanyTreatment.DEPRIORITIZE:
        score -= 30
        reasons.append("company deprioritized by preference")
    elif treatment is CompanyTreatment.REVIEW:
        reasons.append("company needs manual review")

    if any(role in title for role in roles):
        score += 20
        reasons.append("target role")
    elif any(v in title for v in ("software engineer", "software developer", "backend engineer", "backend developer", "full stack", "full-stack", "platform engineer", "java engineer")):
        score += 12
        reasons.append("adjacent role")
    else:
        score -= 18
        reasons.append("weak role match")

    if any(v in title for v in ("principal", "staff", "director", "manager", "architect")):
        score -= 45
        reasons.append("seniority mismatch")
    elif any(v in title for v in ("senior", "sr.", "sr ", "lead")):
        score -= 30
        reasons.append("senior stretch")
    elif any(v in title for v in ("intern", "internship")):
        score -= 50
        reasons.append("internship")

    if "new grad" in title or "new graduate" in title:
        score -= 30
        reasons.append("new-grad program")
    if "clinician" in title or "therapist" in title:
        score -= 45
        reasons.append("non-SWE primary role")

    years = []
    for match in re.finditer(r"(?<!\d)(\d{1,2})\s*\+?\s*(?:years?|yrs?)\b", desc):
        value = int(match.group(1))
        if 0 < value < 20:
            years.append(value)
    if years:
        required = max(years)
        if required >= candidate_years + 4:
            score -= 35
            reasons.append(f"{required}+ YOE requirement")
        elif required >= candidate_years + 2:
            score -= 20
            reasons.append(f"{required}+ YOE stretch")
        elif required == candidate_years + 1:
            score -= 6
            reasons.append(f"{required}+ YOE slight stretch")

    remote_scope = _remote_scope(
        location,
        desc[:240],
        str(job.get("apply_url") or ""),
        str(job.get("url") or ""),
    )
    if remote_scope == "non_us":
        score -= 55
        reasons.append("remote outside US")
    elif remote_scope == "us":
        score += 12
        reasons.append("US remote")
    elif remote_scope == "unspecified":
        score += 6
        reasons.append("remote country unspecified")
    elif any(v in location for v in ("los angeles", "culver city", "santa monica", "burbank", "glendale", "pasadena", "hawthorne", "torrance", "el segundo", "beverly hills", "playa vista")):
        score += 12
        reasons.append("LA area")
    elif location:
        score -= 8
        reasons.append("location mismatch")

    overlap = [kw for kw in keywords if kw and kw in desc]
    score += min(18, len(overlap) * 3)
    if overlap:
        reasons.append("stack overlap: " + ", ".join(overlap[:5]))

    if any(v in title for v in ("ios", "android", "embedded", "firmware", "palantir", ".net")):
        score -= 18
        reasons.append("specialized mismatch")

    if any(v in desc for v in ("active security clearance required", "top secret clearance required", "ts/sci required")):
        score -= 40
        reasons.append("clearance requirement needs verified candidate fact")

    return max(0, min(100, score)), reasons


def triage_jobs(profile_path: str, limit: int = 0) -> dict[str, Any]:
    profile = load_search_profile(profile_path)
    jobs: list[dict[str, Any]] = []
    for status in ("discovered", "matched", "skipped"):
        rows, _ = get_all_jobs(status=status, limit=10000)
        jobs.extend(rows)
    jobs.sort(key=lambda item: str(item.get("discovered_at") or ""))
    if limit > 0:
        jobs = jobs[:limit]

    from utils.tracker import log_matched, log_skipped

    threshold = int(profile.get("preferences", {}).get("min_match_score", 70))
    matched = skipped = 0
    scored = []
    for job in jobs:
        score, reasons = _score_job(job, profile)
        reason = "; ".join(reasons)
        if score >= threshold:
            log_matched(job["id"], score, reason, "")
            matched += 1
            decision = "matched"
        else:
            log_skipped(job["id"], reason, score)
            skipped += 1
            decision = "skipped"
        scored.append({
            "id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "score": score,
            "decision": decision,
        })
    scored.sort(key=lambda item: item["score"], reverse=True)
    return {
        "evaluated": len(jobs),
        "matched": matched,
        "skipped": skipped,
        "threshold": threshold,
        "top": scored[:20],
    }
