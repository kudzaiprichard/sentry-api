from datetime import datetime, timezone
from typing import Sequence
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.extension.domain.models.extension_token import ExtensionToken
from src.shared.database import BaseRepository


class ExtensionTokenRepository(BaseRepository[ExtensionToken]):
    def __init__(self, session: AsyncSession):
        super().__init__(ExtensionToken, session)

    async def get_by_hash(self, token_hash: str) -> ExtensionToken | None:
        stmt = select(ExtensionToken).where(
            ExtensionToken.token_hash == token_hash
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def count_active_for_install(self, install_id: UUID) -> int:
        now = datetime.now(timezone.utc)
        stmt = (
            select(ExtensionToken)
            .where(
                ExtensionToken.install_id == install_id,
                ExtensionToken.is_revoked == False,  # noqa: E712
                ExtensionToken.expires_at > now,
            )
        )
        result = await self.session.execute(stmt)
        return len(result.scalars().all())

    async def revoke_all_for_install(
        self, install_id: UUID, *, reason: str
    ) -> int:
        stmt = (
            update(ExtensionToken)
            .where(
                ExtensionToken.install_id == install_id,
                ExtensionToken.is_revoked == False,  # noqa: E712
            )
            .values(is_revoked=True, revoked_reason=reason)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0

    async def revoke_all_for_installs(
        self, install_ids: Sequence[UUID], *, reason: str
    ) -> int:
        if not install_ids:
            return 0
        stmt = (
            update(ExtensionToken)
            .where(
                ExtensionToken.install_id.in_(list(install_ids)),
                ExtensionToken.is_revoked == False,  # noqa: E712
            )
            .values(is_revoked=True, revoked_reason=reason)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0

    async def revoke_by_hash(self, token_hash: str, *, reason: str) -> None:
        stmt = (
            update(ExtensionToken)
            .where(ExtensionToken.token_hash == token_hash)
            .values(is_revoked=True, revoked_reason=reason)
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc)
        probe_stmt = select(ExtensionToken).where(ExtensionToken.expires_at < now)
        result = await self.session.execute(probe_stmt)
        total = len(result.scalars().all())
        if total:
            await self.session.execute(
                delete(ExtensionToken).where(ExtensionToken.expires_at < now)
            )
            await self.session.flush()
        return total
