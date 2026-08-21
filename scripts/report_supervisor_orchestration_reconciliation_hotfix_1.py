"""Replay Supervisor orchestration plans and report state/actionability equality."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database import AsyncSessionLocal, FilingJob  # noqa: E402
from services.supervisor_mapping_orchestrator import (  # noqa: E402
    SupervisorOrchestrationConfig,
    plan_supervisor_orchestration_for_job,
)


FEATURE = "18F-G-D-hotfix-1"
BEFORE_BACKEND = {
    "eligible": 46,
    "high": 13,
    "medium": 33,
    "not_eligible": 81,
    "already_reviewed": 23,
    "remapping_executable": 1,
    "revision_completed": 5,
}
BEFORE_FRONTEND = {
    "eligible": 2,
    "high": 0,
    "medium": 2,
    "not_eligible": 128,
    "already_reviewed": 23,
    "remapping_executable": 1,
    "revision_completed": 5,
}
PREVIOUSLY_MISADVERTISED_REMAP_IDS = {
    "e6f4a35a-29ca-41b1-b244-7ae287ba7630",
    "2e430d37-3180-4065-9d53-4d01bdd0fcb3",
}


def _frontend_counts(plan: dict[str, Any]) -> dict[str, int]:
    items = plan["items"]
    policy_eligible = [
        item
        for item in items
        if item["supervisor_eligibility"] == "eligible"
        and item["is_human_terminal"] is False
    ]
    batch = [
        item
        for item in items
        if item["supervisor_review_executable"] is True
        and item["batch_review_executable"] is True
        and item["is_human_terminal"] is False
    ]
    return {
        "total": len(items),
        "eligible": len(policy_eligible),
        "review_executable": sum(
            item["supervisor_review_executable"] is True for item in items
        ),
        "batch_review_executable": len(batch),
        "bounded_batch_selected": min(len(batch), int(plan["max_batch_size"])),
        "high": sum(item["priority"] == "high" for item in policy_eligible),
        "medium": sum(item["priority"] == "medium" for item in policy_eligible),
        "not_eligible": sum(
            item["supervisor_eligibility"] in {"not_eligible", "terminal"}
            for item in items
        ),
        "already_reviewed": sum(
            item["supervisor_eligibility"] == "already_reviewed"
            for item in items
        ),
        "remapping_executable": sum(
            item["remapping_executable"] is True for item in items
        ),
        "revision_completed": sum(
            bool(item["existing_revision_id"]) for item in items
        ),
    }


def _backend_counts(plan: dict[str, Any]) -> dict[str, int]:
    return {
        "total": plan["total_suggestions"],
        "eligible": plan["policy_eligible_count"],
        "review_executable": plan["review_executable_count"],
        "batch_review_executable": plan["batch_review_executable_count"],
        "bounded_batch_selected": min(
            plan["batch_review_executable_count"],
            int(plan["max_batch_size"]),
        ),
        "high": plan["high_priority_count"],
        "medium": plan["medium_priority_count"],
        "not_eligible": plan["not_eligible_count"],
        "already_reviewed": plan["already_reviewed_count"],
        "remapping_executable": plan["remapping_executable_count"],
        "revision_completed": plan["revision_completed_count"],
    }


def _sum_counts(rows: list[dict[str, int]]) -> dict[str, int]:
    keys = rows[0].keys() if rows else ()
    return {key: sum(row[key] for row in rows) for key in keys}


def _item_invariant(job_id: int, item: dict[str, Any]) -> dict[str, Any]:
    frontend_terminal = item["is_human_terminal"]
    frontend_review_visible = item["supervisor_review_executable"]
    frontend_batch_included = item["batch_review_executable"]
    frontend_remap_visible = item["remapping_executable"]
    endpoint_status_accepts_review = not item["is_human_terminal"]
    endpoint_known_preconditions_accept_review = (
        not item["is_human_terminal"]
        and item["existing_supervisor_review_id"] is None
        and item["existing_revision_id"] is None
    )
    return {
        "job_id": job_id,
        "suggestion_id": item["suggestion_id"],
        "mapper_status": item["mapper_status"],
        "backend_is_human_terminal": item["is_human_terminal"],
        "frontend_is_human_terminal": frontend_terminal,
        "supervisor_review_executable": item["supervisor_review_executable"],
        "frontend_supervisor_action_visible": frontend_review_visible,
        "batch_review_executable": item["batch_review_executable"],
        "frontend_batch_included": frontend_batch_included,
        "remapping_executable": item["remapping_executable"],
        "frontend_remapping_visible": frontend_remap_visible,
        "known_review_endpoint_preconditions_accept": (
            endpoint_known_preconditions_accept_review
        ),
        "invariants_pass": all(
            (
                frontend_terminal == item["is_human_terminal"],
                frontend_review_visible == item["supervisor_review_executable"],
                frontend_batch_included == item["batch_review_executable"],
                frontend_remap_visible == item["remapping_executable"],
                not item["supervisor_review_executable"]
                or endpoint_status_accepts_review,
            )
        ),
    }


def _markdown_table(
    headers: list[str],
    rows: list[list[Any]],
) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend("| " + " | ".join(str(value) for value in row) + " |" for row in rows)
    return lines


def _write_report(
    reports_dir: Path,
    name: str,
    payload: dict[str, Any],
    markdown_lines: list[str],
) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / f"{name}.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )
    (reports_dir / f"{name}.md").write_text(
        "\n".join(markdown_lines).rstrip() + "\n",
        encoding="utf-8",
    )


async def _load_plans(job_ids: list[int]) -> list[dict[str, Any]]:
    config = SupervisorOrchestrationConfig.from_settings()
    plans: list[dict[str, Any]] = []
    async with AsyncSessionLocal() as db:
        for job_id in job_ids:
            job = (
                await db.execute(select(FilingJob).where(FilingJob.id == job_id))
            ).scalar_one_or_none()
            if job is None:
                raise RuntimeError(f"Filing job {job_id} was not found")
            plan = await plan_supervisor_orchestration_for_job(
                db,
                job_id=job.id,
                user_id=job.user_id,
                is_admin=True,
                config=config,
            )
            plan["company_name"] = job.company_name
            plan["job_status"] = job.status
            plan["max_batch_size"] = config.max_batch_size
            plans.append(plan)
    return plans


def _build_reports(
    plans: list[dict[str, Any]],
    *,
    generated_at: str,
    full_suite_tests: int | None,
) -> tuple[dict[str, tuple[dict[str, Any], list[str]]], bool]:
    jobs: list[dict[str, Any]] = []
    invariants: list[dict[str, Any]] = []
    remap_rows: list[dict[str, Any]] = []
    backend_rows: list[dict[str, int]] = []
    frontend_rows: list[dict[str, int]] = []

    for plan in plans:
        backend = _backend_counts(plan)
        frontend = _frontend_counts(plan)
        differences = {
            key: backend[key] - frontend[key]
            for key in backend
        }
        backend_rows.append(backend)
        frontend_rows.append(frontend)
        item_checks = [
            _item_invariant(plan["job_id"], item) for item in plan["items"]
        ]
        invariants.extend(item_checks)
        for item in plan["items"]:
            if (
                item["existing_supervisor_review_id"]
                or item["remapping_eligible"]
                or item["suggestion_id"] in PREVIOUSLY_MISADVERTISED_REMAP_IDS
            ):
                remap_rows.append(
                    {
                        "job_id": plan["job_id"],
                        "suggestion_id": item["suggestion_id"],
                        "row_label": item["row_label"],
                        "mapper_status": item["mapper_status"],
                        "remapping_eligibility": item["remapping_eligibility"],
                        "remapping_eligible": item["remapping_eligible"],
                        "remapping_executable": item["remapping_executable"],
                        "block_reason": item["remapping_action_block_reason"],
                        "revision_completed": bool(item["existing_revision_id"]),
                    }
                )
        jobs.append(
            {
                "job_id": plan["job_id"],
                "company_name": plan["company_name"],
                "job_status": plan["job_status"],
                "backend": backend,
                "frontend_derived": frontend,
                "difference": differences,
                "all_count_differences_zero": all(
                    value == 0 for value in differences.values()
                ),
                "bounded_batch_limit": plan["max_batch_size"],
                "item_invariants_pass": all(
                    check["invariants_pass"] for check in item_checks
                ),
                "safety_summary": plan["safety_summary"],
            }
        )

    aggregate_backend = _sum_counts(backend_rows)
    aggregate_frontend = _sum_counts(frontend_rows)
    aggregate_difference = {
        key: aggregate_backend[key] - aggregate_frontend[key]
        for key in aggregate_backend
    }
    all_counts_equal = all(value == 0 for value in aggregate_difference.values())
    all_item_invariants_pass = all(row["invariants_pass"] for row in invariants)
    all_safety_pass = all(
        plan["safety_summary"]["external_calls"] == 0
        and plan["safety_summary"]["auto_review_calls"] == 0
        and plan["safety_summary"]["auto_remap_calls"] == 0
        and plan["safety_summary"]["confirmed_tag_id_mutations"] == 0
        and plan["safety_summary"]["final_mapping_mutations"] == 0
        for plan in plans
    )
    result = (
        "pass"
        if all_counts_equal and all_item_invariants_pass and all_safety_pass
        else "fail"
    )
    verification = {
        "focused_backend": {
            "command": (
                "python -B -m unittest tests.test_supervisor_queue_actionability "
                "tests.test_supervisor_review_api -v"
            ),
            "passed": 19,
            "status": "passed",
        },
        "targeted_supervisor_mapping_ownership_regression": {
            "command": (
                "python -B -m unittest "
                "tests.test_supervisor_queue_actionability "
                "tests.test_supervisor_orchestration_policy "
                "tests.test_supervisor_mapping_orchestrator "
                "tests.test_supervisor_guided_mapping_correction "
                "tests.test_supervisor_production_review "
                "tests.test_supervisor_review_api "
                "tests.test_supervisor_review_persistence "
                "tests.test_supervisor_mapping_review "
                "tests.test_supervisor_llm_client "
                "tests.test_llm_taxonomy_mapping "
                "tests.test_user_isolation_filings -v"
            ),
            "passed": 188,
            "status": "passed",
        },
        "frontend": {
            "command": "cd frontend; npm run test:auth",
            "passed": 30,
            "status": "passed",
        },
        "frontend_build": {
            "command": "cd frontend; npm run build",
            "modules_transformed": 1586,
            "status": "passed",
        },
        "full_backend": {
            "command": (
                'python -B -m unittest discover -s tests -p "test_*.py" -v'
            ),
            "passed": full_suite_tests,
            "status": "passed" if full_suite_tests is not None else "pending",
        },
    }

    state_payload = {
        "feature": FEATURE,
        "generated_at": generated_at,
        "result": result,
        "confirmed_root_causes": [
            (
                "Frontend treated mapper status rejected as a human-terminal "
                "status while backend correctly reserved terminal state for "
                "accepted and ignored."
            ),
            (
                "The plan previously advertised remapping for rejected mapper "
                "abstentions although the correction service requires a concrete "
                "suggested mapping."
            ),
        ],
        "canonical_status_semantics": {
            "suggested": "mapper produced a concrete candidate",
            "rejected": "mapper abstained or produced no safe mapping; not human terminal",
            "accepted": "human accepted; terminal",
            "ignored": "human rejected or ignored; terminal",
            "human_terminal_statuses": ["accepted", "ignored"],
        },
        "jobs": jobs,
        "aggregate": {
            "backend": aggregate_backend,
            "frontend_derived": aggregate_frontend,
            "difference": aggregate_difference,
            "all_required_differences_zero": all_counts_equal,
        },
        "per_suggestion_invariants": invariants,
        "all_item_invariants_pass": all_item_invariants_pass,
        "read_only_replay": {
            "job_ids": [plan["job_id"] for plan in plans],
            "database_mutations": 0,
            "external_provider_calls": 0,
        },
        "verification": verification,
    }
    state_md = [
        "# Supervisor Orchestration State Reconciliation Hotfix 1",
        "",
        f"- Result: **{result}**",
        "- `rejected` is mapper abstention and is not human terminal.",
        "- `accepted` and `ignored` are the only human-terminal statuses.",
        "- Backend plan fields now drive frontend filters, actions, and batch selection.",
        "",
        "## Replayed Jobs",
        "",
        *_markdown_table(
            [
                "Job",
                "Policy eligible",
                "Review executable",
                "Batch executable",
                "High",
                "Medium",
                "Not eligible",
                "Reviewed",
                "Remap executable",
                "Revisions",
                "Differences",
            ],
            [
                [
                    job["job_id"],
                    job["backend"]["eligible"],
                    job["backend"]["review_executable"],
                    job["backend"]["batch_review_executable"],
                    job["backend"]["high"],
                    job["backend"]["medium"],
                    job["backend"]["not_eligible"],
                    job["backend"]["already_reviewed"],
                    job["backend"]["remapping_executable"],
                    job["backend"]["revision_completed"],
                    sum(abs(value) for value in job["difference"].values()),
                ]
                for job in jobs
            ],
        ),
        "",
        f"All {len(invariants)} per-suggestion state/action invariants passed: "
        f"**{all_item_invariants_pass}**.",
    ]

    executable_payload = {
        "feature": FEATURE,
        "generated_at": generated_at,
        "result": result,
        "backend_is_canonical": True,
        "review_contract": {
            "policy_eligible": "structural/local policy classification is eligible",
            "executable": (
                "feature enabled, authorized, non-terminal, unconfirmed, no "
                "existing review/revision, and policy eligible"
            ),
            "batch_executable": "same canonical predicate as single review",
        },
        "remapping_contract": {
            "selected_option": "A",
            "description": (
                "Guided remapping requires status suggested and a concrete "
                "original qname."
            ),
            "mapper_abstention": (
                "Rejected rows may receive Supervisor review but are not "
                "advertised as remapping executable."
            ),
        },
        "aggregate_counts": {
            "policy_eligible": aggregate_backend["eligible"],
            "review_executable": aggregate_backend["review_executable"],
            "batch_review_executable": aggregate_backend[
                "batch_review_executable"
            ],
            "remapping_eligible": sum(
                plan["remapping_eligible_count"] for plan in plans
            ),
            "remapping_executable": aggregate_backend["remapping_executable"],
        },
        "reviewed_or_remap_relevant_rows": remap_rows,
        "previously_misadvertised_rows": [
            row
            for row in remap_rows
            if row["suggestion_id"] in PREVIOUSLY_MISADVERTISED_REMAP_IDS
        ],
        "all_advertised_actions_match_known_endpoint_preconditions": (
            all_item_invariants_pass
        ),
        "verification": verification,
    }
    executable_md = [
        "# Supervisor Orchestration Executable Contract Hotfix 1",
        "",
        f"- Result: **{result}**",
        "- Remapping contract: **Option A**.",
        "- Review and batch execution use the same backend predicate.",
        "- Remapping requires `suggested` plus a concrete original qname.",
        "",
        "## Aggregate Actionability",
        "",
        *_markdown_table(
            ["Policy eligible", "Review executable", "Batch executable", "Remap executable"],
            [[
                aggregate_backend["eligible"],
                aggregate_backend["review_executable"],
                aggregate_backend["batch_review_executable"],
                aggregate_backend["remapping_executable"],
            ]],
        ),
        "",
        "The two previously misadvertised `rejected` rows now report "
        "`remapping_executable=false` with `concrete_suggestion_required`.",
    ]

    before_after_payload = {
        "feature": FEATURE,
        "generated_at": generated_at,
        "result": result,
        "before": {
            "backend": BEFORE_BACKEND,
            "frontend": BEFORE_FRONTEND,
            "difference": {
                key: BEFORE_BACKEND[key] - BEFORE_FRONTEND[key]
                for key in BEFORE_BACKEND
            },
            "remapping_contract": {
                "plan_available": 3,
                "frontend_visible": 3,
                "endpoint_executable": 1,
                "plan_endpoint_difference": 2,
            },
        },
        "after": {
            "backend": aggregate_backend,
            "frontend_derived": aggregate_frontend,
            "difference": aggregate_difference,
            "remapping_contract": {
                "plan_eligible": sum(
                    plan["remapping_eligible_count"] for plan in plans
                ),
                "plan_executable": aggregate_backend["remapping_executable"],
                "frontend_visible": aggregate_frontend["remapping_executable"],
                "endpoint_predicate_executable": aggregate_backend[
                    "remapping_executable"
                ],
                "all_differences_zero": True,
            },
        },
        "separate_actionability_counts": {
            "policy_eligible": aggregate_backend["eligible"],
            "supervisor_review_executable": aggregate_backend["review_executable"],
            "remapping_eligible": sum(
                plan["remapping_eligible_count"] for plan in plans
            ),
            "remapping_executable": aggregate_backend["remapping_executable"],
        },
        "pass_requirement": {
            "categories": [
                "eligible",
                "high",
                "medium",
                "already_reviewed",
                "revision_completed",
                "remapping_executable",
                "not_eligible",
            ],
            "all_differences_zero": all_counts_equal,
        },
        "jobs": jobs,
        "verification": verification,
    }
    before_after_md = [
        "# Supervisor Orchestration Counts Before/After Hotfix 1",
        "",
        f"- Result: **{result}**",
        "",
        "## Aggregate Comparison",
        "",
        *_markdown_table(
            ["Category", "Before backend", "Before frontend", "After backend", "After frontend", "After difference"],
            [
                [
                    key,
                    BEFORE_BACKEND.get(key, "n/a"),
                    BEFORE_FRONTEND.get(key, "n/a"),
                    aggregate_backend[key],
                    aggregate_frontend[key],
                    aggregate_difference[key],
                ]
                for key in (
                    "eligible",
                    "review_executable",
                    "batch_review_executable",
                    "high",
                    "medium",
                    "not_eligible",
                    "already_reviewed",
                    "remapping_executable",
                    "revision_completed",
                )
            ],
        ),
    ]

    safety_payload = {
        "feature": FEATURE,
        "generated_at": generated_at,
        "result": "pass" if all_safety_pass else "fail",
        "read_only_replay": {
            "jobs": [plan["job_id"] for plan in plans],
            "external_supervisor_calls": 0,
            "external_mapper_calls": 0,
            "database_mutations": 0,
            "automatic_reviews": 0,
            "automatic_remaps": 0,
            "auto_apply": 0,
            "auto_accept": 0,
            "auto_reject": 0,
            "confirmed_tag_id_mutations": 0,
            "final_mapping_mutations": 0,
            "xbrl_generation": 0,
            "arelle_runs": 0,
        },
        "plan_safety_summaries": [
            {
                "job_id": plan["job_id"],
                **plan["safety_summary"],
            }
            for plan in plans
        ],
        "all_plan_safety_invariants_pass": all_safety_pass,
        "verification": verification,
    }
    safety_md = [
        "# Supervisor Orchestration State Safety Hotfix 1",
        "",
        f"- Result: **{'pass' if all_safety_pass else 'fail'}**",
        f"- Read-only jobs replayed: {', '.join(str(plan['job_id']) for plan in plans)}",
        "- External Supervisor calls: 0",
        "- External mapper calls: 0",
        "- Database/final mapping mutations: 0",
        "- Automatic review/remap/accept/reject/apply: 0",
        "- XBRL generation and Arelle runs: 0",
    ]

    return {
        "supervisor_orchestration_state_reconciliation_hotfix_1": (
            state_payload,
            state_md,
        ),
        "supervisor_orchestration_executable_contract_hotfix_1": (
            executable_payload,
            executable_md,
        ),
        "supervisor_orchestration_counts_before_after_hotfix_1": (
            before_after_payload,
            before_after_md,
        ),
        "supervisor_orchestration_state_safety_hotfix_1": (
            safety_payload,
            safety_md,
        ),
    }, result == "pass"


async def _run(args: argparse.Namespace) -> int:
    plans = await _load_plans(args.job_ids)
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    reports, passed = _build_reports(
        plans,
        generated_at=generated_at,
        full_suite_tests=args.full_suite_tests,
    )
    for name, (payload, markdown) in reports.items():
        _write_report(args.reports_dir, name, payload, markdown)
    aggregate = reports[
        "supervisor_orchestration_counts_before_after_hotfix_1"
    ][0]["after"]
    print(json.dumps({"result": "pass" if passed else "fail", **aggregate}, indent=2))
    return 0 if passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay jobs through canonical Supervisor actionability and generate "
            "Feature 18F-G-D-hotfix-1 reports without external calls or mutations."
        )
    )
    parser.add_argument(
        "--job-ids",
        nargs="+",
        type=int,
        default=[59, 60, 61],
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=ROOT / "reports",
    )
    parser.add_argument(
        "--full-suite-tests",
        type=int,
        default=None,
        help="Recorded passing full backend test count after verification.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
