import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Text,
    Float,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import BaseModel
from src.modules.inference.domain.models.enums import (
    Classification,
    OverrideTrigger,
    PipelineStage,
    PipelineStatus,
)


class Email(BaseModel):
    __tablename__ = "emails"

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    sender: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Stage 1 output
    classification: Mapped[Optional[Classification]] = mapped_column(
        SAEnum(
            Classification,
            name="classification_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    risk_factors: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    link_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Stage 4 output
    final_classification: Mapped[Optional[Classification]] = mapped_column(
        SAEnum(
            Classification,
            name="classification_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    final_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    aggregation_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    override_trigger: Mapped[Optional[OverrideTrigger]] = mapped_column(
        SAEnum(
            OverrideTrigger,
            name="override_trigger_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )

    # Pipeline bookkeeping
    pipeline_status: Mapped[PipelineStatus] = mapped_column(
        SAEnum(
            PipelineStatus,
            name="pipeline_status_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PipelineStatus.PENDING,
        index=True,
    )
    pipeline_stage: Mapped[PipelineStage] = mapped_column(
        SAEnum(
            PipelineStage,
            name="pipeline_stage_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PipelineStage.QUEUED,
    )
    pipeline_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finalised_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Manual review layer
    manual_review_flag: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    manual_review_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    manual_review_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    manual_review_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    manual_override_classification: Mapped[Optional[Classification]] = mapped_column(
        SAEnum(
            Classification,
            name="classification_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )

    # Submitter — FK into users.id (auth exception 1)
    submitted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Originating extension install when the email was submitted through the
    # extension surface — null for dashboard-submitted emails. FK to
    # extension_installs.id; the inference module never imports the extension
    # model itself, only the table name (the composition is wired in
    # src/core/).
    submitted_by_install: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("extension_installs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    links: Mapped[list["Link"]] = relationship(
        "Link",
        back_populates="email",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
