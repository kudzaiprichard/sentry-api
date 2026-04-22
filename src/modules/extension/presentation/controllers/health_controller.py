"""Extension health endpoint — GET /api/v1/health.

Mounted by ``src/core/factory.py`` at ``/api/v1``.

Auth model (BACKEND_CONTRACT §5.1): optional install token — valid token
returns 200; invalid token returns 401; absent returns 200.

Wire shape (BACKEND_CONTRACT §5.1 and STANDARD §11): ``model_version`` is
**snake_case** on purpose — read directly by ``utils/api.js::checkConnection``.
Returns the literal string ``"unknown"`` when no detector is loaded — never
null, never omitted.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict

from src.configs import application
from src.modules.extension.domain.models.enums import InstallStatus
from src.modules.extension.domain.repositories.extension_token_repository import (
    ExtensionTokenRepository,
)
from src.modules.extension.domain.repositories.install_repository import (
    InstallRepository,
)
from src.modules.extension.internal.install_token_provider import hash_token
from src.modules.extension.presentation.dependencies import bearer_scheme
from src.shared.database import async_session
from src.shared.exceptions import (
    AuthenticationException,
    AuthorizationException,
)
from src.shared.responses import ApiResponse, ErrorDetail


router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    name: str
    version: str
    model_version: str  # snake_case by contract (§3, §11)

    model_config = ConfigDict(populate_by_name=True)


def _resolve_model_version(request: Request) -> str:
    """Return the detector's current model version or literal 'unknown'.

    The detector is expected to expose ``model_version`` either as an
    attribute or via ``resolve_model_version()``. Both are optional; when
    the detector is not loaded, BACKEND_CONTRACT §5.1 requires 'unknown'.
    """
    detector = getattr(request.app.state, "detector", None)
    if detector is None:
        return "unknown"
    try:
        resolver = getattr(detector, "resolve_model_version", None)
        if callable(resolver):
            version = resolver()
        else:
            version = getattr(detector, "model_version", None)
    except Exception:  # noqa: BLE001
        version = None
    if not version or not isinstance(version, str):
        return "unknown"
    return version


async def _validate_optional_install_token(token: str) -> None:
    """Validate the install token. Anonymous callers never reach this.

    401 AUTH_FAILED on revoked / expired / unknown.
    403 NOT_WHITELISTED on blacklisted install.
    """
    token_hash = hash_token(token)
    async with async_session() as session:
        async with session.begin():
            token_repo = ExtensionTokenRepository(session)
            install_repo = InstallRepository(session)

            token_row = await token_repo.get_by_hash(token_hash)
            if token_row is None or not token_row.is_valid:
                raise AuthenticationException(
                    message="Install authentication failed",
                    error_detail=ErrorDetail(
                        title="Authentication Failed",
                        code="AUTH_FAILED",
                        status=401,
                        details=["Install token revoked, expired or unknown"],
                    ),
                )

            install = await install_repo.get_by_id(token_row.install_id)
            if install is None:
                raise AuthenticationException(
                    message="Install authentication failed",
                    error_detail=ErrorDetail(
                        title="Authentication Failed",
                        code="AUTH_FAILED",
                        status=401,
                        details=["Install record is missing"],
                    ),
                )
            if install.status == InstallStatus.BLACKLISTED:
                raise AuthorizationException(
                    message="Your account is not authorised for AURA",
                    error_detail=ErrorDetail(
                        title="Your account is not authorised for AURA",
                        code="NOT_WHITELISTED",
                        status=403,
                        details=["Install has been blacklisted"],
                    ),
                )


@router.get("/health")
async def health(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
):
    # Only touch the DB when a bearer was actually provided. Anonymous
    # probes stay DB-free.
    if credentials is not None and credentials.credentials:
        await _validate_optional_install_token(credentials.credentials)

    return ApiResponse.ok(
        value=HealthResponse(
            status="ok",
            name=application.name,
            version=application.version,
            model_version=_resolve_model_version(request),
        ),
    )
