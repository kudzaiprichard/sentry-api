from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field

from src.modules.auth.domain.models.user import User


class UserResponse(BaseModel):
    id: UUID
    email: str
    username: str
    first_name: str = Field(alias="firstName")
    last_name: str = Field(alias="lastName")
    role: str
    is_active: bool = Field(alias="isActive")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_user(user: User) -> "UserResponse":
        return UserResponse(
            id=user.id,
            email=user.email,
            username=user.username,
            firstName=user.first_name,
            lastName=user.last_name,
            role=user.role.value,
            isActive=user.is_active,
            createdAt=user.created_at,
            updatedAt=user.updated_at,
        )


class TokenResponse(BaseModel):
    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")

    class Config:
        populate_by_name = True


class AuthResponse(BaseModel):
    user: UserResponse
    tokens: TokenResponse
