from typing import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.database import BaseRepository
from src.modules.inference.domain.models.page_analysis import PageAnalysis


class PageAnalysisRepository(BaseRepository[PageAnalysis]):
    def __init__(self, session: AsyncSession):
        super().__init__(PageAnalysis, session)

    async def create_from_batch(
        self, results: Sequence[PageAnalysis]
    ) -> Sequence[PageAnalysis]:
        return await self.create_many(results)
