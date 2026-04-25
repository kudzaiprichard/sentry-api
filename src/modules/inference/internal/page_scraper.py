from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.configs import inference
from src.modules.inference.domain.models.enums import ScrapeStatus


_PAYMENT_KEYWORDS = (
    "card", "cardnumber", "cc-", "ccnumber", "cvc", "cvv",
    "expiry", "expir", "billing", "creditcard",
)


@dataclass
class ScrapedPage:
    url: str
    page_title: Optional[str] = None
    meta_description: Optional[str] = None
    has_login_form: bool = False
    has_payment_form: bool = False
    external_domains: list[str] = field(default_factory=list)
    favicon_matches_domain: Optional[bool] = None
    body_text: str = ""
    http_status: Optional[int] = None
    scrape_status: ScrapeStatus = ScrapeStatus.SUCCESS
    error: Optional[str] = None


def _host(url: str) -> str:
    try:
        h = urlparse(url).hostname or ""
    except Exception:
        return ""
    return h.lower().lstrip("www.")


def parse_html(html: str, url: str, *, http_status: Optional[int] = None) -> ScrapedPage:
    soup = BeautifulSoup(html or "", "lxml")
    page = ScrapedPage(url=url, http_status=http_status)

    title_tag = soup.find("title")
    page.page_title = title_tag.get_text(strip=True) if title_tag else None

    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        page.meta_description = meta["content"].strip()

    page.has_login_form = bool(soup.find("input", attrs={"type": "password"}))

    payment_match = False
    for inp in soup.find_all("input"):
        name = (inp.get("name") or inp.get("id") or "").lower()
        autocomplete = (inp.get("autocomplete") or "").lower()
        haystack = name + " " + autocomplete
        if any(k in haystack for k in _PAYMENT_KEYWORDS):
            payment_match = True
            break
    page.has_payment_form = payment_match

    page_host = _host(url)
    externals: set[str] = set()
    for tag, attr in (("script", "src"), ("link", "href"), ("img", "src")):
        for el in soup.find_all(tag):
            src = el.get(attr)
            if not src:
                continue
            host = _host(src)
            if host and host != page_host:
                externals.add(host)
    page.external_domains = sorted(externals)

    favicon = soup.find("link", attrs={"rel": lambda v: v and "icon" in (v if isinstance(v, list) else [v])})
    if favicon and favicon.get("href"):
        fav_host = _host(favicon["href"])
        if fav_host:
            page.favicon_matches_domain = fav_host == page_host

    body = soup.body or soup
    text = " ".join(body.get_text(separator=" ", strip=True).split())
    cap = inference.scraping.content_char_cap
    page.body_text = text[:cap]

    return page


async def fetch_and_parse(
    url: str,
    *,
    timeout: float,
    user_agent: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> ScrapedPage:
    headers = {"User-Agent": user_agent} if user_agent else {}
    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers
        )
    try:
        try:
            response = await client.get(url, headers=headers if not own_client else None)
        except httpx.TimeoutException as e:
            return ScrapedPage(url=url, scrape_status=ScrapeStatus.TIMEOUT, error=str(e))
        except httpx.HTTPError as e:
            return ScrapedPage(url=url, scrape_status=ScrapeStatus.BLOCKED, error=str(e))
    finally:
        if own_client:
            await client.aclose()

    final_url = str(response.url)
    page = parse_html(response.text, final_url, http_status=response.status_code)
    return page
