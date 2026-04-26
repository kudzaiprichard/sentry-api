from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query

from src.modules.inference.domain.services import InferenceStatsService
from src.modules.inference.presentation.dependencies import (
    get_inference_stats_service,
    require_authenticated,
)
from src.modules.inference.presentation.dtos.responses import (
    BrandCountResponse,
    ModelUsageResponse,
    SummaryStatsResponse,
    TriggerCountResponse,
    VerdictBucketResponse,
)
from src.shared.responses import ApiResponse


router = APIRouter(dependencies=[Depends(require_authenticated)])


def _default_window(
    start: Optional[datetime], end: Optional[datetime]
) -> tuple[datetime, datetime]:
    """Fill in the default 30-day window if either edge is missing."""
    now = datetime.now(timezone.utc)
    end = end or now
    start = start or (end - timedelta(days=30))
    return start, end


@router.get("/summary")
async def get_summary(
    start_date: Optional[datetime] = Query(default=None, alias="startDate"),
    end_date: Optional[datetime] = Query(default=None, alias="endDate"),
    service: InferenceStatsService = Depends(get_inference_stats_service),
):
    start, end = _default_window(start_date, end_date)
    summary = await service.summary(start=start, end=end)
    return ApiResponse.ok(value=SummaryStatsResponse.from_summary(summary))


@router.get("/verdicts-over-time")
async def get_verdicts_over_time(
    start_date: Optional[datetime] = Query(default=None, alias="startDate"),
    end_date: Optional[datetime] = Query(default=None, alias="endDate"),
    bucket: Literal["day", "week"] = Query(default="day"),
    service: InferenceStatsService = Depends(get_inference_stats_service),
):
    start, end = _default_window(start_date, end_date)
    rows = await service.verdicts_over_time(start=start, end=end, bucket=bucket)
    return ApiResponse.ok(
        value=[VerdictBucketResponse.from_bucket(r) for r in rows]
    )


@router.get("/override-triggers")
async def get_override_triggers(
    start_date: Optional[datetime] = Query(default=None, alias="startDate"),
    end_date: Optional[datetime] = Query(default=None, alias="endDate"),
    service: InferenceStatsService = Depends(get_inference_stats_service),
):
    start, end = _default_window(start_date, end_date)
    rows = await service.override_trigger_breakdown(start=start, end=end)
    return ApiResponse.ok(
        value=[TriggerCountResponse.from_trigger(r) for r in rows]
    )


@router.get("/model-usage")
async def get_model_usage(
    start_date: Optional[datetime] = Query(default=None, alias="startDate"),
    end_date: Optional[datetime] = Query(default=None, alias="endDate"),
    service: InferenceStatsService = Depends(get_inference_stats_service),
):
    start, end = _default_window(start_date, end_date)
    usage = await service.model_usage(start=start, end=end)
    return ApiResponse.ok(value=ModelUsageResponse.from_usage(usage))


@router.get("/impersonated-brands")
async def get_impersonated_brands(
    limit: int = Query(default=10, ge=1, le=50),
    start_date: Optional[datetime] = Query(default=None, alias="startDate"),
    end_date: Optional[datetime] = Query(default=None, alias="endDate"),
    service: InferenceStatsService = Depends(get_inference_stats_service),
):
    start, end = _default_window(start_date, end_date)
    rows = await service.top_impersonated_brands(
        limit=limit, start=start, end=end
    )
    return ApiResponse.ok(
        value=[BrandCountResponse.from_brand(r) for r in rows]
    )
