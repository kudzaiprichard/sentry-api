"""Phase 6 smoke: full PENDING → RUNNING → COMPLETE lifecycle and
forced-failure injection at each of the four stages.

Hits a real Postgres database (uses the configured DATABASE_URL) but stubs all
LLM/network calls via mocked stage services.
"""
import asyncio
from datetime import datetime, timezone

from src.modules.auth.domain.models.user import User  # noqa: F401 — registers FK target
from src.modules.inference.domain.models.email import Email
from src.modules.inference.domain.models.enums import (
    Classification, PipelineStage, PipelineStatus, ResolveStatus, RiskLevel,
    ScrapeStatus,
)
from src.modules.inference.domain.repositories import (
    EmailRepository, LinkRepository, PageAnalysisRepository,
)
from src.modules.inference.domain.services import (
    AggregationService, EmailClassificationResult, EmailClassificationService,
    ExtractedLink, InferenceService, LinkResolutionService,
    PageAnalysisResult, PageAnalysisService, ResolvedLink,
)
from src.modules.inference.internal import pipeline_runner
from src.modules.inference.internal.page_scraper import ScrapedPage
from src.shared.database import async_session


# ── Mock factories ───────────────────────────────────────────────────────


async def mock_classify_phishing(sender, subject, body):
    return EmailClassificationResult(
        classification=Classification.SUSPICIOUS,
        confidence=0.55,
        reasoning="mock — looks dodgy",
        risk_factors=["mock urgency", "mock impersonation"],
        links=[
            ExtractedLink(url="https://bit.ly/abc", is_shortened=True,
                          shortener_service="bit.ly", context="click here"),
            ExtractedLink(url="https://example.com/about"),
        ],
        model_name="mock-llama",
    )


async def mock_classify_early_exit(sender, subject, body):
    return EmailClassificationResult(
        classification=Classification.PHISHING,
        confidence=0.97,
        reasoning="obvious",
        risk_factors=["spoofed sender"],
        links=[ExtractedLink(url="https://bit.ly/abc", is_shortened=True)],
        model_name="mock-llama",
    )


async def mock_resolve_all_success(links):
    out = []
    for i, l in enumerate(links):
        scraped = ScrapedPage(
            url=f"https://landing-{i}.test",
            page_title=f"Landing {i}",
            meta_description="desc",
            has_login_form=(i == 0),
            has_payment_form=False,
            external_domains=["cdn.test"],
            body_text="welcome please sign in",
            http_status=200,
            scrape_status=ScrapeStatus.SUCCESS,
        )
        out.append(ResolvedLink(
            original_url=l.url,
            is_shortened=l.is_shortened,
            shortener=l.shortener_service,
            anchor_context=l.context,
            resolved_url=f"https://landing-{i}.test",
            resolve_status=ResolveStatus.SUCCESS,
            redirect_hops=1,
            intermediate_domains=["bit.ly"] if l.is_shortened else [],
            http_status=200,
            scraped_page=scraped,
        ))
    return out


async def mock_analyse_batch_high(pages):
    out = []
    for i, p in enumerate(pages, start=1):
        # First page high risk → triggers Rule 2 escalation to phishing
        if i == 1:
            out.append(PageAnalysisResult(
                page_index=i,
                url=p.get("resolved_url") or "",
                page_purpose="credential harvest",
                impersonates_brand="PayPal",
                requests_credentials=True,
                requests_payment=False,
                risk_level=RiskLevel.HIGH,
                risk_confidence=0.95,
                risk_reasons=["credential harvesting form", "impersonates PayPal"],
                summary="fake login",
                model_name="mock-gemini",
            ))
        else:
            out.append(PageAnalysisResult(
                page_index=i,
                url=p.get("resolved_url") or "",
                page_purpose="benign",
                impersonates_brand=None,
                requests_credentials=False,
                requests_payment=False,
                risk_level=RiskLevel.LOW,
                risk_confidence=0.1,
                risk_reasons=["nothing notable"],
                summary="ok",
                model_name="mock-gemini",
            ))
    return out


def build_happy_service(*, fail_stage: str | None = None) -> InferenceService:
    cls_svc = EmailClassificationService()
    res_svc = LinkResolutionService()
    pa_svc = PageAnalysisService()
    agg_svc = AggregationService()

    cls_svc.classify = mock_classify_phishing
    res_svc.resolve_all = mock_resolve_all_success
    pa_svc.analyse_batch = mock_analyse_batch_high

    if fail_stage == "classify":
        async def boom(sender, subject, body):
            raise RuntimeError("Stage-1 forced failure")
        cls_svc.classify = boom
    elif fail_stage == "resolve":
        async def boom(links):
            raise RuntimeError("Stage-2 forced failure")
        res_svc.resolve_all = boom
    elif fail_stage == "analyse":
        async def boom(pages):
            raise RuntimeError("Stage-3 forced failure")
        pa_svc.analyse_batch = boom
    elif fail_stage == "aggregate":
        def boom(email, page_results, *, early_exit=False):
            raise RuntimeError("Stage-4 forced failure")
        agg_svc.finalise = boom

    return InferenceService(
        email_repo=None, link_repo=None, page_analysis_repo=None,
        classification_service=cls_svc,
        resolution_service=res_svc,
        page_analysis_service=pa_svc,
        aggregation_service=agg_svc,
    )


def patch_runner(fail_stage: str | None = None):
    pipeline_runner._build_service = lambda: build_happy_service(
        fail_stage=fail_stage
    )


# ── Helpers ──────────────────────────────────────────────────────────────


async def submit_email(*, fail_stage: str | None = None):
    """Submit one email through the request-scoped service."""
    patch_runner(fail_stage=fail_stage)
    async with async_session() as session:
        async with session.begin():
            svc = InferenceService(
                email_repo=EmailRepository(session),
                link_repo=LinkRepository(session),
                page_analysis_repo=PageAnalysisRepository(session),
                classification_service=EmailClassificationService(
                    client_callable=lambda **kw: None
                ),
            )
            email = await svc.submit(
                sender="alice@x.test",
                subject="hi",
                body=f"body-{datetime.now().isoformat()}-{fail_stage}",
                received_at=datetime.now(timezone.utc),
                user_id=None,
            )
            email_id = email.id
    return email_id


async def find_task(email_id) -> asyncio.Task | None:
    name = f"pipeline:{email_id}"
    for t in pipeline_runner.in_flight_tasks():
        if t.get_name() == name:
            return t
    return None


async def wait_for_pipeline(email_id, *, timeout: float = 10.0):
    task = await find_task(email_id)
    if task is None:
        return
    try:
        await asyncio.wait_for(task, timeout=timeout)
    except asyncio.TimeoutError:
        raise RuntimeError(f"pipeline {email_id} did not finish in {timeout}s")
    except Exception:
        # task swallows exceptions internally → marks FAILED. shouldn't raise.
        pass


async def load_email(email_id) -> Email:
    async with async_session() as session:
        row = await session.get(Email, email_id)
        return row


# ── Tests ────────────────────────────────────────────────────────────────


async def test_happy_path():
    print("\n── happy path: PENDING → RUNNING → COMPLETE ──")
    email_id = await submit_email()

    # Right after submit (before task runs to completion), task should be
    # tracked in the runner's in-flight set.
    assert await find_task(email_id) is not None, "task not tracked in _in_flight"
    print(f"  task tracked in _in_flight set OK (id={email_id})")

    await wait_for_pipeline(email_id)

    # After completion, the task should have been removed from the set.
    assert await find_task(email_id) is None, "task not removed from _in_flight"
    print("  task removed from _in_flight after done OK")

    email = await load_email(email_id)
    assert email is not None
    assert email.pipeline_status == PipelineStatus.COMPLETE, email.pipeline_status
    assert email.pipeline_stage == PipelineStage.DONE, email.pipeline_stage
    assert email.classification == Classification.SUSPICIOUS
    assert email.confidence == 0.55
    assert email.link_count == 2
    assert email.llm_model == "mock-llama"
    assert email.processed_at is not None
    assert email.finalised_at is not None
    # Aggregation: page-1 high risk → escalate to phishing
    assert email.final_classification == Classification.PHISHING
    assert email.final_confidence == 0.95
    assert email.aggregation_note is not None
    assert "Escalated to phishing" in email.aggregation_note
    print(f"  status={email.pipeline_status.value}, "
          f"final={email.final_classification.value} "
          f"({email.final_confidence}) OK")

    # Verify links + page_analysis cascade was written
    async with async_session() as session:
        repo = EmailRepository(session)
        full = await repo.get_with_full_detail(email_id)
        assert len(full.links) == 2, len(full.links)
        # First link should have a page_analysis row (we marked all SUCCESS)
        assert all(l.page_analysis is not None for l in full.links)
        assert any(
            l.page_analysis.risk_level == RiskLevel.HIGH for l in full.links
        )
    print("  links + page_analysis rows persisted with cascade OK")


async def test_early_exit():
    print("\n── early exit: skip stages 2+3 ──")
    pipeline_runner._build_service = lambda: _early_exit_svc()
    async with async_session() as session:
        async with session.begin():
            svc = InferenceService(
                email_repo=EmailRepository(session),
                link_repo=LinkRepository(session),
                page_analysis_repo=PageAnalysisRepository(session),
            )
            email = await svc.submit(
                sender="evil@x.test", subject="urgent",
                body=f"obvious-phishing-{datetime.now().isoformat()}",
                received_at=datetime.now(timezone.utc),
            )
            email_id = email.id
    await wait_for_pipeline(email_id)
    email = await load_email(email_id)
    assert email.pipeline_status == PipelineStatus.COMPLETE
    assert email.final_classification == Classification.PHISHING
    assert "early exit rule triggered" in email.aggregation_note
    # No links should have been processed
    async with async_session() as session:
        repo = EmailRepository(session)
        full = await repo.get_with_full_detail(email_id)
        assert len(full.links) == 0
    print(f"  early-exit complete, no links written, note={email.aggregation_note!r}")


def _early_exit_svc():
    cls = EmailClassificationService()
    cls.classify = mock_classify_early_exit
    return InferenceService(
        classification_service=cls,
        resolution_service=LinkResolutionService(),
        page_analysis_service=PageAnalysisService(),
        aggregation_service=AggregationService(),
    )


async def test_failure_at(stage: str):
    email_id = await submit_email(fail_stage=stage)
    await wait_for_pipeline(email_id)
    email = await load_email(email_id)
    assert email.pipeline_status == PipelineStatus.FAILED, (
        f"stage={stage} expected FAILED got {email.pipeline_status}"
    )
    assert email.pipeline_error is not None
    assert "forced failure" in email.pipeline_error.lower()
    print(f"  stage='{stage}' → FAILED, error={email.pipeline_error!r}")


async def main():
    await test_happy_path()
    await test_early_exit()

    print("\n── forced failure injection at each stage ──")
    for stage in ["classify", "resolve", "analyse", "aggregate"]:
        await test_failure_at(stage)

    print("\nAll Phase-6 lifecycle tests passed.")


asyncio.run(main())
