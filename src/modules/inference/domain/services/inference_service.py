import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import select, update

from src.configs import inference
from src.modules.inference.domain.models.email import Email
from src.modules.inference.domain.models.enums import (
    Classification,
    PipelineStage,
    PipelineStatus,
    ScrapeStatus,
)
from src.modules.inference.domain.models.link import Link
from src.modules.inference.domain.models.page_analysis import PageAnalysis
from src.modules.inference.domain.repositories import (
    EmailRepository,
    LinkRepository,
    PageAnalysisRepository,
)
from src.modules.inference.domain.services.aggregation_service import (
    AggregationEmail,
    AggregationService,
)
from src.modules.inference.domain.services.email_classification_service import (
    EmailClassificationService,
)
from src.modules.inference.domain.services.link_resolution_service import (
    LinkResolutionService,
)
from src.modules.inference.domain.services.page_analysis_service import (
    PageAnalysisService,
)
from src.modules.inference.internal import body_hasher
from src.shared.database import async_session
from src.shared.exceptions import (
    BadRequestException,
    ConflictException,
    NotFoundException,
)
from src.shared.responses.api_response import ErrorDetail


logger = logging.getLogger(__name__)


@dataclass
class SubmitItem:
    sender: str
    subject: str
    body: str
    received_at: Optional[datetime] = None


@dataclass
class RejectedItem:
    index: int
    reason: str


class InferenceService:
    """Orchestrator — request-scoped methods + background pipeline runner.

    Request-scoped methods (`submit`, `submit_batch`, `reanalyze`,
    `apply_manual_review`) operate on the constructor-supplied session via the
    injected repositories.

    `run_pipeline` is invoked by the background runner on a fresh event-loop
    task; it opens its own per-stage sessions so that status transitions are
    visible to other connections while the pipeline is still running. It
    therefore does not use the constructor's repos.
    """

    def __init__(
        self,
        email_repo: Optional[EmailRepository] = None,
        link_repo: Optional[LinkRepository] = None,
        page_analysis_repo: Optional[PageAnalysisRepository] = None,
        *,
        classification_service: Optional[EmailClassificationService] = None,
        resolution_service: Optional[LinkResolutionService] = None,
        page_analysis_service: Optional[PageAnalysisService] = None,
        aggregation_service: Optional[AggregationService] = None,
    ):
        self.email_repo = email_repo
        self.link_repo = link_repo
        self.page_analysis_repo = page_analysis_repo
        self.classification_service = (
            classification_service or EmailClassificationService()
        )
        self.resolution_service = resolution_service or LinkResolutionService()
        self.page_analysis_service = (
            page_analysis_service or PageAnalysisService()
        )
        self.aggregation_service = aggregation_service or AggregationService()

    # ── Request-scoped methods ───────────────────────────────────────────

    async def submit(
        self,
        sender: str,
        subject: str,
        body: str,
        received_at: Optional[datetime] = None,
        user_id: Optional[UUID] = None,
        install_id: Optional[UUID] = None,
    ) -> Email:
        if self.email_repo is None:
            raise RuntimeError("submit requires a session-bound email_repo")

        email = Email(
            sender=sender,
            subject=subject,
            body_hash=body_hasher.hash_body(body),
            received_at=received_at or datetime.now(timezone.utc),
            pipeline_status=PipelineStatus.PENDING,
            pipeline_stage=PipelineStage.QUEUED,
            submitted_by=user_id,
            submitted_by_install=install_id,
            link_count=0,
        )
        saved = await self.email_repo.create(email)

        # Defer the import to avoid a module-load cycle with pipeline_runner.
        from src.modules.inference.internal import pipeline_runner
        pipeline_runner.spawn(saved.id, sender, subject, body)
        return saved

    async def submit_batch(
        self, items: Sequence[SubmitItem], user_id: Optional[UUID] = None
    ) -> tuple[list[Email], list[RejectedItem]]:
        if not items:
            raise BadRequestException(
                message="Batch is empty",
                error_detail=ErrorDetail(
                    title="Empty Batch",
                    code="BATCH_EMPTY",
                    status=400,
                    details=["At least one email is required"],
                ),
            )
        max_size = inference.pipeline.batch_max_size
        if len(items) > max_size:
            raise BadRequestException(
                message="Batch exceeds the configured maximum size",
                error_detail=ErrorDetail(
                    title="Batch Too Large",
                    code="BATCH_TOO_LARGE",
                    status=400,
                    details=[
                        f"Got {len(items)} emails; max is {max_size} per batch"
                    ],
                ),
            )

        submitted: list[Email] = []
        rejected: list[RejectedItem] = []
        for i, item in enumerate(items):
            try:
                email = await self.submit(
                    sender=item.sender,
                    subject=item.subject,
                    body=item.body,
                    received_at=item.received_at,
                    user_id=user_id,
                )
                submitted.append(email)
            except Exception as e:
                rejected.append(RejectedItem(index=i, reason=str(e)))
        return submitted, rejected

    async def reanalyze(self, email_id: UUID, body: str) -> Email:
        if self.email_repo is None or self.link_repo is None:
            raise RuntimeError(
                "reanalyze requires session-bound email_repo and link_repo"
            )

        email = await self.email_repo.get_by_id(email_id)
        if not email:
            raise NotFoundException(
                message="Email not found",
                error_detail=ErrorDetail(
                    title="Email Not Found",
                    code="EMAIL_NOT_FOUND",
                    status=404,
                    details=[f"No email with id {email_id}"],
                ),
            )

        if email.pipeline_status == PipelineStatus.RUNNING:
            raise ConflictException(
                message="Pipeline is already running for this email",
                error_detail=ErrorDetail(
                    title="Pipeline Already Running",
                    code="PIPELINE_ALREADY_RUNNING",
                    status=409,
                    details=["Wait for the current run to finish"],
                ),
            )

        if body_hasher.hash_body(body) != email.body_hash:
            raise ConflictException(
                message="Body does not match the original",
                error_detail=ErrorDetail(
                    title="Body Hash Mismatch",
                    code="BODY_HASH_MISMATCH",
                    status=409,
                    details=[
                        "The supplied body does not match the stored hash; "
                        "create a new email instead"
                    ],
                ),
            )

        await self.link_repo.delete_all_for_email(email_id)
        await self.email_repo.session.execute(
            update(Email)
            .where(Email.id == email_id)
            .values(
                pipeline_status=PipelineStatus.PENDING,
                pipeline_stage=PipelineStage.QUEUED,
                pipeline_error=None,
                processed_at=None,
                finalised_at=None,
                final_classification=None,
                final_confidence=None,
                aggregation_note=None,
                override_trigger=None,
                classification=None,
                confidence=None,
                reasoning=None,
                risk_factors=None,
                link_count=0,
                llm_model=None,
            )
        )
        await self.email_repo.session.flush()

        from src.modules.inference.internal import pipeline_runner
        pipeline_runner.spawn(email_id, email.sender, email.subject, body)
        return email

    async def apply_manual_review(
        self,
        email_id: UUID,
        user_id: UUID,
        note: str,
        override_classification: Optional[Classification] = None,
    ) -> Email:
        if self.email_repo is None:
            raise RuntimeError(
                "apply_manual_review requires a session-bound email_repo"
            )

        email = await self.email_repo.get_by_id(email_id)
        if not email:
            raise NotFoundException(
                message="Email not found",
                error_detail=ErrorDetail(
                    title="Email Not Found",
                    code="EMAIL_NOT_FOUND",
                    status=404,
                    details=[f"No email with id {email_id}"],
                ),
            )

        values: dict = {
            "manual_review_flag": True,
            "manual_review_note": note,
            "manual_review_by": user_id,
            "manual_review_at": datetime.now(timezone.utc),
        }
        if override_classification is not None:
            values["manual_override_classification"] = override_classification

        await self.email_repo.session.execute(
            update(Email).where(Email.id == email_id).values(**values)
        )
        await self.email_repo.session.flush()
        # Re-select with populate_existing so the cached instance gets a fresh
        # eager load of all attributes (including the selectin links). Without
        # this, scalar attribute access in the response DTO triggers an async
        # auto-refresh from a sync code path and raises MissingGreenlet.
        result = await self.email_repo.session.execute(
            select(Email).where(Email.id == email_id).execution_options(
                populate_existing=True
            )
        )
        return result.scalar_one()

    async def delete_email(self, email_id: UUID) -> None:
        if self.email_repo is None:
            raise RuntimeError("delete_email requires a session-bound email_repo")
        email = await self.email_repo.get_by_id(email_id)
        if not email:
            raise NotFoundException(
                message="Email not found",
                error_detail=ErrorDetail(
                    title="Email Not Found",
                    code="EMAIL_NOT_FOUND",
                    status=404,
                    details=[f"No email with id {email_id}"],
                ),
            )
        await self.email_repo.delete(email)

    # ── Background pipeline orchestration ────────────────────────────────

    async def run_pipeline(
        self, email_id: UUID, sender: str, subject: str, body: str
    ) -> None:
        # Stage 1 — classify
        await self._set_stage(
            email_id, PipelineStatus.RUNNING, PipelineStage.CLASSIFICATION
        )
        cls = await self.classification_service.classify(sender, subject, body)
        await self._persist_classification(email_id, cls)

        early_exit = (
            cls.classification == Classification.PHISHING
            and cls.confidence > inference.pipeline.early_exit_confidence
        )
        if early_exit:
            outcome = self.aggregation_service.finalise(
                AggregationEmail(
                    classification=cls.classification,
                    confidence=cls.confidence,
                    link_count=len(cls.links),
                ),
                [],
                early_exit=True,
            )
            await self._finalise(email_id, outcome)
            return

        # Stage 2 — resolve links
        await self._set_stage(
            email_id, PipelineStatus.RUNNING, PipelineStage.LINK_RESOLUTION
        )
        resolved_links = await self.resolution_service.resolve_all(cls.links)
        link_id_for_index = await self._persist_links(email_id, resolved_links)

        # Stage 3 — page analysis
        await self._set_stage(
            email_id, PipelineStatus.RUNNING, PipelineStage.PAGE_ANALYSIS
        )
        scraped_pages: list[dict] = []
        batch_index_to_link_id: dict[int, UUID] = {}
        for i, rl in enumerate(resolved_links):
            sp = rl.scraped_page
            if sp is None or sp.scrape_status != ScrapeStatus.SUCCESS:
                continue
            scraped_pages.append({
                "resolved_url": rl.resolved_url,
                "page_title": sp.page_title,
                "meta_description": sp.meta_description,
                "has_login_form": sp.has_login_form,
                "has_payment_form": sp.has_payment_form,
                "external_domains": sp.external_domains,
                "favicon_matches_domain": sp.favicon_matches_domain,
                "content": sp.body_text,
            })
            batch_index_to_link_id[len(scraped_pages)] = link_id_for_index[i]

        page_results = await self.page_analysis_service.analyse_batch(
            scraped_pages
        )
        await self._persist_page_analyses(
            page_results, scraped_pages, batch_index_to_link_id
        )

        # Stage 4 — aggregate
        await self._set_stage(
            email_id, PipelineStatus.RUNNING, PipelineStage.AGGREGATION
        )
        outcome = self.aggregation_service.finalise(
            AggregationEmail(
                classification=cls.classification,
                confidence=cls.confidence,
                link_count=len(cls.links),
            ),
            page_results,
        )
        await self._finalise(email_id, outcome)

    # ── Pipeline-internal DB writes (each opens its own session) ─────────

    async def _set_stage(
        self, email_id: UUID, status: PipelineStatus, stage: PipelineStage
    ) -> None:
        async with async_session() as session:
            async with session.begin():
                await EmailRepository(session).update_status(
                    email_id, status, stage
                )

    async def _persist_classification(self, email_id: UUID, cls) -> None:
        async with async_session() as session:
            async with session.begin():
                await session.execute(
                    update(Email)
                    .where(Email.id == email_id)
                    .values(
                        classification=cls.classification,
                        confidence=cls.confidence,
                        reasoning=cls.reasoning,
                        risk_factors=list(cls.risk_factors)
                        if cls.risk_factors
                        else None,
                        link_count=len(cls.links),
                        llm_model=cls.model_name,
                    )
                )

    async def _persist_links(
        self, email_id: UUID, resolved_links: Sequence
    ) -> dict[int, UUID]:
        index_to_id: dict[int, UUID] = {}
        if not resolved_links:
            return index_to_id

        async with async_session() as session:
            async with session.begin():
                rows: list[Link] = []
                now = datetime.now(timezone.utc)
                for rl in resolved_links:
                    rows.append(
                        Link(
                            email_id=email_id,
                            original_url=rl.original_url,
                            is_shortened=bool(rl.is_shortened),
                            shortener=rl.shortener,
                            anchor_context=rl.anchor_context,
                            resolved_url=rl.resolved_url,
                            resolve_status=rl.resolve_status,
                            redirect_hops=rl.redirect_hops,
                            intermediate_domains=(
                                list(rl.intermediate_domains)
                                if rl.intermediate_domains
                                else None
                            ),
                            http_status=rl.http_status,
                            resolved_at=now,
                        )
                    )
                session.add_all(rows)
                await session.flush()
                for i, row in enumerate(rows):
                    index_to_id[i] = row.id
        return index_to_id

    async def _persist_page_analyses(
        self,
        page_results: Sequence,
        scraped_pages: Sequence[dict],
        batch_index_to_link_id: dict[int, UUID],
    ) -> None:
        if not page_results:
            return
        async with async_session() as session:
            async with session.begin():
                rows: list[PageAnalysis] = []
                now = datetime.now(timezone.utc)
                for pr in page_results:
                    link_id = batch_index_to_link_id.get(pr.page_index)
                    if link_id is None:
                        continue
                    src = scraped_pages[pr.page_index - 1]
                    rows.append(
                        PageAnalysis(
                            link_id=link_id,
                            page_title=src.get("page_title"),
                            meta_description=src.get("meta_description"),
                            has_login_form=bool(src.get("has_login_form")),
                            has_payment_form=bool(src.get("has_payment_form")),
                            external_domains=(
                                list(src["external_domains"])
                                if src.get("external_domains")
                                else None
                            ),
                            favicon_matches_domain=src.get(
                                "favicon_matches_domain"
                            ),
                            page_purpose=pr.page_purpose,
                            impersonates_brand=pr.impersonates_brand,
                            requests_credentials=pr.requests_credentials,
                            requests_payment=pr.requests_payment,
                            risk_level=pr.risk_level,
                            risk_confidence=pr.risk_confidence,
                            risk_reasons=(
                                list(pr.risk_reasons)
                                if pr.risk_reasons
                                else None
                            ),
                            summary=pr.summary,
                            scrape_status=ScrapeStatus.SUCCESS,
                            llm_model=pr.model_name,
                            analysed_at=now,
                        )
                    )
                if rows:
                    session.add_all(rows)
                    await session.flush()

    async def _finalise(self, email_id: UUID, outcome) -> None:
        async with async_session() as session:
            async with session.begin():
                repo = EmailRepository(session)
                await repo.mark_finalised(
                    email_id,
                    outcome.final_classification,
                    outcome.final_confidence,
                    outcome.aggregation_note,
                    outcome.override_trigger,
                )
                await repo.update_status(
                    email_id, PipelineStatus.COMPLETE, PipelineStage.DONE
                )
