"""Read-only row-level triage for generated XBRL quality findings."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_generated_xbrl_instance import (  # noqa: E402
    DEFAULT_REPORTS_DIR,
    ExpectedFact,
    default_xbrl_path_for_job,
    expected_facts_for_job,
    load_job,
    parse_xbrl_instance,
)


POSITIVE_NATURE_CONCEPT_TERMS = {
    "assets",
    "cash",
    "receivables",
    "equipment",
    "biologicalassets",
}
NEGATIVE_LABEL_TERMS = {
    "loss",
    "deficit",
    "depreciation",
    "amortisation",
    "amortization",
    "impairment",
    "liabilit",
    "payable",
    "financed by",
    "retained earnings",
    "p&l",
    "profit & loss",
}
AGGREGATE_LABEL_TERMS = {
    "total",
    "assets",
    "liabilities",
    "equity",
    "current assets",
    "non-current assets",
    "net current assets",
    "financed by",
}
SAMPLE_LIMIT = 50


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Triage generated XBRL duplicate and signed-value quality findings."
    )
    parser.add_argument("--job-id", type=int, required=True, help="Filing job ID to triage.")
    parser.add_argument(
        "--audit-report",
        type=Path,
        help="Optional #11G audit report path. Defaults to reports/generated_instance_audit_report_<job-id>.json.",
    )
    parser.add_argument("--json", action="store_true", help="Print the full report JSON.")
    return parser.parse_args()


def load_audit_report(job_id: int, audit_report: Path | None) -> dict[str, Any]:
    path = audit_report or DEFAULT_REPORTS_DIR / f"generated_instance_audit_report_{job_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Audit report not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_template_concepts(path: Path = Path("mpers_templates.json")) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    concepts: dict[str, dict[str, Any]] = {}
    templates = data.get("templates", [])
    if isinstance(templates, dict):
        templates = templates.values()
    for template in templates:
        if not isinstance(template, dict):
            continue
        template_code = template.get("code")
        template_description = template.get("description")
        for concept in template.get("concepts", []):
            concept_id = concept.get("concept_id") or concept.get("id")
            if concept_id:
                concepts[concept_id] = {
                    "template_code": template_code,
                    "template_description": template_description,
                    "label": concept.get("label"),
                    "data_type": concept.get("data_type"),
                    "level": concept.get("level"),
                    "is_abstract": concept.get("is_abstract"),
                    "required": concept.get("required"),
                    "position": concept.get("position"),
                    "parent": concept.get("parent"),
                }
    return concepts


def fact_to_row(fact: ExpectedFact, template_concepts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    template_metadata = template_concepts.get(fact.template_field_id or "")
    return {
        "item_id": fact.item_id,
        "page_number": fact.page_number,
        "label": fact.extracted_label,
        "source_value": fact.extracted_value,
        "generated_value": fact.value,
        "template_field_id": fact.template_field_id,
        "confirmed_tag_id": fact.confirmed_tag_id,
        "statement_type": fact.statement_type,
        "concept": fact.concept,
        "contextRef": fact.context_ref,
        "unitRef": fact.unit_ref,
        "source_value_column": fact.source_value_column,
        "value_year": fact.value_year,
        "template_metadata": template_metadata,
    }


def group_expected_facts_by_duplicate_key(
    expected_facts: list[ExpectedFact],
) -> dict[tuple[str, str, str], list[ExpectedFact]]:
    groups: dict[tuple[str, str, str], list[ExpectedFact]] = defaultdict(list)
    for fact in expected_facts:
        groups[(fact.concept, fact.context_ref, fact.unit_ref)].append(fact)
    return {key: values for key, values in groups.items() if len(values) > 1}


def group_generated_facts_by_duplicate_key(
    generated_facts: list[dict[str, Any]],
) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in generated_facts:
        unit_ref = fact.get("unitRef") or ""
        if not unit_ref:
            continue
        groups[(fact["concept"], fact.get("contextRef") or "", unit_ref)].append(fact)
    return {key: values for key, values in groups.items() if len(values) > 1}


def classify_duplicate_group(source_facts: list[ExpectedFact], generated_facts: list[dict[str, Any]]) -> str:
    item_ids = [fact.item_id for fact in source_facts]
    labels = [_normalize(fact.extracted_label) for fact in source_facts]
    values = [fact.value for fact in source_facts]
    value_counts = Counter(values)
    label_value_counts = Counter((label, value) for label, value in zip(labels, values))

    if len(generated_facts) > len(source_facts):
        return "likely_generator_duplicate"
    if len(set(item_ids)) < len(item_ids):
        return "likely_generator_duplicate"
    if any(count > 1 for count in label_value_counts.values()):
        return "likely_extraction_duplicate"
    if len(set(labels)) > 1 and len(set(values)) > 1:
        return "likely_mapping_too_broad"
    if any(count > 1 for count in value_counts.values()):
        return "needs_manual_review"
    return "likely_valid_multi_fact"


def duplicate_classification_reason(classification: str) -> str:
    return {
        "likely_valid_multi_fact": "Multiple source rows share the same concept/context/unit but do not look duplicated by label or value; manual taxonomy review is still needed because no dimensions distinguish them.",
        "likely_mapping_too_broad": "Distinct source labels and values collapse into one concept/context/unit group, suggesting the chosen concept is too broad or dimensions are missing.",
        "likely_extraction_duplicate": "At least two source rows share the same label and value for the same generated fact key.",
        "likely_generator_duplicate": "Generated fact count exceeds traceable source facts, or one source item appears more than once for the same key.",
        "needs_manual_review": "The group has repeated values or otherwise ambiguous evidence that needs row-level review.",
    }[classification]


def triage_duplicate_groups(
    expected_facts: list[ExpectedFact],
    generated_facts: list[dict[str, Any]],
    audit_report: dict[str, Any],
    template_concepts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    expected_groups = group_expected_facts_by_duplicate_key(expected_facts)
    generated_groups = group_generated_facts_by_duplicate_key(generated_facts)
    audit_groups = audit_report["generated_facts"]["duplicate_concept_context_unit_facts"]["groups"]
    results = []

    for group in audit_groups:
        key = (group["concept"], group["contextRef"], group["unitRef"])
        source_facts = expected_groups.get(key, [])
        actual_generated = generated_groups.get(key, [])
        classification = classify_duplicate_group(source_facts, actual_generated)
        generated_values = [fact.get("value") for fact in actual_generated]
        results.append(
            {
                "concept": group["concept"],
                "contextRef": group["contextRef"],
                "unitRef": group["unitRef"],
                "generated_fact_count": len(actual_generated),
                "traceable_source_fact_count": len(source_facts),
                "generated_values": generated_values,
                "unique_generated_values": sorted(set(generated_values)),
                "source_rows": [fact_to_row(fact, template_concepts) for fact in source_facts],
                "classification": classification,
                "classification_reason": duplicate_classification_reason(classification),
            }
        )
    return results


def triage_identical_duplicate_keys(
    expected_facts: list[ExpectedFact],
    generated_facts: list[dict[str, Any]],
    audit_report: dict[str, Any],
    template_concepts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    expected_by_key: dict[tuple[str, str, str, str], list[ExpectedFact]] = defaultdict(list)
    for fact in expected_facts:
        expected_by_key[fact.match_key].append(fact)
    generated_by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for fact in generated_facts:
        generated_by_key[
            (
                fact["concept"],
                fact.get("contextRef") or "",
                fact.get("unitRef") or "",
                fact.get("value") or "",
            )
        ].append(fact)

    results = []
    for group in audit_report["generated_facts"]["concepts_multiple_times_identical_value_context_unit"]["groups"]:
        key = (group["concept"], group["contextRef"], group["unitRef"], group["value"])
        source_facts = expected_by_key.get(key, [])
        actual_generated = generated_by_key.get(key, [])
        label_value_pairs = Counter(
            (_normalize(fact.extracted_label), fact.extracted_value, fact.template_field_id)
            for fact in source_facts
        )
        generator_duplicate = len(actual_generated) > len(source_facts) or len({fact.item_id for fact in source_facts}) < len(source_facts)
        source_rows_duplicated = any(count > 1 for count in label_value_pairs.values())
        mapping_too_broad = len(source_facts) > 1 and len(label_value_pairs) > 1
        results.append(
            {
                "concept": group["concept"],
                "contextRef": group["contextRef"],
                "unitRef": group["unitRef"],
                "value": group["value"],
                "generated_fact_count": len(actual_generated),
                "traceable_source_fact_count": len(source_facts),
                "source_rows_duplicated": source_rows_duplicated,
                "generator_emitted_same_fact_twice_from_one_source_row": generator_duplicate,
                "all_rows_share_same_label_value_template_context_unit": len(label_value_pairs) == 1,
                "source_rows": [fact_to_row(fact, template_concepts) for fact in source_facts],
                "classification": "likely_generator_duplicate"
                if generator_duplicate
                else "likely_extraction_duplicate"
                if source_rows_duplicated
                else "likely_mapping_too_broad"
                if mapping_too_broad
                else "needs_manual_review",
            }
        )
    return results


def classify_signed_value(fact: ExpectedFact) -> tuple[str, str]:
    label = _normalize(fact.extracted_label)
    concept = _normalize(fact.concept)
    value = fact.value
    has_negative_label = any(term in label for term in NEGATIVE_LABEL_TERMS)
    positive_nature = any(term in concept for term in POSITIVE_NATURE_CONCEPT_TERMS)
    aggregate_label = any(term in label for term in AGGREGATE_LABEL_TERMS)

    if not value.startswith("-"):
        return "needs_manual_review", "Flagged source value is not negative after generator normalization."
    if positive_nature and not has_negative_label:
        return "likely_wrong_sign", "Negative value is attached to a positive-nature asset/cash/receivable concept without a loss, contra, liability, or equity label cue."
    if has_negative_label and not positive_nature:
        return "likely_correct_sign", "Negative value has a loss, liability, equity, retained earnings, or comparable label cue and the concept is not obviously positive-nature."
    if has_negative_label and positive_nature:
        return "sign_policy_needed", "Negative source label cue exists, but it is mapped to a positive-nature concept; sign and mapping policy need row-level review together."
    if aggregate_label:
        return "sign_policy_needed", "Negative aggregate/subtotal value may be valid, but the project needs a sign policy before normalization changes."
    return "needs_manual_review", "No deterministic sign cue was strong enough to classify the row."


def triage_signed_values(
    expected_facts: list[ExpectedFact],
    template_concepts: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    results = []
    for fact in expected_facts:
        if not fact.signed_value_suspicious:
            continue
        classification, reason = classify_signed_value(fact)
        row = fact_to_row(fact, template_concepts)
        row.update(
            {
                "reason_flagged": "Source value contains a leading minus sign or accounting-parentheses pattern.",
                "sign_classification": classification,
                "sign_classification_reason": reason,
            }
        )
        results.append(row)
    return results


def summarize_classifications(
    duplicate_groups: list[dict[str, Any]],
    signed_values: list[dict[str, Any]],
    identical_duplicates: list[dict[str, Any]],
) -> dict[str, Any]:
    duplicate_counts = Counter(group["classification"] for group in duplicate_groups)
    sign_counts = Counter(row["sign_classification"] for row in signed_values)
    identical_counts = Counter(row["classification"] for row in identical_duplicates)
    return {
        "duplicate_group_classifications": dict(sorted(duplicate_counts.items())),
        "identical_duplicate_classifications": dict(sorted(identical_counts.items())),
        "signed_value_classifications": dict(sorted(sign_counts.items())),
    }


def recommended_next_actions(summary: dict[str, Any]) -> list[str]:
    actions = []
    duplicate_counts = summary["duplicate_group_classifications"]
    sign_counts = summary["signed_value_classifications"]
    identical_counts = summary["identical_duplicate_classifications"]
    if duplicate_counts.get("likely_mapping_too_broad"):
        actions.append("A. mapping fix")
    if duplicate_counts.get("likely_extraction_duplicate") or identical_counts.get("likely_extraction_duplicate"):
        actions.append("B. extraction duplicate handling")
    if sign_counts.get("sign_policy_needed") or sign_counts.get("likely_wrong_sign"):
        actions.append("C. sign policy/sign normalization")
    if duplicate_counts.get("likely_generator_duplicate") or identical_counts.get("likely_generator_duplicate"):
        actions.append("D. generator de-duplication")
    actions.append("E. regression pack expansion")
    if sign_counts.get("needs_manual_review") or duplicate_counts.get("needs_manual_review"):
        actions.append("F. manual review first")
    return actions


async def build_report(job_id: int, audit_report_path: Path | None = None) -> dict[str, Any]:
    audit_report = load_audit_report(job_id, audit_report_path)
    job = await load_job(job_id)
    xbrl_path = Path(audit_report.get("xbrl_path") or default_xbrl_path_for_job(job))
    parsed = parse_xbrl_instance(xbrl_path)
    expected_facts = expected_facts_for_job(job)
    generated_facts = parsed["facts"]
    template_concepts = load_template_concepts()
    duplicate_groups = triage_duplicate_groups(
        expected_facts=expected_facts,
        generated_facts=generated_facts,
        audit_report=audit_report,
        template_concepts=template_concepts,
    )
    identical_duplicates = triage_identical_duplicate_keys(
        expected_facts=expected_facts,
        generated_facts=generated_facts,
        audit_report=audit_report,
        template_concepts=template_concepts,
    )
    signed_values = triage_signed_values(expected_facts, template_concepts)
    summary = summarize_classifications(duplicate_groups, signed_values, identical_duplicates)
    return {
        "job": audit_report["job"],
        "xbrl_path": str(xbrl_path),
        "source_audit_report": str(audit_report_path or DEFAULT_REPORTS_DIR / f"generated_instance_audit_report_{job_id}.json"),
        "triage_scope": {
            "read_only": True,
            "database_modified": False,
            "generated_xbrl_modified": False,
            "does_not_claim_full_mbrs_validation": True,
        },
        "summary": {
            "duplicate_group_count": len(duplicate_groups),
            "identical_duplicate_key_count": len(identical_duplicates),
            "suspicious_signed_value_count": len(signed_values),
            "classification_counts": summary,
            "recommended_next_actions": recommended_next_actions(summary),
            "immediate_code_fix_justified": False,
            "immediate_code_fix_assessment": "No code fix is justified before row-level mapping/sign decisions are reviewed; evidence points first to mapping breadth, source duplicate handling, and sign policy.",
        },
        "duplicate_concept_context_unit_groups": duplicate_groups,
        "identical_duplicate_fact_keys": identical_duplicates,
        "suspicious_signed_values": signed_values,
    }


def write_report(report: dict[str, Any], job_id: int) -> Path:
    DEFAULT_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DEFAULT_REPORTS_DIR / f"generated_instance_quality_triage_report_{job_id}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def print_summary(report: dict[str, Any], report_path: Path) -> None:
    summary = report["summary"]
    print(f"Generated instance quality triage report: {report_path}")
    print(f"Job ID: {report['job']['id']}")
    print(f"XBRL path: {report['xbrl_path']}")
    print(f"Duplicate groups triaged: {summary['duplicate_group_count']}")
    print(f"Identical duplicate keys triaged: {summary['identical_duplicate_key_count']}")
    print(f"Suspicious signed values triaged: {summary['suspicious_signed_value_count']}")
    print(f"Immediate code fix justified: {summary['immediate_code_fix_justified']}")


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def main() -> int:
    args = parse_args()
    report = asyncio.run(build_report(args.job_id, args.audit_report))
    report_path = write_report(report, args.job_id)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_summary(report, report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
