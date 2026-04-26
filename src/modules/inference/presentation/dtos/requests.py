from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from src.modules.inference.domain.models.enums import Classification


class SubmitEmailRequest(BaseModel):
    sender: str = Field(min_length=1, max_length=320)
    subject: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=500_000)
    received_at: Optional[datetime] = Field(default=None, alias="receivedAt")

    class Config:
        populate_by_name = True


class SubmitEmailBatchRequest(BaseModel):
    emails: List[SubmitEmailRequest] = Field(min_length=1)


class ReanalyzeRequest(BaseModel):
    body: str = Field(min_length=1, max_length=500_000)


class ManualReviewRequest(BaseModel):
    note: str = Field(min_length=1, max_length=2000)
    override_classification: Optional[Classification] = Field(
        default=None, alias="overrideClassification"
    )

    class Config:
        populate_by_name = True
