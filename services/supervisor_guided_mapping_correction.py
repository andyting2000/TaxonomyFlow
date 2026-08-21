"""Bounded manual Supervisor-guided mapper correction service."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import (
    LLMMappingSuggestion,
    MappingSupervisorReview,
    SupervisorGuidedMappingRevision,
)
from services.llm_taxonomy_mapping import (
    HuggingFaceQwenMappingClient,
    LLMMappingConfig,
    run_llm_mapping_advisory_prompt,
)
from services.suggestion_actionability import remapping_actionability
from services.supervisor_mapper_feedback import (
    build_supervisor_guided_mapping_prompt,
    build_supervisor_mapper_feedback_payload,
    supervisor_feedback_eligibility,
    supervisor_review_issues,
)
from services.supervisor_production_review import (
    list_supervisor_reviews_for_job,
    load_ai_mapping_suggestion_for_supervisor,
    load_owned_supervisor_job,
    serialize_supervisor_review,
)
from services.supervisor_rollout_authorization import (
    authorize_supervisor_rollout_user,
    supervisor_rollout_denial_reason,
)


class SupervisorGuidedCorrectionError(ValueError):
    """Base fail-closed correction error."""


class SupervisorGuidedCorrectionDisabled(SupervisorGuidedCorrectionError):
    pass


class SupervisorGuidedCorrectionForbidden(SupervisorGuidedCorrectionError):
    pass


class SupervisorGuidedCorrectionNotFound(SupervisorGuidedCorrectionError):
    pass


class SupervisorGuidedCorrectionNotEligible(SupervisorGuidedCorrectionError):
    pass


class SupervisorGuidedCorrectionRetryLimit(SupervisorGuidedCorrectionError):
    pass


class SupervisorGuidedCorrectionExecutionError(SupervisorGuidedCorrectionError):
    pass


@dataclass(frozen=True)
class SupervisorGuidedCorrectionConfig:
    enabled: bool = False
    auto_run: bool = False
    max_retries: int = 1
    admin_only: bool = True
    allowed_user_ids: Any = ""

    @classmethod
    def from_settings(cls, settings_obj: Any = settings) -> "SupervisorGuidedCorrectionConfig":
        return cls(
            enabled=bool(getattr(settings_obj, "supervisor_mapper_feedback_enabled", False)),
            auto_run=bool(getattr(settings_obj, "supervisor_mapper_feedback_auto_run", False)),
            max_retries=max(
                0,
                int(getattr(settings_obj, "supervisor_mapper_feedback_max_retries", 1) or 0),
            ),
            admin_only=bool(getattr(settings_obj, "supervisor_mapper_feedback_admin_only", True)),
            allowed_user_ids=getattr(
                settings_obj,
                "supervisor_orchestration_allowed_user_ids",
                "",
            ),
        )


def supervisor_mapper_feedback_capabilities(
    *,
    job_id: int,
    is_admin: bool,
    user_id: int | None = None,
    config: SupervisorGuidedCorrectionConfig | None = None,
) -> dict[str, Any]:
    effective = config or SupervisorGuidedCorrectionConfig.from_settings()
    authorization = authorize_supervisor_rollout_user(
        user_id=user_id,
        is_admin=is_admin,
        allowed_user_ids=effective.allowed_user_ids,
    )
    available = (
        effective.enabled
        and not effective.auto_run
        and effective.max_retries > 0
        and authorization.authorized
    )
    return {
        "job_id": job_id,
        "enabled": effective.enabled,
        "available": available,
        "auto_run": effective.auto_run,
        "max_retries": effective.max_retries,
        "admin_only": effective.admin_only,
        "authorization_policy": "admin_or_explicit_internal_reviewer",
        "authorization_source": authorization.source,
        "internal_reviewer": authorization.internal_reviewer,
        "reviewer_allowlist_configured": authorization.allowlist_configured,
        "reviewer_allowlist_user_count": authorization.allowlist_user_count,
        "persistence": "separate_revision_table",
    }


def _json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return decoded if isinstance(decoded, list) else []


def _clean(value: Any, limit: int = 2000) -> str:
    return " ".join(str(value or "").split())[:limit]


def serialize_supervisor_guided_revision(
    revision: SupervisorGuidedMappingRevision,
) -> dict[str, Any]:
    return {
        "id": revision.id,
        "job_id": revision.job_id,
        "parent_suggestion_id": revision.parent_suggestion_id,
        "supervisor_review_id": revision.supervisor_review_id,
        "correction_attempt": revision.correction_attempt,
        "correction_source": revision.correction_source,
        "original_suggested_qname": revision.original_suggested_qname,
        "revised_suggested_qname": revision.revised_suggested_qname,
        "revised_confidence": revision.revised_confidence,
        "supervisor_decision": revision.supervisor_decision,
        "reason": revision.reason,
        "addressed_supervisor_issues": _json_list(
            revision.addressed_supervisor_issues_json
        ),
        "remaining_ambiguities": _json_list(revision.remaining_ambiguities_json),
        "status": revision.status,
        "model_id": revision.model_id,
        "requires_human_review": True,
        "safe_for_auto_apply": False,
        "created_at": revision.created_at.isoformat() if revision.created_at else None,
        "completed_at": revision.completed_at.isoformat() if revision.completed_at else None,
    }


async def list_supervisor_guided_revisions_for_job(
    db: AsyncSession,
    *,
    job_id: int,
) -> list[SupervisorGuidedMappingRevision]:
    result = await db.execute(
        select(SupervisorGuidedMappingRevision)
        .where(SupervisorGuidedMappingRevision.job_id == job_id)
        .order_by(
            SupervisorGuidedMappingRevision.created_at.desc(),
            SupervisorGuidedMappingRevision.id,
        )
    )
    return result.scalars().all()


def _latest_review_for_suggestion(
    reviews: Sequence[MappingSupervisorReview],
    *,
    suggestion_id: str,
) -> MappingSupervisorReview | None:
    candidates = [
        review
        for review in reviews
        if review.llm_mapping_suggestion_id == suggestion_id
        and bool(review.is_latest)
    ]
    if not candidates:
        return None

    def sort_key(review: MappingSupervisorReview) -> tuple[datetime, datetime, str]:
        return (
            review.updated_at or datetime.min,
            review.created_at or datetime.min,
            str(review.id),
        )

    return max(candidates, key=sort_key)


def _initial_suggestion_summary(suggestion: LLMMappingSuggestion) -> dict[str, Any]:
    return {
        "id": suggestion.id,
        "job_id": suggestion.job_id,
        "extracted_data_item_id": suggestion.extracted_data_item_id,
        "suggested_template_field_id": suggestion.suggested_template_field_id,
        "suggested_concept_qname": suggestion.suggested_template_field_id,
        "confidence": float(suggestion.confidence or 0.0),
        "reason": suggestion.reason,
        "status": suggestion.status,
        "model_id": suggestion.model_id,
    }


def _safe_addressed_issues(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, str]] = []
    for row in value[:12]:
        if not isinstance(row, Mapping):
            continue
        rows.append(
            {
                "type": _clean(row.get("type"), 80),
                "resolution": _clean(row.get("resolution"), 600),
            }
        )
    return rows


def _safe_remaining_ambiguities(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean(row, 600) for row in value[:12] if _clean(row, 600)]


async def _flush_and_commit(db: AsyncSession) -> None:
    maybe_flush = db.flush()
    if hasattr(maybe_flush, "__await__"):
        await maybe_flush
    maybe_commit = db.commit()
    if hasattr(maybe_commit, "__await__"):
        await maybe_commit


async def run_supervisor_guided_mapping_correction(
    db: AsyncSession,
    *,
    job_id: int,
    suggestion_id: str,
    user_id: int,
    is_admin: bool,
    config: SupervisorGuidedCorrectionConfig | None = None,
    llm_client: Any | None = None,
    llm_config: LLMMappingConfig | None = None,
) -> dict[str, Any]:
    """Create one separate revision after explicit user action."""

    effective = config or SupervisorGuidedCorrectionConfig.from_settings()
    job = await load_owned_supervisor_job(db, job_id=job_id, user_id=user_id)
    if job is None:
        raise SupervisorGuidedCorrectionNotFound("Filing job not found")
    if not effective.enabled:
        raise SupervisorGuidedCorrectionDisabled(
            "Supervisor-guided mapper correction is disabled."
        )
    if effective.auto_run:
        raise SupervisorGuidedCorrectionDisabled(
            "SUPERVISOR_MAPPER_FEEDBACK_AUTO_RUN must remain false."
        )
    if effective.max_retries <= 0:
        raise SupervisorGuidedCorrectionRetryLimit(
            "Supervisor-guided mapper correction retry limit is zero."
        )
    authorization = authorize_supervisor_rollout_user(
        user_id=user_id,
        is_admin=is_admin,
        allowed_user_ids=effective.allowed_user_ids,
    )
    if not authorization.authorized:
        raise SupervisorGuidedCorrectionForbidden(
            supervisor_rollout_denial_reason(authorization)
        )

    suggestion = await load_ai_mapping_suggestion_for_supervisor(
        db,
        job_id=job.id,
        suggestion_id=suggestion_id,
        lock_for_update=True,
    )
    if suggestion is None:
        raise SupervisorGuidedCorrectionNotFound("AI mapping suggestion not found")
    reviews = await list_supervisor_reviews_for_job(db, job_id=job.id)
    review = _latest_review_for_suggestion(reviews, suggestion_id=suggestion.id)
    revisions = await list_supervisor_guided_revisions_for_job(db, job_id=job.id)
    existing = [row for row in revisions if row.parent_suggestion_id == suggestion.id]
    feedback_eligible, feedback_reason = supervisor_feedback_eligibility(review)
    actionability = remapping_actionability(
        suggestion,
        latest_review=review,
        revisions=existing,
        feedback_eligible=feedback_eligible,
        feedback_reason=feedback_reason,
        feature_enabled=effective.enabled,
        authorized=authorization.authorized,
        auto_run=effective.auto_run,
        max_retries=effective.max_retries,
    )
    if actionability.state == "remapping_retry_exhausted":
        raise SupervisorGuidedCorrectionRetryLimit(
            "Supervisor-guided mapper correction retry limit reached."
        )
    if not actionability.executable or review is None:
        raise SupervisorGuidedCorrectionNotEligible(
            actionability.block_reason or "supervisor_mapper_feedback_not_executable"
        )

    payload = build_supervisor_mapper_feedback_payload(suggestion, review)
    candidates = payload.get("candidate_concepts") or []
    if not candidates:
        raise SupervisorGuidedCorrectionNotEligible(
            "No candidate concepts are available for bounded remapping."
        )

    attempt = len(existing) + 1
    now = datetime.utcnow()
    revision = SupervisorGuidedMappingRevision(
        id=str(uuid.uuid4()),
        job_id=job.id,
        parent_suggestion_id=suggestion.id,
        supervisor_review_id=review.id,
        correction_attempt=attempt,
        correction_source="supervisor_feedback",
        original_suggested_qname=suggestion.suggested_template_field_id,
        revised_suggested_qname=None,
        revised_confidence=None,
        supervisor_decision=str(review.supervisor_decision),
        reason=None,
        addressed_supervisor_issues_json="[]",
        remaining_ambiguities_json="[]",
        status="running",
        model_id=(llm_config.model_id if llm_config else None),
        requires_human_review=True,
        safe_for_auto_apply=False,
        created_at=now,
    )
    db.add(revision)
    await _flush_and_commit(db)

    try:
        mapping_run = await run_llm_mapping_advisory_prompt(
            build_supervisor_guided_mapping_prompt(payload),
            candidates,
            llm_client=llm_client or HuggingFaceQwenMappingClient(),
            config=llm_config,
        )
        validated = mapping_run["validated_mapping"]
        parsed = mapping_run["parsed_output"]
        addressed = _safe_addressed_issues(parsed.get("addressed_supervisor_issues"))
        remaining = _safe_remaining_ambiguities(parsed.get("remaining_ambiguities"))
        if validated.get("status") != "suggested" and not remaining:
            remaining = [
                _clean(validated.get("rejection_reason") or "No safe revised mapping was returned.", 600)
            ]

        revision.revised_suggested_qname = validated.get("selected_template_field_id")
        revision.revised_confidence = float(validated.get("confidence") or 0.0)
        revision.reason = _clean(
            validated.get("reason") or validated.get("rejection_reason"),
            2000,
        )
        revision.addressed_supervisor_issues_json = json.dumps(addressed, ensure_ascii=True)
        revision.remaining_ambiguities_json = json.dumps(remaining, ensure_ascii=True)
        revision.status = "completed"
        revision.model_id = validated.get("model_id")
        revision.requires_human_review = True
        revision.safe_for_auto_apply = False
        revision.completed_at = datetime.utcnow()
        await _flush_and_commit(db)
    except Exception as exc:
        revision.status = "failed"
        revision.reason = f"Mapper correction failed: {type(exc).__name__}"
        revision.remaining_ambiguities_json = json.dumps(
            ["The bounded mapper correction did not complete."],
            ensure_ascii=True,
        )
        revision.requires_human_review = True
        revision.safe_for_auto_apply = False
        revision.completed_at = datetime.utcnow()
        await _flush_and_commit(db)
        raise SupervisorGuidedCorrectionExecutionError(
            "Supervisor-guided mapper correction failed."
        ) from exc

    return {
        "initial_suggestion": _initial_suggestion_summary(suggestion),
        "supervisor_review": serialize_supervisor_review(review),
        "revised_suggestion": serialize_supervisor_guided_revision(revision),
        "safety": {
            "confirmed_tag_id_mutations": 0,
            "final_mapping_mutations": 0,
            "auto_apply_count": 0,
            "auto_accept_count": 0,
            "requires_human_review": True,
            "safe_for_auto_apply": False,
            "automatic_correction_count": 0,
            "recursive_supervisor_calls": 0,
            "original_suggestion_mutations": 0,
        },
    }
