"""Analyse-call audit rows — powers the admin activity endpoint.

Only the non-PII fields required by STANDARD §15 are stored here:
``install_id``, ``model_version``, ``predicted_label``, ``confidence_score``,
``latency_ms``, ``request_id``. No sender, no subject, no body, no email
content ever lands in this table.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.database import BaseModel


class ExtensionAnalyseEvent(BaseModel):
    __tablename__ = "extension_analyse_events"

    install_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("extension_installs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    predicted_label: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
