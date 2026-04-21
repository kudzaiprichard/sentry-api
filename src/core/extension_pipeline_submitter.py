"""Adapter: extension PipelineSubmitter -> inference InferenceService.submit.

Lives in ``src/core`` (composition) because the cross-module rule forbids
the extension from importing inference's domain layer and vice versa.

This adapter is called inline from the extension's analyse flow after the
Stage-1 response has been computed. It opens its own DB session so the
Email row is committed independently of the extension's request
transaction — a pipeline submission must not be rolled back if the
extension response handling fails downstream, and conversely a failure
here must not fail the Stage-1 response (the controller wraps the call
in try/except).

``InferenceService.submit`` both inserts the Email row and schedules the
background pipeline task via ``pipeline_runner.spawn``; this adapter
only needs to wire the session and forward the install id.
"""

from __future__ import annotations

import logging
from uuid import UUID

from src.modules.inference.domain.repositories import EmailRepository
from src.modules.inference.domain.services import InferenceService
from src.shared.database import async_session


logger = logging.getLogger(__name__)


class InferencePipelineSubmitter:
    """Stateless — safe to share across requests."""

    async def submit(
        self,
        *,
        sender: str,
        subject: str,
        body: str,
        install_id: UUID,
    ) -> None:
        async with async_session() as session:
            async with session.begin():
                svc = InferenceService(email_repo=EmailRepository(session))
                saved = await svc.submit(
                    sender=sender,
                    subject=subject,
                    body=body,
                    install_id=install_id,
                )
                logger.info(
                    "Pipeline submitted from extension: email_id=%s install_id=%s",
                    saved.id,
                    install_id,
                )
