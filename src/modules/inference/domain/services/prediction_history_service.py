from typing import Optional, Sequence, Tuple
from datetime import datetime
from uuid import UUID

from src.modules.inference.domain.models.email import Email
from src.modules.inference.domain.models.enums import (
    Classification,
    OverrideTrigger,
    PipelineStatus,
)
from src.modules.inference.domain.models.link import Link
from src.modules.inference.domain.repositories import (
    EmailRepository,
    LinkRepository,
)
from src.shared.exceptions import NotFoundException
from src.shared.responses.api_response import ErrorDetail


class PredictionHistoryService:
    """Read-only queries for submitted emails and their links.

    Thin orchestration over `EmailRepository` / `LinkRepository` that adds
    `NotFoundException` translation for single-row lookups. List queries
    pass straight through to the repository's filter builder.
    """

    def __init__(
        self,
        email_repo: EmailRepository,
        link_repo: LinkRepository,
    ):
        self.email_repo = email_repo
        self.link_repo = link_repo

    async def get_detail(self, email_id: UUID) -> Email:
        email = await self.email_repo.get_with_full_detail(email_id)
        if email is None:
            raise NotFoundException(
                message="Email not found",
                error_detail=ErrorDetail(
                    title="Email Not Found",
                    code="EMAIL_NOT_FOUND",
                    status=404,
                    details=[f"No email with id {email_id}"],
                ),
            )
        return email

    async def list(
        self,
        page: int = 1,
        page_size: int = 20,
        *,
        classification: Optional[Classification] = None,
        min_confidence: Optional[float] = None,
        max_confidence: Optional[float] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        pipeline_status: Optional[PipelineStatus] = None,
        override_trigger: Optional[OverrideTrigger] = None,
        sender: Optional[str] = None,
    ) -> Tuple[Sequence[Email], int]:
        return await self.email_repo.list_with_filters(
            page=page,
            page_size=page_size,
            classification=classification,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            start_date=start_date,
            end_date=end_date,
            pipeline_status=pipeline_status,
            override_trigger=override_trigger,
            sender=sender,
        )

    async def get_link(self, link_id: UUID) -> Link:
        link = await self.link_repo.get_with_page(link_id)
        if link is None:
            raise NotFoundException(
                message="Link not found",
                error_detail=ErrorDetail(
                    title="Link Not Found",
                    code="LINK_NOT_FOUND",
                    status=404,
                    details=[f"No link with id {link_id}"],
                ),
            )
        return link
