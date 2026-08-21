"""Build a read-only mapping breadth and sign policy fix-design report."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


DEFAULT_REPORTS_DIR = Path("reports")
SOURCE_REPORT_TEMPLATE = "generated_instance_quality_triage_report_{job_id}.json"
OUTPUT_REPORT_TEMPLATE = "mapping_sign_policy_fix_design_{job_id}.json"
ROW_SAMPLE_LIMIT = 25

BIOLOGICAL_ASSET_CONCEPTS = {
    "ssmt-mpers:CurrentBiologicalAssets",
    "ssmt-mpers:NoncurrentBiologicalAssets",
}
RECEIVABLE_CONCEPTS = {"ifrs-smes:TradeAndOtherCurrentReceivables"}
AGGREGATE_CONCEPT_TERMS = {
    "Assets",
    "CurrentAssets",
    "NoncurrentAssets",
    "Equity",
    "EquityAndLiabilities",
    "Liabilities",
    "RetainedEarnings",
    "OtherComponentsOfEquity",
    "CashAndBankBalances",
}
BIOLOGICAL_LABEL_TERMS = {
    "biological",
    "livestock",
    "plantation",
    "crop",
    "crops",
    "agriculture",
    "agricultural",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a read-only mapping breadth/sign policy design report."
    )
    parser.add_argument("--job-id", type=int, required=True, help="Filing job ID.")
    parser.add_argument(
        "--triage-report",
        type=Path,
        help="Optional #11H triage report. Defaults to reports/generated_instance_quality_triage_report_<job-id>.json.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report JSON.")
    return parser.parse_args()


def load_triage_report(job_id: int, triage_report: Path | None = None) -> dict[str, Any]:
    path = triage_report or DEFAULT_REPORTS_DIR / SOURCE_REPORT_TEMPLATE.format(job_id=job_id)
    if not path.exists():
        raise FileNotFoundError(f"Triage report not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def build_report(job_id: int, triage_report_path: Path | None = None) -> dict[str, Any]:
    triage = load_triage_report(job_id, triage_report_path)
    mapping_problems = build_mapping_breadth_problems(triage)
    sign_policy = build_sign_policy(triage)
    return {
        "job": triage.get("job", {"id": job_id}),
        "xbrl_path": triage.get("xbrl_path"),
        "source_reports": {
            "quality_triage": str(
                triage_report_path
                or DEFAULT_REPORTS_DIR / SOURCE_REPORT_TEMPLATE.format(job_id=job_id)
            ),
            "generated_instance_audit": triage.get("source_audit_report"),
        },
        "scope": {
            "read_only": True,
            "database_modified": False,
            "generated_xbrl_modified": False,
            "mapping_logic_modified": False,
            "extraction_logic_modified": False,
            "does_not_claim_full_mbrs_validation": True,
            "basis": "Feature #11I design only; no mapping, sign, generator, extraction, frontend, route, schema, OpenAI, or taxonomy file changes.",
        },
        "summary": {
            "mapping_problem_concepts": len(mapping_problems),
            "first_safe_mapping_correction_candidates": first_safe_mapping_candidates(mapping_problems),
            "sign_policy_categories": sign_policy["category_counts"],
            "implementation_layer_recommendation": implementation_layer_recommendation(),
            "code_changes_now_justified": True,
            "code_change_justification": (
                "Behavior changes are justified only for the next narrow slice after this design is reviewed: "
                "start with template mapping guardrails for clearly impossible biological-asset matches and "
                "regression checks. This #11I slice itself changes no behavior."
            ),
            "recommended_feature_11j_scope": recommended_feature_11j_scope(),
        },
        "mapping_breadth_problems": mapping_problems,
        "sign_policy": sign_policy,
        "manual_review_requirements": manual_review_requirements(mapping_problems, sign_policy),
        "regression_checks_required": regression_checks_required(),
        "non_goals_honored": [
            "No extraction logic change",
            "No mapping logic change",
            "No generated XBRL output change",
            "No React/frontend change",
            "No DB schema change",
            "No route/download behavior change",
            "No OpenAI or LLM auto-fix",
            "No automatic remapping",
            "No local taxonomy file modification",
            "No full MBRS/FS-MPERS validation claim",
        ],
    }


def build_mapping_breadth_problems(triage: dict[str, Any]) -> list[dict[str, Any]]:
    groups_by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in triage.get("duplicate_concept_context_unit_groups", []):
        groups_by_concept[group.get("concept", "")].append(group)

    identical_by_concept: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in triage.get("identical_duplicate_fact_keys", []):
        identical_by_concept[group.get("concept", "")].append(group)

    problems = []
    for concept, groups in sorted(
        groups_by_concept.items(),
        key=lambda item: (-sum(group.get("generated_fact_count", 0) for group in item[1]), item[0]),
    ):
        source_rows = sorted(
            _unique_rows(row for group in groups for row in group.get("source_rows", [])),
            key=lambda row: (row.get("page_number") or 0, str(row.get("label") or ""), str(row.get("item_id") or "")),
        )
        labels = sorted({str(row.get("label") or "") for row in source_rows if row.get("label")})
        template_labels = sorted(
            {
                str((row.get("template_metadata") or {}).get("label") or "")
                for row in source_rows
                if (row.get("template_metadata") or {}).get("label")
            }
        )
        treatment = recommend_mapping_treatment(concept, labels, groups)
        problems.append(
            {
                "concept": concept,
                "duplicate_group_count": len(groups),
                "generated_fact_count": sum(group.get("generated_fact_count", 0) for group in groups),
                "classification_counts": dict(Counter(group.get("classification") for group in groups)),
                "identical_duplicate_fact_keys": identical_by_concept.get(concept, []),
                "source_labels_currently_mapped": labels,
                "template_labels_seen": template_labels,
                "source_row_count": len(source_rows),
                "source_row_samples": [_compact_row(row) for row in source_rows[:ROW_SAMPLE_LIMIT]],
                "why_likely_too_broad": explain_mapping_problem(concept, labels, groups),
                "recommended_treatment": treatment["recommended_treatment"],
                "treatment_reason": treatment["reason"],
                "implementation_owner": treatment["implementation_owner"],
                "first_safe_correction_candidates": treatment["first_safe_correction_candidates"],
                "rows_that_must_remain_manual_review": rows_for_manual_review(concept, source_rows),
            }
        )
    return problems


def recommend_mapping_treatment(
    concept: str, labels: list[str], groups: list[dict[str, Any]]
) -> dict[str, Any]:
    labels_normalized = [_normalize(label) for label in labels]
    classifications = Counter(group.get("classification") for group in groups)
    if concept in BIOLOGICAL_ASSET_CONCEPTS:
        has_biological_evidence = any(
            any(term in label for term in BIOLOGICAL_LABEL_TERMS) for label in labels_normalized
        )
        if not has_biological_evidence:
            return {
                "recommended_treatment": "blocked_from_auto_mapping",
                "reason": "No source label in the duplicate group contains biological-asset evidence; the rows should not be auto-mapped to biological assets without explicit source support.",
                "implementation_owner": [
                    "template mapping data",
                    "semantic matcher thresholds",
                    "review UI/manual tagging",
                    "regression pack only",
                ],
                "first_safe_correction_candidates": [
                    "Reject automatic matches to this concept unless the source label explicitly contains biological/agricultural evidence.",
                    "Route current job 9 rows under this concept to manual review before any replacement concept is assigned.",
                    "Add regression fixtures proving P&L, share capital, share premium, creditors, accruals, and company names do not map to biological assets.",
                ],
            }
        return {
            "recommended_treatment": "allowed_only_with_high_confidence_or_manual_confirmation",
            "reason": "Biological assets can be valid in FS-MPERS, but repeated same-context facts need strong label evidence or manual confirmation.",
            "implementation_owner": ["template mapping data", "review UI/manual tagging", "regression pack only"],
            "first_safe_correction_candidates": [
                "Keep only label-evidenced biological asset rows eligible for automatic mapping.",
            ],
        }
    if concept in RECEIVABLE_CONCEPTS:
        return {
            "recommended_treatment": "allowed_only_with_high_confidence_or_manual_confirmation",
            "reason": "Company/customer names may be receivable detail rows, but repeated same concept/context/unit facts without dimensions or aggregation policy are not safe to emit blindly.",
            "implementation_owner": [
                "template mapping data",
                "semantic matcher thresholds",
                "review UI/manual tagging",
                "regression pack only",
            ],
            "first_safe_correction_candidates": [
                "Require debtor/receivable context evidence or manual confirmation for customer-name detail rows.",
                "Define whether detail rows should be aggregated, dimensionalized later, or kept out of generated XBRL.",
            ],
        }
    if classifications.get("likely_valid_multi_fact"):
        return {
            "recommended_treatment": "left_unchanged",
            "reason": "The row-level triage did not find an immediate broad-mapping defect for this group.",
            "implementation_owner": ["regression pack only"],
            "first_safe_correction_candidates": [
                "Keep as a regression observation; do not change until a broader dimensional/aggregation policy exists.",
            ],
        }
    if any(term in concept for term in AGGREGATE_CONCEPT_TERMS):
        return {
            "recommended_treatment": "allowed_only_with_high_confidence_or_manual_confirmation",
            "reason": "Aggregate concepts should normally be reserved for labels that exactly represent totals/subtotals, not arbitrary detail rows with the same context and unit.",
            "implementation_owner": [
                "template mapping data",
                "semantic matcher thresholds",
                "review UI/manual tagging",
                "regression pack only",
            ],
            "first_safe_correction_candidates": [
                "Require exact or near-exact total/subtotal label evidence before auto-mapping aggregate concepts.",
                "Manual-review detail rows that currently collapse into aggregate concepts.",
            ],
        }
    return {
        "recommended_treatment": "manual_confirmation_required",
        "reason": "The duplicate group is not safe to correct automatically from current evidence.",
        "implementation_owner": ["review UI/manual tagging", "regression pack only"],
        "first_safe_correction_candidates": [
            "Keep rows manual until a concept-specific rule is approved.",
        ],
    }


def explain_mapping_problem(
    concept: str, labels: list[str], groups: list[dict[str, Any]]
) -> str:
    classifications = Counter(group.get("classification") for group in groups)
    if concept in BIOLOGICAL_ASSET_CONCEPTS:
        return (
            "The taxonomy concept label is Biological assets, but job 9 labels mapped here include "
            f"{_join_sample(labels)}. Those labels are not biological-asset evidence."
        )
    if concept in RECEIVABLE_CONCEPTS:
        return (
            "Many source labels look like customer/vendor detail rows. Even when receivable-like, "
            "emitting many same concept/context/unit facts without dimensions or aggregation policy is semantically weak."
        )
    if classifications.get("likely_valid_multi_fact"):
        return "The duplicate group may be valid, but remains a regression observation because instance_baseline cannot prove semantic correctness."
    return (
        "Distinct source labels collapse into one concept/context/unit group. The first safe move is to tighten auto-mapping eligibility or require manual confirmation."
    )


def build_sign_policy(triage: dict[str, Any]) -> dict[str, Any]:
    rows = triage.get("suspicious_signed_values", [])
    decisions = []
    for row in rows:
        category, rule, should_not_auto = recommend_sign_policy(row)
        decisions.append(
            {
                "item_id": row.get("item_id"),
                "label": row.get("label"),
                "source_value": row.get("source_value"),
                "generated_value": row.get("generated_value"),
                "concept": row.get("concept"),
                "contextRef": row.get("contextRef"),
                "page_number": row.get("page_number"),
                "statement_type": row.get("statement_type"),
                "triage_classification": row.get("sign_classification"),
                "policy_category": category,
                "proposed_rule": rule,
                "should_not_auto_normalize_reason": should_not_auto,
                "template_field_id": row.get("template_field_id"),
            }
        )

    category_counts = Counter(decision["policy_category"] for decision in decisions)
    return {
        "category_counts": dict(sorted(category_counts.items())),
        "policy_categories_defined": {
            "preserve_negative": "Keep the negative amount when the concept/label evidence indicates a deficit, liability, retained loss, or equity reduction.",
            "convert_to_positive": "Convert only after mapping is confirmed and the concept is positive-nature while the source sign appears to be presentation-only.",
            "infer_from_label": "Use explicit label cues such as loss, deficit, depreciation, accumulated depreciation, payable, receivable, or total/subtotal before choosing sign treatment.",
            "manual_review_required": "Do not normalize automatically because mapping and sign evidence conflict or the row is semantically ambiguous.",
            "not_enough_information": "No deterministic label/concept cue is sufficient.",
        },
        "normalization_rules_proposed": [
            "Do not make the XBRL generator silently flip signs; it should continue preserving reviewed numeric values until a reviewed sign policy is stored upstream.",
            "Preserve negative values for loss/deficit/liability/equity-reduction rows when concept and label evidence agree.",
            "Convert to positive only for positive-nature asset/cash/receivable concepts after the mapping is accepted and the source row is confirmed to use presentation-negative notation.",
            "For P&L or retained-loss labels mapped to positive-nature asset concepts, fix or block the mapping first; do not normalize the sign in isolation.",
            "Rows whose labels are company names or detail accounts need manual review or explicit detail-row policy before sign normalization.",
        ],
        "sign_cases_that_should_not_be_auto_normalized": [
            "Rows where the concept is likely wrong, especially biological-asset mappings for P&L/share/equity/creditor/accrual/company-name labels.",
            "Rows where an aggregate/subtotal can legitimately be negative, such as equity, liabilities, retained earnings, and accumulated losses.",
            "Rows where source evidence lacks enough context to distinguish a presentation sign from an accounting sign.",
        ],
        "row_level_decisions": decisions,
    }


def recommend_sign_policy(row: dict[str, Any]) -> tuple[str, str, str | None]:
    classification = row.get("sign_classification")
    concept = str(row.get("concept") or "")
    label = _normalize(row.get("label"))
    if classification == "likely_correct_sign":
        return (
            "preserve_negative",
            "Preserve the negative value because the row-level triage found concept/label evidence consistent with a negative balance.",
            None,
        )
    if classification == "likely_wrong_sign":
        return (
            "convert_to_positive",
            "Convert only after confirming the positive-nature mapping; this is a policy candidate, not an automatic generator rule.",
            "Mapping confirmation is required before sign conversion because a wrong concept can make the sign diagnosis misleading.",
        )
    if classification == "sign_policy_needed":
        if concept in BIOLOGICAL_ASSET_CONCEPTS:
            return (
                "manual_review_required",
                "Resolve the likely mapping defect before considering sign normalization.",
                "Positive-nature biological-asset concept conflicts with labels such as P&L/profit/loss/share/company detail rows.",
            )
        if any(term in label for term in ("loss", "p&l", "profit & loss", "deficit")):
            return (
                "infer_from_label",
                "Infer sign only after the row is mapped to a concept whose balance nature agrees with the loss/profit label.",
                "The current mapping/sign combination is ambiguous.",
            )
        return (
            "manual_review_required",
            "Manual review is required because aggregate/detail sign treatment cannot be inferred safely.",
            "No approved sign policy exists for this row family yet.",
        )
    return (
        "not_enough_information",
        "No deterministic sign policy can be assigned from the current triage evidence.",
        "The row needs more source context.",
    )


def first_safe_mapping_candidates(problems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for problem in problems:
        if problem["concept"] in BIOLOGICAL_ASSET_CONCEPTS:
            candidates.append(
                {
                    "concept": problem["concept"],
                    "recommended_treatment": problem["recommended_treatment"],
                    "reason": problem["treatment_reason"],
                    "sample_labels": problem["source_labels_currently_mapped"][:10],
                }
            )
    if candidates:
        return candidates
    return [
        {
            "concept": problem["concept"],
            "recommended_treatment": problem["recommended_treatment"],
            "reason": problem["treatment_reason"],
            "sample_labels": problem["source_labels_currently_mapped"][:10],
        }
        for problem in problems[:3]
    ]


def rows_for_manual_review(concept: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manual_rows = []
    for row in rows:
        label = _normalize(row.get("label"))
        if concept in BIOLOGICAL_ASSET_CONCEPTS and not any(
            term in label for term in BIOLOGICAL_LABEL_TERMS
        ):
            manual_rows.append(_compact_row(row))
        elif concept in RECEIVABLE_CONCEPTS and not any(
            term in label for term in ("receivable", "debtor", "customer", "trade")
        ):
            manual_rows.append(_compact_row(row))
    return manual_rows[:ROW_SAMPLE_LIMIT]


def manual_review_requirements(
    mapping_problems: list[dict[str, Any]], sign_policy: dict[str, Any]
) -> dict[str, Any]:
    mapping_rows = sum(len(problem["rows_that_must_remain_manual_review"]) for problem in mapping_problems)
    sign_rows = [
        row
        for row in sign_policy["row_level_decisions"]
        if row["policy_category"] in {"manual_review_required", "not_enough_information"}
    ]
    return {
        "mapping_rows_sampled_for_manual_review": mapping_rows,
        "signed_rows_requiring_manual_review": len(sign_rows),
        "manual_review_reason": "Rows with conflicting mapping/sign evidence must not be auto-corrected or auto-normalized from the current evidence.",
    }


def implementation_layer_recommendation() -> dict[str, Any]:
    return {
        "template_mapping_data": "Primary owner for blocking clearly impossible template_field_id assignments and narrowing concept eligibility.",
        "semantic_matcher_thresholds": "Secondary owner for raising confidence requirements around broad or aggregate concepts.",
        "extraction_prompt": "Not first owner; job 9 shows template-backed rows are present, but mappings are too broad.",
        "xbrl_generator_sign_handling": "Not first owner; generator should preserve reviewed values until upstream mapping/sign decisions are explicit.",
        "review_ui_manual_tagging": "Needed for uncertain rows and detail rows that cannot be deterministically mapped.",
        "regression_pack_only": "Required in the same implementation slice to prevent broad concepts from reappearing for known bad labels.",
    }


def regression_checks_required() -> list[str]:
    return [
        "Unit tests for concept guardrails: P&L, share capital, share premium, creditor, accrual, and company-name labels must not auto-map to biological assets.",
        "Fixture or report-based regression for job 9 duplicate groups: CurrentBiologicalAssets duplicate count should fall after approved mapping guardrails.",
        "Sign-policy tests proving likely-correct negative equity/liability/loss rows are preserved.",
        "Sign-policy tests proving positive-nature asset/cash rows are not flipped until mapping confirmation exists.",
        "Generated-instance audit rerun for job 9 after any #11J behavior change.",
        "Arelle instance_baseline rerun for job 9 after any generated-output-affecting change.",
    ]


def recommended_feature_11j_scope() -> str:
    return (
        "Implement the first mapping guardrail slice only: prevent clearly impossible biological-asset auto-matches, "
        "route affected rows to manual review/no automatic concept instead of inventing replacements, add regression tests, "
        "then rerun job 9 generated-instance audit. Defer sign normalization changes until mapping guardrails are verified."
    )


def write_report(report: dict[str, Any], job_id: int) -> Path:
    DEFAULT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DEFAULT_REPORTS_DIR / OUTPUT_REPORT_TEMPLATE.format(job_id=job_id)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def print_summary(report: dict[str, Any], report_path: Path) -> None:
    summary = report["summary"]
    print(f"Mapping/sign policy fix-design report: {report_path}")
    print(f"Job ID: {report['job'].get('id')}")
    print(f"Mapping problem concepts: {summary['mapping_problem_concepts']}")
    print(f"Sign policy categories: {summary['sign_policy_categories']}")
    print(f"Code changes now justified for next slice: {summary['code_changes_now_justified']}")


def _unique_rows(rows: Any) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for row in rows:
        key = row.get("item_id") or (
            row.get("label"),
            row.get("source_value"),
            row.get("template_field_id"),
            row.get("contextRef"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": row.get("item_id"),
        "page_number": row.get("page_number"),
        "label": row.get("label"),
        "source_value": row.get("source_value"),
        "generated_value": row.get("generated_value"),
        "template_field_id": row.get("template_field_id"),
        "confirmed_tag_id": row.get("confirmed_tag_id"),
        "statement_type": row.get("statement_type"),
    }


def _join_sample(values: list[str], limit: int = 8) -> str:
    sample = values[:limit]
    suffix = "" if len(values) <= limit else f", plus {len(values) - limit} more"
    return ", ".join(sample) + suffix


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def main() -> int:
    args = parse_args()
    report = build_report(args.job_id, args.triage_report)
    report_path = write_report(report, args.job_id)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_summary(report, report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
