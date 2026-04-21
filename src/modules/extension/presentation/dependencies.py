"""Dependencies for the extension surface.

Exports ``require_install`` (§8.3 of EXTENSION_IMPLEMENTATION_STANDARD.md) —
the install-token bearer dependency that is fully separate from auth's
``get_current_user``. It never touches ``users`` / ``tokens``; it resolves the
install and the token row from ``extension_installs`` / ``extension_tokens``.

Also exposes service factories used by the extension controllers.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

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
from src.modules.extension.domain.services.extension_auth_service import (
    ExtensionAuthService,
)
from src.modules.extension.domain.services.install_management_service import (
    InstallManagementService,
)
from src.modules.extension.internal.install_token_provider import hash_token
from src.shared.database import async_session, get_db
from src.shared.exceptions import (
    AuthenticationException,
    AuthorizationException,
)
from src.shared.responses import ErrorDetail


logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


# ── Repository factories ──

def get_install_repository(
    session: AsyncSession = Depends(get_db),
) -> InstallRepository:
    return InstallRepository(session)


def get_extension_token_repository(
    session: AsyncSession = Depends(get_db),
) -> ExtensionTokenRepository:
    return ExtensionTokenRepository(session)


# ── Service factories ──

def get_extension_auth_service(
    session: AsyncSession = Depends(get_db),
) -> ExtensionAuthService:
    return ExtensionAuthService(
        InstallRepository(session),
        ExtensionTokenRepository(session),
    )


def get_install_management_service(
    session: AsyncSession = Depends(get_db),
) -> InstallManagementService:
    return InstallManagementService(
        InstallRepository(session),
        ExtensionTokenRepository(session),
        ExtensionAnalyseEventRepository(session),
    )


# ── Error helpers ──

def _auth_failed(detail: str) -> AuthenticationException:
    return AuthenticationException(
        message="Install authentication failed",
        error_detail=ErrorDetail(
            title="Authentication Failed",
            code="AUTH_FAILED",
            status=401,
            details=[detail],
        ),
    )


def _not_whitelisted() -> AuthorizationException:
    return AuthorizationException(
        message="Your account is not authorised for AURA",
        error_detail=ErrorDetail(
            title="Your account is not authorised for AURA",
            code="NOT_WHITELISTED",
            status=403,
            details=["Install has been blacklisted"],
        ),
    )


# ── last_seen fire-and-forget bump ──

async def _bump_last_seen(install_id) -> None:
    """Write last_seen_at in its own session — must not block the request."""
    try:
        async with async_session() as session:
            async with session.begin():
                repo = InstallRepository(session)
                await repo.touch_last_seen(install_id, datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to bump last_seen for install %s: %s",
            install_id,
            type(exc).__name__,
        )


# ── require_install_for_logout ──

async def require_install_for_logout(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    install_repo: InstallRepository = Depends(get_install_repository),
    token_repo: ExtensionTokenRepository = Depends(
        get_extension_token_repository
    ),
) -> ExtensionInstall:
    """Logout-only variant of ``require_install`` (BACKEND_CONTRACT §5.4).

    Logout is idempotent: a second call with an already-revoked or expired
    token must still return 200. Only an unknown hash or missing header
    surfaces as 401. Blacklisted installs still sign out cleanly.
    """
    if credentials is None or not credentials.credentials:
        raise _auth_failed("Missing install token")

    token_hash = hash_token(credentials.credentials)
    token_row = await token_repo.get_by_hash(token_hash)

    if token_row is None:
        raise _auth_failed("Install token not recognised")

    install = await install_repo.get_by_id(token_row.install_id)
    if install is None:
        raise _auth_failed("Install record is missing")

    request.state.install_token_hash = token_hash
    request.state.install_id = install.id

    return install


# ── require_install ──

async def require_install(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    install_repo: InstallRepository = Depends(get_install_repository),
    token_repo: ExtensionTokenRepository = Depends(
        get_extension_token_repository
    ),
) -> ExtensionInstall:
    """Resolve the extension install from the bearer install token.

    Steps (EXTENSION_IMPLEMENTATION_STANDARD §8.3):
      1. Read ``Authorization: Bearer <token>``
      2. SHA-256 hash the token
      3. Look up in ``extension_tokens`` — 401 AUTH_FAILED if
         not found / revoked / expired
      4. Join to ``extension_installs`` — 403 NOT_WHITELISTED if blacklisted
      5. Fire-and-forget bump of ``last_seen_at``
      6. Return the install record
    """
    if credentials is None or not credentials.credentials:
        raise _auth_failed("Missing install token")

    token_hash = hash_token(credentials.credentials)
    token_row = await token_repo.get_by_hash(token_hash)

    if token_row is None:
        raise _auth_failed("Install token not recognised")
    if not token_row.is_valid:
        raise _auth_failed("Install token revoked or expired")

    install = await install_repo.get_by_id(token_row.install_id)
    if install is None:
        raise _auth_failed("Install record is missing")
    if install.status == InstallStatus.BLACKLISTED:
        raise _not_whitelisted()

    # Expose token_hash to the controller — /auth/extension/renew needs it to
    # rotate the current token, and rate_limit.install_token_key derives its
    # bucket from the same value. Stored under request.state so callers do
    # not have to re-hash.
    request.state.install_token_hash = token_hash
    request.state.install_id = install.id

    asyncio.create_task(_bump_last_seen(install.id))

    return install
