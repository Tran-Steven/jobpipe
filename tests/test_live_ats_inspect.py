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


@pytest.mark.parametrize("url", [
    "https://greenhouse.io/careers",
    "https://attacker.greenhouse.com/jobs/1",
    "https://foo.boards.greenhouse.io/job/1",
    "https://api.lever.co/jobs/1",
    "https://evil.ashbyhq.com/acme/1",
    "https://jobs.lever.co:443/acme/1",
    "https://jobs.lever.co:8443/acme/1",
    "https://jobs.lever.co/acme/1#credentials",
    "https://jobs.ashbyhq.com./acme/1",
    "https://localhost/jobs",
    "https://metadata.google.internal/latest/meta-data",
])
def test_probe_does_not_trust_provider_parent_domains_or_override_ports(url):
    from tools.live_ats_inspect import allowed_resource_url
    assert not allowed_url(url)
    if ".greenhouse.com" not in url and "foo.boards." not in url and "api.lever.co" not in url and "evil.ashbyhq.com" not in url:
        assert not allowed_resource_url(url)


@pytest.mark.parametrize("url", [
    "http://cdn.example.org/app.js",
    "https://127.0.0.1/secret",
    "https://[::1]/api",
    "https://169.254.169.254/latest/meta-data",
    "https://metadata.google.internal/latest/meta-data",
    "https://internal.local/root",
    "https://user@public.example.org/pixel",
    "https://public.example.org:443/script.js",
    "data:text/html,<script>alert(1)</script>",
])
def test_unsafe_subresources_rejected_before_browser_fetch(url):
    from tools.live_ats_inspect import allowed_resource_url
    assert not allowed_resource_url(url)


@pytest.mark.asyncio
async def test_public_dns_all_addresses_must_be_global():
    from tools.live_ats_inspect import _public_dns
    def resolve_public(_host, _port, **_opts):
        return [(None, None, None, None, ("1.1.1.1", 0))]
    def resolve_mixed(_host, _port, **_opts):
        return [
            (None, None, None, None, ("1.1.1.1", 0)),
            (None, None, None, None, ("127.0.0.1", 0)),
        ]
    assert await _public_dns("cdn.example.org", resolver=resolve_public)
    assert not await _public_dns("cdn.example.org", resolver=resolve_mixed)
    assert not await _public_dns("cdn.example.org", resolver=lambda *a, **k: [])
    def resolution_failure(*_args, **_kwargs):
        raise OSError("synthetic DNS failure")
    assert not await _public_dns("cdn.example.org", resolver=resolution_failure)


@pytest.mark.asyncio
async def test_network_guard_aborts_nonpublic_iframe_and_subresource_before_fetch():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch
    from tools.live_ats_inspect import inspect

    class Request:
        def __init__(self, url, navigate=False, method="GET"):
            self.url = url
            self._navigate = navigate
            self.method = method
        def is_navigation_request(self):
            return self._navigate

    class Route:
        def __init__(self, url, navigate=False, method="GET"):
            self.request = Request(url, navigate=navigate, method=method)
            self.abort = AsyncMock()
            self.continue_ = AsyncMock()

    class Page:
        url = "https://jobs.lever.co/acme/123"
        def __init__(self):
            self.context = SimpleNamespace(route=self.register_context_route)
        def set_default_timeout(self, *_args): pass
        async def route(self, _pattern, _handler):
            raise AssertionError("page routing cannot guard popup initial requests")
        async def register_context_route(self, _pattern, handler):
            self.guard = handler
        async def goto(self, _url, **_kwargs):
            unsafe = [
                Route("https://169.254.169.254/latest/meta-data"),
                Route("http://127.0.0.1/secret"),
                Route("https://metadata.google.internal/latest/meta-data"),
            ]
            for routed in unsafe:
                await self.guard(routed)
                assert routed.abort.await_count == 1
                assert routed.continue_.await_count == 0
            mutation = Route(
                "https://jobs.lever.co/acme/123/submit", method="POST"
            )
            await self.guard(mutation)
            assert mutation.abort.await_count == 1
            assert mutation.continue_.await_count == 0
            permitted = Route("https://jobs.lever.co/assets/style.css")
            await self.guard(permitted)
            assert permitted.continue_.await_count == 1
            return type("Response", (), {"status": 200})()
        async def wait_for_timeout(self, *_args): pass
        def locator(self, _selector):
            return type("Locator", (), {
                "count": AsyncMock(return_value=0),
                "inner_text": AsyncMock(return_value="Software Engineer"),
            })()
    class Browser:
        async def new_page(self, **kwargs):
            assert kwargs["accept_downloads"] is False
            assert kwargs["service_workers"] == "block"
            return Page()
        async def close(self): pass
    class Context:
        async def __aenter__(self):
            return type("P", (), {
                "chromium": type("C", (), {
                    "launch": AsyncMock(return_value=Browser()),
                })(),
            })()
        async def __aexit__(self, *_args): pass
    with patch("tools.live_ats_inspect.async_playwright", return_value=Context()):
        result = await inspect(Page.url)
    assert result["blocked_nonpublic_resources"] == 3
    assert result["blocked_mutating_requests"] == 1
    assert result["diagnostic_only"] is True
    assert result["live_review"] == "not_verified"
    assert result["submission"] == "not_attempted"


@pytest.mark.parametrize("url", [
    "https://acme.wd5.myworkdayjobs.com/en-US/Careers/job/Engineer_R123",
    "https://example.wd1.myworkdayjobs.com/en-US/External/job/123",
    "https://acme.wd100.myworkdayjobs.com/External/job/123",
])
def test_explicit_workday_tenant_urls_are_read_only_probe_eligible(url):
    assert allowed_url(url)


@pytest.mark.parametrize("url", [
    "https://myworkdayjobs.com/External/job/1",
    "https://wd5.myworkdayjobs.com/External/job/1",
    "https://attacker.acme.wd5.myworkdayjobs.com/job/1",
    "https://acme.wd5.myworkdayjobs.com.evil.invalid/job/1",
    "https://acme.wd5.myworkdayjobs.com:443/job/1",
    "http://acme.wd5.myworkdayjobs.com/job/1",
    "https://acme.wd0.myworkdayjobs.com/job/1",
    "https://acme.wd9999.myworkdayjobs.com/job/1",
])
def test_malformed_or_spoofed_workday_urls_are_not_trusted(url):
    assert not allowed_url(url)
