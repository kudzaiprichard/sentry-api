import asyncio
import logging

from src.shared.database import async_session
from src.modules.auth.domain.repositories.token_repository import TokenRepository
from src.configs import security

logger = logging.getLogger(__name__)


async def start_token_cleanup() -> None:
    """Background loop that purges expired tokens on a fixed interval."""
    interval = security.token_cleanup_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            async with async_session() as session:
                async with session.begin():
                    repo = TokenRepository(session)
                    count = await repo.cleanup_expired()
                    if count:
                        logger.info("Token cleanup: removed %d expired token(s)", count)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Token cleanup failed: %s", e)
