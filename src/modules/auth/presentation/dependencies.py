from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from src.shared.database import get_db
from src.shared.exceptions import AuthorizationException
from src.shared.responses import ErrorDetail
from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.models.enums import Role
from src.modules.auth.domain.repositories.user_repository import UserRepository
from src.modules.auth.domain.repositories.token_repository import TokenRepository
from src.modules.auth.domain.services.auth_service import AuthService
from src.modules.auth.domain.services.user_management_service import UserManagementService

bearer_scheme = HTTPBearer()


# ── Service factories ──

def get_auth_service(session: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(session), TokenRepository(session))


def get_user_management_service(session: AsyncSession = Depends(get_db)) -> UserManagementService:
    return UserManagementService(UserRepository(session))


# ── Auth dependencies ──

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    return await auth_service.get_current_user(credentials.credentials)


def require_role(*allowed_roles: Role):
    async def _guard(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            role_names = ", ".join(r.value for r in allowed_roles)
            raise AuthorizationException(
                message="You don't have permission to perform this action",
                error_detail=ErrorDetail(
                    title="Access Denied",
                    code="INSUFFICIENT_ROLE",
                    status=403,
                    details=[f"Required role(s): {role_names}"],
                ),
            )
        return current_user
    return _guard


# Convenience aliases
require_admin = require_role(Role.ADMIN)
require_authenticated = require_role(Role.ADMIN, Role.IT_ANALYST)
