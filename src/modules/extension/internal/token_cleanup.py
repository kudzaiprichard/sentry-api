import asyncio
import logging

from src.configs import security
from src.modules.extension.domain.repositories.extension_token_repository import (
    ExtensionTokenRepository,
)
from src.shared.database import async_session


logger = logging.getLogger(__name__)


async def start_extension_token_cleanup() -> None:
    """Background loop that purges expired extension tokens on a fixed interval."""
    interval = security.extension_token_cleanup_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            async with async_session() as session:
                async with session.begin():
                    repo = ExtensionTokenRepository(session)
                    count = await repo.cleanup_expired()
                    if count:
                        logger.info(
                            "Extension token cleanup: removed %d expired token(s)",
                            count,
                        )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Extension token cleanup failed: %s", e)
