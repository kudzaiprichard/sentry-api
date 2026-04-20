"""Orchestrates POST /api/v1/emails/analyze.

- Projects the full Gmail DTO down to ``(sender, subject, body)`` per §12.
- Delegates to the detector (``src.modules.extension.internal.detector``).
- Maps the binary model label → the extension's discriminated label
  (SPAM / NOT_SPAM / REVIEW) per §12.
- Computes ``should_alert`` using ``inference.alert_threshold``.

Kept tiny — the detector itself is swappable and owns the ML logic. This
service is only DTO wiring + label mapping + logging.
"""

from __future__ import annotations

import logging
import time

from src.configs import inference as inference_config
from src.modules.extension.domain.models.extension_analyse_event import (
    ExtensionAnalyseEvent,
)
from src.modules.extension.domain.repositories.extension_analyse_event_repository import (
    ExtensionAnalyseEventRepository,
)
from src.modules.extension.internal.detector import (
    Detector,
    DetectorPrediction,
    EmailAuth,
)
from src.modules.extension.internal.html_text import strip_html
from src.modules.extension.internal.pipeline_submitter import PipelineSubmitter
from src.modules.extension.presentation.dtos.email_analyse import (
    AnalyseEmailRequest,
    EmailIdRef,
    ExtensionAnalysisResponse,
    ExtensionPrediction,
)
from src.shared.exceptions import BadRequestException
from src.shared.responses import ErrorDetail


logger = logging.getLogger(__name__)


def _too_large() -> BadRequestException:
    return BadRequestException(
        message="Email too large to analyse",
        error_detail=ErrorDetail(
            title="Email too large to analyse",
            code="BAD_REQUEST",
            status=400,
            details=[
                "Body exceeds inference.emails.max_body_bytes"
            ],
        ),
    )


def _project_body(req: AnalyseEmailRequest) -> str:
    text = (req.body.text or "").strip()
    if text:
        return text
    return strip_html(req.body.html or "")


def _project_auth(req: AnalyseEmailRequest) -> EmailAuth | None:
    """Forward the receiving mail server's DKIM/SPF/DMARC verdicts.

    DMARC=pass is the single strongest "this is really from who it claims
    to be" signal for well-known transactional senders (Stripe, GitHub,
    banks, etc.) — dropping it causes the classifier to see only body
    signals and over-fire on legitimate mail.
    """
    ar = req.headers.auth_results
    if ar is None:
        return None
    dkim = (ar.dkim or "").strip() or None
    spf = (ar.spf or "").strip() or None
    dmarc = (ar.dmarc or "").strip() or None
    if not (dkim or spf or dmarc):
        return None
    return EmailAuth(dkim=dkim, spf=spf, dmarc=dmarc)


def _map_label(pred: DetectorPrediction) -> str:
    """Binary detector label → extension's discriminated label.

    §12: ``confidence_zone == REVIEW`` when
    ``review_low <= phishing_probability <= review_high``. Otherwise the
    binary label decides. Detectors that do not expose a review band fall
    through to the binary mapping.
    """
    lo = pred.review_low
    hi = pred.review_high
    p = pred.phishing_probability
    if lo is not None and hi is not None and lo <= p <= hi:
        return "REVIEW"
    return "SPAM" if pred.predicted_label == 1 else "NOT_SPAM"


def _should_alert(label: str, phishing_probability: float) -> bool:
    return (
        label == "SPAM"
        and phishing_probability >= inference_config.alert_threshold
    )


class EmailAnalyseService:
    def __init__(
        self,
        detector: Detector,
        event_repo: ExtensionAnalyseEventRepository,
        pipeline_submitter: PipelineSubmitter | None = None,
    ):
        self._detector = detector
        self._event_repo = event_repo
        self._pipeline_submitter = pipeline_submitter

    async def analyse(
        self,
        *,
        req: AnalyseEmailRequest,
        install_id,
        request_id: str | None,
    ) -> ExtensionAnalysisResponse:
        body = _project_body(req)

        # Body size cap (§12, inference.emails.max_body_bytes). Bytes, not
        # characters — the config key is explicit about bytes.
        body_bytes = body.encode("utf-8")
        if len(body_bytes) > inference_config.emails.max_body_bytes:
            raise _too_large()

        sender = (req.headers.from_ or "").strip()
        subject = (req.headers.subject or "").strip()
        auth = _project_auth(req)

        started = time.perf_counter()
        pred = await self._detector.predict(
            sender=sender, subject=subject, body=body, auth=auth
        )
        latency_ms = int((time.perf_counter() - started) * 1000)

        label = _map_label(pred)
        phishing_prob = float(pred.phishing_probability)
        legitimate_prob = max(0.0, min(1.0, 1.0 - phishing_prob))
        confidence = (
            phishing_prob if label == "SPAM" else legitimate_prob
            if label == "NOT_SPAM"
            else phishing_prob  # REVIEW: use phishing prob as the score
        )
        alert = _should_alert(label, phishing_prob)

        await self._event_repo.create(
            ExtensionAnalyseEvent(
                install_id=install_id,
                predicted_label=label,
                confidence_score=round(confidence, 6),
                model_version=pred.model_version,
                latency_ms=latency_ms,
                request_id=request_id,
            )
        )

        # Hand off to the full background pipeline (Stages 2-4) so the
        # dashboard eventually shows link resolution and final
        # aggregation. Must not affect the Stage 1 response the extension
        # is waiting on — submitter owns its own session, and any failure
        # here is logged and swallowed.
        if self._pipeline_submitter is not None:
            try:
                await self._pipeline_submitter.submit(
                    sender=sender,
                    subject=subject,
                    body=body,
                    install_id=install_id,
                )
            except Exception:
                logger.exception(
                    "Background pipeline submit failed for install_id=%s "
                    "request_id=%s",
                    install_id,
                    request_id or "-",
                )

        logger.info(
            "Analyse OK: install_id=%s model_version=%s "
            "predicted_label=%s confidence_score=%.4f latency_ms=%d "
            "request_id=%s",
            install_id,
            pred.model_version,
            label,
            confidence,
            latency_ms,
            request_id or "-",
        )

        return ExtensionAnalysisResponse(
            email=EmailIdRef(id=req.message_id),
            prediction=ExtensionPrediction(
                predicted_label=label,
                confidence_score=round(confidence, 6),
                phishing_probability=round(phishing_prob, 6),
                legitimate_probability=round(legitimate_prob, 6),
                threshold_used=float(pred.threshold_used),
                should_alert=alert,
                message=pred.message,
                email_id=req.message_id,
                model_version=pred.model_version,
            ),
        )
