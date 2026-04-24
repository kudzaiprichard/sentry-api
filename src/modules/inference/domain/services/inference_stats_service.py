from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional, Sequence

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.inference.domain.models.email import Email
from src.modules.inference.domain.models.enums import (
    Classification,
    OverrideTrigger,
    PipelineStatus,
)
from src.modules.inference.domain.models.link import Link
from src.modules.inference.domain.models.page_analysis import PageAnalysis


BucketSize = Literal["day", "week"]


@dataclass
class ClassificationCounts:
    phishing: int = 0
    suspicious: int = 0
    legitimate: int = 0
    pending: int = 0


@dataclass
class PipelineStatusCounts:
    pending: int = 0
    running: int = 0
    complete: int = 0
    failed: int = 0


@dataclass
class SummaryStats:
    total: int
    by_classification: ClassificationCounts
    by_pipeline_status: PipelineStatusCounts
    early_exit_count: int
    escalation_count: int
    average_confidence: Optional[float]
    window_start: Optional[datetime]
    window_end: Optional[datetime]


@dataclass
class VerdictBucket:
    bucket: datetime
    phishing: int = 0
    suspicious: int = 0
    legitimate: int = 0


@dataclass
class TriggerCount:
    trigger: OverrideTrigger
    count: int


@dataclass
class ModelCount:
    model: str
    count: int


@dataclass
class ApiCallsEstimated:
    groq: int
    gemini: int
    total_saved: int


@dataclass
class ModelUsage:
    stage1: list[ModelCount] = field(default_factory=list)
    stage3: list[ModelCount] = field(default_factory=list)
    api_calls_estimated: ApiCallsEstimated = field(
        default_factory=lambda: ApiCallsEstimated(0, 0, 0)
    )


@dataclass
class BrandCount:
    brand: str
    count: int


def _effective_classification():
    return func.coalesce(Email.final_classification, Email.classification)


def _apply_window(
    stmt: Select,
    start: Optional[datetime],
    end: Optional[datetime],
) -> Select:
    if start is not None:
        stmt = stmt.where(Email.received_at >= start)
    if end is not None:
        stmt = stmt.where(Email.received_at <= end)
    return stmt


class InferenceStatsService:
    """Read-only analytics over submitted emails.

    Uses a session injected via `get_db_readonly` so we don't open a
    transaction for what is purely a set of `SELECT`s. All methods accept
    an optional `(start, end)` window on `Email.received_at`.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def summary(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> SummaryStats:
        total_stmt = _apply_window(
            select(func.count()).select_from(Email), start, end
        )
        total = (await self.session.execute(total_stmt)).scalar_one()

        cls_stmt = _apply_window(
            select(
                _effective_classification().label("cls"),
                func.count().label("n"),
            ).select_from(Email),
            start,
            end,
        ).group_by(_effective_classification())
        by_cls = ClassificationCounts()
        for cls_value, n in (await self.session.execute(cls_stmt)).all():
            if cls_value is None:
                by_cls.pending = n
                continue
            if cls_value == Classification.PHISHING:
                by_cls.phishing = n
            elif cls_value == Classification.SUSPICIOUS:
                by_cls.suspicious = n
            elif cls_value == Classification.LEGITIMATE:
                by_cls.legitimate = n

        status_stmt = _apply_window(
            select(Email.pipeline_status, func.count()).select_from(Email),
            start,
            end,
        ).group_by(Email.pipeline_status)
        by_status = PipelineStatusCounts()
        for status_value, n in (await self.session.execute(status_stmt)).all():
            if status_value == PipelineStatus.PENDING:
                by_status.pending = n
            elif status_value == PipelineStatus.RUNNING:
                by_status.running = n
            elif status_value == PipelineStatus.COMPLETE:
                by_status.complete = n
            elif status_value == PipelineStatus.FAILED:
                by_status.failed = n

        early_exit_stmt = _apply_window(
            select(func.count())
            .select_from(Email)
            .where(Email.override_trigger == OverrideTrigger.EARLY_EXIT),
            start,
            end,
        )
        early_exit_count = (
            await self.session.execute(early_exit_stmt)
        ).scalar_one()

        escalation_stmt = _apply_window(
            select(func.count())
            .select_from(Email)
            .where(
                Email.override_trigger.in_(
                    (
                        OverrideTrigger.PAGE_HIGH_RISK,
                        OverrideTrigger.PAGE_MEDIUM_RISK,
                    )
                )
            ),
            start,
            end,
        )
        escalation_count = (
            await self.session.execute(escalation_stmt)
        ).scalar_one()

        avg_stmt = _apply_window(
            select(func.avg(Email.final_confidence)).select_from(Email),
            start,
            end,
        )
        avg_conf = (await self.session.execute(avg_stmt)).scalar_one()

        return SummaryStats(
            total=int(total),
            by_classification=by_cls,
            by_pipeline_status=by_status,
            early_exit_count=int(early_exit_count),
            escalation_count=int(escalation_count),
            average_confidence=float(avg_conf) if avg_conf is not None else None,
            window_start=start,
            window_end=end,
        )

    async def verdicts_over_time(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        bucket: BucketSize = "day",
    ) -> list[VerdictBucket]:
        if bucket not in ("day", "week"):
            raise ValueError(f"bucket must be 'day' or 'week', got {bucket!r}")

        # Force UTC so buckets are independent of the PG session timezone —
        # `timezone('UTC', tz_col)` returns a naive timestamp in UTC.
        bucket_col = func.date_trunc(
            bucket, func.timezone("UTC", Email.received_at)
        ).label("bucket")
        stmt = (
            _apply_window(
                select(
                    bucket_col,
                    _effective_classification().label("cls"),
                    func.count().label("n"),
                ).select_from(Email),
                start,
                end,
            )
            .where(_effective_classification().is_not(None))
            .group_by(bucket_col, _effective_classification())
            .order_by(bucket_col)
        )

        buckets: dict[datetime, VerdictBucket] = {}
        for b, cls_value, n in (await self.session.execute(stmt)).all():
            row = buckets.setdefault(b, VerdictBucket(bucket=b))
            if cls_value == Classification.PHISHING:
                row.phishing = n
            elif cls_value == Classification.SUSPICIOUS:
                row.suspicious = n
            elif cls_value == Classification.LEGITIMATE:
                row.legitimate = n
        return list(buckets.values())

    async def override_trigger_breakdown(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[TriggerCount]:
        stmt = (
            _apply_window(
                select(Email.override_trigger, func.count()).select_from(Email),
                start,
                end,
            )
            .where(Email.override_trigger.is_not(None))
            .group_by(Email.override_trigger)
            .order_by(func.count().desc())
        )
        return [
            TriggerCount(trigger=trigger, count=int(n))
            for trigger, n in (await self.session.execute(stmt)).all()
        ]

    async def model_usage(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> ModelUsage:
        stage1_stmt = (
            _apply_window(
                select(Email.llm_model, func.count()).select_from(Email),
                start,
                end,
            )
            .where(Email.llm_model.is_not(None))
            .group_by(Email.llm_model)
            .order_by(func.count().desc())
        )
        stage1 = [
            ModelCount(model=model, count=int(n))
            for model, n in (await self.session.execute(stage1_stmt)).all()
        ]

        stage3_stmt = (
            select(
                PageAnalysis.llm_model,
                func.count(func.distinct(Link.email_id)),
            )
            .select_from(PageAnalysis)
            .join(Link, Link.id == PageAnalysis.link_id)
            .join(Email, Email.id == Link.email_id)
            .where(PageAnalysis.llm_model.is_not(None))
        )
        if start is not None:
            stage3_stmt = stage3_stmt.where(Email.received_at >= start)
        if end is not None:
            stage3_stmt = stage3_stmt.where(Email.received_at <= end)
        stage3_stmt = stage3_stmt.group_by(PageAnalysis.llm_model).order_by(
            func.count(func.distinct(Link.email_id)).desc()
        )
        stage3 = [
            ModelCount(model=model, count=int(n))
            for model, n in (await self.session.execute(stage3_stmt)).all()
        ]

        groq_total = sum(m.count for m in stage1)
        gemini_total = sum(m.count for m in stage3)

        saved_stmt = _apply_window(
            select(func.count())
            .select_from(Email)
            .where(Email.override_trigger == OverrideTrigger.EARLY_EXIT),
            start,
            end,
        )
        total_saved = (await self.session.execute(saved_stmt)).scalar_one()

        return ModelUsage(
            stage1=stage1,
            stage3=stage3,
            api_calls_estimated=ApiCallsEstimated(
                groq=int(groq_total),
                gemini=int(gemini_total),
                total_saved=int(total_saved),
            ),
        )

    async def top_impersonated_brands(
        self,
        limit: int = 10,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> list[BrandCount]:
        if limit <= 0:
            return []
        stmt = (
            select(PageAnalysis.impersonates_brand, func.count())
            .select_from(PageAnalysis)
            .join(Link, Link.id == PageAnalysis.link_id)
            .join(Email, Email.id == Link.email_id)
            .where(PageAnalysis.impersonates_brand.is_not(None))
        )
        if start is not None:
            stmt = stmt.where(Email.received_at >= start)
        if end is not None:
            stmt = stmt.where(Email.received_at <= end)
        stmt = (
            stmt.group_by(PageAnalysis.impersonates_brand)
            .order_by(func.count().desc(), PageAnalysis.impersonates_brand.asc())
            .limit(limit)
        )
        return [
            BrandCount(brand=brand, count=int(n))
            for brand, n in (await self.session.execute(stmt)).all()
        ]
