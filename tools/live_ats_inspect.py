"""Bounded, read-only public ATS landing-page diagnostics.

This DOES NOT fill forms, authenticate, reach Review, or prove submission.
Routing refuses redirects outside official ATS hosts and blocks non-public
subresources before the browser fetches them. Output contains no job URLs,
page text, tokens, cookies, or personal data.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import socket
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

_OFFICIAL_HOSTS = frozenset({
    "boards.greenhouse.io", "job-boards.greenhouse.io",
    "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io",
    "jobs.lever.co", "jobs.eu.lever.co",
    "jobs.ashbyhq.com", "jobs.eu.ashbyhq.com",
    "jobs.jobvite.com", "apply.jobvite.com",
})
_DENIED_HOSTS = frozenset({
    "localhost", "instance-data", "metadata.google.internal",
    "metadata.azure.internal",
})


def _parsed_https(url: str):
    """Validate absolute public HTTPS form without trusting string prefixes."""
    if not isinstance(url, str) or not url or len(url) > 2048:
        return None
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.username is not None or parsed.password is not None
        or port is not None or parsed.fragment
    ):
        return None
    host = parsed.hostname.casefold()
    if (
        host.endswith(".") or host in _DENIED_HOSTS
        or host.endswith(".localhost") or host.endswith(".internal")
        or host.endswith(".local") or host.endswith(".test")
        or len(host) > 253 or ".." in host
    ):
        return None
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return parsed
    return None  # No IP-literal network destinations, public or private.


def allowed_url(url: str) -> bool:
    """Only official, exact hosted ATS web domains may be navigated to."""
    parsed = _parsed_https(url)
    return parsed is not None and parsed.hostname.casefold() in _OFFICIAL_HOSTS


def allowed_resource_url(url: str) -> bool:
    """URL-level fail-closed resource filter (DNS validation occurs separately)."""
    return _parsed_https(url) is not None


async def _public_dns(host: str, resolver=None) -> bool:
    """Block DNS names resolving to any private/non-global address.

    The Chromium resolver is distinct, so this is defense-in-depth rather
    than a DNS-pinning guarantee. Non-ATS resource loads are not qualification
    evidence and are safe to drop on DNS errors or timeouts.
    """
    lookup = resolver or socket.getaddrinfo
    try:
        records = await asyncio.wait_for(
            asyncio.to_thread(
                lookup, host, None, family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            ),
            timeout=3,
        )
        addresses = {
            str(ipaddress.ip_address(record[4][0]))
            for record in records
        }
        return bool(addresses) and all(
            ipaddress.ip_address(address).is_global for address in addresses
        )
    except (OSError, ValueError, IndexError, TimeoutError):
        return False


async def inspect(url: str) -> dict:
    """Read a public ATS landing page once without interacting with it."""
    if not allowed_url(url):
        raise ValueError("Only official public HTTPS ATS hosts are allowed")
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page(
                accept_downloads=False,
                service_workers="block",
            )
            page.set_default_timeout(12000)
            blocked_navigations = []
            blocked_resources = 0
            allowed_hosts = {}
            async def navigation_guard(route):
                nonlocal blocked_resources
                request = route.request
                requested = request.url
                if request.is_navigation_request():
                    if not allowed_url(requested):
                        blocked_navigations.append(True)
                        await route.abort()
                        return
                else:
                    if not allowed_resource_url(requested):
                        blocked_resources += 1
                        await route.abort()
                        return
                    host = urlsplit(requested).hostname.casefold()
                    if host not in _OFFICIAL_HOSTS:
                        permitted = allowed_hosts.get(host)
                        if permitted is None:
                            permitted = await _public_dns(host)
                            allowed_hosts[host] = permitted
                        if not permitted:
                            blocked_resources += 1
                            await route.abort()
                            return
                await route.continue_()
            await page.route("**/*", navigation_guard)
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=25000
            )
            if blocked_navigations or not allowed_url(page.url):
                raise ValueError("Navigation left official ATS HTTPS domains")
            status = response.status if response is not None else None
            # Bounded observation only: no clicks, fills, sign-in or uploads.
            await page.wait_for_timeout(2500)
            form_count = await page.locator("form").count()
            input_count = await page.locator("input").count()
            body_text = await page.locator("body").inner_text(timeout=8000)
            normalized = " ".join(body_text.split())
            indicators = tuple(
                term for term in (
                    "not found", "no longer available",
                    "position has been filled", "job is closed", "access denied",
                )
                if term in normalized.casefold()
            )
            return {
                "url_host": urlsplit(page.url).hostname,
                "reachable": status is not None and 200 <= status < 400,
                "http_status": status,
                "application_form_detected": bool(form_count and input_count),
                "diagnostic_only": True,
                "rendered_text_length": len(normalized),
                "empty_rendered_page": not bool(normalized),
                "unavailable_page_indicators": list(indicators),
                "final_scheme": urlsplit(page.url).scheme,
                "form_count": form_count,
                "input_count": input_count,
                "button_count": await page.locator("button").count(),
                "blocked_nonpublic_resources": blocked_resources,
                "live_review": "not_verified",
                "submission": "not_attempted",
                "auth": "not_attempted",
            }
        finally:
            await browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    args = parser.parse_args()
    if not allowed_url(args.url):
        parser.error("URL is not an official public ATS HTTPS host")
    print(json.dumps(asyncio.run(inspect(args.url)), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
