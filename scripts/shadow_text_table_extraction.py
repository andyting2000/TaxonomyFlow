"""Run the read-only text/table-first shadow extractor for existing filing jobs."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import AsyncSessionLocal, FilingJob, FinancialStatementPage
from services.shadow_text_table_extractor import ShadowTextTableExtractor, flatten_candidates, utc_timestamp


REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_BENCHMARK_JOBS = [13, 14, 15, 18, 19, 20, 23]


async def load_jobs(job_ids: Sequence[int]) -> tuple[list[FilingJob], list[int]]:
    unique_job_ids = list(dict.fromkeys(job_ids))
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        stmt = (
            select(FilingJob)
            .options(selectinload(FilingJob.pages))
            .where(FilingJob.id.in_(unique_job_ids))
        )
        result = await session.execute(stmt)
        jobs = result.scalars().unique().all()
        jobs_by_id = {int(job.id): job for job in jobs}
        ordered_jobs = [jobs_by_id[job_id] for job_id in unique_job_ids if job_id in jobs_by_id]
        missing_jobs = [job_id for job_id in unique_job_ids if job_id not in jobs_by_id]
        session.expunge_all()
        await session.rollback()
    return ordered_jobs, missing_jobs


async def build_shadow_report(
    job_ids: Sequence[int],
    *,
    limit_pages: int | None = None,
    use_openai: bool = False,
    output_json: Path | None = None,
) -> dict[str, Any]:
    jobs, missing_jobs = await load_jobs(job_ids)
    extractor = ShadowTextTableExtractor(openai_enabled=use_openai)
    job_reports: list[dict[str, Any]] = []

    for job in jobs:
        pages = sorted(job.pages or [], key=lambda page: page.page_number or 0)
        page_ids_by_number = {
            int(page.page_number): str(page.id)
            for page in pages
            if page.page_number is not None
        }
        job_report = await extractor.extract_pdf(
            job.source_pdf_path,
            job_id=int(job.id),
            page_ids_by_number=page_ids_by_number,
            limit_pages=limit_pages,
            use_openai=use_openai,
        )
        job_report["job_metadata"] = {
            "job_id": int(job.id),
            "company_name": job.company_name,
            "registration_number": job.registration_number,
            "financial_year_end": job.financial_year_end.isoformat() if job.financial_year_end else None,
            "status": job.status,
            "source_pdf_path": job.source_pdf_path,
            "db_page_count": len(pages),
        }
        job_reports.append(job_report)

    candidates = flatten_candidates(job_reports)
    warning_counts = Counter(
        warning
        for candidate in candidates
        for warning in candidate.get("warnings", [])
    )
    row_type_counts = Counter(candidate.get("row_type") or "unknown" for candidate in candidates)
    method_counts = Counter(candidate.get("extraction_method") or "unknown" for candidate in candidates)
    output_path = output_json or REPORTS_DIR / f"shadow_text_table_extraction_{utc_timestamp()}.json"

    return {
        "run_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "script": "scripts/shadow_text_table_extraction.py",
            "read_only": True,
            "database_mutated": False,
            "production_behavior_changed": False,
            "openai_used": bool(use_openai),
            "limit_pages": limit_pages,
            "output_path": str(output_path),
        },
        "selected_jobs": list(dict.fromkeys(job_ids)),
        "default_benchmark_jobs": DEFAULT_BENCHMARK_JOBS,
        "missing_jobs": missing_jobs,
        "job_reports": job_reports,
        "candidates": candidates,
        "aggregate_metrics": {
            "jobs_analyzed": len(job_reports),
            "candidate_count": len(candidates),
            "numeric_fact_count": row_type_counts.get("numeric_fact", 0),
            "text_block_count": row_type_counts.get("text_block", 0),
            "heading_count": row_type_counts.get("heading", 0),
            "subtotal_or_total_count": row_type_counts.get("subtotal_or_total", 0),
            "method_counts": dict(sorted(method_counts.items())),
            "row_type_counts": dict(sorted(row_type_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
        },
        "limitations": [
            "Shadow prototype only; no database rows are inserted, updated, or deleted.",
            "Native text/table heuristics are intentionally conservative and are not a production cutover.",
            "OpenAI vision fallback runs only when --use-openai is supplied.",
            "No taxonomy mapping, XBRL generation, Arelle validation, or production processing is performed.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate_metrics"]
    lines = [
        "# Shadow Text/Table Extraction Report",
        "",
        "## Executive Summary",
        "",
        f"- Jobs analyzed: {aggregate['jobs_analyzed']}",
        f"- Shadow candidates: {aggregate['candidate_count']}",
        f"- Numeric facts: {aggregate['numeric_fact_count']}",
        f"- Text blocks: {aggregate['text_block_count']}",
        f"- OpenAI used: {report['run_metadata']['openai_used']}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        "",
        "## Jobs",
        "",
        "| Job | Status | Company | Pages | Candidates | Numeric Facts | Text Blocks | Warnings |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for job_report in report["job_reports"]:
        meta = job_report.get("job_metadata", {})
        warning_total = sum((job_report.get("warning_counts") or {}).values())
        lines.append(
            "| {job_id} | {status} | {company} | {pages} | {candidates} | {numeric} | {text_blocks} | {warnings} |".format(
                job_id=meta.get("job_id"),
                status=meta.get("status") or job_report.get("status") or "",
                company=str(meta.get("company_name") or "").replace("|", "\\|"),
                pages=job_report.get("pages_analyzed", 0),
                candidates=job_report.get("candidate_count", 0),
                numeric=job_report.get("numeric_fact_count", 0),
                text_blocks=job_report.get("text_block_count", 0),
                warnings=warning_total,
            )
        )
    lines.extend(["", "## Aggregate Warnings", ""])
    warning_counts = aggregate.get("warning_counts") or {}
    if warning_counts:
        for warning, count in warning_counts.items():
            lines.append(f"- {warning}: {count}")
    else:
        lines.append("- none")
    lines.extend([
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in report.get("limitations", [])],
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only shadow text/table-first extraction.")
    parser.add_argument("--jobs", nargs="+", type=int, default=DEFAULT_BENCHMARK_JOBS)
    parser.add_argument("--limit-pages", type=int)
    parser.add_argument("--use-openai", action="store_true", help="Allow explicit OpenAI vision fallback.")
    parser.add_argument("--no-openai", action="store_true", help="Disable OpenAI vision fallback. This is the default.")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    selected_jobs = list(dict.fromkeys(args.jobs))
    use_openai = bool(args.use_openai and not args.no_openai)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_json = args.output_json or REPORTS_DIR / f"shadow_text_table_extraction_{utc_timestamp()}.json"
    output_md = args.output_md or output_json.with_suffix(".md")

    report = await build_shadow_report(
        selected_jobs,
        limit_pages=args.limit_pages,
        use_openai=use_openai,
        output_json=output_json,
    )
    output_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")

    print(f"Shadow extraction report: {output_json}")
    print(f"Markdown summary: {output_md}")
    print(f"Jobs analyzed: {report['aggregate_metrics']['jobs_analyzed']}")
    print(f"Candidates: {report['aggregate_metrics']['candidate_count']}")
    if report["missing_jobs"]:
        print(f"Missing jobs: {', '.join(str(job_id) for job_id in report['missing_jobs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
