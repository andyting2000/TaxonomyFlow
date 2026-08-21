"""Read-only diagnostics for Azure DI production mapping coverage."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import AsyncSessionLocal, ExtractedDataItem, FilingJob, FinancialStatementPage
from services.azure_di_production_mapping import diagnose_azure_di_candidate_mapping


def _candidate_from_item(item: ExtractedDataItem, page: FinancialStatementPage) -> dict[str, Any]:
    row_type = "numeric_fact" if str(item.extracted_value or "").strip() else "text_block"
    return {
        "row_type": row_type,
        "label": item.extracted_label,
        "value": item.extracted_value,
        "previous_value": item.value_previous_year,
        "statement_section": item.statement_type,
        "page_number": page.page_number,
        "warnings": _decode_warnings(item.validation_warnings),
    }


def _decode_warnings(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    if isinstance(decoded, list):
        return [str(item) for item in decoded]
    return [str(decoded)]


def _item_rows(job: FilingJob) -> list[tuple[FinancialStatementPage, ExtractedDataItem]]:
    rows: list[tuple[FinancialStatementPage, ExtractedDataItem]] = []
    for page in sorted(job.pages, key=lambda page: page.page_number):
        for item in sorted(page.extracted_items, key=lambda row: row.id):
            rows.append((page, item))
    return rows


def build_mapping_diagnostics(job: FilingJob) -> dict[str, Any]:
    rows = _item_rows(job)
    item_diagnostics = []
    for page, item in rows:
        diagnosis = diagnose_azure_di_candidate_mapping(_candidate_from_item(item, page))
        item_diagnostics.append(
            {
                "item_id": item.id,
                "page_number": page.page_number,
                "label": item.extracted_label,
                "value": item.extracted_value,
                "previous_value": item.value_previous_year,
                "statement_type": item.statement_type,
                "template_field_id": item.template_field_id,
                "is_reviewed": item.is_reviewed,
                "stored_warnings": _decode_warnings(item.validation_warnings),
                "diagnosis": diagnosis,
            }
        )

    total = len(rows)
    mapped = [entry for entry in item_diagnostics if entry["template_field_id"]]
    unmapped = [entry for entry in item_diagnostics if not entry["template_field_id"]]
    reviewed = [entry for entry in item_diagnostics if entry["is_reviewed"]]
    statement_counts = Counter(str(entry["statement_type"] or "Unassigned") for entry in item_diagnostics)
    template_presence = Counter("mapped" if entry["template_field_id"] else "unmapped" for entry in item_diagnostics)
    rejection_counts = Counter(
        str((entry["diagnosis"] or {}).get("mapping_rejection_reason") or "mapped")
        for entry in item_diagnostics
    )

    return {
        "job_id": job.id,
        "company_name": job.company_name,
        "status": job.status,
        "read_only": True,
        "total_extracted_rows": total,
        "mapped_rows": len(mapped),
        "unmapped_rows": len(unmapped),
        "reviewed_rows": len(reviewed),
        "rows_by_statement_type": dict(sorted(statement_counts.items())),
        "rows_by_template_field_id_presence": dict(sorted(template_presence.items())),
        "mapping_rejection_reasons": dict(sorted(rejection_counts.items())),
        "unmapped_labels": [
            {
                "label": entry["label"],
                "value": entry["value"],
                "previous_value": entry["previous_value"],
                "page_number": entry["page_number"],
                "statement_type": entry["statement_type"],
                "classification_evidence": entry["diagnosis"].get("statement_classification_evidence"),
                "rejection_reason": entry["diagnosis"].get("mapping_rejection_reason"),
                "top_candidate_matches": entry["diagnosis"].get("top_candidate_matches"),
            }
            for entry in unmapped
        ],
        "items": item_diagnostics,
    }


async def load_job(job_id: int) -> FilingJob | None:
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        result = await session.execute(
            select(FilingJob)
            .options(selectinload(FilingJob.pages).selectinload(FinancialStatementPage.extracted_items))
            .where(FilingJob.id == job_id)
        )
        job = result.scalars().unique().one_or_none()
        if job is not None:
            # Detach loaded graph before rolling back the read-only transaction.
            for page in job.pages:
                list(page.extracted_items)
        await session.rollback()
        return job


def render_text(report: dict[str, Any]) -> str:
    lines = [
        "Azure DI production mapping diagnostics",
        f"job_id: {report['job_id']}",
        f"company_name: {report['company_name']}",
        f"status: {report['status']}",
        f"total_extracted_rows: {report['total_extracted_rows']}",
        f"mapped_rows: {report['mapped_rows']}",
        f"unmapped_rows: {report['unmapped_rows']}",
        f"reviewed_rows: {report['reviewed_rows']}",
        "",
        "Rows by statement_type:",
    ]
    lines.extend(f"  - {key}: {value}" for key, value in report["rows_by_statement_type"].items())
    lines.append("")
    lines.append("Mapping rejection reasons:")
    lines.extend(f"  - {key}: {value}" for key, value in report["mapping_rejection_reasons"].items())
    lines.append("")
    lines.append("Unmapped labels:")
    for row in report["unmapped_labels"]:
        top = row["top_candidate_matches"][0] if row["top_candidate_matches"] else {}
        candidate = f" candidate={top.get('template_field_id')} score={top.get('score')}" if top else ""
        lines.append(
            "  - "
            f"page={row['page_number']} label={row['label']!r} value={row['value']!r} "
            f"statement={row['statement_type']!r} reason={row['rejection_reason']}{candidate}"
        )
    return "\n".join(lines)


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect Azure DI production mapping coverage for one filing job."
    )
    parser.add_argument("--job-id", type=int, required=True, help="filing_jobs.id to inspect.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    parser.add_argument("--output", type=Path, help="Optional path to write the JSON report.")
    args = parser.parse_args()

    job = await load_job(args.job_id)
    if job is None:
        print(f"No filing job found for job_id={args.job_id}", file=sys.stderr)
        return 1

    report = build_mapping_diagnostics(job)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
