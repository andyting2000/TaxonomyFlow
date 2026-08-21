"""Read-only mapping handoff contract builder for Extraction v2 reports."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping

from services.extraction_v2_quality_analyzer import clean_text, parse_amount


ALLOWED_GATE_STATUSES = {"auto_mappable_candidate", "suggest_mapping_only"}
EXCLUDED_GATE_STATUSES = {
    "manual_review_required",
    "blocked_from_mapping",
    "reference_only_or_context",
}
NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
BLOCKING_RESOLUTION_ACTIONS = {
    "suppress_exact_duplicate",
    "downgrade_to_metadata",
    "downgrade_to_heading",
    "mark_not_ready",
    "mark_conflict_review_required",
}
CONFLICT_PREFIX = "conflict-"
MIN_TEXT_BLOCK_LENGTH = 20


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def no_side_effect_metadata() -> dict[str, Any]:
    return {
        "feature": "13V",
        "generated_at": utc_now_iso(),
        "read_only": True,
        "database_mutated": False,
        "db_schema_changed": False,
        "migration_created": False,
        "api_routes_implemented": False,
        "frontend_code_modified": False,
        "production_behavior_changed": False,
        "taxonomy_mapping_performed": False,
        "semantic_matcher_called": False,
        "xbrl_generated": False,
        "arelle_validation_run": False,
        "live_huggingface_calls_made": False,
        "live_openai_calls_made": False,
        "benchmark_rerun": False,
        "reference_xml_sent_to_model": False,
    }


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _candidate_id(record: Mapping[str, Any]) -> str:
    return str(
        record.get("candidate_id")
        or record.get("original_candidate_id")
        or record.get("source_candidate_id")
        or ""
    )


def _cleaned_candidate_map(cleaned_report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    by_id: dict[str, Mapping[str, Any]] = {}
    for case in _as_list(cleaned_report.get("case_reports")):
        for candidate in _as_list(case.get("candidates")):
            cid = _candidate_id(candidate)
            if cid:
                by_id[cid] = candidate
    return by_id


def _audit_map(cleaned_report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    entries = (cleaned_report.get("duplicate_resolution") or {}).get("candidate_audit_trail") or []
    return {
        str(entry.get("original_candidate_id")): entry
        for entry in entries
        if entry.get("original_candidate_id")
    }


def _queue_maps(manual_review_queue: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    by_candidate: dict[str, Mapping[str, Any]] = {}
    conflict_by_candidate: dict[str, Mapping[str, Any]] = {}
    for item in _as_list(manual_review_queue.get("manual_review_queue")):
        cid = _candidate_id(item)
        if cid:
            by_candidate[cid] = item
    for group in _as_list(manual_review_queue.get("conflict_groups")):
        for option in _as_list(group.get("candidate_options")):
            cid = _candidate_id(option)
            if cid:
                conflict_by_candidate[cid] = group
        for cid in _as_list(group.get("candidate_ids")):
            if cid:
                conflict_by_candidate[str(cid)] = group
    return by_candidate, conflict_by_candidate


def _expected_counts(mapping_gate_report: Mapping[str, Any]) -> dict[str, int]:
    gate_counts = mapping_gate_report.get("aggregate_gate_counts") or {}
    summary = mapping_gate_report.get("mapping_candidate_input_summary") or {}
    return {
        "total_original_candidates": _as_int(mapping_gate_report.get("total_original_candidates")),
        "total_cleaned_candidates": _as_int(mapping_gate_report.get("total_cleaned_candidates")),
        "auto_mappable_candidate": _as_int(gate_counts.get("auto_mappable_candidate")),
        "suggest_mapping_only": _as_int(gate_counts.get("suggest_mapping_only")),
        "manual_review_required": _as_int(gate_counts.get("manual_review_required")),
        "blocked_from_mapping": _as_int(gate_counts.get("blocked_from_mapping")),
        "reference_only_or_context": _as_int(gate_counts.get("reference_only_or_context")),
        "expected_allowed": _as_int(summary.get("allowed_into_13u_count")),
        "expected_requires_confirmation": _as_int(summary.get("requires_confirmation_count")),
        "expected_excluded": _as_int(summary.get("blocked_from_13u_count")),
    }


def _resolution_action(record: Mapping[str, Any], audit_entry: Mapping[str, Any] | None) -> str:
    return str(
        record.get("resolution_action")
        or (audit_entry or {}).get("action")
        or ""
    )


def _duplicate_group_ids(record: Mapping[str, Any], audit_entry: Mapping[str, Any] | None) -> list[str]:
    values: list[str] = []
    for source in (record, audit_entry or {}):
        for item in _as_list(source.get("duplicate_group_ids")):
            text = str(item)
            if text and text not in values:
                values.append(text)
    return values


def _has_unresolved_conflict(
    record: Mapping[str, Any],
    audit_entry: Mapping[str, Any] | None,
    conflict_group: Mapping[str, Any] | None,
) -> bool:
    if conflict_group:
        return bool(conflict_group.get("blocks_auto_mapping", True))
    if any(group_id.startswith(CONFLICT_PREFIX) for group_id in _duplicate_group_ids(record, audit_entry)):
        return True
    if "duplicate_conflicting_values" in _as_list(record.get("review_reasons")):
        return True
    return False


def _usable_label_or_text(record: Mapping[str, Any]) -> bool:
    return bool(clean_text(record.get("label")) or clean_text(record.get("text") or record.get("text_preview")))


def _numeric_valid(record: Mapping[str, Any]) -> bool:
    if str(record.get("row_type") or "") not in NUMERIC_ROW_TYPES:
        return True
    return parse_amount(record.get("value")) is not None or parse_amount(record.get("previous_value")) is not None


def _text_valid(record: Mapping[str, Any]) -> bool:
    if str(record.get("row_type") or "") != "text_block":
        return True
    text = clean_text(record.get("text") or record.get("text_preview") or record.get("source_snippet"))
    return len(text) >= MIN_TEXT_BLOCK_LENGTH


def _has_provenance(record: Mapping[str, Any]) -> bool:
    provenance = record.get("source_provenance") or {}
    return bool(record.get("source") or provenance.get("extraction_method")) and bool(
        record.get("page_number") or provenance.get("page_number")
    )


def exclusion_reasons(
    record: Mapping[str, Any],
    *,
    audit_entry: Mapping[str, Any] | None = None,
    queue_item: Mapping[str, Any] | None = None,
    conflict_group: Mapping[str, Any] | None = None,
) -> list[str]:
    reasons: list[str] = []
    gate_status = str(record.get("gate_status") or "")
    action = _resolution_action(record, audit_entry)
    if gate_status in EXCLUDED_GATE_STATUSES:
        reasons.append(f"excluded_gate_status:{gate_status}")
    elif gate_status not in ALLOWED_GATE_STATUSES:
        reasons.append("excluded_gate_status:unknown")
    if action in BLOCKING_RESOLUTION_ACTIONS:
        reasons.append(f"blocking_resolution_action:{action}")
    if not record.get("retained_in_cleaned_rows", True):
        reasons.append("suppressed_candidate")
    if _has_unresolved_conflict(record, audit_entry, conflict_group):
        reasons.append("unresolved_conflict")
    if queue_item and str(queue_item.get("gate_status") or "") == "manual_review_required":
        reasons.append("manual_review_queue_item_unresolved")
    if not _usable_label_or_text(record):
        reasons.append("missing_usable_label_or_text")
    if not _numeric_valid(record):
        reasons.append("non_numeric_numeric_value")
    if not _text_valid(record):
        reasons.append("short_text_block")
    if not _has_provenance(record):
        reasons.append("insufficient_source_provenance")
    return reasons


def _build_handoff_item(
    record: Mapping[str, Any],
    index: int,
    *,
    cleaned_candidate: Mapping[str, Any] | None,
    audit_entry: Mapping[str, Any] | None,
    queue_item: Mapping[str, Any] | None,
) -> dict[str, Any]:
    candidate_id = _candidate_id(record)
    gate_status = str(record.get("gate_status") or "")
    requires_confirmation = gate_status == "suggest_mapping_only"
    source_provenance = deepcopy(record.get("source_provenance") or {})
    source_provenance.setdefault("gate_report_candidate_id", candidate_id)
    if cleaned_candidate:
        source_provenance.setdefault("cleaned_candidate_report_candidate_id", _candidate_id(cleaned_candidate))
    return {
        "mapping_input_id": f"13V-MAP-{index:04d}",
        "source_candidate_id": candidate_id,
        "original_candidate_id": record.get("original_candidate_id") or candidate_id,
        "cleaned_candidate_id": (cleaned_candidate or {}).get("original_candidate_id") or candidate_id,
        "case_id": record.get("case_id"),
        "page_number": record.get("page_number"),
        "row_type": record.get("row_type"),
        "label": record.get("label"),
        "value": record.get("value"),
        "previous_value": record.get("previous_value"),
        "text": record.get("text") or record.get("text_preview"),
        "statement_section": record.get("statement_section"),
        "gate_status": gate_status,
        "requires_confirmation": requires_confirmation,
        "readiness_level": record.get("readiness"),
        "readiness_score": None,
        "confidence": source_provenance.get("confidence"),
        "source_method": record.get("source") or source_provenance.get("extraction_method"),
        "source_provenance": source_provenance,
        "source_snippet": record.get("source_snippet"),
        "warning_flags": list(_as_list(record.get("warning_flags"))),
        "review_reasons": list(_as_list(record.get("review_reasons"))),
        "duplicate_group_id": (_duplicate_group_ids(record, audit_entry) or [None])[0],
        "duplicate_group_ids": _duplicate_group_ids(record, audit_entry),
        "conflict_group_id": None,
        "conflict_status": "none",
        "mapping_allowed": True,
        "mapping_blocked_reason": None,
        "manual_review_queue_id": (queue_item or {}).get("queue_id"),
        "audit_trail": {
            "source": "13V_report_based_handoff",
            "original_candidate_id": record.get("original_candidate_id") or candidate_id,
            "cleaned_candidate_present": bool(cleaned_candidate),
            "gate_status_source": "reports/extraction_v2_mapping_candidate_gate_13t.json",
            "cleaned_candidate_source": "reports/extraction_v2_cleaned_candidates_13s.json",
            "manual_review_queue_source": "reports/extraction_v2_manual_review_queue_13t.json",
            "resolution_action": _resolution_action(record, audit_entry) or None,
        },
    }


def _build_exclusion(
    record: Mapping[str, Any],
    reasons: list[str],
    *,
    audit_entry: Mapping[str, Any] | None,
    queue_item: Mapping[str, Any] | None,
    conflict_group: Mapping[str, Any] | None,
) -> dict[str, Any]:
    category = "excluded_because_validation_failed"
    gate_status = str(record.get("gate_status") or "")
    if gate_status == "manual_review_required" or "manual_review_queue_item_unresolved" in reasons:
        category = "excluded_because_requires_manual_review"
    elif gate_status == "reference_only_or_context":
        category = "excluded_because_reference_context_only"
    elif any(reason.startswith("blocking_resolution_action:") or reason == "suppressed_candidate" for reason in reasons):
        category = "excluded_because_suppressed_or_downgraded"
    elif gate_status == "blocked_from_mapping" or "unresolved_conflict" in reasons:
        category = "excluded_because_unsafe"
    return {
        "source_candidate_id": _candidate_id(record),
        "original_candidate_id": record.get("original_candidate_id") or _candidate_id(record),
        "case_id": record.get("case_id"),
        "page_number": record.get("page_number"),
        "row_type": record.get("row_type"),
        "label": record.get("label"),
        "value": record.get("value"),
        "previous_value": record.get("previous_value"),
        "gate_status": gate_status,
        "reason_codes": reasons,
        "exclusion_category": category,
        "priority": (queue_item or {}).get("priority"),
        "manual_review_queue_id": (queue_item or {}).get("queue_id"),
        "duplicate_group_ids": _duplicate_group_ids(record, audit_entry),
        "conflict_group_id": (conflict_group or {}).get("conflict_group_id"),
        "source_method": record.get("source"),
        "traceability": {
            "has_gate_record": True,
            "has_cleaned_audit_entry": bool(audit_entry),
            "has_manual_review_queue_item": bool(queue_item),
            "has_conflict_group": bool(conflict_group),
        },
    }


def build_mapping_handoff_reports(
    *,
    cleaned_report: Mapping[str, Any],
    mapping_gate_report: Mapping[str, Any],
    manual_review_queue: Mapping[str, Any],
    data_contract: Mapping[str, Any] | None = None,
    ui_api_plan: Mapping[str, Any] | None = None,
    input_paths: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    cleaned_by_id = _cleaned_candidate_map(cleaned_report)
    audit_by_id = _audit_map(cleaned_report)
    queue_by_id, conflict_by_id = _queue_maps(manual_review_queue)
    expected = _expected_counts(mapping_gate_report)

    handoff_items: list[dict[str, Any]] = []
    exclusion_ledger: list[dict[str, Any]] = []
    records = _as_list(mapping_gate_report.get("candidate_gate_records"))
    for record in records:
        cid = _candidate_id(record)
        audit_entry = audit_by_id.get(cid)
        queue_item = queue_by_id.get(cid)
        conflict_group = conflict_by_id.get(cid)
        reasons = exclusion_reasons(
            record,
            audit_entry=audit_entry,
            queue_item=queue_item,
            conflict_group=conflict_group,
        )
        if str(record.get("gate_status") or "") in ALLOWED_GATE_STATUSES and not reasons:
            handoff_items.append(
                _build_handoff_item(
                    record,
                    len(handoff_items) + 1,
                    cleaned_candidate=cleaned_by_id.get(cid),
                    audit_entry=audit_entry,
                    queue_item=queue_item,
                )
            )
        else:
            exclusion_ledger.append(
                _build_exclusion(
                    record,
                    reasons,
                    audit_entry=audit_entry,
                    queue_item=queue_item,
                    conflict_group=conflict_group,
                )
            )

    candidates_report = _build_candidates_report(
        handoff_items,
        exclusion_ledger,
        cleaned_report=cleaned_report,
        mapping_gate_report=mapping_gate_report,
        expected=expected,
        input_paths=input_paths,
    )
    validation_report = validate_mapping_handoff(
        candidates_report,
        mapping_gate_report=mapping_gate_report,
        expected=expected,
    )
    contract_report = build_contract_report(
        candidates_report,
        validation_report,
        data_contract=data_contract or {},
        ui_api_plan=ui_api_plan or {},
        input_paths=input_paths,
    )
    return candidates_report, validation_report, contract_report


def _build_candidates_report(
    handoff_items: list[dict[str, Any]],
    exclusion_ledger: list[dict[str, Any]],
    *,
    cleaned_report: Mapping[str, Any],
    mapping_gate_report: Mapping[str, Any],
    expected: Mapping[str, int],
    input_paths: Mapping[str, Any] | None,
) -> dict[str, Any]:
    per_case = Counter(str(item.get("case_id")) for item in handoff_items)
    per_row_type = Counter(str(item.get("row_type")) for item in handoff_items)
    per_source = Counter(str(item.get("source_method")) for item in handoff_items)
    gate_counts = Counter(str(item.get("gate_status")) for item in handoff_items)
    reason_counts = Counter(reason for item in exclusion_ledger for reason in item.get("reason_codes", []))
    category_counts = Counter(str(item.get("exclusion_category")) for item in exclusion_ledger)
    metadata = no_side_effect_metadata()
    return {
        "run_metadata": {
            **metadata,
            "report_type": "mapping_handoff_candidates",
            "script": "scripts/build_extraction_v2_mapping_handoff.py",
        },
        "input_reports": dict(input_paths or {}),
        "source_feature_chain": ["13Q", "13R", "13S", "13T", "13U", "13V"],
        "total_cleaned_candidates": _as_int(
            (cleaned_report.get("duplicate_resolution") or {}).get("cleaned_candidate_count"),
            _as_int(mapping_gate_report.get("total_cleaned_candidates")),
        ),
        "total_original_candidates": _as_int(mapping_gate_report.get("total_original_candidates")),
        "total_handoff_candidates": len(handoff_items),
        "auto_mappable_count": gate_counts.get("auto_mappable_candidate", 0),
        "suggest_mapping_only_count": gate_counts.get("suggest_mapping_only", 0),
        "requires_confirmation_count": sum(1 for item in handoff_items if item.get("requires_confirmation")),
        "excluded_count": len(exclusion_ledger),
        "expected_13t_counts": dict(expected),
        "per_case_handoff_count": dict(sorted(per_case.items())),
        "per_row_type_handoff_count": dict(sorted(per_row_type.items())),
        "per_source_handoff_count": dict(sorted(per_source.items())),
        "exclusion_summary": {
            "by_reason": dict(reason_counts.most_common()),
            "by_category": dict(category_counts.most_common()),
            "by_gate_status": dict(Counter(str(item.get("gate_status")) for item in exclusion_ledger).most_common()),
            "by_case_id": dict(Counter(str(item.get("case_id")) for item in exclusion_ledger).most_common()),
            "by_row_type": dict(Counter(str(item.get("row_type")) for item in exclusion_ledger).most_common()),
            "by_priority": dict(Counter(str(item.get("priority")) for item in exclusion_ledger if item.get("priority")).most_common()),
        },
        "handoff_items": handoff_items,
        "exclusion_ledger": exclusion_ledger,
        "non_goals": [
            "No taxonomy mapping.",
            "No semantic matcher call.",
            "No generated XBRL.",
            "No Arelle validation.",
            "No DB mutation.",
            "No API or UI implementation.",
            "No live model calls.",
        ],
    }


def validate_mapping_handoff(
    candidates_report: Mapping[str, Any],
    *,
    mapping_gate_report: Mapping[str, Any],
    expected: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    expected = dict(expected or _expected_counts(mapping_gate_report))
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    handoff_items = _as_list(candidates_report.get("handoff_items"))
    excluded = _as_list(candidates_report.get("exclusion_ledger"))
    for item in handoff_items:
        mid = item.get("mapping_input_id")
        gate = item.get("gate_status")
        if gate not in ALLOWED_GATE_STATUSES:
            errors.append({"mapping_input_id": mid, "code": "blocked_or_unknown_gate_included", "gate_status": gate})
        if gate == "suggest_mapping_only" and item.get("requires_confirmation") is not True:
            errors.append({"mapping_input_id": mid, "code": "suggest_mapping_only_missing_confirmation"})
        if gate == "auto_mappable_candidate" and item.get("requires_confirmation") is not False:
            errors.append({"mapping_input_id": mid, "code": "auto_mappable_requires_confirmation_unexpected"})
        if item.get("conflict_status") not in {"none", None}:
            errors.append({"mapping_input_id": mid, "code": "unresolved_conflict_included"})
        if not item.get("source_candidate_id") or not item.get("case_id") or not item.get("row_type"):
            errors.append({"mapping_input_id": mid, "code": "missing_required_identity"})
        if not clean_text(item.get("label")) and not clean_text(item.get("text")):
            errors.append({"mapping_input_id": mid, "code": "missing_label_or_text"})
        if not item.get("statement_section"):
            warnings.append({"mapping_input_id": mid, "code": "missing_statement_section"})
        if not item.get("source_provenance"):
            errors.append({"mapping_input_id": mid, "code": "missing_source_provenance"})
        if item.get("row_type") in NUMERIC_ROW_TYPES and parse_amount(item.get("value")) is None and parse_amount(item.get("previous_value")) is None:
            errors.append({"mapping_input_id": mid, "code": "non_numeric_numeric_value"})
        if item.get("row_type") == "text_block" and len(clean_text(item.get("text"))) < MIN_TEXT_BLOCK_LENGTH:
            errors.append({"mapping_input_id": mid, "code": "short_text_block"})

    included_gate_counts = Counter(str(item.get("gate_status")) for item in handoff_items)
    excluded_gate_counts = Counter(str(item.get("gate_status")) for item in excluded)
    expected_allowed = expected.get("expected_allowed", 0)
    total_included = len(handoff_items)
    if expected_allowed and total_included != expected_allowed:
        warnings.append(
            {
                "code": "included_count_differs_from_13t_allowed",
                "expected_allowed": expected_allowed,
                "actual_included": total_included,
                "difference": total_included - expected_allowed,
            }
        )
    if expected.get("expected_requires_confirmation", 0) != sum(1 for item in handoff_items if item.get("requires_confirmation")):
        warnings.append(
            {
                "code": "requires_confirmation_count_differs_from_13t",
                "expected": expected.get("expected_requires_confirmation", 0),
                "actual": sum(1 for item in handoff_items if item.get("requires_confirmation")),
            }
        )

    traceable = sum(1 for item in handoff_items if item.get("source_candidate_id") and item.get("source_provenance"))
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "report_type": "mapping_handoff_validation",
            "script": "scripts/build_extraction_v2_mapping_handoff.py",
        },
        "validation_passed": not errors,
        "fatal_contract_violation": bool(errors),
        "validation_errors": errors,
        "validation_warnings": warnings,
        "reconciliation": {
            "expected_13t_counts": expected,
            "included_count": total_included,
            "excluded_count": len(excluded),
            "included_gate_counts": dict(included_gate_counts),
            "excluded_gate_counts": dict(excluded_gate_counts),
            "expected_allowed_count": expected_allowed,
            "included_matches_expected_allowed": (not expected_allowed) or total_included == expected_allowed,
            "excluded_reconciles_to_original": total_included + len(excluded) == expected.get("total_original_candidates", 0),
        },
        "traceability_coverage": {
            "handoff_items": total_included,
            "items_with_source_candidate_id_and_provenance": traceable,
            "coverage_ratio": 1.0 if not total_included else round(traceable / total_included, 4),
        },
        "confirmation_rule_checks": {
            "suggest_mapping_only_requires_confirmation": all(
                item.get("requires_confirmation") is True
                for item in handoff_items
                if item.get("gate_status") == "suggest_mapping_only"
            ),
            "auto_mappable_requires_confirmation_false": all(
                item.get("requires_confirmation") is False
                for item in handoff_items
                if item.get("gate_status") == "auto_mappable_candidate"
            ),
        },
        "conflict_exclusion_checks": {
            "unresolved_conflict_items_included": [
                item.get("mapping_input_id")
                for item in handoff_items
                if item.get("conflict_status") not in {"none", None}
            ],
            "excluded_unresolved_conflict_count": sum(
                1 for item in excluded if "unresolved_conflict" in item.get("reason_codes", [])
            ),
        },
        "numeric_text_validity_checks": {
            "numeric_items": sum(1 for item in handoff_items if item.get("row_type") in NUMERIC_ROW_TYPES),
            "text_block_items": sum(1 for item in handoff_items if item.get("row_type") == "text_block"),
        },
    }


def build_contract_report(
    candidates_report: Mapping[str, Any],
    validation_report: Mapping[str, Any],
    *,
    data_contract: Mapping[str, Any],
    ui_api_plan: Mapping[str, Any],
    input_paths: Mapping[str, Any] | None,
) -> dict[str, Any]:
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "report_type": "mapping_handoff_contract",
            "script": "scripts/build_extraction_v2_mapping_handoff.py",
        },
        "input_reports": dict(input_paths or {}),
        "handoff_package_metadata": {
            "total_handoff_candidates": candidates_report.get("total_handoff_candidates"),
            "requires_confirmation_count": candidates_report.get("requires_confirmation_count"),
            "validation_passed": validation_report.get("validation_passed"),
        },
        "allowed_gate_statuses": sorted(ALLOWED_GATE_STATUSES),
        "excluded_gate_statuses": sorted(EXCLUDED_GATE_STATUSES),
        "confirmation_rules": {
            "auto_mappable_candidate": "requires_confirmation=false",
            "suggest_mapping_only": "requires_confirmation=true",
        },
        "conflict_rules": [
            "Unresolved conflict candidates must not enter handoff.",
            "Conflict group options are preserved in review reports, not auto-selected in handoff.",
            "Future reviewer decisions may create a new approved handoff item.",
        ],
        "handoff_item_schema": {
            "required_fields": [
                "mapping_input_id",
                "source_candidate_id",
                "case_id",
                "page_number",
                "row_type",
                "label or text",
                "statement_section or warning",
                "gate_status",
                "requires_confirmation",
                "source_provenance",
                "mapping_allowed",
                "audit_trail",
            ],
            "optional_fields": [
                "original_candidate_id",
                "cleaned_candidate_id",
                "value",
                "previous_value",
                "readiness_score",
                "readiness_level",
                "confidence",
                "source_snippet",
                "warning_flags",
                "review_reasons",
                "duplicate_group_id",
                "conflict_group_id",
                "manual_review_queue_id",
            ],
        },
        "examples": {
            "auto_mappable_candidate": {
                "mapping_input_id": "13V-MAP-0001",
                "gate_status": "auto_mappable_candidate",
                "requires_confirmation": False,
                "mapping_allowed": True,
            },
            "suggest_mapping_only": {
                "mapping_input_id": "13V-MAP-0002",
                "gate_status": "suggest_mapping_only",
                "requires_confirmation": True,
                "mapping_allowed": True,
            },
        },
        "validation_rules": [
            "No blocked, manual-review, reference/context, suppressed, downgraded, rejected, or unresolved conflict candidates may be included.",
            "Suggest-only items must have requires_confirmation=true.",
            "Auto-mappable items must have requires_confirmation=false.",
            "Every item must have stable identity, case_id, row_type, usable label or text, provenance, and audit trail.",
            "Numeric items must contain numeric-looking current or previous values.",
            "Text blocks must contain sufficient narrative text.",
        ],
        "required_provenance_fields": [
            "source_candidate_id",
            "original_candidate_id",
            "cleaned_candidate_id",
            "source_method",
            "source_provenance",
            "page_number",
            "audit_trail",
        ],
        "expected_downstream_13w_behavior": [
            "Consume only handoff_items from this package.",
            "Preserve requires_confirmation and warning_flags.",
            "Generate mapping candidates only; do not generate XBRL.",
            "Do not call semantic matcher for excluded candidates.",
            "Keep mapping suggestions traceable to mapping_input_id and source_candidate_id.",
        ],
        "prohibited_downstream_behavior": [
            "Do not treat this as final taxonomy mapping.",
            "Do not call semantic matcher for candidates outside the handoff package.",
            "Do not generate XBRL or run Arelle from this contract alone.",
            "Do not mutate DB from report-based handoff output.",
            "Do not auto-map suggest-only candidates without confirmation metadata.",
        ],
        "source_contract_references": {
            "data_contract_mapping_handoff_contract": data_contract.get("mapping_handoff_contract", {}),
            "ui_api_mapping_handoff_rules": ui_api_plan.get("mapping_handoff_rules", {}),
        },
        "non_goals": [
            "This is not taxonomy mapping.",
            "This is not semantic matching.",
            "This is not XBRL generation.",
            "This does not prove mapping accuracy.",
            "This is only the safe report-based input contract for #13W.",
        ],
        "recommended_next_feature": "Feature #13W - Mapping candidate generation v2 with conservative readiness gates.",
    }


def render_candidates_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Extraction V2 Mapping Handoff Candidates - Feature #13V",
        "",
        "## Summary",
        f"- Total cleaned candidates: {report.get('total_cleaned_candidates', 0)}",
        f"- Handoff candidates: {report.get('total_handoff_candidates', 0)}",
        f"- Auto mappable: {report.get('auto_mappable_count', 0)}",
        f"- Suggest mapping only: {report.get('suggest_mapping_only_count', 0)}",
        f"- Requires confirmation: {report.get('requires_confirmation_count', 0)}",
        f"- Excluded candidates: {report.get('excluded_count', 0)}",
        "",
        "## Per Case",
    ]
    lines.extend(f"- {case_id}: {count}" for case_id, count in report.get("per_case_handoff_count", {}).items())
    lines.extend(["", "## Exclusion Summary"])
    for reason, count in report.get("exclusion_summary", {}).get("by_reason", {}).items():
        lines.append(f"- {reason}: {count}")
    lines.extend(["", "## Non-Goals"])
    lines.extend(f"- {item}" for item in report.get("non_goals", []))
    return "\n".join(lines) + "\n"


def render_validation_markdown(report: Mapping[str, Any]) -> str:
    reconciliation = report.get("reconciliation", {})
    lines = [
        "# Extraction V2 Mapping Handoff Validation - Feature #13V",
        "",
        "## Validation Summary",
        f"- Validation passed: {report.get('validation_passed')}",
        f"- Fatal contract violation: {report.get('fatal_contract_violation')}",
        f"- Validation errors: {len(report.get('validation_errors', []))}",
        f"- Validation warnings: {len(report.get('validation_warnings', []))}",
        f"- Included count: {reconciliation.get('included_count', 0)}",
        f"- Excluded count: {reconciliation.get('excluded_count', 0)}",
        f"- Included matches #13T allowed count: {reconciliation.get('included_matches_expected_allowed')}",
        "",
        "## Traceability",
        f"- Coverage ratio: {report.get('traceability_coverage', {}).get('coverage_ratio', 0)}",
        "",
        "## Rule Checks",
        f"- Suggest-only confirmation rule: {report.get('confirmation_rule_checks', {}).get('suggest_mapping_only_requires_confirmation')}",
        f"- Auto-mappable confirmation rule: {report.get('confirmation_rule_checks', {}).get('auto_mappable_requires_confirmation_false')}",
    ]
    return "\n".join(lines) + "\n"


def render_contract_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Extraction V2 Mapping Handoff Contract - Feature #13V",
        "",
        "## Scope",
        "This is the safe report-based input contract for #13W. It is not taxonomy mapping, semantic matching, XBRL generation, or Arelle validation.",
        "",
        "## Allowed Gate Statuses",
    ]
    lines.extend(f"- `{status}`" for status in report.get("allowed_gate_statuses", []))
    lines.extend(["", "## Excluded Gate Statuses"])
    lines.extend(f"- `{status}`" for status in report.get("excluded_gate_statuses", []))
    lines.extend(["", "## Required Fields"])
    lines.extend(f"- `{field}`" for field in report.get("handoff_item_schema", {}).get("required_fields", []))
    lines.extend(["", "## Downstream #13W Responsibilities"])
    lines.extend(f"- {item}" for item in report.get("expected_downstream_13w_behavior", []))
    lines.extend(["", "## Prohibited Downstream Behavior"])
    lines.extend(f"- {item}" for item in report.get("prohibited_downstream_behavior", []))
    lines.extend(["", "## Recommended Next Feature", report.get("recommended_next_feature", "")])
    return "\n".join(lines) + "\n"
