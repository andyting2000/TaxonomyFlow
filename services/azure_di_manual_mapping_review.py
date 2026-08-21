"""Report-only manual review workflow for Azure DI mapping candidates."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_MAPPING_REPORT = Path("reports/azure_di_mapping_candidates_14a.json")
DEFAULT_CONFIDENCE_REPORT = Path("reports/azure_di_mapping_confidence_14a.json")
DEFAULT_GAP_REPORT = Path("reports/azure_di_mapping_gap_analysis_14a.json")
DEFAULT_OUTPUT_DIR = Path("reports")

NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
HIGH_OR_MEDIUM_STATUSES = {"high_confidence_suggestion", "medium_confidence_suggestion"}
WEAK_STATUSES = {"low_confidence_suggestion", "no_safe_suggestion", "ambiguous_multiple_suggestions"}

BASE_REVIEW_DECISIONS = [
    "approve_suggested_concept",
    "approve_alternative_concept",
    "correct_label_and_approve",
    "correct_section_and_approve",
    "mark_as_context_only",
    "reject_mapping",
    "request_alias_enrichment",
    "request_concept_metadata_enrichment",
    "require_manual_taxonomy_mapping",
    "defer_mapping",
    "split_candidate",
    "merge_candidate",
    "keep_for_notes_only",
]

AMBIGUOUS_DECISIONS = [
    "choose_one_concept",
    "keep_multiple_concepts_as_detail_rows",
    "reject_all_suggestions",
    "require_dimension_policy",
    "require_aggregation_policy",
    "require_manual_taxonomy_mapping",
]

NO_SAFE_DECISIONS = [
    "request_alias_enrichment",
    "request_concept_metadata_enrichment",
    "manual_taxonomy_search_required",
    "mark_as_unmappable",
    "keep_for_context_only",
]


@dataclass(frozen=True)
class ManualReviewOutputPaths:
    queue_json: Path
    queue_md: Path
    policy_json: Path
    policy_md: Path
    contract_json: Path
    contract_md: Path
    summary_json: Path
    summary_md: Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def no_side_effect_metadata() -> dict[str, Any]:
    return {
        "feature": "14B",
        "generated_at": utc_now_iso(),
        "read_only": True,
        "database_mutated": False,
        "db_schema_changed": False,
        "migration_created": False,
        "api_routes_implemented": False,
        "frontend_code_modified": False,
        "production_behavior_changed": False,
        "production_extraction_behavior_changed": False,
        "production_mapping_behavior_changed": False,
        "final_mapping_approved": False,
        "automatic_winner_selection_for_ambiguous_suggestions": False,
        "semantic_matcher_called": False,
        "production_semantic_matcher_called": False,
        "embeddings_used": False,
        "xbrl_generated": False,
        "arelle_validation_run": False,
        "azure_di_live_call_made": False,
        "live_huggingface_calls_made": False,
        "live_openai_calls_made": False,
        "external_provider_calls": False,
        "reference_xml_sent_to_model": False,
        "reference_xml_sent_to_provider": False,
    }


def output_paths_from_prefix(output_prefix: str | Path | None = None) -> ManualReviewOutputPaths:
    if output_prefix is None:
        root = DEFAULT_OUTPUT_DIR
        return ManualReviewOutputPaths(
            queue_json=root / "azure_di_manual_mapping_review_queue_14b.json",
            queue_md=root / "azure_di_manual_mapping_review_queue_14b.md",
            policy_json=root / "azure_di_mapping_review_policy_14b.json",
            policy_md=root / "azure_di_mapping_review_policy_14b.md",
            contract_json=root / "azure_di_mapping_review_handoff_contract_14b.json",
            contract_md=root / "azure_di_mapping_review_handoff_contract_14b.md",
            summary_json=root / "azure_di_mapping_review_summary_14b.json",
            summary_md=root / "azure_di_mapping_review_summary_14b.md",
        )
    prefix = Path(output_prefix)
    return ManualReviewOutputPaths(
        queue_json=Path(f"{prefix}_manual_mapping_review_queue_14b.json"),
        queue_md=Path(f"{prefix}_manual_mapping_review_queue_14b.md"),
        policy_json=Path(f"{prefix}_mapping_review_policy_14b.json"),
        policy_md=Path(f"{prefix}_mapping_review_policy_14b.md"),
        contract_json=Path(f"{prefix}_mapping_review_handoff_contract_14b.json"),
        contract_md=Path(f"{prefix}_mapping_review_handoff_contract_14b.md"),
        summary_json=Path(f"{prefix}_mapping_review_summary_14b.json"),
        summary_md=Path(f"{prefix}_mapping_review_summary_14b.md"),
    )


def _load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _score(record: Mapping[str, Any]) -> float:
    top = record.get("top_suggestion") or {}
    try:
        return float(top.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _concept_type_mismatch(record: Mapping[str, Any]) -> bool:
    blockers = set(str(item) for item in record.get("blockers") or [])
    if "row_type_or_concept_type_mismatch" in blockers:
        return True
    top = record.get("top_suggestion") or {}
    evidence = top.get("evidence") or {}
    if top and evidence.get("concept_type_match") is False:
        return True
    if top and evidence.get("row_type_match") is False:
        return True
    row_type = str(record.get("row_type") or "")
    if row_type in NUMERIC_ROW_TYPES and top.get("is_text_block_concept") is True:
        return True
    if row_type == "text_block" and top.get("is_numeric_concept") is True:
        return True
    return False


def _section_compatible(record: Mapping[str, Any]) -> bool:
    top = record.get("top_suggestion") or {}
    evidence = top.get("evidence") or {}
    return not bool(evidence.get("section_family_mismatch"))


def classify_workflow_status(record: Mapping[str, Any]) -> str:
    mapping_status = str(record.get("mapping_status") or "")
    row_type = str(record.get("row_type") or "")
    blockers = set(str(item) for item in record.get("blockers") or [])
    gate_status = str(record.get("gate_status") or "")
    requires_confirmation = bool(record.get("requires_confirmation"))
    top = record.get("top_suggestion") or {}

    if mapping_status == "blocked_by_gate" or _concept_type_mismatch(record):
        return "blocked_from_xbrl"
    if mapping_status == "ambiguous_multiple_suggestions":
        return "needs_human_concept_choice"
    if requires_confirmation or gate_status == "suggest_mapping_only":
        return "needs_confirmation"
    if mapping_status == "high_confidence_suggestion":
        return "ready_for_review_approval"
    if mapping_status == "medium_confidence_suggestion":
        if top and _score(record) >= 0.70 and _section_compatible(record) and not blockers:
            return "ready_for_review_approval"
        return "needs_confirmation"
    if mapping_status == "no_safe_suggestion":
        if row_type == "text_block" and "generic_or_weak_label" not in blockers:
            return "needs_alias_or_metadata_enrichment"
        if "generic_or_weak_label" in blockers or row_type in NUMERIC_ROW_TYPES:
            return "blocked_from_xbrl"
        return "needs_alias_or_metadata_enrichment"
    if mapping_status == "low_confidence_suggestion":
        if row_type == "text_block" and _score(record) < 0.25:
            return "context_only"
        return "needs_alias_or_metadata_enrichment"
    return "context_only"


def classify_priority(record: Mapping[str, Any], workflow_status: str) -> str:
    row_type = str(record.get("row_type") or "")
    mapping_status = str(record.get("mapping_status") or "")
    requires_confirmation = bool(record.get("requires_confirmation"))

    if workflow_status == "blocked_from_xbrl" or _concept_type_mismatch(record):
        return "critical"
    if row_type in NUMERIC_ROW_TYPES and mapping_status in {"ambiguous_multiple_suggestions", "no_safe_suggestion"}:
        return "critical"
    if mapping_status == "ambiguous_multiple_suggestions":
        return "high"
    if row_type in NUMERIC_ROW_TYPES and mapping_status == "low_confidence_suggestion":
        return "high"
    if row_type == "subtotal_or_total":
        return "high"
    if row_type in NUMERIC_ROW_TYPES and requires_confirmation:
        return "high"
    if workflow_status == "needs_confirmation":
        return "medium"
    if row_type == "text_block" and workflow_status in {"needs_alias_or_metadata_enrichment", "needs_human_concept_choice"}:
        return "medium"
    if mapping_status in HIGH_OR_MEDIUM_STATUSES:
        return "medium"
    return "low"


def _review_reasons(record: Mapping[str, Any], workflow_status: str) -> list[str]:
    reasons = [f"workflow_status:{workflow_status}", f"mapping_status:{record.get('mapping_status') or 'unknown'}"]
    if record.get("requires_confirmation"):
        reasons.append("requires_confirmation_from_handoff_gate")
    if record.get("blockers"):
        reasons.extend(f"blocker:{blocker}" for blocker in record.get("blockers") or [])
    if record.get("mapping_status") == "ambiguous_multiple_suggestions":
        reasons.append("multiple_plausible_concepts_require_human_choice")
    if record.get("mapping_status") == "no_safe_suggestion":
        reasons.append("no_safe_deterministic_concept_suggestion")
    if _concept_type_mismatch(record):
        reasons.append("concept_type_mismatch_blocks_xbrl")
    top = record.get("top_suggestion") or {}
    if top:
        reasons.append(f"top_suggestion_score:{_score(record):.4f}")
    return reasons


def reviewer_decision_options_for(record: Mapping[str, Any], workflow_status: str) -> list[str]:
    options = list(BASE_REVIEW_DECISIONS)
    if workflow_status == "needs_human_concept_choice":
        options.extend(AMBIGUOUS_DECISIONS)
    if workflow_status in {"needs_alias_or_metadata_enrichment", "blocked_from_xbrl"} or record.get("mapping_status") == "no_safe_suggestion":
        options.extend(NO_SAFE_DECISIONS)
    if workflow_status == "context_only":
        options = ["mark_as_context_only", "keep_for_notes_only", "reject_mapping", "defer_mapping"]
    return sorted(dict.fromkeys(options))


def _recommended_action(workflow_status: str) -> str:
    return {
        "ready_for_review_approval": "Review evidence and approve only if the suggested concept is correct.",
        "needs_human_concept_choice": "Choose one concept, reject all, or request policy for dimensions/aggregation/detail rows.",
        "needs_confirmation": "Confirm or reject the suggested concept before any future mapping handoff.",
        "needs_alias_or_metadata_enrichment": "Request alias or concept metadata enrichment, then rerun mapping suggestions.",
        "blocked_from_xbrl": "Reject or defer; do not allow into XBRL until the blocker is resolved by a reviewer.",
        "context_only": "Keep as review context or notes-only evidence, not as a mapped fact.",
    }.get(workflow_status, "Review manually before use.")


def _source_evidence(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "label": record.get("label"),
        "value": record.get("value"),
        "previous_value": record.get("previous_value"),
        "text_preview": record.get("text_preview"),
        "statement_section": record.get("statement_section"),
        "warning_flags": list(record.get("warning_flags") or []),
        "blockers": list(record.get("blockers") or []),
    }


def _provenance(record: Mapping[str, Any]) -> dict[str, Any]:
    audit = record.get("audit_trail") or {}
    source_audit = audit.get("source_handoff_audit_trail") or {}
    return {
        "case_id": record.get("case_id"),
        "page_number": record.get("page_number"),
        "mapping_input_id": record.get("mapping_input_id"),
        "source_candidate_id": record.get("source_candidate_id"),
        "source_handoff_audit_trail": source_audit,
        "mapping_audit_trail": audit,
    }


def build_review_queue(mapping_report: Mapping[str, Any], *, run_id: str | None, input_paths: Mapping[str, Any]) -> dict[str, Any]:
    queue_items = []
    for index, record in enumerate(mapping_report.get("mapping_records") or [], start=1):
        workflow_status = classify_workflow_status(record)
        priority = classify_priority(record, workflow_status)
        top = record.get("top_suggestion")
        item = {
            "review_mapping_item_id": f"14B-REVIEW-{index:04d}",
            "mapping_input_id": record.get("mapping_input_id"),
            "source_candidate_id": record.get("source_candidate_id"),
            "case_id": record.get("case_id"),
            "page_number": record.get("page_number"),
            "row_type": record.get("row_type"),
            "label": record.get("label"),
            "value": record.get("value"),
            "previous_value": record.get("previous_value"),
            "text_preview": record.get("text_preview"),
            "statement_section": record.get("statement_section"),
            "gate_status": record.get("gate_status"),
            "requires_confirmation": bool(record.get("requires_confirmation")),
            "mapping_status": record.get("mapping_status"),
            "workflow_status": workflow_status,
            "priority": priority,
            "top_suggestion": top,
            "suggestions": list(record.get("suggestions") or []),
            "confidence_tier": (top or {}).get("confidence_tier") if top else "none",
            "score": _score(record) if top else 0.0,
            "review_reasons": _review_reasons(record, workflow_status),
            "blockers": list(record.get("blockers") or []),
            "warnings": list(record.get("warning_flags") or []),
            "source_evidence": _source_evidence(record),
            "provenance": _provenance(record),
            "recommended_reviewer_action": _recommended_action(workflow_status),
            "reviewer_decision_options": reviewer_decision_options_for(record, workflow_status),
            "audit_trail": {
                "source": "14B_report_only_manual_mapping_review_queue",
                "mapping_input_id": record.get("mapping_input_id"),
                "source_candidate_id": record.get("source_candidate_id"),
                "source_mapping_status": record.get("mapping_status"),
                "source_mapping_decision_status": "suggested_only",
                "final_mapping_approved": False,
                "xbrl_eligible": False,
            },
        }
        queue_items.append(item)

    workflow_counts = Counter(item["workflow_status"] for item in queue_items)
    priority_counts = Counter(item["priority"] for item in queue_items)
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_manual_mapping_review_queue",
            "script": "scripts/build_azure_di_manual_mapping_review_14b.py",
        },
        "input_reports": dict(input_paths),
        "source_feature_chain": ["13X", "13Y", "13Z", "14A", "14B"],
        "total_mapping_records": len(mapping_report.get("mapping_records") or []),
        "review_queue_count": len(queue_items),
        "workflow_status_distribution": dict(workflow_counts),
        "priority_distribution": dict(priority_counts),
        "queue_items": queue_items,
        "traceability_summary": {
            "items": len(queue_items),
            "items_with_mapping_input_id": sum(1 for item in queue_items if item.get("mapping_input_id")),
            "items_with_source_candidate_id": sum(1 for item in queue_items if item.get("source_candidate_id")),
            "coverage_ratio": 1.0
            if not queue_items
            else round(
                sum(1 for item in queue_items if item.get("mapping_input_id") and item.get("source_candidate_id"))
                / len(queue_items),
                4,
            ),
        },
        "limitations": [
            "Review queue is report-only and does not approve mappings.",
            "No DB/API/UI implementation is included.",
            "No XBRL generation or Arelle validation can use this queue directly.",
        ],
    }


def build_policy_report(*, run_id: str | None, input_paths: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_mapping_review_policy",
            "script": "scripts/build_azure_di_manual_mapping_review_14b.py",
        },
        "input_reports": dict(input_paths),
        "workflow_status_definitions": {
            "ready_for_review_approval": "High or strong medium suggestions that may be approved only by a human reviewer.",
            "needs_human_concept_choice": "Ambiguous suggestions where a reviewer must choose a concept, reject all, or require policy.",
            "needs_confirmation": "Suggest-only or confirmation-required candidates that cannot proceed without explicit reviewer confirmation.",
            "needs_alias_or_metadata_enrichment": "Weak/no-safe candidates where labels are understandable but aliases or concept metadata are insufficient.",
            "blocked_from_xbrl": "Records with weak evidence, unsafe gates, concept type conflicts, or no safe concept; they must not enter XBRL.",
            "context_only": "Useful review context or notes-only evidence, not a mapped fact.",
        },
        "priority_definitions": {
            "critical": "Concept type mismatch, blocked_from_xbrl, or material numeric ambiguity/no-safe status.",
            "high": "Ambiguous suggestions, low-confidence numeric facts, subtotal/total uncertainty, or confirmation-required numeric candidates.",
            "medium": "Medium suggestions, suggest-only text blocks, or text-block concept uncertainty.",
            "low": "Context-only records, no-safe narrative context, or alias enrichment candidates with low XBRL impact.",
        },
        "reviewer_decision_option_definitions": {
            option: "Allowed manual review decision option; modeled for future workflow only."
            for option in sorted(set(BASE_REVIEW_DECISIONS + AMBIGUOUS_DECISIONS + NO_SAFE_DECISIONS))
        },
        "required_evidence_for_approval": [
            "mapping_input_id and source_candidate_id traceability",
            "source label/text/value evidence",
            "chosen concept qname and label",
            "row type and concept type compatibility",
            "statement section compatibility or reviewer override rationale",
            "reviewer identity, timestamp, decision, and notes in a future workflow",
        ],
        "future_approved_mapping_handoff_rules": [
            "Only reviewer-approved mappings can enter a future approved mapping handoff.",
            "High-confidence suggestions still require human approval.",
            "Suggest-only mappings require explicit confirmation.",
            "Ambiguous mappings require explicit concept choice or rejection.",
            "No-safe mappings require manual taxonomy mapping or enrichment before approval.",
            "Rejected, context-only, and deferred mappings are not XBRL eligible.",
        ],
        "blocked_rules": [
            "Concept type mismatch remains blocked until corrected by a reviewer.",
            "No automatic winner selection is allowed for ambiguous suggestions.",
            "No XBRL can be generated from #14B reports.",
        ],
        "audit_requirements": [
            "Preserve Azure DI source candidate provenance.",
            "Preserve mapping_input_id and source_candidate_id.",
            "Preserve source suggestions and reviewer decision trail.",
            "Record all label, section, and concept corrections.",
        ],
        "non_goals": [
            "No final mapping approval in #14B.",
            "No DB, API, or UI implementation.",
            "No XBRL generation or Arelle validation.",
            "No production semantic matcher call.",
            "No live provider or model calls.",
        ],
    }


def build_handoff_contract_report(*, run_id: str | None, input_paths: Mapping[str, Any]) -> dict[str, Any]:
    schema_fields = {
        "reviewed_mapping_id": "Stable reviewed mapping identifier.",
        "mapping_input_id": "Trace to #13Y/#14A handoff mapping input.",
        "source_candidate_id": "Trace to Azure DI normalized extraction candidate.",
        "case_id": "Source case identifier.",
        "final_concept_qname": "Reviewer-approved concept qname.",
        "final_concept_label": "Reviewer-approved concept label.",
        "final_concept_type": "Reviewer-approved concept type.",
        "final_label": "Reviewer-approved source label.",
        "final_value": "Reviewer-approved current value.",
        "final_previous_value": "Reviewer-approved prior value.",
        "final_text": "Reviewer-approved narrative text.",
        "final_row_type": "Reviewer-approved row type.",
        "final_statement_section": "Reviewer-approved statement section.",
        "reviewer_decision": "Structured reviewer decision.",
        "reviewer_notes": "Human notes supporting the decision.",
        "reviewed_by": "Reviewer identifier.",
        "reviewed_at": "Review timestamp.",
        "approval_status": "approved, rejected, context_only, deferred, or needs_more_information.",
        "requires_confirmation": "Whether source gate required confirmation.",
        "source_suggestion_id": "Trace to the selected source suggestion.",
        "evidence": "Source evidence used by reviewer.",
        "provenance": "Azure DI and mapping provenance.",
        "audit_trail": "Full review audit trail.",
        "xbrl_eligible": "True only after reviewer approval and eligibility checks.",
        "xbrl_blockers": "Reasons a reviewed mapping cannot be used for XBRL.",
    }
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_mapping_review_handoff_contract",
            "script": "scripts/build_azure_di_manual_mapping_review_14b.py",
        },
        "input_reports": dict(input_paths),
        "contract_status": "future_schema_only_no_approved_mappings",
        "reviewed_mapping_schema": schema_fields,
        "eligibility_rules": [
            "Only reviewer-approved mappings can become xbrl_eligible.",
            "High-confidence suggestions still require approval.",
            "Suggest-only mappings require confirmation.",
            "Ambiguous mappings require explicit concept choice.",
            "No-safe mappings require manual taxonomy mapping or enrichment before approval.",
            "Rejected, context-only, and deferred mappings are not XBRL eligible.",
        ],
        "approval_status_values": [
            "approved",
            "rejected",
            "context_only",
            "deferred",
            "needs_more_information",
        ],
        "empty_reviewed_mapping_records": [],
        "limitations": [
            "This contract defines a future handoff shape only.",
            "No reviewed mapping record is produced or approved by #14B.",
            "No XBRL eligibility is granted by this report.",
        ],
    }


def _top_labels(records: Iterable[Mapping[str, Any]], status: str, limit: int = 10) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        if record.get("mapping_status") != status:
            continue
        rows.append(
            {
                "mapping_input_id": record.get("mapping_input_id"),
                "label": record.get("label"),
                "row_type": record.get("row_type"),
                "statement_section": record.get("statement_section"),
                "blockers": record.get("blockers") or [],
            }
        )
    return rows[:limit]


def build_summary_report(
    *,
    queue_report: Mapping[str, Any],
    mapping_report: Mapping[str, Any],
    confidence_report: Mapping[str, Any],
    gap_report: Mapping[str, Any],
    run_id: str | None,
    input_paths: Mapping[str, Any],
) -> dict[str, Any]:
    records = list(mapping_report.get("mapping_records") or [])
    queue_items = list(queue_report.get("queue_items") or [])
    workflow_counts = Counter(item.get("workflow_status") for item in queue_items)
    priority_counts = Counter(item.get("priority") for item in queue_items)
    alias_candidates = [
        item
        for item in queue_items
        if item.get("workflow_status") == "needs_alias_or_metadata_enrichment"
        or "request_alias_enrichment" in (item.get("reviewer_decision_options") or [])
    ]
    metadata_candidates = [
        item
        for item in queue_items
        if item.get("workflow_status") == "needs_alias_or_metadata_enrichment"
        or "request_concept_metadata_enrichment" in (item.get("reviewer_decision_options") or [])
    ]
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_mapping_review_summary",
            "script": "scripts/build_azure_di_manual_mapping_review_14b.py",
        },
        "input_reports": dict(input_paths),
        "total_mapping_records": len(records),
        "review_queue_count": len(queue_items),
        "workflow_status_distribution": dict(workflow_counts),
        "priority_distribution": dict(priority_counts),
        "ready_for_review_approval_count": workflow_counts.get("ready_for_review_approval", 0),
        "needs_human_concept_choice_count": workflow_counts.get("needs_human_concept_choice", 0),
        "needs_confirmation_count": workflow_counts.get("needs_confirmation", 0),
        "needs_alias_or_metadata_enrichment_count": workflow_counts.get("needs_alias_or_metadata_enrichment", 0),
        "blocked_from_xbrl_count": workflow_counts.get("blocked_from_xbrl", 0),
        "context_only_count": workflow_counts.get("context_only", 0),
        "source_14a_status_counts": dict(confidence_report.get("status_counts") or mapping_report.get("status_counts") or {}),
        "source_14a_confidence_tier_counts": dict(confidence_report.get("confidence_tier_counts") or {}),
        "top_ambiguous_labels": _top_labels(records, "ambiguous_multiple_suggestions", limit=15),
        "top_no_safe_labels": _top_labels(records, "no_safe_suggestion", limit=15),
        "top_alias_enrichment_candidates": [
            {
                "review_mapping_item_id": item.get("review_mapping_item_id"),
                "mapping_input_id": item.get("mapping_input_id"),
                "label": item.get("label"),
                "row_type": item.get("row_type"),
                "priority": item.get("priority"),
            }
            for item in alias_candidates[:15]
        ],
        "top_concept_metadata_enrichment_candidates": [
            {
                "review_mapping_item_id": item.get("review_mapping_item_id"),
                "mapping_input_id": item.get("mapping_input_id"),
                "label": item.get("label"),
                "row_type": item.get("row_type"),
                "priority": item.get("priority"),
            }
            for item in metadata_candidates[:15]
        ],
        "gap_report_context": {
            "labels_with_no_safe_suggestion": gap_report.get("labels_with_no_safe_suggestion") or [],
            "labels_still_ambiguous": gap_report.get("labels_still_ambiguous") or [],
        },
        "estimated_review_workload": {
            "total_items": len(queue_items),
            "critical_or_high_priority_items": priority_counts.get("critical", 0) + priority_counts.get("high", 0),
            "manual_concept_choice_items": workflow_counts.get("needs_human_concept_choice", 0),
            "confirmation_items": workflow_counts.get("needs_confirmation", 0),
            "enrichment_or_blocked_items": workflow_counts.get("needs_alias_or_metadata_enrichment", 0)
            + workflow_counts.get("blocked_from_xbrl", 0),
        },
        "recommended_next_feature": recommend_next_feature(queue_report),
        "limitations": [
            "No mapping is final in #14B.",
            "No XBRL can be generated from #14B reports.",
            "Human reviewer decisions are modeled only as a future workflow.",
            "DB/API/UI implementation is not included.",
        ],
    }


def recommend_next_feature(queue_report: Mapping[str, Any]) -> str:
    workflow = Counter(queue_report.get("workflow_status_distribution") or {})
    total = int(queue_report.get("review_queue_count") or 0)
    ambiguous = workflow.get("needs_human_concept_choice", 0)
    enrichment = workflow.get("needs_alias_or_metadata_enrichment", 0)
    blocked = workflow.get("blocked_from_xbrl", 0)
    if total and ambiguous + enrichment + blocked >= total * 0.45:
        return "Feature #14C - Report-based reviewed mapping decision simulator, no DB mutation."
    if total and workflow.get("ready_for_review_approval", 0) >= total * 0.5:
        return "Feature #14C - Manual mapping review UI/API planning if review workload is high."
    return "Feature #14C - Concept metadata enrichment v2 if alias/metadata gaps still dominate."


def build_manual_mapping_review_reports(
    *,
    mapping_report: Mapping[str, Any],
    confidence_report: Mapping[str, Any],
    gap_report: Mapping[str, Any],
    run_id: str | None = "azure_di_manual_mapping_review_14b",
    input_paths: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    inputs = dict(input_paths or {})
    queue = build_review_queue(mapping_report, run_id=run_id, input_paths=inputs)
    policy = build_policy_report(run_id=run_id, input_paths=inputs)
    contract = build_handoff_contract_report(run_id=run_id, input_paths=inputs)
    summary = build_summary_report(
        queue_report=queue,
        mapping_report=mapping_report,
        confidence_report=confidence_report,
        gap_report=gap_report,
        run_id=run_id,
        input_paths=inputs,
    )
    return queue, policy, contract, summary


def render_queue_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Manual Mapping Review Queue - Feature #14B",
        "",
        "## Summary",
        "",
        f"- Review queue items: {report.get('review_queue_count', 0)}",
        f"- Workflow statuses: {report.get('workflow_status_distribution', {})}",
        f"- Priorities: {report.get('priority_distribution', {})}",
        f"- Database mutated: {report.get('run_metadata', {}).get('database_mutated')}",
        f"- Final mapping approved: {report.get('run_metadata', {}).get('final_mapping_approved')}",
        "",
        "## Queue Preview",
        "",
    ]
    for item in (report.get("queue_items") or [])[:25]:
        lines.append(
            f"- `{item.get('review_mapping_item_id')}` {item.get('priority')} "
            f"{item.get('workflow_status')} - {item.get('label')}"
        )
    if not report.get("queue_items"):
        lines.append("- None")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def render_policy_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Mapping Review Policy - Feature #14B",
        "",
        "## Workflow Statuses",
        "",
    ]
    for key, value in (report.get("workflow_status_definitions") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Priorities", ""])
    for key, value in (report.get("priority_definitions") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Required Evidence For Approval", ""])
    lines.extend(f"- {item}" for item in report.get("required_evidence_for_approval", []))
    lines.extend(["", "## Non-Goals", ""])
    lines.extend(f"- {item}" for item in report.get("non_goals", []))
    lines.append("")
    return "\n".join(lines)


def render_contract_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Mapping Review Handoff Contract - Feature #14B",
        "",
        "## Summary",
        "",
        f"- Contract status: {report.get('contract_status')}",
        f"- Reviewed mapping records produced: {len(report.get('empty_reviewed_mapping_records', []))}",
        "",
        "## Reviewed Mapping Fields",
        "",
    ]
    for key, value in (report.get("reviewed_mapping_schema") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Eligibility Rules", ""])
    lines.extend(f"- {item}" for item in report.get("eligibility_rules", []))
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Mapping Review Summary - Feature #14B",
        "",
        "## Summary",
        "",
        f"- Total mapping records: {report.get('total_mapping_records', 0)}",
        f"- Review queue items: {report.get('review_queue_count', 0)}",
        f"- Ready for review approval: {report.get('ready_for_review_approval_count', 0)}",
        f"- Needs human concept choice: {report.get('needs_human_concept_choice_count', 0)}",
        f"- Needs confirmation: {report.get('needs_confirmation_count', 0)}",
        f"- Needs alias/metadata enrichment: {report.get('needs_alias_or_metadata_enrichment_count', 0)}",
        f"- Blocked from XBRL: {report.get('blocked_from_xbrl_count', 0)}",
        f"- Context only: {report.get('context_only_count', 0)}",
        f"- Recommended next feature: {report.get('recommended_next_feature')}",
        "",
        "## Review Workload",
        "",
    ]
    for key, value in (report.get("estimated_review_workload") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Top Ambiguous Labels", ""])
    ambiguous = report.get("top_ambiguous_labels") or []
    lines.extend(f"- `{row.get('mapping_input_id')}` {row.get('label')}" for row in ambiguous[:15]) if ambiguous else lines.append("- None")
    lines.extend(["", "## Top No-Safe Labels", ""])
    no_safe = report.get("top_no_safe_labels") or []
    lines.extend(f"- `{row.get('mapping_input_id')}` {row.get('label')}" for row in no_safe[:15]) if no_safe else lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def run_manual_mapping_review(
    *,
    mapping_report_path: str | Path = DEFAULT_MAPPING_REPORT,
    confidence_report_path: str | Path = DEFAULT_CONFIDENCE_REPORT,
    gap_report_path: str | Path = DEFAULT_GAP_REPORT,
    run_id: str | None = "azure_di_manual_mapping_review_14b",
    output_prefix: str | Path | None = None,
) -> dict[str, Any]:
    mapping_path = Path(mapping_report_path)
    confidence_path = Path(confidence_report_path)
    gap_path = Path(gap_report_path)
    paths = output_paths_from_prefix(output_prefix)
    input_paths = {
        "mapping_report": str(mapping_path),
        "confidence_report": str(confidence_path),
        "gap_report": str(gap_path),
    }
    queue, policy, contract, summary = build_manual_mapping_review_reports(
        mapping_report=_load_json(mapping_path),
        confidence_report=_load_json(confidence_path),
        gap_report=_load_json(gap_path),
        run_id=run_id,
        input_paths=input_paths,
    )
    for report, path in [
        (queue, paths.queue_json),
        (policy, paths.policy_json),
        (contract, paths.contract_json),
        (summary, paths.summary_json),
    ]:
        metadata = dict(report.get("run_metadata") or {})
        metadata["output_path"] = str(path)
        report["run_metadata"] = metadata

    _write_json(paths.queue_json, queue)
    _write_text(paths.queue_md, render_queue_markdown(queue))
    _write_json(paths.policy_json, policy)
    _write_text(paths.policy_md, render_policy_markdown(policy))
    _write_json(paths.contract_json, contract)
    _write_text(paths.contract_md, render_contract_markdown(contract))
    _write_json(paths.summary_json, summary)
    _write_text(paths.summary_md, render_summary_markdown(summary))

    return {
        "paths": paths,
        "queue_report": queue,
        "policy_report": policy,
        "contract_report": contract,
        "summary_report": summary,
    }

