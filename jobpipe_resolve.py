from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from playwright.async_api import async_playwright

from utils.tracker import get_all_jobs, mark_archived, update_apply_url
from utils.url_resolver import is_aggregator_url, is_ats_url, resolve_and_update_url


def _normalize_title(value: str) -> str:
    text = " ".join(str(value or "").casefold().split())
    text = re.sub(r"\s+new$", "", text)
    return text


def _greenhouse_slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(company or "").casefold())


def _greenhouse_board_token_from_html(html: str) -> str:
    patterns = (
        r"boards\.greenhouse\.io/embed/job_board/js\?for=([a-zA-Z0-9_-]+)",
        r"boards\.greenhouse\.io/embed/job_board\?for=([a-zA-Z0-9_-]+)",
        r"job-boards\.greenhouse\.io/([a-zA-Z0-9_-]+)",
        r"boards\.greenhouse\.io/([a-zA-Z0-9_-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, html or "", re.I)
        if match:
            return match.group(1)
    return ""


async def _greenhouse_board_token_from_wrapper(
    client: httpx.AsyncClient,
    base_url: str,
) -> str:
    try:
        response = await client.get(
            base_url,
            headers={"Accept": "text/html", "User-Agent": "jobpipe/0.1"},
            follow_redirects=True,
        )
    except httpx.HTTPError:
        return ""
    if response.status_code != 200:
        return ""
    content = response.text[:2_000_000]
    return _greenhouse_board_token_from_html(content)


def _base_url(job: dict[str, Any]) -> str:
    metadata = job.get("metadata")
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            metadata = {}
    if isinstance(metadata, dict):
        direct = str(metadata.get("job_url_direct") or "").strip()
        if direct:
            return direct
    apply_url = str(job.get("apply_url") or "").strip()
    if apply_url:
        return apply_url
    return str(job.get("url") or "").strip()


def _login_like(url: str) -> bool:
    lowered = url.casefold()
    return any(token in lowered for token in ("/sign_in", "/signin", "/login", "auth/login"))


def _safe_resolution(original: str, resolved: str) -> bool:
    if not resolved or resolved == original:
        return False
    if _login_like(resolved):
        return False
    if is_aggregator_url(resolved):
        return False
    return True


async def _greenhouse_lookup(job: dict[str, Any], base_url: str) -> dict[str, Any] | None:
    company = str(job.get("company") or "").strip()
    title = _normalize_title(str(job.get("title") or ""))
    slug = _greenhouse_slug(company)
    if not slug or not title:
        return None

    parsed = urlparse(base_url)
    gh_id = (parse_qs(parsed.query).get("gh_jid") or [""])[0]
    direct_greenhouse = (
        parsed.hostname in {"grnh.se", "boards.greenhouse.io", "job-boards.greenhouse.io", "my.greenhouse.io"}
        or bool(gh_id)
    )

    try:
        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            board_tokens = [slug]
            if gh_id and parsed.hostname not in {
                "grnh.se",
                "boards.greenhouse.io",
                "job-boards.greenhouse.io",
                "my.greenhouse.io",
            }:
                wrapper_token = await _greenhouse_board_token_from_wrapper(
                    client,
                    base_url,
                )
                if wrapper_token and wrapper_token not in board_tokens:
                    board_tokens.insert(0, wrapper_token)

            jobs = None
            resolved_token = ""
            for token in board_tokens:
                api = (
                    "https://boards-api.greenhouse.io/v1/boards/"
                    f"{token}/jobs?content=true"
                )
                response = await client.get(
                    api,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "jobpipe/0.1",
                    },
                )
                if response.status_code != 200:
                    continue
                try:
                    candidate_jobs = response.json().get("jobs", [])
                except Exception:
                    continue
                if isinstance(candidate_jobs, list):
                    jobs = candidate_jobs
                    resolved_token = token
                    break
    except httpx.HTTPError:
        return None
    if jobs is None:
        return None

    if gh_id:
        for item in jobs:
            if str(item.get("id") or "") == gh_id:
                if resolved_token and parsed.hostname not in {
                    "grnh.se",
                    "boards.greenhouse.io",
                    "job-boards.greenhouse.io",
                    "my.greenhouse.io",
                }:
                    embed_url = (
                        "https://job-boards.greenhouse.io/embed/job_app"
                        f"?for={resolved_token}&token={gh_id}"
                    )
                    return {
                        "state": "found",
                        "url": embed_url,
                        "source": "greenhouse_embed",
                    }
                return {
                    "state": "found",
                    "url": str(item.get("absolute_url") or base_url),
                    "source": "greenhouse_id",
                }

    matches = [item for item in jobs if _normalize_title(str(item.get("title") or "")) == title]
    if matches:
        source_location = str(job.get("location") or "").casefold()
        remote = [item for item in matches if "remote" in str((item.get("location") or {}).get("name") or "").casefold()]
        if remote:
            chosen = remote[0]
        else:
            chosen = None
            for item in matches:
                candidate_location = str((item.get("location") or {}).get("name") or "").casefold()
                source_tokens = {token for token in re.split(r"[^a-z]+", source_location) if len(token) > 2}
                candidate_tokens = {token for token in re.split(r"[^a-z]+", candidate_location) if len(token) > 2}
                if source_tokens and candidate_tokens and source_tokens.intersection(candidate_tokens):
                    chosen = item
                    break
            if chosen is None and len(matches) == 1 and not source_location:
                chosen = matches[0]
        if chosen is not None:
            return {"state": "found", "url": str(chosen.get("absolute_url") or base_url), "source": "greenhouse_title"}

    if direct_greenhouse:
        return {"state": "closed", "url": base_url, "source": "greenhouse_board"}
    return {"state": "not_found", "url": base_url, "source": "greenhouse_board"}


async def resolve_matched(limit: int = 0) -> dict[str, Any]:
    jobs, _ = get_all_jobs(
        status="matched",
        sort_by="match_score",
        sort_order="desc",
        limit=limit or 10000,
    )
    results = []
    updated = direct = unresolved = failed = archived = 0
    pending: list[tuple[dict[str, Any], str]] = []

    for job in jobs:
        base = _base_url(job)
        if not base:
            failed += 1
            results.append({"id": job.get("id"), "resolution": "missing_url"})
            continue

        if is_ats_url(base):
            update_apply_url(job["id"], base)
            direct += 1
            results.append({
                "id": job.get("id"),
                "company": job.get("company"),
                "title": job.get("title"),
                "resolution": "ats_direct",
                "url": base,
            })
            continue

        greenhouse = await _greenhouse_lookup(job, base)
        if greenhouse and greenhouse["state"] == "found":
            resolved = greenhouse["url"]
            update_apply_url(job["id"], resolved)
            updated += int(resolved != str(job.get("apply_url") or ""))
            direct += int(is_ats_url(resolved))
            results.append({
                "id": job.get("id"),
                "company": job.get("company"),
                "title": job.get("title"),
                "resolution": greenhouse["source"],
                "url": resolved,
            })
            continue
        if greenhouse and greenhouse["state"] == "closed":
            mark_archived(job["id"], "live Greenhouse board no longer contains this posting")
            archived += 1
            results.append({
                "id": job.get("id"),
                "company": job.get("company"),
                "title": job.get("title"),
                "resolution": "closed",
                "url": base,
            })
            continue

        pending.append((job, base))

    if pending:
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()
                try:
                    for job, base in pending:
                        try:
                            result = await resolve_and_update_url(page, {**job, "apply_url": base})
                        except Exception as exc:
                            update_apply_url(job["id"], base)
                            failed += 1
                            results.append({
                                "id": job.get("id"),
                                "company": job.get("company"),
                                "title": job.get("title"),
                                "resolution": "error",
                                "error": type(exc).__name__,
                                "url": base,
                            })
                            continue

                        resolved = str(result.get("resolved_url") or base).strip()
                        resolution = str(result.get("resolution") or "unresolved")
                        if _safe_resolution(base, resolved):
                            update_apply_url(job["id"], resolved)
                            updated += 1
                            results.append({
                                "id": job.get("id"),
                                "company": job.get("company"),
                                "title": job.get("title"),
                                "resolution": resolution,
                                "url": resolved,
                            })
                        else:
                            update_apply_url(job["id"], base)
                            unresolved += 1
                            results.append({
                                "id": job.get("id"),
                                "company": job.get("company"),
                                "title": job.get("title"),
                                "resolution": "unresolved",
                                "url": base,
                            })
                finally:
                    await context.close()
                    await browser.close()
        except Exception as exc:
            for job, base in pending:
                update_apply_url(job["id"], base)
                failed += 1
                results.append({
                    "id": job.get("id"),
                    "company": job.get("company"),
                    "title": job.get("title"),
                    "resolution": "browser_unavailable",
                    "error": type(exc).__name__,
                    "url": base,
                })

    return {
        "considered": len(jobs),
        "ats_direct": direct,
        "updated": updated,
        "archived": archived,
        "unresolved": unresolved,
        "failed": failed,
        "results": results,
    }
