"""Detector lookup for the extension surface.

The Chrome extension needs a single ``sender/subject/body`` → verdict
request-response call. The full ``inference`` module is a multi-stage
DB-polled pipeline (Groq + Gemini + link scraping) that cannot serve that
shape end-to-end, but its Stage-1 classifier can — a detector adapter in
``src/core`` wires Stage-1 to ``app.state.detector`` at startup.

BACKEND_CONTRACT §5.5.3 and STANDARD §16 allow the extension surface to
return **503 SERVICE_UNAVAILABLE** while no detector is wired. This module
centralises that lookup:

- If ``app.state.detector`` is set and exposes ``predict(sender, subject,
  body) -> Prediction``, callers use it.
- Otherwise callers raise ``ServiceUnavailableException`` with code
  ``SERVICE_UNAVAILABLE``.

The shape the detector must return is intentionally minimal — see
``DetectorPrediction``. Backend 2 can swap in a different detector later
without changing the controller or DTO code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from starlette.requests import Request

from src.shared.exceptions import ServiceUnavailableException
from src.shared.responses import ErrorDetail


@dataclass(frozen=True)
class EmailAuth:
    """DKIM / SPF / DMARC results the receiving mail server reported.

    Passed through from ``AnalyseEmailRequest.headers.authResults`` to
    the detector so the underlying model can weigh cryptographic sender
    verification. None for any field means the extension did not report
    that signal for this email.
    """

    dkim: str | None = None
    spf: str | None = None
    dmarc: str | None = None

    def is_empty(self) -> bool:
        return not (self.dkim or self.spf or self.dmarc)


@dataclass(frozen=True)
class DetectorPrediction:
    # Raw phishing probability in [0.0, 1.0]. Legitimate = 1 - phishing.
    phishing_probability: float
    # Binary label: 1 = phishing, 0 = legitimate. Review zone is decided by
    # threshold_used — the detector itself only needs to classify.
    predicted_label: int
    # Decision threshold applied (usually ``inference.decision_threshold``).
    threshold_used: float
    # Model version string — echoed in the response and used by the
    # extension's cache to invalidate old entries.
    model_version: str
    # Optional review band for confidence_zone == REVIEW mapping.
    review_low: float | None = None
    review_high: float | None = None
    # Optional user-facing explanation — verbatim, no HTML.
    message: str | None = None


class Detector(Protocol):
    async def predict(
        self,
        *,
        sender: str,
        subject: str,
        body: str,
        auth: EmailAuth | None = None,
    ) -> DetectorPrediction: ...


def _unavailable() -> ServiceUnavailableException:
    return ServiceUnavailableException(
        message="The analysis service is temporarily unavailable",
        error_detail=ErrorDetail(
            title="Service Unavailable",
            code="SERVICE_UNAVAILABLE",
            status=503,
            details=["Detector is not loaded"],
        ),
    )


def get_detector(request: Request) -> Detector:
    """Return the active detector or raise 503.

    Callers must treat the returned object as opaque — ``predict(...)`` is
    the only method guaranteed by the extension surface.
    """
    detector = getattr(request.app.state, "detector", None)
    if detector is None:
        raise _unavailable()
    if not hasattr(detector, "predict"):
        raise _unavailable()
    return detector
