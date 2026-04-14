from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from src.shared.database.engine import async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Transactional session — auto-commits on success, rolls back on error."""
    async with async_session() as session:
        async with session.begin():
            yield session


async def get_db_readonly() -> AsyncGenerator[AsyncSession, None]:
    """Read-only session — no explicit transaction, no auto-commit."""
    async with async_session() as session:
        yield session
