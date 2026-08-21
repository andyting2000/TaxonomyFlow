"""Read-only planning helpers for Extraction v2 manual-review UI/API design."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


DEFAULT_INPUT_PATHS = {
    "manual_review_policy": "reports/extraction_v2_manual_review_policy_13t.json",
    "mapping_gate_report": "reports/extraction_v2_mapping_candidate_gate_13t.json",
    "manual_review_queue": "reports/extraction_v2_manual_review_queue_13t.json",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_no_side_effect_metadata(generated_at: Optional[str] = None) -> Dict[str, Any]:
    return {
        "feature": "13U",
        "generated_at": generated_at or utc_now_iso(),
        "read_only": True,
        "database_mutated": False,
        "db_schema_changed": False,
        "migration_created": False,
        "api_routes_implemented": False,
        "frontend_code_modified": False,
        "production_behavior_changed": False,
        "ui_implemented": False,
        "xbrl_generated": False,
        "arelle_validation_run": False,
        "live_huggingface_calls_made": False,
        "live_openai_calls_made": False,
        "benchmark_rerun": False,
        "reference_xml_sent_to_model": False,
    }


def _nested_get(data: Mapping[str, Any], paths: Iterable[Iterable[str]], default: Any = None) -> Any:
    for path in paths:
        current: Any = data
        for key in path:
            if not isinstance(current, Mapping) or key not in current:
                current = None
                break
            current = current[key]
        if current is not None:
            return current
    return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_queue_items(manual_review_queue: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    items = _nested_get(
        manual_review_queue,
        [
            ("queue_items",),
            ("manual_review_queue", "queue_items"),
            ("items",),
        ],
        [],
    )
    return list(items) if isinstance(items, list) else []


def _extract_conflict_groups(
    duplicate_report: Mapping[str, Any], manual_review_queue: Mapping[str, Any]
) -> List[Mapping[str, Any]]:
    groups = _nested_get(
        duplicate_report,
        [
            ("conflict_groups",),
            ("groups", "conflicting_duplicate_groups"),
            ("manual_review_conflict_groups",),
        ],
        None,
    )
    if isinstance(groups, list):
        return list(groups)
    groups = _nested_get(
        manual_review_queue,
        [
            ("conflict_groups",),
            ("manual_review_queue", "conflict_groups"),
        ],
        [],
    )
    return list(groups) if isinstance(groups, list) else []


def extract_queue_summary(
    manual_review_policy: Mapping[str, Any],
    mapping_gate_report: Mapping[str, Any],
    manual_review_queue: Mapping[str, Any],
) -> Dict[str, Any]:
    gate_counts = _nested_get(
        mapping_gate_report,
        [
            ("aggregate_gate_counts",),
            ("gate_counts",),
            ("summary", "gate_counts"),
            ("mapping_candidate_gate", "gate_counts"),
        ],
        {},
    )
    if not isinstance(gate_counts, Mapping):
        gate_counts = {}

    queue_items = _extract_queue_items(manual_review_queue)
    priority_counts = _nested_get(
        manual_review_queue,
        [
            ("priority_distribution",),
            ("summary", "priority_distribution"),
            ("queue_summary", "priority_distribution"),
        ],
        None,
    )
    if not isinstance(priority_counts, Mapping):
        priority_counts = Counter(str(item.get("priority", "unknown")) for item in queue_items)

    allowed_into_mapping = _nested_get(
        mapping_gate_report,
        [
            ("mapping_candidate_input_summary", "allowed_into_13u_count"),
            ("mapping_candidate_input", "allowed_candidate_count"),
            ("summary", "allowed_into_mapping"),
            ("allowed_into_mapping",),
        ],
        None,
    )
    requires_confirmation = _nested_get(
        mapping_gate_report,
        [
            ("mapping_candidate_input_summary", "requires_confirmation_count"),
            ("mapping_candidate_input", "requires_confirmation_count"),
            ("summary", "requires_confirmation"),
            ("requires_confirmation",),
        ],
        None,
    )

    original_total = _nested_get(
        mapping_gate_report,
        [
            ("summary", "total_original_candidates"),
            ("total_original_candidates",),
        ],
        None,
    )
    cleaned_total = _nested_get(
        mapping_gate_report,
        [
            ("summary", "total_cleaned_candidates"),
            ("total_cleaned_candidates",),
        ],
        None,
    )

    conflict_groups = _nested_get(
        manual_review_policy,
        [
            ("conflict_group_policy", "conflict_group_count"),
            ("summary", "conflict_group_count"),
            ("conflict_group_count",),
        ],
        None,
    )

    auto_count = _as_int(gate_counts.get("auto_mappable_candidate"))
    suggest_count = _as_int(gate_counts.get("suggest_mapping_only"))
    manual_count = _as_int(gate_counts.get("manual_review_required"))
    blocked_count = _as_int(gate_counts.get("blocked_from_mapping"))
    context_count = _as_int(gate_counts.get("reference_only_or_context"))

    if allowed_into_mapping is None:
        allowed_into_mapping = auto_count + suggest_count
    if requires_confirmation is None:
        requires_confirmation = suggest_count
    if cleaned_total is None:
        cleaned_total = auto_count + suggest_count + manual_count + blocked_count + context_count
    if original_total is None:
        original_total = cleaned_total
    if conflict_groups is None:
        conflict_groups = len(
            _extract_conflict_groups(manual_review_policy, manual_review_queue)
        )

    return {
        "total_original_candidates": _as_int(original_total),
        "total_cleaned_candidates": _as_int(cleaned_total),
        "auto_mappable_candidate": auto_count,
        "suggest_mapping_only": suggest_count,
        "manual_review_required": manual_count,
        "blocked_from_mapping": blocked_count,
        "reference_only_or_context": context_count,
        "allowed_into_mapping_candidate_generation": _as_int(allowed_into_mapping),
        "requires_confirmation": _as_int(requires_confirmation),
        "excluded_from_automatic_mapping": manual_count + blocked_count + context_count,
        "manual_review_queue_items": len(queue_items)
        or _as_int(
            _nested_get(
                manual_review_queue,
                [
                    ("summary", "queue_item_count"),
                    ("queue_item_count",),
                ],
                0,
            )
        ),
        "priority_distribution": {str(k): _as_int(v) for k, v in dict(priority_counts).items()},
        "conflict_group_count": _as_int(conflict_groups),
    }


def build_data_contract_report(
    queue_summary: Mapping[str, Any], input_paths: Optional[Mapping[str, str]] = None
) -> Dict[str, Any]:
    metadata = build_no_side_effect_metadata()
    entities = [
        {
            "name": "manual_review_batch",
            "purpose": "Groups one generated review queue and its source reports.",
            "storage_recommendation": "Start as JSON report-only; later promote to database table when API/UI work starts.",
            "fields": [
                "review_batch_id",
                "source_report_id",
                "source_extraction_report_path",
                "source_cleaned_candidates_report_path",
                "source_manual_review_queue_report_path",
                "created_at",
                "status",
                "total_queue_items",
                "total_conflict_groups",
                "total_candidates_allowed_to_mapping",
                "total_candidates_blocked",
                "generated_by_feature",
                "metadata",
            ],
        },
        {
            "name": "manual_review_item",
            "purpose": "Represents one candidate or context row requiring reviewer visibility.",
            "storage_recommendation": "JSON item first; later API-facing resource owned by a review batch.",
            "fields": [
                "review_item_id",
                "review_batch_id",
                "case_id",
                "candidate_id",
                "original_candidate_id",
                "duplicate_group_id",
                "conflict_group_id",
                "page_number",
                "statement_section",
                "row_type",
                "label",
                "value",
                "previous_value",
                "text_preview",
                "source",
                "source_snippet",
                "gate_status",
                "priority",
                "review_reasons",
                "recommended_reviewer_action",
                "decision_status",
                "reviewer_decision",
                "reviewer_notes",
                "reviewed_by",
                "reviewed_at",
                "audit_metadata",
            ],
        },
        {
            "name": "conflict_group",
            "purpose": "Surfaces related candidates where automatic mapping must be blocked until reviewed.",
            "storage_recommendation": "JSON group first; later normalized table or API subresource.",
            "fields": [
                "conflict_group_id",
                "review_batch_id",
                "case_id",
                "normalized_label",
                "candidate_ids",
                "value_variants",
                "affected_pages",
                "affected_sections",
                "blocks_auto_mapping",
                "recommended_policy",
                "decision_status",
                "group_decision",
                "reviewed_by",
                "reviewed_at",
            ],
        },
        {
            "name": "reviewer_decision",
            "purpose": "Records user decisions, corrections, and mapping eligibility changes.",
            "storage_recommendation": "Append-only decision log when persisted; never overwrite source extraction evidence.",
            "fields": [
                "decision_id",
                "review_item_id",
                "conflict_group_id",
                "decision_type",
                "corrected_label",
                "corrected_value",
                "corrected_previous_value",
                "corrected_row_type",
                "corrected_section",
                "selected_candidate_id",
                "rejected_candidate_ids",
                "requires_manual_taxonomy_mapping",
                "approved_for_mapping",
                "requires_confirmation",
                "notes",
                "created_by",
                "created_at",
            ],
        },
        {
            "name": "mapping_handoff_item",
            "purpose": "Defines the reviewed candidate payload allowed to enter future mapping candidate generation.",
            "storage_recommendation": "Report-based handoff contract for #13V; later generated from reviewed database state.",
            "fields": [
                "mapping_input_id",
                "review_batch_id",
                "candidate_id",
                "case_id",
                "label",
                "value",
                "previous_value",
                "text",
                "row_type",
                "statement_section",
                "gate_status",
                "requires_confirmation",
                "review_decision_id",
                "approved_for_mapping",
                "warning_flags",
                "source_provenance",
                "page_number",
                "duplicate_conflict_status",
            ],
        },
    ]

    return {
        "metadata": metadata,
        "planning_inputs": dict(input_paths or DEFAULT_INPUT_PATHS),
        "queue_summary": dict(queue_summary),
        "storage_strategy": {
            "recommended_first_step": "JSON report-only flow",
            "database_tables": "Plan for later feature after handoff contract and mapping sandbox are stable.",
            "temporary_staging_tables": "Possible bridge after API design, but not needed for #13V.",
            "existing_table_extensions": "Avoid initially to prevent mixing benchmark review state with production extraction rows.",
            "api_facing_resources": [
                "review_batches",
                "review_items",
                "conflict_groups",
                "reviewer_decisions",
                "mapping_handoff_items",
            ],
        },
        "entities": entities,
        "json_examples": {
            "manual_review_batch": {
                "review_batch_id": "review_batch_13t_001",
                "status": "ready_for_review",
                "total_queue_items": queue_summary.get("manual_review_queue_items", 0),
                "total_conflict_groups": queue_summary.get("conflict_group_count", 0),
            },
            "manual_review_item": {
                "review_item_id": "item_000001",
                "case_id": "002-bezlife-marketing",
                "candidate_id": "cand_000123",
                "gate_status": "manual_review_required",
                "priority": "critical",
                "review_reasons": ["duplicate_conflicting_values"],
                "decision_status": "pending_review",
            },
            "conflict_group": {
                "conflict_group_id": "conflict_0001",
                "case_id": "003-fine-batik",
                "normalized_label": "cash and bank balances",
                "candidate_ids": ["cand_1", "cand_2"],
                "blocks_auto_mapping": True,
                "decision_status": "unresolved",
            },
            "reviewer_decision": {
                "decision_id": "decision_0001",
                "review_item_id": "item_000001",
                "decision_type": "corrected_and_approved",
                "approved_for_mapping": True,
                "requires_confirmation": False,
            },
            "mapping_handoff_item": {
                "mapping_input_id": "mapping_input_0001",
                "candidate_id": "cand_000123",
                "gate_status": "auto_mappable_candidate",
                "mapping_allowed": True,
                "requires_confirmation": False,
                "provenance": {"source_report": "extraction_v2_cleaned_candidates_13s"},
            },
        },
        "validation_rules": [
            "Every review item must belong to exactly one review batch.",
            "Conflict-group decisions must preserve all candidate options and record any selected candidate.",
            "Approved mapping handoff items must include final label, row type, section, provenance, and page number.",
            "Suppressed, downgraded metadata/date/year, blocked, and unresolved conflict candidates must not be auto-mapped.",
            "Reviewer corrections must be stored as decisions, not by overwriting source extraction evidence.",
        ],
        "audit_trail_requirements": [
            "Record source report paths and hashes when available.",
            "Record created_by/reviewed_by and timestamps for every decision.",
            "Keep original candidate values alongside corrected values.",
            "Keep conflict group membership stable across exports.",
            "Make mapping handoff reproducible from batch, item, group, and decision records.",
        ],
        "mapping_handoff_contract": build_mapping_handoff_rules(),
        "unresolved_decisions": [
            "Whether production review state should live in dedicated tables or a staging schema.",
            "Whether reviewer identity comes from current auth users or a separate review role model.",
            "Whether conflict-group decisions should be required before any case-level handoff.",
        ],
    }


def build_api_endpoints() -> List[Dict[str, Any]]:
    return [
        _endpoint(
            "GET",
            "/api/v1/extraction-v2/review-batches",
            "List review batches with summary counts and status filters.",
            ["status", "created_after", "case_id", "limit", "offset"],
            {"batches": "array", "pagination": "object"},
            True,
        ),
        _endpoint(
            "POST",
            "/api/v1/extraction-v2/review-batches",
            "Create a review batch from a cleaned candidate report or production extraction job.",
            ["source_report_id", "source_type", "metadata"],
            {"review_batch": "object"},
            True,
        ),
        _endpoint(
            "GET",
            "/api/v1/extraction-v2/review-batches/{batch_id}",
            "Return batch detail, progress, and aggregate review state.",
            ["batch_id"],
            {"review_batch": "object", "summary": "object"},
            True,
        ),
        _endpoint(
            "GET",
            "/api/v1/extraction-v2/review-batches/{batch_id}/items",
            "List review items with filters for priority, case, row type, gate status, and reason code.",
            ["batch_id", "priority", "case_id", "row_type", "gate_status", "reason_code", "conflict_only", "search"],
            {"items": "array", "filters": "object", "pagination": "object"},
            True,
        ),
        _endpoint(
            "GET",
            "/api/v1/extraction-v2/review-batches/{batch_id}/conflict-groups",
            "List conflict groups and all candidate options that block automatic mapping.",
            ["batch_id", "case_id", "status", "priority"],
            {"conflict_groups": "array"},
            True,
        ),
        _endpoint(
            "PATCH",
            "/api/v1/extraction-v2/review-items/{item_id}/decision",
            "Record a reviewer decision or correction for one review item.",
            ["item_id", "decision_type", "corrections", "notes"],
            {"review_item": "object", "decision": "object"},
            True,
        ),
        _endpoint(
            "PATCH",
            "/api/v1/extraction-v2/conflict-groups/{group_id}/decision",
            "Record group-level conflict resolution without discarding candidate evidence.",
            ["group_id", "group_decision", "selected_candidate_id", "rejected_candidate_ids", "notes"],
            {"conflict_group": "object", "decision": "object"},
            True,
        ),
        _endpoint(
            "POST",
            "/api/v1/extraction-v2/review-batches/{batch_id}/mapping-handoff",
            "Generate the reviewed mapping input set for future mapping candidate generation.",
            ["batch_id", "include_suggest_only", "require_no_unresolved_conflicts"],
            {"mapping_handoff": "object", "items": "array"},
            True,
        ),
        _endpoint(
            "GET",
            "/api/v1/extraction-v2/review-batches/{batch_id}/summary",
            "Return dashboard-ready review progress and blocker counts.",
            ["batch_id"],
            {"summary": "object"},
            False,
        ),
        _endpoint(
            "GET",
            "/api/v1/extraction-v2/review-batches/{batch_id}/export",
            "Export queue, decisions, and mapping handoff evidence for audit.",
            ["batch_id", "format"],
            {"download_url": "string", "export_metadata": "object"},
            False,
        ),
    ]


def _endpoint(
    method: str,
    path: str,
    purpose: str,
    inputs: List[str],
    outputs: Mapping[str, str],
    mvp_required: bool,
) -> Dict[str, Any]:
    return {
        "method": method,
        "path": path,
        "purpose": purpose,
        "inputs": inputs,
        "outputs": dict(outputs),
        "validation_rules": [
            "Require authenticated user with access to the source extraction job or review batch.",
            "Validate status transitions against the review state machine.",
            "Validate corrected numeric values and row types before approval.",
            "Reject handoff generation while blocking conflicts are unresolved.",
        ],
        "allowed_status_transitions": "See review_state_transitions in this report.",
        "failure_cases": [
            "batch_not_found",
            "item_not_found",
            "invalid_transition",
            "unresolved_conflict_group",
            "validation_failed",
            "unauthorized",
        ],
        "security_auth_considerations": [
            "Use existing user isolation and authorization checks.",
            "Do not expose source snippets across tenants.",
            "Record reviewer identity and timestamps for every mutation.",
            "Rate limit export endpoints if large source evidence is included.",
        ],
        "mvp_required": mvp_required,
    }


def build_review_state_transitions() -> Dict[str, Any]:
    return {
        "candidate_item_statuses": [
            "pending_review",
            "in_review",
            "approved_for_mapping",
            "approved_suggest_only",
            "corrected_and_approved",
            "context_only",
            "rejected",
            "blocked",
            "needs_manual_taxonomy_mapping",
            "needs_aggregation_policy",
            "needs_dimension_policy",
        ],
        "candidate_allowed_transitions": {
            "pending_review": ["in_review", "approved_for_mapping", "approved_suggest_only", "context_only", "rejected", "blocked"],
            "in_review": [
                "approved_for_mapping",
                "approved_suggest_only",
                "corrected_and_approved",
                "context_only",
                "rejected",
                "blocked",
                "needs_manual_taxonomy_mapping",
                "needs_aggregation_policy",
                "needs_dimension_policy",
            ],
            "approved_for_mapping": ["in_review"],
            "approved_suggest_only": ["in_review"],
            "corrected_and_approved": ["in_review"],
            "context_only": ["in_review"],
            "rejected": ["in_review"],
            "blocked": ["in_review"],
            "needs_manual_taxonomy_mapping": ["in_review"],
            "needs_aggregation_policy": ["in_review"],
            "needs_dimension_policy": ["in_review"],
        },
        "candidate_invalid_transitions": [
            "blocked -> approved_for_mapping without a new reviewer decision",
            "rejected -> mapping handoff without explicit reopen and approval",
            "needs_aggregation_policy -> approved_for_mapping without policy resolution",
            "needs_dimension_policy -> approved_for_mapping without policy resolution",
        ],
        "conflict_group_statuses": [
            "unresolved",
            "in_review",
            "resolved_choose_one",
            "resolved_keep_multiple",
            "resolved_context_only",
            "resolved_reject_all",
            "requires_aggregation_policy",
            "requires_dimension_policy",
            "requires_manual_taxonomy_mapping",
        ],
        "conflict_group_allowed_transitions": {
            "unresolved": ["in_review"],
            "in_review": [
                "resolved_choose_one",
                "resolved_keep_multiple",
                "resolved_context_only",
                "resolved_reject_all",
                "requires_aggregation_policy",
                "requires_dimension_policy",
                "requires_manual_taxonomy_mapping",
            ],
            "resolved_choose_one": ["in_review"],
            "resolved_keep_multiple": ["in_review"],
            "resolved_context_only": ["in_review"],
            "resolved_reject_all": ["in_review"],
            "requires_aggregation_policy": ["in_review"],
            "requires_dimension_policy": ["in_review"],
            "requires_manual_taxonomy_mapping": ["in_review"],
        },
        "batch_statuses": [
            "draft",
            "ready_for_review",
            "in_review",
            "partially_reviewed",
            "review_complete",
            "ready_for_mapping_handoff",
            "blocked_by_unresolved_conflicts",
            "archived",
        ],
        "batch_allowed_transitions": {
            "draft": ["ready_for_review", "archived"],
            "ready_for_review": ["in_review", "archived"],
            "in_review": ["partially_reviewed", "review_complete", "blocked_by_unresolved_conflicts", "archived"],
            "partially_reviewed": ["in_review", "review_complete", "blocked_by_unresolved_conflicts", "archived"],
            "review_complete": ["ready_for_mapping_handoff", "archived"],
            "ready_for_mapping_handoff": ["archived"],
            "blocked_by_unresolved_conflicts": ["in_review", "archived"],
            "archived": [],
        },
    }


def build_mapping_handoff_rules() -> Dict[str, Any]:
    return {
        "allowed_without_review": [
            {
                "gate_status": "auto_mappable_candidate",
                "conditions": ["not conflict-blocked", "not suppressed", "not downgraded", "valid label/value/text"],
                "requires_confirmation": False,
            }
        ],
        "allowed_with_confirmation": [
            {
                "gate_status": "suggest_mapping_only",
                "conditions": ["requires_confirmation=true", "not conflict-blocked", "review warnings preserved"],
                "requires_confirmation": True,
            },
            {
                "decision_status": "approved_for_mapping",
                "conditions": ["reviewer explicitly approved candidate"],
                "requires_confirmation": False,
            },
            {
                "decision_status": "corrected_and_approved",
                "conditions": ["final corrected fields captured in reviewer decision"],
                "requires_confirmation": False,
            },
        ],
        "blocked_from_handoff": [
            "manual_review_required and unresolved",
            "blocked_from_mapping",
            "reference_only_or_context",
            "suppressed exact duplicate",
            "downgraded metadata/date/year row",
            "unresolved conflict group",
            "rejected candidate",
            "candidate requiring aggregation policy",
            "candidate requiring dimension policy",
        ],
        "handoff_item_fields": [
            "mapping_allowed",
            "requires_confirmation",
            "review_decision_id",
            "original_candidate_id",
            "cleaned_candidate_id",
            "final_label",
            "final_value",
            "final_previous_value",
            "final_row_type",
            "final_statement_section",
            "warnings",
            "provenance",
        ],
    }


def build_ui_api_plan_report(
    queue_summary: Mapping[str, Any], input_paths: Optional[Mapping[str, str]] = None
) -> Dict[str, Any]:
    return {
        "metadata": build_no_side_effect_metadata(),
        "planning_inputs": dict(input_paths or DEFAULT_INPUT_PATHS),
        "queue_summary": dict(queue_summary),
        "api_design": {
            "auth_assumption": "Use existing authenticated user and tenant/job isolation; add reviewer permissions before production use.",
            "endpoints": build_api_endpoints(),
        },
        "react_ui_design": {
            "entry_point": {
                "recommendation": "Expose the queue from the TaxonomyFlow workspace as a review batch tied to an extraction job or benchmark report.",
                "scope": "Per review batch with case-level filters, not a global unscoped inbox.",
            },
            "queue_list_view": {
                "required_controls": [
                    "priority filters",
                    "case filter",
                    "row_type filter",
                    "gate_status filter",
                    "reason-code filter",
                    "conflict-only filter",
                    "search by label/value/text",
                    "progress counts",
                    "review completion status",
                ],
                "layout_intent": "Dense table optimized for triage, with batch summary and unresolved conflict counters.",
            },
            "review_detail_panel": {
                "must_show": [
                    "candidate label/value/previous_value/text",
                    "statement section",
                    "page number",
                    "source snippet",
                    "extracted evidence",
                    "duplicate/conflict group context",
                    "reason codes",
                    "recommended reviewer action",
                    "decision options",
                ]
            },
            "conflict_group_view": {
                "must_show": [
                    "all candidate options",
                    "value variants",
                    "affected pages/sections",
                    "block reason",
                    "decision options",
                ],
                "decision_options": [
                    "choose_one_candidate",
                    "keep_multiple_as_detail_rows",
                    "mark_all_as_context_only",
                    "reject_all",
                    "require_aggregation_policy",
                    "require_dimension_policy",
                    "require_manual_taxonomy_mapping",
                ],
            },
            "reviewer_decision_ui": {
                "controls": [
                    "approve for mapping",
                    "suggest mapping only",
                    "block from mapping",
                    "correct label",
                    "correct value",
                    "correct previous value",
                    "correct section",
                    "correct row type",
                    "mark as metadata/context only",
                    "reject candidate",
                    "require manual taxonomy mapping",
                    "add reviewer note",
                ]
            },
            "mapping_handoff_preview": {
                "must_show": [
                    "candidates that will enter #13V",
                    "candidates requiring confirmation",
                    "candidates blocked",
                    "unresolved conflicts",
                    "readiness to proceed",
                ]
            },
        },
        "review_state_transitions": build_review_state_transitions(),
        "conflict_surfacing_policy": {
            "preserve_all_options": True,
            "automatic_winner_selection": False,
            "block_auto_mapping_while_unresolved": True,
            "reviewer_group_decisions": [
                "choose_one_candidate",
                "keep_multiple_as_detail_rows",
                "mark_all_as_context_only",
                "reject_all",
                "require_aggregation_policy",
                "require_dimension_policy",
                "require_manual_taxonomy_mapping",
            ],
        },
        "mapping_handoff_rules": build_mapping_handoff_rules(),
        "security_auth_considerations": [
            "Require authenticated access to the source job, report, or batch.",
            "Preserve tenant/user isolation for source evidence and exports.",
            "Store reviewer decisions as audit records with user and timestamp.",
            "Do not expose model prompts, tokens, or environment values.",
            "Separate benchmark report imports from production extraction jobs until a production import policy exists.",
        ],
        "non_goals": [
            "No DB schema or migration implementation.",
            "No API route implementation.",
            "No React/frontend implementation.",
            "No mapping v2 implementation.",
            "No XBRL generation or Arelle validation.",
            "No live model calls or benchmark rerun.",
        ],
    }


def build_implementation_sequence_report(
    queue_summary: Mapping[str, Any], input_paths: Optional[Mapping[str, str]] = None
) -> Dict[str, Any]:
    return {
        "metadata": build_no_side_effect_metadata(),
        "planning_inputs": dict(input_paths or DEFAULT_INPUT_PATHS),
        "queue_summary": dict(queue_summary),
        "recommended_next_feature": "Feature #13V - Report-based mapping handoff contract with no DB mutation.",
        "staged_roadmap": [
            {
                "feature": "13V-data-contract",
                "title": "Report-based mapping handoff contract with no DB mutation",
                "goal": "Produce a deterministic JSON handoff containing only allowed mapping inputs from #13T/#13U gates.",
                "acceptance_criteria": [
                    "No DB mutation",
                    "No taxonomy mapping",
                    "Suppressed/manual-review/reference-only candidates excluded",
                    "Suggest-only candidates marked requires_confirmation=true",
                ],
            },
            {
                "feature": "13W-mapping-v2-sandbox",
                "title": "Mapping candidate generation v2 sandbox",
                "goal": "Generate taxonomy mapping suggestions only for handoff-approved candidates.",
                "acceptance_criteria": [
                    "No production cutover",
                    "No XBRL generation",
                    "Manual-review and conflict-blocked candidates remain excluded",
                ],
            },
            {
                "feature": "13X-manual-review-db-design",
                "title": "Manual-review DB schema design before API/UI implementation",
                "goal": "Design and review durable tables after report-based contracts are stable.",
                "acceptance_criteria": [
                    "Explicit migration plan",
                    "Audit trail preserved",
                    "Benchmark and production sources separated",
                ],
            },
            {
                "feature": "13Y-manual-review-api",
                "title": "Manual-review API implementation",
                "goal": "Implement authenticated review batch, item, conflict, decision, and export endpoints.",
                "acceptance_criteria": [
                    "Authorization enforced",
                    "State transitions validated",
                    "Decision audit trail stored",
                ],
            },
            {
                "feature": "13Z-manual-review-ui",
                "title": "Manual-review React queue UI",
                "goal": "Build the queue, detail, conflict, decision, and handoff preview workflow.",
                "acceptance_criteria": [
                    "Queue filters and progress counts implemented",
                    "Conflict groups surfaced",
                    "Reviewer decisions captured safely",
                ],
            },
            {
                "feature": "later",
                "title": "Mapping handoff integration, XBRL sandbox generation, and Arelle validation",
                "goal": "Only after review and mapping candidate gates are stable, test downstream XBRL generation and validation.",
                "acceptance_criteria": [
                    "Reviewed mapping handoff exists",
                    "Mapping quality evidence available",
                    "Validation failures surfaced without production cutover",
                ],
            },
        ],
        "dependencies": [
            "#13Q full Hugging Face Qwen benchmark",
            "#13R quality/readiness analysis",
            "#13S duplicate/conflict cleanup",
            "#13T manual-review policy and queue reports",
        ],
        "risks_and_mitigations": [
            _risk("reviewer choosing wrong candidate", "Require evidence preview, conflict context, and reversible audit decisions."),
            _risk("blocking too many candidates", "Track blocked counts and allow suggest-only review paths before hard rejection."),
            _risk("allowing too many candidates into mapping", "Enforce handoff gates and unresolved-conflict blocks before mapping candidate generation."),
            _risk("conflict groups delaying mapping", "Prioritize critical numeric conflicts and allow case-level progress summaries."),
            _risk("introducing DB schema too early", "Start with report-based handoff before migrations."),
            _risk("UI complexity", "Implement dense MVP queue filters before advanced dashboards."),
            _risk("mixing benchmark reports with production jobs", "Record source type and keep batch import policy explicit."),
            _risk("missing audit trail", "Store reviewer identity, timestamps, original values, corrected values, and decision history."),
            _risk("mapping before review decisions exist", "Block unresolved manual-review and conflict statuses from handoff."),
        ],
        "future_acceptance_criteria": [
            "Mapping handoff can be regenerated from review batch state.",
            "No suppressed, blocked, reference/context, or unresolved conflict candidates enter mapping.",
            "Reviewer decisions are auditable and reversible before production cutover.",
            "API/UI implementation preserves existing auth and user isolation.",
        ],
    }


def _risk(title: str, mitigation: str) -> Dict[str, str]:
    return {"risk": title, "mitigation": mitigation}


def build_manual_review_queue_plan_reports(
    manual_review_policy: Mapping[str, Any],
    mapping_gate_report: Mapping[str, Any],
    manual_review_queue: Mapping[str, Any],
    input_paths: Optional[Mapping[str, str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    paths = dict(input_paths or DEFAULT_INPUT_PATHS)
    queue_summary = extract_queue_summary(manual_review_policy, mapping_gate_report, manual_review_queue)
    ui_api_plan = build_ui_api_plan_report(queue_summary, paths)
    data_contract = build_data_contract_report(queue_summary, paths)
    implementation_sequence = build_implementation_sequence_report(queue_summary, paths)
    return ui_api_plan, data_contract, implementation_sequence


def render_ui_api_plan_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("queue_summary", {})
    lines = [
        "# Manual Review Queue UI/API Plan - Feature #13U",
        "",
        "## Scope",
        "Planning only. No DB schema, API route, React UI, mapping, XBRL, Arelle, benchmark rerun, or live model call was implemented.",
        "",
        "## Queue Summary",
        f"- Auto mappable: {summary.get('auto_mappable_candidate', 0)}",
        f"- Suggest mapping only: {summary.get('suggest_mapping_only', 0)}",
        f"- Manual review required: {summary.get('manual_review_required', 0)}",
        f"- Blocked from mapping: {summary.get('blocked_from_mapping', 0)}",
        f"- Reference/context only: {summary.get('reference_only_or_context', 0)}",
        f"- Manual review queue items: {summary.get('manual_review_queue_items', 0)}",
        f"- Conflict groups: {summary.get('conflict_group_count', 0)}",
        "",
        "## Future API Design",
    ]
    for endpoint in report.get("api_design", {}).get("endpoints", []):
        lines.append(f"- `{endpoint['method']} {endpoint['path']}`: {endpoint['purpose']}")
    lines.extend(
        [
            "",
            "## Future React UI Design",
            "- Queue list view: priority, case, row type, gate status, reason-code, conflict-only, and search filters.",
            "- Review detail panel: candidate evidence, reasons, source snippets, and decision controls.",
            "- Conflict group view: all options, value variants, affected pages/sections, and group decisions.",
            "- Mapping handoff preview: allowed, confirmation-required, blocked, and unresolved conflict counts.",
            "",
            "## Review State Transitions",
            "- Candidate, conflict group, and batch state machines are defined in the JSON report.",
            "",
            "## Mapping Handoff Rules",
            "- Auto mappable candidates may proceed when not conflict-blocked.",
            "- Suggest-only candidates may proceed with `requires_confirmation=true`.",
            "- Manual-review, blocked, reference/context, suppressed, downgraded, and unresolved conflict candidates cannot proceed automatically.",
            "",
            "## Non-Goals",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("non_goals", []))
    return "\n".join(lines) + "\n"


def render_data_contract_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Manual Review Queue Data Contract - Feature #13U",
        "",
        "## Storage Strategy",
        f"- Recommended first step: {report.get('storage_strategy', {}).get('recommended_first_step', 'JSON report-only flow')}",
        "- Do not extend production extraction rows until report-based handoff behavior is stable.",
        "",
        "## Proposed Entities",
    ]
    for entity in report.get("entities", []):
        lines.append(f"- `{entity['name']}`: {entity['purpose']}")
    lines.extend(
        [
            "",
            "## Validation Rules",
        ]
    )
    lines.extend(f"- {rule}" for rule in report.get("validation_rules", []))
    lines.extend(
        [
            "",
            "## Audit Trail Requirements",
        ]
    )
    lines.extend(f"- {rule}" for rule in report.get("audit_trail_requirements", []))
    lines.extend(
        [
            "",
            "## Mapping Handoff Contract",
            "- Include original and cleaned candidate identifiers, final reviewed fields, warnings, provenance, and conflict status.",
            "- Exclude suppressed, downgraded metadata/date/year, blocked, and unresolved conflict candidates from automatic mapping.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_implementation_sequence_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Manual Review Queue Implementation Sequence - Feature #13U",
        "",
        f"Recommended next feature: {report.get('recommended_next_feature')}",
        "",
        "## Staged Roadmap",
    ]
    for step in report.get("staged_roadmap", []):
        lines.append(f"- `{step['feature']}`: {step['title']}")
    lines.extend(
        [
            "",
            "## Risks And Mitigations",
        ]
    )
    for risk in report.get("risks_and_mitigations", []):
        lines.append(f"- {risk['risk']}: {risk['mitigation']}")
    lines.extend(
        [
            "",
            "## Future Acceptance Criteria",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("future_acceptance_criteria", []))
    return "\n".join(lines) + "\n"
