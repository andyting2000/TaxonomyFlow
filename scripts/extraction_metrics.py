import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from database import AsyncSessionLocal, ExtractedDataItem, FilingJob, FinancialStatementPage


NEGATIVE_VALUE_RE = re.compile(r"(^|[^\d])- ?\d|\(\s*[\d,]+(?:\.\d+)?\s*\)")


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _has_template_field(item: ExtractedDataItem) -> bool:
    return bool(str(item.template_field_id or "").strip())


def _has_blank_statement_type(item: ExtractedDataItem) -> bool:
    return not bool(str(item.statement_type or "").strip())


def _has_suspicious_signed_value(item: ExtractedDataItem) -> bool:
    values = [item.extracted_value, item.value_previous_year]
    return any(NEGATIVE_VALUE_RE.search(str(value or "")) for value in values)


def _duplicate_excess_count(keys: Iterable[str]) -> int:
    counts = Counter(key for key in keys if key)
    return sum(count - 1 for count in counts.values() if count > 1)


def calculate_job_metrics(job: FilingJob) -> Dict[str, Any]:
    items: List[ExtractedDataItem] = [
        item
        for page in sorted(job.pages, key=lambda page: page.page_number)
        for item in page.extracted_items
    ]

    label_keys = [_normalize_text(item.extracted_label) for item in items]
    label_value_keys = [
        f"{_normalize_text(item.extracted_label)}|{_normalize_text(item.extracted_value)}"
        for item in items
    ]

    reviewed_count = sum(1 for item in items if item.is_reviewed)
    tagged_count = sum(1 for item in items if item.confirmed_tag_id is not None)

    return {
        "job_id": job.id,
        "company_name": job.company_name,
        "status": job.status,
        "page_count": len(job.pages),
        "total_extracted_rows": len(items),
        "rows_with_template_field_id": sum(1 for item in items if _has_template_field(item)),
        "rows_without_template_field_id": sum(1 for item in items if not _has_template_field(item)),
        "rows_with_blank_statement_type": sum(1 for item in items if _has_blank_statement_type(item)),
        "duplicate_label_count": _duplicate_excess_count(label_keys),
        "duplicate_label_value_count": _duplicate_excess_count(label_value_keys),
        "suspicious_signed_value_count": sum(1 for item in items if _has_suspicious_signed_value(item)),
        "reviewed_count": reviewed_count,
        "tagged_count": tagged_count,
        "reviewed_or_tagged_count": sum(
            1 for item in items if item.is_reviewed or item.confirmed_tag_id is not None
        ),
    }


def render_console_report(metrics: Sequence[Dict[str, Any]], missing_job_ids: Sequence[int]) -> str:
    lines = [
        "Extraction metrics baseline",
        "Mode: read-only inspection of existing filing jobs",
        "",
    ]

    if metrics:
        for metric in metrics:
            lines.extend(
                [
                    f"Job {metric['job_id']} - {metric['company_name']} ({metric['status']})",
                    f"  page_count: {metric['page_count']}",
                    f"  total_extracted_rows: {metric['total_extracted_rows']}",
                    f"  rows_with_template_field_id: {metric['rows_with_template_field_id']}",
                    f"  rows_without_template_field_id: {metric['rows_without_template_field_id']}",
                    f"  rows_with_blank_statement_type: {metric['rows_with_blank_statement_type']}",
                    f"  duplicate_label_count: {metric['duplicate_label_count']}",
                    f"  duplicate_label_value_count: {metric['duplicate_label_value_count']}",
                    f"  suspicious_signed_value_count: {metric['suspicious_signed_value_count']}",
                    f"  reviewed_count: {metric['reviewed_count']}",
                    f"  tagged_count: {metric['tagged_count']}",
                    f"  reviewed_or_tagged_count: {metric['reviewed_or_tagged_count']}",
                    "",
                ]
            )
    else:
        lines.extend(["No requested jobs were found.", ""])

    if missing_job_ids:
        lines.append("Missing jobs:")
        lines.extend(f"  - {job_id}" for job_id in missing_job_ids)
        lines.append("")

    lines.append("Note: duplicate counts are duplicate rows beyond the first normalized match.")
    lines.append("Note: suspicious signed values are rows with an explicit negative sign or parentheses in current/previous values.")
    return "\n".join(lines)


async def load_metrics(job_ids: Sequence[int]) -> Dict[str, Any]:
    unique_job_ids = list(dict.fromkeys(job_ids))

    async with AsyncSessionLocal() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        stmt = (
            select(FilingJob)
            .options(
                selectinload(FilingJob.pages).selectinload(FinancialStatementPage.extracted_items)
            )
            .where(FilingJob.id.in_(unique_job_ids))
        )
        result = await session.execute(stmt)
        jobs = result.scalars().unique().all()
        jobs_by_id = {job.id: job for job in jobs}
        metrics = [
            calculate_job_metrics(jobs_by_id[job_id])
            for job_id in unique_job_ids
            if job_id in jobs_by_id
        ]
        missing_job_ids = [job_id for job_id in unique_job_ids if job_id not in jobs_by_id]
        await session.rollback()

    return {
        "requested_job_ids": unique_job_ids,
        "metrics": metrics,
        "missing_job_ids": missing_job_ids,
        "read_only": True,
    }


async def async_main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect extraction quality metrics for existing filing jobs."
    )
    parser.add_argument(
        "--jobs",
        nargs="+",
        type=int,
        required=True,
        help="Filing job IDs to inspect, e.g. --jobs 3 4 5",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of the copy-friendly console report.",
    )
    args = parser.parse_args()

    report = await load_metrics(args.jobs)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(render_console_report(report["metrics"], report["missing_job_ids"]))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
