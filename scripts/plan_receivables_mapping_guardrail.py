"""Read-only planning report for TradeAndOtherCurrentReceivables mapping guardrails."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_generated_xbrl_instance import (
    DEFAULT_REPORTS_DIR,
    ExpectedFact,
    build_report as build_generated_instance_audit,
    expected_facts_for_job,
    load_job,
)
from services.xbrl_template_service import get_xbrl_template_service


TARGET_CONCEPT = "ifrs-smes:TradeAndOtherCurrentReceivables"
DEFAULT_REPORT_TEMPLATE = "reports/receivables_mapping_guardrail_plan_{job_id}.json"

RECEIVABLE_SUMMARY_TERMS = (
    "trade and other current receivables",
    "trade and other receivables",
    "trade receivables",
    "other receivables",
    "current receivables",
    "accounts receivable",
    "account receivable",
    "receivables",
    "receivable",
    "debtors",
    "debtor",
    "amounts due from",
    "amount due from",
    "due from",
)

DETAIL_COMPANY_TERMS = (
    "sdn bhd",
    "sdn. bhd",
    "berhad",
    " bhd",
    "bhd.",
    "limited",
    " ltd",
    "ltd.",
    "corporation",
    "corp",
    "services",
    "consultants",
    "management",
)

NON_RECEIVABLE_TERMS = (
    "share capital",
    "share premium",
    "profit and loss",
    "p&l",
    "cash",
    "bank",
    "trade payable",
    "trade payables",
    "payable",
    "payables",
    "creditor",
    "creditors",
    "accrual",
    "accruals",
    "revenue",
    "expenses",
    "expense",
    "goodwill",
    "equipment",
    "inventory",
    "inventories",
)


@dataclass(frozen=True)
class ReceivableEvidenceRow:
    item_id: str
    page_id: str | None
    page_number: int | None
    extracted_label: str | None
    extracted_value: str | None
    current_template_field_id: str | None
    resolved_concept: str
    resolved_concept_label: str | None
    statement_type: str | None
    confirmed_tag_id: int | None
    contextRef: str | None
    unitRef: str | None
    generated_value: str | None
    duplicate_group_membership: dict[str, Any] | None
    classification: str
    classification_reason: str
    proposed_action: dict[str, Any]


def normalize_label(label: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9&().'\- ]+", " ", str(label or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()


def has_receivable_summary_evidence(label: str | None) -> bool:
    normalized = normalize_label(label)
    return any(term in normalized for term in RECEIVABLE_SUMMARY_TERMS)


def is_company_or_customer_like_label(label: str | None) -> bool:
    normalized = f" {normalize_label(label)} "
    if any(term in normalized for term in DETAIL_COMPANY_TERMS):
        return True
    return False


def has_non_receivable_evidence(label: str | None) -> bool:
    normalized = normalize_label(label)
    return any(term in normalized for term in NON_RECEIVABLE_TERMS)


def classify_receivable_label(label: str | None) -> tuple[str, str]:
    if has_non_receivable_evidence(label):
        return (
            "likely_not_receivable",
            "Label contains terms that point to non-receivable balances such as payables, capital, cash, revenue, or expenses.",
        )
    if has_receivable_summary_evidence(label) and not is_company_or_customer_like_label(label):
        return (
            "likely_valid_receivable_summary",
            "Label explicitly describes a receivable/debtor summary line.",
        )
    if has_receivable_summary_evidence(label) and is_company_or_customer_like_label(label):
        return (
            "likely_valid_receivable_detail_but_needs_dimension_or_aggregation_policy",
            "Label has receivable evidence but also looks like a detail/customer row, so repeated same-context facts need aggregation or dimensions.",
        )
    if is_company_or_customer_like_label(label):
        return (
            "likely_valid_receivable_detail_but_needs_dimension_or_aggregation_policy",
            "Label looks like a customer/company detail row; it may be receivable detail, but should not become repeated same-context summary facts without manual confirmation or an aggregation/dimension policy.",
        )
    if label and normalize_label(label):
        return (
            "likely_mapping_too_broad",
            "Label is not explicit receivable evidence for this broad concept and should require higher confidence or manual confirmation.",
        )
    return (
        "not_enough_information",
        "No label evidence is available to support automatic receivables mapping.",
    )


def proposed_action_for_classification(classification: str) -> dict[str, Any]:
    if classification == "likely_valid_receivable_summary":
        action = "allow automatic mapping only when high-confidence summary evidence exists"
    elif classification == "likely_valid_receivable_detail_but_needs_dimension_or_aggregation_policy":
        action = "require manual confirmation or aggregation/dimension policy before generating repeated same-context facts"
    else:
        action = "block or require manual confirmation for automatic mapping to this broad concept"

    return {
        "recommended_future_behavior": action,
        "assign_replacement_concept": False,
        "replacement_concept_id": None,
        "preserve_extracted_label": True,
        "preserve_extracted_value": True,
        "manual_review_required": classification != "likely_valid_receivable_summary",
    }


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _target_duplicate_group(audit_report: dict[str, Any]) -> dict[str, Any] | None:
    groups = (
        audit_report.get("generated_facts", {})
        .get("duplicate_concept_context_unit_facts", {})
        .get("groups", [])
    )
    for group in groups:
        if group.get("concept") == TARGET_CONCEPT:
            return group
    return None


def _concept_label(concept_id: str) -> str | None:
    template_service = get_xbrl_template_service()
    info = template_service.get_concept_info(concept_id) or {}
    return info.get("label") or info.get("name")


def build_evidence_rows(
    expected_facts: Sequence[ExpectedFact],
    audit_report: dict[str, Any],
) -> list[ReceivableEvidenceRow]:
    duplicate_group = _target_duplicate_group(audit_report)
    concept_label = _concept_label(TARGET_CONCEPT)
    rows: list[ReceivableEvidenceRow] = []

    for fact in sorted(expected_facts, key=lambda item: (item.page_number or 0, item.item_id)):
        if fact.concept != TARGET_CONCEPT:
            continue
        classification, reason = classify_receivable_label(fact.extracted_label)
        rows.append(
            ReceivableEvidenceRow(
                item_id=fact.item_id,
                page_id=fact.page_id,
                page_number=fact.page_number,
                extracted_label=fact.extracted_label,
                extracted_value=fact.extracted_value,
                current_template_field_id=fact.template_field_id,
                resolved_concept=fact.concept,
                resolved_concept_label=concept_label,
                statement_type=fact.statement_type,
                confirmed_tag_id=fact.confirmed_tag_id,
                contextRef=fact.context_ref,
                unitRef=fact.unit_ref,
                generated_value=fact.value,
                duplicate_group_membership=duplicate_group,
                classification=classification,
                classification_reason=reason,
                proposed_action=proposed_action_for_classification(classification),
            )
        )

    return rows


def summarize_classifications(rows: Sequence[ReceivableEvidenceRow]) -> dict[str, int]:
    return dict(sorted(Counter(row.classification for row in rows).items()))


def decide_next_feature_scope(rows: Sequence[ReceivableEvidenceRow]) -> dict[str, Any]:
    summary = summarize_classifications(rows)
    detail_count = summary.get("likely_valid_receivable_detail_but_needs_dimension_or_aggregation_policy", 0)
    non_summary_count = len(rows) - summary.get("likely_valid_receivable_summary", 0)
    return {
        "recommended_11N_scope": "Add a receivables guardrail/high-confidence rule for company/customer detail labels and prepare a dry-run persisted-row correction plan only after the guardrail design is accepted.",
        "code_changes_justified_next": non_summary_count > 0,
        "block_automatic_detail_row_mapping": detail_count > 0,
        "require_high_confidence": True,
        "manual_confirmation_for_company_like_labels": detail_count > 0,
        "aggregation_or_dimension_policy_needed": detail_count > 0,
        "leave_concept_unchanged_for_summary_rows": True,
        "invent_replacement_concepts": False,
        "existing_job_9_persisted_row_recommendation": (
            "If a future guardrail is approved, create a dry-run exact-row plan for affected job 9 rows; "
            "clear only automatic template_field_id for rows that fail the guardrail, preserve label/value/statement_type/confirmed_tag_id, "
            "and assign no replacement concept."
        ),
    }


def build_planning_report(
    job_id: int,
    audit_report: dict[str, Any],
    evidence_rows: Sequence[ReceivableEvidenceRow],
) -> dict[str, Any]:
    duplicate_group = _target_duplicate_group(audit_report)
    labels = [row.extracted_label for row in evidence_rows if row.extracted_label]
    return {
        "feature": "11M",
        "job_id": job_id,
        "target_concept": TARGET_CONCEPT,
        "mode": "read_only_planning",
        "read_only": True,
        "database_modified": False,
        "mapping_behavior_changed": False,
        "generated_xbrl_modified": False,
        "sign_normalization_deferred": True,
        "full_mbrs_validation_claimed": False,
        "source_reports": {
            "generated_instance_audit_report": str(DEFAULT_REPORTS_DIR / f"generated_instance_audit_report_{job_id}.json"),
            "generated_instance_quality_triage_report": str(DEFAULT_REPORTS_DIR / f"generated_instance_quality_triage_report_{job_id}.json"),
            "mapping_sign_policy_fix_design": str(DEFAULT_REPORTS_DIR / f"mapping_sign_policy_fix_design_{job_id}.json"),
        },
        "xbrl_path": audit_report.get("xbrl_path"),
        "row_count": len(evidence_rows),
        "classification_summary": summarize_classifications(evidence_rows),
        "duplicate_group_evidence": duplicate_group,
        "source_label_summary": {
            "company_or_customer_like_count": sum(1 for label in labels if is_company_or_customer_like_label(label)),
            "explicit_receivable_summary_count": sum(1 for label in labels if has_receivable_summary_evidence(label)),
            "non_receivable_evidence_count": sum(1 for label in labels if has_non_receivable_evidence(label)),
        },
        "planning_answers": {
            "are_repeated_facts_summary_detail_or_incorrect": (
                "The job 9 repeated facts are primarily customer/company-like detail rows and OTHER DEBTOR detail rows, "
                "not a single receivables summary line. They should not be emitted repeatedly with the same concept/context/unit "
                "without manual confirmation, aggregation, or dimensional policy."
            ),
            "should_block_automatic_detail_row_mapping": True,
            "should_require_high_confidence_only": True,
            "manual_confirmation_when_label_looks_like_company_or_customer": True,
            "aggregation_or_dimension_problem": True,
            "existing_persisted_job_9_rows": decide_next_feature_scope(evidence_rows)["existing_job_9_persisted_row_recommendation"],
        },
        "guardrail_recommendation": decide_next_feature_scope(evidence_rows),
        "rows": [asdict(row) for row in evidence_rows],
    }


async def build_report(job_id: int) -> dict[str, Any]:
    job = await load_job(job_id)
    audit_report = await build_generated_instance_audit(job_id)
    expected_facts = expected_facts_for_job(job)
    evidence_rows = build_evidence_rows(expected_facts, audit_report)
    return build_planning_report(job_id, audit_report, evidence_rows)


def write_report(report: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return path


def render_console_report(report: dict[str, Any]) -> str:
    lines = [
        "Feature #11M receivables mapping guardrail plan",
        f"job_id: {report['job_id']}",
        f"target_concept: {report['target_concept']}",
        f"row_count: {report['row_count']}",
        f"classification_summary: {report['classification_summary']}",
        f"database_modified: {report['database_modified']}",
        f"mapping_behavior_changed: {report['mapping_behavior_changed']}",
        "",
        "Recommendation:",
        f"  {report['guardrail_recommendation']['recommended_11N_scope']}",
        "",
        "Row evidence:",
    ]
    for row in report["rows"]:
        lines.append(
            "  - "
            f"item_id={row['item_id']} "
            f"page_number={row['page_number']} "
            f"label={row['extracted_label']} "
            f"value={row['extracted_value']} "
            f"contextRef={row['contextRef']} "
            f"unitRef={row['unitRef']} "
            f"classification={row['classification']}"
        )
    if not report["rows"]:
        lines.append("  - none")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only planning report for TradeAndOtherCurrentReceivables mapping guardrails."
    )
    parser.add_argument("--job-id", type=int, required=True, help="Filing job ID to inspect.")
    parser.add_argument("--json", action="store_true", help="Print full report JSON.")
    parser.add_argument(
        "--report-path",
        type=Path,
        help="Report path. Defaults to reports/receivables_mapping_guardrail_plan_<job_id>.json.",
    )
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    report = await build_report(args.job_id)
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
