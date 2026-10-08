"""Read-only public ATS inspection -> private sanitized review snapshot."""
from __future__ import annotations
import argparse,asyncio,json
from pathlib import Path
from playwright.async_api import async_playwright
from tools.live_ats_inspect import allowed_url
from tools.ats_field_labels import extract_field_labels
from tools.ats_review_snapshot import save_snapshot

async def capture(url:str,target:Path)->dict:
    if not allowed_url(url):raise ValueError("ATS URL not allowed")
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True)
        try:
            page=await browser.new_page(accept_downloads=False)
            blocked=[]
            async def guard(route):
                if route.request.is_navigation_request() and not allowed_url(route.request.url):
                    blocked.append(True)
                    await route.abort()
                else:await route.continue_()
            await page.route("**/*",guard)
            response=await page.goto(url,wait_until="domcontentloaded",timeout=25000)
            if blocked or not allowed_url(page.url):raise ValueError("unapproved ATS redirect")
            if response is None or not (200<=response.status<300):raise ValueError("ATS page not ready")
            await page.wait_for_timeout(2500)
            fields=await extract_field_labels(page)
            if not fields:raise ValueError("no fields found")
            save_snapshot(target,fields)
            return {"http_status":response.status,"field_count":len(fields),"snapshot_written":True,
                    "submission":"not_attempted","auth":"not_attempted","form_fill":"not_attempted"}
        finally:await browser.close()

def main(argv=None)->int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("url")
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(argv)
    if not allowed_url(args.url):p.error("URL must be an approved public HTTPS ATS host")
    print(json.dumps(asyncio.run(capture(args.url,args.output)),sort_keys=True))
    return 0
if __name__=="__main__":raise SystemExit(main())
