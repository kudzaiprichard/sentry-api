from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.repositories.user_repository import UserRepository
from src.modules.auth.domain.repositories.token_repository import TokenRepository
from src.modules.auth.internal import password_hasher, token_provider
from src.shared.exceptions import (
    ConflictException,
    AuthenticationException,
    NotFoundException,
)
from src.shared.responses import ErrorDetail


class AuthService:
    def __init__(self, user_repository: UserRepository, token_repository: TokenRepository):
        self.user_repo = user_repository
        self.token_repo = token_repository

    async def login(self, email: str, password: str) -> tuple[User, dict]:
        user = await self.user_repo.get_by_email(email)

        if not user or not password_hasher.verify_password(password, user.password_hash):
            raise AuthenticationException(
                message="Invalid email or password",
                error_detail=ErrorDetail(
                    title="Login Failed",
                    code="INVALID_CREDENTIALS",
                    status=401,
                    details=["Invalid email or password"],
                ),
            )

        if not user.is_active:
            raise AuthenticationException(
                message="Your account has been deactivated",
                error_detail=ErrorDetail(
                    title="Account Inactive",
                    code="ACCOUNT_INACTIVE",
                    status=403,
                    details=["Account is deactivated"],
                ),
            )

        await self.token_repo.revoke_all_user_tokens(user.id)
        tokens = await token_provider.create_token_pair(
            user.id, user.role.value, self.token_repo
        )

        return user, tokens

    async def register(
        self,
        email: str,
        username: str,
        first_name: str,
        last_name: str,
        password: str,
    ) -> tuple[User, dict]:
        from src.modules.auth.domain.models.enums import Role

        if await self.user_repo.email_exists(email):
            error = ErrorDetail.builder("Registration Failed", "EMAIL_EXISTS", 409)
            error.add_field_error("email", "Email already registered")
            raise ConflictException(
                message="This email is already registered",
                error_detail=error.build(),
            )

        if await self.user_repo.username_exists(username):
            error = ErrorDetail.builder("Registration Failed", "USERNAME_EXISTS", 409)
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
            role=Role.IT_ANALYST,
        )

        saved_user = await self.user_repo.create(user)
        tokens = await token_provider.create_token_pair(
            saved_user.id, saved_user.role.value, self.token_repo
        )

        return saved_user, tokens

    async def refresh_token(self, refresh_token: str) -> dict:
        payload = await token_provider.verify_token(
            refresh_token, self.token_repo, expected_type="refresh"
        )

        user = await self.user_repo.get_by_id(payload["sub"])
        if not user:
            raise NotFoundException(
                message="Your account could not be found",
                error_detail=ErrorDetail(
                    title="User Not Found",
                    code="USER_NOT_FOUND",
                    status=404,
                    details=["User associated with token not found"],
                ),
            )

        if not user.is_active:
            raise AuthenticationException(
                message="Your account has been deactivated",
                error_detail=ErrorDetail(
                    title="Account Inactive",
                    code="ACCOUNT_INACTIVE",
                    status=403,
                    details=["Account is deactivated"],
                ),
            )

        await self.token_repo.revoke_token(refresh_token)
        return await token_provider.create_token_pair(
            user.id, user.role.value, self.token_repo
        )

    async def logout(self, token: str) -> None:
        payload = token_provider.decode_token(token, expected_type="access")
        await self.token_repo.revoke_all_user_tokens(payload["sub"])

    async def get_current_user(self, token: str) -> User:
        payload = await token_provider.verify_token(
            token, self.token_repo, expected_type="access"
        )

        user = await self.user_repo.get_by_id(payload["sub"])
        if not user:
            raise NotFoundException(
                message="Your account could not be found",
                error_detail=ErrorDetail(
                    title="User Not Found",
                    code="USER_NOT_FOUND",
                    status=404,
                    details=["User associated with token not found"],
                ),
            )

        if not user.is_active:
            raise AuthenticationException(
                message="Your account has been deactivated",
                error_detail=ErrorDetail(
                    title="Account Inactive",
                    code="ACCOUNT_INACTIVE",
                    status=403,
                    details=["Account is deactivated"],
                ),
            )

        return user

    async def update_profile(
        self,
        user: User,
        first_name: str | None = None,
        last_name: str | None = None,
        username: str | None = None,
    ) -> User:
        data = {}

        if first_name is not None:
            data["first_name"] = first_name
        if last_name is not None:
            data["last_name"] = last_name

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
