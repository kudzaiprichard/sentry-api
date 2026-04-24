from dataclasses import dataclass, field
from typing import Optional

from src.configs import inference
from src.modules.inference.domain.models.enums import Classification
from src.modules.inference.internal import groq_client, prompts
from src.shared.exceptions import ServiceUnavailableException
from src.shared.responses.api_response import ErrorDetail


@dataclass
class ExtractedLink:
    url: str
    is_shortened: bool = False
    shortener_service: Optional[str] = None
    context: Optional[str] = None


@dataclass(frozen=True)
class AuthSignals:
    """DKIM / SPF / DMARC results reported by the receiving mail server.

    Values are the raw status strings (e.g. "pass", "fail", "neutral",
    "softfail") — the prompt surfaces them verbatim so the LLM can weigh
    them. None means the caller did not supply that signal.
    """

    dkim: Optional[str] = None
    spf: Optional[str] = None
    dmarc: Optional[str] = None


@dataclass
class EmailClassificationResult:
    classification: Classification
    confidence: float
    reasoning: str
    risk_factors: list[str] = field(default_factory=list)
    links: list[ExtractedLink] = field(default_factory=list)
    model_name: str = ""


def _malformed(reason: str) -> ServiceUnavailableException:
    return ServiceUnavailableException(
        message="The classification service returned an invalid response",
        error_detail=ErrorDetail(
            title="LLM Unavailable",
            code="LLM_UNAVAILABLE",
            status=503,
            details=[reason],
        ),
    )


class EmailClassificationService:
    """Stage 1 — call Groq, parse JSON, return a typed result.

    No DB access. Injectable client lets tests substitute a mock.
    """

    def __init__(self, client_callable=None):
        self._client_callable = client_callable or groq_client.chat_json

    async def classify(
        self,
        sender: str,
        subject: str,
        body: str,
        *,
        auth_signals: Optional[AuthSignals] = None,
    ) -> EmailClassificationResult:
        prompt = prompts.format_stage_1(
            sender,
            subject,
            body,
            dkim=auth_signals.dkim if auth_signals else None,
            spf=auth_signals.spf if auth_signals else None,
            dmarc=auth_signals.dmarc if auth_signals else None,
        )
        raw = await self._client_callable(
            messages=[{"role": "user", "content": prompt}]
        )

        if not isinstance(raw, dict):
            raise _malformed(f"Stage-1 response not an object: {type(raw).__name__}")

        try:
            classification = Classification(str(raw["classification"]).lower())
            confidence = float(raw["confidence"])
        except (KeyError, ValueError, TypeError) as e:
            raise _malformed(f"Stage-1 missing/invalid required fields: {e}")

        reasoning = str(raw.get("reasoning") or "")
        risk_factors = [str(x) for x in (raw.get("risk_factors") or [])]

        links: list[ExtractedLink] = []
        for item in raw.get("links") or []:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            links.append(
                ExtractedLink(
                    url=str(item["url"]),
                    is_shortened=bool(item.get("is_shortened", False)),
                    shortener_service=(
                        str(item["shortener_service"])
                        if item.get("shortener_service")
                        else None
                    ),
                    context=(str(item["context"]) if item.get("context") else None),
                )
            )

        return EmailClassificationResult(
            classification=classification,
            confidence=confidence,
            reasoning=reasoning,
            risk_factors=risk_factors,
            links=links,
            model_name=inference.groq.model,
        )
