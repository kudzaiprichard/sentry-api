import uuid
from datetime import datetime
from typing import Any, List, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.modules.extension.domain.models.enums import InstallStatus
from src.shared.database import BaseModel


class ExtensionInstall(BaseModel):
    __tablename__ = "extension_installs"

    google_sub: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    status: Mapped[InstallStatus] = mapped_column(
        SAEnum(InstallStatus, name="install_status_enum"),
        nullable=False,
        default=InstallStatus.ACTIVE,
    )
    extension_version: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    environment_json: Mapped[Optional[Any]] = mapped_column(JSONB, nullable=True)
    blacklisted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    blacklisted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    blacklist_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tokens: Mapped[List["ExtensionToken"]] = relationship(  # noqa: F821
        "ExtensionToken",
        back_populates="install",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def is_blacklisted(self) -> bool:
        return self.status == InstallStatus.BLACKLISTED
