"""Read-only operational metrics and audit export for Supervisor rollout."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence


def _value(record: Any, name: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        return record.get(name, default)
    return getattr(record, name, default)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _elapsed_ms(started: Any, completed: Any) -> float | None:
    if not isinstance(started, datetime) or not isinstance(completed, datetime):
        return None
    return max(0.0, round((completed - started).total_seconds() * 1000, 3))


def build_supervisor_rollout_audit_rows(
    *,
    reviews: Sequence[Any],
    revisions: Sequence[Any],
    suggestions: Sequence[Any],
) -> list[dict[str, Any]]:
    """Build non-sensitive action history without mutating persisted records."""

    suggestions_by_id = {
        str(_value(row, "id", "")): row
        for row in suggestions
        if _value(row, "id")
    }
    reviews_by_id = {
        str(_value(row, "id", "")): row
        for row in reviews
        if _value(row, "id")
    }
    rows: list[dict[str, Any]] = []

    for review in reviews:
        suggestion_id = str(
            _value(review, "llm_mapping_suggestion_id", "") or ""
        )
        suggestion = suggestions_by_id.get(suggestion_id)
        rows.append(
            {
                "event_type": "supervisor_review",
                "user_id": _value(review, "user_id"),
                "user_id_source": "review_record",
                "filing_id": _value(review, "job_id"),
                "job_id": _value(review, "job_id"),
                "row_id": _value(review, "extracted_data_item_id"),
                "suggestion_id": suggestion_id or None,
                "supervisor_review_id": _value(review, "id"),
                "revision_id": None,
                "action_timestamp": _iso(
                    _value(review, "completed_at")
                    or _value(review, "created_at")
                ),
                "model_provider": _value(review, "supervisor_model_provider"),
                "model_id": _value(review, "supervisor_model_id"),
                "prompt_version": _value(review, "supervisor_prompt_version"),
                "schema_version": _value(review, "supervisor_schema_version"),
                "supervisor_decision": _value(review, "supervisor_decision"),
                "risk_level": _value(review, "supervisor_risk_level"),
                "recommended_action": _value(
                    review,
                    "supervisor_recommended_action",
                ),
                "initial_qname": (
                    _value(review, "mapper_selected_qname")
                    or _value(suggestion, "suggested_template_field_id")
                ),
                "revised_qname": None,
                "correction_attempt": None,
                "requires_human_review": True,
                "safe_for_auto_apply": False,
                "human_decision": _value(suggestion, "status"),
                "status": _value(review, "review_status"),
                "source": _value(review, "source"),
            }
        )

    for revision in revisions:
        suggestion_id = str(_value(revision, "parent_suggestion_id", "") or "")
        review_id = str(_value(revision, "supervisor_review_id", "") or "")
        suggestion = suggestions_by_id.get(suggestion_id)
        review = reviews_by_id.get(review_id)
        job = _value(suggestion, "job")
        review_user_id = _value(review, "user_id")
        owner_user_id = _value(job, "user_id")
        rows.append(
            {
                "event_type": "guided_mapping_revision",
                "user_id": review_user_id or owner_user_id,
                "user_id_source": (
                    "linked_review"
                    if review_user_id is not None
                    else "owned_job"
                ),
                "filing_id": _value(revision, "job_id"),
                "job_id": _value(revision, "job_id"),
                "row_id": (
                    _value(review, "extracted_data_item_id")
                    or _value(suggestion, "extracted_data_item_id")
                ),
                "suggestion_id": suggestion_id or None,
                "supervisor_review_id": review_id or None,
                "revision_id": _value(revision, "id"),
                "action_timestamp": _iso(
                    _value(revision, "completed_at")
                    or _value(revision, "created_at")
                ),
                "model_provider": _value(review, "supervisor_model_provider"),
                "model_id": _value(revision, "model_id"),
                "prompt_version": _value(review, "supervisor_prompt_version"),
                "schema_version": _value(review, "supervisor_schema_version"),
                "supervisor_decision": _value(
                    revision,
                    "supervisor_decision",
                ),
                "risk_level": _value(review, "supervisor_risk_level"),
                "recommended_action": _value(
                    review,
                    "supervisor_recommended_action",
                ),
                "initial_qname": _value(
                    revision,
                    "original_suggested_qname",
                ),
                "revised_qname": _value(
                    revision,
                    "revised_suggested_qname",
                ),
                "correction_attempt": _value(revision, "correction_attempt"),
                "requires_human_review": True,
                "safe_for_auto_apply": False,
                "human_decision": _value(suggestion, "status"),
                "status": _value(revision, "status"),
                "source": _value(revision, "correction_source"),
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            str(row["action_timestamp"] or ""),
            str(row["event_type"]),
            str(row["supervisor_review_id"] or ""),
            str(row["revision_id"] or ""),
        ),
    )


def build_supervisor_rollout_operational_report(
    *,
    plans: Sequence[Mapping[str, Any]],
    reviews: Sequence[Any],
    revisions: Sequence[Any],
    suggestions: Sequence[Any],
) -> dict[str, Any]:
    """Aggregate rollout counters from read-only plan and persistence snapshots."""

    live_reviews = [
        row for row in reviews if str(_value(row, "source", "")) == "live"
    ]
    latencies = [
        value
        for value in (
            _elapsed_ms(
                _value(row, "started_at"),
                _value(row, "completed_at"),
            )
            for row in live_reviews
        )
        if value is not None
    ]
    completed_reviews = [
        row for row in live_reviews if _value(row, "review_status") == "completed"
    ]
    failed_reviews = [
        row for row in live_reviews if _value(row, "review_status") == "failed"
    ]
    decisions = {
        name: sum(
            1
            for row in completed_reviews
            if _value(row, "supervisor_decision") == name
        )
        for name in ("agree", "disagree", "needs_human_review")
    }
    invalid_response_count = sum(
        1
        for row in failed_reviews
        if any(
            token in str(_value(row, "error_type", "") or "").lower()
            for token in ("invalid", "schema", "json", "response")
        )
    )
    completed_revisions = [
        row for row in revisions if _value(row, "status") == "completed"
    ]
    failed_revisions = [
        row for row in revisions if _value(row, "status") == "failed"
    ]
    no_safe_revisions = [
        row
        for row in completed_revisions
        if not _value(row, "revised_suggested_qname")
    ]
    changed_revisions = [
        row
        for row in completed_revisions
        if _value(row, "revised_suggested_qname")
        and _value(row, "revised_suggested_qname")
        != _value(row, "original_suggested_qname")
    ]
    unchanged_revisions = [
        row
        for row in completed_revisions
        if _value(row, "revised_suggested_qname")
        and _value(row, "revised_suggested_qname")
        == _value(row, "original_suggested_qname")
    ]
    plan_items = [
        item
        for plan in plans
        for item in (plan.get("items") or [])
        if isinstance(item, Mapping)
    ]
    safety_keys = {
        "auto_review_calls": "auto_review_calls",
        "auto_remap_calls": "auto_remap_calls",
        "auto_apply": "auto_apply_count",
        "orchestration_confirmed_tag_mutations": "confirmed_tag_id_mutations",
        "orchestration_final_mapping_mutations": "final_mapping_mutations",
    }
    safety = {
        output_key: sum(
            int((plan.get("safety_summary") or {}).get(source_key) or 0)
            for plan in plans
        )
        for output_key, source_key in safety_keys.items()
    }
    suggestion_status_counts = {
        name: sum(1 for row in suggestions if _value(row, "status") == name)
        for name in ("accepted", "ignored", "suggested", "rejected")
    }

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "read_only": True,
        "metrics": {
            "orchestration_plan_snapshots": len(plans),
            "eligible_count": sum(
                int(plan.get("policy_eligible_count") or plan.get("eligible_count") or 0)
                for plan in plans
            ),
            "high_priority_count": sum(
                int(plan.get("high_priority_count") or 0) for plan in plans
            ),
            "medium_priority_count": sum(
                int(plan.get("medium_priority_count") or 0) for plan in plans
            ),
            "supervisor_review_attempts": len(live_reviews),
            "supervisor_review_successes": len(completed_reviews),
            "supervisor_review_failures": len(failed_reviews),
            "supervisor_provider_latency_ms_average": (
                round(sum(latencies) / len(latencies), 3) if latencies else None
            ),
            "supervisor_provider_latency_ms_max": max(latencies) if latencies else None,
            "supervisor_invalid_response_count": invalid_response_count,
            "supervisor_decisions": decisions,
            "remapping_attempts": len(revisions),
            "remapping_successes": len(completed_revisions),
            "remapping_failures": len(failed_revisions),
            "no_safe_revised_mapping": len(no_safe_revisions),
            "changed_qname": len(changed_revisions),
            "unchanged_qname": len(unchanged_revisions),
            "revision_count": len(revisions),
            "retry_blocked_count": sum(
                1
                for item in plan_items
                if item.get("remapping_action_block_reason")
                == "correction_retry_limit_reached"
            ),
            "eventual_accept": suggestion_status_counts["accepted"],
            "reject_or_ignore": suggestion_status_counts["ignored"],
            "pending_human_review": (
                suggestion_status_counts["suggested"]
                + suggestion_status_counts["rejected"]
            ),
            "mapper_abstentions": suggestion_status_counts["rejected"],
        },
        "safety_counters": safety,
        "audit_rows": build_supervisor_rollout_audit_rows(
            reviews=reviews,
            revisions=revisions,
            suggestions=suggestions,
        ),
        "limitations": [
            "Plan request volume comes from API access logs; this snapshot counts supplied plan responses.",
            "Revision actor user_id is resolved from the linked review, then the owned job when no review user is available.",
            "Reviewer actions are operational evidence, not auditor gold labels.",
        ],
    }
