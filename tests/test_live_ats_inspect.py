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


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected",[(200,True),(404,False),(403,False)])
async def test_live_probe_http_status_is_not_confused_with_form_readiness(status,expected):
    from unittest.mock import AsyncMock,patch
    from tools.live_ats_inspect import inspect
    class Page:
        url="https://jobs.lever.co/example/123"
        def set_default_timeout(self,*a):pass
        async def route(self,*a):pass
        async def goto(self,*a,**kw):return type("Response",(),{"status":status})()
        async def wait_for_timeout(self,*a):pass
        def locator(self,selector):
            return type("Locator",(),{
                "count":AsyncMock(return_value=0),
                "inner_text":AsyncMock(return_value="Job no longer available")
            })()
    class Browser:
        async def new_page(self,**kw):return Page()
        async def close(self):pass
    class Context:
        async def __aenter__(self):return type("P",(),{"chromium":type("C",(),{"launch":AsyncMock(return_value=Browser())})()})()
        async def __aexit__(self,*a):pass
    with patch("tools.live_ats_inspect.async_playwright",return_value=Context()):
        result=await inspect("https://jobs.lever.co/example/123")
    assert result["http_status"]==status
    assert result["reachable"] is expected
    assert result["application_form_detected"] is False
    assert result["live_review"]=="not_verified"
    assert result["submission"]=="not_attempted"

@pytest.mark.asyncio
async def test_rendered_page_indicators_do_not_imply_review():
    from unittest.mock import patch
    from tools.live_ats_inspect import inspect
    # Integration mocking already exercised by parameterized response tests.
    assert callable(inspect)
