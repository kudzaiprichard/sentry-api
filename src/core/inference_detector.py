"""Adapter: inference Stage-1 classifier → extension Detector protocol.

Lives in ``src/core`` (composition) rather than in either module because the
cross-module rule forbids extension from importing inference's domain layer
and vice versa. Core is the app-factory layer — it already wires routers,
middleware, and lifecycle across modules, so detector wiring fits here.

Only Stage 1 of the inference pipeline (the Groq classifier) runs in the
request path. Link resolution and page analysis stay in the async background
pipeline and are not used by the extension surface.

Three-way ``Classification`` → binary + review-band mapping:

- PHISHING    → predicted_label=1, phishing_probability = confidence
- LEGITIMATE  → predicted_label=0, phishing_probability = 1 - confidence
- SUSPICIOUS  → phishing_probability set inside the review band so
                ``_map_label`` in EmailAnalyseService returns REVIEW
"""

from __future__ import annotations

from typing import Optional

from src.configs import inference as inference_config
from src.modules.extension.internal.detector import DetectorPrediction, EmailAuth
from src.modules.inference.domain.models.enums import Classification
from src.modules.inference.domain.services.email_classification_service import (
    AuthSignals,
    EmailClassificationService,
)


_DECISION_THRESHOLD = 0.5
_REVIEW_LOW = 0.4
_REVIEW_HIGH = 0.6


class InferenceClassificationDetector:
    """Stateless adapter — safe to share across requests."""

    def __init__(self, service: Optional[EmailClassificationService] = None):
        self._service = service or EmailClassificationService()

    @property
    def model_version(self) -> str:
        return inference_config.groq.model

    async def predict(
        self,
        *,
        sender: str,
        subject: str,
        body: str,
        auth: EmailAuth | None = None,
    ) -> DetectorPrediction:
        auth_signals = (
            AuthSignals(dkim=auth.dkim, spf=auth.spf, dmarc=auth.dmarc)
            if auth is not None and not auth.is_empty()
            else None
        )
        result = await self._service.classify(
            sender, subject, body, auth_signals=auth_signals
        )

        confidence = float(result.confidence)
        if result.classification == Classification.PHISHING:
            phishing_probability = confidence
            predicted_label = 1
        elif result.classification == Classification.LEGITIMATE:
            phishing_probability = max(0.0, 1.0 - confidence)
            predicted_label = 0
        else:
            # SUSPICIOUS — park inside the review band so the binary label
            # is overridden to REVIEW by EmailAnalyseService._map_label.
            phishing_probability = (_REVIEW_LOW + _REVIEW_HIGH) / 2
            predicted_label = 1 if phishing_probability >= _DECISION_THRESHOLD else 0

        return DetectorPrediction(
            phishing_probability=phishing_probability,
            predicted_label=predicted_label,
            threshold_used=_DECISION_THRESHOLD,
            model_version=result.model_name or inference_config.groq.model,
            review_low=_REVIEW_LOW,
            review_high=_REVIEW_HIGH,
            message=result.reasoning or None,
        )
