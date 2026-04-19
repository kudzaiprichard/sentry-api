import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import BaseModel


class ExtensionToken(BaseModel):
    __tablename__ = "extension_tokens"

    install_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("extension_installs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    is_revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    revoked_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    install: Mapped["ExtensionInstall"] = relationship(  # noqa: F821
        "ExtensionInstall", back_populates="tokens"
    )

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= datetime.now(timezone.utc)

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_expired

    def revoke(self, reason: str | None = None) -> None:
        self.is_revoked = True
        if reason:
            self.revoked_reason = reason
