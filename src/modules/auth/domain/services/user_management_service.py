from typing import Sequence, Tuple
from uuid import UUID

from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.models.enums import Role
from src.modules.auth.domain.repositories.user_repository import UserRepository
from src.modules.auth.internal import password_hasher
from src.shared.exceptions import (
    NotFoundException,
    ConflictException,
)
from src.shared.responses import ErrorDetail


class UserManagementService:
    def __init__(self, user_repository: UserRepository):
        self.user_repo = user_repository

    async def get_users(
        self,
        page: int = 1,
        page_size: int = 20,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> Tuple[Sequence[User], int]:
        filters = {}
        if role is not None:
            filters["role"] = Role[role]
        if is_active is not None:
            filters["is_active"] = is_active

        return await self.user_repo.paginate(
            page=page,
            page_size=page_size,
            order_by="created_at",
            descending=True,
            **filters,
        )

    async def get_user(self, user_id: UUID) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundException(
                message="User not found",
                error_detail=ErrorDetail(
                    title="Not Found",
                    code="USER_NOT_FOUND",
                    status=404,
                    details=[f"No user found with id {user_id}"],
                ),
            )
        return user

    async def create_user(
        self,
        email: str,
        username: str,
        first_name: str,
        last_name: str,
        password: str,
        role: str,
    ) -> User:
        if await self.user_repo.email_exists(email):
            error = ErrorDetail.builder("Creation Failed", "EMAIL_EXISTS", 409)
            error.add_field_error("email", "Email already registered")
            raise ConflictException(
                message="This email is already registered",
                error_detail=error.build(),
            )

        if await self.user_repo.username_exists(username):
            error = ErrorDetail.builder("Creation Failed", "USERNAME_EXISTS", 409)
            error.add_field_error("username", "Username already taken")
            raise ConflictException(
                message="This username is already taken",
                error_detail=error.build(),
            )

        user = User(
            email=email,
            username=username,
            first_name=first_name,
            last_name=last_name,
            password_hash=password_hasher.hash_password(password),
            role=Role[role],
        )

        return await self.user_repo.create(user)

    async def update_user(
        self,
        user_id: UUID,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> User:
        user = await self.get_user(user_id)
        data = {}

        if first_name is not None:
            data["first_name"] = first_name
        if last_name is not None:
            data["last_name"] = last_name
        if role is not None:
            data["role"] = Role[role]
        if is_active is not None:
            data["is_active"] = is_active

        if username is not None and username != user.username:
            if await self.user_repo.username_exists(username):
                error = ErrorDetail.builder("Update Failed", "USERNAME_EXISTS", 409)
                error.add_field_error("username", "Username already taken")
                raise ConflictException(
                    message="This username is already taken",
                    error_detail=error.build(),
                )
            data["username"] = username

        if not data:
            return user

        return await self.user_repo.update(user, data)

    async def delete_user(self, user_id: UUID) -> None:
        user = await self.get_user(user_id)
        await self.user_repo.delete(user)

    async def set_active_status(self, user_id: UUID, is_active: bool) -> User:
        user = await self.get_user(user_id)
        if user.is_active == is_active:
            return user
        return await self.user_repo.update(user, {"is_active": is_active})
