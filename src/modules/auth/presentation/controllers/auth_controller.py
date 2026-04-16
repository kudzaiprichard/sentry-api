from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials

from src.shared.responses import ApiResponse
from src.modules.auth.domain.models.user import User
from src.modules.auth.domain.services.auth_service import AuthService
from src.modules.auth.presentation.dependencies import (
    bearer_scheme,
    get_auth_service,
    get_current_user,
)
from src.modules.auth.presentation.dtos.requests import (
    RegisterRequest,
    LoginRequest,
    RefreshTokenRequest,
    UpdateProfileRequest,
)
from src.modules.auth.presentation.dtos.responses import (
    UserResponse,
    TokenResponse,
    AuthResponse,
)

router = APIRouter()


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    user, tokens = await auth_service.register(
        email=body.email,
        username=body.username,
        first_name=body.first_name,
        last_name=body.last_name,
        password=body.password,
    )
    return ApiResponse.ok(
        value=AuthResponse(
            user=UserResponse.from_user(user),
            tokens=TokenResponse(
                accessToken=tokens["access_token"],
                refreshToken=tokens["refresh_token"],
            ),
        ),
        message="Registration successful",
    )


@router.post("/login")
async def login(
    body: LoginRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    user, tokens = await auth_service.login(email=body.email, password=body.password)
    return ApiResponse.ok(
        value=AuthResponse(
            user=UserResponse.from_user(user),
            tokens=TokenResponse(
                accessToken=tokens["access_token"],
                refreshToken=tokens["refresh_token"],
            ),
        ),
        message="Login successful",
    )


@router.post("/refresh")
async def refresh_token(
    body: RefreshTokenRequest,
    auth_service: AuthService = Depends(get_auth_service),
):
    tokens = await auth_service.refresh_token(body.refresh_token)
    return ApiResponse.ok(
        value=TokenResponse(
            accessToken=tokens["access_token"],
            refreshToken=tokens["refresh_token"],
        ),
        message="Tokens refreshed",
    )


@router.post("/logout", status_code=200)
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    auth_service: AuthService = Depends(get_auth_service),
):
    await auth_service.logout(credentials.credentials)
    return ApiResponse.ok(value=None, message="Logged out successfully")


@router.get("/me")
async def get_profile(current_user: User = Depends(get_current_user)):
    return ApiResponse.ok(value=UserResponse.from_user(current_user))


@router.patch("/me")
async def update_profile(
    body: UpdateProfileRequest,
    current_user: User = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
):
    updated = await auth_service.update_profile(
        user=current_user,
        first_name=body.first_name,
        last_name=body.last_name,
        username=body.username,
    )
    return ApiResponse.ok(value=UserResponse.from_user(updated), message="Profile updated")
