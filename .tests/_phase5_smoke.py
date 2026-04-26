import asyncio
import time

from src.modules.inference.domain.models.enums import (
    Classification, OverrideTrigger, ResolveStatus, RiskLevel, ScrapeStatus,
)
from src.modules.inference.domain.services import (
    AggregationEmail, AggregationService,
    EmailClassificationService, ExtractedLink,
    LinkResolutionService,
    PageAnalysisResult, PageAnalysisService,
)
from src.modules.inference.internal.link_unshortener import ResolvedUrl
from src.modules.inference.internal.page_scraper import ScrapedPage
from src.shared.exceptions import ServiceUnavailableException


# ── 1. EmailClassificationService ──────────────────────────────
async def test_classification():
    async def fake_groq(messages):
        assert isinstance(messages, list)
        assert messages[0]["role"] == "user"
        assert "<email_body>" in messages[0]["content"]
        return {
            "classification": "phishing",
            "confidence": 0.92,
            "reasoning": "spoofed sender",
            "risk_factors": ["urgency", "credential request"],
            "links": [
                {"url": "https://bit.ly/abc", "is_shortened": True,
                 "shortener_service": "bit.ly", "context": "click here"},
                {"url": "https://example.com", "is_shortened": False,
                 "shortener_service": None, "context": None},
                {"is_shortened": False},  # no url — should be dropped
            ],
        }
    svc = EmailClassificationService(client_callable=fake_groq)
    result = await svc.classify("evil@x.com", "Subj", "BODY")
    assert result.classification == Classification.PHISHING
    assert result.confidence == 0.92
    assert result.reasoning == "spoofed sender"
    assert result.risk_factors == ["urgency", "credential request"]
    assert len(result.links) == 2
    assert result.links[0].is_shortened is True
    assert result.links[0].shortener_service == "bit.ly"
    assert result.links[1].context is None
    print("EmailClassificationService (success): parsed JSON, dropped malformed link OK")

    async def malformed(messages):
        return {"confidence": 0.5}  # no classification
    raised = False
    try:
        await EmailClassificationService(client_callable=malformed).classify("a", "b", "c")
    except ServiceUnavailableException as e:
        assert e.error_detail.code == "LLM_UNAVAILABLE"
        raised = True
    assert raised
    print("EmailClassificationService (malformed): raises LLM_UNAVAILABLE OK")

    async def not_a_dict(messages):
        return ["wrong"]
    raised = False
    try:
        await EmailClassificationService(client_callable=not_a_dict).classify("a", "b", "c")
    except ServiceUnavailableException as e:
        assert e.error_detail.code == "LLM_UNAVAILABLE"
        raised = True
    assert raised
    print("EmailClassificationService (non-dict): raises LLM_UNAVAILABLE OK")

asyncio.run(test_classification())


# ── 2. LinkResolutionService ───────────────────────────────────
async def test_resolution():
    async def fake_unshorten(url):
        if "bad" in url:
            raise RuntimeError("unshorten boom")
        return ResolvedUrl(
            original_url=url,
            resolved_url=url.replace("bit.ly/abc", "example.com/final"),
            status=ResolveStatus.SUCCESS,
            hops=1,
            intermediate_domains=["bit.ly"],
            http_status=200,
            attempt=1,
        )

    scrape_called: list[str] = []
    async def fake_scrape(url):
        scrape_called.append(url)
        if "blocked" in url:
            return ScrapedPage(url=url, scrape_status=ScrapeStatus.BLOCKED, error="403")
        return ScrapedPage(
            url=url, page_title="t", body_text="hi",
            http_status=200, scrape_status=ScrapeStatus.SUCCESS,
        )

    svc = LinkResolutionService(
        unshorten=fake_unshorten, scrape=fake_scrape, max_concurrency=2,
    )

    links = [
        ExtractedLink(url="https://bit.ly/abc", is_shortened=True,
                      shortener_service="bit.ly", context="click"),
        ExtractedLink(url="https://example.com/blocked"),
        ExtractedLink(url="https://example.com/bad"),
    ]
    out = await svc.resolve_all(links)
    assert len(out) == 3

    # success path
    assert out[0].resolve_status == ResolveStatus.SUCCESS
    assert out[0].resolved_url == "https://example.com/final"
    assert out[0].redirect_hops == 1
    assert out[0].scraped_page is not None
    assert out[0].scraped_page.scrape_status == ScrapeStatus.SUCCESS

    # scrape blocked but resolve succeeded
    assert out[1].resolve_status == ResolveStatus.SUCCESS
    assert out[1].scraped_page.scrape_status == ScrapeStatus.BLOCKED

    # unshorten exception → FAILED, no scrape attempted
    assert out[2].resolve_status == ResolveStatus.FAILED
    assert out[2].scraped_page is None
    assert "https://example.com/bad" not in scrape_called
    print("LinkResolutionService: per-link failure isolated, semaphore in place OK")

    # empty input
    assert await svc.resolve_all([]) == []
    print("LinkResolutionService (empty): returns [] OK")

    # semaphore concurrency cap
    in_flight = 0
    peak = 0
    async def slow_unshorten(url):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            await asyncio.sleep(0.05)
            return ResolvedUrl(original_url=url, resolved_url=url,
                               status=ResolveStatus.SUCCESS, hops=0,
                               intermediate_domains=[], http_status=200, attempt=1)
        finally:
            in_flight -= 1

    async def noop_scrape(url):
        return ScrapedPage(url=url)

    svc2 = LinkResolutionService(
        unshorten=slow_unshorten, scrape=noop_scrape, max_concurrency=3,
    )
    many = [ExtractedLink(url=f"https://x.test/{i}") for i in range(10)]
    started = time.monotonic()
    res = await svc2.resolve_all(many)
    elapsed = time.monotonic() - started
    assert len(res) == 10
    assert peak <= 3, f"semaphore violated: peak={peak}"
    assert elapsed >= 0.05 * (10 / 3), f"elapsed={elapsed:.3f}"
    print(f"LinkResolutionService (concurrency cap): peak={peak} <= 3 OK")

asyncio.run(test_resolution())


# ── 3. PageAnalysisService ─────────────────────────────────────
async def test_page_analysis():
    captured = {}
    async def fake_gemini(prompt):
        captured["prompt"] = prompt
        # Return out-of-order to verify alignment
        return [
            {"page_index": 2, "url": "https://b.test", "page_purpose": "second",
             "impersonates_brand": None, "requests_credentials": False,
             "requests_payment": True, "risk_level": "low",
             "risk_confidence": 0.2, "risk_reasons": ["clean"], "summary": "fine"},
            {"page_index": 1, "url": "https://a.test", "page_purpose": "login",
             "impersonates_brand": "PayPal", "requests_credentials": True,
             "requests_payment": False, "risk_level": "high",
             "risk_confidence": 0.95, "risk_reasons": ["cred form", "brand"],
             "summary": "fake login"},
        ]
    svc = PageAnalysisService(client_callable=fake_gemini)
    pages = [
        {"resolved_url": "https://a.test", "page_title": "A", "has_login_form": True,
         "external_domains": ["cdn.x"], "content": "login here"},
        {"resolved_url": "https://b.test", "page_title": "B", "has_payment_form": True,
         "content": "buy now"},
    ]
    out = await svc.analyse_batch(pages)
    assert len(out) == 2
    # Aligned to input order (1-based) — out[0] is page_index=1
    assert out[0].page_index == 1
    assert out[0].url == "https://a.test"
    assert out[0].risk_level == RiskLevel.HIGH
    assert out[0].risk_confidence == 0.95
    assert out[0].impersonates_brand == "PayPal"
    assert out[0].requests_credentials is True
    assert out[1].page_index == 2
    assert out[1].risk_level == RiskLevel.LOW
    assert "PAGE_1:" in captured["prompt"] and "PAGE_2:" in captured["prompt"]
    print("PageAnalysisService (success): out-of-order response realigned OK")

    # Empty input → no API call
    called = False
    async def explode(prompt):
        nonlocal called
        called = True
        return []
    assert await PageAnalysisService(client_callable=explode).analyse_batch([]) == []
    assert called is False
    print("PageAnalysisService (empty): no API call, returns [] OK")

    # Malformed: object instead of array
    async def wrong_shape(prompt):
        return {"oops": "not a list"}
    raised = False
    try:
        await PageAnalysisService(client_callable=wrong_shape).analyse_batch([{"url": "x"}])
    except ServiceUnavailableException as e:
        assert e.error_detail.code == "LLM_UNAVAILABLE"
        raised = True
    assert raised
    print("PageAnalysisService (malformed): raises LLM_UNAVAILABLE OK")

    # Missing entry for page_index=2 → fallback empty result
    async def partial(prompt):
        return [
            {"page_index": 1, "risk_level": "medium", "risk_confidence": 0.5,
             "risk_reasons": ["odd"], "url": "https://a.test"},
        ]
    out = await PageAnalysisService(client_callable=partial).analyse_batch([
        {"resolved_url": "https://a.test"},
        {"resolved_url": "https://missing.test"},
    ])
    assert out[0].risk_level == RiskLevel.MEDIUM
    assert out[1].risk_level is None
    assert out[1].url == "https://missing.test"
    print("PageAnalysisService (partial): missing entry fallback OK")

asyncio.run(test_page_analysis())


# ── 4. AggregationService — all five rule cases ────────────────
agg = AggregationService()


def _page(i, level, conf=0.8, url=None, reasons=None, brand=None):
    return PageAnalysisResult(
        page_index=i,
        url=url or f"https://page{i}.test",
        risk_level=level,
        risk_confidence=conf,
        risk_reasons=reasons or [],
        impersonates_brand=brand,
    )


# Rule 1 — early exit
e1 = AggregationEmail(classification=Classification.PHISHING, confidence=0.93, link_count=4)
out1 = agg.finalise(e1, [], early_exit=True)
assert out1.final_classification == Classification.PHISHING
assert out1.final_confidence == 0.93
assert out1.override_trigger == OverrideTrigger.EARLY_EXIT
assert "early exit rule triggered" in out1.aggregation_note
assert "0.93" in out1.aggregation_note
print(f"Rule 1 (early exit): {out1.override_trigger.value} | {out1.aggregation_note!r}")

# Rule 2 (single page) — escalate to phishing
e2 = AggregationEmail(classification=Classification.LEGITIMATE, confidence=0.72, link_count=1)
pages2 = [_page(2, RiskLevel.HIGH, conf=0.94,
               url="https://paypal-secure-login.xyz/login",
               reasons=["credential harvesting form", "impersonates PayPal"],
               brand="PayPal")]
out2 = agg.finalise(e2, pages2)
assert out2.final_classification == Classification.PHISHING
assert out2.final_confidence == 0.94
assert out2.override_trigger == OverrideTrigger.PAGE_HIGH_RISK
assert "Original: legitimate (0.72)" in out2.aggregation_note
assert "page 2" in out2.aggregation_note
assert "paypal-secure-login.xyz" in out2.aggregation_note
assert "credential harvesting form, impersonates PayPal" in out2.aggregation_note
print(f"Rule 2 (single high): {out2.override_trigger.value}")

# Rule 2 (multi-page) — escalate to phishing
e2m = AggregationEmail(classification=Classification.SUSPICIOUS, confidence=0.61, link_count=5)
pages2m = [
    _page(1, RiskLevel.HIGH, 0.9,  url="https://domain-a.com",
          reasons=["credential harvesting"]),
    _page(2, RiskLevel.LOW,  0.1),
    _page(3, RiskLevel.HIGH, 0.96, url="https://domain-b.xyz",
          reasons=["payment form impersonating Nedbank"]),
    _page(4, RiskLevel.LOW,  0.2),
    _page(5, RiskLevel.HIGH, 0.88, url="https://domain-c.net",
          reasons=["brand impersonation Microsoft"]),
]
out2m = agg.finalise(e2m, pages2m)
assert out2m.final_classification == Classification.PHISHING
assert out2m.final_confidence == 0.96
assert out2m.override_trigger == OverrideTrigger.PAGE_HIGH_RISK
assert "Original: suspicious (0.61)" in out2m.aggregation_note
assert "3 pages flagged high risk" in out2m.aggregation_note
assert "page 1 (domain-a.com): credential harvesting" in out2m.aggregation_note
assert "page 3 (domain-b.xyz): payment form impersonating Nedbank" in out2m.aggregation_note
assert "page 5 (domain-c.net): brand impersonation Microsoft" in out2m.aggregation_note
print(f"Rule 2 (multi high): {out2m.override_trigger.value}")

# Rule 3 — escalate to suspicious (medium + original legitimate)
e3 = AggregationEmail(classification=Classification.LEGITIMATE, confidence=0.58, link_count=1)
pages3 = [_page(4, RiskLevel.MEDIUM, conf=0.66,
                url="https://offers-win.com",
                reasons=["unusual external domains", "no clear page purpose"])]
out3 = agg.finalise(e3, pages3)
assert out3.final_classification == Classification.SUSPICIOUS
assert out3.final_confidence == 0.66
assert out3.override_trigger == OverrideTrigger.PAGE_MEDIUM_RISK
assert "Original: legitimate (0.58)" in out3.aggregation_note
assert "page 4 (offers-win.com)" in out3.aggregation_note
assert "unusual external domains, no clear page purpose" in out3.aggregation_note
print(f"Rule 3 (medium -> suspicious): {out3.override_trigger.value}")

# Rule 3 negative — medium + original NOT legitimate → falls through to Rule 4
e3n = AggregationEmail(classification=Classification.PHISHING, confidence=0.91, link_count=2)
pages3n = [_page(1, RiskLevel.MEDIUM, 0.5), _page(2, RiskLevel.LOW, 0.1)]
out3n = agg.finalise(e3n, pages3n)
assert out3n.final_classification == Classification.PHISHING
assert out3n.override_trigger == OverrideTrigger.ALL_LOW
print(f"Rule 3 negative (medium but original phishing): keeps {out3n.final_classification.value}")

# Rule 4 — all low, keep original
e4 = AggregationEmail(classification=Classification.PHISHING, confidence=0.91, link_count=5)
pages4 = [_page(i, RiskLevel.LOW, 0.1 + i * 0.05) for i in range(1, 6)]
out4 = agg.finalise(e4, pages4)
assert out4.final_classification == Classification.PHISHING
assert out4.final_confidence == 0.91
assert out4.override_trigger == OverrideTrigger.ALL_LOW
assert "All 5 pages low risk" in out4.aggregation_note
assert "phishing (0.91)" in out4.aggregation_note
print(f"Rule 4 (all low): {out4.override_trigger.value}")

# Rule 5 — all scrapes failed
e5 = AggregationEmail(classification=Classification.SUSPICIOUS, confidence=0.55, link_count=3)
out5 = agg.finalise(e5, [])
assert out5.final_classification == Classification.SUSPICIOUS
assert out5.final_confidence == 0.55
assert out5.override_trigger == OverrideTrigger.ALL_FAILED
assert "All 3 links failed to resolve" in out5.aggregation_note
assert "manual review recommended" in out5.aggregation_note
print(f"Rule 5 (all failed): {out5.override_trigger.value}")

# No-link email with empty results — should NOT trigger Rule 5 (link_count=0)
e_no = AggregationEmail(classification=Classification.LEGITIMATE, confidence=0.8, link_count=0)
out_no = agg.finalise(e_no, [])
assert out_no.override_trigger == OverrideTrigger.ALL_LOW
assert out_no.final_classification == Classification.LEGITIMATE
print(f"Edge (no links at all): {out_no.override_trigger.value}")

print()
print("All Phase-5 stage-service smoke tests passed.")
