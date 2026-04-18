import asyncio
import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.shared.database.engine import engine
from src.configs import logging as log_config
from src.core.extension_pipeline_submitter import InferencePipelineSubmitter
from src.core.inference_detector import InferenceClassificationDetector
from src.modules.auth.internal import seed_admin, start_token_cleanup
from src.modules.extension.internal import start_extension_token_cleanup
from src.modules.inference.internal import pipeline_runner as inference_runner


logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    log_dir = os.path.dirname(log_config.file_path)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_level = getattr(logging, log_config.level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format=log_config.format,
        handlers=[
            logging.FileHandler(log_config.file_path),
            logging.StreamHandler(),
        ],
        force=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──
    _setup_logging()
    logger.info("Starting up — logging configured, DB pool initialised")

    await seed_admin()

    app.state.detector = InferenceClassificationDetector()
    app.state.pipeline_submitter = InferencePipelineSubmitter()
    logger.info("Detector wired — extension /emails/analyze is live")

    token_cleanup_task = asyncio.create_task(start_token_cleanup())
    extension_token_cleanup_task = asyncio.create_task(
        start_extension_token_cleanup()
    )

    yield

    # ── Shutdown ──
    for task in (token_cleanup_task, extension_token_cleanup_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await inference_runner.drain(timeout=30.0)

    await engine.dispose()
    logger.info("Shutting down — DB pool disposed")
