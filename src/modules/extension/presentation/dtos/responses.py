"""Response DTOs for the extension auth surface.

Wire contract: camelCase aliases via ``Field(alias="...")`` with
``populate_by_name=True``. ``expiresAt`` is epoch milliseconds (int).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class InstallUserRef(BaseModel):
    email: str
    sub: str

    model_config = ConfigDict(populate_by_name=True)


class ExtensionRegisterResponse(BaseModel):
    token: str
    expires_at: int = Field(alias="expiresAt")
    user: InstallUserRef

    model_config = ConfigDict(populate_by_name=True)


class ExtensionTokenResponse(BaseModel):
    token: str
    expires_at: int = Field(alias="expiresAt")

    model_config = ConfigDict(populate_by_name=True)
