import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.shared.database.engine import engine
from src.configs import logging as log_config


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

    yield

    # ── Shutdown ──
    await engine.dispose()
    logger.info("Shutting down — DB pool disposed")
