from datetime import datetime
from typing import Optional, Sequence, Tuple
from uuid import UUID

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.extension.domain.models.enums import InstallStatus
from src.modules.extension.domain.models.extension_install import (
    ExtensionInstall,
)
from src.shared.database import BaseRepository


class InstallRepository(BaseRepository[ExtensionInstall]):
    def __init__(self, session: AsyncSession):
        super().__init__(ExtensionInstall, session)

    async def get_by_sub(self, google_sub: str) -> ExtensionInstall | None:
        stmt = select(ExtensionInstall).where(
            ExtensionInstall.google_sub == google_sub
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def touch_last_seen(self, install_id: UUID, ts: datetime) -> None:
        await self.session.execute(
            update(ExtensionInstall)
            .where(ExtensionInstall.id == install_id)
            .values(last_seen_at=ts)
        )

    async def search(
        self,
        *,
        page: int,
        page_size: int,
        email_contains: Optional[str] = None,
        domain: Optional[str] = None,
        status: Optional[InstallStatus] = None,
        version: Optional[str] = None,
        last_seen_after: Optional[datetime] = None,
        last_seen_before: Optional[datetime] = None,
    ) -> Tuple[Sequence[ExtensionInstall], int]:
        stmt: Select = select(ExtensionInstall)
        conditions = []

        if email_contains:
            conditions.append(
                ExtensionInstall.email.ilike(f"%{email_contains}%")
            )
        if domain:
            conditions.append(
                ExtensionInstall.email.ilike(f"%@{domain}")
            )
        if status is not None:
            conditions.append(ExtensionInstall.status == status)
        if version:
            conditions.append(ExtensionInstall.extension_version == version)
        if last_seen_after is not None:
            conditions.append(ExtensionInstall.last_seen_at >= last_seen_after)
        if last_seen_before is not None:
            conditions.append(ExtensionInstall.last_seen_at <= last_seen_before)

        if conditions:
            stmt = stmt.where(*conditions)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = stmt.order_by(ExtensionInstall.created_at.desc())
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)
        result = await self.session.execute(stmt)
        return result.scalars().all(), total

    async def blacklist_domain(
        self,
        *,
        domain: str,
        blacklisted_by: UUID,
        reason: str | None,
        ts: datetime,
    ) -> int:
        """Mark every ACTIVE install whose email ends in @domain as BLACKLISTED.

        Returns the number of install rows updated. Caller is responsible for
        revoking tokens in the same transaction — see InstallManagementService.
        """
        stmt = (
            update(ExtensionInstall)
            .where(
                ExtensionInstall.status == InstallStatus.ACTIVE,
                ExtensionInstall.email.ilike(f"%@{domain}"),
            )
            .values(
                status=InstallStatus.BLACKLISTED,
                blacklisted_at=ts,
                blacklisted_by=blacklisted_by,
                blacklist_reason=reason,
            )
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0

    async def matching_domain_ids(self, domain: str) -> Sequence[UUID]:
        stmt = select(ExtensionInstall.id).where(
            ExtensionInstall.status == InstallStatus.ACTIVE,
            ExtensionInstall.email.ilike(f"%@{domain}"),
        )
        result = await self.session.execute(stmt)
        return [row[0] for row in result.all()]
