"""Read-only, no-auth ATS landing-page probe. No forms, uploads, or submits."""
from __future__ import annotations
import argparse
import asyncio
import json
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

def allowed_url(url: str) -> bool:
    p=urlsplit(url)
    if p.scheme!="https" or not p.hostname or p.username or p.password:
        return False
    host=p.hostname.lower().rstrip(".")
    return any(host==base or host.endswith("."+base) for base in
        ("greenhouse.io","greenhouse.com","lever.co","ashbyhq.com","jobvite.com"))

async def inspect(url: str)->dict:
    if not allowed_url(url):
        raise ValueError("Only public HTTPS Greenhouse, Lever, Ashby, or Jobvite pages allowed")
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True)
        try:
            page=await browser.new_page(accept_downloads=False)
            page.set_default_timeout(12000)
            blocked_navigations=[]
            async def navigation_guard(route):
                request=route.request
                if request.is_navigation_request() and not allowed_url(request.url):
                    blocked_navigations.append(urlsplit(request.url).hostname or "invalid")
                    await route.abort()
                else:
                    await route.continue_()
            await page.route("**/*",navigation_guard)
            await page.goto(url,wait_until="domcontentloaded",timeout=25000)
            if blocked_navigations or not allowed_url(page.url):
                raise ValueError("Navigation left approved ATS HTTPS domains")
            return {
                "url_host":urlsplit(page.url).hostname,
                "reachable":True,
                "final_scheme":urlsplit(page.url).scheme,
                "form_count":await page.locator("form").count(),
                "input_count":await page.locator("input").count(),
                "button_count":await page.locator("button").count(),
                "live_review":"not_verified",
                "submission":"not_attempted",
                "auth":"not_attempted",
            }
        finally:
            await browser.close()

def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    args=parser.parse_args()
    if not allowed_url(args.url):
        parser.error("URL is not an allowed public ATS HTTPS host")
    print(json.dumps(asyncio.run(inspect(args.url)),sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
