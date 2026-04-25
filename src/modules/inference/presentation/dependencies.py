from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.auth.domain.models.enums import Role
from src.modules.auth.presentation.dependencies import (
    get_current_user,
    require_admin,
    require_role,
)
from src.modules.inference.domain.repositories import (
    EmailRepository,
    LinkRepository,
    PageAnalysisRepository,
)
from src.modules.inference.domain.services import (
    AggregationService,
    EmailClassificationService,
    InferenceService,
    InferenceStatsService,
    LinkResolutionService,
    PageAnalysisService,
    PredictionHistoryService,
)
from src.shared.database import get_db, get_db_readonly


require_authenticated = require_role(Role.ADMIN, Role.IT_ANALYST)


def get_inference_service(
    session: AsyncSession = Depends(get_db),
) -> InferenceService:
    return InferenceService(
        email_repo=EmailRepository(session),
        link_repo=LinkRepository(session),
        page_analysis_repo=PageAnalysisRepository(session),
        classification_service=EmailClassificationService(),
        resolution_service=LinkResolutionService(),
        page_analysis_service=PageAnalysisService(),
        aggregation_service=AggregationService(),
    )


def get_prediction_history_service(
    session: AsyncSession = Depends(get_db_readonly),
) -> PredictionHistoryService:
    return PredictionHistoryService(
        email_repo=EmailRepository(session),
        link_repo=LinkRepository(session),
    )


def get_inference_stats_service(
    session: AsyncSession = Depends(get_db_readonly),
) -> InferenceStatsService:
    return InferenceStatsService(session)


__all__ = [
    "get_current_user",
    "get_inference_service",
    "get_inference_stats_service",
    "get_prediction_history_service",
    "require_admin",
    "require_authenticated",
]
