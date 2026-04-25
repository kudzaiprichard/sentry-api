import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx

from src.configs import inference
from src.modules.inference.domain.models.enums import ResolveStatus


@dataclass
class ResolvedUrl:
    original_url: str
    resolved_url: Optional[str] = None
    status: ResolveStatus = ResolveStatus.BLOCKED
    hops: int = 0
    intermediate_domains: list[str] = field(default_factory=list)
    http_status: Optional[int] = None
    elapsed_ms: int = 0
    attempt: int = 0
    error: Optional[str] = None


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


async def _httpx_attempt(
    url: str,
    timeout: float,
    user_agent: Optional[str],
    client: Optional[httpx.AsyncClient] = None,
) -> tuple[Optional[str], Optional[int], int, list[str]]:
    headers = {"User-Agent": user_agent} if user_agent else None
    own = client is None
    if own:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers)
    try:
        response = await client.get(url, headers=headers if not own else None)
        history = list(response.history)
        intermediate = [_host(str(r.url)) for r in history if _host(str(r.url))]
        return str(response.url), response.status_code, len(history), intermediate
    finally:
        if own:
            await client.aclose()


async def resolve_url(
    url: str,
    *,
    user_agent: Optional[str] = None,
    timeout_1: Optional[float] = None,
    timeout_2: Optional[float] = None,
    timeout_3: Optional[float] = None,
    httpx_client: Optional[httpx.AsyncClient] = None,
    use_playwright: bool = True,
) -> ResolvedUrl:
    """
    Three-attempt escalation:
      1. plain httpx GET, follow_redirects=True
      2. httpx GET with a real browser User-Agent
      3. Playwright headless render

    Each attempt is wrapped in asyncio.wait_for so a slow link cannot
    block the pipeline.
    """
    cfg = inference.scraping
    t1 = timeout_1 if timeout_1 is not None else cfg.attempt_1_timeout
    t2 = timeout_2 if timeout_2 is not None else cfg.attempt_2_timeout
    t3 = timeout_3 if timeout_3 is not None else cfg.attempt_3_timeout
    ua = user_agent if user_agent is not None else cfg.user_agent

    started = time.monotonic()
    last_exc: Optional[BaseException] = None

    # ── Attempt 1: plain httpx ────────────────────────────────
    try:
        final, status, hops, inter = await asyncio.wait_for(
            _httpx_attempt(url, t1, None, httpx_client), timeout=t1
        )
        return ResolvedUrl(
            original_url=url,
            resolved_url=final,
            status=ResolveStatus.SUCCESS,
            hops=hops,
            intermediate_domains=inter,
            http_status=status,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            attempt=1,
        )
    except (asyncio.TimeoutError, httpx.HTTPError) as e:
        last_exc = e

    # ── Attempt 2: httpx with browser User-Agent ──────────────
    try:
        final, status, hops, inter = await asyncio.wait_for(
            _httpx_attempt(url, t2, ua, httpx_client), timeout=t2
        )
        return ResolvedUrl(
            original_url=url,
            resolved_url=final,
            status=ResolveStatus.SUCCESS,
            hops=hops,
            intermediate_domains=inter,
            http_status=status,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            attempt=2,
        )
    except (asyncio.TimeoutError, httpx.HTTPError) as e:
        last_exc = e

    # ── Attempt 3: Playwright headless ────────────────────────
    if use_playwright:
        try:
            from src.modules.inference.internal.playwright_scraper import (
                resolve_with_browser,
            )
            final, status, hops = await asyncio.wait_for(
                resolve_with_browser(url, timeout=t3), timeout=t3
            )
            if final:
                return ResolvedUrl(
                    original_url=url,
                    resolved_url=final,
                    status=ResolveStatus.SUCCESS,
                    hops=hops,
                    intermediate_domains=[],
                    http_status=status,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                    attempt=3,
                )
        except (asyncio.TimeoutError, Exception) as e:
            last_exc = e

    final_status = (
        ResolveStatus.TIMEOUT
        if isinstance(last_exc, asyncio.TimeoutError)
        else ResolveStatus.BLOCKED
    )
    return ResolvedUrl(
        original_url=url,
        resolved_url=None,
        status=final_status,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        error=str(last_exc) if last_exc else None,
    )
