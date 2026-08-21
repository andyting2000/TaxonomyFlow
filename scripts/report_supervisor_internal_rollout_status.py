"""Export a read-only Supervisor rollout operational snapshot."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import AsyncSessionLocal, FilingJob  # noqa: E402
from services.supervisor_guided_mapping_correction import (  # noqa: E402
    list_supervisor_guided_revisions_for_job,
)
from services.supervisor_mapping_orchestrator import (  # noqa: E402
    SupervisorOrchestrationConfig,
    build_supervisor_orchestration_plan,
)
from services.supervisor_production_review import (  # noqa: E402
    list_ai_mapping_suggestions_for_supervisor,
    list_supervisor_reviews_for_job,
)
from services.supervisor_rollout_observability import (  # noqa: E402
    build_supervisor_rollout_operational_report,
)


def parse_job_ids(value: str) -> list[int]:
    job_ids: list[int] = []
    for raw in value.split(","):
        entry = raw.strip()
        if not entry:
            continue
        try:
            job_id = int(entry)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"Invalid job ID: {entry!r}"
            ) from exc
        if job_id <= 0:
            raise argparse.ArgumentTypeError("Job IDs must be positive integers.")
        job_ids.append(job_id)
    if not job_ids:
        raise argparse.ArgumentTypeError("At least one job ID is required.")
    return sorted(set(job_ids))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read existing Supervisor plans/reviews/revisions for selected jobs "
            "and emit a non-sensitive rollout audit snapshot. No provider call "
            "or database mutation is performed."
        )
    )
    parser.add_argument(
        "--job-ids",
        required=True,
        type=parse_job_ids,
        help="Comma-separated filing job IDs.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON output path. Without this option, JSON is printed.",
    )
    return parser.parse_args(argv)


async def build_report(job_ids: list[int]) -> dict:
    plans = []
    reviews = []
    revisions = []
    suggestions = []
    missing_job_ids = []
    config = SupervisorOrchestrationConfig.from_settings()

    async with AsyncSessionLocal() as db:
        for job_id in job_ids:
            result = await db.execute(
                select(FilingJob).where(FilingJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if job is None:
                missing_job_ids.append(job_id)
                continue
            job_suggestions = await list_ai_mapping_suggestions_for_supervisor(
                db,
                job_id=job.id,
            )
            job_reviews = await list_supervisor_reviews_for_job(db, job_id=job.id)
            job_revisions = await list_supervisor_guided_revisions_for_job(
                db,
                job_id=job.id,
            )
            plans.append(
                build_supervisor_orchestration_plan(
                    job=job,
                    suggestions=job_suggestions,
                    reviews=job_reviews,
                    revisions=job_revisions,
                    config=config,
                    is_admin=True,
                    user_id=job.user_id,
                )
            )
            suggestions.extend(job_suggestions)
            reviews.extend(job_reviews)
            revisions.extend(job_revisions)

    report = build_supervisor_rollout_operational_report(
        plans=plans,
        reviews=reviews,
        revisions=revisions,
        suggestions=suggestions,
    )
    report["requested_job_ids"] = job_ids
    report["missing_job_ids"] = missing_job_ids
    report["provider_calls"] = 0
    report["database_mutations"] = 0
    return report


async def async_main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = await build_report(args.job_ids)
    encoded = json.dumps(report, indent=2, ensure_ascii=True, default=str)
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")
        print(output)
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
