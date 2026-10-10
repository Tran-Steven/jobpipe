"""Read a hosted Ashby posting via the officially documented public board API.

See https://developers.ashbyhq.com/docs/public-job-posting-api .
Only the fixed api.ashbyhq.com hostname is contacted. The board API returns
published postings; absence is definitive only for a complete, valid response.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .contract import (
    AtsType, FieldProvenance, ProvenanceSource, ReadJobReason,
    ReadJobRequest, ReadJobResult, SourceJobObservation, SourcePlatform, WorkMode,
)
from .greenhouse import _plain_text, _normalize_source_timestamp, _rfc3339

_PATH = re.compile(r"/(?P<board>[a-zA-Z0-9_-]{1,128})/(?P<job>[a-zA-Z0-9_-]{1,128})/?")
_MAX_BYTES = 2_000_000
_MAX_POSTINGS = 5000


def _parse_public_job_url(url: str) -> tuple[str, str, str, str] | ReadJobResult:
    if not isinstance(url, str) or not url.strip() or len(url) > 2048:
        return ReadJobResult.failed(ReadJobReason.INVALID_URL)
    try:
        p = urlsplit(url.strip())
        port = p.port
    except ValueError:
        return ReadJobResult.failed(ReadJobReason.INVALID_URL)
    if (
        p.scheme.casefold() not in {"http", "https"} or not p.hostname
        or p.username is not None or p.password is not None
    ):
        return ReadJobResult.failed(ReadJobReason.INVALID_URL)
    if port is not None or p.hostname.casefold() not in {
        "jobs.ashbyhq.com", "jobs.eu.ashbyhq.com"
    }:
        return ReadJobResult.failed(ReadJobReason.UNSUPPORTED_URL)
    matched = _PATH.fullmatch(p.path)
    if matched is None or p.fragment:
        return ReadJobResult.failed(ReadJobReason.UNSUPPORTED_URL)
    board, job = matched.group("board"), matched.group("job")
    source = f"https://{p.hostname.casefold()}/{board}/{job}"
    api = f"https://api.ashbyhq.com/posting-api/job-board/{quote(board, safe='')}"
    return source, board, job, api


def _observation(
    entry: Mapping[str, Any], *, url: str, board: str, job: str,
    at: datetime,
) -> SourceJobObservation:
    hosted = entry.get("jobUrl")
    if not isinstance(hosted, str):
        raise ValueError("Ashby posting lacks jobUrl")
    parsed = _parse_public_job_url(hosted)
    if isinstance(parsed, ReadJobResult) or (
        parsed[1].casefold() != board.casefold() or parsed[2] != job
    ):
        raise ValueError("Ashby employer job identity mismatch")
    title = entry.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 240:
        raise ValueError("Ashby title is invalid")
    raw_description = entry.get("descriptionPlain")
    if not isinstance(raw_description, str) or not raw_description.strip():
        raw_description = _plain_text(entry.get("descriptionHtml"))
    if not raw_description or len(raw_description) > 100_000:
        raise ValueError("Ashby description is invalid")
    location = entry.get("location") or ""
    if not isinstance(location, str) or len(location) > 320:
        raise ValueError("Ashby location is invalid")
    raw_mode = entry.get("workplaceType")
    if raw_mode is not None and not isinstance(raw_mode, str):
        raise ValueError("Ashby work mode is invalid")
    mode = {"onsite": WorkMode.ONSITE, "remote": WorkMode.REMOTE,
            "hybrid": WorkMode.HYBRID}.get((raw_mode or "").casefold(), WorkMode.UNKNOWN)
    apply_url = entry.get("applyUrl")
    if apply_url is not None:
        if not isinstance(apply_url, str):
            raise ValueError("Ashby applyUrl is invalid")
        try:
            parsed_apply = urlsplit(apply_url)
            if (
                parsed_apply.scheme.casefold() != "https"
                or (parsed_apply.hostname or "").casefold() not in {
                    "jobs.ashbyhq.com", "jobs.eu.ashbyhq.com"
                }
                or parsed_apply.username is not None
                or parsed_apply.password is not None
                or parsed_apply.port is not None
            ):
                raise ValueError("Ashby applyUrl is not hosted")
        except ValueError as exc:
            raise ValueError("Ashby applyUrl is invalid") from exc
    published = _normalize_source_timestamp(entry.get("publishedAt"))
    fields = (
        ("source_platform", ProvenanceSource.SYSTEM, "reader"),
        ("source_job_id", ProvenanceSource.SOURCE_API, "jobUrl"),
        ("source_url", ProvenanceSource.SOURCE_API, "jobUrl"),
        ("application_url", ProvenanceSource.SOURCE_API, "applyUrl"),
        ("company", ProvenanceSource.REQUEST, "url.board"),
        ("title", ProvenanceSource.SOURCE_API, "title"),
        ("description", ProvenanceSource.SOURCE_API, "descriptionPlain"),
        ("location", ProvenanceSource.SOURCE_API, "location"),
        ("work_mode", ProvenanceSource.SOURCE_API, "workplaceType"),
        ("posted_at", ProvenanceSource.SOURCE_API, "publishedAt"),
        ("ats_type", ProvenanceSource.SYSTEM, "reader"),
        ("observed_at", ProvenanceSource.SYSTEM, "clock"),
    )
    return SourceJobObservation(
        source_platform=SourcePlatform.ASHBY,
        source_job_id=job,
        source_url=parsed[0],
        application_url=apply_url,
        company=board,  # Board handle, not a claimed legal employer identity.
        title=" ".join(title.split()),
        description=" ".join(raw_description.split()),
        location=" ".join(location.split()),
        work_mode=mode, posted_at=published,
        ats_type=AtsType.ASHBY,
        observed_at=_rfc3339(at),
        provenance=tuple(FieldProvenance(*field) for field in fields),
    )


class AshbyPublicJobReader:
    def __init__(
        self, *, timeout_seconds: float = 10,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout must be positive")
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def read_job(self, request: ReadJobRequest) -> ReadJobResult:
        if not isinstance(request, ReadJobRequest):
            raise TypeError("request must be a ReadJobRequest")
        parsed = _parse_public_job_url(request.url)
        if isinstance(parsed, ReadJobResult):
            return parsed
        source, board, job, api = parsed
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds, transport=self._transport,
                follow_redirects=False,
                headers={"Accept": "application/json", "User-Agent": "Jobops/1.0 AshbyPublicJobReader"},
            ) as client:
                response = await client.get(api)
        except httpx.TimeoutException:
            return ReadJobResult.failed(ReadJobReason.SOURCE_TIMEOUT)
        except httpx.HTTPError:
            return ReadJobResult.failed(ReadJobReason.SOURCE_UNAVAILABLE)
        if response.status_code == 429:
            return ReadJobResult.failed(ReadJobReason.SOURCE_RATE_LIMITED)
        if response.status_code in {408, 504}:
            return ReadJobResult.failed(ReadJobReason.SOURCE_TIMEOUT)
        if response.status_code >= 500:
            return ReadJobResult.failed(ReadJobReason.SOURCE_UNAVAILABLE)
        if response.status_code != 200:
            return ReadJobResult.failed(
                ReadJobReason.SOURCE_UNAVAILABLE, retryable=False
            )
        if len(response.content) > _MAX_BYTES:
            return ReadJobResult.failed(ReadJobReason.SOURCE_RESPONSE_INVALID)
        try:
            data = response.json()
            if (
                not isinstance(data, Mapping)
                or data.get("apiVersion") != "1"
                or not isinstance(data.get("jobs"), list)
                or len(data["jobs"]) > _MAX_POSTINGS
            ):
                raise ValueError("invalid Ashby listing schema")
            matched = []
            for entry in data["jobs"]:
                if not isinstance(entry, Mapping):
                    raise ValueError("invalid Ashby job entry")
                hosted = entry.get("jobUrl")
                if not isinstance(hosted, str):
                    raise ValueError("invalid Ashby job URL")
                item_url = _parse_public_job_url(hosted)
                if isinstance(item_url, ReadJobResult):
                    raise ValueError("invalid Ashby hosted URL")
                if item_url[1].casefold() != board.casefold():
                    raise ValueError("Ashby listing contains foreign board")
                if item_url[2] == job:
                    matched.append(entry)
            if len(matched) > 1:
                raise ValueError("ambiguous Ashby job identity")
            if not matched:
                return ReadJobResult.failed(ReadJobReason.JOB_NOT_FOUND)
            return ReadJobResult.succeeded(
                _observation(matched[0], url=source, board=board, job=job, at=self._clock())
            )
        except (ValueError, TypeError, KeyError):
            return ReadJobResult.failed(ReadJobReason.SOURCE_RESPONSE_INVALID)


__all__ = ["AshbyPublicJobReader"]
