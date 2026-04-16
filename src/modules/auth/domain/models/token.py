import uuid
from datetime import datetime, timezone

from sqlalchemy import Text, Boolean, DateTime, ForeignKey, Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from src.shared.database import BaseModel
from src.modules.auth.domain.models.enums import TokenType


class Token(BaseModel):
    __tablename__ = "tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(
        Text, nullable=False, unique=True, index=True
    )
    token_type: Mapped[TokenType] = mapped_column(
        SAEnum(TokenType, name="token_type_enum"), nullable=False
    )
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and self.expires_at > datetime.now(timezone.utc)

    def revoke(self) -> None:
        self.is_revoked = True
