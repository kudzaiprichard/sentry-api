from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from src.modules.auth.domain.models.user import User
from src.modules.inference.domain.models.enums import (
    Classification,
    OverrideTrigger,
    PipelineStatus,
)
from src.modules.inference.domain.services import (
    InferenceService,
    PredictionHistoryService,
    SubmitItem,
)
from src.modules.inference.presentation.dependencies import (
    get_current_user,
    get_inference_service,
    get_prediction_history_service,
    require_admin,
    require_authenticated,
)
from src.modules.inference.presentation.dtos.requests import (
    ManualReviewRequest,
    ReanalyzeRequest,
    SubmitEmailBatchRequest,
    SubmitEmailRequest,
)
from src.modules.inference.presentation.dtos.responses import (
    BatchRejectedItem,
    EmailDetailResponse,
    EmailLinksResponse,
    EmailStatusResponse,
    EmailSummaryResponse,
    LinkWithPageResponse,
    SubmitEmailBatchResponse,
    SubmitEmailResponse,
)
from src.shared.database.pagination import PaginationParams, get_pagination
from src.shared.responses import ApiResponse, PaginatedResponse


router = APIRouter(dependencies=[Depends(require_authenticated)])


# ── Submissions ──────────────────────────────────────────────────────────


@router.post("/emails", status_code=202)
async def submit_email(
    body: SubmitEmailRequest,
    current_user: User = Depends(get_current_user),
    service: InferenceService = Depends(get_inference_service),
):
    email = await service.submit(
        sender=body.sender,
        subject=body.subject,
        body=body.body,
        received_at=body.received_at,
        user_id=current_user.id,
    )
    return ApiResponse.ok(
        value=SubmitEmailResponse.from_email(email),
        message="Email submitted for analysis",
    )


@router.post("/emails/batch", status_code=202)
async def submit_email_batch(
    body: SubmitEmailBatchRequest,
    current_user: User = Depends(get_current_user),
    service: InferenceService = Depends(get_inference_service),
):
    items = [
        SubmitItem(
            sender=e.sender,
            subject=e.subject,
            body=e.body,
            received_at=e.received_at,
        )
        for e in body.emails
    ]
    submitted, rejected = await service.submit_batch(items, user_id=current_user.id)
    return ApiResponse.ok(
        value=SubmitEmailBatchResponse.build(
            submitted=list(submitted),
            rejected=[
                BatchRejectedItem(index=r.index, reason=r.reason) for r in rejected
            ],
        ),
        message=f"{len(submitted)} emails submitted for analysis",
    )


# ── History / detail ─────────────────────────────────────────────────────


@router.get("/emails")
async def list_emails(
    pagination: PaginationParams = Depends(get_pagination),
    classification: Optional[Classification] = Query(default=None),
    min_confidence: Optional[float] = Query(
        default=None, ge=0.0, le=1.0, alias="minConfidence"
    ),
    max_confidence: Optional[float] = Query(
        default=None, ge=0.0, le=1.0, alias="maxConfidence"
    ),
    start_date: Optional[datetime] = Query(default=None, alias="startDate"),
    end_date: Optional[datetime] = Query(default=None, alias="endDate"),
    pipeline_status: Optional[PipelineStatus] = Query(
        default=None, alias="pipelineStatus"
    ),
    override_trigger: Optional[OverrideTrigger] = Query(
        default=None, alias="overrideTrigger"
    ),
    sender: Optional[str] = Query(default=None),
    service: PredictionHistoryService = Depends(get_prediction_history_service),
):
    rows, total = await service.list(
        page=pagination.page,
        page_size=pagination.page_size,
        classification=classification,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
        start_date=start_date,
        end_date=end_date,
        pipeline_status=pipeline_status,
        override_trigger=override_trigger,
        sender=sender,
    )
    return PaginatedResponse.ok(
        value=[EmailSummaryResponse.from_email(e) for e in rows],
        page=pagination.page,
        total=total,
        page_size=pagination.page_size,
    )


@router.get("/emails/{email_id}")
async def get_email_detail(
    email_id: UUID,
    service: PredictionHistoryService = Depends(get_prediction_history_service),
):
    email = await service.get_detail(email_id)
    return ApiResponse.ok(value=EmailDetailResponse.from_email(email))


@router.get("/emails/{email_id}/status")
async def get_email_status(
    email_id: UUID,
    service: PredictionHistoryService = Depends(get_prediction_history_service),
):
    email = await service.get_detail(email_id)
    return ApiResponse.ok(value=EmailStatusResponse.from_email(email))


@router.get("/emails/{email_id}/links")
async def get_email_links(
    email_id: UUID,
    service: PredictionHistoryService = Depends(get_prediction_history_service),
):
    email = await service.get_detail(email_id)
    return ApiResponse.ok(value=EmailLinksResponse.from_email(email))


@router.get("/links/{link_id}")
async def get_link(
    link_id: UUID,
    service: PredictionHistoryService = Depends(get_prediction_history_service),
):
    link = await service.get_link(link_id)
    return ApiResponse.ok(value=LinkWithPageResponse.from_link(link))


# ── Mutations ────────────────────────────────────────────────────────────


@router.post(
    "/emails/{email_id}/reanalyze",
    status_code=202,
    dependencies=[Depends(require_admin)],
)
async def reanalyze_email(
    email_id: UUID,
    body: ReanalyzeRequest,
    service: InferenceService = Depends(get_inference_service),
):
    email = await service.reanalyze(email_id, body.body)
    return ApiResponse.ok(
        value=SubmitEmailResponse.from_email(email),
        message="Email re-queued for analysis",
    )


@router.post("/emails/{email_id}/manual-review")
async def apply_manual_review(
    email_id: UUID,
    body: ManualReviewRequest,
    current_user: User = Depends(get_current_user),
    service: InferenceService = Depends(get_inference_service),
):
    email = await service.apply_manual_review(
        email_id=email_id,
        user_id=current_user.id,
        note=body.note,
        override_classification=body.override_classification,
    )
    return ApiResponse.ok(
        value=EmailDetailResponse.from_email(email),
        message="Manual review recorded",
    )


@router.delete("/emails/{email_id}", dependencies=[Depends(require_admin)])
async def delete_email(
    email_id: UUID,
    service: InferenceService = Depends(get_inference_service),
):
    await service.delete_email(email_id)
    return ApiResponse.ok(value=None, message="Email deleted")
