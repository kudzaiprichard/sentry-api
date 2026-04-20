"""Dashboard-admin install management — list / blacklist / revoke.

Every blacklist operation revokes the install's tokens in the **same
transaction** (the controller's ``get_db`` session). After a blacklist, any
future request bearing an old token fails ``require_install`` with
``403 NOT_WHITELISTED`` — the token row may still exist briefly, but the
status check cuts access.

Unblacklist does **not** reissue tokens. The user must re-register — §13.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, Sequence, Tuple
from uuid import UUID

from src.modules.extension.domain.models.enums import InstallStatus
from src.modules.extension.domain.models.extension_install import (
    ExtensionInstall,
)
from src.modules.extension.domain.repositories.extension_analyse_event_repository import (
    ExtensionAnalyseEventRepository,
)
from src.modules.extension.domain.repositories.extension_token_repository import (
    ExtensionTokenRepository,
)
from src.modules.extension.domain.repositories.install_repository import (
    InstallRepository,
)
from src.shared.exceptions import NotFoundException
from src.shared.responses import ErrorDetail


logger = logging.getLogger(__name__)


def _not_found(detail: str) -> NotFoundException:
    return NotFoundException(
        message="Install not found",
        error_detail=ErrorDetail(
            title="Install Not Found",
            code="NOT_FOUND",
            status=404,
            details=[detail],
        ),
    )


class InstallManagementService:
    def __init__(
        self,
        install_repo: InstallRepository,
        token_repo: ExtensionTokenRepository,
        event_repo: ExtensionAnalyseEventRepository,
    ):
        self.install_repo = install_repo
        self.token_repo = token_repo
        self.event_repo = event_repo

    # ── queries ──

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
        return await self.install_repo.search(
            page=page,
            page_size=page_size,
            email_contains=email_contains,
            domain=domain,
            status=status,
            version=version,
            last_seen_after=last_seen_after,
            last_seen_before=last_seen_before,
        )

    async def get_detail(
        self, install_id: UUID
    ) -> Tuple[ExtensionInstall, int]:
        install = await self.install_repo.get_by_id(install_id)
        if install is None:
            raise _not_found(f"No install with id {install_id}")
        active = await self.token_repo.count_active_for_install(install.id)
        return install, active

    async def list_activity(
        self, install_id: UUID, *, page: int, page_size: int
    ):
        install = await self.install_repo.get_by_id(install_id)
        if install is None:
            raise _not_found(f"No install with id {install_id}")
        return await self.event_repo.list_for_install(
            install.id, page=page, page_size=page_size
        )

    # ── mutations ──

    async def blacklist(
        self,
        install_id: UUID,
        *,
        admin_id: UUID,
        reason: str | None,
    ) -> ExtensionInstall:
        install = await self.install_repo.get_by_id(install_id)
        if install is None:
            raise _not_found(f"No install with id {install_id}")

        now = datetime.now(timezone.utc)
        await self.install_repo.update(
            install,
            {
                "status": InstallStatus.BLACKLISTED,
                "blacklisted_at": now,
                "blacklisted_by": admin_id,
                "blacklist_reason": reason,
            },
        )
        # Atomic: same transaction as the status flip (controller's session).
        await self.token_repo.revoke_all_for_install(
            install.id, reason="blacklisted"
        )
        logger.info(
            "Install blacklisted: install_id=%s admin_id=%s", install.id, admin_id
        )
        return install

    async def unblacklist(self, install_id: UUID) -> ExtensionInstall:
        install = await self.install_repo.get_by_id(install_id)
        if install is None:
            raise _not_found(f"No install with id {install_id}")

        await self.install_repo.update(
            install,
            {
                "status": InstallStatus.ACTIVE,
                "blacklisted_at": None,
                "blacklisted_by": None,
                "blacklist_reason": None,
            },
        )
        logger.info("Install unblacklisted: install_id=%s", install.id)
        return install

    async def revoke_tokens(
        self, install_id: UUID, *, reason: str = "admin_revoke"
    ) -> int:
        install = await self.install_repo.get_by_id(install_id)
        if install is None:
            raise _not_found(f"No install with id {install_id}")
        revoked = await self.token_repo.revoke_all_for_install(
            install.id, reason=reason
        )
        logger.info(
            "Revoked %d tokens for install_id=%s", revoked, install.id
        )
        return revoked

    async def blacklist_domain(
        self,
        *,
        domain: str,
        admin_id: UUID,
        reason: str | None,
    ) -> Tuple[int, int]:
        """Atomically blacklist every ACTIVE install whose email ends in
        ``@domain`` and revoke their tokens.

        Returns ``(installs_updated, tokens_revoked)``.
        """
        ids = await self.install_repo.matching_domain_ids(domain)
        if not ids:
            return 0, 0

        now = datetime.now(timezone.utc)
        installs = await self.install_repo.blacklist_domain(
            domain=domain,
            blacklisted_by=admin_id,
            reason=reason,
            ts=now,
        )
        tokens = await self.token_repo.revoke_all_for_installs(
            ids, reason="domain_blacklisted"
        )
        logger.info(
            "Domain blacklist: domain=%s installs=%d tokens=%d admin_id=%s",
            domain,
            installs,
            tokens,
            admin_id,
        )
        return installs, tokens
