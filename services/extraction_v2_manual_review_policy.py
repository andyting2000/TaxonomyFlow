"""Read-only manual-review policy and mapping gate reports for Extraction v2."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from services.extraction_v2_quality_analyzer import (
    NON_MAPPING_ROW_TYPES,
    NUMERIC_ROW_TYPES,
    clean_text,
    detect_candidate_issues,
    is_date_only_label,
    is_generic_period_label,
    is_heading_like_label,
    is_weak_label,
    is_year_only_label,
    normalize_label,
    parse_amount,
    readiness_for_candidate,
    source_bucket,
)


GATE_STATUSES = [
    "auto_mappable_candidate",
    "suggest_mapping_only",
    "manual_review_required",
    "blocked_from_mapping",
    "reference_only_or_context",
]

REASON_DEFINITIONS = {
    "duplicate_conflicting_values": "Same case/label has multiple value variants; no value can be chosen automatically.",
    "duplicate_same_label_value": "Same label/value appears more than once and should be reviewed for evidence/context.",
    "exact_duplicate_suppressed": "Candidate was suppressed as an exact duplicate in the #13S cleaned report.",
    "date_or_year_label": "Candidate label is a pure date, year, or generic period label.",
    "year_header_row": "Candidate appears to be a year/period header row rather than a fact.",
    "heading_like_numeric_fact": "Numeric row has a heading-like label and may need total/subtotal or section policy.",
    "weak_label": "Candidate label is missing, too short, generic, or otherwise weak.",
    "weak_text_block_label": "Text block has weak or missing label evidence.",
    "missing_statement_section": "Candidate has no statement_section.",
    "ambiguous_statement_section": "Candidate section is generic or questionable for mapping.",
    "non_numeric_numeric_value": "Numeric candidate value is not numeric.",
    "sign_uncertainty": "Negative or dash/zero values require sign/normalization policy.",
    "current_prior_uncertainty": "Current/prior values or year context are incomplete or uncertain.",
    "subtotal_total_uncertainty": "Total/subtotal meaning requires policy or confirmation.",
    "text_block_boundary_uncertainty": "Text block may be too short, too long, heading-only, or poorly bounded.",
    "section_mismatch": "Candidate row type appears inconsistent with its statement section.",
    "cleaned_downgraded_candidate": "Candidate was downgraded during #13S cleanup.",
    "suppressed_candidate": "Candidate is retained only in audit trail and must not enter automatic mapping.",
    "not_ready_candidate": "Candidate readiness is not_ready or otherwise unsafe for mapping.",
    "requires_manual_mapping_confirmation": "Mapping suggestions are allowed only with later human confirmation.",
}

REVIEWER_DECISION_OPTIONS = [
    "confirm_candidate_for_mapping",
    "correct_label",
    "correct_value",
    "correct_previous_value",
    "correct_row_type",
    "correct_section",
    "mark_as_metadata",
    "suppress_candidate",
    "split_text_block",
    "merge_text_block",
    "keep_for_context_only",
    "reject_candidate",
    "manual_taxonomy_mapping_required",
]

CONFLICT_DECISION_OPTIONS = [
    "choose_one_candidate",
    "keep_multiple_as_detail_rows",
    "mark_all_as_context_only",
    "reject_all",
    "require_aggregation_policy",
    "require_dimension_policy",
    "require_manual_taxonomy_mapping",
]

ISSUE_REASON_MAP = {
    "date_only_label": "date_or_year_label",
    "year_only_label": "date_or_year_label",
    "generic_period_label": "date_or_year_label",
    "year_header_row_extracted_as_fact": "year_header_row",
    "heading_like_numeric_fact": "heading_like_numeric_fact",
    "empty_label": "weak_label",
    "too_short_label": "weak_label",
    "enumeration_only_label": "weak_label",
    "amount_with_weak_label": "weak_label",
    "weak_text_block_label": "weak_text_block_label",
    "missing_statement_section": "missing_statement_section",
    "generic_statement_section": "ambiguous_statement_section",
    "non_numeric_value": "non_numeric_numeric_value",
    "date_or_year_value_as_amount": "non_numeric_numeric_value",
    "missing_year_context": "current_prior_uncertainty",
    "missing_previous_value": "current_prior_uncertainty",
    "previous_without_current": "current_prior_uncertainty",
    "date_or_year_previous_value": "current_prior_uncertainty",
    "non_numeric_previous_value": "current_prior_uncertainty",
    "parentheses_negative_value": "sign_uncertainty",
    "suspicious_negative_value": "sign_uncertainty",
    "dash_or_zero_value": "sign_uncertainty",
    "short_text_block": "text_block_boundary_uncertainty",
    "long_text_block": "text_block_boundary_uncertainty",
    "text_block_heading_only": "text_block_boundary_uncertainty",
    "numeric_under_narrative_section": "section_mismatch",
    "text_under_numeric_section": "section_mismatch",
    "duplicate_label_conflicting_values": "duplicate_conflicting_values",
    "duplicate_label_value_same_case": "duplicate_same_label_value",
    "exact_duplicate_same_page": "duplicate_same_label_value",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _issue_codes(issues: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("code")) for item in issues}


def _is_period_label(candidate: dict[str, Any]) -> bool:
    label = candidate.get("label")
    return is_date_only_label(label) or is_year_only_label(label) or is_generic_period_label(label)


def _text_preview(candidate: dict[str, Any], limit: int = 240) -> str:
    text = clean_text(candidate.get("text") or candidate.get("source_snippet") or candidate.get("value"))
    return text[:limit]


def _candidate_identity(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": candidate.get("case_id"),
        "page_number": candidate.get("page_number"),
        "candidate_id": candidate.get("original_candidate_id"),
        "label": candidate.get("label"),
        "value": candidate.get("value"),
        "previous_value": candidate.get("previous_value"),
        "text_preview": _text_preview(candidate),
        "statement_section": candidate.get("statement_section"),
        "row_type": candidate.get("row_type"),
        "source": candidate.get("extraction_method"),
        "source_snippet": clean_text(candidate.get("source_snippet"))[:500],
    }


def _group_maps(duplicate_report: dict[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_group: dict[str, dict[str, Any]] = {}
    for group in duplicate_report.get("duplicate_groups") or []:
        group_id = str(group.get("group_id") or "")
        if not group_id:
            continue
        by_group[group_id] = group
        for candidate_id in group.get("candidate_ids") or []:
            by_candidate[str(candidate_id)].append(group)
    return by_candidate, by_group


def _audit_entries(cleaned_report: dict[str, Any]) -> list[dict[str, Any]]:
    entries = (cleaned_report.get("duplicate_resolution") or {}).get("candidate_audit_trail") or []
    if entries:
        return deepcopy(entries)

    fallback: list[dict[str, Any]] = []
    index = 0
    for case_report in cleaned_report.get("case_reports") or []:
        case_id = str(case_report.get("case_id") or "")
        for case_index, candidate in enumerate(case_report.get("candidates") or []):
            clean_candidate = deepcopy(candidate)
            clean_candidate.setdefault("case_id", case_id)
            candidate_id = clean_candidate.get("original_candidate_id") or f"{case_id}:candidate:{case_index}:{index}"
            clean_candidate["original_candidate_id"] = candidate_id
            issues = detect_candidate_issues(clean_candidate)
            fallback.append(
                {
                    "original_candidate_id": candidate_id,
                    "original_global_index": index,
                    "original_case_index": case_index,
                    "case_id": case_id,
                    "page_number": clean_candidate.get("page_number"),
                    "duplicate_group_ids": clean_candidate.get("duplicate_group_ids") or [],
                    "original_row_type": clean_candidate.get("row_type"),
                    "proposed_row_type": clean_candidate.get("row_type"),
                    "original_readiness": readiness_for_candidate(clean_candidate, issues),
                    "proposed_readiness": readiness_for_candidate(clean_candidate, issues),
                    "action": clean_candidate.get("resolution_action") or "keep",
                    "action_reasons": [],
                    "retained_in_cleaned_rows": True,
                    "original_candidate": deepcopy(clean_candidate),
                    "cleaned_candidate": clean_candidate,
                }
            )
            index += 1
    return fallback


def _reason_codes_for_candidate(
    *,
    candidate: dict[str, Any],
    entry: dict[str, Any],
    issues: list[dict[str, Any]],
    groups: list[dict[str, Any]],
) -> list[str]:
    reasons: list[str] = []
    action = str(entry.get("action") or "")
    row_type = str(candidate.get("row_type") or "unknown")
    group_types = {str(group.get("group_type")) for group in groups}
    warnings = {str(item) for item in candidate.get("warnings") or []}

    if action == "suppress_exact_duplicate" or not entry.get("retained_in_cleaned_rows", True):
        _append_unique(reasons, "exact_duplicate_suppressed")
        _append_unique(reasons, "suppressed_candidate")
    if action in {"downgrade_to_metadata", "downgrade_to_heading"}:
        _append_unique(reasons, "cleaned_downgraded_candidate")
    if action == "mark_not_ready":
        _append_unique(reasons, "not_ready_candidate")
    if action == "manual_review_required":
        _append_unique(reasons, "requires_manual_mapping_confirmation")
    if action == "mark_conflict_review_required" or "same_label_conflicting_values" in group_types:
        _append_unique(reasons, "duplicate_conflicting_values")
    if "same_label_value_duplicate" in group_types:
        _append_unique(reasons, "duplicate_same_label_value")
    if "exact_duplicate" in group_types and action != "suppress_exact_duplicate":
        _append_unique(reasons, "duplicate_same_label_value")

    if _is_period_label(candidate):
        _append_unique(reasons, "date_or_year_label")
    if _is_period_label(candidate) and clean_text(candidate.get("value")):
        _append_unique(reasons, "year_header_row")
    if row_type in NUMERIC_ROW_TYPES and is_heading_like_label(candidate.get("label")):
        _append_unique(reasons, "heading_like_numeric_fact")
    if row_type in NUMERIC_ROW_TYPES and str(candidate.get("row_type")) == "subtotal_or_total":
        _append_unique(reasons, "subtotal_total_uncertainty")
    if is_weak_label(candidate.get("label")) and row_type != "text_block":
        _append_unique(reasons, "weak_label")

    for issue in issues:
        reason = ISSUE_REASON_MAP.get(str(issue.get("code")))
        if reason:
            _append_unique(reasons, reason)
    if "conflict_review_required" in warnings:
        _append_unique(reasons, "duplicate_conflicting_values")
    if "heading_like_numeric_fact_requires_review" in warnings:
        _append_unique(reasons, "heading_like_numeric_fact")
    if "downgraded_period_label_not_fact" in warnings:
        _append_unique(reasons, "cleaned_downgraded_candidate")
    return reasons


def classify_gate_status(
    *,
    candidate: dict[str, Any],
    entry: dict[str, Any],
    readiness: str,
    reasons: list[str],
    issues: list[dict[str, Any]],
) -> str:
    row_type = str(candidate.get("row_type") or "unknown")
    issue_codes = _issue_codes(issues)

    if "suppressed_candidate" in reasons or "exact_duplicate_suppressed" in reasons:
        return "blocked_from_mapping"
    if row_type in NON_MAPPING_ROW_TYPES:
        return "reference_only_or_context"
    if "non_numeric_numeric_value" in reasons or "not_ready_candidate" in reasons:
        return "blocked_from_mapping"
    if row_type in NUMERIC_ROW_TYPES and parse_amount(candidate.get("value")) is None:
        return "blocked_from_mapping"
    if "date_or_year_label" in reasons or "year_header_row" in reasons:
        return "reference_only_or_context"
    if "duplicate_conflicting_values" in reasons:
        return "manual_review_required"
    if {
        "heading_like_numeric_fact",
        "weak_text_block_label",
        "missing_statement_section",
        "section_mismatch",
    } & set(reasons):
        return "manual_review_required"
    if row_type == "text_block" and "text_block_boundary_uncertainty" in reasons:
        return "manual_review_required"
    if row_type in NUMERIC_ROW_TYPES and {
        "current_prior_uncertainty",
        "sign_uncertainty",
        "subtotal_total_uncertainty",
        "duplicate_same_label_value",
        "ambiguous_statement_section",
    } & set(reasons):
        return "suggest_mapping_only"
    if readiness == "high" and row_type not in NON_MAPPING_ROW_TYPES and not (
        {"empty_label", "non_numeric_value", "date_or_year_value_as_amount"} & issue_codes
    ):
        return "auto_mappable_candidate"
    if readiness == "medium" and row_type not in NON_MAPPING_ROW_TYPES:
        return "suggest_mapping_only"
    if readiness == "low" and row_type == "text_block" and clean_text(candidate.get("text") or candidate.get("source_snippet")):
        return "suggest_mapping_only"
    return "manual_review_required" if row_type not in NON_MAPPING_ROW_TYPES else "reference_only_or_context"


def _review_priority(candidate: dict[str, Any], gate_status: str, reasons: list[str]) -> str:
    row_type = str(candidate.get("row_type") or "unknown")
    if gate_status == "manual_review_required" and "duplicate_conflicting_values" in reasons and row_type in NUMERIC_ROW_TYPES:
        return "critical"
    if gate_status == "blocked_from_mapping" and {"non_numeric_numeric_value", "suppressed_candidate"} & set(reasons):
        return "high"
    if {"heading_like_numeric_fact", "date_or_year_label"} & set(reasons):
        return "high"
    if "missing_statement_section" in reasons and row_type in NUMERIC_ROW_TYPES:
        return "high"
    if {
        "weak_text_block_label",
        "text_block_boundary_uncertainty",
        "subtotal_total_uncertainty",
        "current_prior_uncertainty",
    } & set(reasons):
        return "medium"
    return "low"


def _recommended_action(gate_status: str, reasons: list[str], row_type: str) -> str:
    if gate_status == "blocked_from_mapping":
        if "suppressed_candidate" in reasons:
            return "suppress_candidate"
        if "non_numeric_numeric_value" in reasons:
            return "correct_value"
        return "reject_candidate"
    if gate_status == "reference_only_or_context":
        return "keep_for_context_only"
    if "duplicate_conflicting_values" in reasons:
        return "manual_taxonomy_mapping_required"
    if "heading_like_numeric_fact" in reasons:
        return "correct_row_type"
    if "weak_text_block_label" in reasons:
        return "correct_label"
    if "missing_statement_section" in reasons:
        return "correct_section"
    if row_type == "text_block" and "text_block_boundary_uncertainty" in reasons:
        return "split_text_block"
    return "confirm_candidate_for_mapping"


def _candidate_gate_record(
    *,
    entry: dict[str, Any],
    groups_by_candidate: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    candidate_id = str(entry.get("original_candidate_id") or "")
    retained = bool(entry.get("retained_in_cleaned_rows", True))
    candidate = deepcopy(entry.get("cleaned_candidate") if retained else entry.get("original_candidate") or {})
    candidate.setdefault("original_candidate_id", candidate_id)
    candidate.setdefault("case_id", entry.get("case_id"))
    candidate.setdefault("page_number", entry.get("page_number"))
    groups = groups_by_candidate.get(candidate_id, [])
    issues = detect_candidate_issues(candidate)
    readiness = str(entry.get("proposed_readiness") or readiness_for_candidate(candidate, issues))
    reasons = _reason_codes_for_candidate(candidate=candidate, entry=entry, issues=issues, groups=groups)
    gate_status = classify_gate_status(
        candidate=candidate,
        entry=entry,
        readiness=readiness,
        reasons=reasons,
        issues=issues,
    )
    requires_confirmation = gate_status == "suggest_mapping_only"
    warning_flags = sorted({str(issue.get("code")) for issue in issues} | set(reasons) | {str(item) for item in candidate.get("warnings") or []})
    return {
        **_candidate_identity(candidate),
        "original_candidate_id": candidate_id,
        "original_global_index": entry.get("original_global_index"),
        "retained_in_cleaned_rows": retained,
        "original_row_type": entry.get("original_row_type"),
        "proposed_row_type": candidate.get("row_type"),
        "resolution_action": entry.get("action"),
        "duplicate_group_ids": [str(group.get("group_id")) for group in groups],
        "duplicate_group_types": sorted({str(group.get("group_type")) for group in groups}),
        "readiness": readiness,
        "gate_status": gate_status,
        "requires_confirmation": requires_confirmation,
        "review_reasons": reasons,
        "issue_codes": [str(issue.get("code")) for issue in issues],
        "warning_flags": warning_flags,
        "source_provenance": {
            "extraction_method": candidate.get("extraction_method"),
            "source_pdf": candidate.get("source_pdf"),
            "page_number": candidate.get("page_number"),
            "confidence": candidate.get("confidence"),
            "provenance": candidate.get("provenance") or {},
        },
    }


def _queue_item(record: dict[str, Any], sequence: int) -> dict[str, Any]:
    priority = _review_priority(record, record["gate_status"], record["review_reasons"])
    row_type = str(record.get("row_type") or "unknown")
    return {
        "queue_id": f"13T-{sequence:04d}",
        "priority": priority,
        "case_id": record.get("case_id"),
        "candidate_id": record.get("candidate_id"),
        "original_candidate_id": record.get("original_candidate_id"),
        "duplicate_group_id": (record.get("duplicate_group_ids") or [None])[0],
        "duplicate_group_ids": record.get("duplicate_group_ids") or [],
        "label": record.get("label"),
        "value": record.get("value"),
        "previous_value": record.get("previous_value"),
        "text_preview": record.get("text_preview"),
        "statement_section": record.get("statement_section"),
        "row_type": row_type,
        "source": record.get("source"),
        "page_number": record.get("page_number"),
        "gate_status": record.get("gate_status"),
        "review_reasons": record.get("review_reasons") or [],
        "recommended_reviewer_action": _recommended_action(record["gate_status"], record["review_reasons"], row_type),
        "reviewer_decision_options": REVIEWER_DECISION_OPTIONS,
        "source_snippet": record.get("source_snippet"),
        "evidence_preview": record.get("source_snippet") or record.get("text_preview"),
        "retained_in_cleaned_rows": record.get("retained_in_cleaned_rows"),
    }


def _priority_sort_key(item: dict[str, Any]) -> tuple[int, str, int]:
    priority_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    return (
        priority_rank.get(str(item.get("priority")), 9),
        str(item.get("case_id") or ""),
        int(item.get("page_number") or 0),
    )


def _conflict_groups(duplicate_report: dict[str, Any], records_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in duplicate_report.get("duplicate_groups") or []:
        if group.get("group_type") != "same_label_conflicting_values":
            continue
        candidate_ids = [str(item) for item in group.get("candidate_ids") or []]
        candidate_options = [records_by_id[candidate_id] for candidate_id in candidate_ids if candidate_id in records_by_id]
        row_types = {str(record.get("row_type") or "") for record in candidate_options}
        numeric_conflict = bool(row_types & NUMERIC_ROW_TYPES)
        rows.append(
            {
                "conflict_group_id": group.get("group_id"),
                "case_id": group.get("case_id"),
                "normalized_label": group.get("normalized_label"),
                "label": group.get("label"),
                "candidate_count": group.get("candidate_count"),
                "value_variants": group.get("values") or [],
                "affected_pages": group.get("page_numbers") or [],
                "affected_sections": group.get("statement_sections") or [],
                "candidate_options": candidate_options,
                "group_review_priority": "critical" if numeric_conflict else "high",
                "recommended_policy": "manual_review_before_mapping",
                "blocks_auto_mapping": True,
                "reason": "Conflicting candidate values must be resolved before automatic mapping.",
                "reviewer_decision_options": CONFLICT_DECISION_OPTIONS,
            }
        )
    return rows


def _count_by(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get(key) or "unknown") for record in records).items()))


def _nested_count(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        grouped[str(record.get(key) or "unknown")][record["gate_status"]] += 1
    return [
        {"name": name, **{status: counts.get(status, 0) for status in GATE_STATUSES}}
        for name, counts in sorted(grouped.items())
    ]


def _top_reason_rows(records: list[dict[str, Any]], statuses: set[str] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for record in records:
        if statuses and record.get("gate_status") not in statuses:
            continue
        for reason in record.get("review_reasons") or []:
            counter[reason] += 1
    return [{"reason": reason, "count": count} for reason, count in counter.most_common(limit)]


def _top_labels_requiring_review(records: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for record in records:
        if record.get("gate_status") in {"manual_review_required", "blocked_from_mapping", "suggest_mapping_only"}:
            counter[normalize_label(record.get("label")) or "(blank)"] += 1
    return [{"label": label, "count": count} for label, count in counter.most_common(limit)]


def policy_definitions() -> dict[str, Any]:
    return {
        "gate_status_definitions": {
            "auto_mappable_candidate": "High-readiness fact/text candidate with strong evidence and no conflict/manual-review blockers.",
            "suggest_mapping_only": "Usable candidate that may receive mapping suggestions but requires human confirmation before XBRL generation.",
            "manual_review_required": "Candidate or conflict group must be reviewed before any mapping attempt.",
            "blocked_from_mapping": "Candidate must not enter automatic mapping.",
            "reference_only_or_context": "Contextual heading/metadata/narrative support; not a mapped fact.",
        },
        "manual_review_reason_definitions": REASON_DEFINITIONS,
        "reviewer_decision_options": REVIEWER_DECISION_OPTIONS,
        "conflict_group_decision_options": CONFLICT_DECISION_OPTIONS,
        "mapping_candidate_input_contract": mapping_candidate_input_contract(),
        "limitations": [
            "This is not taxonomy mapping.",
            "This is not XBRL generation.",
            "This does not prove production readiness.",
            "Reference XML is not sent to any model.",
            "No DB mutation, live model call, benchmark rerun, UI/API implementation, or production cutover is performed.",
        ],
    }


def mapping_candidate_input_contract() -> dict[str, Any]:
    return {
        "allowed_gate_statuses_for_13u": ["auto_mappable_candidate", "suggest_mapping_only"],
        "suggest_mapping_only_requires_confirmation": True,
        "blocked_gate_statuses_for_automatic_mapping": [
            "manual_review_required",
            "blocked_from_mapping",
            "reference_only_or_context",
        ],
        "required_fields_for_13u": [
            "candidate_id",
            "case_id",
            "label",
            "value",
            "previous_value",
            "text",
            "row_type",
            "statement_section",
            "confidence_or_readiness_score",
            "gate_status",
            "requires_confirmation",
            "warning_flags",
            "source_provenance",
            "page_number",
            "duplicate_conflict_group_status",
        ],
        "rules": [
            "Do not include suppressed candidates in auto mapping input.",
            "Do not include downgraded metadata/year/date candidates in auto mapping input.",
            "Do not include conflict-review candidates in auto mapping input unless future human confirmation exists.",
            "Do not map manual_review_required, blocked_from_mapping, or reference_only_or_context candidates automatically.",
        ],
    }


def build_manual_review_policy_reports(
    *,
    cleaned_report: dict[str, Any],
    duplicate_report: dict[str, Any],
    readiness_report: dict[str, Any],
    quality_report: dict[str, Any] | None = None,
    reference_report: dict[str, Any] | None = None,
    input_paths: dict[str, str | None] | None = None,
    output_paths: dict[str, str | None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    del quality_report, reference_report
    groups_by_candidate, _groups_by_id = _group_maps(duplicate_report)
    records = [
        _candidate_gate_record(entry=entry, groups_by_candidate=groups_by_candidate)
        for entry in _audit_entries(cleaned_report)
    ]
    records_by_id = {str(record["original_candidate_id"]): record for record in records}
    gate_counts = Counter(record["gate_status"] for record in records)
    queue_records = [
        record
        for record in records
        if record["gate_status"] != "auto_mappable_candidate"
        or record["requires_confirmation"]
    ]
    queue_items = [_queue_item(record, index + 1) for index, record in enumerate(queue_records)]
    queue_items.sort(key=_priority_sort_key)
    for index, item in enumerate(queue_items, start=1):
        item["queue_id"] = f"13T-{index:04d}"

    conflict_groups = _conflict_groups(duplicate_report, records_by_id)
    allowed_records = [
        record
        for record in records
        if record["gate_status"] in {"auto_mappable_candidate", "suggest_mapping_only"}
    ]
    requires_confirmation_records = [
        record for record in allowed_records if record["requires_confirmation"]
    ]
    blocked_records = [
        record
        for record in records
        if record["gate_status"] in {"manual_review_required", "blocked_from_mapping", "reference_only_or_context"}
    ]
    metadata = {
        "generated_at": utc_now_iso(),
        "feature": "13T",
        "read_only": True,
        "database_mutated": False,
        "production_behavior_changed": False,
        "ui_upload_required": False,
        "xbrl_generated": False,
        "arelle_validation_run": False,
        "live_huggingface_calls_made": False,
        "live_openai_calls_made": False,
        "reference_xml_sent_to_model": False,
        "benchmark_rerun": False,
    }
    output_paths = output_paths or {}
    input_paths = input_paths or {}

    policy_report = {
        "run_metadata": {
            **metadata,
            "script": "scripts/build_extraction_v2_manual_review_queue.py",
            "report_type": "manual_review_policy",
            "output_path": output_paths.get("policy"),
        },
        "input_reports": input_paths,
        "final_13q_benchmark_still_successful": True,
        "feature_13r_baseline_remains_valid": True,
        "feature_13s_cleaned_report_is_input": True,
        **policy_definitions(),
        "conflict_group_policy": {
            "preserve_all_conflicting_candidates": True,
            "choose_winner_automatically": False,
            "blocks_auto_mapping_by_default": True,
            "conflict_group_count": len(conflict_groups),
        },
        "recommended_next_feature": _recommended_next_feature(gate_counts, len(allowed_records), len(conflict_groups)),
    }

    gate_report = {
        "run_metadata": {
            **metadata,
            "script": "scripts/build_extraction_v2_manual_review_queue.py",
            "report_type": "mapping_candidate_gate",
            "output_path": output_paths.get("gate"),
        },
        "input_reports": input_paths,
        "aggregate_gate_counts": {status: gate_counts.get(status, 0) for status in GATE_STATUSES},
        "total_original_candidates": (cleaned_report.get("duplicate_resolution") or {}).get("original_candidate_count", len(records)),
        "total_cleaned_candidates": (cleaned_report.get("duplicate_resolution") or {}).get("cleaned_candidate_count"),
        "per_case_gate_distribution": _nested_count(records, "case_id"),
        "per_row_type_gate_distribution": _nested_count(records, "row_type"),
        "per_source_gate_distribution": _nested_count(records, "source"),
        "top_manual_review_reasons": _top_reason_rows(records, {"manual_review_required", "suggest_mapping_only"}),
        "top_blocked_reasons": _top_reason_rows(records, {"blocked_from_mapping", "reference_only_or_context"}),
        "top_cases_requiring_review": [
            {"case_id": name, "count": count}
            for name, count in Counter(
                str(record.get("case_id") or "unknown")
                for record in records
                if record["gate_status"] in {"manual_review_required", "blocked_from_mapping", "suggest_mapping_only"}
            ).most_common(20)
        ],
        "top_labels_requiring_review": _top_labels_requiring_review(records),
        "top_conflict_groups_requiring_review": conflict_groups[:20],
        "candidate_gate_records": records,
        "mapping_candidate_input_contract": mapping_candidate_input_contract(),
        "mapping_candidate_input_summary": {
            "allowed_into_13u_count": len(allowed_records),
            "requires_confirmation_count": len(requires_confirmation_records),
            "auto_mappable_count": gate_counts.get("auto_mappable_candidate", 0),
            "suggest_mapping_only_count": gate_counts.get("suggest_mapping_only", 0),
            "blocked_from_13u_count": len(blocked_records),
            "blocked_or_context_statuses": {
                status: gate_counts.get(status, 0)
                for status in ["manual_review_required", "blocked_from_mapping", "reference_only_or_context"]
            },
        },
        "limitations": policy_definitions()["limitations"],
    }

    queue_report = {
        "run_metadata": {
            **metadata,
            "script": "scripts/build_extraction_v2_manual_review_queue.py",
            "report_type": "manual_review_queue",
            "output_path": output_paths.get("queue"),
        },
        "input_reports": input_paths,
        "queue_item_count": len(queue_items),
        "priority_distribution": _count_by(queue_items, "priority"),
        "per_case_review_load": [
            {"case_id": name, "count": count}
            for name, count in Counter(str(item.get("case_id") or "unknown") for item in queue_items).most_common()
        ],
        "top_conflict_groups": conflict_groups[:20],
        "top_numeric_review_items": [
            item for item in queue_items if str(item.get("row_type")) in NUMERIC_ROW_TYPES
        ][:25],
        "top_text_block_review_items": [
            item for item in queue_items if str(item.get("row_type")) == "text_block"
        ][:25],
        "manual_review_queue": queue_items,
        "conflict_groups": conflict_groups,
        "limitations": policy_definitions()["limitations"],
    }
    return policy_report, gate_report, queue_report


def _recommended_next_feature(gate_counts: Counter[str], allowed_count: int, conflict_group_count: int) -> str:
    manual = gate_counts.get("manual_review_required", 0)
    blocked = gate_counts.get("blocked_from_mapping", 0)
    if conflict_group_count or manual > allowed_count * 0.25:
        return "Feature #13U - Manual-review queue UI/API planning before mapping cutover."
    if allowed_count > 0:
        return "Feature #13U - Mapping candidate generation v2 with conservative readiness gates."
    if blocked > manual:
        return "Feature #13U - Label and section normalization before mapping candidate generation."
    return "Feature #13U - Text-block label and section cleanup before mapping."


def render_policy_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Feature #13T Manual-Review Policy",
        "",
        "## Gate Status Definitions",
        "",
    ]
    for status, definition in report.get("gate_status_definitions", {}).items():
        lines.append(f"- `{status}`: {definition}")
    lines.extend(["", "## Manual Review Reasons", ""])
    for code, definition in report.get("manual_review_reason_definitions", {}).items():
        lines.append(f"- `{code}`: {definition}")
    lines.extend(["", "## Conflict Group Policy", ""])
    policy = report.get("conflict_group_policy", {})
    lines.extend(
        [
            f"- Preserve all conflicting candidates: {policy.get('preserve_all_conflicting_candidates')}",
            f"- Choose winner automatically: {policy.get('choose_winner_automatically')}",
            f"- Blocks auto mapping by default: {policy.get('blocks_auto_mapping_by_default')}",
            f"- Conflict group count: {policy.get('conflict_group_count', 0)}",
        ]
    )
    lines.extend(["", "## Mapping Candidate Input Contract", ""])
    contract = report.get("mapping_candidate_input_contract", {})
    lines.append(f"- Allowed statuses for #13U: {contract.get('allowed_gate_statuses_for_13u', [])}")
    lines.append(f"- Suggest-only requires confirmation: {contract.get('suggest_mapping_only_requires_confirmation')}")
    lines.append(f"- Blocked statuses: {contract.get('blocked_gate_statuses_for_automatic_mapping', [])}")
    lines.extend(["", "## Reviewer Decision Options", ""])
    lines.extend(f"- `{option}`" for option in report.get("reviewer_decision_options", []))
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.extend(["", "## Recommended Next Feature", "", f"- {report.get('recommended_next_feature')}", ""])
    return "\n".join(lines)


def render_gate_markdown(report: dict[str, Any]) -> str:
    counts = report.get("aggregate_gate_counts", {})
    summary = report.get("mapping_candidate_input_summary", {})
    lines = [
        "# Feature #13T Mapping Candidate Gate Report",
        "",
        "## Summary",
        "",
        f"- Total original candidates: {report.get('total_original_candidates', 0)}",
        f"- Total cleaned candidates: {report.get('total_cleaned_candidates', 0)}",
        f"- Auto mappable: {counts.get('auto_mappable_candidate', 0)}",
        f"- Suggest mapping only: {counts.get('suggest_mapping_only', 0)}",
        f"- Manual review required: {counts.get('manual_review_required', 0)}",
        f"- Blocked from mapping: {counts.get('blocked_from_mapping', 0)}",
        f"- Reference only/context: {counts.get('reference_only_or_context', 0)}",
        f"- Allowed into #13U: {summary.get('allowed_into_13u_count', 0)}",
        f"- Requires confirmation: {summary.get('requires_confirmation_count', 0)}",
        f"- Blocked from #13U: {summary.get('blocked_from_13u_count', 0)}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        "",
        "This is not taxonomy mapping, XBRL generation, or production readiness proof.",
        "",
        "## Per Case Gate Distribution",
        "",
        "| Case | Auto | Suggest | Manual | Blocked | Context |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("per_case_gate_distribution", []):
        lines.append(
            "| {name} | {auto_mappable_candidate} | {suggest_mapping_only} | {manual_review_required} | {blocked_from_mapping} | {reference_only_or_context} |".format(
                **row
            )
        )
    lines.extend(["", "## Top Manual Review Reasons", ""])
    lines.extend(f"- {item['reason']}: {item['count']}" for item in report.get("top_manual_review_reasons", [])[:15])
    lines.extend(["", "## Top Blocked Reasons", ""])
    lines.extend(f"- {item['reason']}: {item['count']}" for item in report.get("top_blocked_reasons", [])[:15])
    lines.append("")
    return "\n".join(lines)


def render_queue_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Feature #13T Manual Review Queue",
        "",
        "## Summary",
        "",
        f"- Queue item count: {report.get('queue_item_count', 0)}",
        f"- Priority distribution: {report.get('priority_distribution', {})}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        "",
        "## Per Case Review Load",
        "",
        "| Case | Queue Items |",
        "| --- | ---: |",
    ]
    for row in report.get("per_case_review_load", []):
        lines.append(f"| {row['case_id']} | {row['count']} |")
    lines.extend(["", "## Top Conflict Groups", ""])
    for group in report.get("top_conflict_groups", [])[:10]:
        lines.append(
            f"- `{group.get('conflict_group_id')}` {group.get('case_id')} / {group.get('normalized_label')}: {group.get('candidate_count')} candidates, priority={group.get('group_review_priority')}"
        )
    lines.extend(["", "## Queue Preview", ""])
    for item in report.get("manual_review_queue", [])[:25]:
        lines.append(
            f"- `{item['queue_id']}` {item['priority']} {item.get('case_id')} p{item.get('page_number')}: {item.get('label')} [{item.get('gate_status')}] reasons={item.get('review_reasons')}"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)
