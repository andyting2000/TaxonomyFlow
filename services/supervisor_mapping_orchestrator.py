"""Disabled-by-default orchestration planner for Supervisor-guided mapping.

The public planning path is read-only and local. Existing manual review and
correction services may be delegated to only by explicit manual methods; this
module provides no automatic/background execution loop.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Sequence

from config import settings
from sqlalchemy.ext.asyncio import AsyncSession

from services.supervisor_guided_mapping_correction import (
    SupervisorGuidedCorrectionConfig,
    list_supervisor_guided_revisions_for_job,
    run_supervisor_guided_mapping_correction,
)
from services.supervisor_orchestration_policy import (
    SupervisorEligibilityPolicyConfig,
    derive_orchestration_state,
    evaluate_supervisor_eligibility,
)
from services.suggestion_actionability import (
    is_human_terminal,
    remapping_actionability,
    supervisor_review_actionability,
)
from services.supervisor_mapper_feedback import supervisor_feedback_eligibility
from services.supervisor_production_review import (
    list_ai_mapping_suggestions_for_supervisor,
    list_supervisor_reviews_for_job,
    load_owned_supervisor_job,
    run_supervisor_review_for_suggestion,
    run_supervisor_reviews_for_job,
)
from services.supervisor_rollout_authorization import (
    authorize_supervisor_rollout_user,
    parse_supervisor_reviewer_allowlist,
    supervisor_rollout_denial_reason,
)


class SupervisorOrchestrationError(ValueError):
    pass


class SupervisorOrchestrationDisabled(SupervisorOrchestrationError):
    pass


class SupervisorOrchestrationForbidden(SupervisorOrchestrationError):
    pass


class SupervisorOrchestrationNotFound(SupervisorOrchestrationError):
    pass


class SupervisorOrchestrationUnsafeConfig(SupervisorOrchestrationError):
    pass


class SupervisorOrchestrationBatchLimit(SupervisorOrchestrationError):
    pass


@dataclass(frozen=True)
class SupervisorOrchestrationConfig:
    enabled: bool = False
    default_mode: str = "manual"
    auto_eligibility: bool = True
    auto_review: bool = False
    auto_remap: bool = False
    admin_only: bool = True
    max_batch_size: int = 10
    max_remap_retries: int = 1
    min_risk: str = "medium"
    max_concurrent_live_calls: int = 2
    confidence_threshold: float = 0.85
    per_row_timeout_seconds: float = 120.0
    review_execution_enabled: bool = False
    review_execution_admin_only: bool = True
    remap_execution_enabled: bool = False
    remap_execution_auto_run: bool = False
    remap_execution_admin_only: bool = True
    remap_execution_max_retries: int = 1
    allowed_user_ids: Any = ""

    @classmethod
    def from_settings(cls, settings_obj: Any = settings) -> "SupervisorOrchestrationConfig":
        return cls(
            enabled=bool(
                getattr(settings_obj, "supervisor_orchestration_enabled", False)
            ),
            default_mode=str(
                getattr(settings_obj, "supervisor_orchestration_default_mode", "manual")
                or "manual"
            ).strip().lower(),
            auto_eligibility=bool(
                getattr(settings_obj, "supervisor_orchestration_auto_eligibility", True)
            ),
            auto_review=bool(
                getattr(settings_obj, "supervisor_orchestration_auto_review", False)
            ),
            auto_remap=bool(
                getattr(settings_obj, "supervisor_orchestration_auto_remap", False)
            ),
            admin_only=bool(
                getattr(settings_obj, "supervisor_orchestration_admin_only", True)
            ),
            max_batch_size=max(
                1,
                int(
                    getattr(
                        settings_obj,
                        "supervisor_orchestration_max_batch_size",
                        10,
                    )
                    or 10
                ),
            ),
            max_remap_retries=max(
                0,
                int(
                    getattr(
                        settings_obj,
                        "supervisor_orchestration_max_remap_retries",
                        1,
                    )
                    or 0
                ),
            ),
            min_risk=str(
                getattr(settings_obj, "supervisor_orchestration_min_risk", "medium")
                or "medium"
            ).strip().lower(),
            max_concurrent_live_calls=max(
                1,
                int(
                    getattr(
                        settings_obj,
                        "supervisor_orchestration_max_concurrent_live_calls",
                        2,
                    )
                    or 2
                ),
            ),
            confidence_threshold=min(
                1.0,
                max(
                    0.0,
                    float(
                        getattr(
                            settings_obj,
                            "supervisor_orchestration_confidence_threshold",
                            0.85,
                        )
                        or 0.85
                    ),
                ),
            ),
            per_row_timeout_seconds=max(
                1.0,
                float(
                    getattr(
                        settings_obj,
                        "supervisor_orchestration_per_row_timeout_seconds",
                        120.0,
                    )
                    or 120.0
                ),
            ),
            review_execution_enabled=bool(
                getattr(settings_obj, "supervisor_production_live_enabled", False)
            ),
            review_execution_admin_only=bool(
                getattr(settings_obj, "supervisor_production_live_admin_only", True)
            ),
            remap_execution_enabled=bool(
                getattr(settings_obj, "supervisor_mapper_feedback_enabled", False)
            ),
            remap_execution_auto_run=bool(
                getattr(settings_obj, "supervisor_mapper_feedback_auto_run", False)
            ),
            remap_execution_admin_only=bool(
                getattr(settings_obj, "supervisor_mapper_feedback_admin_only", True)
            ),
            remap_execution_max_retries=max(
                0,
                int(
                    getattr(
                        settings_obj,
                        "supervisor_mapper_feedback_max_retries",
                        1,
                    )
                    or 0
                ),
            ),
            allowed_user_ids=getattr(
                settings_obj,
                "supervisor_orchestration_allowed_user_ids",
                "",
            ),
        )

    def policy_config(self) -> SupervisorEligibilityPolicyConfig:
        return SupervisorEligibilityPolicyConfig(
            confidence_threshold=self.confidence_threshold,
            min_priority=self.min_risk,
            max_remap_retries=self.max_remap_retries,
        )

    def unsafe_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.default_mode != "manual":
            reasons.append("default_mode_must_be_manual")
        if self.auto_review:
            reasons.append("automatic_supervisor_review_is_forbidden")
        if self.auto_remap:
            reasons.append("automatic_remapping_is_forbidden")
        if self.remap_execution_auto_run:
            reasons.append("automatic_mapper_feedback_is_forbidden")
        if self.max_remap_retries > 1:
            reasons.append("maximum_one_correction_attempt_is_supported")
        if self.remap_execution_max_retries > 1:
            reasons.append("maximum_one_mapper_feedback_attempt_is_supported")
        if self.min_risk not in {"low", "medium", "high"}:
            reasons.append("invalid_min_risk")
        if not parse_supervisor_reviewer_allowlist(self.allowed_user_ids).valid:
            reasons.append("invalid_internal_reviewer_allowlist")
        return reasons

    def assert_safe(self) -> None:
        reasons = self.unsafe_reasons()
        if reasons:
            raise SupervisorOrchestrationUnsafeConfig(
                "Unsafe Supervisor orchestration configuration: " + ", ".join(reasons)
            )


def supervisor_orchestration_capabilities(
    *,
    job_id: int,
    is_admin: bool,
    user_id: int | None = None,
    config: SupervisorOrchestrationConfig | None = None,
) -> dict[str, Any]:
    effective = config or SupervisorOrchestrationConfig.from_settings()
    unsafe_reasons = effective.unsafe_reasons()
    authorization = authorize_supervisor_rollout_user(
        user_id=user_id,
        is_admin=is_admin,
        allowed_user_ids=effective.allowed_user_ids,
    )
    authorized = authorization.authorized
    return {
        "job_id": job_id,
        "enabled": effective.enabled,
        "available": effective.enabled and authorized and not unsafe_reasons,
        "authorized": authorized,
        "mode": effective.default_mode,
        "plan_only": True,
        "auto_eligibility": effective.auto_eligibility,
        "auto_review": False,
        "auto_remap": False,
        "admin_only": effective.admin_only,
        "authorization_policy": "admin_or_explicit_internal_reviewer",
        "authorization_source": authorization.source,
        "internal_reviewer": authorization.internal_reviewer,
        "reviewer_allowlist_configured": authorization.allowlist_configured,
        "reviewer_allowlist_user_count": authorization.allowlist_user_count,
        "max_batch_size": effective.max_batch_size,
        "max_remap_retries": effective.max_remap_retries,
        "min_risk": effective.min_risk,
        "max_concurrent_live_calls": effective.max_concurrent_live_calls,
        "per_row_timeout_seconds": effective.per_row_timeout_seconds,
        "review_execution_enabled": effective.review_execution_enabled,
        "review_execution_authorized": authorized,
        "remap_execution_enabled": effective.remap_execution_enabled,
        "remap_execution_authorized": authorized,
        "unsafe_configuration_reasons": unsafe_reasons,
        "manual_execution_endpoints": {
            "single_review": f"/api/v1/filings/jobs/{job_id}/supervisor-reviews/run",
            "batch_review": f"/api/v1/filings/jobs/{job_id}/supervisor-reviews/run-batch",
            "single_remap": (
                f"/api/v1/filings/jobs/{job_id}/suggestions/"
                "{suggestion_id}/remap-with-supervisor-feedback"
            ),
        },
        "safety": {
            "planning_external_calls": 0,
            "automatic_review_supported": False,
            "automatic_remap_supported": False,
            "auto_apply_supported": False,
            "confirmed_tag_id_automation_supported": False,
            "final_mapping_mutation_supported": False,
        },
    }


def _latest_by_created(records: Sequence[Any]) -> Any | None:
    if not records:
        return None
    latest_records = [
        record for record in records if bool(getattr(record, "is_latest", True))
    ]
    candidates = latest_records or list(records)
    return max(
        candidates,
        key=lambda record: (
            str(getattr(record, "updated_at", None) or getattr(record, "created_at", None) or ""),
            int(getattr(record, "review_attempt", 0) or 0),
            str(getattr(record, "id", "")),
        ),
    )


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, (list, dict)):
        return value
    if not value:
        return fallback
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _requires_confirmation(suggestion: Any) -> bool:
    diagnostic = _json_value(getattr(suggestion, "diagnostic_json", None), {})
    if isinstance(diagnostic, Mapping):
        nested = diagnostic.get("suggestion")
        sources = (
            diagnostic,
            nested if isinstance(nested, Mapping) else {},
        )
        for source in sources:
            for key in (
                "requires_confirmation",
                "requires_human_confirmation",
                "requires_human_review",
            ):
                if source.get(key) is True:
                    return True
    candidates = _json_value(getattr(suggestion, "ranked_candidates_json", None), [])
    return any(
        isinstance(candidate, Mapping)
        and candidate.get("requires_confirmation") is True
        for candidate in candidates
    )


def _group_by(records: Sequence[Any], field: str) -> dict[str, list[Any]]:
    grouped: dict[str, list[Any]] = {}
    for record in records:
        key = str(getattr(record, field, "") or "")
        if key:
            grouped.setdefault(key, []).append(record)
    return grouped


def build_supervisor_orchestration_plan(
    *,
    job: Any,
    suggestions: Sequence[Any],
    reviews: Sequence[Any],
    revisions: Sequence[Any],
    config: SupervisorOrchestrationConfig,
    is_admin: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Build a deterministic queue from already-loaded records."""

    config.assert_safe()
    authorization = authorize_supervisor_rollout_user(
        user_id=user_id,
        is_admin=is_admin,
        allowed_user_ids=config.allowed_user_ids,
    )
    reviews_by_suggestion = _group_by(reviews, "llm_mapping_suggestion_id")
    revisions_by_suggestion = _group_by(revisions, "parent_suggestion_id")
    items: list[dict[str, Any]] = []
    counts = {
        "eligible": 0,
        "review_executable": 0,
        "batch_review_executable": 0,
        "high_priority": 0,
        "medium_priority": 0,
        "not_eligible": 0,
        "blocked": 0,
        "already_reviewed": 0,
        "terminal": 0,
        "remapping_eligible": 0,
        "remapping_executable": 0,
        "revision_created": 0,
    }

    for suggestion in suggestions:
        suggestion_reviews = reviews_by_suggestion.get(str(suggestion.id), [])
        suggestion_revisions = revisions_by_suggestion.get(str(suggestion.id), [])
        row = getattr(suggestion, "extracted_data_item", None)
        latest_review = _latest_by_created(suggestion_reviews)
        latest_revision = _latest_by_created(suggestion_revisions)
        eligibility = evaluate_supervisor_eligibility(
            suggestion,
            row=row,
            reviews=suggestion_reviews,
            revisions=suggestion_revisions,
            config=config.policy_config(),
        )
        review_execution_authorized = authorization.authorized
        review_actionability = supervisor_review_actionability(
            suggestion,
            policy_classification=eligibility.classification,
            latest_review=latest_review,
            latest_revision=latest_revision,
            feature_enabled=config.review_execution_enabled,
            authorized=review_execution_authorized,
        )
        feedback_eligible, feedback_reason = supervisor_feedback_eligibility(
            latest_review
        )
        effective_remap_retries = min(
            config.max_remap_retries,
            config.remap_execution_max_retries,
        )
        remapping = remapping_actionability(
            suggestion,
            latest_review=latest_review,
            revisions=suggestion_revisions,
            feedback_eligible=feedback_eligible,
            feedback_reason=feedback_reason,
            feature_enabled=config.remap_execution_enabled,
            authorized=authorization.authorized,
            auto_run=config.remap_execution_auto_run,
            max_retries=effective_remap_retries,
        )
        state = derive_orchestration_state(
            suggestion,
            supervisor_decision=eligibility,
            reviews=suggestion_reviews,
            revisions=suggestion_revisions,
            max_retries=effective_remap_retries,
        )
        state["remapping_eligibility"] = remapping.state
        if (
            state["primary"] == "remapping_available"
            and not remapping.executable
        ):
            state["primary"] = "supervisor_completed"
        counts[eligibility.classification] += 1
        if eligibility.classification == "eligible":
            if eligibility.priority == "high":
                counts["high_priority"] += 1
            elif eligibility.priority == "medium":
                counts["medium_priority"] += 1
        if review_actionability.executable:
            counts["review_executable"] += 1
        if review_actionability.batch_executable:
            counts["batch_review_executable"] += 1
        if remapping.eligible:
            counts["remapping_eligible"] += 1
        if remapping.executable:
            counts["remapping_executable"] += 1
        if latest_revision is not None:
            counts["revision_created"] += 1

        recommended_action = eligibility.recommended_manual_action
        if latest_revision is not None:
            recommended_action = "inspect_revision"
        elif remapping.executable:
            recommended_action = "run_guided_remap"
        elif review_actionability.executable:
            recommended_action = "run_supervisor_review"

        items.append(
            {
                "suggestion_id": str(suggestion.id),
                "row_id": str(getattr(suggestion, "extracted_data_item_id", "")),
                "row_label": getattr(row, "extracted_label", None),
                "statement_family": getattr(row, "statement_type", None),
                "initial_qname": getattr(
                    suggestion, "suggested_template_field_id", None
                ),
                "confidence": float(getattr(suggestion, "confidence", 0.0) or 0.0),
                "mapper_status": str(getattr(suggestion, "status", "") or ""),
                "is_human_terminal": is_human_terminal(suggestion),
                "requires_confirmation": _requires_confirmation(suggestion),
                "orchestration_state": state["primary"],
                "state_details": state,
                "supervisor_eligibility": eligibility.classification,
                "eligibility_reasons": list(eligibility.eligibility_reasons),
                "blocking_reasons": list(eligibility.blocking_reasons),
                "priority": eligibility.priority,
                "eligibility_score": eligibility.eligibility_score,
                "strong_signals": list(eligibility.strong_signals),
                "weak_signals": list(eligibility.weak_signals),
                "supervisor_review_executable": review_actionability.executable,
                "supervisor_action_block_reason": review_actionability.block_reason,
                "batch_review_executable": review_actionability.batch_executable,
                "existing_supervisor_review_id": (
                    str(latest_review.id) if latest_review is not None else None
                ),
                "supervisor_decision": (
                    getattr(latest_review, "supervisor_decision", None)
                    if latest_review is not None
                    else None
                ),
                "remapping_eligibility": remapping.state,
                "remapping_eligible": remapping.eligible,
                "remapping_executable": remapping.executable,
                "remapping_action_block_reason": remapping.block_reason,
                "existing_revision_id": (
                    str(latest_revision.id) if latest_revision is not None else None
                ),
                "correction_attempts_used": len(suggestion_revisions),
                "recommended_manual_action": recommended_action,
                "requires_human_review": True,
                "safe_for_auto_apply": False,
                "provenance": {
                    "job_id": job.id,
                    "row_id": str(getattr(suggestion, "extracted_data_item_id", "")),
                    "suggestion_id": str(suggestion.id),
                    "supervisor_review_id": (
                        str(latest_review.id) if latest_review is not None else None
                    ),
                    "revision_id": (
                        str(latest_revision.id) if latest_revision is not None else None
                    ),
                    "supervisor_prompt_version": (
                        getattr(latest_review, "supervisor_prompt_version", None)
                        if latest_review is not None
                        else None
                    ),
                    "supervisor_model_provider": (
                        getattr(latest_review, "supervisor_model_provider", None)
                        if latest_review is not None
                        else None
                    ),
                    "supervisor_model_id": (
                        getattr(latest_review, "supervisor_model_id", None)
                        if latest_review is not None
                        else None
                    ),
                    "review_user_id": (
                        getattr(latest_review, "user_id", None)
                        if latest_review is not None
                        else None
                    ),
                    "correction_attempt": (
                        getattr(latest_revision, "correction_attempt", None)
                        if latest_revision is not None
                        else None
                    ),
                    "original_qname": getattr(
                        suggestion, "suggested_template_field_id", None
                    ),
                    "revised_qname": (
                        getattr(latest_revision, "revised_suggested_qname", None)
                        if latest_revision is not None
                        else None
                    ),
                },
            }
        )

    return {
        "job_id": int(job.id),
        "filing_id": int(job.id),
        "orchestration_enabled": config.enabled,
        "authorization_source": authorization.source,
        "mode": "plan_only",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_suggestions": len(suggestions),
        "policy_eligible_count": counts["eligible"],
        "eligible_count": counts["eligible"],
        "review_executable_count": counts["review_executable"],
        "batch_review_executable_count": counts["batch_review_executable"],
        "high_priority_count": counts["high_priority"],
        "medium_priority_count": counts["medium_priority"],
        "not_eligible_count": counts["not_eligible"] + counts["terminal"],
        "blocked_count": counts["blocked"],
        "already_reviewed_count": counts["already_reviewed"],
        "remapping_eligible_count": counts["remapping_eligible"],
        "remapping_executable_count": counts["remapping_executable"],
        "remapping_available_count": counts["remapping_executable"],
        "revision_completed_count": counts["revision_created"],
        "revision_created_count": counts["revision_created"],
        "items": items,
        "safety_summary": {
            "planning_live_calls": 0,
            "auto_review_calls": 0,
            "auto_remap_calls": 0,
            "external_calls": 0,
            "supervisor_calls": 0,
            "mapper_calls": 0,
            "automatic_reviews": 0,
            "automatic_remaps": 0,
            "auto_apply_count": 0,
            "auto_accept_count": 0,
            "auto_reject_count": 0,
            "confirmed_tag_id_mutations": 0,
            "final_mapping_mutations": 0,
            "human_review_required": True,
            "requires_human_review_count": len(items),
            "safe_for_auto_apply_count": 0,
            "estimated_live_calls": 0,
            "estimated_manual_live_calls_if_all_eligible_selected": min(
                counts["review_executable"],
                config.max_batch_size,
            ),
            "eligible_over_manual_batch_limit": max(
                0,
                counts["review_executable"] - config.max_batch_size,
            ),
        },
    }


async def plan_supervisor_orchestration_for_job(
    db: AsyncSession,
    *,
    job_id: int,
    user_id: int,
    is_admin: bool,
    config: SupervisorOrchestrationConfig | None = None,
) -> dict[str, Any]:
    effective = config or SupervisorOrchestrationConfig.from_settings()
    job = await load_owned_supervisor_job(db, job_id=job_id, user_id=user_id)
    if job is None:
        raise SupervisorOrchestrationNotFound("Filing job not found")
    if not effective.enabled:
        raise SupervisorOrchestrationDisabled(
            "Supervisor orchestration planning is disabled."
        )
    authorization = authorize_supervisor_rollout_user(
        user_id=user_id,
        is_admin=is_admin,
        allowed_user_ids=effective.allowed_user_ids,
    )
    if not authorization.authorized:
        raise SupervisorOrchestrationForbidden(
            supervisor_rollout_denial_reason(authorization)
        )
    effective.assert_safe()
    suggestions = await list_ai_mapping_suggestions_for_supervisor(db, job_id=job.id)
    reviews = await list_supervisor_reviews_for_job(db, job_id=job.id)
    revisions = await list_supervisor_guided_revisions_for_job(db, job_id=job.id)
    return build_supervisor_orchestration_plan(
        job=job,
        suggestions=suggestions,
        reviews=reviews,
        revisions=revisions,
        config=effective,
        is_admin=is_admin,
        user_id=user_id,
    )


async def _await_bounded(
    awaitable: Awaitable[Any],
    *,
    timeout_seconds: float,
) -> Any:
    return await asyncio.wait_for(awaitable, timeout=timeout_seconds)


def _assert_manual_request(
    *,
    explicit_manual_request: bool,
    user_id: int,
    is_admin: bool,
    config: SupervisorOrchestrationConfig,
) -> None:
    if not explicit_manual_request:
        raise SupervisorOrchestrationForbidden(
            "Explicit manual action is required for Supervisor orchestration execution."
        )
    if not config.enabled:
        raise SupervisorOrchestrationDisabled("Supervisor orchestration is disabled.")
    authorization = authorize_supervisor_rollout_user(
        user_id=user_id,
        is_admin=is_admin,
        allowed_user_ids=config.allowed_user_ids,
    )
    if not authorization.authorized:
        raise SupervisorOrchestrationForbidden(
            supervisor_rollout_denial_reason(authorization)
        )
    config.assert_safe()


async def run_manual_single_review(
    db: AsyncSession,
    *,
    job_id: int,
    suggestion_id: str,
    user_id: int,
    is_admin: bool,
    explicit_manual_request: bool,
    source: str = "live",
    config: SupervisorOrchestrationConfig | None = None,
    delegate: Callable[..., Awaitable[Any]] | None = None,
) -> Any:
    effective = config or SupervisorOrchestrationConfig.from_settings()
    _assert_manual_request(
        explicit_manual_request=explicit_manual_request,
        user_id=user_id,
        is_admin=is_admin,
        config=effective,
    )
    runner = delegate or run_supervisor_review_for_suggestion
    return await _await_bounded(
        runner(
            db,
            job_id=job_id,
            suggestion_id=suggestion_id,
            user_id=user_id,
            force_refresh=False,
            source=source,
        ),
        timeout_seconds=effective.per_row_timeout_seconds,
    )


async def run_manual_batch_reviews(
    db: AsyncSession,
    *,
    job_id: int,
    user_id: int,
    is_admin: bool,
    requested_count: int,
    explicit_manual_request: bool,
    source: str = "live",
    config: SupervisorOrchestrationConfig | None = None,
    delegate: Callable[..., Awaitable[Any]] | None = None,
) -> Any:
    effective = config or SupervisorOrchestrationConfig.from_settings()
    _assert_manual_request(
        explicit_manual_request=explicit_manual_request,
        user_id=user_id,
        is_admin=is_admin,
        config=effective,
    )
    if requested_count > effective.max_batch_size:
        raise SupervisorOrchestrationBatchLimit(
            f"Requested batch size {requested_count} exceeds maximum "
            f"{effective.max_batch_size}."
        )
    runner = delegate or run_supervisor_reviews_for_job
    # Existing batch execution is sequential, so live concurrency remains one.
    return await _await_bounded(
        runner(
            db,
            job_id=job_id,
            user_id=user_id,
            force_refresh=False,
            source=source,
            max_batch_size=effective.max_batch_size,
        ),
        timeout_seconds=effective.per_row_timeout_seconds * max(1, requested_count),
    )


async def run_manual_guided_remap(
    db: AsyncSession,
    *,
    job_id: int,
    suggestion_id: str,
    user_id: int,
    is_admin: bool,
    explicit_manual_request: bool,
    config: SupervisorOrchestrationConfig | None = None,
    correction_config: SupervisorGuidedCorrectionConfig | None = None,
    delegate: Callable[..., Awaitable[Any]] | None = None,
) -> Any:
    effective = config or SupervisorOrchestrationConfig.from_settings()
    _assert_manual_request(
        explicit_manual_request=explicit_manual_request,
        user_id=user_id,
        is_admin=is_admin,
        config=effective,
    )
    runner = delegate or run_supervisor_guided_mapping_correction
    configured_correction = (
        correction_config or SupervisorGuidedCorrectionConfig.from_settings()
    )
    bounded_correction_config = SupervisorGuidedCorrectionConfig(
        enabled=configured_correction.enabled,
        auto_run=configured_correction.auto_run,
        max_retries=min(
            1,
            effective.max_remap_retries,
            configured_correction.max_retries,
        ),
        admin_only=configured_correction.admin_only,
        allowed_user_ids=configured_correction.allowed_user_ids,
    )
    return await _await_bounded(
        runner(
            db,
            job_id=job_id,
            suggestion_id=suggestion_id,
            user_id=user_id,
            is_admin=is_admin,
            config=bounded_correction_config,
        ),
        timeout_seconds=effective.per_row_timeout_seconds,
    )
