from typing import Sequence
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.shared.database import BaseRepository
from src.modules.inference.domain.models.link import Link


class LinkRepository(BaseRepository[Link]):
    def __init__(self, session: AsyncSession):
        super().__init__(Link, session)

    async def create_many_for_email(
        self, email_id: UUID, links: Sequence[Link]
    ) -> Sequence[Link]:
        for link in links:
            link.email_id = email_id
        self.session.add_all(links)
        await self.session.flush()
        for link in links:
            await self.session.refresh(link)
        return links

    async def get_with_page(self, link_id: UUID) -> Link | None:
        stmt = (
            select(Link)
            .where(Link.id == link_id)
            .options(selectinload(Link.page_analysis))
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def delete_all_for_email(self, email_id: UUID) -> int:
        stmt = delete(Link).where(Link.email_id == email_id)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0
