import logging

from src.shared.database import async_session
from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.models.enums import Role
from src.modules.auth.domain.repositories.user_repository import UserRepository
from src.modules.auth.internal import password_hasher
from src.configs import security

logger = logging.getLogger(__name__)


async def seed_admin() -> None:
    async with async_session() as session:
        async with session.begin():
            repo = UserRepository(session)

            if await repo.exists(role=Role.ADMIN):
                logger.info("Admin user already exists — skipping seed")
                return

            admin = User(
                email=security.admin.email,
                username=security.admin.username,
                first_name=security.admin.first_name,
                last_name=security.admin.last_name,
                password_hash=password_hasher.hash_password(security.admin.password),
                role=Role.ADMIN,
            )

            await repo.create(admin)
            logger.info("Default admin user created (%s)", security.admin.email)
