from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from src.modules.inference.domain.models.email import Email
from src.modules.inference.domain.models.enums import (
    Classification,
    OverrideTrigger,
    PipelineStage,
    PipelineStatus,
    ResolveStatus,
    RiskLevel,
    ScrapeStatus,
)
from src.modules.inference.domain.models.link import Link
from src.modules.inference.domain.models.page_analysis import PageAnalysis
from src.modules.inference.domain.services.inference_stats_service import (
    ApiCallsEstimated,
    BrandCount,
    ClassificationCounts,
    ModelCount,
    ModelUsage,
    PipelineStatusCounts,
    SummaryStats,
    TriggerCount,
    VerdictBucket,
)


# ── Submit responses ─────────────────────────────────────────────────────


class SubmitEmailResponse(BaseModel):
    email_id: UUID = Field(alias="emailId")
    pipeline_status: PipelineStatus = Field(alias="pipelineStatus")
    received_at: datetime = Field(alias="receivedAt")
    submitted_at: datetime = Field(alias="submittedAt")

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_email(email: Email) -> "SubmitEmailResponse":
        return SubmitEmailResponse(
            emailId=email.id,
            pipelineStatus=email.pipeline_status,
            receivedAt=email.received_at,
            submittedAt=email.created_at,
        )


class BatchSubmittedItem(BaseModel):
    email_id: UUID = Field(alias="emailId")
    pipeline_status: PipelineStatus = Field(alias="pipelineStatus")

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_email(email: Email) -> "BatchSubmittedItem":
        return BatchSubmittedItem(
            emailId=email.id,
            pipelineStatus=email.pipeline_status,
        )


class BatchRejectedItem(BaseModel):
    index: int
    reason: str

    class Config:
        populate_by_name = True


class SubmitEmailBatchResponse(BaseModel):
    submitted: List[BatchSubmittedItem]
    rejected: List[BatchRejectedItem]

    class Config:
        populate_by_name = True

    @staticmethod
    def build(
        submitted: List[Email],
        rejected: List["BatchRejectedItem"],
    ) -> "SubmitEmailBatchResponse":
        return SubmitEmailBatchResponse(
            submitted=[BatchSubmittedItem.from_email(e) for e in submitted],
            rejected=list(rejected),
        )


# ── Page analysis ────────────────────────────────────────────────────────


class PageAnalysisResponse(BaseModel):
    id: UUID
    page_title: Optional[str] = Field(default=None, alias="pageTitle")
    meta_description: Optional[str] = Field(
        default=None, alias="metaDescription"
    )
    has_login_form: bool = Field(alias="hasLoginForm")
    has_payment_form: bool = Field(alias="hasPaymentForm")
    external_domains: Optional[List[str]] = Field(
        default=None, alias="externalDomains"
    )
    favicon_matches_domain: Optional[bool] = Field(
        default=None, alias="faviconMatchesDomain"
    )

    page_purpose: Optional[str] = Field(default=None, alias="pagePurpose")
    impersonates_brand: Optional[str] = Field(
        default=None, alias="impersonatesBrand"
    )
    requests_credentials: bool = Field(alias="requestsCredentials")
    requests_payment: bool = Field(alias="requestsPayment")
    risk_level: Optional[RiskLevel] = Field(default=None, alias="riskLevel")
    risk_confidence: Optional[float] = Field(
        default=None, alias="riskConfidence"
    )
    risk_reasons: Optional[List[str]] = Field(default=None, alias="riskReasons")
    summary: Optional[str] = None

    scrape_status: Optional[ScrapeStatus] = Field(
        default=None, alias="scrapeStatus"
    )
    llm_model: Optional[str] = Field(default=None, alias="llmModel")
    analysed_at: Optional[datetime] = Field(default=None, alias="analysedAt")
    created_at: datetime = Field(alias="createdAt")

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_page_analysis(page: PageAnalysis) -> "PageAnalysisResponse":
        return PageAnalysisResponse(
            id=page.id,
            pageTitle=page.page_title,
            metaDescription=page.meta_description,
            hasLoginForm=page.has_login_form,
            hasPaymentForm=page.has_payment_form,
            externalDomains=page.external_domains,
            faviconMatchesDomain=page.favicon_matches_domain,
            pagePurpose=page.page_purpose,
            impersonatesBrand=page.impersonates_brand,
            requestsCredentials=page.requests_credentials,
            requestsPayment=page.requests_payment,
            riskLevel=page.risk_level,
            riskConfidence=page.risk_confidence,
            riskReasons=page.risk_reasons,
            summary=page.summary,
            scrapeStatus=page.scrape_status,
            llmModel=page.llm_model,
            analysedAt=page.analysed_at,
            createdAt=page.created_at,
        )


# ── Link responses ───────────────────────────────────────────────────────


class LinkResponse(BaseModel):
    id: UUID
    email_id: UUID = Field(alias="emailId")
    original_url: str = Field(alias="originalUrl")
    is_shortened: bool = Field(alias="isShortened")
    shortener: Optional[str] = None
    anchor_context: Optional[str] = Field(default=None, alias="anchorContext")
    resolved_url: Optional[str] = Field(default=None, alias="resolvedUrl")
    resolve_status: Optional[ResolveStatus] = Field(
        default=None, alias="resolveStatus"
    )
    redirect_hops: int = Field(alias="redirectHops")
    intermediate_domains: Optional[List[str]] = Field(
        default=None, alias="intermediateDomains"
    )
    http_status: Optional[int] = Field(default=None, alias="httpStatus")
    resolved_at: Optional[datetime] = Field(default=None, alias="resolvedAt")
    created_at: datetime = Field(alias="createdAt")

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_link(link: Link) -> "LinkResponse":
        return LinkResponse(
            id=link.id,
            emailId=link.email_id,
            originalUrl=link.original_url,
            isShortened=link.is_shortened,
            shortener=link.shortener,
            anchorContext=link.anchor_context,
            resolvedUrl=link.resolved_url,
            resolveStatus=link.resolve_status,
            redirectHops=link.redirect_hops,
            intermediateDomains=link.intermediate_domains,
            httpStatus=link.http_status,
            resolvedAt=link.resolved_at,
            createdAt=link.created_at,
        )


class LinkWithPageResponse(BaseModel):
    id: UUID
    email_id: UUID = Field(alias="emailId")
    original_url: str = Field(alias="originalUrl")
    is_shortened: bool = Field(alias="isShortened")
    shortener: Optional[str] = None
    anchor_context: Optional[str] = Field(default=None, alias="anchorContext")
    resolved_url: Optional[str] = Field(default=None, alias="resolvedUrl")
    resolve_status: Optional[ResolveStatus] = Field(
        default=None, alias="resolveStatus"
    )
    redirect_hops: int = Field(alias="redirectHops")
    intermediate_domains: Optional[List[str]] = Field(
        default=None, alias="intermediateDomains"
    )
    http_status: Optional[int] = Field(default=None, alias="httpStatus")
    resolved_at: Optional[datetime] = Field(default=None, alias="resolvedAt")
    created_at: datetime = Field(alias="createdAt")
    page_analysis: Optional[PageAnalysisResponse] = Field(
        default=None, alias="pageAnalysis"
    )

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_link(link: Link) -> "LinkWithPageResponse":
        return LinkWithPageResponse(
            id=link.id,
            emailId=link.email_id,
            originalUrl=link.original_url,
            isShortened=link.is_shortened,
            shortener=link.shortener,
            anchorContext=link.anchor_context,
            resolvedUrl=link.resolved_url,
            resolveStatus=link.resolve_status,
            redirectHops=link.redirect_hops,
            intermediateDomains=link.intermediate_domains,
            httpStatus=link.http_status,
            resolvedAt=link.resolved_at,
            createdAt=link.created_at,
            pageAnalysis=(
                PageAnalysisResponse.from_page_analysis(link.page_analysis)
                if link.page_analysis is not None
                else None
            ),
        )


# ── Email history / detail ───────────────────────────────────────────────


class EmailSummaryResponse(BaseModel):
    id: UUID
    sender: str
    subject: str
    received_at: datetime = Field(alias="receivedAt")
    classification: Optional[Classification] = None
    confidence: Optional[float] = None
    final_classification: Optional[Classification] = Field(
        default=None, alias="finalClassification"
    )
    final_confidence: Optional[float] = Field(
        default=None, alias="finalConfidence"
    )
    override_trigger: Optional[OverrideTrigger] = Field(
        default=None, alias="overrideTrigger"
    )
    link_count: int = Field(alias="linkCount")
    pipeline_status: PipelineStatus = Field(alias="pipelineStatus")
    finalised_at: Optional[datetime] = Field(default=None, alias="finalisedAt")
    submitted_by_install: Optional[UUID] = Field(
        default=None, alias="submittedByInstall"
    )

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_email(email: Email) -> "EmailSummaryResponse":
        return EmailSummaryResponse(
            id=email.id,
            sender=email.sender,
            subject=email.subject,
            receivedAt=email.received_at,
            classification=email.classification,
            confidence=email.confidence,
            finalClassification=email.final_classification,
            finalConfidence=email.final_confidence,
            overrideTrigger=email.override_trigger,
            linkCount=email.link_count,
            pipelineStatus=email.pipeline_status,
            finalisedAt=email.finalised_at,
            submittedByInstall=email.submitted_by_install,
        )


class EmailDetailResponse(BaseModel):
    id: UUID
    sender: str
    subject: str
    body_hash: str = Field(alias="bodyHash")
    received_at: datetime = Field(alias="receivedAt")
    processed_at: Optional[datetime] = Field(default=None, alias="processedAt")
    finalised_at: Optional[datetime] = Field(default=None, alias="finalisedAt")

    classification: Optional[Classification] = None
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    risk_factors: Optional[List[str]] = Field(default=None, alias="riskFactors")
    llm_model: Optional[str] = Field(default=None, alias="llmModel")

    link_count: int = Field(alias="linkCount")
    final_classification: Optional[Classification] = Field(
        default=None, alias="finalClassification"
    )
    final_confidence: Optional[float] = Field(
        default=None, alias="finalConfidence"
    )
    override_trigger: Optional[OverrideTrigger] = Field(
        default=None, alias="overrideTrigger"
    )
    aggregation_note: Optional[str] = Field(
        default=None, alias="aggregationNote"
    )

    pipeline_status: PipelineStatus = Field(alias="pipelineStatus")
    pipeline_stage: PipelineStage = Field(alias="pipelineStage")
    pipeline_error: Optional[str] = Field(default=None, alias="pipelineError")

    manual_review_flag: bool = Field(alias="manualReviewFlag")
    manual_review_note: Optional[str] = Field(
        default=None, alias="manualReviewNote"
    )
    manual_review_by: Optional[UUID] = Field(
        default=None, alias="manualReviewBy"
    )
    manual_review_at: Optional[datetime] = Field(
        default=None, alias="manualReviewAt"
    )
    manual_override_classification: Optional[Classification] = Field(
        default=None, alias="manualOverrideClassification"
    )

    submitted_by: Optional[UUID] = Field(default=None, alias="submittedBy")
    submitted_by_install: Optional[UUID] = Field(
        default=None, alias="submittedByInstall"
    )
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")

    links: List[LinkWithPageResponse]

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_email(email: Email) -> "EmailDetailResponse":
        return EmailDetailResponse(
            id=email.id,
            sender=email.sender,
            subject=email.subject,
            bodyHash=email.body_hash,
            receivedAt=email.received_at,
            processedAt=email.processed_at,
            finalisedAt=email.finalised_at,
            classification=email.classification,
            confidence=email.confidence,
            reasoning=email.reasoning,
            riskFactors=email.risk_factors,
            llmModel=email.llm_model,
            linkCount=email.link_count,
            finalClassification=email.final_classification,
            finalConfidence=email.final_confidence,
            overrideTrigger=email.override_trigger,
            aggregationNote=email.aggregation_note,
            pipelineStatus=email.pipeline_status,
            pipelineStage=email.pipeline_stage,
            pipelineError=email.pipeline_error,
            manualReviewFlag=email.manual_review_flag,
            manualReviewNote=email.manual_review_note,
            manualReviewBy=email.manual_review_by,
            manualReviewAt=email.manual_review_at,
            manualOverrideClassification=email.manual_override_classification,
            submittedBy=email.submitted_by,
            submittedByInstall=email.submitted_by_install,
            createdAt=email.created_at,
            updatedAt=email.updated_at,
            links=[LinkWithPageResponse.from_link(l) for l in email.links],
        )


class EmailLinksResponse(BaseModel):
    email_id: UUID = Field(alias="emailId")
    links: List[LinkResponse]

    class Config:
        populate_by_name = True

    @staticmethod
    def from_email(email: Email) -> "EmailLinksResponse":
        return EmailLinksResponse(
            emailId=email.id,
            links=[LinkResponse.from_link(l) for l in email.links],
        )


# ── Status poll ──────────────────────────────────────────────────────────


class EmailStatusResponse(BaseModel):
    email_id: UUID = Field(alias="emailId")
    pipeline_status: PipelineStatus = Field(alias="pipelineStatus")
    stage: PipelineStage
    started_at: Optional[datetime] = Field(default=None, alias="startedAt")
    finalised_at: Optional[datetime] = Field(default=None, alias="finalisedAt")
    error: Optional[str] = None

    class Config:
        populate_by_name = True
        from_attributes = True

    @staticmethod
    def from_email(email: Email) -> "EmailStatusResponse":
        return EmailStatusResponse(
            emailId=email.id,
            pipelineStatus=email.pipeline_status,
            stage=email.pipeline_stage,
            startedAt=email.processed_at,
            finalisedAt=email.finalised_at,
            error=email.pipeline_error,
        )


# ── Stats responses ──────────────────────────────────────────────────────


class ClassificationCountsResponse(BaseModel):
    phishing: int
    suspicious: int
    legitimate: int
    pending: int

    class Config:
        populate_by_name = True

    @staticmethod
    def from_counts(
        counts: ClassificationCounts,
    ) -> "ClassificationCountsResponse":
        return ClassificationCountsResponse(
            phishing=counts.phishing,
            suspicious=counts.suspicious,
            legitimate=counts.legitimate,
            pending=counts.pending,
        )


class PipelineStatusCountsResponse(BaseModel):
    pending: int
    running: int
    complete: int
    failed: int

    class Config:
        populate_by_name = True

    @staticmethod
    def from_counts(
        counts: PipelineStatusCounts,
    ) -> "PipelineStatusCountsResponse":
        return PipelineStatusCountsResponse(
            pending=counts.pending,
            running=counts.running,
            complete=counts.complete,
            failed=counts.failed,
        )


class SummaryStatsResponse(BaseModel):
    total: int
    by_classification: ClassificationCountsResponse = Field(
        alias="byClassification"
    )
    by_pipeline_status: PipelineStatusCountsResponse = Field(
        alias="byPipelineStatus"
    )
    early_exit_count: int = Field(alias="earlyExitCount")
    escalation_count: int = Field(alias="escalationCount")
    average_confidence: Optional[float] = Field(
        default=None, alias="averageConfidence"
    )
    window_start: Optional[datetime] = Field(default=None, alias="windowStart")
    window_end: Optional[datetime] = Field(default=None, alias="windowEnd")

    class Config:
        populate_by_name = True

    @staticmethod
    def from_summary(s: SummaryStats) -> "SummaryStatsResponse":
        return SummaryStatsResponse(
            total=s.total,
            byClassification=ClassificationCountsResponse.from_counts(
                s.by_classification
            ),
            byPipelineStatus=PipelineStatusCountsResponse.from_counts(
                s.by_pipeline_status
            ),
            earlyExitCount=s.early_exit_count,
            escalationCount=s.escalation_count,
            averageConfidence=s.average_confidence,
            windowStart=s.window_start,
            windowEnd=s.window_end,
        )


class VerdictBucketResponse(BaseModel):
    bucket: datetime
    phishing: int
    suspicious: int
    legitimate: int

    class Config:
        populate_by_name = True

    @staticmethod
    def from_bucket(b: VerdictBucket) -> "VerdictBucketResponse":
        return VerdictBucketResponse(
            bucket=b.bucket,
            phishing=b.phishing,
            suspicious=b.suspicious,
            legitimate=b.legitimate,
        )


class TriggerCountResponse(BaseModel):
    trigger: OverrideTrigger
    count: int

    class Config:
        populate_by_name = True

    @staticmethod
    def from_trigger(t: TriggerCount) -> "TriggerCountResponse":
        return TriggerCountResponse(trigger=t.trigger, count=t.count)


class ModelCountResponse(BaseModel):
    model: str
    count: int

    class Config:
        populate_by_name = True

    @staticmethod
    def from_model_count(m: ModelCount) -> "ModelCountResponse":
        return ModelCountResponse(model=m.model, count=m.count)


class ApiCallsEstimatedResponse(BaseModel):
    groq: int
    gemini: int
    total_saved: int = Field(alias="totalSaved")

    class Config:
        populate_by_name = True

    @staticmethod
    def from_estimated(e: ApiCallsEstimated) -> "ApiCallsEstimatedResponse":
        return ApiCallsEstimatedResponse(
            groq=e.groq, gemini=e.gemini, totalSaved=e.total_saved
        )


class ModelUsageResponse(BaseModel):
    stage1: List[ModelCountResponse]
    stage3: List[ModelCountResponse]
    api_calls_estimated: ApiCallsEstimatedResponse = Field(
        alias="apiCallsEstimated"
    )

    class Config:
        populate_by_name = True

    @staticmethod
    def from_usage(u: ModelUsage) -> "ModelUsageResponse":
        return ModelUsageResponse(
            stage1=[ModelCountResponse.from_model_count(m) for m in u.stage1],
            stage3=[ModelCountResponse.from_model_count(m) for m in u.stage3],
            apiCallsEstimated=ApiCallsEstimatedResponse.from_estimated(
                u.api_calls_estimated
            ),
        )


class BrandCountResponse(BaseModel):
    brand: str
    count: int

    class Config:
        populate_by_name = True

    @staticmethod
    def from_brand(b: BrandCount) -> "BrandCountResponse":
        return BrandCountResponse(brand=b.brand, count=b.count)
