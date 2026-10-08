"""Read-only probe cannot accept arbitrary URLs or claim application success."""
import pytest
from tools.live_ats_inspect import allowed_url

@pytest.mark.parametrize("url",[
    "https://boards.greenhouse.io/example/jobs/123",
    "https://jobs.lever.co/example/123",
    "https://jobs.ashbyhq.com/example/123",
    "https://jobs.jobvite.com/example",
])
def test_allowed_public_ats_hosts(url):
    assert allowed_url(url)

@pytest.mark.parametrize("url",[
    "http://boards.greenhouse.io/example",
    "https://boards.greenhouse.io.evil.com/x",
    "https://127.0.0.1/x",
    "https://user:pass@jobs.lever.co/",
    "https://evil.com/",
    "file:///etc/passwd",
])
def test_reject_unsafe_targets(url):
    assert not allowed_url(url)
