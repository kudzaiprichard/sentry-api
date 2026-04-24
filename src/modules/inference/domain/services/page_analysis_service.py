from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from src.configs import inference
from src.modules.inference.domain.models.enums import RiskLevel
from src.modules.inference.internal import gemini_client, prompts
from src.shared.exceptions import ServiceUnavailableException
from src.shared.responses.api_response import ErrorDetail


@dataclass
class PageAnalysisResult:
    page_index: int
    url: str
    page_purpose: Optional[str] = None
    impersonates_brand: Optional[str] = None
    requests_credentials: bool = False
    requests_payment: bool = False
    risk_level: Optional[RiskLevel] = None
    risk_confidence: Optional[float] = None
    risk_reasons: list[str] = field(default_factory=list)
    summary: Optional[str] = None
    model_name: str = ""


def _malformed(reason: str) -> ServiceUnavailableException:
    return ServiceUnavailableException(
        message="The page-analysis service returned an invalid response",
        error_detail=ErrorDetail(
            title="LLM Unavailable",
            code="LLM_UNAVAILABLE",
            status=503,
            details=[reason],
        ),
    )


def _coerce_risk(value) -> Optional[RiskLevel]:
    if value is None:
        return None
    try:
        return RiskLevel(str(value).lower())
    except ValueError:
        return None


class PageAnalysisService:
    """Stage 3 — one batched Gemini call for all scraped pages.

    Input is a sequence of dict-like page records with at minimum keys
    `resolved_url` (or `url`), `page_title`, `meta_description`,
    `has_login_form`, `has_payment_form`, `external_domains`, `content`.

    Output preserves input order: results[i] corresponds to pages[i].
    Empty input returns [] without making an API call.
    """

    def __init__(self, client_callable=None):
        self._client_callable = client_callable or gemini_client.generate_json

    async def analyse_batch(
        self, pages: Sequence[Mapping]
    ) -> list[PageAnalysisResult]:
        if not pages:
            return []

        prompt = prompts.format_stage_3(pages)
        raw = await self._client_callable(prompt=prompt)

        if not isinstance(raw, list):
            raise _malformed(
                f"Stage-3 response not a JSON array: {type(raw).__name__}"
            )

        by_index: dict[int, Mapping] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item.get("page_index"))
            except (TypeError, ValueError):
                continue
            by_index[idx] = item

        results: list[PageAnalysisResult] = []
        for i, page in enumerate(pages, start=1):
            item = by_index.get(i)
            url = (
                page.get("resolved_url")
                or page.get("url")
                or (item.get("url") if item else "")
            )
            if item is None:
                results.append(
                    PageAnalysisResult(
                        page_index=i,
                        url=url or "",
                        model_name=inference.gemini.model,
                    )
                )
                continue

            results.append(
                PageAnalysisResult(
                    page_index=i,
                    url=item.get("url") or url or "",
                    page_purpose=(
                        str(item["page_purpose"])
                        if item.get("page_purpose")
                        else None
                    ),
                    impersonates_brand=(
                        str(item["impersonates_brand"])
                        if item.get("impersonates_brand")
                        else None
                    ),
                    requests_credentials=bool(item.get("requests_credentials")),
                    requests_payment=bool(item.get("requests_payment")),
                    risk_level=_coerce_risk(item.get("risk_level")),
                    risk_confidence=(
                        float(item["risk_confidence"])
                        if isinstance(
                            item.get("risk_confidence"), (int, float)
                        )
                        else None
                    ),
                    risk_reasons=[
                        str(r) for r in (item.get("risk_reasons") or [])
                    ],
                    summary=(
                        str(item["summary"]) if item.get("summary") else None
                    ),
                    model_name=inference.gemini.model,
                )
            )

        return results
