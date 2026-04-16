from uuid import UUID
from datetime import datetime, timezone

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.database import BaseRepository
from src.modules.auth.domain.models.token import Token
from src.modules.auth.domain.models.enums import TokenType


class TokenRepository(BaseRepository[Token]):
    def __init__(self, session: AsyncSession):
        super().__init__(Token, session)

    async def get_by_token(self, token: str) -> Token | None:
        stmt = select(Token).where(Token.token == token)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def is_token_valid(self, token: str) -> bool:
        record = await self.get_by_token(token)
        return record is not None and record.is_valid

    async def revoke_token(self, token: str) -> None:
        stmt = (
            update(Token)
            .where(Token.token == token)
            .values(is_revoked=True)
        )
        await self.session.execute(stmt)

    async def revoke_all_user_tokens(self, user_id: UUID) -> None:
        stmt = (
            update(Token)
            .where(Token.user_id == user_id, Token.is_revoked == False)
            .values(is_revoked=True)
        )
        await self.session.execute(stmt)

    async def revoke_user_tokens_by_type(self, user_id: UUID, token_type: TokenType) -> None:
        stmt = (
            update(Token)
            .where(
                Token.user_id == user_id,
                Token.token_type == token_type,
                Token.is_revoked == False,
            )
            .values(is_revoked=True)
        )
        await self.session.execute(stmt)

    async def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        count_stmt = select(Token).where(Token.expires_at < now)
        result = await self.session.execute(count_stmt)
        expired = result.scalars().all()
        total = len(expired)
        if total:
            del_stmt = delete(Token).where(Token.expires_at < now)
            await self.session.execute(del_stmt)
            await self.session.flush()
        return total
