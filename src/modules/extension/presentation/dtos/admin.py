"""Admin DTOs for the install management surface.

Wire shape: camelCase via ``Field(alias="...")`` with ``populate_by_name=True``
and ``from_attributes=True``, using ``from_*`` static factories that pass
values by alias name. Matches the existing convention (see
``UserResponse.from_user``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.modules.extension.domain.models.extension_analyse_event import (
    ExtensionAnalyseEvent,
)
from src.modules.extension.domain.models.extension_install import (
    ExtensionInstall,
)


# ── Install list / detail ──

class InstallResponse(BaseModel):
    id: UUID
    email: str
    google_sub: str = Field(alias="googleSub")
    status: str
    extension_version: Optional[str] = Field(default=None, alias="extensionVersion")
    last_seen_at: Optional[datetime] = Field(default=None, alias="lastSeenAt")
    blacklisted_at: Optional[datetime] = Field(
        default=None, alias="blacklistedAt"
    )
    blacklist_reason: Optional[str] = Field(
        default=None, alias="blacklistReason"
    )
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    @staticmethod
    def from_install(install: ExtensionInstall) -> "InstallResponse":
        return InstallResponse(
            id=install.id,
            email=install.email,
            googleSub=install.google_sub,
            status=install.status.value,
            extensionVersion=install.extension_version,
            lastSeenAt=install.last_seen_at,
            blacklistedAt=install.blacklisted_at,
            blacklistReason=install.blacklist_reason,
            createdAt=install.created_at,
            updatedAt=install.updated_at,
        )


class InstallDetailResponse(InstallResponse):
    active_token_count: int = Field(alias="activeTokenCount")
    environment: Optional[dict] = None

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    @staticmethod
    def from_install_with_count(
        install: ExtensionInstall, active_count: int
    ) -> "InstallDetailResponse":
        return InstallDetailResponse(
            id=install.id,
            email=install.email,
            googleSub=install.google_sub,
            status=install.status.value,
            extensionVersion=install.extension_version,
            lastSeenAt=install.last_seen_at,
            blacklistedAt=install.blacklisted_at,
            blacklistReason=install.blacklist_reason,
            createdAt=install.created_at,
            updatedAt=install.updated_at,
            activeTokenCount=active_count,
            environment=install.environment_json,
        )


# ── Activity ──

class AnalyseEventResponse(BaseModel):
    id: UUID
    install_id: UUID = Field(alias="installId")
    predicted_label: str = Field(alias="predictedLabel")
    confidence_score: float = Field(alias="confidenceScore")
    model_version: str = Field(alias="modelVersion")
    latency_ms: int = Field(alias="latencyMs")
    request_id: Optional[str] = Field(default=None, alias="requestId")
    created_at: datetime = Field(alias="createdAt")

    model_config = ConfigDict(populate_by_name=True, from_attributes=True)

    @staticmethod
    def from_event(event: ExtensionAnalyseEvent) -> "AnalyseEventResponse":
        return AnalyseEventResponse(
            id=event.id,
            installId=event.install_id,
            predictedLabel=event.predicted_label,
            confidenceScore=event.confidence_score,
            modelVersion=event.model_version,
            latencyMs=event.latency_ms,
            requestId=event.request_id,
            createdAt=event.created_at,
        )


# ── Mutation requests ──

class BlacklistInstallRequest(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class BlacklistDomainRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=320)
    reason: Optional[str] = Field(default=None, max_length=500)

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class RevokeTokensResponse(BaseModel):
    revoked: int

    model_config = ConfigDict(populate_by_name=True)


class BlacklistDomainResponse(BaseModel):
    installs_updated: int = Field(alias="installsUpdated")
    tokens_revoked: int = Field(alias="tokensRevoked")

    model_config = ConfigDict(populate_by_name=True)
