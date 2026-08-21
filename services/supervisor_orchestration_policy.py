"""Local-only policy and state model for conditional Supervisor orchestration.

This module never calls a provider and never mutates suggestions, extracted
rows, Supervisor reviews, revisions, or final mappings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from services.suggestion_actionability import (
    is_human_terminal,
    remapping_actionability,
)
from services.supervisor_mapper_feedback import supervisor_feedback_eligibility


MAPPING_STATES = (
    "mapping_suggested",
    "mapping_no_safe_candidate",
    "mapping_failed",
)
SUPERVISOR_ELIGIBILITY_STATES = (
    "supervisor_not_evaluated",
    "supervisor_not_eligible",
    "supervisor_eligible",
    "supervisor_blocked",
)
SUPERVISOR_EXECUTION_STATES = (
    "supervisor_pending",
    "supervisor_running",
    "supervisor_completed",
    "supervisor_failed",
    "supervisor_skipped",
)
REMAPPING_ELIGIBILITY_STATES = (
    "remapping_not_evaluated",
    "remapping_not_eligible",
    "remapping_not_executable",
    "remapping_available",
    "remapping_retry_exhausted",
    "remapping_blocked",
)
REMAPPING_EXECUTION_STATES = (
    "remapping_not_started",
    "remapping_running",
    "revision_created",
    "revision_no_safe_mapping",
    "remapping_failed",
)
HUMAN_WORKFLOW_STATES = (
    "human_review_pending",
    "human_accepted",
    "human_rejected",
)

STATE_GROUPS = {
    "mapping": MAPPING_STATES,
    "supervisor_eligibility": SUPERVISOR_ELIGIBILITY_STATES,
    "supervisor_execution": SUPERVISOR_EXECUTION_STATES,
    "remapping_eligibility": REMAPPING_ELIGIBILITY_STATES,
    "remapping_execution": REMAPPING_EXECUTION_STATES,
    "human_workflow": HUMAN_WORKFLOW_STATES,
}

HARD_INVALID_TRANSITIONS = {
    ("supervisor_completed", "remapping_running"),
    ("revision_created", "human_accepted"),
    ("human_review_pending", "human_accepted"),
    ("remapping_retry_exhausted", "remapping_running"),
    ("supervisor_blocked", "supervisor_running"),
    ("human_accepted", "remapping_running"),
    ("human_rejected", "remapping_running"),
    ("human_review_pending", "confirmed_tag_id"),
}

VALID_TRANSITIONS = {
    "mapping_suggested": {
        "supervisor_not_evaluated",
        "supervisor_not_eligible",
        "supervisor_eligible",
        "supervisor_blocked",
        "human_accepted",
        "human_rejected",
    },
    "mapping_no_safe_candidate": {
        "supervisor_not_evaluated",
        "supervisor_eligible",
        "supervisor_blocked",
    },
    "supervisor_not_evaluated": {
        "supervisor_not_eligible",
        "supervisor_eligible",
        "supervisor_blocked",
    },
    "supervisor_eligible": {"supervisor_pending"},
    "supervisor_pending": {"supervisor_running", "supervisor_skipped"},
    "supervisor_running": {"supervisor_completed", "supervisor_failed"},
    "supervisor_completed": {
        "remapping_not_eligible",
        "remapping_available",
        "remapping_retry_exhausted",
        "human_review_pending",
    },
    "remapping_available": {"remapping_running"},
    "remapping_running": {
        "revision_created",
        "revision_no_safe_mapping",
        "remapping_failed",
    },
    "revision_created": {"human_review_pending"},
    "revision_no_safe_mapping": {"human_review_pending"},
    "remapping_failed": {"human_review_pending"},
    "human_review_pending": {"human_accepted", "human_rejected"},
}

PRIORITY_RANK = {"low": 0, "medium": 1, "high": 2}
STRONG_SIGNAL_WEIGHTS = {
    "statement_family_mismatch": 4,
    "concept_family_mismatch": 4,
    "broad_substitute_with_concrete_alternative": 4,
    "severe_period_context_conflict": 3,
    "ranked_candidate_source_conflict": 3,
    "previous_supervisor_disagreement": 5,
    "no_safe_revised_mapping": 5,
    "explicit_human_request": 5,
}
WEAK_SIGNAL_WEIGHTS = {
    "requires_confirmation": 1,
    "mapper_confidence_below_threshold": 1,
    "generic_label": 1,
    "close_competing_candidates": 1,
    "incomplete_context": 1,
    "safe_flag_withheld_due_confidence": 0,
}
class SupervisorOrchestrationPolicyError(ValueError):
    pass


@dataclass(frozen=True)
class SupervisorEligibilityPolicyConfig:
    confidence_threshold: float = 0.85
    close_candidate_delta: float = 0.10
    min_priority: str = "medium"
    max_remap_retries: int = 1
    eligibility_score_threshold: int = 3
    weak_signal_count_threshold: int = 2
    weak_signal_score_threshold: int = 2
    high_priority_score: int = 5


@dataclass(frozen=True)
class SupervisorRiskAssessment:
    score: int
    strong_signals: tuple[str, ...]
    weak_signals: tuple[str, ...]
    evidence_reasons: tuple[str, ...]
    priority: str
    qualifies: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "strong_signals": list(self.strong_signals),
            "weak_signals": list(self.weak_signals),
            "evidence_reasons": list(self.evidence_reasons),
            "priority": self.priority,
            "qualifies": self.qualifies,
        }


@dataclass(frozen=True)
class SupervisorEligibilityDecision:
    classification: str
    eligible: bool
    eligibility_reasons: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    priority: str
    recommended_manual_action: str
    eligibility_score: int = 0
    strong_signals: tuple[str, ...] = ()
    weak_signals: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification,
            "eligible": self.eligible,
            "eligibility_reasons": list(self.eligibility_reasons),
            "blocking_reasons": list(self.blocking_reasons),
            "priority": self.priority,
            "recommended_manual_action": self.recommended_manual_action,
            "eligibility_score": self.eligibility_score,
            "strong_signals": list(self.strong_signals),
            "weak_signals": list(self.weak_signals),
        }


def is_valid_state_transition(
    current_state: str,
    next_state: str,
    *,
    explicit_human_action: bool = False,
) -> bool:
    transition = (current_state, next_state)
    if transition in HARD_INVALID_TRANSITIONS:
        return bool(
            explicit_human_action
            and transition
            in {
                ("revision_created", "human_accepted"),
                ("human_review_pending", "human_accepted"),
            }
        )
    return next_state in VALID_TRANSITIONS.get(current_state, set())


def assert_valid_state_transition(
    current_state: str,
    next_state: str,
    *,
    explicit_human_action: bool = False,
) -> None:
    if not is_valid_state_transition(
        current_state,
        next_state,
        explicit_human_action=explicit_human_action,
    ):
        raise SupervisorOrchestrationPolicyError(
            f"Invalid Supervisor orchestration transition: {current_state} -> {next_state}"
        )


def _value(record: Any, key: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(key, default)
    return getattr(record, key, default)


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _normalized(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").split())


def _flatten_text(value: Any) -> str:
    if isinstance(value, Mapping):
        return " ".join(
            f"{key} {_flatten_text(nested)}" for key, nested in value.items()
        )
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten_text(item) for item in value)
    return str(value or "")


def _latest_review(reviews: Sequence[Any]) -> Any | None:
    latest = [review for review in reviews if bool(_value(review, "is_latest", True))]
    candidates = latest or list(reviews)
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda review: (
            _value(review, "updated_at") or _value(review, "created_at") or "",
            int(_value(review, "review_attempt", 0) or 0),
            str(_value(review, "id", "")),
        ),
    )


def _candidate_rows(suggestion: Any) -> list[dict[str, Any]]:
    candidates = _json_value(_value(suggestion, "ranked_candidates_json"), [])
    return [dict(row) for row in candidates if isinstance(row, Mapping)]


def _diagnostic(suggestion: Any) -> dict[str, Any]:
    decoded = _json_value(_value(suggestion, "diagnostic_json"), {})
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _statement_family(value: Any) -> str:
    normalized = _normalized(value)
    if "cash flow" in normalized:
        return "cash_flow"
    if "financial position" in normalized or "balance sheet" in normalized:
        return "financial_position"
    if "changes in equity" in normalized:
        return "changes_in_equity"
    if "profit or loss" in normalized or "comprehensive income" in normalized:
        return "profit_or_loss"
    return normalized


def _candidate_qname(candidate: Mapping[str, Any]) -> str:
    return str(
        candidate.get("template_field_id")
        or candidate.get("concept_qname")
        or candidate.get("qname")
        or ""
    )


def _selected_candidate(
    suggestion: Any,
    candidates: Sequence[Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    selected_qname = str(
        _value(suggestion, "suggested_template_field_id", "") or ""
    )
    for candidate in candidates:
        candidate_qname = _candidate_qname(candidate)
        if selected_qname and candidate_qname == selected_qname:
            return candidate
    return candidates[0] if candidates else None


def _nested_suggestion_diagnostic(suggestion: Any) -> dict[str, Any]:
    diagnostic = _diagnostic(suggestion)
    nested = diagnostic.get("suggestion")
    return dict(nested) if isinstance(nested, Mapping) else {}


def _risk_evidence_text(
    suggestion: Any,
    *,
    candidates: Sequence[Mapping[str, Any]],
    selected: Mapping[str, Any] | None,
) -> str:
    diagnostic = _diagnostic(suggestion)
    nested = _nested_suggestion_diagnostic(suggestion)
    evidence: list[Any] = [
        _value(suggestion, "reason", ""),
        diagnostic.get("rejection_reason"),
        diagnostic.get("precheck_rejection_reason"),
        diagnostic.get("warning_level"),
        diagnostic.get("issue_type"),
        diagnostic.get("risk_reasons"),
        nested.get("reason"),
        nested.get("model_rejection_reason"),
        nested.get("rejection_reason"),
        nested.get("warning_level"),
        nested.get("issue_type"),
        nested.get("risk_reasons"),
    ]
    if _value(suggestion, "suggested_template_field_id") and selected is not None:
        evidence.append(selected.get("reason"))
    elif not _value(suggestion, "suggested_template_field_id"):
        evidence.extend(candidate.get("reason") for candidate in candidates)
    return _normalized(_flatten_text(evidence))


def _qname_statement_families(qname: Any) -> set[str]:
    token = re.sub(r"[^a-z0-9]", "", str(qname or "").lower())
    if not token:
        return set()
    if any(
        marker in token
        for marker in (
            "cashandcashequivalent",
            "cashandbank",
        )
    ):
        return {"cash_flow", "financial_position"}
    if any(
        marker in token
        for marker in (
            "cashflows",
            "increasedecreaseincash",
        )
    ):
        return {"cash_flow"}
    if any(
        marker in token
        for marker in (
            "profitloss",
            "taxexpense",
            "income",
            "revenue",
            "costofsales",
            "expense",
            "comprehensive",
        )
    ):
        return {"profit_or_loss"}
    if any(
        marker in token
        for marker in (
            "issuedcapital",
            "retainedearning",
        )
    ):
        return {"financial_position", "changes_in_equity"}
    if any(
        marker in token
        for marker in (
            "asset",
            "liabilit",
            "receivable",
            "payable",
            "equity",
            "propertyplantequipment",
        )
    ):
        return {"financial_position"}
    return set()


def _has_statement_family_mismatch(
    suggestion: Any,
    row: Any,
    *,
    candidates: Sequence[Mapping[str, Any]],
    selected: Mapping[str, Any] | None,
    evidence_text: str,
) -> bool:
    if selected is not None:
        row_family = _statement_family(_value(row, "statement_type"))
        candidate_family = _statement_family(
            selected.get("statement_type") or selected.get("statement_family")
        )
        if row_family and candidate_family and row_family != candidate_family:
            return True

        qname_families = _qname_statement_families(
            _value(suggestion, "suggested_template_field_id")
        )
        if row_family and qname_families and row_family not in qname_families:
            return True

    return any(
        phrase in evidence_text
        for phrase in (
            "statement family mismatch",
            "statement type mismatch",
            "statement context mismatch",
            "different statement type",
            "different statement family",
            "mismatch in statement type",
            "context mismatch",
            "contextually misaligned",
        )
    )


def _has_concept_family_mismatch(evidence_text: str) -> bool:
    return any(
        phrase in evidence_text
        for phrase in (
            "concept family mismatch",
            "incorrect concept family",
            "incorrect activity classification",
            "not semantically aligned",
            "semantic mismatch",
            "semantically misaligned",
        )
    )


def _has_broad_substitute_with_concrete_alternative(
    suggestion: Any,
    *,
    candidates: Sequence[Mapping[str, Any]],
    selected: Mapping[str, Any] | None,
    evidence_text: str,
) -> bool:
    selected_qname = str(
        _value(suggestion, "suggested_template_field_id", "") or ""
    )
    alternatives = [
        _candidate_qname(candidate)
        for candidate in candidates
        if _candidate_qname(candidate)
        and _candidate_qname(candidate) != selected_qname
    ]
    if not alternatives:
        return False
    if any(
        phrase in evidence_text
        for phrase in (
            "broad substitute",
            "broader summary",
            "too broad",
            "overbroad",
            "broad substitution",
        )
    ):
        return True

    normalized_qname = re.sub(r"[^a-z0-9]", "", selected_qname.lower())
    if "otherinflowsoutflowsofcashclassifiedas" not in normalized_qname:
        return False
    activity = next(
        (
            value
            for value in ("operating", "investing", "financing")
            if value in normalized_qname
        ),
        None,
    )
    return bool(
        activity
        and any(
            activity in re.sub(r"[^a-z0-9]", "", alternative.lower())
            and "cashflowsfromusedin" in re.sub(
                r"[^a-z0-9]", "", alternative.lower()
            )
            for alternative in alternatives
        )
    )


def _has_severe_period_context_conflict(evidence_text: str) -> bool:
    return any(
        phrase in evidence_text
        for phrase in (
            "beginning vs end",
            "beginning/end",
            "current/noncurrent",
            "current noncurrent",
            "period mismatch",
            "period timing",
            "temporally different",
        )
    )


def _has_generic_label(row: Any, evidence_text: str) -> bool:
    label = _normalized(_value(row, "extracted_label"))
    meaningful_tokens = [
        token for token in label.split() if any(character.isalpha() for character in token)
    ]
    return len(meaningful_tokens) <= 1 or any(
        phrase in evidence_text
        for phrase in (
            "generic label",
            "label lacks specificity",
            "label is too generic",
            "ambiguous label",
            "composite label",
        )
    )


def _has_incomplete_context(evidence_text: str) -> bool:
    return any(
        phrase in evidence_text
        for phrase in (
            "insufficient evidence",
            "lack of evidence",
            "lacks context",
            "lack of context",
            "without clear context",
            "not provide strong context",
        )
    )


def _safe_flag_withheld_only_for_confidence(review: Any | None) -> bool:
    if review is None:
        return False
    if _normalized(_value(review, "supervisor_decision")) != "agree":
        return False
    issues_text = _normalized(_flatten_text(_json_value(
        _value(review, "supervisor_issues_json"),
        [],
    )))
    return (
        "safe flag withheld" in issues_text
        and "confidence" in issues_text
    )


def _previous_supervisor_disagreement(review: Any | None) -> bool:
    if review is None:
        return False
    return (
        _normalized(_value(review, "review_status")) == "completed"
        and _normalized(_value(review, "supervisor_decision"))
        in {"disagree", "needs human review"}
    )


def _has_no_safe_revised_mapping(revisions: Sequence[Any]) -> bool:
    return any(
        _normalized(_value(revision, "status")) == "completed"
        and not _value(revision, "revised_suggested_qname")
        for revision in revisions
    )


def _requires_confirmation(suggestion: Any) -> bool:
    diagnostic = _diagnostic(suggestion)
    nested = _nested_suggestion_diagnostic(suggestion)
    for source in (diagnostic, nested):
        for key in (
            "requires_confirmation",
            "requires_human_confirmation",
            "requires_human_review",
        ):
            if source.get(key) is True:
                return True
    return any(
        candidate.get("requires_confirmation") is True
        for candidate in _candidate_rows(suggestion)
    )


def _has_close_competitors(suggestion: Any, delta: float) -> bool:
    confidences = sorted(
        [
            float(candidate.get("confidence"))
            for candidate in _candidate_rows(suggestion)
            if isinstance(candidate.get("confidence"), (int, float))
        ],
        reverse=True,
    )
    return (
        len(confidences) >= 2
        and abs(confidences[0] - confidences[1]) <= delta
    )


def assess_supervisor_risk(
    suggestion: Any,
    row: Any,
    *,
    reviews: Sequence[Any] = (),
    revisions: Sequence[Any] = (),
    explicit_human_request: bool = False,
    config: SupervisorEligibilityPolicyConfig | None = None,
) -> SupervisorRiskAssessment:
    effective = config or SupervisorEligibilityPolicyConfig()
    latest_review = _latest_review(reviews)
    candidates = _candidate_rows(suggestion)
    selected = _selected_candidate(suggestion, candidates)
    evidence_text = _risk_evidence_text(
        suggestion,
        candidates=candidates,
        selected=selected,
    )
    strong: list[str] = []
    weak: list[str] = []
    evidence_reasons: list[str] = []

    def add_strong(reason: str) -> None:
        if reason not in strong:
            strong.append(reason)

    def add_weak(reason: str) -> None:
        if reason not in weak:
            weak.append(reason)

    if (
        not _value(suggestion, "suggested_template_field_id")
        or _normalized(_value(suggestion, "status")) == "rejected"
    ):
        evidence_reasons.append("mapping_no_safe_candidate")
    if _has_statement_family_mismatch(
        suggestion,
        row,
        candidates=candidates,
        selected=selected,
        evidence_text=evidence_text,
    ):
        add_strong("statement_family_mismatch")
    if _has_concept_family_mismatch(evidence_text):
        add_strong("concept_family_mismatch")
    if _has_broad_substitute_with_concrete_alternative(
        suggestion,
        candidates=candidates,
        selected=selected,
        evidence_text=evidence_text,
    ):
        add_strong("broad_substitute_with_concrete_alternative")
    if _has_severe_period_context_conflict(evidence_text):
        add_strong("severe_period_context_conflict")
    if "source conflict" in evidence_text:
        add_strong("ranked_candidate_source_conflict")
    if _previous_supervisor_disagreement(latest_review):
        add_strong("previous_supervisor_disagreement")
    if _has_no_safe_revised_mapping(revisions):
        add_strong("no_safe_revised_mapping")
    if explicit_human_request:
        add_strong("explicit_human_request")

    has_selected_qname = bool(
        _value(suggestion, "suggested_template_field_id")
    )
    confidence = float(_value(suggestion, "confidence", 0.0) or 0.0)
    if _requires_confirmation(suggestion):
        add_weak("requires_confirmation")
    if has_selected_qname and confidence < effective.confidence_threshold:
        add_weak("mapper_confidence_below_threshold")
    if _has_generic_label(row, evidence_text):
        add_weak("generic_label")
    if _has_close_competitors(suggestion, effective.close_candidate_delta):
        add_weak("close_competing_candidates")
    if _has_incomplete_context(evidence_text):
        add_weak("incomplete_context")
    if _safe_flag_withheld_only_for_confidence(latest_review):
        add_weak("safe_flag_withheld_due_confidence")

    strong_score = sum(STRONG_SIGNAL_WEIGHTS[reason] for reason in strong)
    weak_score = sum(WEAK_SIGNAL_WEIGHTS[reason] for reason in weak)
    score = strong_score + weak_score
    positive_weak_count = sum(
        1 for reason in weak if WEAK_SIGNAL_WEIGHTS[reason] > 0
    )
    qualifies = bool(
        explicit_human_request
        or bool(strong)
        and score >= effective.eligibility_score_threshold
        or has_selected_qname
        and positive_weak_count >= effective.weak_signal_count_threshold
        and weak_score >= effective.weak_signal_score_threshold
    )
    priority = (
        "high"
        if qualifies and strong_score >= effective.high_priority_score
        else "medium"
        if qualifies
        else "low"
    )
    return SupervisorRiskAssessment(
        score=score,
        strong_signals=tuple(strong),
        weak_signals=tuple(weak),
        evidence_reasons=tuple(evidence_reasons),
        priority=priority,
        qualifies=qualifies,
    )


def _local_risk_signals(
    suggestion: Any,
    row: Any,
    *,
    config: SupervisorEligibilityPolicyConfig,
) -> tuple[list[str], str]:
    assessment = assess_supervisor_risk(
        suggestion,
        row,
        config=config,
    )
    return (
        list(
            assessment.evidence_reasons
            + assessment.strong_signals
            + assessment.weak_signals
        ),
        assessment.priority,
    )


def evaluate_supervisor_eligibility(
    suggestion: Any,
    *,
    row: Any | None = None,
    reviews: Sequence[Any] = (),
    revisions: Sequence[Any] = (),
    explicit_human_request: bool = False,
    config: SupervisorEligibilityPolicyConfig | None = None,
) -> SupervisorEligibilityDecision:
    """Classify one suggestion using persisted/local evidence only."""

    effective = config or SupervisorEligibilityPolicyConfig()
    status = _normalized(_value(suggestion, "status", "suggested"))
    row = row or _value(suggestion, "extracted_data_item")
    latest_review = _latest_review(reviews)
    assessment = (
        assess_supervisor_risk(
            suggestion,
            row,
            reviews=reviews,
            revisions=revisions,
            explicit_human_request=explicit_human_request,
            config=effective,
        )
        if row is not None and _normalized(_value(row, "extracted_label"))
        else None
    )

    def risk_fields() -> dict[str, Any]:
        if assessment is None:
            return {}
        return {
            "eligibility_score": assessment.score,
            "strong_signals": assessment.strong_signals,
            "weak_signals": assessment.weak_signals,
        }

    if is_human_terminal(status):
        human_state = "human_accepted" if status == "accepted" else "human_rejected"
        return SupervisorEligibilityDecision(
            classification="terminal",
            eligible=False,
            eligibility_reasons=(),
            blocking_reasons=(human_state,),
            priority="low",
            recommended_manual_action="no_action",
            **risk_fields(),
        )

    if revisions:
        return SupervisorEligibilityDecision(
            classification="already_reviewed",
            eligible=False,
            eligibility_reasons=(),
            blocking_reasons=("suggestion_superseded_by_revision",),
            priority="low",
            recommended_manual_action="inspect_revision",
            **risk_fields(),
        )

    if latest_review is not None:
        review_status = _normalized(_value(latest_review, "review_status"))
        decision = _normalized(_value(latest_review, "supervisor_decision"))
        risk = _normalized(_value(latest_review, "supervisor_risk_level"))
        if review_status in {"pending", "running"}:
            return SupervisorEligibilityDecision(
                classification="blocked",
                eligible=False,
                eligibility_reasons=(),
                blocking_reasons=(f"supervisor_{review_status}",),
                priority="medium",
                recommended_manual_action="no_action",
                **risk_fields(),
            )
        if review_status == "failed":
            return SupervisorEligibilityDecision(
                classification="blocked",
                eligible=False,
                eligibility_reasons=(),
                blocking_reasons=("supervisor_failed",),
                priority="high",
                recommended_manual_action="review_without_llm",
                **risk_fields(),
            )
        if review_status == "completed":
            reason = (
                "completed_low_risk_agree_review"
                if decision == "agree" and risk == "low"
                else "completed_supervisor_review"
            )
            return SupervisorEligibilityDecision(
                classification="already_reviewed",
                eligible=False,
                eligibility_reasons=(),
                blocking_reasons=(reason,),
                priority=risk if risk in PRIORITY_RANK else "medium",
                recommended_manual_action="no_action",
                **risk_fields(),
            )

    if row is None or not _normalized(_value(row, "extracted_label")):
        return SupervisorEligibilityDecision(
            classification="blocked",
            eligible=False,
            eligibility_reasons=(),
            blocking_reasons=("no_usable_row_context",),
            priority="high",
            recommended_manual_action="review_without_llm",
        )

    if assessment is None:
        raise SupervisorOrchestrationPolicyError(
            "Supervisor risk assessment unexpectedly unavailable"
        )
    reasons = list(
        assessment.evidence_reasons
        + assessment.strong_signals
        + assessment.weak_signals
    )
    if not assessment.qualifies:
        blocking_reason = (
            "weak_signals_do_not_independently_enqueue"
            if reasons
            else "high_confidence_no_local_risk_issue"
        )
        return SupervisorEligibilityDecision(
            classification="not_eligible",
            eligible=False,
            eligibility_reasons=tuple(reasons),
            blocking_reasons=(blocking_reason,),
            priority="low",
            recommended_manual_action=(
                "review_without_llm"
                if "mapping_no_safe_candidate" in reasons
                else "no_action"
            ),
            **risk_fields(),
        )
    if PRIORITY_RANK[assessment.priority] < PRIORITY_RANK.get(
        effective.min_priority,
        1,
    ):
        return SupervisorEligibilityDecision(
            classification="not_eligible",
            eligible=False,
            eligibility_reasons=tuple(reasons),
            blocking_reasons=("below_configured_priority_threshold",),
            priority=assessment.priority,
            recommended_manual_action="review_without_llm",
            **risk_fields(),
        )
    return SupervisorEligibilityDecision(
        classification="eligible",
        eligible=True,
        eligibility_reasons=tuple(reasons),
        blocking_reasons=(),
        priority=assessment.priority,
        recommended_manual_action="run_supervisor_review",
        **risk_fields(),
    )


def evaluate_remapping_eligibility(
    suggestion: Any,
    *,
    reviews: Sequence[Any] = (),
    revisions: Sequence[Any] = (),
    max_retries: int = 1,
) -> dict[str, Any]:
    latest_review = _latest_review(reviews)
    feedback_eligible, feedback_reason = supervisor_feedback_eligibility(latest_review)
    actionability = remapping_actionability(
        suggestion,
        latest_review=latest_review,
        revisions=revisions,
        feedback_eligible=feedback_eligible,
        feedback_reason=feedback_reason,
        feature_enabled=True,
        authorized=True,
        auto_run=False,
        max_retries=max_retries,
    )
    return {
        "state": actionability.state,
        "available": actionability.executable,
        "eligible": actionability.eligible,
        "executable": actionability.executable,
        "reasons": [actionability.block_reason] if actionability.block_reason else [],
    }


def derive_orchestration_state(
    suggestion: Any,
    *,
    supervisor_decision: SupervisorEligibilityDecision,
    reviews: Sequence[Any] = (),
    revisions: Sequence[Any] = (),
    max_retries: int = 1,
) -> dict[str, str]:
    status = _normalized(_value(suggestion, "status", "suggested"))
    latest_review = _latest_review(reviews)
    latest_revision = revisions[-1] if revisions else None
    mapping_state = (
        "mapping_failed"
        if status == "failed"
        else "mapping_no_safe_candidate"
        if status == "rejected" or not _value(suggestion, "suggested_template_field_id")
        else "mapping_suggested"
    )
    human_state = (
        "human_accepted"
        if status == "accepted"
        else "human_rejected"
        if is_human_terminal(status)
        else "human_review_pending"
    )
    supervisor_eligibility_state = {
        "eligible": "supervisor_eligible",
        "not_eligible": "supervisor_not_eligible",
        "blocked": "supervisor_blocked",
        "already_reviewed": "supervisor_not_eligible",
        "terminal": "supervisor_blocked",
    }[supervisor_decision.classification]
    review_status = _normalized(_value(latest_review, "review_status")) if latest_review else ""
    supervisor_execution_state = {
        "pending": "supervisor_pending",
        "running": "supervisor_running",
        "completed": "supervisor_completed",
        "failed": "supervisor_failed",
        "skipped": "supervisor_skipped",
    }.get(review_status, "supervisor_pending")
    remapping = evaluate_remapping_eligibility(
        suggestion,
        reviews=reviews,
        revisions=revisions,
        max_retries=max_retries,
    )
    revision_status = _normalized(_value(latest_revision, "status")) if latest_revision else ""
    remapping_execution_state = (
        "remapping_running"
        if revision_status == "running"
        else "remapping_failed"
        if revision_status == "failed"
        else "revision_no_safe_mapping"
        if revision_status == "completed" and not _value(latest_revision, "revised_suggested_qname")
        else "revision_created"
        if revision_status == "completed"
        else "remapping_not_started"
    )

    if human_state in {"human_accepted", "human_rejected"}:
        primary = human_state
    elif revision_status == "completed":
        primary = remapping_execution_state
    elif revision_status == "failed":
        primary = "remapping_failed"
    elif review_status in {"running", "failed"}:
        primary = supervisor_execution_state
    elif remapping["state"] == "remapping_available":
        primary = "remapping_available"
    elif review_status == "completed":
        primary = "supervisor_completed"
    else:
        primary = supervisor_eligibility_state

    return {
        "primary": primary,
        "mapping": mapping_state,
        "supervisor_eligibility": supervisor_eligibility_state,
        "supervisor_execution": supervisor_execution_state,
        "remapping_eligibility": remapping["state"],
        "remapping_execution": remapping_execution_state,
        "human_workflow": human_state,
    }
