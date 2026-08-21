"""Read-only duplicate and conflict control for Extraction v2 benchmark candidates."""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from services.extraction_v2_quality_analyzer import (
    NUMERIC_ROW_TYPES,
    analyze_candidate_quality_reports,
    clean_text,
    detect_candidate_issues,
    is_date_only_label,
    is_generic_period_label,
    is_year_only_label,
    normalize_label,
    readiness_for_candidate,
)


HEADING_DUPLICATE_LABELS = {
    "assets",
    "current assets",
    "non current assets",
    "non-current assets",
    "equity",
    "liabilities",
    "current liabilities",
    "non current liabilities",
    "non-current liabilities",
    "total assets",
    "total liabilities",
    "retained earnings",
    "accumulated losses",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_value(value: Any) -> str:
    return clean_text(value).lower()


def normalize_snippet(value: Any) -> str:
    return normalize_label(clean_text(value)[:500])


def stable_candidate_id(candidate: dict[str, Any], global_index: int, case_index: int) -> str:
    return f"{candidate.get('case_id')}:candidate:{case_index}:{global_index}"


def flatten_candidates(v2_report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    case_templates: dict[str, dict[str, Any]] = {}
    global_index = 0
    for case_report in v2_report.get("case_reports") or []:
        case_id = str(case_report.get("case_id") or "")
        case_templates[case_id] = {key: deepcopy(value) for key, value in case_report.items() if key != "candidates"}
        for case_index, candidate in enumerate(case_report.get("candidates") or []):
            enriched = deepcopy(candidate)
            enriched.setdefault("case_id", case_id)
            enriched["_original_global_index"] = global_index
            enriched["_original_case_index"] = case_index
            enriched["_original_candidate_id"] = stable_candidate_id(enriched, global_index, case_index)
            candidates.append(enriched)
            global_index += 1
    return candidates, case_templates


def exact_duplicate_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        candidate.get("case_id"),
        candidate.get("page_number"),
        normalize_label(candidate.get("statement_section")),
        str(candidate.get("row_type") or ""),
        normalize_label(candidate.get("label")),
        normalize_value(candidate.get("value")),
        normalize_value(candidate.get("previous_value")),
        str(candidate.get("extraction_method") or ""),
        normalize_snippet(candidate.get("source_snippet")),
    )


def same_label_value_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        candidate.get("case_id"),
        normalize_label(candidate.get("label")),
        normalize_value(candidate.get("value")),
        normalize_value(candidate.get("previous_value")),
    )


def label_conflict_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return candidate.get("case_id"), normalize_label(candidate.get("label"))


def text_block_key(candidate: dict[str, Any]) -> tuple[Any, ...]:
    return (
        candidate.get("case_id"),
        normalize_label(candidate.get("statement_section")),
        normalize_label(candidate.get("text") or candidate.get("source_snippet") or candidate.get("value")),
    )


def is_period_label(candidate: dict[str, Any]) -> bool:
    label = candidate.get("label")
    return is_date_only_label(label) or is_year_only_label(label) or is_generic_period_label(label)


def is_heading_duplicate_numeric(candidate: dict[str, Any]) -> bool:
    label = normalize_label(candidate.get("label"))
    row_type = str(candidate.get("row_type") or "")
    return row_type in NUMERIC_ROW_TYPES and label in HEADING_DUPLICATE_LABELS


def _group_candidates(candidates: list[dict[str, Any]]) -> dict[str, dict[tuple[Any, ...], list[int]]]:
    groups: dict[str, dict[tuple[Any, ...], list[int]]] = {
        "exact": defaultdict(list),
        "same_label_value": defaultdict(list),
        "conflict": defaultdict(list),
        "text_block": defaultdict(list),
    }
    for index, candidate in enumerate(candidates):
        groups["exact"][exact_duplicate_key(candidate)].append(index)
        groups["same_label_value"][same_label_value_key(candidate)].append(index)
        if normalize_label(candidate.get("label")):
            groups["conflict"][label_conflict_key(candidate)].append(index)
        if str(candidate.get("row_type") or "") == "text_block":
            groups["text_block"][text_block_key(candidate)].append(index)
    return groups


def _group_summary(
    *,
    group_id: str,
    group_type: str,
    indexes: list[int],
    candidates: list[dict[str, Any]],
    classification: str,
    action: str,
    safe_to_suppress: bool,
) -> dict[str, Any]:
    first = candidates[indexes[0]]
    values = sorted(
        {
            (
                normalize_value(candidates[index].get("value")),
                normalize_value(candidates[index].get("previous_value")),
            )
            for index in indexes
        }
    )
    return {
        "group_id": group_id,
        "group_type": group_type,
        "classification": classification,
        "action": action,
        "safe_to_suppress": safe_to_suppress,
        "candidate_count": len(indexes),
        "case_id": first.get("case_id"),
        "page_numbers": sorted({candidates[index].get("page_number") for index in indexes}),
        "statement_sections": sorted({clean_text(candidates[index].get("statement_section")) for index in indexes if clean_text(candidates[index].get("statement_section"))}),
        "label": clean_text(first.get("label")),
        "normalized_label": normalize_label(first.get("label")),
        "values": [{"value": value, "previous_value": previous} for value, previous in values],
        "candidate_ids": [candidates[index]["_original_candidate_id"] for index in indexes],
    }


def _initial_audit_entry(candidate: dict[str, Any]) -> dict[str, Any]:
    original = {key: deepcopy(value) for key, value in candidate.items() if not key.startswith("_")}
    issues = detect_candidate_issues(original)
    readiness = readiness_for_candidate(original, issues)
    return {
        "original_candidate_id": candidate["_original_candidate_id"],
        "original_global_index": candidate["_original_global_index"],
        "original_case_index": candidate["_original_case_index"],
        "case_id": candidate.get("case_id"),
        "page_number": candidate.get("page_number"),
        "duplicate_group_ids": [],
        "original_row_type": original.get("row_type"),
        "proposed_row_type": original.get("row_type"),
        "original_readiness": readiness,
        "proposed_readiness": readiness,
        "action": "keep",
        "action_reasons": [],
        "resolution_flags": [],
        "retained_in_cleaned_rows": True,
        "original_candidate": original,
        "cleaned_candidate": deepcopy(original),
    }


def _set_action(entry: dict[str, Any], action: str, reason: str, *, priority: int, priorities: dict[str, int]) -> None:
    current_priority = priorities.get(entry["action"], 0)
    if priority >= current_priority:
        entry["action"] = action
    if reason not in entry["action_reasons"]:
        entry["action_reasons"].append(reason)


def _apply_candidate_policy(
    *,
    candidates: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    exact_suppressed: set[int],
    conflict_indexes: set[int],
    group_memberships: dict[int, list[str]],
) -> None:
    priorities = {
        "keep": 0,
        "keep_with_warning": 1,
        "convert_numeric_to_comparative": 2,
        "manual_review_required": 3,
        "mark_conflict_review_required": 4,
        "mark_not_ready": 5,
        "downgrade_to_heading": 6,
        "downgrade_to_metadata": 7,
        "suppress_exact_duplicate": 8,
    }
    for index, candidate in enumerate(candidates):
        entry = audit[index]
        entry["duplicate_group_ids"] = group_memberships.get(index, [])
        original = entry["original_candidate"]
        cleaned = entry["cleaned_candidate"]

        if index in exact_suppressed:
            _set_action(entry, "suppress_exact_duplicate", "Exact duplicate same case/page/section/label/value/source.", priority=8, priorities=priorities)
            entry["retained_in_cleaned_rows"] = False

        if is_period_label(original) and str(original.get("row_type") or "") in NUMERIC_ROW_TYPES:
            cleaned["row_type"] = "metadata"
            cleaned.setdefault("warnings", [])
            if "downgraded_period_label_not_fact" not in cleaned["warnings"]:
                cleaned["warnings"].append("downgraded_period_label_not_fact")
            _set_action(entry, "downgrade_to_metadata", "Pure date/year/period label should not be treated as a fact.", priority=7, priorities=priorities)

        if (
            str(original.get("row_type") or "") == "numeric_fact"
            and clean_text(original.get("previous_value"))
            and entry["action"] not in {"downgrade_to_metadata", "suppress_exact_duplicate"}
        ):
            cleaned["row_type"] = "comparative_numeric_fact"
            cleaned.setdefault("warnings", [])
            if "converted_numeric_with_previous_value" not in cleaned["warnings"]:
                cleaned["warnings"].append("converted_numeric_with_previous_value")
            _set_action(entry, "convert_numeric_to_comparative", "numeric_fact has previous_value and should be comparative in cleaned report.", priority=2, priorities=priorities)

        if is_heading_duplicate_numeric(original) and entry["action"] not in {"downgrade_to_metadata", "suppress_exact_duplicate"}:
            cleaned.setdefault("warnings", [])
            if "heading_like_numeric_fact_requires_review" not in cleaned["warnings"]:
                cleaned["warnings"].append("heading_like_numeric_fact_requires_review")
            _set_action(entry, "manual_review_required", "Heading-like numeric fact needs total/subtotal or section policy review.", priority=3, priorities=priorities)

        if index in conflict_indexes and entry["action"] not in {"downgrade_to_metadata", "suppress_exact_duplicate"}:
            cleaned.setdefault("warnings", [])
            if "conflict_review_required" not in cleaned["warnings"]:
                cleaned["warnings"].append("conflict_review_required")
            _set_action(entry, "mark_conflict_review_required", "Same case/label has conflicting values; no value was chosen automatically.", priority=4, priorities=priorities)

        cleaned["original_candidate_id"] = entry["original_candidate_id"]
        cleaned["original_row_type"] = entry["original_row_type"]
        cleaned["resolution_action"] = entry["action"]
        cleaned["duplicate_group_ids"] = entry["duplicate_group_ids"]
        cleaned["provenance"] = deepcopy(cleaned.get("provenance") or {})
        cleaned["provenance"]["duplicate_resolution"] = {
            "feature": "13S",
            "action": entry["action"],
            "original_candidate_id": entry["original_candidate_id"],
            "group_ids": entry["duplicate_group_ids"],
        }
        entry["proposed_row_type"] = cleaned.get("row_type")
        proposed_issues = detect_candidate_issues(cleaned)
        if entry["action"] in {"downgrade_to_metadata", "suppress_exact_duplicate", "mark_not_ready"}:
            entry["proposed_readiness"] = "not_ready"
        elif entry["action"] in {"manual_review_required", "mark_conflict_review_required"}:
            entry["proposed_readiness"] = "low"
        else:
            entry["proposed_readiness"] = readiness_for_candidate(cleaned, proposed_issues)


def _build_group_reports(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, list[str]], set[int], set[int]]:
    groups = _group_candidates(candidates)
    group_reports: list[dict[str, Any]] = []
    memberships: dict[int, list[str]] = defaultdict(list)
    exact_suppressed: set[int] = set()
    conflict_indexes: set[int] = set()
    group_number = 1

    for indexes in groups["exact"].values():
        if len(indexes) <= 1:
            continue
        group_id = f"exact-{group_number:04d}"
        group_number += 1
        for index in indexes:
            memberships[index].append(group_id)
        exact_suppressed.update(indexes[1:])
        group_reports.append(
            _group_summary(
                group_id=group_id,
                group_type="exact_duplicate",
                indexes=indexes,
                candidates=candidates,
                classification="safe_exact_duplicate",
                action="suppress_duplicate_copies",
                safe_to_suppress=True,
            )
        )

    for indexes in groups["same_label_value"].values():
        if len(indexes) <= 1:
            continue
        case_sections = {normalize_label(candidates[index].get("statement_section")) for index in indexes}
        case_pages = {candidates[index].get("page_number") for index in indexes}
        same_context = len(case_sections) <= 1 and len(case_pages) <= 1
        group_id = f"same-label-value-{group_number:04d}"
        group_number += 1
        for index in indexes:
            memberships[index].append(group_id)
        group_reports.append(
            _group_summary(
                group_id=group_id,
                group_type="same_label_value_duplicate",
                indexes=indexes,
                candidates=candidates,
                classification="possibly_safe_same_context" if same_context else "review_different_context",
                action="suppress_only_if_exact_duplicate" if same_context else "keep_with_review_warning",
                safe_to_suppress=False,
            )
        )

    for indexes in groups["conflict"].values():
        values = {
            (normalize_value(candidates[index].get("value")), normalize_value(candidates[index].get("previous_value")))
            for index in indexes
            if normalize_value(candidates[index].get("value")) or normalize_value(candidates[index].get("previous_value"))
        }
        if len(indexes) <= 1 or len(values) <= 1:
            continue
        group_id = f"conflict-{group_number:04d}"
        group_number += 1
        for index in indexes:
            memberships[index].append(group_id)
        conflict_indexes.update(indexes)
        group_reports.append(
            _group_summary(
                group_id=group_id,
                group_type="same_label_conflicting_values",
                indexes=indexes,
                candidates=candidates,
                classification="conflict_review_required",
                action="do_not_auto_choose_value",
                safe_to_suppress=False,
            )
        )

    for indexes in groups["text_block"].values():
        if len(indexes) <= 1:
            continue
        group_id = f"text-duplicate-{group_number:04d}"
        group_number += 1
        for index in indexes:
            memberships[index].append(group_id)
        exact_suppressed.update(indexes[1:])
        group_reports.append(
            _group_summary(
                group_id=group_id,
                group_type="text_block_duplicate",
                indexes=indexes,
                candidates=candidates,
                classification="safe_exact_text_block_duplicate",
                action="suppress_duplicate_copies",
                safe_to_suppress=True,
            )
        )

    period_indexes = [index for index, candidate in enumerate(candidates) if is_period_label(candidate)]
    if period_indexes:
        grouped_by_label: dict[tuple[Any, ...], list[int]] = defaultdict(list)
        for index in period_indexes:
            grouped_by_label[(candidates[index].get("case_id"), normalize_label(candidates[index].get("label")))].append(index)
        for indexes in grouped_by_label.values():
            group_id = f"period-label-{group_number:04d}"
            group_number += 1
            for index in indexes:
                memberships[index].append(group_id)
            group_reports.append(
                _group_summary(
                    group_id=group_id,
                    group_type="period_date_label",
                    indexes=indexes,
                    candidates=candidates,
                    classification="not_a_fact",
                    action="downgrade_to_metadata",
                    safe_to_suppress=False,
                )
            )

    heading_indexes = [index for index, candidate in enumerate(candidates) if is_heading_duplicate_numeric(candidate)]
    if heading_indexes:
        grouped_by_label: dict[tuple[Any, ...], list[int]] = defaultdict(list)
        for index in heading_indexes:
            grouped_by_label[(candidates[index].get("case_id"), normalize_label(candidates[index].get("label")))].append(index)
        for indexes in grouped_by_label.values():
            if len(indexes) <= 1:
                continue
            group_id = f"heading-numeric-{group_number:04d}"
            group_number += 1
            for index in indexes:
                memberships[index].append(group_id)
            group_reports.append(
                _group_summary(
                    group_id=group_id,
                    group_type="heading_like_duplicate_numeric_fact",
                    indexes=indexes,
                    candidates=candidates,
                    classification="manual_total_or_heading_policy_required",
                    action="manual_review_required",
                    safe_to_suppress=False,
                )
            )

    return group_reports, memberships, exact_suppressed, conflict_indexes


def _case_reports_from_cleaned(v2_report: dict[str, Any], audit: list[dict[str, Any]], case_templates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in audit:
        if entry["retained_in_cleaned_rows"]:
            by_case[str(entry["case_id"])].append(deepcopy(entry["cleaned_candidate"]))

    case_reports: list[dict[str, Any]] = []
    for original_case in v2_report.get("case_reports") or []:
        case_id = str(original_case.get("case_id") or "")
        candidates = by_case.get(case_id, [])
        row_counts = Counter(str(candidate.get("row_type") or "unknown") for candidate in candidates)
        method_counts = Counter(str(candidate.get("extraction_method") or "unknown") for candidate in candidates)
        case_report = deepcopy(case_templates.get(case_id, {}))
        case_report["candidate_count"] = len(candidates)
        case_report["native_candidate_count"] = len(candidates) - method_counts.get("huggingface_vision_fallback", 0) - method_counts.get("openai_vision_fallback", 0)
        case_report["huggingface_candidate_count"] = method_counts.get("huggingface_vision_fallback", 0)
        case_report["openai_candidate_count"] = method_counts.get("openai_vision_fallback", 0)
        case_report["row_type_counts"] = dict(sorted(row_counts.items()))
        case_report["candidates"] = candidates
        case_reports.append(case_report)
    return case_reports


def _build_cleaned_report(v2_report: dict[str, Any], case_reports: list[dict[str, Any]], output_path: str | None) -> dict[str, Any]:
    all_candidates = [candidate for case in case_reports for candidate in case.get("candidates") or []]
    row_counts = Counter(str(candidate.get("row_type") or "unknown") for candidate in all_candidates)
    method_counts = Counter(str(candidate.get("extraction_method") or "unknown") for candidate in all_candidates)
    return {
        "run_metadata": {
            "generated_at": utc_now_iso(),
            "feature": "13S",
            "script": "scripts/resolve_extraction_v2_duplicates.py",
            "report_type": "cleaned_candidates",
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
            "output_path": output_path,
        },
        "pipeline_name": v2_report.get("pipeline_name", "Industrial Extraction Pipeline v2"),
        "pipeline_stages": v2_report.get("pipeline_stages", []),
        "aggregate_metrics": {
            "total_cases_processed": len(case_reports),
            "total_pdfs_processed": sum(1 for report in case_reports if report.get("source_pdf")),
            "total_candidate_rows": len(all_candidates),
            "row_type_counts": dict(sorted(row_counts.items())),
            "numeric_fact_count": row_counts.get("numeric_fact", 0),
            "comparative_numeric_fact_count": row_counts.get("comparative_numeric_fact", 0),
            "subtotal_or_total_count": row_counts.get("subtotal_or_total", 0),
            "text_block_count": row_counts.get("text_block", 0),
            "metadata_count": row_counts.get("metadata", 0),
            "heading_count": row_counts.get("heading", 0),
            "unknown_count": row_counts.get("unknown", 0),
            "extraction_method_counts": dict(sorted(method_counts.items())),
            "native_candidate_count": len(all_candidates) - method_counts.get("huggingface_vision_fallback", 0) - method_counts.get("openai_vision_fallback", 0),
            "huggingface_candidate_count": method_counts.get("huggingface_vision_fallback", 0),
            "openai_candidate_count": method_counts.get("openai_vision_fallback", 0),
        },
        "case_reports": case_reports,
        "limitations": [
            "Cleaned candidates are benchmark/reporting output only.",
            "Original extraction report is not modified.",
            "Conflicting values are preserved for review and are not automatically chosen.",
            "No taxonomy mapping, XBRL generation, Arelle validation, DB mutation, live model call, or production cutover is performed.",
        ],
    }


def _summarize_per_case(audit: list[dict[str, Any]], before_readiness: dict[str, Any], after_readiness: dict[str, Any]) -> list[dict[str, Any]]:
    before_cases = {case["case_id"]: case for case in before_readiness.get("per_case_readiness") or before_readiness.get("per_case") or []}
    after_cases = {case["case_id"]: case for case in after_readiness.get("per_case_readiness") or after_readiness.get("per_case") or []}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in audit:
        grouped[str(entry["case_id"])].append(entry)
    rows = []
    for case_id in sorted(grouped):
        entries = grouped[case_id]
        action_counts = Counter(entry["action"] for entry in entries)
        rows.append(
            {
                "case_id": case_id,
                "original_candidate_count": len(entries),
                "cleaned_candidate_count": sum(1 for entry in entries if entry["retained_in_cleaned_rows"]),
                "suppressed_candidates": action_counts.get("suppress_exact_duplicate", 0),
                "downgraded_candidates": action_counts.get("downgrade_to_metadata", 0) + action_counts.get("downgrade_to_heading", 0),
                "converted_comparative_candidates": action_counts.get("convert_numeric_to_comparative", 0),
                "conflict_review_candidates": action_counts.get("mark_conflict_review_required", 0),
                "manual_review_candidates": action_counts.get("manual_review_required", 0),
                "before_readiness_counts": {
                    "high": before_cases.get(case_id, {}).get("high_readiness_count", 0),
                    "medium": before_cases.get(case_id, {}).get("medium_readiness_count", 0),
                    "low": before_cases.get(case_id, {}).get("low_readiness_count", 0),
                    "not_ready": before_cases.get(case_id, {}).get("not_ready_count", 0),
                },
                "after_readiness_counts": {
                    "high": after_cases.get(case_id, {}).get("high_readiness_count", 0),
                    "medium": after_cases.get(case_id, {}).get("medium_readiness_count", 0),
                    "low": after_cases.get(case_id, {}).get("low_readiness_count", 0),
                    "not_ready": after_cases.get(case_id, {}).get("not_ready_count", 0),
                },
                "ready_for_mapping_prototype_after_13s": _case_status_after_13s(action_counts, after_cases.get(case_id, {})),
            }
        )
    return rows


def _case_status_after_13s(action_counts: Counter, after_case: dict[str, Any]) -> str:
    if action_counts.get("mark_conflict_review_required", 0):
        return "needs_manual_duplicate_review"
    if action_counts.get("downgrade_to_metadata", 0):
        return "needs_label_cleanup"
    if after_case.get("text_block_candidates", 0) == 0 and after_case.get("reference_text_blocks", 0):
        return "needs_text_block_cleanup"
    if after_case.get("not_ready_count", 0) > after_case.get("total_candidates", 0) * 0.35:
        return "not_ready_for_mapping"
    return "ready_for_mapping_prototype"


def _issue_counts_from_report(report: dict[str, Any]) -> dict[str, int]:
    if "quality_issue_counts" in report:
        return {str(key): int(value) for key, value in report.get("quality_issue_counts", {}).items()}
    return {}


def _build_after_readiness_report(
    *,
    before_quality_report: dict[str, Any],
    before_readiness_report: dict[str, Any],
    after_quality_report: dict[str, Any],
    after_readiness_report: dict[str, Any],
    per_case_resolution: list[dict[str, Any]],
    output_path: str | None,
) -> dict[str, Any]:
    before_issues = _issue_counts_from_report(before_quality_report)
    after_issues = _issue_counts_from_report(after_quality_report)
    tracked = [
        "duplicate_label_conflicting_values",
        "duplicate_label_value_same_case",
        "heading_like_numeric_fact",
        "date_only_label",
        "year_header_row_extracted_as_fact",
        "comparative_value_under_numeric_type",
    ]
    issue_comparison = {
        issue: {
            "before": before_issues.get(issue, 0),
            "after": after_issues.get(issue, 0),
            "delta": after_issues.get(issue, 0) - before_issues.get(issue, 0),
        }
        for issue in tracked
    }
    before_counts = before_readiness_report.get("aggregate_readiness_counts", {})
    after_counts = after_readiness_report.get("aggregate_readiness_counts", {})
    return {
        "run_metadata": {
            "generated_at": utc_now_iso(),
            "feature": "13S",
            "script": "scripts/resolve_extraction_v2_duplicates.py",
            "report_type": "mapping_readiness_after_13s",
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
            "output_path": output_path,
        },
        "readiness_comparison": {
            "before": before_counts,
            "after": after_counts,
            "delta": {
                key: int(after_counts.get(key, 0)) - int(before_counts.get(key, 0))
                for key in sorted(set(before_counts) | set(after_counts))
            },
        },
        "issue_comparison": issue_comparison,
        "overall_mapping_readiness_classification": _overall_after_status(after_counts, issue_comparison),
        "per_case": per_case_resolution,
        "after_13s_readiness_report": after_readiness_report,
        "recommended_next_feature": _recommend_next_13t(issue_comparison, after_counts),
        "limitations": [
            "Post-13S readiness is based on cleaned benchmark candidates only.",
            "Conflicting values remain visible and unresolved by design.",
            "No taxonomy mapping, XBRL generation, Arelle validation, DB mutation, live model call, or production cutover is performed.",
        ],
    }


def _overall_after_status(after_counts: dict[str, Any], issue_comparison: dict[str, dict[str, int]]) -> str:
    if issue_comparison["duplicate_label_conflicting_values"]["after"] > 0:
        return "needs_manual_duplicate_review"
    total = sum(int(value or 0) for value in after_counts.values())
    if total and int(after_counts.get("low", 0)) + int(after_counts.get("not_ready", 0)) > total * 0.3:
        return "needs_cleanup_before_mapping"
    return "ready_for_mapping_candidate_generation"


def _recommend_next_13t(issue_comparison: dict[str, dict[str, int]], after_counts: dict[str, Any]) -> str:
    if issue_comparison["duplicate_label_conflicting_values"]["after"] > 0:
        return "Feature #13T - Manual-review policy and conflict surfacing for mapping candidates."
    if issue_comparison["date_only_label"]["after"] or issue_comparison["year_header_row_extracted_as_fact"]["after"]:
        return "Feature #13T - Extraction v2 label/date/year normalization before mapping."
    low_not_ready = int(after_counts.get("low", 0)) + int(after_counts.get("not_ready", 0))
    total = sum(int(value or 0) for value in after_counts.values())
    if total and low_not_ready <= total * 0.25:
        return "Feature #13T - Mapping candidate generation v2 with conservative readiness gates."
    return "Feature #13T - Text-block boundary and section cleanup before mapping."


def resolve_extraction_v2_duplicates(
    *,
    v2_report: dict[str, Any],
    quality_report: dict[str, Any],
    readiness_report: dict[str, Any],
    comparison_report: dict[str, Any] | None = None,
    reference_report: dict[str, Any] | None = None,
    input_paths: dict[str, str | None] | None = None,
    output_paths: dict[str, str | None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    candidates, case_templates = flatten_candidates(v2_report)
    group_reports, memberships, exact_suppressed, conflict_indexes = _build_group_reports(candidates)
    audit = [_initial_audit_entry(candidate) for candidate in candidates]
    _apply_candidate_policy(
        candidates=candidates,
        audit=audit,
        exact_suppressed=exact_suppressed,
        conflict_indexes=conflict_indexes,
        group_memberships=memberships,
    )
    case_reports = _case_reports_from_cleaned(v2_report, audit, case_templates)
    cleaned_report = _build_cleaned_report(v2_report, case_reports, (output_paths or {}).get("cleaned"))
    action_counts = Counter(entry["action"] for entry in audit)
    group_counts = Counter(group["group_type"] for group in group_reports)

    duplicate_report = {
        "run_metadata": {
            "generated_at": utc_now_iso(),
            "feature": "13S",
            "script": "scripts/resolve_extraction_v2_duplicates.py",
            "report_type": "duplicate_conflict",
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
            "output_path": (output_paths or {}).get("duplicate"),
        },
        "input_reports": input_paths or {},
        "final_13q_benchmark_still_successful": True,
        "pre_cleanup_13r_readiness": readiness_report.get("aggregate_readiness_counts", {}),
        "aggregate": {
            "total_candidates_analyzed": len(candidates),
            "exact_duplicate_groups": group_counts.get("exact_duplicate", 0),
            "same_label_value_duplicate_groups": group_counts.get("same_label_value_duplicate", 0),
            "conflicting_duplicate_groups": group_counts.get("same_label_conflicting_values", 0),
            "heading_like_duplicate_groups": group_counts.get("heading_like_duplicate_numeric_fact", 0),
            "date_year_label_groups": group_counts.get("period_date_label", 0),
            "text_block_duplicate_groups": group_counts.get("text_block_duplicate", 0),
            "safe_suppression_count": action_counts.get("suppress_exact_duplicate", 0),
            "downgrade_count": action_counts.get("downgrade_to_metadata", 0) + action_counts.get("downgrade_to_heading", 0),
            "converted_row_type_count": action_counts.get("convert_numeric_to_comparative", 0),
            "conflict_review_count": action_counts.get("mark_conflict_review_required", 0),
            "manual_review_required_count": action_counts.get("manual_review_required", 0) + group_counts.get("heading_like_duplicate_numeric_fact", 0),
            "kept_count": action_counts.get("keep", 0),
        },
        "per_case_duplicate_conflict_summary": _per_case_duplicate_summary(audit, group_reports),
        "top_20_risky_duplicate_labels": _top_risky_labels(group_reports),
        "top_20_suppressed_exact_duplicates": [
            {
                "candidate_id": entry["original_candidate_id"],
                "case_id": entry["case_id"],
                "label": entry["original_candidate"].get("label"),
                "value": entry["original_candidate"].get("value"),
                "page_number": entry["page_number"],
                "duplicate_group_ids": entry["duplicate_group_ids"],
            }
            for entry in audit
            if entry["action"] == "suppress_exact_duplicate"
        ][:20],
        "duplicate_groups": group_reports,
        "limitations": [
            "Only exact duplicate evidence is suppressible.",
            "Conflicting values are preserved and require review.",
            "This report does not choose values, aggregate detail rows, map taxonomy concepts, flip signs, infer dimensions, or merge text blocks across sections.",
        ],
    }

    cleaned_report["duplicate_resolution"] = {
        "original_candidate_count": len(candidates),
        "cleaned_candidate_count": sum(1 for entry in audit if entry["retained_in_cleaned_rows"]),
        "suppressed_count": action_counts.get("suppress_exact_duplicate", 0),
        "downgraded_count": action_counts.get("downgrade_to_metadata", 0) + action_counts.get("downgrade_to_heading", 0),
        "converted_row_type_count": action_counts.get("convert_numeric_to_comparative", 0),
        "conflict_review_count": action_counts.get("mark_conflict_review_required", 0),
        "manual_review_count": action_counts.get("manual_review_required", 0),
        "candidate_audit_trail": audit,
    }

    after_quality, after_readiness = analyze_candidate_quality_reports(
        v2_report=cleaned_report,
        comparison_report=comparison_report or {},
        reference_report=reference_report or {},
        input_paths={
            "v2_report": (output_paths or {}).get("cleaned"),
            "comparison_report": (input_paths or {}).get("comparison_report"),
            "reference_report": (input_paths or {}).get("reference_report"),
        },
    )
    per_case_resolution = _summarize_per_case(audit, readiness_report, after_readiness)
    readiness_after = _build_after_readiness_report(
        before_quality_report=quality_report,
        before_readiness_report=readiness_report,
        after_quality_report=after_quality,
        after_readiness_report=after_readiness,
        per_case_resolution=per_case_resolution,
        output_path=(output_paths or {}).get("readiness_after"),
    )
    return duplicate_report, cleaned_report, readiness_after


def _per_case_duplicate_summary(audit: list[dict[str, Any]], group_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    grouped_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in audit:
        grouped_entries[str(entry["case_id"])].append(entry)
    for group in group_reports:
        grouped_groups[str(group.get("case_id"))].append(group)
    rows = []
    for case_id in sorted(grouped_entries):
        entries = grouped_entries[case_id]
        action_counts = Counter(entry["action"] for entry in entries)
        group_counts = Counter(group["group_type"] for group in grouped_groups.get(case_id, []))
        rows.append(
            {
                "case_id": case_id,
                "original_candidate_count": len(entries),
                "cleaned_candidate_count": sum(1 for entry in entries if entry["retained_in_cleaned_rows"]),
                "suppressed_candidates": action_counts.get("suppress_exact_duplicate", 0),
                "downgraded_candidates": action_counts.get("downgrade_to_metadata", 0) + action_counts.get("downgrade_to_heading", 0),
                "converted_comparative_candidates": action_counts.get("convert_numeric_to_comparative", 0),
                "conflict_groups": group_counts.get("same_label_conflicting_values", 0),
                "manual_review_groups": group_counts.get("heading_like_duplicate_numeric_fact", 0),
                "text_block_duplicate_groups": group_counts.get("text_block_duplicate", 0),
            }
        )
    return rows


def _top_risky_labels(group_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for group in group_reports:
        if group["group_type"] in {"same_label_conflicting_values", "heading_like_duplicate_numeric_fact"}:
            counter[group.get("normalized_label") or "(blank)"] += int(group.get("candidate_count") or 0)
    return [{"label": label, "count": count} for label, count in counter.most_common(20)]


def render_duplicate_conflict_markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate"]
    lines = [
        "# Feature #13S Extraction v2 Duplicate and Conflict Report",
        "",
        "## Summary",
        "",
        f"- Total candidates analyzed: {aggregate.get('total_candidates_analyzed', 0)}",
        f"- Exact duplicate groups: {aggregate.get('exact_duplicate_groups', 0)}",
        f"- Same label/value duplicate groups: {aggregate.get('same_label_value_duplicate_groups', 0)}",
        f"- Conflicting duplicate groups: {aggregate.get('conflicting_duplicate_groups', 0)}",
        f"- Heading-like duplicate groups: {aggregate.get('heading_like_duplicate_groups', 0)}",
        f"- Date/year label groups: {aggregate.get('date_year_label_groups', 0)}",
        f"- Text-block duplicate groups: {aggregate.get('text_block_duplicate_groups', 0)}",
        f"- Safe suppression count: {aggregate.get('safe_suppression_count', 0)}",
        f"- Downgrade count: {aggregate.get('downgrade_count', 0)}",
        f"- Converted row type count: {aggregate.get('converted_row_type_count', 0)}",
        f"- Conflict review count: {aggregate.get('conflict_review_count', 0)}",
        f"- Manual review required count: {aggregate.get('manual_review_required_count', 0)}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        f"- Live model calls made: {report['run_metadata']['live_huggingface_calls_made'] or report['run_metadata']['live_openai_calls_made']}",
        "",
        "## Per Case",
        "",
        "| Case | Original | Cleaned | Suppressed | Downgraded | Converted | Conflict Groups | Manual Groups |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("per_case_duplicate_conflict_summary", []):
        lines.append(
            "| {case_id} | {original_candidate_count} | {cleaned_candidate_count} | {suppressed_candidates} | {downgraded_candidates} | {converted_comparative_candidates} | {conflict_groups} | {manual_review_groups} |".format(
                **row
            )
        )
    lines.extend(["", "## Top Risky Duplicate Labels", ""])
    lines.extend(f"- {item['label']}: {item['count']}" for item in report.get("top_20_risky_duplicate_labels", []))
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def render_cleaned_candidates_markdown(report: dict[str, Any]) -> str:
    resolution = report["duplicate_resolution"]
    aggregate = report["aggregate_metrics"]
    lines = [
        "# Feature #13S Cleaned Extraction v2 Candidates",
        "",
        "## Summary",
        "",
        f"- Original candidate count: {resolution.get('original_candidate_count', 0)}",
        f"- Cleaned candidate count: {resolution.get('cleaned_candidate_count', 0)}",
        f"- Suppressed count: {resolution.get('suppressed_count', 0)}",
        f"- Downgraded count: {resolution.get('downgraded_count', 0)}",
        f"- Converted row type count: {resolution.get('converted_row_type_count', 0)}",
        f"- Conflict review count: {resolution.get('conflict_review_count', 0)}",
        f"- Manual review count: {resolution.get('manual_review_count', 0)}",
        f"- Row type counts: {aggregate.get('row_type_counts', {})}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        f"- Live model calls made: {report['run_metadata']['live_huggingface_calls_made'] or report['run_metadata']['live_openai_calls_made']}",
        "",
        "## Audit Trail",
        "",
        "The JSON report retains every original candidate with original_candidate_id, proposed row type, action, duplicate groups, and cleaned candidate payload.",
        "",
        "## Limitations",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def render_readiness_after_13s_markdown(report: dict[str, Any]) -> str:
    comparison = report["readiness_comparison"]
    lines = [
        "# Feature #13S Mapping Readiness After Duplicate Control",
        "",
        "## Summary",
        "",
        f"- Overall mapping readiness classification: {report.get('overall_mapping_readiness_classification')}",
        f"- Recommended next feature: {report.get('recommended_next_feature')}",
        f"- Before readiness: {comparison.get('before', {})}",
        f"- After readiness: {comparison.get('after', {})}",
        f"- Delta: {comparison.get('delta', {})}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        "",
        "## Issue Comparison",
        "",
        "| Issue | Before | After | Delta |",
        "| --- | ---: | ---: | ---: |",
    ]
    for issue_name, values in report.get("issue_comparison", {}).items():
        lines.append(f"| {issue_name} | {values.get('before', 0)} | {values.get('after', 0)} | {values.get('delta', 0)} |")
    lines.extend(["", "## Per Case", ""])
    lines.extend([
        "| Case | Original | Cleaned | Suppressed | Downgraded | Converted | Conflicts | After Status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ])
    for row in report.get("per_case", []):
        lines.append(
            "| {case_id} | {original_candidate_count} | {cleaned_candidate_count} | {suppressed_candidates} | {downgraded_candidates} | {converted_comparative_candidates} | {conflict_review_candidates} | {ready_for_mapping_prototype_after_13s} |".format(
                **row
            )
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)
