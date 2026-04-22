"""Extension auth endpoints — register / renew / logout.

Mounted by ``src/core/factory.py`` at ``/api/v1/auth/extension``. Uses slowapi
via the ``@limiter.limit`` decorator — no SlowAPIMiddleware, because that
subclasses ``BaseHTTPMiddleware`` which buffers response bodies and breaks
streaming. ``RateLimitExceeded`` is caught in ``error_handlers.py`` and
returned with ``code="RATE_LIMITED"``.

EXTENSION_IMPLEMENTATION_STANDARD §15 (logging): never log the Google
access token or the raw install bearer token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request

from src.configs import server
from src.modules.extension.domain.models.extension_install import (
    ExtensionInstall,
)
from src.modules.extension.domain.services.extension_auth_service import (
    ExtensionAuthService,
)
from src.modules.extension.internal.install_token_provider import epoch_millis
from src.modules.extension.internal.rate_limit import limiter
from src.modules.extension.presentation.dependencies import (
    get_extension_auth_service,
    require_install,
    require_install_for_logout,
)
from src.modules.extension.presentation.dtos.requests import (
    ExtensionRegisterRequest,
)
from src.modules.extension.presentation.dtos.responses import (
    ExtensionRegisterResponse,
    ExtensionTokenResponse,
    InstallUserRef,
)
from src.shared.exceptions import ValidationException
from src.shared.responses import ApiResponse, ErrorDetail


router = APIRouter()


# ── /register ──

@router.post("/register")
@limiter.limit(server.rate_limit.extension_register)
async def register_install(
    request: Request,
    body: ExtensionRegisterRequest,
    x_google_access_token: str | None = Header(default=None),
    service: ExtensionAuthService = Depends(get_extension_auth_service),
):
    if not x_google_access_token or not x_google_access_token.strip():
        error = ErrorDetail.builder(
            "Validation Error", "VALIDATION_ERROR", 400
        ).add_field_error(
            "X-Google-Access-Token", "Header is required"
        ).build()
        raise ValidationException(
            message="Missing Google access token", error_detail=error
        )

    install, issued = await service.register(
        google_access_token=x_google_access_token,
        body_email=body.email,
        body_sub=body.sub,
        extension_version=body.environment.extension_version,
        environment_json=body.environment.model_dump(
            by_alias=True, exclude_none=True
        ),
    )

    return ApiResponse.ok(
        value=ExtensionRegisterResponse(
            token=issued.token,
            expiresAt=epoch_millis(issued.expires_at),
            user=InstallUserRef(email=install.email, sub=install.google_sub),
        ),
        message="Registration successful",
    )


# ── /renew ──

@router.post("/renew")
@limiter.limit(server.rate_limit.extension_renew)
async def renew_install_token(
    request: Request,
    install: ExtensionInstall = Depends(require_install),
    service: ExtensionAuthService = Depends(get_extension_auth_service),
):
    current_hash: str = request.state.install_token_hash
    issued = await service.renew(
        install=install, current_token_hash=current_hash
    )
    return ApiResponse.ok(
        value=ExtensionTokenResponse(
            token=issued.token,
            expiresAt=epoch_millis(issued.expires_at),
        ),
        message="Tokens refreshed",
    )


# ── /logout ──

@router.post("/logout")
async def logout_install(
    request: Request,
    install: ExtensionInstall = Depends(require_install_for_logout),
    service: ExtensionAuthService = Depends(get_extension_auth_service),
):
    current_hash: str = request.state.install_token_hash
    await service.logout(install=install, current_token_hash=current_hash)
    return ApiResponse.ok(value=None, message="Logged out successfully")
