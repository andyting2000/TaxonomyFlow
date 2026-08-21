"""Manual Azure DI production extraction smoke for one approved PDF."""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select  # noqa: E402

from database import AsyncSessionLocal, ExtractedDataItem, FilingJob, FinancialStatementPage  # noqa: E402
from file_safety import build_upload_pdf_path  # noqa: E402
from services.azure_di_production_extraction import process_azure_di_filing_job  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the production Azure DI extraction path against one human-approved sample PDF."
    )
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--company-name", required=True)
    parser.add_argument("--registration-number", default="AZURE-DI-SMOKE")
    parser.add_argument("--financial-year-end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--approve-azure-document-intelligence-upload", action="store_true")
    parser.add_argument("--approve-db-mutation", action="store_true")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    if not args.approve_azure_document_intelligence_upload:
        print("Refusing to upload PDF to Azure DI without --approve-azure-document-intelligence-upload.", file=sys.stderr)
        return 2
    if not args.approve_db_mutation:
        print("Refusing to create a smoke filing job without --approve-db-mutation.", file=sys.stderr)
        return 2
    if not args.pdf.exists() or args.pdf.suffix.lower() != ".pdf":
        print(f"PDF input does not exist or is not a PDF: {args.pdf}", file=sys.stderr)
        return 2

    destination = build_upload_pdf_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(args.pdf, destination)

    async with AsyncSessionLocal() as db:
        job = FilingJob(
            user_id=args.user_id,
            company_name=args.company_name,
            registration_number=args.registration_number,
            financial_year_end=datetime.strptime(args.financial_year_end, "%Y-%m-%d"),
            source_pdf_path=str(destination),
            status="PROCESSING",
        )
        db.add(job)
        await db.flush()
        await db.commit()

        result = await process_azure_di_filing_job(job.id, db)
        await db.refresh(job)

        pages_count = (
            await db.execute(
                select(func.count(FinancialStatementPage.id)).where(FinancialStatementPage.job_id == job.id)
            )
        ).scalar() or 0
        rows_count = (
            await db.execute(
                select(func.count(ExtractedDataItem.id))
                .join(FinancialStatementPage)
                .where(FinancialStatementPage.job_id == job.id)
            )
        ).scalar() or 0
        print(f"Azure DI called=true")
        print(f"legacy_smart_ai_processor_process_pdf_called=false")
        print(f"db_mutated=true")
        print(f"job_id={job.id}")
        print(f"job_status={job.status}")
        print(f"result_status={result.status.value}")
        print(f"result_message={result.message or result.error}")
        print(f"pages_count={pages_count}")
        print(f"extracted_rows_count={rows_count}")
        return 0 if job.status in {"REVIEW", "ERROR"} else 1


def main() -> int:
    return asyncio.run(run(parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
