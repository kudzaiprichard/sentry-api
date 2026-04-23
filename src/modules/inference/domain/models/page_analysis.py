import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Text,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.shared.database import BaseModel
from src.modules.inference.domain.models.enums import RiskLevel, ScrapeStatus


class PageAnalysis(BaseModel):
    __tablename__ = "page_analysis"

    link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("links.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Raw scraped data
    page_title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    meta_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    has_login_form: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    has_payment_form: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    external_domains: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    favicon_matches_domain: Mapped[Optional[bool]] = mapped_column(
        Boolean, nullable=True
    )

    # LLM analysis output
    page_purpose: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    impersonates_brand: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )
    requests_credentials: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    requests_payment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    risk_level: Mapped[Optional[RiskLevel]] = mapped_column(
        SAEnum(
            RiskLevel,
            name="risk_level_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    risk_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    risk_reasons: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Meta
    scrape_status: Mapped[Optional[ScrapeStatus]] = mapped_column(
        SAEnum(
            ScrapeStatus,
            name="scrape_status_enum",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=True,
    )
    llm_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    analysed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    link: Mapped["Link"] = relationship("Link", back_populates="page_analysis")
