import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import AsyncSessionLocal, ExtractedDataItem, FinancialStatementPage
from services.xbrl_template_service import (
    BIOLOGICAL_ASSET_EVIDENCE_TERMS,
    biological_asset_guardrail_allows,
    get_xbrl_template_service,
    is_biological_asset_concept,
)


DEFAULT_REPORT_TEMPLATE = "reports/biological_asset_persisted_row_correction_plan_{job_id}.json"
GUARDRAIL_REPORT_TEMPLATE = "reports/biological_asset_guardrail_report_{job_id}.json"


@dataclass(frozen=True)
class PersistedBiologicalAssetRow:
    item_id: str
    job_id: int
    page_id: str
    page_number: Optional[int]
    extracted_label: Optional[str]
    extracted_value: Optional[str]
    current_template_field_id: Optional[str]
    current_concept_name: Optional[str]
    current_concept_id: Optional[str]
    statement_type: Optional[str]
    is_reviewed: bool
    confirmed_tag_id: Optional[int]
    guardrail_reason: str
    proposed_action: Dict[str, Any]


def build_candidate_select_statement(job_id: int):
    return (
        select(
            ExtractedDataItem.id.label("item_id"),
            FinancialStatementPage.job_id,
            ExtractedDataItem.page_id,
            FinancialStatementPage.page_number,
            ExtractedDataItem.extracted_label,
            ExtractedDataItem.extracted_value,
            ExtractedDataItem.template_field_id,
            ExtractedDataItem.statement_type,
            ExtractedDataItem.is_reviewed,
            ExtractedDataItem.confirmed_tag_id,
        )
        .join(FinancialStatementPage, FinancialStatementPage.id == ExtractedDataItem.page_id)
        .where(FinancialStatementPage.job_id == job_id)
        .where(ExtractedDataItem.template_field_id.is_not(None))
        .order_by(FinancialStatementPage.page_number, ExtractedDataItem.id)
    )


def _guardrail_reason(row: Any) -> str:
    return (
        "template_field_id is a guarded biological-asset concept, but extracted_label "
        "does not contain direct biological/agricultural evidence terms: "
        + ", ".join(BIOLOGICAL_ASSET_EVIDENCE_TERMS)
    )


def _proposed_action(row: Any) -> Dict[str, Any]:
    return {
        "future_apply_behavior": "clear template_field_id only for this exact item_id if still assigned to the same guarded biological-asset concept",
        "set_template_field_id_to": None,
        "replacement_concept_id": None,
        "invent_replacement_concept": False,
        "preserve_extracted_label": True,
        "preserve_extracted_value": True,
        "preserve_statement_type": True,
        "preserve_confirmed_tag_id": True,
        "manual_review_required": True,
        "note": "This dry-run plan does not mutate the database.",
    }


def _concept_label(template_service: Any, concept_id: Optional[str]) -> Optional[str]:
    if not concept_id:
        return None
    concept_info = template_service.get_concept_info(concept_id)
    if not concept_info:
        return None
    return concept_info.get("label") or concept_info.get("name") or concept_id


def detect_correction_candidates(
    rows: Sequence[Any],
    template_service: Any,
) -> List[PersistedBiologicalAssetRow]:
    candidates: List[PersistedBiologicalAssetRow] = []

    for row in rows:
        concept_id = getattr(row, "template_field_id", None)
        label = getattr(row, "extracted_label", None)

        if not is_biological_asset_concept(concept_id):
            continue
        if biological_asset_guardrail_allows(concept_id, label):
            continue

        candidates.append(
            PersistedBiologicalAssetRow(
                item_id=str(row.item_id),
                job_id=int(row.job_id),
                page_id=str(row.page_id),
                page_number=row.page_number,
                extracted_label=label,
                extracted_value=getattr(row, "extracted_value", None),
                current_template_field_id=concept_id,
                current_concept_name=_concept_label(template_service, concept_id),
                current_concept_id=concept_id,
                statement_type=getattr(row, "statement_type", None),
                is_reviewed=bool(getattr(row, "is_reviewed", False)),
                confirmed_tag_id=getattr(row, "confirmed_tag_id", None),
                guardrail_reason=_guardrail_reason(row),
                proposed_action=_proposed_action(row),
            )
        )

    return candidates


def _load_expected_count(job_id: int) -> Optional[int]:
    report_path = Path(GUARDRAIL_REPORT_TEMPLATE.format(job_id=job_id))
    if not report_path.exists():
        return None
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return (
        report.get("job_9_before_after_audit", {})
        .get("impact", {})
        .get("rows_moved_to_manual_review_or_no_automatic_generated_concept")
    )


def build_report(job_id: int, candidates: Sequence[PersistedBiologicalAssetRow]) -> Dict[str, Any]:
    expected_count = _load_expected_count(job_id)
    rows_by_concept: Dict[str, int] = {}
    for candidate in candidates:
        concept_id = candidate.current_template_field_id or ""
        rows_by_concept[concept_id] = rows_by_concept.get(concept_id, 0) + 1

    return {
        "feature": "11K",
        "job_id": job_id,
        "mode": "dry_run_only",
        "read_only": True,
        "database_modified": False,
        "apply_supported": False,
        "candidate_count": len(candidates),
        "expected_count_from_11j_guardrail_report": expected_count,
        "candidate_count_matches_11j_skipped_rows": (
            expected_count is not None and len(candidates) == expected_count
        ),
        "rows_by_current_template_field_id": rows_by_concept,
        "selection_criteria": [
            "row belongs to selected job_id",
            "template_field_id is ssmt-mpers:CurrentBiologicalAssets or ssmt-mpers:NoncurrentBiologicalAssets, including equivalent unprefixed local names",
            "extracted_label does not satisfy biological-asset guardrail evidence terms",
        ],
        "proposed_future_correction": {
            "clear_template_field_id": True,
            "assign_replacement_concept": False,
            "preserve_extracted_label_value": True,
            "preserve_confirmed_tag_id": True,
            "requires_exact_id_guarded_apply_script": True,
            "apply_in_this_feature": False,
        },
        "candidates": [asdict(candidate) for candidate in candidates],
        "next_step_options": [
            "Approve an exact-ID guarded apply script for these candidate rows.",
            "Skip database correction and move to the next mapping-quality issue such as ifrs-smes:TradeAndOtherCurrentReceivables.",
        ],
    }


def render_console_report(report: Dict[str, Any]) -> str:
    lines = [
        "Feature #11K biological-asset persisted-row correction plan",
        "Mode: dry-run only",
        "",
        f"job_id: {report['job_id']}",
        f"candidate_count: {report['candidate_count']}",
        f"expected_count_from_11j_guardrail_report: {report['expected_count_from_11j_guardrail_report']}",
        f"candidate_count_matches_11j_skipped_rows: {report['candidate_count_matches_11j_skipped_rows']}",
        f"database_modified: {report['database_modified']}",
        f"apply_supported: {report['apply_supported']}",
        "",
        "Rows by current template_field_id:",
    ]

    for concept_id, count in sorted(report["rows_by_current_template_field_id"].items()):
        lines.append(f"  - {concept_id}: {count}")

    lines.extend(["", "Candidate row evidence:"])
    for row in report["candidates"]:
        lines.append(
            "  - "
            f"item_id={row['item_id']} "
            f"job_id={row['job_id']} "
            f"page_id={row['page_id']} "
            f"page_number={row['page_number']} "
            f"extracted_label={row['extracted_label']} "
            f"extracted_value={row['extracted_value']} "
            f"current_template_field_id={row['current_template_field_id']} "
            f"current_concept_name={row['current_concept_name']} "
            f"statement_type={row['statement_type']} "
            f"is_reviewed={row['is_reviewed']} "
            f"confirmed_tag_id={row['confirmed_tag_id']} "
            "proposed_action=clear template_field_id in future exact-ID apply script; no replacement concept"
        )

    if not report["candidates"]:
        lines.append("  - none")

    lines.extend(
        [
            "",
            "Note: this script has no --apply option and performs no database mutation.",
            "Note: proposed future correction clears only the automatic template_field_id and preserves extracted label/value for manual review.",
        ]
    )
    return "\n".join(lines)


async def load_candidates(job_id: int) -> List[PersistedBiologicalAssetRow]:
    template_service = get_xbrl_template_service()
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        result = await session.execute(build_candidate_select_statement(job_id))
        rows = result.all()
        candidates = detect_correction_candidates(rows, template_service)
        await session.rollback()
    return candidates


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Plan a dry-run-only correction for persisted biological-asset template_field_id rows."
    )
    parser.add_argument("--job-id", type=int, required=True, help="Filing job ID to inspect.")
    parser.add_argument("--json", action="store_true", help="Print JSON report instead of console text.")
    parser.add_argument(
        "--report-path",
        default=None,
        help="Where to save the JSON report. Defaults to reports/biological_asset_persisted_row_correction_plan_<job_id>.json.",
    )
    args = parser.parse_args()

    candidates = await load_candidates(args.job_id)
    report = build_report(args.job_id, candidates)

    report_path = Path(args.report_path or DEFAULT_REPORT_TEMPLATE.format(job_id=args.job_id))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render_console_report(report))
        print(f"\nReport saved: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
