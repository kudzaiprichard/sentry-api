from dataclasses import dataclass
from typing import Optional, Sequence
from urllib.parse import urlparse

from src.modules.inference.domain.models.enums import (
    Classification,
    OverrideTrigger,
    RiskLevel,
)
from src.modules.inference.domain.services.page_analysis_service import (
    PageAnalysisResult,
)


@dataclass
class AggregationEmail:
    classification: Classification
    confidence: float
    link_count: int = 0


@dataclass
class AggregationOutcome:
    final_classification: Classification
    final_confidence: float
    aggregation_note: str
    override_trigger: OverrideTrigger


def _host(url: Optional[str]) -> str:
    if not url:
        return ""
    try:
        h = urlparse(url).hostname or ""
    except Exception:
        return ""
    h = h.lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def _conf(v: Optional[float]) -> float:
    return float(v) if v is not None else 0.0


def _summarise_reasons(page: PageAnalysisResult) -> str:
    if page.risk_reasons:
        return ", ".join(page.risk_reasons)
    if page.summary:
        return page.summary
    return "no reasons reported"


class AggregationService:
    """Stage 4 — pure-function verdict aggregation.

    Applies the rules from `phishing_detection_design.md` §Stage 4 in order
    and returns the final verdict + a human-readable note.

    The note strings are templated here so this is the only place those
    sentences live.
    """

    def finalise(
        self,
        email: AggregationEmail,
        page_results: Sequence[PageAnalysisResult],
        *,
        early_exit: bool = False,
    ) -> AggregationOutcome:
        # Rule 1 — early exit: caller bypassed Stages 2+3 because the email
        # itself was high-confidence phishing.
        if early_exit:
            return AggregationOutcome(
                final_classification=Classification.PHISHING,
                final_confidence=email.confidence,
                aggregation_note=(
                    f"High confidence phishing ({email.confidence:.2f}). "
                    f"Page analysis skipped — early exit rule triggered."
                ),
                override_trigger=OverrideTrigger.EARLY_EXIT,
            )

        # Rule 5 — links existed but every one failed to resolve / scrape /
        # analyse. We can't verify the original verdict.
        if email.link_count > 0 and not page_results:
            return AggregationOutcome(
                final_classification=email.classification,
                final_confidence=email.confidence,
                aggregation_note=(
                    f"All {email.link_count} links failed to resolve "
                    f"(status: blocked). Classification unverified — "
                    f"manual review recommended."
                ),
                override_trigger=OverrideTrigger.ALL_FAILED,
            )

        # Rule 2 — any high-risk page escalates to phishing.
        high = [p for p in page_results if p.risk_level == RiskLevel.HIGH]
        if high:
            best_conf = max(_conf(p.risk_confidence) for p in high)
            if len(high) == 1:
                p = high[0]
                note = (
                    f"Original: {email.classification.value} "
                    f"({email.confidence:.2f}). "
                    f"Escalated to phishing — page {p.page_index} "
                    f"({_host(p.url)}) flagged high risk. "
                    f"Reasons: {_summarise_reasons(p)}"
                )
            else:
                lines = [
                    (
                        f"Original: {email.classification.value} "
                        f"({email.confidence:.2f}). "
                        f"Escalated to phishing — {len(high)} pages "
                        f"flagged high risk:"
                    )
                ]
                for p in high:
                    lines.append(
                        f"  page {p.page_index} ({_host(p.url)}): "
                        f"{_summarise_reasons(p)}"
                    )
                note = "\n".join(lines)
            return AggregationOutcome(
                final_classification=Classification.PHISHING,
                final_confidence=best_conf,
                aggregation_note=note,
                override_trigger=OverrideTrigger.PAGE_HIGH_RISK,
            )

        # Rule 3 — any medium-risk page AND original was legitimate → suspicious.
        medium = [p for p in page_results if p.risk_level == RiskLevel.MEDIUM]
        if medium and email.classification == Classification.LEGITIMATE:
            p = medium[0]
            best_conf = max(_conf(x.risk_confidence) for x in medium)
            note = (
                f"Original: legitimate ({email.confidence:.2f}). "
                f"Escalated to suspicious — page {p.page_index} "
                f"({_host(p.url)}) flagged medium risk. "
                f"Reasons: {_summarise_reasons(p)}"
            )
            return AggregationOutcome(
                final_classification=Classification.SUSPICIOUS,
                final_confidence=best_conf,
                aggregation_note=note,
                override_trigger=OverrideTrigger.PAGE_MEDIUM_RISK,
            )

        # Rule 4 — no escalation triggered, keep original.
        note = (
            f"All {len(page_results)} pages low risk. "
            f"Original classification retained: "
            f"{email.classification.value} ({email.confidence:.2f})"
        )
        return AggregationOutcome(
            final_classification=email.classification,
            final_confidence=email.confidence,
            aggregation_note=note,
            override_trigger=OverrideTrigger.ALL_LOW,
        )
