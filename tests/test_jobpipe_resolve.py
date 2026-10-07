from __future__ import annotations

import pytest

import jobpipe_resolve


@pytest.mark.asyncio
async def test_resolve_matched_direct_ats_does_not_need_browser(monkeypatch):
    monkeypatch.setattr(jobpipe_resolve, "get_all_jobs", lambda **kwargs: ([{
        "id": "job-1",
        "company": "Example",
        "title": "Software Engineer",
        "apply_url": "https://example.wd5.myworkdayjobs.com/en-US/Careers/job/Software-Engineer_R123",
        "url": "https://example.test/job",
    }], 1))

    result = await jobpipe_resolve.resolve_matched()

    assert result["considered"] == 1
    assert result["ats_direct"] == 1
    assert result["failed"] == 0
    assert result["results"][0]["resolution"] == "ats_direct"


@pytest.mark.asyncio
async def test_resolve_matched_missing_url(monkeypatch):
    monkeypatch.setattr(jobpipe_resolve, "get_all_jobs", lambda **kwargs: ([{
        "id": "job-2",
        "company": "Example",
        "title": "Software Engineer",
        "apply_url": "",
        "url": "",
    }], 1))

    result = await jobpipe_resolve.resolve_matched()

    assert result["failed"] == 1
    assert result["results"][0]["resolution"] == "missing_url"


def test_greenhouse_board_token_from_wrapper_html() -> None:
    html = '<script src="https://boards.greenhouse.io/embed/job_board/js?for=businessolver"></script>'
    assert jobpipe_resolve._greenhouse_board_token_from_html(html) == "businessolver"
