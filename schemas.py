# schemas.py - Enhanced with new item creation schemas
import json

from pydantic import BaseModel, Field, field_validator, validator
from typing import Optional, List, Any, Dict
from datetime import datetime
from enum import Enum


# Enums
class JobStatus(str, Enum):
    PROCESSING = "PROCESSING"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


class PeriodType(str, Enum):
    INSTANT = "instant"
    DURATION = "duration"


class MappingSupervisorReviewStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SupervisorDecision(str, Enum):
    AGREE = "agree"
    DISAGREE = "disagree"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class SupervisorRiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SupervisorRecommendedAction(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    KEEP_FOR_HUMAN_REVIEW = "keep_for_human_review"
    REQUEST_BETTER_CANDIDATE = "request_better_candidate"


class SupervisorConfidenceAdjustment(str, Enum):
    INCREASE = "increase"
    KEEP = "keep"
    DECREASE = "decrease"


class MappingSupervisorReviewSource(str, Enum):
    MOCK = "mock"
    LIVE = "live"
    IMPORTED = "imported"
    MANUAL = "manual"


class SupervisorReviewRunMode(str, Enum):
    MOCK = "mock"
    LIVE = "live"


class UserResponse(BaseModel):
    id: int
    email: str
    is_admin: bool = False
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Valid email is required")
        local_part, domain = normalized.rsplit("@", 1)
        if not local_part or "." not in domain:
            raise ValueError("Valid email is required")
        return normalized


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        return RegisterRequest.normalize_and_validate_email(value)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)


class DeleteAccountRequest(BaseModel):
    email_confirmation: str = Field(..., min_length=3, max_length=320)
    current_password: str = Field(..., min_length=1, max_length=128)
    confirm_password: str = Field(..., min_length=1, max_length=128)

    @field_validator("email_confirmation")
    @classmethod
    def normalize_email_confirmation(cls, value: str) -> str:
        return LoginRequest.normalize_and_validate_email(value)


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class ChangePasswordResponse(BaseModel):
    success: bool
    message: str


class DeleteAccountResponse(BaseModel):
    success: bool
    message: str
    deleted_user: bool
    deleted_jobs_count: int
    deleted_pages_count: int
    deleted_extracted_items_count: int
    deleted_files_count: int
    skipped_missing_files_count: int


class LogoutResponse(BaseModel):
    success: bool
    message: str


class AdminCreateUserRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_and_validate_email(cls, value: str) -> str:
        return RegisterRequest.normalize_and_validate_email(value)


class AdminChangeUserPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)


# Base schemas
class TaxonomyTagBase(BaseModel):
    label: str = Field(..., min_length=1, max_length=555)
    xbrl_tag: str = Field(..., min_length=1, max_length=555)
    namespace: str = Field(..., min_length=1, max_length=50)
    period_type: PeriodType = PeriodType.DURATION


class TaxonomyTagCreate(TaxonomyTagBase):
    pass


class TaxonomyTagResponse(TaxonomyTagBase):
    id: int

    class Config:
        from_attributes = True


# Filing Job schemas
class FilingJobCreate(BaseModel):
    company_name: str = Field(..., min_length=3, max_length=255)
    registration_number: Optional[str] = Field(None, max_length=100)
    financial_year_end: datetime


class FilingJobUpdate(BaseModel):
    company_name: Optional[str] = Field(None, min_length=3, max_length=255)
    registration_number: Optional[str] = Field(None, max_length=100)
    financial_year_end: Optional[datetime] = None
    status: Optional[JobStatus] = None
    directors_report_html: Optional[str] = None


class FilingJobResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    company_name: str
    registration_number: Optional[str]
    financial_year_end: datetime
    source_pdf_path: str
    status: JobStatus
    progress: Optional[int] = None
    error_message: Optional[str] = None
    uploaded_at: datetime
    directors_report_html: Optional[str]

    class Config:
        from_attributes = True


class MappingSupervisorReviewCreateInternal(BaseModel):
    """Internal persistence shape for advisory Supervisor review rows."""

    user_id: Optional[int] = None
    job_id: int
    extracted_data_item_id: Optional[str] = None
    llm_mapping_suggestion_id: Optional[str] = None
    mapper_selected_template_field_id: Optional[str] = None
    mapper_selected_qname: Optional[str] = None
    mapper_confidence: Optional[float] = Field(None, ge=0, le=1)
    mapper_status: Optional[str] = Field(None, max_length=40)
    review_status: MappingSupervisorReviewStatus = MappingSupervisorReviewStatus.PENDING
    supervisor_prompt_version: Optional[str] = Field(None, max_length=80)
    supervisor_schema_version: Optional[str] = Field(None, max_length=80)
    supervisor_payload_hash: Optional[str] = Field(None, min_length=64, max_length=64)
    source: MappingSupervisorReviewSource = MappingSupervisorReviewSource.MOCK


class MappingSupervisorReviewUpdateInternal(BaseModel):
    """Internal update shape for completed/failed/skipped Supervisor review rows."""

    review_status: Optional[MappingSupervisorReviewStatus] = None
    supervisor_decision: Optional[SupervisorDecision] = None
    supervisor_risk_level: Optional[SupervisorRiskLevel] = None
    supervisor_recommended_action: Optional[SupervisorRecommendedAction] = None
    supervisor_safe_to_accept: Optional[bool] = None
    calibrated_safe_to_accept: Optional[bool] = None
    supervisor_confidence_adjustment: Optional[SupervisorConfidenceAdjustment] = None
    supervisor_issues: Optional[List[dict[str, Any]]] = None
    supervisor_reason: Optional[str] = None
    supervisor_model_provider: Optional[str] = Field(None, max_length=50)
    supervisor_model_id: Optional[str] = Field(None, max_length=200)
    supervisor_response_hash: Optional[str] = Field(None, min_length=64, max_length=64)
    error_type: Optional[str] = Field(None, max_length=80)
    error_message_sanitized: Optional[str] = None


class MappingSupervisorReviewRead(BaseModel):
    """Non-sensitive advisory Supervisor review response shape for future APIs."""

    id: str
    job_id: int
    extracted_data_item_id: Optional[str] = None
    llm_mapping_suggestion_id: Optional[str] = None
    review_status: MappingSupervisorReviewStatus
    supervisor_decision: Optional[SupervisorDecision] = None
    supervisor_risk_level: Optional[SupervisorRiskLevel] = None
    supervisor_recommended_action: Optional[SupervisorRecommendedAction] = None
    supervisor_safe_to_accept: bool = False
    calibrated_safe_to_accept: bool = False
    supervisor_confidence_adjustment: Optional[SupervisorConfidenceAdjustment] = None
    supervisor_issues: List[dict[str, Any]] = Field(default_factory=list)
    supervisor_reason: Optional[str] = None
    supervisor_model_provider: Optional[str] = None
    supervisor_model_id: Optional[str] = None
    supervisor_prompt_version: Optional[str] = None
    supervisor_schema_version: Optional[str] = None
    source: MappingSupervisorReviewSource = MappingSupervisorReviewSource.MOCK
    error_type: Optional[str] = None
    error_message_sanitized: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MappingSupervisorReviewRunRequest(BaseModel):
    """Request body for explicit Supervisor review execution."""

    llm_mapping_suggestion_id: Optional[str] = None
    ai_suggestion_id: Optional[str] = None
    mode: SupervisorReviewRunMode = SupervisorReviewRunMode.MOCK
    force_refresh: bool = False

    @property
    def suggestion_id(self) -> Optional[str]:
        return self.llm_mapping_suggestion_id or self.ai_suggestion_id


class MappingSupervisorReviewBatchRunRequest(BaseModel):
    """Request body for explicit batch Supervisor review execution."""

    mode: SupervisorReviewRunMode = SupervisorReviewRunMode.MOCK
    force_refresh: bool = False
    suggestion_ids: Optional[List[str]] = Field(default=None, max_length=100)


class MappingSupervisorReviewBatchRunResponse(BaseModel):
    """Non-sensitive batch Supervisor review response."""

    job_id: int
    mode: SupervisorReviewRunMode
    force_refresh: bool
    reviews_created: int
    reviews_reused: int
    reviews: List[MappingSupervisorReviewRead]


class SupervisorGuidedMappingRevisionRead(BaseModel):
    """Separate human-review-required mapper revision."""

    id: str
    job_id: int
    parent_suggestion_id: str
    supervisor_review_id: str
    correction_attempt: int = Field(..., ge=1)
    correction_source: str = "supervisor_feedback"
    original_suggested_qname: Optional[str] = None
    revised_suggested_qname: Optional[str] = None
    revised_confidence: Optional[float] = Field(None, ge=0, le=1)
    supervisor_decision: str
    reason: Optional[str] = None
    addressed_supervisor_issues: List[dict[str, Any]] = Field(default_factory=list)
    remaining_ambiguities: List[str] = Field(default_factory=list)
    status: str
    model_id: Optional[str] = None
    requires_human_review: bool = True
    safe_for_auto_apply: bool = False
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class SupervisorMapperFeedbackCapabilitiesRead(BaseModel):
    """Effective gates for the manual Supervisor-to-mapper correction action."""

    job_id: int
    enabled: bool = False
    available: bool = False
    auto_run: bool = False
    max_retries: int = Field(1, ge=0)
    admin_only: bool = True
    authorization_policy: str = "admin_or_explicit_internal_reviewer"
    authorization_source: str = "not_authorized"
    internal_reviewer: bool = False
    reviewer_allowlist_configured: bool = False
    reviewer_allowlist_user_count: int = Field(0, ge=0)
    persistence: str = "separate_revision_table"


class SupervisorGuidedMappingCorrectionResponse(BaseModel):
    """Bounded correction response with no final-mapping mutation fields."""

    initial_suggestion: Dict[str, Any]
    supervisor_review: MappingSupervisorReviewRead
    revised_suggestion: SupervisorGuidedMappingRevisionRead
    safety: Dict[str, Any]


class SupervisorOrchestrationCapabilitiesRead(BaseModel):
    """Read-only effective gates for local orchestration planning."""

    job_id: int
    enabled: bool = False
    available: bool = False
    authorized: bool = False
    mode: str = "manual"
    plan_only: bool = True
    auto_eligibility: bool = True
    auto_review: bool = False
    auto_remap: bool = False
    admin_only: bool = True
    authorization_policy: str = "admin_or_explicit_internal_reviewer"
    authorization_source: str = "not_authorized"
    internal_reviewer: bool = False
    reviewer_allowlist_configured: bool = False
    reviewer_allowlist_user_count: int = Field(0, ge=0)
    max_batch_size: int = Field(10, ge=1)
    max_remap_retries: int = Field(1, ge=0)
    min_risk: str = "medium"
    max_concurrent_live_calls: int = Field(2, ge=1)
    per_row_timeout_seconds: float = Field(120.0, ge=1)
    review_execution_enabled: bool = False
    review_execution_authorized: bool = False
    remap_execution_enabled: bool = False
    remap_execution_authorized: bool = False
    unsafe_configuration_reasons: List[str] = Field(default_factory=list)
    manual_execution_endpoints: Dict[str, str] = Field(default_factory=dict)
    safety: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("auto_review", "auto_remap")
    @classmethod
    def orchestration_automatic_execution_remains_disabled(cls, value: bool) -> bool:
        if value:
            raise ValueError("Automatic Supervisor/remapping execution is forbidden")
        return False


class SupervisorOrchestrationPlanItem(BaseModel):
    """One advisory queue item derived without external calls."""

    suggestion_id: str
    row_id: str
    row_label: Optional[str] = None
    statement_family: Optional[str] = None
    initial_qname: Optional[str] = None
    confidence: float = Field(0.0, ge=0, le=1)
    mapper_status: str
    is_human_terminal: bool = False
    requires_confirmation: bool = False
    orchestration_state: str
    state_details: Dict[str, str] = Field(default_factory=dict)
    supervisor_eligibility: str
    eligibility_reasons: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    priority: str
    eligibility_score: int = Field(0, ge=0)
    strong_signals: List[str] = Field(default_factory=list)
    weak_signals: List[str] = Field(default_factory=list)
    supervisor_review_executable: bool = False
    supervisor_action_block_reason: Optional[str] = None
    batch_review_executable: bool = False
    existing_supervisor_review_id: Optional[str] = None
    supervisor_decision: Optional[str] = None
    remapping_eligibility: str
    remapping_eligible: bool = False
    remapping_executable: bool = False
    remapping_action_block_reason: Optional[str] = None
    existing_revision_id: Optional[str] = None
    correction_attempts_used: int = Field(0, ge=0)
    recommended_manual_action: str
    requires_human_review: bool = True
    safe_for_auto_apply: bool = False
    provenance: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("requires_human_review")
    @classmethod
    def orchestration_item_requires_human_review(cls, value: bool) -> bool:
        if not value:
            raise ValueError("Orchestration queue items require human review")
        return True

    @field_validator("safe_for_auto_apply")
    @classmethod
    def orchestration_item_never_safe_for_auto_apply(cls, value: bool) -> bool:
        if value:
            raise ValueError("Orchestration queue items cannot be safe for auto-apply")
        return False


class SupervisorOrchestrationPlanResponse(BaseModel):
    """Owned-job, plan-only Supervisor orchestration queue."""

    job_id: int
    filing_id: int
    orchestration_enabled: bool
    authorization_source: str = "not_authorized"
    mode: str = "plan_only"
    generated_at: datetime
    total_suggestions: int = Field(0, ge=0)
    policy_eligible_count: int = Field(0, ge=0)
    eligible_count: int = Field(0, ge=0)
    review_executable_count: int = Field(0, ge=0)
    batch_review_executable_count: int = Field(0, ge=0)
    high_priority_count: int = Field(0, ge=0)
    medium_priority_count: int = Field(0, ge=0)
    not_eligible_count: int = Field(0, ge=0)
    blocked_count: int = Field(0, ge=0)
    already_reviewed_count: int = Field(0, ge=0)
    remapping_eligible_count: int = Field(0, ge=0)
    remapping_executable_count: int = Field(0, ge=0)
    remapping_available_count: int = Field(0, ge=0)
    revision_completed_count: int = Field(0, ge=0)
    revision_created_count: int = Field(0, ge=0)
    items: List[SupervisorOrchestrationPlanItem] = Field(default_factory=list)
    safety_summary: Dict[str, Any] = Field(default_factory=dict)


class RulebookMapperSuggestionRead(BaseModel):
    """Advisory-only deterministic rulebook suggestion for one PDF row value."""

    job_id: int
    sample_id: Optional[str] = None
    row_id: str
    pdf_label: str
    normalized_label: str
    pdf_value: Optional[str] = None
    statement_family: Optional[str] = None
    period: Dict[str, Any] = Field(default_factory=dict)
    suggestion_source: str
    matched_rule_id: Optional[str] = None
    rule_readiness: str
    predicted_qname: Optional[str] = None
    predicted_concept_label: Optional[str] = None
    confidence_score: float = Field(0.0, ge=0, le=1)
    confidence_bucket: str
    requires_human_review: bool = True
    safe_for_auto_apply: bool = False
    match_reasons: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    evidence_summary: Dict[str, Any] = Field(default_factory=dict)
    competing_rules: List[Dict[str, Any]] = Field(default_factory=list)
    false_positive_risk_notes: List[Dict[str, Any]] = Field(default_factory=list)


class RulebookMapperSummaryRead(BaseModel):
    """Non-sensitive advisory mapper run summary."""

    job_id: int
    total_pdf_row_value_observations: int = 0
    hardened_rules_loaded: int = 0
    advisory_suggestions_count: int = 0
    review_required_suggestions_count: int = 0
    conflicts_count: int = 0
    no_match_count: int = 0
    safe_for_auto_apply_count: int = 0
    requires_human_review_count: int = 0
    no_suggestion_safe_for_auto_apply: bool = True
    confidence_bucket_counts: Dict[str, int] = Field(default_factory=dict)
    rule_readiness_counts: Dict[str, int] = Field(default_factory=dict)
    per_sample_summary: List[Dict[str, Any]] = Field(default_factory=list)
    recommendation: Dict[str, Any] = Field(default_factory=dict)
    safety: Dict[str, Any] = Field(default_factory=dict)


class RulebookMapperRunResponse(BaseModel):
    """Feature-flagged dry-run response for deterministic advisory suggestions."""

    job_id: int
    mode: str = "dry_run"
    feature_enabled: bool = True
    persistence_enabled: bool = False
    summary: RulebookMapperSummaryRead
    suggestions: List[RulebookMapperSuggestionRead] = Field(default_factory=list)


class RulebookMapperCapabilitiesRead(BaseModel):
    """Read-only capability metadata for the advisory mapper endpoint."""

    job_id: int
    enabled: bool = False
    default_mode: str = "dry_run"
    allow_persistence: bool = False
    supported_modes: List[str] = Field(default_factory=lambda: ["dry_run"])
    endpoints: List[str] = Field(default_factory=list)
    safety: Dict[str, Any] = Field(default_factory=dict)


class RankedCandidateCapabilitiesRead(BaseModel):
    """Read-only capability metadata for ranked candidate advisory endpoints."""

    job_id: int
    enabled: bool = False
    default_mode: str = "dry_run"
    allow_persistence: bool = False
    default_profile: str = "balanced"
    supported_profiles: List[str] = Field(default_factory=list)
    supported_modes: List[str] = Field(default_factory=lambda: ["dry_run"])
    supported_actions: List[str] = Field(default_factory=list)
    max_rows: int = 1000
    max_candidates_per_row: int = 5
    admin_only: bool = True
    feature_flags: Dict[str, Any] = Field(default_factory=dict)
    endpoints: List[str] = Field(default_factory=list)
    safety: Dict[str, Any] = Field(default_factory=dict)


class RankedCandidateAdvisoryMode(str, Enum):
    DRY_RUN = "dry_run"
    PERSISTED_LATER = "persisted_later"


class RankedCandidateGenerationStatus(str, Enum):
    DISABLED = "disabled"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RankedCandidateRecommendedAction(str, Enum):
    REVIEW_CANDIDATE = "review_candidate"
    KEEP_FOR_HUMAN_REVIEW = "keep_for_human_review"
    NO_CANDIDATE = "no_candidate"
    BLOCKED = "blocked"


class RankedCandidateEvidence(BaseModel):
    """Non-sensitive local evidence for one ranked candidate."""

    match_reasons: List[str] = Field(default_factory=list)
    risk_reasons: List[str] = Field(default_factory=list)
    profile_filter_reasons: List[str] = Field(default_factory=list)
    source_weight: Optional[float] = None
    raw_evidence: Dict[str, Any] = Field(default_factory=dict)


class RankedCandidateItem(BaseModel):
    """Advisory-only ranked taxonomy candidate."""

    rank: int = Field(..., ge=1)
    qname: str
    concept_label: Optional[str] = None
    namespace: Optional[str] = None
    candidate_sources_combined: List[str] = Field(default_factory=list)
    score: float = Field(..., ge=0, le=1)
    confidence_bucket: str
    risk_level: str
    evidence: RankedCandidateEvidence = Field(default_factory=RankedCandidateEvidence)
    ambiguity_reasons: List[str] = Field(default_factory=list)
    blocking_reasons: List[str] = Field(default_factory=list)
    requires_human_review: bool = True
    safe_for_auto_apply: bool = False
    recommended_action: RankedCandidateRecommendedAction = RankedCandidateRecommendedAction.REVIEW_CANDIDATE
    profile: str = "balanced"
    calibration_version: str = "18F-B-balanced"

    @field_validator("requires_human_review")
    @classmethod
    def ranked_candidate_requires_human_review(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("ranked candidates must require human review")
        return True

    @field_validator("safe_for_auto_apply")
    @classmethod
    def ranked_candidate_never_safe_for_auto_apply(cls, value: bool) -> bool:
        if value is not False:
            raise ValueError("ranked candidates are never safe for auto-apply")
        return False

    @field_validator("recommended_action", mode="before")
    @classmethod
    def ranked_candidate_action_is_advisory_only(cls, value):
        action = str(value.value if isinstance(value, Enum) else value)
        if action in {"accept", "apply", "confirm", "auto_apply", "auto_accept"}:
            raise ValueError("ranked candidate action must remain advisory-only")
        return value


class RankedCandidateRow(BaseModel):
    """One extracted row with advisory ranked candidates."""

    row_id: str
    statement_family: Optional[str] = None
    section_block: Optional[str] = None
    row_label: Optional[str] = None
    normalized_label: Optional[str] = None
    row_value: Any = None
    period: Dict[str, Any] = Field(default_factory=dict)
    note_boundary_type: Optional[str] = None
    candidate_coverage_status: str
    candidates: List[RankedCandidateItem] = Field(default_factory=list)


class RankedCandidateSafetySummary(BaseModel):
    """Safety counters for advisory ranked-candidate responses."""

    safe_for_auto_apply_count: int = 0
    requires_human_review_count: int = 0
    confirmed_tag_id_mutations: int = 0
    final_mapping_mutations: int = 0
    persistence_writes: int = 0
    ai_suggestion_table_writes: int = 0
    external_calls: int = 0
    xbrl_generation_count: int = 0
    arelle_runs: int = 0
    no_auto_apply_guarantee: bool = True


class RankedCandidateAdvisoryRequest(BaseModel):
    """Future request shape for ranked candidate advisory generation."""

    profile: str = "balanced"
    mode: RankedCandidateAdvisoryMode = RankedCandidateAdvisoryMode.DRY_RUN
    max_rows: int = Field(1000, ge=1)
    max_candidates_per_row: int = Field(5, ge=1, le=10)


class RankedCandidateAdvisoryResponse(BaseModel):
    """Dry-run advisory response for ranked taxonomy candidates."""

    job_id: int
    filing_id: Optional[int] = None
    profile: str = "balanced"
    mode: RankedCandidateAdvisoryMode = RankedCandidateAdvisoryMode.DRY_RUN
    candidate_generation_status: RankedCandidateGenerationStatus = RankedCandidateGenerationStatus.DISABLED
    total_rows: int = 0
    rows_with_candidates: int = 0
    candidate_coverage: Optional[float] = None
    generated_at: Optional[str] = None
    feature_flags: Dict[str, Any] = Field(default_factory=dict)
    safety: RankedCandidateSafetySummary = Field(default_factory=RankedCandidateSafetySummary)
    rows: List[RankedCandidateRow] = Field(default_factory=list)


def mapping_supervisor_review_read_from_model(review) -> MappingSupervisorReviewRead:
    """Serialize a Supervisor review ORM row without exposing payload hashes or raw payloads."""

    issues = []
    raw_issues = getattr(review, "supervisor_issues_json", None)
    if raw_issues:
        try:
            decoded = json.loads(raw_issues)
            if isinstance(decoded, list):
                issues = [item for item in decoded if isinstance(item, dict)]
        except json.JSONDecodeError:
            issues = []

    return MappingSupervisorReviewRead(
        id=review.id,
        job_id=review.job_id,
        extracted_data_item_id=getattr(review, "extracted_data_item_id", None),
        llm_mapping_suggestion_id=getattr(review, "llm_mapping_suggestion_id", None),
        review_status=getattr(review, "review_status", "pending"),
        supervisor_decision=getattr(review, "supervisor_decision", None),
        supervisor_risk_level=getattr(review, "supervisor_risk_level", None),
        supervisor_recommended_action=getattr(review, "supervisor_recommended_action", None),
        supervisor_safe_to_accept=bool(getattr(review, "supervisor_safe_to_accept", False)),
        calibrated_safe_to_accept=bool(getattr(review, "calibrated_safe_to_accept", False)),
        supervisor_confidence_adjustment=getattr(review, "supervisor_confidence_adjustment", None),
        supervisor_issues=issues,
        supervisor_reason=getattr(review, "supervisor_reason", None),
        supervisor_model_provider=getattr(review, "supervisor_model_provider", None),
        supervisor_model_id=getattr(review, "supervisor_model_id", None),
        supervisor_prompt_version=getattr(review, "supervisor_prompt_version", None),
        supervisor_schema_version=getattr(review, "supervisor_schema_version", None),
        source=getattr(review, "source", None) or "mock",
        error_type=getattr(review, "error_type", None),
        error_message_sanitized=getattr(review, "error_message_sanitized", None),
        created_at=getattr(review, "created_at", None),
        updated_at=getattr(review, "updated_at", None),
    )


# Page schemas
class PageResponse(BaseModel):
    id: str
    job_id: int
    page_number: int
    image_path: str

    class Config:
        from_attributes = True


# Enhanced Extracted Data schemas
class ExtractedDataItemCreate(BaseModel):
    """Schema for creating new extracted data items"""
    extracted_label: str = Field(..., min_length=1, max_length=1000,
                                 description="Financial item label")  # Increased
    # Removed max_length
    extracted_value: str = Field(..., min_length=1,
                                 description="Financial item value")
    financial_year: Optional[int] = Field(
        None, description="Financial year for this data")
    statement_type: Optional[str] = Field(
        None, max_length=200, description="Statement type (used for context inference)")
    template_field_id: Optional[str] = Field(
        None, description="Template field ID for XBRL mapping")
    is_reviewed: Optional[bool] = Field(
        False, description="Whether this item has been reviewed")

    @validator('extracted_value')
    def clean_extracted_value(cls, v):
        if v:
            # Remove extra whitespace and normalize
            return ' '.join(v.split())
        return v

    @validator('financial_year')
    def validate_financial_year(cls, v):
        if v is not None and (v < 1900 or v > 2100):
            raise ValueError('Financial year must be between 1900 and 2100')
        return v


class ExtractedDataItemUpdate(BaseModel):
    """Schema for updating extracted data items"""
    extracted_label: Optional[str] = Field(None, min_length=1, max_length=555)
    extracted_value: Optional[str] = Field(None, max_length=500)
    financial_year: Optional[int] = None
    is_reviewed: Optional[bool] = None
    confirmed_tag_id: Optional[int] = None

    @validator('extracted_value')
    def clean_extracted_value(cls, v):
        if v:
            return ' '.join(v.split())
        return v

    @validator('financial_year')
    def validate_financial_year(cls, v):
        if v is not None and (v < 1900 or v > 2100):
            raise ValueError('Financial year must be between 1900 and 2100')
        return v


class ExtractedDataItemResponse(BaseModel):
    """Schema for extracted data item responses"""
    id: str
    page_id: str
    extracted_label: str
    extracted_value: str
    financial_year: Optional[int]
    is_reviewed: bool
    confirmed_tag_id: Optional[int]

    # Related data
    page_number: Optional[int] = None
    confirmed_tag_label: Optional[str] = None

    class Config:
        from_attributes = True


# Bulk operations
class BulkUpdateRequest(BaseModel):
    """Schema for bulk update requests"""
    items: List[dict] = Field(..., min_items=1,
                              description="List of items to update")

    @validator('items')
    def validate_items(cls, v):
        for item in v:
            if 'id' not in item:
                raise ValueError('Each item must have an id field')
        return v


class BulkUpdateResponse(BaseModel):
    """Schema for bulk update responses"""
    success: bool
    updated_count: int
    message: str
    deleted_count: Optional[int] = 0


# Search schemas
class TaxonomySearchResponse(BaseModel):
    """Schema for taxonomy search responses"""
    results: List[dict]
    cached: bool = False
    search_time: float
    total_results: int


# Pagination
class PaginationParams(BaseModel):
    """Schema for pagination parameters"""
    page: int = Field(1, ge=1, description="Page number (1-based)")
    size: int = Field(50, ge=1, le=100, description="Number of items per page")


class PaginatedResponse(BaseModel):
    """Schema for paginated responses"""
    items: List[dict]
    total: int
    page: int
    size: int
    pages: int
    has_next: bool
    has_previous: bool


# File upload
class FileUploadResponse(BaseModel):
    """Schema for file upload responses"""
    filename: str
    file_path: str
    size: int
    content_type: str


# XBRL Generation
class XBRLGenerationRequest(BaseModel):
    """Schema for XBRL generation requests"""
    job_id: int
    include_unreviewed: bool = False


class XBRLGenerationResponse(BaseModel):
    """Schema for XBRL generation responses"""
    success: bool
    file_path: Optional[str] = None
    content: Optional[str] = None
    error: Optional[str] = None
    validation_results: Optional[dict] = None


# AI Processing
class AIExtractionResult(BaseModel):
    """Schema for AI extraction results"""
    entity_info: Optional[dict] = None
    financial_items: List[dict] = []
    html_content: Optional[str] = None
    confidence_score: Optional[float] = None


class ProcessingStatus(BaseModel):
    """Schema for processing status"""
    job_id: int
    status: JobStatus
    progress: Optional[int] = Field(
        None, ge=0, le=100, description="Progress percentage (0-100)")
    message: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    extracted_row_count: Optional[int] = None
    ai_mapping_status: Optional[str] = None
    ai_suggestion_count: Optional[int] = None
    warnings: List[dict] = Field(default_factory=list)
    optional_stage: Optional[str] = None
    optional_stage_status: Optional[str] = None
    optional_stage_error_code: Optional[str] = None
    optional_stage_error_message: Optional[str] = None


class TocEntry(BaseModel):
    entry_id: str
    raw_title: str
    normalized_title: str
    canonical_section_hint: str
    printed_page_start: Optional[int] = None
    printed_page_end: Optional[int] = None
    printed_page_start_label: Optional[str] = None
    printed_page_end_label: Optional[str] = None
    printed_page_text: Optional[str] = None
    source_pdf_page_index: int = Field(..., ge=0)
    source_text: str
    confidence: float = Field(..., ge=0, le=1)
    range_method: str = "unresolved"
    parse_warnings: List[str] = Field(default_factory=list)


class HeadingAnchor(BaseModel):
    anchor_id: str
    toc_entry_id: str
    source_content_id: str
    toc_title: str
    matched_heading: str
    pdf_page_index: int = Field(..., ge=0)
    azure_page_number: int = Field(..., ge=1)
    match_score: float = Field(..., ge=0, le=1)
    match_method: str
    match_tier: str = "legacy"
    lexical_score: float = Field(0.0, ge=0, le=1)
    token_coverage: float = Field(0.0, ge=0, le=1)
    expected_token_coverage: float = Field(0.0, ge=0, le=1)
    candidate_token_coverage: float = Field(0.0, ge=0, le=1)
    expected_core_token_coverage: float = Field(0.0, ge=0, le=1)
    candidate_core_token_coverage: float = Field(0.0, ge=0, le=1)
    missing_expected_core_tokens: List[str] = Field(default_factory=list)
    length_ratio: float = Field(0.0, ge=0, le=1)
    heading_quality_score: float = Field(0.0, ge=0, le=1)
    trusted: bool = True
    rejection_reason: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0, le=1)
    scoring_signals: List[str] = Field(default_factory=list)
    text_evidence: str
    bounding_evidence: List[dict] = Field(default_factory=list)
    alternative_candidates: List[dict] = Field(default_factory=list)
    rejected_candidates: List[dict] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class DocumentPageMapping(BaseModel):
    pdf_page_index: int = Field(..., ge=0)
    azure_page_number: int = Field(..., ge=1)
    printed_page_number: Optional[int] = None
    printed_page_label: Optional[str] = None
    numbering_scheme: Optional[str] = None
    offset: Optional[int] = None
    mapping_method: str
    confidence: float = Field(..., ge=0, le=1)
    anchor_title: Optional[str] = None
    requires_human_review: bool = False
    warnings: List[str] = Field(default_factory=list)


class DocumentContentEvidence(BaseModel):
    """Minimal, artifact-scoped evidence for a referenced source item."""

    content_id: str
    content_type: str
    text_evidence: Optional[str] = None
    pdf_page_indexes: List[int] = Field(default_factory=list)
    azure_page_numbers: List[int] = Field(default_factory=list)
    bounding_evidence: List[dict] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class DocumentContentDisposition(BaseModel):
    content_id: str
    content_type: str
    pdf_page_index: Optional[int] = None
    azure_page_number: Optional[int] = None
    pdf_page_indexes: List[int] = Field(default_factory=list)
    azure_page_numbers: List[int] = Field(default_factory=list)
    reason: str
    candidate_section_ids: List[str] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class DocumentSection(BaseModel):
    section_id: str
    job_id: int
    raw_title: str
    normalized_title: str
    canonical_section_type: str
    toc_entry_id: str
    parent_section_id: Optional[str] = None
    section_level: int = Field(1, ge=1)
    section_order: int = Field(..., ge=0)
    printed_page_start: Optional[int] = None
    printed_page_end: Optional[int] = None
    pdf_page_start: Optional[int] = None
    pdf_page_end: Optional[int] = None
    azure_page_start: Optional[int] = None
    azure_page_end: Optional[int] = None
    heading_anchor_page: Optional[int] = None
    heading_anchor_id: Optional[str] = None
    start_heading_bbox: List[dict] = Field(default_factory=list)
    start_heading_offset: Optional[float] = None
    end_heading_bbox: List[dict] = Field(default_factory=list)
    end_heading_offset: Optional[float] = None
    confidence: float = Field(..., ge=0, le=1)
    grouping_method: str
    requires_human_review: bool = False
    warnings: List[str] = Field(default_factory=list)
    text_block_ids: List[str] = Field(default_factory=list)
    heading_ids: List[str] = Field(default_factory=list)
    table_ids: List[str] = Field(default_factory=list)
    table_cell_ids: List[str] = Field(default_factory=list)
    extracted_row_ids: List[str] = Field(default_factory=list)
    candidate_note_heading_ids: List[str] = Field(default_factory=list)
    range_consistency: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)


class DocumentStructureResult(BaseModel):
    job_id: int
    document_id: str
    feature_version: str
    toc_detected: bool
    toc_page_indexes: List[int] = Field(default_factory=list)
    toc_confidence: float = Field(..., ge=0, le=1)
    toc_detection: Dict[str, Any] = Field(default_factory=dict)
    page_mapping_confidence: float = Field(..., ge=0, le=1)
    page_alignment_summary: Dict[str, Any] = Field(default_factory=dict)
    section_count: int = Field(..., ge=0)
    toc_entries: List[TocEntry] = Field(default_factory=list)
    heading_anchors: List[HeadingAnchor] = Field(default_factory=list)
    page_mappings: List[DocumentPageMapping] = Field(default_factory=list)
    sections: List[DocumentSection] = Field(default_factory=list)
    content_evidence: List[DocumentContentEvidence] = Field(default_factory=list)
    unassigned_content: List[DocumentContentDisposition] = Field(default_factory=list)
    ambiguous_content: List[DocumentContentDisposition] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    safety_summary: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime


class DocumentStructureCapabilitiesRead(BaseModel):
    feature_version: str
    enabled: bool
    persistence_enabled: bool
    llm_fallback_enabled: bool
    llm_fallback_implemented: bool = False
    available: bool
    result_persisted: bool
    analysis_mode: str = "deterministic_local"
    warnings: List[str] = Field(default_factory=list)


class TemplateGroupAssignmentMethod(str, Enum):
    DETERMINISTIC_EXACT = "deterministic_exact"
    DETERMINISTIC_ALIAS = "deterministic_alias"
    DETERMINISTIC_RULE = "deterministic_rule"
    BOUNDED_LLM = "bounded_llm"
    HUMAN_OVERRIDE = "human_override"


class SectionClassificationOutcomeType(str, Enum):
    MATCHED = "matched"
    MULTIPLE_TEMPLATES = "multiple_templates"
    NARRATIVE_ONLY = "narrative_only"
    CONTAINER_ONLY = "container_only"
    NOT_APPLICABLE = "not_applicable"
    AMBIGUOUS = "ambiguous"
    UNASSIGNED = "unassigned"
    CLASSIFICATION_FAILED = "classification_failed"


class TemplateGroupCard(BaseModel):
    """Canonical, registry-derived classification view of one template role."""

    template_group_id: str
    code: str
    role_uri: str
    official_role_definition: str
    canonical_name: str
    user_display_name: str
    normalized_name: str
    template_kind: str
    structural_role: str
    statement_family: str
    aliases: List[str] = Field(default_factory=list)
    classification_enabled: bool
    mapping_enabled: bool
    allows_multiple_source_sections: bool
    expected_source_section_types: List[str] = Field(default_factory=list)
    positive_indicators: List[str] = Field(default_factory=list)
    exclusion_indicators: List[str] = Field(default_factory=list)
    source_taxonomy_version: str
    semantic_hash: str
    primary_deterministic_classification_allowed: bool = False
    note_subsection_classification_allowed: bool = False
    multiple_assignments_allowed: bool = False
    legacy_aliases_not_for_classification: List[str] = Field(default_factory=list)


class TemplateGroupAssignment(BaseModel):
    assignment_id: str
    source_section_id: str
    parent_section_id: Optional[str] = None
    template_group_id: str
    template_code: str
    canonical_template_name: str
    assignment_method: TemplateGroupAssignmentMethod
    confidence: float = Field(..., ge=0, le=1)
    evidence: List[str] = Field(default_factory=list)
    alternative_template_group_ids: List[str] = Field(default_factory=list)
    requires_human_review: bool = False
    warnings: List[str] = Field(default_factory=list)


class NoteSubsection(BaseModel):
    child_section_id: str
    parent_section_id: str = "notes_container"
    raw_heading: str
    normalized_heading: str
    note_number: Optional[str] = None
    note_label: str
    pdf_page_start: Optional[int] = None
    pdf_page_end: Optional[int] = None
    azure_page_start: Optional[int] = None
    azure_page_end: Optional[int] = None
    heading_evidence: List[str] = Field(default_factory=list)
    paragraph_references: List[str] = Field(default_factory=list)
    table_references: List[str] = Field(default_factory=list)
    table_cell_references: List[str] = Field(default_factory=list)
    extracted_row_references: List[str] = Field(default_factory=list)
    other_evidence_references: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)
    warnings: List[str] = Field(default_factory=list)


class NotesSegmentationMetrics(BaseModel):
    raw_heading_candidate_count: int = Field(0, ge=0)
    accepted_heading_candidate_count: int = Field(0, ge=0)
    accepted_logical_subsection_count: int = Field(0, ge=0)
    duplicate_headings_merged: int = Field(0, ge=0)
    continuation_headings_merged: int = Field(0, ge=0)
    boilerplate_lines_suppressed: int = Field(0, ge=0)
    table_value_fragments_suppressed: int = Field(0, ge=0)
    invalid_numeric_note_numbers_rejected: int = Field(0, ge=0)
    prose_candidates_rejected: int = Field(0, ge=0)
    other_low_quality_candidates_rejected: int = Field(0, ge=0)
    extracted_rows_attached: int = Field(0, ge=0)
    child_sections_with_zero_meaningful_content: int = Field(0, ge=0)


class NotesContentConservation(BaseModel):
    total_notes_evidence_items: int = Field(0, ge=0)
    assigned_items: int = Field(0, ge=0)
    ambiguous_items: int = Field(0, ge=0)
    unassigned_items: int = Field(0, ge=0)
    dropped_items: int = Field(0, ge=0)
    assigned_evidence_ids: List[str] = Field(default_factory=list)
    ambiguous_evidence_ids: List[str] = Field(default_factory=list)
    unassigned_evidence_ids: List[str] = Field(default_factory=list)
    segmentation_metrics: NotesSegmentationMetrics = Field(
        default_factory=NotesSegmentationMetrics
    )
    passed: bool = False


class SectionClassificationOutcome(BaseModel):
    section_id: str
    raw_title: str
    normalized_title: str
    canonical_section_type: str
    section_level: int = Field(..., ge=1)
    parent_section_id: Optional[str] = None
    page_range: Dict[str, Optional[int]] = Field(default_factory=dict)
    outcome: SectionClassificationOutcomeType
    assignments: List[TemplateGroupAssignment] = Field(default_factory=list)
    alternative_template_group_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)
    evidence: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    requires_human_review: bool = False
    llm_called: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None
    prompt_version: Optional[str] = None


class DocumentTemplateClassificationResult(BaseModel):
    job_id: int
    filing_id: int
    source_structure_artifact_version: str
    source_structure_hash: str
    classification_version: str
    canonical_registry_version: str
    canonical_registry_hash: str
    total_primary_sections: int = Field(0, ge=0)
    total_note_subsections: int = Field(0, ge=0)
    matched_count: int = Field(0, ge=0)
    multiple_template_count: int = Field(0, ge=0)
    narrative_only_count: int = Field(0, ge=0)
    container_only_count: int = Field(0, ge=0)
    ambiguous_count: int = Field(0, ge=0)
    unassigned_count: int = Field(0, ge=0)
    failed_count: int = Field(0, ge=0)
    deterministic_count: int = Field(0, ge=0)
    llm_count: int = Field(0, ge=0)
    outcomes: List[SectionClassificationOutcome] = Field(default_factory=list)
    note_subsections: List[NoteSubsection] = Field(default_factory=list)
    notes_conservation: NotesContentConservation = Field(
        default_factory=NotesContentConservation
    )
    warnings: List[str] = Field(default_factory=list)
    safety_summary: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime


class TemplateClassificationCapabilitiesRead(BaseModel):
    classification_version: str
    enabled: bool
    persistence_enabled: bool
    live_llm_enabled: bool
    llm_fallback_implemented: bool = True
    available: bool
    result_persisted: bool
    registry_version: str
    registry_hash: str
    source_structure_version: Optional[str] = None
    source_structure_hash: Optional[str] = None
    analysis_mode: str = "deterministic_first_bounded_llm"
    warnings: List[str] = Field(default_factory=list)


class RowMappingEligibility(BaseModel):
    source_row_id: str
    outcome: str
    eligible: bool = False
    reasons: List[str] = Field(default_factory=list)
    duplicate_group_id: Optional[str] = None
    competing_source_row_ids: List[str] = Field(default_factory=list)
    requires_human_review: bool = True


class TaxonomyConceptCard(BaseModel):
    concept_id: str
    qname: str
    namespace: Optional[str] = None
    local_name: str
    standard_label: str
    terse_label: Optional[str] = None
    verbose_label: Optional[str] = None
    documentation: Optional[str] = None
    datatype: Optional[str] = None
    period_type: Optional[str] = None
    balance: Optional[str] = None
    abstract: bool = False
    nillable: Optional[bool] = None
    substitution_group: Optional[str] = None
    template_group_ids: List[str] = Field(default_factory=list)
    template_codes: List[str] = Field(default_factory=list)
    role_uris: List[str] = Field(default_factory=list)
    statement_family: List[str] = Field(default_factory=list)
    concept_path: List[str] = Field(default_factory=list)
    parent_concepts: List[str] = Field(default_factory=list)
    child_concepts: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    positive_indicators: List[str] = Field(default_factory=list)
    exclusion_indicators: List[str] = Field(default_factory=list)
    do_not_confuse: List[str] = Field(default_factory=list)
    source_taxonomy_version: str
    provenance: Dict[str, Any] = Field(default_factory=dict)


class CandidateScoreBreakdown(BaseModel):
    lexical_score: float = 0.0
    alias_score: float = 0.0
    documentation_score: float = 0.0
    semantic_phrase_score: float = 0.0
    section_compatibility_score: float = 0.0
    template_group_score: float = 0.0
    datatype_score: float = 0.0
    period_type_score: float = 0.0
    balance_score: float = 0.0
    hierarchy_score: float = 0.0
    sibling_context_score: float = 0.0
    value_shape_score: float = 0.0
    total_subtotal_score: float = 0.0
    exclusion_penalty: float = 0.0
    abstract_penalty: float = 0.0
    semantic_contrast_penalty: float = 0.0
    scope_limitation_penalty: float = 0.0
    total_score: float = 0.0
    reasons: List[str] = Field(default_factory=list)


class SectionAwareTaxonomyCandidate(BaseModel):
    rank: int = Field(..., ge=1)
    concept_id: str
    qname: str
    selectable: bool = True
    concept_card: TaxonomyConceptCard
    score: CandidateScoreBreakdown


class SectionAwareCandidateSet(BaseModel):
    source_row_id: str
    section_id: Optional[str] = None
    subsection_id: Optional[str] = None
    template_group_ids: List[str] = Field(default_factory=list)
    row_eligibility: RowMappingEligibility
    candidate_outcome: str
    candidate_count_before_filter: int = Field(0, ge=0)
    candidate_count_after_filter: int = Field(0, ge=0)
    top_k: int = Field(0, ge=0, le=20)
    candidates: List[SectionAwareTaxonomyCandidate] = Field(default_factory=list)
    semantic_source_label: str = ""
    semantic_normalization_reasons: List[str] = Field(default_factory=list)
    semantic_target_families: List[str] = Field(default_factory=list)
    semantic_scope_limitations: List[str] = Field(default_factory=list)
    retrieval_version: str
    concept_inventory_hash: str
    requires_human_review: bool = True
    warnings: List[str] = Field(default_factory=list)


class InitialTaxonomyMappingResult(BaseModel):
    mapping_id: str
    source_row_id: str
    section_id: Optional[str] = None
    subsection_id: Optional[str] = None
    template_group_ids: List[str] = Field(default_factory=list)
    source_label: str
    source_values: Dict[str, Any] = Field(default_factory=dict)
    row_eligibility: RowMappingEligibility
    decision: str
    selected_concept_id: Optional[str] = None
    selected_qname: Optional[str] = None
    candidate_set: SectionAwareCandidateSet
    confidence: float = Field(0.0, ge=0, le=1)
    reason: str
    alternatives: List[str] = Field(default_factory=list)
    requires_human_review: bool = True
    mapping_method: str
    provider: Optional[str] = None
    model: Optional[str] = None
    provider_call_count: int = Field(0, ge=0, le=1)
    prompt_hash: Optional[str] = None
    prompt_version: str
    retrieval_version: str
    concept_inventory_hash: str
    source_structure_hash: str
    source_classification_hash: str
    registry_hash: str
    duplicate_group_id: Optional[str] = None
    competing_source_row_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    generated_at: datetime


class DocumentInitialMappingResult(BaseModel):
    job_id: int
    filing_id: int
    source_structure_version: str
    source_structure_hash: str
    source_classification_version: str
    source_classification_hash: str
    registry_version: str
    registry_hash: str
    taxonomy_version: str
    concept_inventory_hash: str
    mapping_version: str
    total_rows: int = Field(0, ge=0)
    eligible_rows: int = Field(0, ge=0)
    mapped_rows: int = Field(0, ge=0)
    ambiguous_rows: int = Field(0, ge=0)
    abstained_rows: int = Field(0, ge=0)
    no_safe_mapping_rows: int = Field(0, ge=0)
    structural_rows: int = Field(0, ge=0)
    failed_rows: int = Field(0, ge=0)
    deterministic_candidate_sets: int = Field(0, ge=0)
    llm_calls: int = Field(0, ge=0)
    mappings: List[InitialTaxonomyMappingResult] = Field(default_factory=list)
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    safety_summary: Dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime


class InitialMappingCapabilitiesRead(BaseModel):
    mapping_version: str
    candidate_retrieval_enabled: bool
    initial_mapping_enabled: bool
    persistence_enabled: bool
    live_llm_enabled: bool
    mode: str
    available: bool
    result_persisted: bool
    max_candidates: int = Field(..., ge=1, le=20)
    max_rows_per_job: int = Field(..., ge=1)
    source_structure_hash: Optional[str] = None
    source_classification_hash: Optional[str] = None
    registry_hash: Optional[str] = None
    concept_inventory_hash: Optional[str] = None
    provider_call_count: int = Field(0, ge=0)
    warnings: List[str] = Field(default_factory=list)


# Enhanced Progress Tracking
class ProgressUpdate(BaseModel):
    """Schema for progress updates"""
    job_id: int
    progress: int = Field(..., ge=0, le=100)
    status: JobStatus
    message: Optional[str] = None
    current_page: Optional[int] = None
    total_pages: Optional[int] = None
    items_extracted: Optional[int] = None


# Performance monitoring
class PerformanceMetrics(BaseModel):
    """Schema for performance metrics"""
    request_count: int
    avg_response_time: float
    slow_requests: int
    cache_hit_rate: float
    database_queries: int
    active_jobs: Optional[int] = 0


# Dashboard
class DashboardStats(BaseModel):
    """Schema for dashboard statistics"""
    total_jobs: int
    processing_jobs: int
    completed_jobs: int
    error_jobs: int
    total_extracted_items: int
    reviewed_items: int
    taxonomy_tags: int

    # Additional stats
    avg_processing_time: Optional[float] = None
    items_per_job_avg: Optional[float] = None
    review_completion_rate: Optional[float] = None


# Enhanced Item Management
class ItemCreateRequest(BaseModel):
    """Schema for creating new extracted data items"""
    page_id: str = Field(...,
                         description="ID of the page to associate the item with")
    extracted_label: str = Field(..., min_length=1, max_length=255)
    extracted_value: str = Field(..., max_length=500)
    financial_year: Optional[int] = None
    confirmed_tag_id: Optional[int] = None
    is_reviewed: bool = False


class ItemBatchCreateRequest(BaseModel):
    """Schema for creating multiple items at once"""
    items: List[ItemCreateRequest] = Field(..., min_items=1, max_items=50)


class ItemBatchCreateResponse(BaseModel):
    """Schema for batch create responses"""
    success: bool
    created_count: int
    failed_count: int = 0
    created_items: List[ExtractedDataItemResponse] = []
    errors: List[str] = []


# Page-based data schemas
class PageDataRequest(BaseModel):
    """Schema for requesting page-specific data"""
    job_id: int
    page_number: int = Field(..., ge=1, description="Page number (1-based)")


class PageDataResponse(BaseModel):
    """Schema for page-specific data response"""
    page_info: dict
    extracted_items: List[ExtractedDataItemResponse]
    total_items: int
    reviewed_items: int
    page_image_url: str


# Enhanced validation and status
class ValidationResult(BaseModel):
    """Schema for validation results"""
    is_valid: bool
    errors: List[str] = []
    warnings: List[str] = []
    suggestions: List[str] = []


class ItemValidationRequest(BaseModel):
    """Schema for validating extracted data items"""
    extracted_label: str
    extracted_value: str
    confirmed_tag_id: Optional[int] = None


# Error responses
class ErrorResponse(BaseModel):
    """Schema for error responses"""
    error: str
    detail: Optional[str] = None
    status_code: int
    timestamp: Optional[datetime] = None
    request_id: Optional[str] = None


# API Response wrapper
class APIResponse(BaseModel):
    """Generic API response wrapper"""
    success: bool
    data: Optional[dict] = None
    message: Optional[str] = None
    errors: Optional[List[str]] = None
    meta: Optional[dict] = None


# Export commonly used schemas
__all__ = [
    'JobStatus',
    'PeriodType',
    'MappingSupervisorReviewStatus',
    'SupervisorDecision',
    'SupervisorRiskLevel',
    'SupervisorRecommendedAction',
    'SupervisorConfidenceAdjustment',
    'MappingSupervisorReviewSource',
    'SupervisorReviewRunMode',
    'UserResponse',
    'RegisterRequest',
    'LoginRequest',
    'ChangePasswordRequest',
    'DeleteAccountRequest',
    'AdminCreateUserRequest',
    'AdminChangeUserPasswordRequest',
    'AuthTokenResponse',
    'ChangePasswordResponse',
    'DeleteAccountResponse',
    'LogoutResponse',
    'FilingJobCreate',
    'FilingJobUpdate',
    'FilingJobResponse',
    'MappingSupervisorReviewCreateInternal',
    'MappingSupervisorReviewUpdateInternal',
    'MappingSupervisorReviewRead',
    'MappingSupervisorReviewRunRequest',
    'MappingSupervisorReviewBatchRunRequest',
    'MappingSupervisorReviewBatchRunResponse',
    'SupervisorGuidedMappingRevisionRead',
    'SupervisorMapperFeedbackCapabilitiesRead',
    'SupervisorGuidedMappingCorrectionResponse',
    'SupervisorOrchestrationCapabilitiesRead',
    'SupervisorOrchestrationPlanItem',
    'SupervisorOrchestrationPlanResponse',
    'RulebookMapperSuggestionRead',
    'RulebookMapperSummaryRead',
    'RulebookMapperRunResponse',
    'RulebookMapperCapabilitiesRead',
    'RankedCandidateCapabilitiesRead',
    'RankedCandidateAdvisoryMode',
    'RankedCandidateGenerationStatus',
    'RankedCandidateRecommendedAction',
    'RankedCandidateEvidence',
    'RankedCandidateItem',
    'RankedCandidateRow',
    'RankedCandidateSafetySummary',
    'RankedCandidateAdvisoryRequest',
    'RankedCandidateAdvisoryResponse',
    'mapping_supervisor_review_read_from_model',
    'ExtractedDataItemCreate',
    'ExtractedDataItemUpdate',
    'ExtractedDataItemResponse',
    'BulkUpdateRequest',
    'BulkUpdateResponse',
    'TaxonomySearchResponse',
    'PaginatedResponse',
    'XBRLGenerationResponse',
    'ProcessingStatus',
    'TocEntry',
    'HeadingAnchor',
    'DocumentPageMapping',
    'DocumentContentEvidence',
    'DocumentContentDisposition',
    'DocumentSection',
    'DocumentStructureResult',
    'DocumentStructureCapabilitiesRead',
    'ProgressUpdate',
    'DashboardStats',
    'PageDataResponse',
    'ItemCreateRequest',
    'ItemBatchCreateRequest',
    'ValidationResult',
    'ErrorResponse',
    'APIResponse'
]
