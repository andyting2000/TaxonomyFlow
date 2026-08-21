import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence

from sqlalchemy import select, text, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import AsyncSessionLocal, ExtractedDataItem, FinancialStatementPage


TARGET_STATEMENT_TYPE = "Director Business Review"
PROPOSED_STATEMENT_TYPE = ""

TARGET_ITEM_IDS = (
    "c7a39463-11cd-4e98-81e7-6062888991c0",
    "2228f2a3-8d5e-4ead-8bd7-0ffb9470dc56",
    "7ee722c7-e759-4d03-a8cc-ebc7832ae175",
    "9527ccaf-9eb7-4968-8cef-9928b50b16f7",
    "8155513c-3316-495c-ab0a-d99622308f2e",
    "e1ec98e1-d6cd-491c-bbf1-1810a76df863",
    "0557f002-ce97-4f53-9dd1-8f2f58dece7d",
    "69a8c8d1-1b83-4c8c-aeb6-8760013fa74d",
    "bf1d17a5-063d-4c16-aad2-0184e4b09e9a",
    "e243a9cb-aed9-44e9-bbfa-c1ec787764fa",
    "737ee0ea-0a29-4eb3-a749-40a393dbdae8",
    "42d62c2e-9c29-402e-9208-238f45449538",
    "dc7d72a9-8ef9-4a6e-aea6-406665224ca5",
)


@dataclass(frozen=True)
class CorrectionRow:
    item_id: str
    job_id: int | None
    page_id: str | None
    page_number: int | None
    extracted_label: str | None
    extracted_value: str | None
    template_field_id: str | None
    current_statement_type: str | None
    proposed_statement_type: str


@dataclass(frozen=True)
class CorrectionReport:
    applied: bool
    expected_target_count: int
    rows_found: int
    rows_eligible: int
    rows_updated: int
    rows_missing: List[str]
    rows: List[CorrectionRow]


def build_target_select_statement():
    return (
        select(
            ExtractedDataItem.id,
            FinancialStatementPage.job_id,
            ExtractedDataItem.page_id,
            FinancialStatementPage.page_number,
            ExtractedDataItem.extracted_label,
            ExtractedDataItem.extracted_value,
            ExtractedDataItem.template_field_id,
            ExtractedDataItem.statement_type,
        )
        .outerjoin(FinancialStatementPage, FinancialStatementPage.id == ExtractedDataItem.page_id)
        .where(ExtractedDataItem.id.in_(TARGET_ITEM_IDS))
        .order_by(FinancialStatementPage.job_id, FinancialStatementPage.page_number, ExtractedDataItem.id)
    )


def build_correction_update_statement():
    return (
        update(ExtractedDataItem)
        .where(ExtractedDataItem.id.in_(TARGET_ITEM_IDS))
        .where(ExtractedDataItem.statement_type == TARGET_STATEMENT_TYPE)
        .values(statement_type=PROPOSED_STATEMENT_TYPE)
    )


def _row_from_result(row) -> CorrectionRow:
    return CorrectionRow(
        item_id=row.id,
        job_id=row.job_id,
        page_id=row.page_id,
        page_number=row.page_number,
        extracted_label=row.extracted_label,
        extracted_value=row.extracted_value,
        template_field_id=row.template_field_id,
        current_statement_type=row.statement_type,
        proposed_statement_type=PROPOSED_STATEMENT_TYPE,
    )


def _missing_ids(rows: Sequence[CorrectionRow]) -> List[str]:
    found_ids = {row.item_id for row in rows}
    return [item_id for item_id in TARGET_ITEM_IDS if item_id not in found_ids]


def _eligible_count(rows: Sequence[CorrectionRow]) -> int:
    return sum(
        1
        for row in rows
        if row.current_statement_type == TARGET_STATEMENT_TYPE
    )


def render_report(report: CorrectionReport) -> str:
    mode = "apply" if report.applied else "dry-run"
    lines = [
        "Feature #10D statement_type correction",
        f"Mode: {mode}",
        "",
        f"expected_target_count: {report.expected_target_count}",
        f"rows_found: {report.rows_found}",
        f"rows_eligible: {report.rows_eligible}",
        f"rows_updated: {report.rows_updated}",
        f"rows_missing: {len(report.rows_missing)}",
    ]

    if report.rows_missing:
        lines.append("Missing target IDs:")
        lines.extend(f"  - {item_id}" for item_id in report.rows_missing)

    lines.extend(["", "Row evidence:"])
    if report.rows:
        for row in report.rows:
            lines.append(
                "  - "
                f"item_id={row.item_id} "
                f"job_id={row.job_id} "
                f"page_id={row.page_id} "
                f"page_number={row.page_number} "
                f"extracted_label={row.extracted_label} "
                f"extracted_value={row.extracted_value} "
                f"template_field_id={row.template_field_id} "
                f"current_statement_type={row.current_statement_type} "
                f"proposed_statement_type={row.proposed_statement_type!r}"
            )
    else:
        lines.append("  - none")

    lines.extend([
        "",
        "Note: dry-run is the default and does not modify rows.",
        "Note: apply mode only updates the exact Feature #10D target IDs that still have statement_type='Director Business Review'.",
        "Note: no replacement statement_type is inferred; eligible rows are reset to a blank statement_type.",
    ])
    return "\n".join(lines)


async def run_correction(apply_changes: bool) -> CorrectionReport:
    async with AsyncSessionLocal() as session:
        if not apply_changes:
            await session.execute(text("SET TRANSACTION READ ONLY"))

        result = await session.execute(build_target_select_statement())
        rows = [_row_from_result(row) for row in result.all()]
        rows_updated = 0

        if apply_changes:
            update_result = await session.execute(build_correction_update_statement())
            rows_updated = int(update_result.rowcount or 0)
            await session.commit()
        else:
            await session.rollback()

        return CorrectionReport(
            applied=apply_changes,
            expected_target_count=len(TARGET_ITEM_IDS),
            rows_found=len(rows),
            rows_eligible=_eligible_count(rows),
            rows_updated=rows_updated,
            rows_missing=_missing_ids(rows),
            rows=rows,
        )


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Correct the exact 13 known-wrong Feature #10D statement_type backfill rows."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the correction. Dry-run is the default.",
    )
    args = parser.parse_args()

    report = await run_correction(apply_changes=args.apply)
    print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
