# Requires the chromium browser binary. Run once per environment:
#     python -m playwright install chromium

import asyncio
from typing import Optional

from src.modules.inference.domain.models.enums import ScrapeStatus
from src.modules.inference.internal.page_scraper import ScrapedPage, parse_html


_browser_lock = asyncio.Lock()
_browser = None
_pw = None


async def _get_browser():
    global _browser, _pw
    async with _browser_lock:
        if _browser is None:
            from playwright.async_api import async_playwright
            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(headless=True)
        return _browser


async def shutdown_browser() -> None:
    global _browser, _pw
    async with _browser_lock:
        if _browser is not None:
            await _browser.close()
            _browser = None
        if _pw is not None:
            await _pw.stop()
            _pw = None


async def fetch_with_browser(url: str, *, timeout: float) -> ScrapedPage:
    """Render the page in headless chromium and return a parsed ScrapedPage."""
    timeout_ms = int(timeout * 1000)
    try:
        browser = await _get_browser()
        context = await browser.new_context()
        try:
            page = await context.new_page()
            response = await page.goto(url, timeout=timeout_ms, wait_until="load")
            html = await page.content()
            final_url = page.url
            status = response.status if response else None
        finally:
            await context.close()
    except Exception as e:
        msg = str(e).lower()
        if "timeout" in msg:
            status = ScrapeStatus.TIMEOUT
        else:
            status = ScrapeStatus.BLOCKED
        return ScrapedPage(url=url, scrape_status=status, error=str(e))

    parsed = parse_html(html, final_url, http_status=status)
    return parsed


async def resolve_with_browser(
    url: str, *, timeout: float
) -> tuple[Optional[str], Optional[int], int]:
    """Follow JS-driven redirects and return (final_url, http_status, hops)."""
    timeout_ms = int(timeout * 1000)
    try:
        browser = await _get_browser()
        context = await browser.new_context()
        try:
            page = await context.new_page()
            hops = 0

            def on_response(resp):
                nonlocal hops
                if resp.request.is_navigation_request() and 300 <= resp.status < 400:
                    hops += 1

            page.on("response", on_response)
            response = await page.goto(url, timeout=timeout_ms, wait_until="load")
            return page.url, (response.status if response else None), hops
        finally:
            await context.close()
    except Exception:
        return None, None, 0
