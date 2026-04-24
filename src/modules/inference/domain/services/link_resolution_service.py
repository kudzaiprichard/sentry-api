import asyncio
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional, Sequence

from src.configs import inference
from src.modules.inference.domain.models.enums import ResolveStatus, ScrapeStatus
from src.modules.inference.domain.services.email_classification_service import (
    ExtractedLink,
)
from src.modules.inference.internal import (
    link_unshortener,
    page_scraper,
)
from src.modules.inference.internal.link_unshortener import ResolvedUrl
from src.modules.inference.internal.page_scraper import ScrapedPage


logger = logging.getLogger(__name__)


@dataclass
class ResolvedLink:
    original_url: str
    is_shortened: bool = False
    shortener: Optional[str] = None
    anchor_context: Optional[str] = None
    resolved_url: Optional[str] = None
    resolve_status: ResolveStatus = ResolveStatus.BLOCKED
    redirect_hops: int = 0
    intermediate_domains: list[str] = field(default_factory=list)
    http_status: Optional[int] = None
    scraped_page: Optional[ScrapedPage] = None


UnshortenFn = Callable[[str], Awaitable[ResolvedUrl]]
ScrapeFn = Callable[[str], Awaitable[ScrapedPage]]


class LinkResolutionService:
    """Stage 2 — resolve every link concurrently, then scrape successes.

    Per-link failures become ResolvedLink rows with a non-SUCCESS resolve_status;
    they never propagate. Concurrency is capped via an asyncio.Semaphore so a
    burst of links cannot exhaust descriptors or browser slots.
    """

    def __init__(
        self,
        unshorten: Optional[UnshortenFn] = None,
        scrape: Optional[ScrapeFn] = None,
        max_concurrency: Optional[int] = None,
    ):
        self._unshorten = unshorten or self._default_unshorten
        self._scrape = scrape or self._default_scrape
        self._max_concurrency = (
            max_concurrency
            if max_concurrency is not None
            else inference.pipeline.max_concurrent_link_tasks
        )

    @staticmethod
    async def _default_unshorten(url: str) -> ResolvedUrl:
        return await link_unshortener.resolve_url(url)

    @staticmethod
    async def _default_scrape(url: str) -> ScrapedPage:
        return await page_scraper.fetch_and_parse(
            url,
            timeout=inference.scraping.attempt_2_timeout,
            user_agent=inference.scraping.user_agent,
        )

    async def resolve_all(
        self, links: Sequence[ExtractedLink]
    ) -> list[ResolvedLink]:
        if not links:
            return []

        sem = asyncio.Semaphore(max(1, self._max_concurrency))

        async def _one(link: ExtractedLink) -> ResolvedLink:
            async with sem:
                return await self._resolve_one(link)

        results = await asyncio.gather(
            *(_one(l) for l in links), return_exceptions=True
        )

        out: list[ResolvedLink] = []
        for link, res in zip(links, results):
            if isinstance(res, BaseException):
                logger.warning(
                    "link resolution raised: %s url=%s", res, link.url
                )
                out.append(
                    ResolvedLink(
                        original_url=link.url,
                        is_shortened=link.is_shortened,
                        shortener=link.shortener_service,
                        anchor_context=link.context,
                        resolve_status=ResolveStatus.FAILED,
                    )
                )
            else:
                out.append(res)
        return out

    async def _resolve_one(self, link: ExtractedLink) -> ResolvedLink:
        try:
            resolved = await self._unshorten(link.url)
        except Exception as e:
            logger.warning("unshorten failed url=%s err=%s", link.url, e)
            return ResolvedLink(
                original_url=link.url,
                is_shortened=link.is_shortened,
                shortener=link.shortener_service,
                anchor_context=link.context,
                resolve_status=ResolveStatus.FAILED,
            )

        scraped: Optional[ScrapedPage] = None
        if (
            resolved.status == ResolveStatus.SUCCESS
            and resolved.resolved_url
        ):
            try:
                scraped = await self._scrape(resolved.resolved_url)
            except Exception as e:
                logger.warning(
                    "scrape failed url=%s err=%s", resolved.resolved_url, e
                )
                scraped = ScrapedPage(
                    url=resolved.resolved_url,
                    scrape_status=ScrapeStatus.BLOCKED,
                    error=str(e),
                )

        return ResolvedLink(
            original_url=link.url,
            is_shortened=link.is_shortened,
            shortener=link.shortener_service,
            anchor_context=link.context,
            resolved_url=resolved.resolved_url,
            resolve_status=resolved.status,
            redirect_hops=resolved.hops,
            intermediate_domains=list(resolved.intermediate_domains or []),
            http_status=resolved.http_status,
            scraped_page=scraped,
        )
