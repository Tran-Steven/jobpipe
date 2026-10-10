"""Provider-neutral entry for reading one supported public job URL."""

from __future__ import annotations

from .contract import ReadJobReason, ReadJobRequest, ReadJobResult
from .ashby import AshbyPublicJobReader, _parse_public_job_url as _parse_ashby_url
from .greenhouse import (
    GreenhousePublicJobReader,
    _parse_public_job_url as _parse_greenhouse_url,
)
from .generic_jsonld import GenericJsonLdJobReader
from .lever import (
    LeverPublicJobReader,
    _parse_public_job_url as _parse_lever_url,
)


async def read_public_job(request: ReadJobRequest) -> ReadJobResult:
    """Read one public job without exposing a provider-specific reader."""
    if not isinstance(request, ReadJobRequest):
        raise TypeError("request must be a ReadJobRequest")

    greenhouse = _parse_greenhouse_url(request.url)
    if not isinstance(greenhouse, ReadJobResult):
        return await GreenhousePublicJobReader().read_job(request)
    if greenhouse.reason_code is ReadJobReason.INVALID_URL:
        return greenhouse

    lever = _parse_lever_url(request.url)
    if not isinstance(lever, ReadJobResult):
        return await LeverPublicJobReader().read_job(request)
    if lever.reason_code is ReadJobReason.INVALID_URL:
        return lever

    ashby = _parse_ashby_url(request.url)
    if not isinstance(ashby, ReadJobResult):
        return await AshbyPublicJobReader().read_job(request)
    if ashby.reason_code is ReadJobReason.INVALID_URL:
        return ashby

    return await GenericJsonLdJobReader().read_job(request)


__all__ = ["read_public_job"]
