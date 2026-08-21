"""Canonical suggestion status and manual actionability predicates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


HUMAN_TERMINAL_STATUSES = frozenset({"accepted", "ignored"})
MAPPER_ABSTENTION_STATUS = "rejected"
CONCRETE_SUGGESTION_STATUS = "suggested"


def _value(record: Any, field: str, default: Any = None) -> Any:
    if isinstance(record, dict):
        return record.get(field, default)
    return getattr(record, field, default)


def normalized_suggestion_status(suggestion_or_status: Any) -> str:
    value = (
        _value(suggestion_or_status, "status")
        if not isinstance(suggestion_or_status, str)
        else suggestion_or_status
    )
    return str(value or CONCRETE_SUGGESTION_STATUS).strip().lower()


def is_human_terminal(suggestion_or_status: Any) -> bool:
    """Return true only for persisted human Accept/Reject decisions."""

    return normalized_suggestion_status(suggestion_or_status) in HUMAN_TERMINAL_STATUSES


@dataclass(frozen=True)
class SupervisorReviewActionability:
    executable: bool
    batch_executable: bool
    block_reason: str | None


def supervisor_review_actionability(
    suggestion: Any,
    *,
    policy_classification: str,
    latest_review: Any | None,
    latest_revision: Any | None,
    feature_enabled: bool,
    authorized: bool,
) -> SupervisorReviewActionability:
    """Evaluate one pending queue item against manual review preconditions."""

    block_reason: str | None = None
    if not feature_enabled:
        block_reason = "supervisor_review_execution_disabled"
    elif not authorized:
        block_reason = "supervisor_review_execution_forbidden"
    elif is_human_terminal(suggestion):
        block_reason = "human_decision_is_terminal"
    elif _value(_value(suggestion, "extracted_data_item"), "confirmed_tag_id") is not None:
        block_reason = "confirmed_mapping_exists"
    elif latest_revision is not None:
        block_reason = "suggestion_superseded_by_revision"
    elif latest_review is not None:
        block_reason = "supervisor_review_already_exists"
    elif str(policy_classification or "") != "eligible":
        block_reason = "supervisor_policy_not_eligible"

    executable = block_reason is None
    return SupervisorReviewActionability(
        executable=executable,
        batch_executable=executable,
        block_reason=block_reason,
    )


@dataclass(frozen=True)
class RemappingActionability:
    eligible: bool
    executable: bool
    state: str
    block_reason: str | None


def remapping_actionability(
    suggestion: Any,
    *,
    latest_review: Any | None,
    revisions: Sequence[Any] = (),
    feedback_eligible: bool,
    feedback_reason: str,
    feature_enabled: bool,
    authorized: bool,
    auto_run: bool,
    max_retries: int,
) -> RemappingActionability:
    """Apply Option A: only a concrete, unconfirmed suggestion may be revised."""

    status = normalized_suggestion_status(suggestion)
    selected_qname = str(_value(suggestion, "suggested_template_field_id") or "").strip()
    confirmed_tag_id = _value(
        _value(suggestion, "extracted_data_item"),
        "confirmed_tag_id",
    )
    attempts_used = len(revisions)

    if is_human_terminal(status):
        return RemappingActionability(
            eligible=False,
            executable=False,
            state="remapping_blocked",
            block_reason="human_decision_is_terminal",
        )
    if status != CONCRETE_SUGGESTION_STATUS or not selected_qname:
        return RemappingActionability(
            eligible=False,
            executable=False,
            state="remapping_not_eligible",
            block_reason="concrete_suggestion_required",
        )
    if confirmed_tag_id is not None:
        return RemappingActionability(
            eligible=False,
            executable=False,
            state="remapping_blocked",
            block_reason="confirmed_mapping_exists",
        )
    if attempts_used >= max_retries:
        return RemappingActionability(
            eligible=False,
            executable=False,
            state="remapping_retry_exhausted",
            block_reason="correction_retry_limit_reached",
        )
    if latest_review is None:
        return RemappingActionability(
            eligible=False,
            executable=False,
            state="remapping_not_evaluated",
            block_reason="supervisor_review_required",
        )
    if str(_value(latest_review, "review_status") or "").strip().lower() != "completed":
        return RemappingActionability(
            eligible=False,
            executable=False,
            state="remapping_blocked",
            block_reason="supervisor_review_not_completed",
        )
    if not feedback_eligible:
        return RemappingActionability(
            eligible=False,
            executable=False,
            state="remapping_not_eligible",
            block_reason=feedback_reason or "supervisor_feedback_not_eligible",
        )

    execution_block: str | None = None
    if not feature_enabled:
        execution_block = "supervisor_mapper_feedback_disabled"
    elif auto_run:
        execution_block = "automatic_remapping_is_forbidden"
    elif max_retries <= 0:
        execution_block = "correction_retry_limit_is_zero"
    elif not authorized:
        execution_block = "supervisor_mapper_feedback_forbidden"

    return RemappingActionability(
        eligible=True,
        executable=execution_block is None,
        state=(
            "remapping_available"
            if execution_block is None
            else "remapping_not_executable"
        ),
        block_reason=execution_block,
    )
