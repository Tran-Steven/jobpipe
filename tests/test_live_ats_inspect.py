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

@pytest.mark.asyncio
async def test_redirect_to_unapproved_host_aborted_without_form_actions():
    from unittest.mock import AsyncMock, patch
    from tools.live_ats_inspect import inspect
    class Request:
        def __init__(self,url):self.url=url
        def is_navigation_request(self):return True
    class Route:
        def __init__(self,url):self.request=Request(url);self.abort=AsyncMock();self.continue_=AsyncMock()
    class Page:
        url="https://boards.greenhouse.io/valid"
        def __init__(self):self.guard=None
        def set_default_timeout(self,*args):pass
        async def route(self,pattern,handler):self.guard=handler
        async def goto(self,url,**kwargs):
            malicious=Route("http://127.0.0.1/private")
            await self.guard(malicious)
            assert malicious.abort.await_count==1
            assert malicious.continue_.await_count==0
    class Browser:
        async def new_page(self,**kwargs):return Page()
        async def close(self):pass
    class Chromium:
        async def launch(self,**kwargs):return Browser()
    class Playwright:
        chromium=Chromium()
    class Context:
        async def __aenter__(self):return Playwright()
        async def __aexit__(self,*args):pass
    with patch("tools.live_ats_inspect.async_playwright",return_value=Context()):
        with pytest.raises(ValueError,match="Navigation left"):
            await inspect("https://boards.greenhouse.io/valid")
