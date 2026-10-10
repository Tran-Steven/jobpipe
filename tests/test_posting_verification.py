from __future__ import annotations

from dataclasses import replace

import pytest

from core.posting_verification import (
    PostingVerification,
    supported_employer_identity,
    verify_employer_observation,
)
from source_connectors.contract import (
    AtsType,
    ReadJobReason,
    ReadJobResult,
    SourcePlatform,
)
from tests.test_job_library_refresh import _observation


ATS = "https://job-boards.greenhouse.io/example/jobs/1001"
EXTERNAL = "https://www.linkedin.com/jobs/view/1234567890"


def _external():
    return replace(
        _observation(EXTERNAL),
        source_platform=SourcePlatform.GENERIC_WEB,
        ats_type=AtsType.UNKNOWN,
        source_job_id="1234567890",
        application_url=ATS,
    )


def test_only_real_hosted_ats_posting_urls_are_considered_verifiable() -> None:
    assert supported_employer_identity(ATS) is not None
    assert supported_employer_identity(
        "https://boards.greenhouse.io/example/jobs/1001?utm_source=linkedin"
    ) == supported_employer_identity(ATS)
    assert supported_employer_identity(
        "https://jobs.lever.co/example/position-123"
    ) == supported_employer_identity(
        "https://jobs.lever.co/example/position-123/apply"
    )
    assert supported_employer_identity("https://linkedin.com/jobs/view/1001") is None
    assert supported_employer_identity("https://evilgreenhouse.io/example/jobs/1001") is None
    assert supported_employer_identity("https://job-boards.greenhouse.io/example/jobs/no-id") is None
    assert supported_employer_identity("file:///etc/passwd") is None


def test_independently_read_employer_posting_confirms_exact_alias() -> None:
    source = _external()
    employer = _observation(ATS)
    assert verify_employer_observation(
        source, ATS, ReadJobResult.succeeded(employer)
    ) is PostingVerification.VERIFIED
    assert verify_employer_observation(
        source, ATS, ReadJobResult.succeeded(
            replace(employer, title="Backend Engineer")
        )
    ) is PostingVerification.CONFLICT
    assert verify_employer_observation(
        source, ATS, ReadJobResult.succeeded(
            replace(employer, company="Completely Different Employer")
        )
    ) is PostingVerification.CONFLICT
    assert verify_employer_observation(
        source, ATS, ReadJobResult.succeeded(
            replace(employer, source_url="https://job-boards.greenhouse.io/example/jobs/1002")
        )
    ) is PostingVerification.CONFLICT


@pytest.mark.parametrize("reason", [ReadJobReason.JOB_CLOSED, ReadJobReason.JOB_NOT_FOUND])
def test_employer_closed_is_definitive_without_guessing(reason) -> None:
    assert verify_employer_observation(
        _external(), ATS, ReadJobResult.failed(reason)
    ) is PostingVerification.CLOSED


def test_transient_or_untrusted_status_never_proves_an_alias() -> None:
    for result in (
        ReadJobResult.failed(ReadJobReason.SOURCE_TIMEOUT),
        ReadJobResult.failed(ReadJobReason.SOURCE_RATE_LIMITED),
        ReadJobResult.failed(ReadJobReason.SOURCE_UNAVAILABLE),
        None,
    ):
        assert verify_employer_observation(
            _external(), ATS, result
        ) is PostingVerification.INCONCLUSIVE
