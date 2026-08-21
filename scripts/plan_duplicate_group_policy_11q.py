"""Read-only policy plan for remaining duplicate generated XBRL fact groups."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_generated_xbrl_instance import (  # noqa: E402
    DEFAULT_REPORTS_DIR,
    ExpectedFact,
    build_report as build_generated_instance_audit,
    default_xbrl_path_for_job,
    expected_facts_for_job,
    load_job,
    parse_xbrl_instance,
)
from services.xbrl_template_service import get_xbrl_template_service  # noqa: E402


DEFAULT_REPORT_TEMPLATE = "reports/duplicate_group_policy_plan_11q_{job_id}.json"
SUMMARY_CONCEPT_LABELS = {
    "assets",
    "current assets",
    "non-current assets",
    "noncurrent assets",
    "current liabilities",
    "liabilities",
    "equity",
    "equity and liabilities",
    "equity attributable to owners of parent",
    "retained earnings",
    "other components of equity",
    "total equity - other components",
    "cash and bank balances",
    "cash and cash equivalents",
}
DETAIL_CUE_TERMS = (
    "other debtor",
    "other debtors",
    "amount due",
    "due from",
    "due to",
    "sdn bhd",
    "sdn. bhd",
    "berhad",
    " bhd",
    "bhd.",
    "ltd",
    "limited",
    "pte ltd",
    "corp",
    "corporation",
)
MAPPING_TOO_BROAD_CUES = (
    "net current assets",
    "financed by",
    "profit & loss",
    "profit and loss",
    "p&l",
    "share capital",
    "share premium",
    "cash",
    "bank",
    "other debtor",
)


@dataclass(frozen=True)
class DuplicateSourceRow:
    item_id: str
    page_id: str | None
    page_number: int | None
    extracted_label: str | None
    extracted_value: str | None
    generated_value: str
    statement_type: str | None
    template_field_id: str | None
    confirmed_tag_id: int | None
    contextRef: str
    unitRef: str
    value_year: int | None
    source_value_column: str


@dataclass(frozen=True)
class DuplicateGroupPlan:
    concept: str
    concept_label: str | None
    contextRef: str
    unitRef: str
    duplicate_fact_count: int
    source_item_ids: list[str]
    extracted_labels: list[str | None]
    extracted_values: list[str | None]
    page_numbers: list[int | None]
    statement_types: list[str | None]
    template_field_ids: list[str | None]
    confirmed_tag_ids: list[int | None]
    survived_after_biological_and_receivables_guardrails: bool
    any_source_row_has_null_template_field_id_after_11l_11p: bool
    generated_values: list[str]
    source_rows: list[dict[str, Any]]
    row_shape_assessment: str
    classification: str
    classification_reason: str
    recommended_future_handling: str
    future_handling_reason: str
    replacement_concept_recommended: bool
    sign_policy_deferred: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only policy plan for duplicate concept/context/unit groups."
    )
    parser.add_argument("--job-id", type=int, required=True, help="Filing job ID to inspect.")
    parser.add_argument(
        "--audit-report",
        type=Path,
        help="Optional generated-instance audit report. Defaults to reports/generated_instance_audit_report_<job-id>.json.",
    )
    parser.add_argument(
        "--triage-report",
        type=Path,
        help="Optional prior row-level triage report for context only.",
    )
    parser.add_argument("--json", action="store_true", help="Print full report JSON.")
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Report path. Defaults to reports/duplicate_group_policy_plan_11q_<job-id>.json.",
    )
    return parser.parse_args()


def normalize_label(label: Any) -> str:
    normalized = re.sub(r"[^a-z0-9&().'\- ]+", " ", str(label or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()


def load_json(path: Path | None) -> dict[str, Any] | None:
    if not path or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def concept_label(concept_id: str) -> str | None:
    info = get_xbrl_template_service().get_concept_info(concept_id) or {}
    return info.get("label") or info.get("name")


def duplicate_groups_from_audit(audit_report: dict[str, Any]) -> list[dict[str, Any]]:
    return (
        audit_report.get("generated_facts", {})
        .get("duplicate_concept_context_unit_facts", {})
        .get("groups", [])
    )


def group_expected_facts_by_duplicate_key(
    expected_facts: Iterable[ExpectedFact],
) -> dict[tuple[str, str, str], list[ExpectedFact]]:
    groups: dict[tuple[str, str, str], list[ExpectedFact]] = defaultdict(list)
    for fact in expected_facts:
        groups[(fact.concept, fact.context_ref, fact.unit_ref)].append(fact)
    return groups


def group_generated_facts_by_duplicate_key(
    generated_facts: Iterable[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in generated_facts:
        unit_ref = fact.get("unitRef") or ""
        if not unit_ref:
            continue
        groups[(fact["concept"], fact.get("contextRef") or "", unit_ref)].append(fact)
    return groups


def source_row_from_fact(fact: ExpectedFact) -> DuplicateSourceRow:
    return DuplicateSourceRow(
        item_id=fact.item_id,
        page_id=fact.page_id,
        page_number=fact.page_number,
        extracted_label=fact.extracted_label,
        extracted_value=fact.extracted_value,
        generated_value=fact.value,
        statement_type=fact.statement_type,
        template_field_id=fact.template_field_id,
        confirmed_tag_id=fact.confirmed_tag_id,
        contextRef=fact.context_ref,
        unitRef=fact.unit_ref,
        value_year=fact.value_year,
        source_value_column=fact.source_value_column,
    )


def labels_are_detail_rows(labels: Sequence[str | None]) -> bool:
    normalized = [f" {normalize_label(label)} " for label in labels]
    return any(any(term in label for term in DETAIL_CUE_TERMS) for label in normalized)


def labels_are_summary_rows(labels: Sequence[str | None], concept: str, label: str | None) -> bool:
    normalized = [normalize_label(candidate) for candidate in labels]
    concept_local = normalize_label(concept.split(":")[-1])
    concept_text = normalize_label(label)
    summary_terms = SUMMARY_CONCEPT_LABELS | {concept_local, concept_text}
    return all(
        candidate in summary_terms
        or candidate.startswith("total ")
        or any(term and candidate == term for term in summary_terms)
        for candidate in normalized
        if candidate
    )


def labels_suggest_broad_mapping(labels: Sequence[str | None], concept: str) -> bool:
    normalized_labels = [normalize_label(label) for label in labels if normalize_label(label)]
    concept_norm = normalize_label(concept)
    if len(set(normalized_labels)) > 1:
        if any(any(cue in label for cue in MAPPING_TOO_BROAD_CUES) for label in normalized_labels):
            return True
    if any("cash" in label or "bank" in label for label in normalized_labels):
        return "cash" not in concept_norm and "bank" not in concept_norm
    return False


def assess_row_shape(labels: Sequence[str | None], values: Sequence[str], concept: str, label: str | None) -> str:
    if labels_are_detail_rows(labels):
        return "detail_rows"
    if labels_are_summary_rows(labels, concept, label):
        return "summary_rows"
    if len(set(normalize_label(item) for item in labels)) == 1:
        return "repeated_extracted_subtotals"
    if labels_suggest_broad_mapping(labels, concept):
        return "mapping_too_broad_rows"
    if len(set(values)) == 1:
        return "repeated_extracted_subtotals"
    return "mixed_or_unclear_rows"


def classify_duplicate_group(
    *,
    concept: str,
    concept_label_value: str | None,
    source_rows: Sequence[DuplicateSourceRow],
    generated_fact_count: int,
) -> tuple[str, str, str, str]:
    labels = [row.extracted_label for row in source_rows]
    values = [row.generated_value for row in source_rows]
    row_shape = assess_row_shape(labels, values, concept, concept_label_value)
    unique_labels = {normalize_label(label) for label in labels}
    unique_values = set(values)

    if not source_rows:
        return (
            "not_enough_information",
            "No traceable source rows were available for this duplicate group.",
            "needs_more_taxonomy_research",
            "The group cannot be classified safely without traceable source row evidence.",
        )
    if row_shape == "detail_rows":
        if "TradeAndOtherCurrentReceivables" in concept:
            return (
                "likely_detail_rows_need_aggregation_policy",
                "Rows look like receivable/debtor detail lines sharing one summary concept/context/unit.",
                "aggregate_before_generation_later",
                "Receivable detail rows should be summed or otherwise handled by an explicit future policy before generation.",
            )
        return (
            "likely_detail_rows_need_dimension_policy",
            "Rows look like detail lines sharing one concept/context/unit and may need dimensional/member modeling.",
            "dimension_model_required_later",
            "Repeated detail rows need an explicit dimensional policy or manual confirmation before same-context generation is trusted.",
        )
    if row_shape == "summary_rows":
        if len(unique_values) == generated_fact_count and generated_fact_count > 1:
            return (
                "likely_summary_duplicate_needs_dedup_policy",
                "Multiple summary/subtotal-looking rows share the same concept/context/unit.",
                "deduplicate_same_context_summary_later",
                "Future generation should choose one authoritative summary fact per concept/context/unit or require manual confirmation.",
            )
        return (
            "likely_valid_multi_fact",
            "The rows look summary-like, but current evidence does not prove which one should be suppressed.",
            "keep_as_is",
            "Keep pending taxonomy/formula review; do not change behavior without a clearer policy.",
        )
    if row_shape == "mapping_too_broad_rows" or len(unique_labels) > 1 and len(unique_values) > 1:
        return (
            "likely_mapping_too_broad",
            "Different labels and values collapse into one broad concept/context/unit.",
            "require_manual_confirmation",
            "This concept should require stronger evidence or manual confirmation before repeated same-context facts are trusted.",
        )
    if row_shape == "repeated_extracted_subtotals":
        return (
            "likely_summary_duplicate_needs_dedup_policy",
            "Repeated subtotal-like evidence shares one concept/context/unit.",
            "deduplicate_same_context_summary_later",
            "A future policy should choose a single authoritative fact or require manual confirmation.",
        )
    return (
        "likely_manual_review_required",
        "Evidence is mixed and does not support an automatic mapping, aggregation, or dimension decision.",
        "require_manual_confirmation",
        "Keep rows manual-review-first until a concept-specific policy is approved.",
    )


def build_group_plans(
    audit_report: dict[str, Any],
    expected_facts: Sequence[ExpectedFact],
    generated_facts: Sequence[dict[str, Any]],
) -> list[DuplicateGroupPlan]:
    expected_groups = group_expected_facts_by_duplicate_key(expected_facts)
    generated_groups = group_generated_facts_by_duplicate_key(generated_facts)
    plans: list[DuplicateGroupPlan] = []

    for group in duplicate_groups_from_audit(audit_report):
        concept = group["concept"]
        context_ref = group["contextRef"]
        unit_ref = group["unitRef"]
        key = (concept, context_ref, unit_ref)
        source_rows = [source_row_from_fact(fact) for fact in expected_groups.get(key, [])]
        generated_values = [str(fact.get("value") or "") for fact in generated_groups.get(key, [])]
        label = concept_label(concept)
        classification, reason, handling, handling_reason = classify_duplicate_group(
            concept=concept,
            concept_label_value=label,
            source_rows=source_rows,
            generated_fact_count=len(generated_values) or int(group.get("count") or 0),
        )
        row_shape = assess_row_shape(
            [row.extracted_label for row in source_rows],
            [row.generated_value for row in source_rows],
            concept,
            label,
        )
        plans.append(
            DuplicateGroupPlan(
                concept=concept,
                concept_label=label,
                contextRef=context_ref,
                unitRef=unit_ref,
                duplicate_fact_count=int(group.get("count") or len(generated_values)),
                source_item_ids=[row.item_id for row in source_rows],
                extracted_labels=[row.extracted_label for row in source_rows],
                extracted_values=[row.extracted_value for row in source_rows],
                page_numbers=[row.page_number for row in source_rows],
                statement_types=sorted({row.statement_type for row in source_rows}),
                template_field_ids=sorted({row.template_field_id for row in source_rows}),
                confirmed_tag_ids=sorted({row.confirmed_tag_id for row in source_rows if row.confirmed_tag_id is not None}),
                survived_after_biological_and_receivables_guardrails=True,
                any_source_row_has_null_template_field_id_after_11l_11p=any(
                    row.template_field_id is None for row in source_rows
                ),
                generated_values=generated_values,
                source_rows=[asdict(row) for row in source_rows],
                row_shape_assessment=row_shape,
                classification=classification,
                classification_reason=reason,
                recommended_future_handling=handling,
                future_handling_reason=handling_reason,
                replacement_concept_recommended=False,
                sign_policy_deferred=True,
            )
        )
    return plans


def summarize(plans: Sequence[DuplicateGroupPlan]) -> dict[str, Any]:
    classification_counts = Counter(plan.classification for plan in plans)
    handling_counts = Counter(plan.recommended_future_handling for plan in plans)
    concept_candidates = sorted(
        plan.concept
        for plan in plans
        if plan.recommended_future_handling in {"require_manual_confirmation", "block_auto_mapping_later"}
        or plan.classification == "likely_mapping_too_broad"
    )
    manual_review_rows = sorted(
        {
            row["item_id"]
            for plan in plans
            if plan.recommended_future_handling in {"require_manual_confirmation", "dimension_model_required_later"}
            for row in plan.source_rows
        }
    )
    return {
        "duplicate_group_count": len(plans),
        "classification_summary": dict(sorted(classification_counts.items())),
        "recommended_future_handling_summary": dict(sorted(handling_counts.items())),
        "future_concept_specific_guardrail_candidates": concept_candidates,
        "manual_review_only_source_item_ids_until_policy": manual_review_rows,
        "true_mapping_quality_problem_count": sum(
            classification_counts.get(key, 0)
            for key in [
                "likely_detail_rows_need_aggregation_policy",
                "likely_detail_rows_need_dimension_policy",
                "likely_mapping_too_broad",
                "likely_summary_duplicate_needs_dedup_policy",
                "likely_manual_review_required",
            ]
        ),
        "possibly_acceptable_multi_fact_group_count": classification_counts.get("likely_valid_multi_fact", 0),
        "sign_policy_remains_deferred": True,
        "immediate_code_change_justified": False,
        "recommended_11r_scope": (
            "Choose one narrow next implementation slice from this report: either a summary duplicate de-duplication policy "
            "for repeated financial-position totals, or a dedicated aggregation/dimension policy design for remaining detail schedules. "
            "Do not implement sign normalization in that slice."
        ),
    }


def build_planning_answers(plans: Sequence[DuplicateGroupPlan]) -> dict[str, Any]:
    return {
        "which_duplicate_groups_are_true_mapping_quality_problems": [
            plan.concept
            for plan in plans
            if plan.classification
            in {
                "likely_mapping_too_broad",
                "likely_detail_rows_need_aggregation_policy",
                "likely_detail_rows_need_dimension_policy",
                "likely_summary_duplicate_needs_dedup_policy",
            }
        ],
        "which_duplicate_groups_may_be_acceptable_multi_fact_outputs": [
            plan.concept for plan in plans if plan.classification == "likely_valid_multi_fact"
        ],
        "which_groups_are_detail_schedules_requiring_aggregation": [
            plan.concept for plan in plans if plan.classification == "likely_detail_rows_need_aggregation_policy"
        ],
        "which_groups_may_require_dimensions": [
            plan.concept for plan in plans if plan.classification == "likely_detail_rows_need_dimension_policy"
        ],
        "which_concepts_are_future_guardrail_candidates": summarize(plans)[
            "future_concept_specific_guardrail_candidates"
        ],
        "rows_manual_review_only_until_policy": summarize(plans)[
            "manual_review_only_source_item_ids_until_policy"
        ],
        "sign_policy_should_remain_deferred_after_11q": True,
    }


def build_policy_report(
    *,
    job_id: int,
    audit_report: dict[str, Any],
    triage_report: dict[str, Any] | None,
    group_plans: Sequence[DuplicateGroupPlan],
    xbrl_path: Path,
    audit_report_path: Path,
    triage_report_path: Path | None,
) -> dict[str, Any]:
    return {
        "feature": "11Q",
        "job_id": job_id,
        "mode": "read_only_planning",
        "read_only": True,
        "database_modified": False,
        "generated_xbrl_modified": False,
        "mapping_behavior_changed": False,
        "aggregation_implemented": False,
        "dimensions_implemented": False,
        "sign_normalization_implemented": False,
        "replacement_concepts_assigned": False,
        "full_mbrs_validation_claimed": False,
        "xbrl_path": str(xbrl_path),
        "source_reports": {
            "generated_instance_audit_report": str(audit_report_path),
            "generated_instance_quality_triage_report": str(triage_report_path) if triage_report_path else None,
            "triage_report_loaded": triage_report is not None,
        },
        "current_job_9_state": {
            "generated_facts": audit_report.get("generated_facts", {}).get("total_generated_facts"),
            "expected_extracted_facts": audit_report.get("coverage", {}).get("expected_generated_fact_count"),
            "represented_expected_extracted_facts": audit_report.get("coverage", {}).get("represented_expected_fact_count"),
            "duplicate_concept_context_unit_groups": len(group_plans),
            "identical_duplicate_fact_groups": audit_report.get("generated_facts", {})
            .get("concepts_multiple_times_identical_value_context_unit", {})
            .get("group_count"),
            "suspicious_signed_values": audit_report.get("extracted_rows", {})
            .get("suspicious_signed_values_carried_into_xbrl", {})
            .get("count"),
            "missing_context_refs": audit_report.get("context_unit_summary", {})
            .get("contexts", {})
            .get("missing_context_refs", []),
            "missing_unit_refs": audit_report.get("context_unit_summary", {})
            .get("units", {})
            .get("missing_unit_refs", []),
        },
        "summary": summarize(group_plans),
        "planning_answers": build_planning_answers(group_plans),
        "policy_constraints": {
            "do_not_invent_replacement_concepts": True,
            "do_not_aggregate_in_11q": True,
            "do_not_create_dimensions_in_11q": True,
            "do_not_mutate_persisted_rows": True,
            "do_not_change_generator_output": True,
            "do_not_normalize_signs": True,
            "future_aggregation_or_dimension_work_requires_explicit_slice": True,
        },
        "duplicate_groups": [asdict(plan) for plan in group_plans],
    }


async def build_report(
    job_id: int,
    audit_report_path: Path | None = None,
    triage_report_path: Path | None = None,
) -> dict[str, Any]:
    job = await load_job(job_id)
    resolved_audit_path = audit_report_path or DEFAULT_REPORTS_DIR / f"generated_instance_audit_report_{job_id}.json"
    audit_report = load_json(resolved_audit_path)
    if audit_report is None:
        audit_report = await build_generated_instance_audit(job_id)
    triage_report = load_json(triage_report_path) if triage_report_path else load_json(
        DEFAULT_REPORTS_DIR / f"generated_instance_quality_triage_report_{job_id}.json"
    )
    resolved_triage_path = triage_report_path or DEFAULT_REPORTS_DIR / f"generated_instance_quality_triage_report_{job_id}.json"
    xbrl_path = Path(audit_report.get("xbrl_path") or default_xbrl_path_for_job(job))
    parsed = parse_xbrl_instance(xbrl_path)
    expected_facts = expected_facts_for_job(job)
    group_plans = build_group_plans(audit_report, expected_facts, parsed["facts"])
    return build_policy_report(
        job_id=job_id,
        audit_report=audit_report,
        triage_report=triage_report,
        group_plans=group_plans,
        xbrl_path=xbrl_path,
        audit_report_path=resolved_audit_path,
        triage_report_path=resolved_triage_path if triage_report else None,
    )


def write_report(report: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def render_console_report(report: dict[str, Any]) -> str:
    lines = [
        "Feature #11Q duplicate group policy plan",
        f"job_id: {report['job_id']}",
        f"duplicate_groups: {report['summary']['duplicate_group_count']}",
        f"classification_summary: {report['summary']['classification_summary']}",
        f"recommended_future_handling_summary: {report['summary']['recommended_future_handling_summary']}",
        f"database_modified: {report['database_modified']}",
        f"generated_xbrl_modified: {report['generated_xbrl_modified']}",
        "",
        "Groups:",
    ]
    for group in report["duplicate_groups"]:
        lines.append(
            "  - "
            f"{group['concept']} "
            f"count={group['duplicate_fact_count']} "
            f"classification={group['classification']} "
            f"future={group['recommended_future_handling']}"
        )
    return "\n".join(lines)


async def async_main() -> int:
    args = parse_args()
    report = await build_report(args.job_id, args.audit_report, args.triage_report)
    report_path = args.report_path or Path(DEFAULT_REPORT_TEMPLATE.format(job_id=args.job_id))
    write_report(report, report_path)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_console_report(report))
        print(f"\nReport saved: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
