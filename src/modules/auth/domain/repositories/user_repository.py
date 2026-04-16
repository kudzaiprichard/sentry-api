from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.database import BaseRepository
from src.modules.auth.domain.models.user import User


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_username(self, username: str) -> User | None:
        stmt = select(User).where(User.username == username)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def email_exists(self, email: str) -> bool:
        return await self.exists(email=email)

    async def username_exists(self, username: str) -> bool:
        return await self.exists(username=username)
