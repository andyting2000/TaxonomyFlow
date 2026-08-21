"""Read-only design and simulation for summary duplicate de-duplication policy."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Sequence


DEFAULT_DUPLICATE_PLAN_TEMPLATE = "reports/duplicate_group_policy_plan_11q_{job_id}.json"
DEFAULT_AUDIT_REPORT_TEMPLATE = "reports/generated_instance_audit_report_{job_id}.json"
DEFAULT_REPORT_TEMPLATE = "reports/summary_duplicate_dedup_policy_design_11r_{job_id}.json"
TARGET_11Q_CLASSIFICATION = "likely_summary_duplicate_needs_dedup_policy"
TOTAL_TERMS = ("total", "totals")
SUBTOTAL_TERMS = ("subtotal", "sub-total", "current liabilities", "profit & loss", "profit and loss")
GENERIC_HEADING_TERMS = ("liabilities", "current liabilities", "retained earnings")


@dataclass(frozen=True)
class SummaryDedupRow:
    item_id: str
    page_id: str | None
    page_number: int | None
    extracted_label: str | None
    extracted_value: str | None
    normalized_value: str | None
    generated_value: str | None
    statement_type: str | None
    template_field_id: str | None
    confirmed_tag_id: int | None
    label_role: str
    future_selection_rank: int
    future_selection_reason: str


@dataclass(frozen=True)
class SummaryDedupGroup:
    concept: str
    concept_label: str | None
    contextRef: str
    unitRef: str
    duplicate_fact_count: int
    source_item_ids: list[str]
    extracted_labels: list[str | None]
    extracted_values: list[str | None]
    normalized_values: list[str | None]
    page_numbers: list[int | None]
    statement_types: list[str | None]
    template_field_ids: list[str | None]
    confirmed_tag_ids: list[int | None]
    values_are_identical: bool
    values_are_conflicting: bool
    labels_assessment: str
    safe_to_deduplicate_later: bool
    manual_review_required_before_implementation: bool
    classification: str
    classification_reason: str
    recommended_future_handling: str
    future_handling_reason: str
    proposed_keep_item_id: str | None
    proposed_suppress_item_ids: list[str]
    proposed_future_selection_rule: dict[str, Any]
    replacement_concept_recommended: bool
    aggregation_recommended: bool
    dimension_recommended: bool
    sign_normalization_recommended: bool
    source_rows: list[dict[str, Any]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Design a read-only summary duplicate de-duplication policy simulation."
    )
    parser.add_argument("--job-id", type=int, required=True, help="Filing job ID to inspect.")
    parser.add_argument(
        "--duplicate-plan-report",
        type=Path,
        help="Optional Feature #11Q duplicate policy report path.",
    )
    parser.add_argument(
        "--audit-report",
        type=Path,
        help="Optional generated-instance audit report path.",
    )
    parser.add_argument("--json", action="store_true", help="Print full report JSON.")
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Report path. Defaults to reports/summary_duplicate_dedup_policy_design_11r_<job-id>.json.",
    )
    return parser.parse_args()


def normalize_label(label: Any) -> str:
    normalized = re.sub(r"[^a-z0-9&().'\- ]+", " ", str(label or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()


def normalize_numeric_value(value: Any) -> str | None:
    text = str(value or "").replace(",", "").replace(" ", "").strip()
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    text = re.sub(r"[^\d.-]", "", text)
    if not text or text in {"-", ".", "-."}:
        return None
    try:
        decimal = Decimal(text)
    except InvalidOperation:
        return None
    return format(decimal, "f")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def target_summary_groups(duplicate_plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        group
        for group in duplicate_plan.get("duplicate_groups", [])
        if group.get("classification") == TARGET_11Q_CLASSIFICATION
    ]


def classify_label_role(label: str | None, concept_label: str | None) -> str:
    normalized = normalize_label(label)
    concept_normalized = normalize_label(concept_label)
    if not normalized:
        return "not_enough_information"
    if any(term in normalized for term in TOTAL_TERMS):
        return "total"
    if any(term in normalized for term in SUBTOTAL_TERMS):
        return "subtotal"
    if normalized in GENERIC_HEADING_TERMS:
        return "generic_heading"
    if concept_normalized and normalized == concept_normalized:
        return "exact_summary_label"
    return "ambiguous_summary"


def classify_labels(rows: Sequence[SummaryDedupRow]) -> str:
    roles = {row.label_role for row in rows}
    if roles <= {"exact_summary_label"}:
        return "exact_summary_labels"
    if "subtotal" in roles and ("total" in roles or "exact_summary_label" in roles or "generic_heading" in roles):
        return "subtotal_vs_total_or_heading_ambiguous"
    if "generic_heading" in roles and ("exact_summary_label" in roles or "total" in roles):
        return "generic_heading_with_explicit_summary"
    if roles <= {"generic_heading", "exact_summary_label"}:
        return "repeated_heading_or_layout_noise"
    return "mixed_summary_evidence"


def rank_row_for_future_selection(row: SummaryDedupRow, concept_label: str | None) -> tuple[int, str]:
    if row.confirmed_tag_id is not None:
        return 0, "manual confirmed tag would be preferred if future policy allows automatic selection"
    if row.label_role == "exact_summary_label":
        return 1, "exact concept summary label is preferred over generic heading"
    if row.label_role == "total":
        return 2, "explicit total label is preferred over subtotal/detail label"
    if row.label_role == "generic_heading":
        return 3, "generic heading is lower confidence than exact or total label"
    if row.label_role == "subtotal":
        return 4, "subtotal/current-section label is not preferred over total summary"
    return 5, "ambiguous label is not preferred"


def build_rows(group: dict[str, Any]) -> list[SummaryDedupRow]:
    rows = []
    concept_label = group.get("concept_label")
    for source in group.get("source_rows", []):
        normalized_value = normalize_numeric_value(source.get("generated_value") or source.get("extracted_value"))
        role = classify_label_role(source.get("extracted_label"), concept_label)
        placeholder = SummaryDedupRow(
            item_id=source.get("item_id"),
            page_id=source.get("page_id"),
            page_number=source.get("page_number"),
            extracted_label=source.get("extracted_label"),
            extracted_value=source.get("extracted_value"),
            normalized_value=normalized_value,
            generated_value=source.get("generated_value"),
            statement_type=source.get("statement_type"),
            template_field_id=source.get("template_field_id"),
            confirmed_tag_id=source.get("confirmed_tag_id"),
            label_role=role,
            future_selection_rank=99,
            future_selection_reason="",
        )
        rank, reason = rank_row_for_future_selection(placeholder, concept_label)
        rows.append(
            SummaryDedupRow(
                **{
                    **asdict(placeholder),
                    "future_selection_rank": rank,
                    "future_selection_reason": reason,
                }
            )
        )
    return rows


def classify_group(rows: Sequence[SummaryDedupRow]) -> tuple[str, str, str, str, bool]:
    values = [row.normalized_value for row in rows if row.normalized_value is not None]
    unique_values = set(values)
    labels_assessment = classify_labels(rows)
    values_identical = len(unique_values) == 1 and len(values) == len(rows)
    values_conflicting = len(unique_values) > 1

    if values_identical and labels_assessment in {"exact_summary_labels", "repeated_heading_or_layout_noise"}:
        return (
            "safe_identical_summary_duplicate",
            "All duplicate rows have the same normalized value and summary/heading labels.",
            "deduplicate_keep_one_later",
            "A future generator policy could keep the best-ranked row because values are identical.",
            False,
        )
    if values_conflicting:
        if labels_assessment == "subtotal_vs_total_or_heading_ambiguous":
            return (
                "subtotal_vs_total_ambiguous",
                "Values conflict and labels mix subtotal/current-section wording with total or heading evidence.",
                "require_manual_confirmation_later",
                "Do not choose automatically when values conflict and subtotal/total meaning is ambiguous.",
                True,
            )
        return (
            "conflicting_summary_duplicate_requires_manual_review",
            "Values conflict across rows sharing one concept/context/unit.",
            "require_manual_confirmation_later",
            "Do not choose automatically when values conflict.",
            True,
        )
    if labels_assessment == "repeated_heading_or_layout_noise":
        return (
            "repeated_heading_or_layout_noise",
            "Labels look like repeated headings, but current evidence is not enough to alter output.",
            "needs_more_taxonomy_or_presentation_research",
            "Research presentation/layout source before generator de-duplication.",
            True,
        )
    return (
        "not_safe_to_deduplicate",
        "Current evidence does not satisfy the future safe de-duplication rule.",
        "do_not_deduplicate",
        "Keep current behavior until manual review or a narrower rule is approved.",
        True,
    )


def proposed_future_selection_rule() -> dict[str, Any]:
    return {
        "policy_status": "design_only_not_implemented",
        "only_apply_when": [
            "concept, contextRef, and unitRef are identical",
            "rows are summary/heading duplicates, not detail schedules",
            "all duplicate normalized values are identical",
            "no row has conflicting manual confirmation evidence",
        ],
        "selection_preferences": [
            "prefer reviewed/manual-confirmed row if available",
            "prefer exact summary label match over generic heading",
            "prefer explicit total label over subtotal/detail label",
            "prefer same value only when all duplicates are identical",
        ],
        "never_auto_choose_when": [
            "values conflict",
            "labels are ambiguous",
            "one row appears to be subtotal and another appears to be total",
            "deduplication would require sign normalization",
            "deduplication would require aggregation or dimensions",
        ],
        "replacement_concepts": "never assign replacement concepts",
    }


def build_group_design(group: dict[str, Any]) -> SummaryDedupGroup:
    rows = build_rows(group)
    classification, reason, handling, handling_reason, manual_required = classify_group(rows)
    values = [row.normalized_value for row in rows if row.normalized_value is not None]
    values_identical = len(set(values)) == 1 and len(values) == len(rows)
    values_conflicting = len(set(values)) > 1
    safe = classification == "safe_identical_summary_duplicate"
    ranked_rows = sorted(rows, key=lambda row: (row.future_selection_rank, row.page_number or 0, row.item_id))
    keep_item_id = ranked_rows[0].item_id if safe and ranked_rows else None
    suppress_item_ids = [row.item_id for row in ranked_rows[1:]] if keep_item_id else []
    return SummaryDedupGroup(
        concept=group.get("concept"),
        concept_label=group.get("concept_label"),
        contextRef=group.get("contextRef"),
        unitRef=group.get("unitRef"),
        duplicate_fact_count=group.get("duplicate_fact_count", len(rows)),
        source_item_ids=[row.item_id for row in rows],
        extracted_labels=[row.extracted_label for row in rows],
        extracted_values=[row.extracted_value for row in rows],
        normalized_values=[row.normalized_value for row in rows],
        page_numbers=[row.page_number for row in rows],
        statement_types=sorted({row.statement_type for row in rows}),
        template_field_ids=sorted({row.template_field_id for row in rows}),
        confirmed_tag_ids=sorted({row.confirmed_tag_id for row in rows if row.confirmed_tag_id is not None}),
        values_are_identical=values_identical,
        values_are_conflicting=values_conflicting,
        labels_assessment=classify_labels(rows),
        safe_to_deduplicate_later=safe,
        manual_review_required_before_implementation=manual_required,
        classification=classification,
        classification_reason=reason,
        recommended_future_handling=handling,
        future_handling_reason=handling_reason,
        proposed_keep_item_id=keep_item_id,
        proposed_suppress_item_ids=suppress_item_ids,
        proposed_future_selection_rule=proposed_future_selection_rule(),
        replacement_concept_recommended=False,
        aggregation_recommended=False,
        dimension_recommended=False,
        sign_normalization_recommended=False,
        source_rows=[asdict(row) for row in rows],
    )


def summarize(groups: Sequence[SummaryDedupGroup]) -> dict[str, Any]:
    classification_counts = Counter(group.classification for group in groups)
    handling_counts = Counter(group.recommended_future_handling for group in groups)
    safe_groups = [group.concept for group in groups if group.safe_to_deduplicate_later]
    manual_groups = [group.concept for group in groups if group.manual_review_required_before_implementation]
    return {
        "target_group_count": len(groups),
        "classification_summary": dict(sorted(classification_counts.items())),
        "recommended_future_handling_summary": dict(sorted(handling_counts.items())),
        "safe_for_future_generator_level_deduplication_count": len(safe_groups),
        "safe_for_future_generator_level_deduplication": safe_groups,
        "manual_review_required_group_count": len(manual_groups),
        "manual_review_required_groups": manual_groups,
        "future_generator_deduplication_is_safe_now": len(safe_groups) == len(groups) and bool(groups),
        "sign_policy_remains_deferred": True,
        "recommended_11s_scope": (
            "Do not implement automatic summary de-duplication for these job 9 groups yet because all target groups have "
            "conflicting values or subtotal/total ambiguity. Feature #11S should either design a manual confirmation workflow "
            "for conflicting summary duplicates or move to the mapping-too-broad guardrail planning track."
        ),
    }


def build_report(
    job_id: int,
    duplicate_plan_report: Path | None = None,
    audit_report: Path | None = None,
) -> dict[str, Any]:
    duplicate_path = duplicate_plan_report or Path(DEFAULT_DUPLICATE_PLAN_TEMPLATE.format(job_id=job_id))
    audit_path = audit_report or Path(DEFAULT_AUDIT_REPORT_TEMPLATE.format(job_id=job_id))
    duplicate_plan = load_json(duplicate_path)
    audit = load_json(audit_path) if audit_path.exists() else {}
    group_designs = [build_group_design(group) for group in target_summary_groups(duplicate_plan)]
    report_groups = [asdict(group) for group in group_designs]
    return {
        "feature": "11R",
        "job_id": job_id,
        "mode": "read_only_design_and_dry_run_simulation",
        "read_only": True,
        "database_modified": False,
        "generated_xbrl_modified": False,
        "mapping_behavior_changed": False,
        "deduplication_implemented": False,
        "aggregation_implemented": False,
        "dimensions_implemented": False,
        "sign_normalization_implemented": False,
        "replacement_concepts_assigned": False,
        "full_mbrs_validation_claimed": False,
        "target_11q_classification": TARGET_11Q_CLASSIFICATION,
        "target_concepts": [group.concept for group in group_designs],
        "source_reports": {
            "duplicate_group_policy_plan_11q": str(duplicate_path),
            "generated_instance_audit_report": str(audit_path),
        },
        "current_job_9_state": {
            "generated_facts": audit.get("generated_facts", {}).get("total_generated_facts"),
            "expected_extracted_facts": audit.get("coverage", {}).get("expected_generated_fact_count"),
            "represented_expected_extracted_facts": audit.get("coverage", {}).get("represented_expected_fact_count"),
            "duplicate_concept_context_unit_groups": audit.get("generated_facts", {})
            .get("duplicate_concept_context_unit_facts", {})
            .get("group_count"),
            "identical_duplicate_fact_groups": audit.get("generated_facts", {})
            .get("concepts_multiple_times_identical_value_context_unit", {})
            .get("group_count"),
            "suspicious_signed_values": audit.get("extracted_rows", {})
            .get("suspicious_signed_values_carried_into_xbrl", {})
            .get("count"),
        },
        "summary": summarize(group_designs),
        "policy_answers": {
            "are_the_3_groups_safe_to_deduplicate_later": summarize(group_designs)[
                "future_generator_deduplication_is_safe_now"
            ],
            "which_rows_would_be_kept": {
                group.concept: group.proposed_keep_item_id for group in group_designs
            },
            "which_rows_would_be_suppressed": {
                group.concept: group.proposed_suppress_item_ids for group in group_designs
            },
            "any_values_conflicting": any(group.values_are_conflicting for group in group_designs),
            "manual_review_required_before_implementation": any(
                group.manual_review_required_before_implementation for group in group_designs
            ),
            "safest_future_generator_level_rule": proposed_future_selection_rule(),
            "tests_required_before_implementation": [
                "identical summary duplicates keep one and suppress the rest",
                "conflicting values are never auto-deduplicated",
                "subtotal versus total ambiguity requires manual review",
                "generic headings are not preferred over exact summary or total labels",
                "confirmed/manual tag precedence is respected",
                "no aggregation, dimensions, sign normalization, or replacement concepts are introduced",
            ],
            "sign_normalization_should_remain_deferred": True,
        },
        "policy_constraints": {
            "do_not_implement_deduplication_in_11r": True,
            "do_not_remove_facts": True,
            "do_not_mutate_persisted_rows": True,
            "do_not_normalize_signs": True,
            "do_not_aggregate_values": True,
            "do_not_create_dimensions": True,
            "do_not_infer_replacement_concepts": True,
        },
        "groups": report_groups,
    }


def write_report(report: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def render_console_report(report: dict[str, Any]) -> str:
    lines = [
        "Feature #11R summary duplicate de-dup policy design",
        f"job_id: {report['job_id']}",
        f"target_groups: {report['summary']['target_group_count']}",
        f"classification_summary: {report['summary']['classification_summary']}",
        f"future_generator_deduplication_is_safe_now: {report['summary']['future_generator_deduplication_is_safe_now']}",
        f"database_modified: {report['database_modified']}",
        f"generated_xbrl_modified: {report['generated_xbrl_modified']}",
        "",
        "Groups:",
    ]
    for group in report["groups"]:
        lines.append(
            "  - "
            f"{group['concept']} "
            f"count={group['duplicate_fact_count']} "
            f"classification={group['classification']} "
            f"future={group['recommended_future_handling']} "
            f"safe={group['safe_to_deduplicate_later']}"
        )
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    report = build_report(args.job_id, args.duplicate_plan_report, args.audit_report)
    report_path = args.report_path or Path(DEFAULT_REPORT_TEMPLATE.format(job_id=args.job_id))
    write_report(report, report_path)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_console_report(report))
        print(f"\nReport saved: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
