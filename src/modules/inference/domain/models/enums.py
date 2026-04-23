import enum


class Classification(str, enum.Enum):
    PHISHING = "phishing"
    SUSPICIOUS = "suspicious"
    LEGITIMATE = "legitimate"


class OverrideTrigger(str, enum.Enum):
    PAGE_HIGH_RISK = "page_high_risk"
    PAGE_MEDIUM_RISK = "page_medium_risk"
    ALL_LOW = "all_low"
    ALL_FAILED = "all_failed"
    EARLY_EXIT = "early_exit"


class ResolveStatus(str, enum.Enum):
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"


class ScrapeStatus(str, enum.Enum):
    SUCCESS = "success"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"
    JS_REQUIRED = "js_required"


class RiskLevel(str, enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PipelineStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"


class PipelineStage(str, enum.Enum):
    QUEUED = "queued"
    CLASSIFICATION = "classification"
    LINK_RESOLUTION = "link_resolution"
    PAGE_ANALYSIS = "page_analysis"
    AGGREGATION = "aggregation"
    DONE = "done"
