"""Offline contract and safety tests for the documented Ashby public board API."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

import httpx
import pytest

from core.posting_verification import (
    PostingVerification, supported_employer_identity, verify_employer_observation,
)
from source_connectors.ashby import AshbyPublicJobReader, _parse_public_job_url
from source_connectors.contract import (
    AtsType, ReadJobReason, ReadJobRequest, ReadJobResult, ReadJobStatus, SourcePlatform,
)
from tests.test_posting_verification import _external


URL = "https://jobs.ashbyhq.com/Example/87d93163-2b0d-4cc0-a004-d0080b8bdb24"
ANOTHER = "https://jobs.ashbyhq.com/Example/another-job"
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def _job(url=URL):
    return {
        "jobUrl": url,
        "applyUrl": url + "/application",
        "title": "Software Engineer",
        "descriptionPlain": "Develop reliable systems.",
        "location": "Los Angeles, CA",
        "workplaceType": "Hybrid",
        "publishedAt": "2026-10-01T10:00:00+00:00",
    }


def _payload(*jobs):
    return {"apiVersion": "1", "jobs": list(jobs)}


def _reader(body, status=200):
    def handler(request):
        assert request.url.host == "api.ashbyhq.com"
        assert request.url.path == "/posting-api/job-board/Example"
        assert request.method == "GET"
        return httpx.Response(status, json=body)
    return AshbyPublicJobReader(
        transport=httpx.MockTransport(handler), clock=lambda: NOW,
    )


@pytest.mark.asyncio
async def test_reads_exact_published_posting_from_official_fixed_host():
    result = await _reader(_payload(_job(), _job(ANOTHER))).read_job(ReadJobRequest(URL))
    assert result.status is ReadJobStatus.SUCCEEDED
    assert result.observation.source_platform is SourcePlatform.ASHBY
    assert result.observation.ats_type is AtsType.ASHBY
    assert result.observation.title == "Software Engineer"
    assert result.observation.company == "Example"
    assert result.observation.source_job_id == URL.rsplit("/", 1)[-1]
    assert result.observation.application_url == URL + "/application"
    assert result.observation.work_mode.value == "HYBRID"
    assert result.observation.observed_at == "2026-10-10T12:00:00Z"


@pytest.mark.asyncio
async def test_missing_posting_definitively_closed_only_on_valid_complete_feed():
    result = await _reader(_payload(_job(ANOTHER))).read_job(ReadJobRequest(URL))
    assert result.reason_code is ReadJobReason.JOB_NOT_FOUND
    assert not result.retryable


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"apiVersion": "0", "jobs": []},
    {"apiVersion": "1", "jobs": {}},
    {"apiVersion": "1", "jobs": ["bad"]},
    _payload(_job(), _job()),  # duplicate matched posting identity
    _payload({**_job(), "descriptionPlain": "" , "descriptionHtml": ""}),
    _payload({**_job(), "applyUrl": "https://attacker.invalid/form"}),
    _payload({**_job(), "publishedAt": "not-a-date"}),
    _payload({**_job(), "jobUrl": "http://127.0.0.1/internal"}),
])
async def test_malformed_feed_never_claims_posting_verified(payload):
    result = await _reader(payload).read_job(ReadJobRequest(URL))
    assert result.reason_code is ReadJobReason.SOURCE_RESPONSE_INVALID


@pytest.mark.asyncio
@pytest.mark.parametrize("status,reason", [
    (429, ReadJobReason.SOURCE_RATE_LIMITED),
    (500, ReadJobReason.SOURCE_UNAVAILABLE),
    (408, ReadJobReason.SOURCE_TIMEOUT),
    (302, ReadJobReason.SOURCE_UNAVAILABLE),
])
async def test_transient_and_redirect_responses_do_not_prove_closure(status, reason):
    result = await _reader({}, status=status).read_job(ReadJobRequest(URL))
    assert result.reason_code is reason
    assert result.reason_code is not ReadJobReason.JOB_NOT_FOUND


@pytest.mark.parametrize("url", [
    "https://evil.ashbyhq.com/Example/id",
    "http://jobs.ashbyhq.com.evil.invalid/Example/id",
    "https://jobs.ashbyhq.com/Example",
    "https://jobs.ashbyhq.com/Example/id/extra",
    "https://jobs.ashbyhq.com/Example/id#fragment",
    "file:///tmp/job",
    "https://secret:pass@jobs.ashbyhq.com/Example/id",
    "https://jobs.ashbyhq.com:8080/Example/id",
])
def test_rejects_untrusted_urls(url):
    assert isinstance(_parse_public_job_url(url), ReadJobResult)
    assert supported_employer_identity(url) is None


@pytest.mark.asyncio
async def test_employer_corrob_supports_exact_ashby_identity_not_recruiter_guess():
    employer = (await _reader(_payload(_job())).read_job(ReadJobRequest(URL))).observation
    external = replace(
        _external(), company="Example",
        title="Software Engineer", application_url=URL,
    )
    assert supported_employer_identity(URL) is not None
    assert verify_employer_observation(
        external, URL, ReadJobResult.succeeded(employer),
    ) is PostingVerification.VERIFIED
    assert verify_employer_observation(
        replace(external, company="Different"),
        URL, ReadJobResult.succeeded(employer),
    ) is PostingVerification.CONFLICT
    assert verify_employer_observation(
        external, URL, ReadJobResult.succeeded(replace(employer, source_url=ANOTHER)),
    ) is PostingVerification.CONFLICT
