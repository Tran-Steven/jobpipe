"""Conservative verification of a posting against a supported public employer ATS.

A search result or a third-party page is not itself evidence that the employer
is accepting applications. Only an independently successful Greenhouse/Lever
public read may establish a cross-site alias, and employer/title contradictions
always stop automatic admission. No fuzzy title-based joining.
"""

from __future__ import annotations

from enum import StrEnum

from .company_filters import normalize_company_name
from .event_ledger import hash_job_url
from source_connectors.contract import (
    ReadJobReason,
    ReadJobResult,
    ReadJobStatus,
    SourceJobObservation,
)
from source_connectors.greenhouse import _parse_public_job_url as _greenhouse
from source_connectors.lever import _parse_public_job_url as _lever


class PostingVerification(StrEnum):
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"
    INCONCLUSIVE = "INCONCLUSIVE"
    CONFLICT = "CONFLICT"


def supported_employer_identity(url: str) -> str | None:
    """Recognize exact public hosted ATS posting URL shapes, not arbitrary domains."""
    if not isinstance(url, str):
        return None
    for parser in (_greenhouse, _lever):
        try:
            parsed = parser(url)
        except (TypeError, ValueError):
            continue
        if not isinstance(parsed, ReadJobResult):
            return hash_job_url(url)
    return None


def verify_employer_observation(
    original: SourceJobObservation,
    expected_url: str,
    employer_read: ReadJobResult,
) -> PostingVerification:
    """Verify a second public read without trusting source-provided ATS claims."""
    if not isinstance(original, SourceJobObservation):
        raise TypeError("original observation must be typed")
    if not isinstance(employer_read, ReadJobResult):
        return PostingVerification.INCONCLUSIVE
    native_identity = supported_employer_identity(expected_url)
    if native_identity is None:
        return PostingVerification.INCONCLUSIVE
    if employer_read.status is not ReadJobStatus.SUCCEEDED:
        if employer_read.reason_code in {
            ReadJobReason.JOB_CLOSED,
            ReadJobReason.JOB_NOT_FOUND,
        }:
            return PostingVerification.CLOSED
        return PostingVerification.INCONCLUSIVE
    employer = employer_read.observation
    assert employer is not None
    if (
        supported_employer_identity(employer.source_url) != native_identity
        or normalize_company_name(original.company)
        != normalize_company_name(employer.company)
        or normalize_company_name(original.title)
        != normalize_company_name(employer.title)
    ):
        return PostingVerification.CONFLICT
    return PostingVerification.VERIFIED


__all__ = [
    "PostingVerification",
    "supported_employer_identity",
    "verify_employer_observation",
]
