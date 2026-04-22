"""DTOs for POST /api/v1/emails/analyze.

Request:  full Gmail shape per BACKEND_CONTRACT §5.5.1 — `extra = "ignore"`
          on every nested model so the extension can add fields without
          breaking the backend.

Response: snake_case ``prediction`` block per BACKEND_CONTRACT §3. The
          wrapper is a **separate DTO** — deliberately not derived from
          any inference response model.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Request ──

class AuthResults(BaseModel):
    dkim: Optional[str] = None
    spf: Optional[str] = None
    dmarc: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class EmailHeaders(BaseModel):
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None
    cc: Optional[str] = None
    bcc: Optional[str] = None
    reply_to: Optional[str] = Field(default=None, alias="replyTo")
    return_path: Optional[str] = Field(default=None, alias="returnPath")
    subject: Optional[str] = None
    date: Optional[str] = None
    message_id_header: Optional[str] = Field(
        default=None, alias="messageIdHeader"
    )
    dkim_signature: Optional[str] = Field(default=None, alias="dkimSignature")
    list_unsubscribe: Optional[str] = Field(
        default=None, alias="listUnsubscribe"
    )
    x_originating_ip: Optional[str] = Field(
        default=None, alias="xOriginatingIp"
    )
    received: Optional[List[str]] = None
    auth_results: Optional[AuthResults] = Field(
        default=None, alias="authResults"
    )

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class EmailBody(BaseModel):
    text: Optional[str] = None
    html: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class EmailAttachment(BaseModel):
    name: Optional[str] = None
    mime_type: Optional[str] = Field(default=None, alias="mimeType")
    size: Optional[int] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class AnalyseEmailRequest(BaseModel):
    message_id: str = Field(alias="messageId", min_length=1, max_length=128)
    thread_id: Optional[str] = Field(default=None, alias="threadId")
    label_ids: Optional[List[str]] = Field(default=None, alias="labelIds")
    snippet: Optional[str] = None
    headers: EmailHeaders
    body: EmailBody
    urls: Optional[List[str]] = None
    attachments: Optional[List[EmailAttachment]] = None

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


# ── Response ──

class EmailIdRef(BaseModel):
    id: str

    model_config = ConfigDict(populate_by_name=True)


class ExtensionPrediction(BaseModel):
    """Snake-case block — read directly by the extension (no aliases).

    The extension's parser lives in ``models/AnalysisResponse.js::fromJson``
    and reads ``predicted_label``, ``confidence_score``, etc. as-is.
    """

    predicted_label: str
    confidence_score: float
    phishing_probability: float
    legitimate_probability: float
    threshold_used: float
    should_alert: bool
    message: Optional[str] = None
    email_id: Optional[str] = None
    model_version: str

    model_config = ConfigDict(populate_by_name=True)


class ExtensionAnalysisResponse(BaseModel):
    email: EmailIdRef
    prediction: ExtensionPrediction

    model_config = ConfigDict(populate_by_name=True)
