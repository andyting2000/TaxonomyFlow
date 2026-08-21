import argparse
import asyncio
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, not_, or_, select, text, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import AsyncSessionLocal, ExtractedDataItem, FinancialStatementPage
from services.xbrl_template_service import (
    BIOLOGICAL_ASSET_EVIDENCE_TERMS,
    BIOLOGICAL_ASSET_NEGATIVE_EVIDENCE_TERMS,
    biological_asset_guardrail_allows,
    get_xbrl_template_service,
    is_biological_asset_concept,
)


DEFAULT_JOB_ID = 9
EXPECTED_TARGET_COUNT = 34
DEFAULT_PLAN_REPORT_TEMPLATE = "reports/biological_asset_persisted_row_correction_plan_{job_id}.json"
DEFAULT_DRY_RUN_REPORT_TEMPLATE = (
    "reports/biological_asset_template_field_correction_11l_dry_run_{job_id}.json"
)
DEFAULT_APPLY_REPORT_TEMPLATE = (
    "reports/biological_asset_template_field_correction_11l_apply_{job_id}.json"
)

BIOLOGICAL_ASSET_TEMPLATE_FIELD_IDS = (
    "ssmt-mpers:CurrentBiologicalAssets",
    "ssmt-mpers:NoncurrentBiologicalAssets",
    "CurrentBiologicalAssets",
    "NoncurrentBiologicalAssets",
)


@dataclass(frozen=True)
class CorrectionRowEvidence:
    item_id: str
    job_id: Optional[int]
    page_id: Optional[str]
    page_number: Optional[int]
    extracted_label: Optional[str]
    extracted_value: Optional[str]
    current_template_field_id: Optional[str]
    resolved_concept: Optional[str]
    current_statement_type: Optional[str]
    confirmed_tag_id: Optional[int]
    proposed_action: Dict[str, Any]
    eligible: bool
    eligibility_reason: str


def load_plan_report(report_path: Path) -> Dict[str, Any]:
    if not report_path.exists():
        raise FileNotFoundError(f"Correction plan report not found: {report_path}")
    return json.loads(report_path.read_text(encoding="utf-8"))


def load_target_ids_from_plan(
    report_path: Path,
    job_id: int,
    expected_count: int = EXPECTED_TARGET_COUNT,
) -> tuple[str, ...]:
    report = load_plan_report(report_path)

    if report.get("feature") != "11K":
        raise ValueError("Target report must be the Feature #11K correction plan.")
    if int(report.get("job_id")) != job_id:
        raise ValueError(f"Target report job_id {report.get('job_id')} does not match {job_id}.")
    if report.get("apply_supported") is not False:
        raise ValueError("Target report must be the dry-run-only #11K plan.")
    if int(report.get("candidate_count", -1)) != expected_count:
        raise ValueError(
            f"Expected {expected_count} target candidates, found {report.get('candidate_count')}."
        )

    candidate_rows = report.get("candidates") or []
    target_ids = tuple(str(row["item_id"]) for row in candidate_rows)
    if len(target_ids) != expected_count or len(set(target_ids)) != expected_count:
        raise ValueError("Target item IDs must be complete and unique.")

    for row in candidate_rows:
        if int(row.get("job_id")) != job_id:
            raise ValueError("Every target row in the plan must match the requested job_id.")
        if not is_biological_asset_concept(row.get("current_template_field_id")):
            raise ValueError("Every target row must have a biological-asset template_field_id.")

    return target_ids


def build_target_select_statement(target_ids: Sequence[str]):
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
            ExtractedDataItem.confirmed_tag_id,
        )
        .outerjoin(FinancialStatementPage, FinancialStatementPage.id == ExtractedDataItem.page_id)
        .where(ExtractedDataItem.id.in_(tuple(target_ids)))
        .order_by(FinancialStatementPage.job_id, FinancialStatementPage.page_number, ExtractedDataItem.id)
    )


def build_guardrail_failure_predicate():
    label = func.lower(func.coalesce(ExtractedDataItem.extracted_label, ""))
    evidence_present = or_(
        *[label.like(f"%{term}%") for term in BIOLOGICAL_ASSET_EVIDENCE_TERMS]
    )
    negative_present = or_(
        *[label.like(f"%{term}%") for term in BIOLOGICAL_ASSET_NEGATIVE_EVIDENCE_TERMS]
    )
    return or_(negative_present, not_(evidence_present))


def build_correction_update_statement(
    job_id: int,
    target_ids: Sequence[str],
    eligible_ids: Sequence[str],
):
    page_ids_for_job = select(FinancialStatementPage.id).where(FinancialStatementPage.job_id == job_id)
    return (
        update(ExtractedDataItem)
        .where(ExtractedDataItem.id.in_(tuple(target_ids)))
        .where(ExtractedDataItem.id.in_(tuple(eligible_ids)))
        .where(ExtractedDataItem.page_id.in_(page_ids_for_job))
        .where(ExtractedDataItem.template_field_id.in_(BIOLOGICAL_ASSET_TEMPLATE_FIELD_IDS))
        .where(build_guardrail_failure_predicate())
        .values(template_field_id=None)
    )


def _concept_label(template_service: Any, concept_id: Optional[str]) -> Optional[str]:
    if not concept_id:
        return None
    concept_info = template_service.get_concept_info(concept_id)
    if not concept_info:
        return concept_id
    return concept_info.get("label") or concept_info.get("name") or concept_id


def proposed_action() -> Dict[str, Any]:
    return {
        "set_template_field_id_to": None,
        "replacement_concept_id": None,
        "invent_replacement_concept": False,
        "preserve_extracted_label": True,
        "preserve_extracted_value": True,
        "preserve_statement_type": True,
        "preserve_confirmed_tag_id": True,
        "preserve_reviewed_status": True,
        "delete_row": False,
        "manual_review_required": True,
    }


def _eligibility_reason(row: Any, expected_job_id: int) -> tuple[bool, str]:
    if getattr(row, "job_id", None) != expected_job_id:
        return False, f"not eligible: row job_id is {getattr(row, 'job_id', None)}, expected {expected_job_id}"

    concept_id = getattr(row, "template_field_id", None)
    if not is_biological_asset_concept(concept_id):
        return False, "not eligible: current template_field_id is no longer a guarded biological-asset concept"

    if biological_asset_guardrail_allows(concept_id, getattr(row, "extracted_label", None)):
        return False, "not eligible: current extracted_label now supports biological-asset mapping"

    return True, "eligible: exact target row still has guarded biological-asset template_field_id and non-biological label"


def row_to_evidence(
    row: Any,
    expected_job_id: int,
    template_service: Any,
) -> CorrectionRowEvidence:
    eligible, reason = _eligibility_reason(row, expected_job_id)
    concept_id = getattr(row, "template_field_id", None)
    return CorrectionRowEvidence(
        item_id=str(row.item_id),
        job_id=getattr(row, "job_id", None),
        page_id=getattr(row, "page_id", None),
        page_number=getattr(row, "page_number", None),
        extracted_label=getattr(row, "extracted_label", None),
        extracted_value=getattr(row, "extracted_value", None),
        current_template_field_id=concept_id,
        resolved_concept=_concept_label(template_service, concept_id),
        current_statement_type=getattr(row, "statement_type", None),
        confirmed_tag_id=getattr(row, "confirmed_tag_id", None),
        proposed_action=proposed_action(),
        eligible=eligible,
        eligibility_reason=reason,
    )


def build_report(
    job_id: int,
    target_ids: Sequence[str],
    rows: Sequence[CorrectionRowEvidence],
    apply_changes: bool,
    rows_updated: int,
) -> Dict[str, Any]:
    found_ids = {row.item_id for row in rows}
    eligible_rows = [row for row in rows if row.eligible]
    not_eligible_rows = [row for row in rows if not row.eligible]

    rows_by_concept: Dict[str, int] = {}
    for row in rows:
        concept_id = row.current_template_field_id or "missing"
        rows_by_concept[concept_id] = rows_by_concept.get(concept_id, 0) + 1

    return {
        "feature": "11L",
        "mode": "apply" if apply_changes else "dry_run",
        "applied": apply_changes,
        "database_modified": bool(apply_changes and rows_updated),
        "job_id": job_id,
        "expected_target_count": len(target_ids),
        "rows_found": len(rows),
        "rows_eligible": len(eligible_rows),
        "rows_updated": rows_updated,
        "rows_missing": [item_id for item_id in target_ids if item_id not in found_ids],
        "rows_not_eligible": len(not_eligible_rows),
        "rows_by_current_template_field_id": rows_by_concept,
        "update_policy": {
            "dry_run_by_default": True,
            "apply_requires_explicit_flag": True,
            "target_exact_item_ids_only": True,
            "clear_template_field_id_only": True,
            "assign_replacement_concept": False,
            "preserve_extracted_label": True,
            "preserve_extracted_value": True,
            "preserve_statement_type": True,
            "preserve_confirmed_tag_id": True,
            "preserve_reviewed_status": True,
        },
        "target_rows": [asdict(row) for row in rows],
        "not_eligible_rows": [asdict(row) for row in not_eligible_rows],
    }


def render_report(report: Dict[str, Any]) -> str:
    lines = [
        "Feature #11L biological-asset template_field_id correction",
        f"Mode: {report['mode']}",
        "",
        f"job_id: {report['job_id']}",
        f"expected_target_count: {report['expected_target_count']}",
        f"rows_found: {report['rows_found']}",
        f"rows_eligible: {report['rows_eligible']}",
        f"rows_updated: {report['rows_updated']}",
        f"rows_missing: {len(report['rows_missing'])}",
        f"rows_not_eligible: {report['rows_not_eligible']}",
        f"database_modified: {report['database_modified']}",
        "",
        "Row evidence:",
    ]

    if not report["target_rows"]:
        lines.append("  - none")
    for row in report["target_rows"]:
        lines.append(
            "  - "
            f"item_id={row['item_id']} "
            f"job_id={row['job_id']} "
            f"page_id={row['page_id']} "
            f"page_number={row['page_number']} "
            f"extracted_label={row['extracted_label']} "
            f"extracted_value={row['extracted_value']} "
            f"current_template_field_id={row['current_template_field_id']} "
            f"resolved_concept={row['resolved_concept']} "
            f"current_statement_type={row['current_statement_type']} "
            f"confirmed_tag_id={row['confirmed_tag_id']} "
            "proposed_action=clear template_field_id only; no replacement concept "
            f"eligibility_reason={row['eligibility_reason']}"
        )

    if report["rows_missing"]:
        lines.extend(["", "Missing target IDs:"])
        lines.extend(f"  - {item_id}" for item_id in report["rows_missing"])

    lines.extend(
        [
            "",
            "Note: dry-run is the default and does not modify rows.",
            "Note: apply mode clears only template_field_id for exact target rows still matching the biological-asset guardrail predicate.",
            "Note: extracted label/value, statement_type, confirmed_tag_id, reviewed status, and row existence are preserved.",
        ]
    )
    return "\n".join(lines)


async def run_correction(
    job_id: int,
    target_ids: Sequence[str],
    apply_changes: bool,
) -> Dict[str, Any]:
    template_service = get_xbrl_template_service()
    async with AsyncSessionLocal() as session:
        if not apply_changes:
            await session.execute(text("SET TRANSACTION READ ONLY"))

        result = await session.execute(build_target_select_statement(target_ids))
        evidence_rows = [
            row_to_evidence(row, expected_job_id=job_id, template_service=template_service)
            for row in result.all()
        ]
        eligible_ids = [row.item_id for row in evidence_rows if row.eligible]
        rows_updated = 0

        if apply_changes and eligible_ids:
            update_result = await session.execute(
                build_correction_update_statement(job_id, target_ids, eligible_ids)
            )
            rows_updated = int(update_result.rowcount or 0)
            await session.commit()
        elif apply_changes:
            await session.commit()
        else:
            await session.rollback()

    return build_report(
        job_id=job_id,
        target_ids=target_ids,
        rows=evidence_rows,
        apply_changes=apply_changes,
        rows_updated=rows_updated,
    )


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Correct exact Feature #11L biological-asset template_field_id rows."
    )
    parser.add_argument("--job-id", type=int, default=DEFAULT_JOB_ID, help="Filing job ID to correct.")
    parser.add_argument(
        "--plan-report",
        default=None,
        help="Feature #11K plan report to load target IDs from.",
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help="Where to save the JSON result report.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON report instead of console text.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the correction. Dry-run is the default and should be reviewed first.",
    )
    args = parser.parse_args()

    plan_report_path = Path(
        args.plan_report or DEFAULT_PLAN_REPORT_TEMPLATE.format(job_id=args.job_id)
    )
    target_ids = load_target_ids_from_plan(plan_report_path, args.job_id)
    report = await run_correction(
        job_id=args.job_id,
        target_ids=target_ids,
        apply_changes=args.apply,
    )

    default_report_template = (
        DEFAULT_APPLY_REPORT_TEMPLATE if args.apply else DEFAULT_DRY_RUN_REPORT_TEMPLATE
    )
    report_path = Path(args.report_path or default_report_template.format(job_id=args.job_id))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render_report(report))
        print(f"\nReport saved: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
