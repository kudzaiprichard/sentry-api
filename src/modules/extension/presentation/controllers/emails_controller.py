"""Extension email analyse endpoint — POST /api/v1/emails/analyze.

Mounted by ``src/core/factory.py`` at ``/api/v1/emails``.

Auth: ``require_install`` (install bearer token).
Rate limit: ``server.rate_limit.extension_predict`` keyed by install token hash
so a user's bucket is not shared with other installs behind the same NAT.

Detector availability: if ``app.state.detector`` is not set, returns
``503 SERVICE_UNAVAILABLE`` — STANDARD §16 and BACKEND_CONTRACT §5.5.3.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from src.configs import server
from src.modules.extension.domain.models.extension_install import (
    ExtensionInstall,
)
from src.modules.extension.domain.repositories.extension_analyse_event_repository import (
    ExtensionAnalyseEventRepository,
)
from src.modules.extension.domain.services.email_analyse_service import (
    EmailAnalyseService,
)
from src.modules.extension.internal.detector import get_detector
from src.modules.extension.internal.rate_limit import (
    install_token_key,
    limiter,
)
from src.modules.extension.presentation.dependencies import require_install
from src.modules.extension.presentation.dtos.email_analyse import (
    AnalyseEmailRequest,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.database import get_db
from src.shared.responses import ApiResponse


router = APIRouter()


@router.post("/analyze")
@limiter.limit(server.rate_limit.extension_predict, key_func=install_token_key)
async def analyze_email(
    request: Request,
    body: AnalyseEmailRequest,
    install: ExtensionInstall = Depends(require_install),
    session: AsyncSession = Depends(get_db),
):
    detector = get_detector(request)
    event_repo = ExtensionAnalyseEventRepository(session)
    # Pipeline submitter is wired onto app.state in lifespan (same pattern
    # as the detector) to avoid a src/core <-> src/modules/extension
    # import cycle at module load time.
    submitter = getattr(request.app.state, "pipeline_submitter", None)
    service = EmailAnalyseService(detector, event_repo, submitter)

    request_id = getattr(request.state, "request_id", None)

    result = await service.analyse(
        req=body,
        install_id=install.id,
        request_id=request_id,
    )
    return ApiResponse.ok(value=result)
