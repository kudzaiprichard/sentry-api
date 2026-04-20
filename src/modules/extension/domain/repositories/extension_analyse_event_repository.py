from typing import Sequence, Tuple
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.extension.domain.models.extension_analyse_event import (
    ExtensionAnalyseEvent,
)
from src.shared.database import BaseRepository


class ExtensionAnalyseEventRepository(BaseRepository[ExtensionAnalyseEvent]):
    def __init__(self, session: AsyncSession):
        super().__init__(ExtensionAnalyseEvent, session)

    async def list_for_install(
        self, install_id: UUID, *, page: int, page_size: int
    ) -> Tuple[Sequence[ExtensionAnalyseEvent], int]:
        base = select(ExtensionAnalyseEvent).where(
            ExtensionAnalyseEvent.install_id == install_id
        )
        total = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()

        stmt = (
            base.order_by(ExtensionAnalyseEvent.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all(), total
