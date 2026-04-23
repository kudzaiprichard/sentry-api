import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Text,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import BaseModel
from src.modules.inference.domain.models.enums import ResolveStatus


class Link(BaseModel):
    __tablename__ = "links"

    email_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("emails.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_shortened: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    shortener: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    anchor_context: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolve_status: Mapped[Optional[ResolveStatus]] = mapped_column(
        SAEnum(
            ResolveStatus,
            name="resolve_status_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    redirect_hops: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    intermediate_domains: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    http_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    email: Mapped["Email"] = relationship("Email", back_populates="links")
    page_analysis: Mapped[Optional["PageAnalysis"]] = relationship(
        "PageAnalysis",
        back_populates="link",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin",
    )
