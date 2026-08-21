"""Inspect Azure DI production jobs without mutating the database."""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from sqlalchemy import text

from database import engine


JOB_COLUMNS = [
    "id",
    "user_id",
    "company_name",
    "status",
    "progress",
    "error_message",
    "uploaded_at",
    "source_pdf_path",
]


async def _columns(conn, table_name: str) -> set[str]:
    result = await conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = :table_name
            """
        ),
        {"table_name": table_name},
    )
    return {str(row[0]) for row in result.fetchall()}


async def _counts(conn, job_id: int) -> tuple[int, int]:
    pages = await conn.execute(
        text("SELECT COUNT(*) FROM financial_statement_pages WHERE job_id = :job_id"),
        {"job_id": job_id},
    )
    items = await conn.execute(
        text(
            """
            SELECT COUNT(*)
            FROM extracted_data_items item
            JOIN financial_statement_pages page ON page.id = item.page_id
            WHERE page.job_id = :job_id
            """
        ),
        {"job_id": job_id},
    )
    return int(pages.scalar() or 0), int(items.scalar() or 0)


def _print_job(row: dict[str, Any], pages_count: int, items_count: int) -> None:
    print(f"job_id={row.get('id')}")
    print(f"user_id={row.get('user_id')}")
    print(f"status={row.get('status')}")
    print(f"progress={row.get('progress')}")
    print(f"error_message={row.get('error_message')}")
    print(f"uploaded_at={row.get('uploaded_at')}")
    print(f"source_pdf_path={row.get('source_pdf_path')}")
    print(f"pages_count={pages_count}")
    print(f"extracted_items_count={items_count}")
    print("")


async def inspect_jobs(job_id: int | None, processing_only: bool, limit: int) -> None:
    async with engine.begin() as conn:
        columns = await _columns(conn, "filing_jobs")
        selected = [
            column if column in columns else f"NULL AS {column}"
            for column in JOB_COLUMNS
        ]
        sql = f"SELECT {', '.join(selected)} FROM filing_jobs"
        params: dict[str, Any] = {}
        predicates = []
        if job_id is not None:
            predicates.append("id = :job_id")
            params["job_id"] = job_id
        if processing_only:
            predicates.append("status = 'PROCESSING'")
        if predicates:
            sql += " WHERE " + " AND ".join(predicates)
        sql += " ORDER BY uploaded_at DESC LIMIT :limit"
        params["limit"] = limit

        result = await conn.execute(text(sql), params)
        rows = [dict(row._mapping) for row in result.fetchall()]
        if not rows:
            print("No matching filing jobs found.")
            return

        for row in rows:
            pages_count, items_count = await _counts(conn, int(row["id"]))
            _print_job(row, pages_count, items_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect Azure DI filing job status, progress, errors, pages, and extracted rows."
    )
    parser.add_argument("--job-id", type=int, help="Specific filing_jobs.id to inspect.")
    parser.add_argument(
        "--processing-only",
        action="store_true",
        help="Show only jobs still marked PROCESSING.",
    )
    parser.add_argument("--limit", type=int, default=10, help="Maximum jobs to print.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(inspect_jobs(args.job_id, args.processing_only, args.limit))


if __name__ == "__main__":
    main()

