"""Extension install admin management — dashboard-facing, ADMIN role only.

Mounted by ``src/core/factory.py`` at ``/api/v1/extension/installs``.

Routes (EXTENSION_IMPLEMENTATION_STANDARD §13):
- GET    /                                (list + search installs)
- POST   /domains/blacklist               (bulk blacklist by email domain)
- GET    /{install_id}                    (full detail + active token count)
- POST   /{install_id}/blacklist          (block + revoke tokens atomically)
- POST   /{install_id}/unblacklist        (reverse block; no token re-issue)
- POST   /{install_id}/revoke-tokens      (bulk revoke without blacklisting)
- GET    /{install_id}/activity           (paginated analyse history)

``domains/blacklist`` is declared before the ``{install_id}`` routes because
FastAPI's router matches in definition order — without this order the literal
``domains`` path segment would be captured by the ``{install_id}`` UUID
parser and raise a 422.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.modules.auth.domain.models.user import User
from src.modules.auth.presentation.dependencies import require_admin
from src.modules.extension.domain.models.enums import InstallStatus
from src.modules.extension.domain.services.install_management_service import (
    InstallManagementService,
)
from src.modules.extension.presentation.dependencies import (
    get_install_management_service,
)
from src.modules.extension.presentation.dtos.admin import (
    AnalyseEventResponse,
    BlacklistDomainRequest,
    BlacklistDomainResponse,
    BlacklistInstallRequest,
    InstallDetailResponse,
    InstallResponse,
    RevokeTokensResponse,
)
from src.shared.database.pagination import PaginationParams, get_pagination
from src.shared.responses import ApiResponse, PaginatedResponse


router = APIRouter(dependencies=[Depends(require_admin)])


# ── list / search ──

@router.get("")
async def list_installs(
    pagination: PaginationParams = Depends(get_pagination),
    email: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
    status: Optional[InstallStatus] = Query(default=None),
    version: Optional[str] = Query(default=None),
    last_seen_after: Optional[datetime] = Query(
        default=None, alias="lastSeenAfter"
    ),
    last_seen_before: Optional[datetime] = Query(
        default=None, alias="lastSeenBefore"
    ),
    service: InstallManagementService = Depends(
        get_install_management_service
    ),
):
    installs, total = await service.search(
        page=pagination.page,
        page_size=pagination.page_size,
        email_contains=email,
        domain=domain,
        status=status,
        version=version,
        last_seen_after=last_seen_after,
        last_seen_before=last_seen_before,
    )
    return PaginatedResponse.ok(
        value=[InstallResponse.from_install(i) for i in installs],
        page=pagination.page,
        total=total,
        page_size=pagination.page_size,
    )


# ── bulk: domain blacklist ──
# Must precede /{install_id} routes so the literal "domains" is not parsed
# as a UUID path parameter.

@router.post("/domains/blacklist")
async def blacklist_domain(
    body: BlacklistDomainRequest,
    current_admin: User = Depends(require_admin),
    service: InstallManagementService = Depends(
        get_install_management_service
    ),
):
    installs, tokens = await service.blacklist_domain(
        domain=body.domain,
        admin_id=current_admin.id,
        reason=body.reason,
    )
    return ApiResponse.ok(
        value=BlacklistDomainResponse(
            installsUpdated=installs,
            tokensRevoked=tokens,
        ),
        message="Domain blacklisted",
    )


# ── detail ──

@router.get("/{install_id}")
async def get_install(
    install_id: UUID,
    service: InstallManagementService = Depends(
        get_install_management_service
    ),
):
    install, active_count = await service.get_detail(install_id)
    return ApiResponse.ok(
        value=InstallDetailResponse.from_install_with_count(
            install, active_count
        )
    )


# ── activity ──

@router.get("/{install_id}/activity")
async def get_install_activity(
    install_id: UUID,
    pagination: PaginationParams = Depends(get_pagination),
    service: InstallManagementService = Depends(
        get_install_management_service
    ),
):
    events, total = await service.list_activity(
        install_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return PaginatedResponse.ok(
        value=[AnalyseEventResponse.from_event(e) for e in events],
        page=pagination.page,
        total=total,
        page_size=pagination.page_size,
    )


# ── blacklist / unblacklist / revoke ──

@router.post("/{install_id}/blacklist")
async def blacklist_install(
    install_id: UUID,
    body: BlacklistInstallRequest,
    current_admin: User = Depends(require_admin),
    service: InstallManagementService = Depends(
        get_install_management_service
    ),
):
    install = await service.blacklist(
        install_id, admin_id=current_admin.id, reason=body.reason
    )
    return ApiResponse.ok(
        value=InstallResponse.from_install(install),
        message="Install blacklisted",
    )


@router.post("/{install_id}/unblacklist")
async def unblacklist_install(
    install_id: UUID,
    service: InstallManagementService = Depends(
        get_install_management_service
    ),
):
    install = await service.unblacklist(install_id)
    return ApiResponse.ok(
        value=InstallResponse.from_install(install),
        message="Install reinstated",
    )


@router.post("/{install_id}/revoke-tokens")
async def revoke_install_tokens(
    install_id: UUID,
    service: InstallManagementService = Depends(
        get_install_management_service
    ),
):
    revoked = await service.revoke_tokens(install_id)
    return ApiResponse.ok(
        value=RevokeTokensResponse(revoked=revoked),
        message="Tokens revoked",
    )
