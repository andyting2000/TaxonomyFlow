"""Smoke/report runner for backend LLM taxonomy mapping suggestions."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import AsyncSessionLocal  # noqa: E402
from services.llm_taxonomy_mapping import (  # noqa: E402
    HuggingFaceQwenMappingClient,
    MockQwenMappingClient,
    run_llm_mapping_for_job,
    run_llm_mapping_for_loaded_job,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate candidate-constrained LLM taxonomy mapping suggestions for one filing job."
    )
    parser.add_argument("--job-id", type=int, required=True, help="filing_jobs.id to inspect.")
    parser.add_argument("--mock", action="store_true", help="Use deterministic local mock LLM responses.")
    parser.add_argument("--use-live-llm", action="store_true", help="Call the configured Qwen text model.")
    parser.add_argument(
        "--apply-high-confidence",
        action="store_true",
        help="Apply only valid high-confidence suggestions to currently unassigned extracted rows.",
    )
    parser.add_argument(
        "--include-mapped",
        action="store_true",
        help="Include already mapped rows for audit; they are still not overwritten by default.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("reports"))
    return parser


def _report_paths(output_dir: Path, job_id: int) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    base = output_dir / f"llm_taxonomy_mapping_suggestions_{job_id}"
    return base.with_suffix(".json"), base.with_suffix(".md")


def _write_reports(report: dict[str, Any], output_dir: Path, job_id: int) -> tuple[Path, Path]:
    json_path, md_path = _report_paths(output_dir, job_id)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True, default=str), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, md_path


def _safe_database_error(exc: Exception) -> str:
    text = str(exc)
    if "UndefinedTableError" in text and "llm_mapping_suggestions" in text:
        return "llm_mapping_suggestions table is not available; apply migrations/009_add_llm_mapping_suggestions.sql."
    first_line = text.splitlines()[0] if text else exc.__class__.__name__
    return first_line[:300]


def render_markdown_report(report: dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    metadata = report.get("run_metadata") or {}
    lines = [
        "# LLM Taxonomy Mapping Suggestions",
        "",
        f"- Job ID: {report.get('job_id')}",
        f"- Company: {report.get('company_name')}",
        f"- Model: {metadata.get('model_id')}",
        f"- LLM called: {metadata.get('llm_called')}",
        f"- Candidate constrained: {metadata.get('candidate_constrained')}",
        f"- Apply mode: {metadata.get('auto_apply_high_confidence')}",
        "",
        "## Summary",
        "",
        f"- Total rows: {summary.get('total_rows', 0)}",
        f"- Already mapped rows: {summary.get('already_mapped_rows', 0)}",
        f"- Rows considered: {summary.get('rows_considered', 0)}",
        f"- Rows sent to LLM: {summary.get('rows_sent_to_llm', 0)}",
        f"- Display suggestions generated: {summary.get('display_suggestions_generated', summary.get('suggestions_generated', 0))}",
        f"- High-confidence suggestions: {summary.get('high_confidence_suggestions', 0)}",
        f"- Medium-confidence suggestions: {summary.get('medium_confidence_suggestions', 0)}",
        f"- Low-confidence suggestions: {summary.get('low_confidence_suggestions', 0)}",
        f"- Rejected rows: {summary.get('rejected_rows', 0)}",
        f"- Rejected precheck rows: {summary.get('rejected_precheck_rows', 0)}",
        f"- Rejected low-confidence rows: {summary.get('rejected_low_confidence_rows', 0)}",
        f"- Rejected no-candidate rows: {summary.get('rejected_no_candidate_rows', 0)}",
        f"- Candidate coverage rate: {summary.get('candidate_coverage_rate', 0)}",
        f"- Invalid LLM responses: {summary.get('invalid_llm_responses', 0)}",
        f"- Hallucinated concept rejections: {summary.get('hallucinated_concept_rejections', 0)}",
        f"- Before mapped count: {summary.get('before_mapped_count', 0)}",
        f"- After mapped count: {summary.get('after_mapped_count', 0)}",
        f"- Applied suggestions: {summary.get('applied_suggestions', 0)}",
        "",
        "## Suggestions",
        "",
    ]
    for row in report.get("rows") or []:
        suggestion = row.get("suggestion") or {}
        selected = suggestion.get("selected_template_field_id")
        rejection = suggestion.get("rejection_reason")
        lines.append(
            "- "
            f"page={row.get('page_number')} "
            f"label={row.get('extracted_label')!r} "
            f"selected={selected or 'null'} "
            f"confidence={suggestion.get('confidence')} "
            f"status={suggestion.get('status')} "
            f"rejection={rejection}"
        )
    return "\n".join(lines) + "\n"


def _mock_loaded_job(job_id: int) -> Any:
    rows = [
        SimpleNamespace(
            id="mock-item-revenue",
            extracted_label="Revenue",
            extracted_value="1000",
            value_previous_year="900",
            financial_year=2026,
            financial_year_previous=2025,
            statement_type="Statement of Profit or Loss (By Function)",
            template_field_id=None,
            template_position=None,
            is_required_field=False,
            is_reviewed=False,
            confirmed_tag_id=None,
            validation_warnings=None,
        ),
        SimpleNamespace(
            id="mock-item-company",
            extracted_label="Example Sdn Bhd",
            extracted_value="1000",
            value_previous_year=None,
            financial_year=2026,
            financial_year_previous=None,
            statement_type="Statement of Financial Position",
            template_field_id=None,
            template_position=None,
            is_required_field=False,
            is_reviewed=False,
            confirmed_tag_id=None,
            validation_warnings=None,
        ),
        SimpleNamespace(
            id="mock-item-note",
            extracted_label="Other receivable",
            extracted_value="5",
            value_previous_year=None,
            financial_year=2026,
            financial_year_previous=None,
            statement_type="Statement of Financial Position",
            template_field_id=None,
            template_position=None,
            is_required_field=False,
            is_reviewed=False,
            confirmed_tag_id=None,
            validation_warnings='["note_column_values_ignored"]',
        ),
    ]
    page = SimpleNamespace(id="mock-page-1", page_number=1, extracted_items=rows)
    return SimpleNamespace(
        id=job_id,
        company_name="Mock LLM Mapping Smoke",
        status="REVIEW",
        pages=[page],
    )


async def _run_with_database(args: argparse.Namespace) -> tuple[dict[str, Any] | None, str | None]:
    llm_client = None
    if args.mock:
        llm_client = MockQwenMappingClient()
    elif args.use_live_llm:
        llm_client = HuggingFaceQwenMappingClient()

    async with AsyncSessionLocal() as db:
        persist_suggestions = bool(args.use_live_llm or args.apply_high_confidence)
        report = await run_llm_mapping_for_job(
            db,
            args.job_id,
            llm_client=llm_client,
            include_mapped=args.include_mapped,
            apply_high_confidence=args.apply_high_confidence,
            persist_suggestions=persist_suggestions,
        )
        if args.apply_high_confidence:
            await db.commit()
        else:
            await db.rollback()
        return report, None


async def async_main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mock and args.use_live_llm:
        print("Use either --mock or --use-live-llm, not both.", file=sys.stderr)
        return 2
    if args.apply_high_confidence and not (args.mock or args.use_live_llm):
        print("--apply-high-confidence requires --mock or --use-live-llm.", file=sys.stderr)
        return 2

    report = None
    db_error = None
    try:
        report, db_error = await _run_with_database(args)
    except Exception as exc:
        db_error = _safe_database_error(exc)
        if not args.mock:
            print(f"Could not load job {args.job_id}: {db_error}", file=sys.stderr)
            return 1

    if report is None and args.mock:
        mock_job = _mock_loaded_job(args.job_id)
        report = await run_llm_mapping_for_loaded_job(
            None,
            mock_job,
            llm_client=MockQwenMappingClient(),
            include_mapped=args.include_mapped,
            apply_high_confidence=False,
            persist_suggestions=False,
        )
        report["run_metadata"]["mock_fixture_used"] = True
        report["run_metadata"]["database_error"] = db_error

    if report is None:
        print(f"No report generated for job {args.job_id}", file=sys.stderr)
        return 1

    json_path, md_path = _write_reports(report, args.output_dir, args.job_id)
    summary = report.get("summary") or {}
    print(f"job_id={args.job_id}")
    print(f"llm_called={report.get('run_metadata', {}).get('llm_called')}")
    print(f"rows_considered={summary.get('rows_considered', 0)}")
    print(f"rows_sent_to_llm={summary.get('rows_sent_to_llm', 0)}")
    print(f"suggestions_generated={summary.get('suggestions_generated', 0)}")
    print(f"display_suggestions_generated={summary.get('display_suggestions_generated', 0)}")
    print(f"high_confidence_suggestions={summary.get('high_confidence_suggestions', 0)}")
    print(f"medium_confidence_suggestions={summary.get('medium_confidence_suggestions', 0)}")
    print(f"low_confidence_suggestions={summary.get('low_confidence_suggestions', 0)}")
    print(f"rejected_rows={summary.get('rejected_rows', 0)}")
    print(f"rejected_precheck_rows={summary.get('rejected_precheck_rows', 0)}")
    print(f"rejected_low_confidence_rows={summary.get('rejected_low_confidence_rows', 0)}")
    print(f"rejected_no_candidate_rows={summary.get('rejected_no_candidate_rows', 0)}")
    print(f"candidate_coverage_rate={summary.get('candidate_coverage_rate', 0)}")
    print(f"hallucinated_concept_rejections={summary.get('hallucinated_concept_rejections', 0)}")
    print(f"before_mapped_count={summary.get('before_mapped_count', 0)}")
    print(f"after_mapped_count={summary.get('after_mapped_count', 0)}")
    print(f"json_report={json_path}")
    print(f"markdown_report={md_path}")
    if args.use_live_llm and summary.get("invalid_llm_responses", 0) and not summary.get("suggestions_generated", 0):
        return 1
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
