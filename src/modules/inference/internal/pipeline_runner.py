import asyncio
import logging
from uuid import UUID

from sqlalchemy import update

from src.shared.database import async_session
from src.modules.inference.domain.models.email import Email
from src.modules.inference.domain.models.enums import PipelineStatus


logger = logging.getLogger(__name__)


# Module-level set holding strong references to in-flight pipeline tasks.
#
# `asyncio.create_task` only holds a *weak* reference, so a task with no other
# referent can be garbage-collected mid-run (the loop logs a warning and the
# coroutine simply stops). Adding the task here keeps it alive until it
# completes; the done-callback removes it again so the set drains naturally.
_in_flight: set[asyncio.Task] = set()


def spawn(email_id: UUID, sender: str, subject: str, body: str) -> asyncio.Task:
    """Schedule a pipeline run as a background task and retain a strong ref."""
    task = asyncio.create_task(
        run(email_id, sender, subject, body),
        name=f"pipeline:{email_id}",
    )
    _in_flight.add(task)
    task.add_done_callback(_in_flight.discard)
    return task


def in_flight_tasks() -> set[asyncio.Task]:
    """Snapshot of currently-running pipeline tasks (used by the lifespan drain)."""
    return set(_in_flight)


async def drain(timeout: float = 30.0) -> None:
    """Wait for all in-flight tasks to finish, up to a grace period."""
    pending = list(_in_flight)
    if not pending:
        return
    logger.info("Draining %d in-flight pipeline task(s)", len(pending))
    try:
        await asyncio.wait_for(
            asyncio.gather(*pending, return_exceptions=True),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        still_running = sum(1 for t in pending if not t.done())
        logger.warning(
            "Timed out draining pipeline tasks; %d still running", still_running
        )


# ── Service factory — overridable in tests ───────────────────────────────────


def _build_service():
    """Construct the InferenceService used by the background runner.

    Tests monkey-patch this to inject mocked stage services / LLM clients.
    """
    from src.modules.inference.domain.repositories import (
        EmailRepository,
        LinkRepository,
        PageAnalysisRepository,
    )
    from src.modules.inference.domain.services import (
        AggregationService,
        EmailClassificationService,
        InferenceService,
        LinkResolutionService,
        PageAnalysisService,
    )

    # The runner-bound service does not use these repos (run_pipeline opens its
    # own per-stage sessions), but the constructor accepts them so the same
    # class serves both request-scoped and background callers.
    return InferenceService(
        email_repo=None,
        link_repo=None,
        page_analysis_repo=None,
        classification_service=EmailClassificationService(),
        resolution_service=LinkResolutionService(),
        page_analysis_service=PageAnalysisService(),
        aggregation_service=AggregationService(),
    )


async def run(email_id: UUID, sender: str, subject: str, body: str) -> None:
    """Background entry point — own session, own service, own try/except."""
    try:
        await _wait_for_email(email_id)
        svc = _build_service()
        await svc.run_pipeline(email_id, sender, subject, body)
    except asyncio.CancelledError:
        logger.warning("Pipeline cancelled for email %s", email_id)
        raise
    except Exception as e:
        logger.exception("Pipeline failed for email %s", email_id)
        await _mark_failed(email_id, _truncate(str(e), 1000))


async def _wait_for_email(
    email_id: UUID, *, max_attempts: int = 20, interval: float = 0.05
) -> None:
    """Defensive wait — the request that spawned us may not have committed yet."""
    for _ in range(max_attempts):
        async with async_session() as session:
            row = await session.get(Email, email_id)
            if row is not None:
                return
        await asyncio.sleep(interval)


async def _mark_failed(email_id: UUID, error: str) -> None:
    try:
        async with async_session() as session:
            async with session.begin():
                await session.execute(
                    update(Email)
                    .where(Email.id == email_id)
                    .values(
                        pipeline_status=PipelineStatus.FAILED,
                        pipeline_error=error,
                    )
                )
    except Exception:
        logger.exception("Could not mark email %s as FAILED", email_id)


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 3] + "..."
