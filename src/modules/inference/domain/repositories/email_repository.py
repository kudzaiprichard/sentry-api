from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.shared.database import BaseRepository
from src.modules.inference.domain.models.email import Email
from src.modules.inference.domain.models.link import Link
from src.modules.inference.domain.models.enums import (
    Classification,
    OverrideTrigger,
    PipelineStage,
    PipelineStatus,
)


class EmailRepository(BaseRepository[Email]):
    def __init__(self, session: AsyncSession):
        super().__init__(Email, session)

    async def get_with_full_detail(self, email_id: UUID) -> Email | None:
        stmt = (
            select(Email)
            .where(Email.id == email_id)
            .options(selectinload(Email.links).selectinload(Link.page_analysis))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def list_with_filters(
        self,
        page: int = 1,
        page_size: int = 20,
        classification: Optional[Classification] = None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        pipeline_status: Optional[PipelineStatus] = None,
        override_trigger: Optional[OverrideTrigger] = None,
        sender: Optional[str] = None,
    ) -> Tuple[Sequence[Email], int]:
        stmt = select(Email)

        if classification is not None:
            effective = func.coalesce(
                Email.final_classification, Email.classification
            )
            stmt = stmt.where(effective == classification)

        if min_confidence is not None:
            stmt = stmt.where(Email.final_confidence >= min_confidence)
        if max_confidence is not None:
            stmt = stmt.where(Email.final_confidence <= max_confidence)

        if start_date is not None:
            stmt = stmt.where(Email.received_at >= start_date)
        if end_date is not None:
            stmt = stmt.where(Email.received_at <= end_date)

        if pipeline_status is not None:
            stmt = stmt.where(Email.pipeline_status == pipeline_status)

        if override_trigger is not None:
            stmt = stmt.where(Email.override_trigger == override_trigger)

        if sender:
            stmt = stmt.where(Email.sender.ilike(f"%{sender}%"))

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        offset = (page - 1) * page_size
        page_stmt = (
            stmt.order_by(Email.received_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        records = (await self.session.execute(page_stmt)).scalars().all()
        return records, total

    async def update_status(
        self,
        email_id: UUID,
        status: PipelineStatus,
        stage: PipelineStage,
        error: Optional[str] = None,
    ) -> None:
        values: dict = {
            "pipeline_status": status,
            "pipeline_stage": stage,
        }
        if error is not None:
            values["pipeline_error"] = error
        if status == PipelineStatus.RUNNING:
            values["processed_at"] = datetime.now(timezone.utc)

        stmt = update(Email).where(Email.id == email_id).values(**values)
        await self.session.execute(stmt)
        await self.session.flush()

    async def mark_finalised(
        self,
        email_id: UUID,
        final_classification: Classification,
        final_confidence: float,
        aggregation_note: str,
        override_trigger: OverrideTrigger,
    ) -> None:
        stmt = (
            update(Email)
            .where(Email.id == email_id)
            .values(
                final_classification=final_classification,
                final_confidence=final_confidence,
                aggregation_note=aggregation_note,
                override_trigger=override_trigger,
                finalised_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()
