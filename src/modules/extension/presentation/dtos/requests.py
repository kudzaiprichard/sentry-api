"""Request DTOs for the extension surface.

Wire contract: all camelCase aliases via ``Field(alias="...")`` with
``populate_by_name=True``. Matches ``.docs/BACKEND_CONTRACT.md`` verbatim.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ExtensionEnvironment(BaseModel):
    """Extension environment block sent with /auth/extension/register.

    Stored verbatim on ``extension_installs.environment_json`` for forensics.
    Only ``extensionVersion`` is required.
    """

    user_agent: str | None = Field(default=None, alias="userAgent")
    browser: dict[str, Any] | None = None
    os: dict[str, Any] | None = None
    language: str | None = None
    timezone: str | None = None
    extension_version: str = Field(alias="extensionVersion", min_length=1)

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class ExtensionRegisterRequest(BaseModel):
    email: EmailStr
    sub: str = Field(min_length=1, max_length=255)
    environment: ExtensionEnvironment

    model_config = ConfigDict(populate_by_name=True, extra="ignore")
