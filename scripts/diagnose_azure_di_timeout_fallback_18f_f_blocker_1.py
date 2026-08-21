"""Write the #18F-F-blocker-1 Azure DI timeout fallback diagnostic reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def build_report() -> dict:
    return {
        "feature": "18F-F-blocker-1",
        "title": "Azure DI local normalization timeout fallback",
        "root_cause": (
            "asyncio.wait_for timed out the local normalization coroutine, but its "
            "asyncio.to_thread worker could not be cancelled. The worker later logged "
            "usable normalized candidates after the coroutine had already entered the "
            "fatal timeout handler and marked the job ERROR."
        ),
        "affected_job_evidence": {
            "job_id": 48,
            "azure_submit_status": 202,
            "azure_result_status": 200,
            "pages_count": 23,
            "tables_count": 17,
            "table_cells": 607,
            "content_length": 30570,
            "table_candidate_count": 96,
            "deduped_candidate_count": 93,
            "normalized_candidates_count": 83,
            "incorrect_final_status_before_hotfix": "ERROR",
            "interpretation": "Local normalization timeout, not an Azure DI service limit failure.",
        },
        "non_fatal_classification": [
            "Outer local normalization timeout after a valid Azure result with pages and table evidence",
            "Text-block or paragraph normalization timeout when table-only normalization returns persistable candidates",
        ],
        "fatal_classification": [
            "Azure DI configuration, submit, or analyze-result failure",
            "Azure DI result with no usable pages/table evidence",
            "Table-only fallback with zero persistable candidates",
            "Table-only fallback timeout or normalization failure",
            "Database persistence failure",
        ],
        "fallback_behavior": {
            "enabled_by_default": True,
            "config": "AZURE_DI_ALLOW_TABLE_FALLBACK_ON_TEXT_TIMEOUT=true",
            "input": "Already-received local Azure DI result",
            "mode": "One bounded table-only normalization attempt",
            "success_status": "REVIEW",
            "warning_code": "azure_di_text_block_normalization_timeout",
            "fallback_used": "table_candidates_only",
            "warning_storage": "Existing ExtractedDataItem.validation_warnings JSON; no migration",
            "fatal_if_no_persistable_candidates": True,
        },
        "tests_added": [
            "service result + outer timeout + tables completes with warning",
            "normalized fallback rows and structured warning metadata persist",
            "outer timeout + zero table candidates remains ERROR",
            "submit failure remains ERROR",
            "analyze failure remains ERROR",
        ],
        "manual_retest": [
            "Restart backend and Celery workers so the hotfix is loaded.",
            "Upload the INFO House PDF once, or reuse a cached raw result if an existing isolated path supports it.",
            "Confirm the job reaches REVIEW rather than ERROR when the local text-block timeout occurs.",
            "Confirm extracted rows are greater than zero and Review Workspace loads them.",
            "Confirm logs and row validation_warnings contain azure_di_text_block_normalization_timeout and table_candidates_only.",
        ],
        "safety": {
            "live_azure_di_called": False,
            "llm_qwen_supervisor_called": False,
            "xbrl_generated": False,
            "arelle_run": False,
            "auto_mapping_changed": False,
            "confirmed_tag_id_automation": False,
        },
        "recommended_next_feature_after_manual_retest": (
            "Feature #18F-G - Decide next path: persistence design vs reviewer UX workflow"
        ),
    }


def render_markdown(report: dict) -> str:
    evidence = report["affected_job_evidence"]
    fallback = report["fallback_behavior"]
    lines = [
        "# Azure DI Timeout Fallback - #18F-F-blocker-1",
        "",
        "## Root Cause",
        "",
        report["root_cause"],
        "",
        "Job 48 confirms Azure DI returned successfully before local normalization failed: "
        f"pages={evidence['pages_count']}, tables={evidence['tables_count']}, "
        f"table cells={evidence['table_cells']}, table candidates={evidence['table_candidate_count']}, "
        f"normalized candidates={evidence['normalized_candidates_count']}.",
        "",
        "## Fallback",
        "",
        f"A local timeout now triggers {fallback['mode'].lower()} from the cached Azure result. "
        "The job reaches `REVIEW` only if persistable candidates exist. Structured warning metadata "
        "is stored in existing row validation warnings; no database migration is required.",
        "",
        "## Fatal Conditions",
        "",
    ]
    lines.extend(f"- {item}" for item in report["fatal_classification"])
    lines.extend(["", "## Manual Retest", ""])
    lines.extend(f"{index}. {item}" for index, item in enumerate(report["manual_retest"], 1))
    lines.extend([
        "",
        "Recommended next feature after a successful INFO House retest: "
        "#18F-G - Decide next path: persistence design vs reviewer UX workflow.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report = build_report()
    json_path = output_dir / "azure_di_timeout_fallback_18f_f_blocker_1.json"
    md_path = output_dir / "azure_di_timeout_fallback_18f_f_blocker_1.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
