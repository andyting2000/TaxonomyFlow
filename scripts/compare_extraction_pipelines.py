"""Compare production DB extraction rows with a shadow extraction report."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from sqlalchemy import select, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import AsyncSessionLocal, ExtractedDataItem, FinancialStatementPage
from services.shadow_text_table_extractor import parse_amount, utc_timestamp


REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_BENCHMARK_JOBS = [13, 14, 15, 18, 19, 20, 23]


def normalize_label(value: Any) -> str:
    text = re.sub(r"[^a-z0-9&().'\-/ ]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def normalize_value(value: Any) -> str:
    amount = parse_amount(value)
    if amount is not None:
        return format(amount.normalize(), "f")
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def duplicate_excess_count(values: Iterable[Any]) -> int:
    counts = Counter(value for value in values if value)
    return sum(count - 1 for count in counts.values() if count > 1)


def duplicate_groups(values: Iterable[Any], limit: int = 15) -> list[dict[str, Any]]:
    counts = Counter(value for value in values if value)
    groups = [{"key": key, "count": count} for key, count in counts.items() if count > 1]
    return sorted(groups, key=lambda item: (-item["count"], str(item["key"])))[:limit]


def _has_warning(row: dict[str, Any], warning: str) -> bool:
    return warning in (row.get("warnings") or [])


def summarize_rows(rows: Sequence[dict[str, Any]], *, source: str) -> dict[str, Any]:
    labels = [normalize_label(row.get("label")) for row in rows]
    label_values = [
        (normalize_label(row.get("label")), normalize_value(row.get("value")))
        for row in rows
        if row.get("label") or row.get("value")
    ]
    row_types = Counter(row.get("row_type") or "unknown" for row in rows)
    statement_key = "statement_type" if source == "production" else "statement_hint"
    statement_counts = Counter(str(row.get(statement_key) or "<blank>").strip() or "<blank>" for row in rows)
    return {
        "row_count": len(rows),
        "duplicate_label_count": duplicate_excess_count(labels),
        "duplicate_label_value_count": duplicate_excess_count(label_values),
        "duplicate_label_groups": duplicate_groups(labels),
        "duplicate_label_value_groups": duplicate_groups(label_values),
        "rows_by_statement": dict(sorted(statement_counts.items())),
        "row_type_counts": dict(sorted(row_types.items())),
    }


def _production_row_dict(item: Any, job_id: int, page_number: int) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "page_number": page_number,
        "label": getattr(item, "extracted_label", None),
        "value": getattr(item, "extracted_value", None),
        "previous_value": getattr(item, "value_previous_year", None),
        "statement_type": getattr(item, "statement_type", None),
        "template_field_id": getattr(item, "template_field_id", None),
        "confirmed_tag_id": getattr(item, "confirmed_tag_id", None),
    }


async def load_production_rows(job_ids: Sequence[int]) -> list[dict[str, Any]]:
    unique_job_ids = list(dict.fromkeys(job_ids))
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        stmt = (
            select(ExtractedDataItem, FinancialStatementPage.job_id, FinancialStatementPage.page_number)
            .join(FinancialStatementPage, ExtractedDataItem.page_id == FinancialStatementPage.id)
            .where(FinancialStatementPage.job_id.in_(unique_job_ids))
            .order_by(FinancialStatementPage.job_id, FinancialStatementPage.page_number, ExtractedDataItem.id)
        )
        result = await session.execute(stmt)
        rows = [
            _production_row_dict(item, int(job_id), int(page_number or 0))
            for item, job_id, page_number in result.all()
        ]
        await session.rollback()
    return rows


def _group_by_job(rows: Sequence[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        job_id = row.get("job_id")
        if job_id is not None:
            grouped[int(job_id)].append(row)
    return dict(grouped)


def _overlap_metrics(
    production_rows: Sequence[dict[str, Any]],
    shadow_rows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    production_labels = {normalize_label(row.get("label")) for row in production_rows if normalize_label(row.get("label"))}
    shadow_labels = {normalize_label(row.get("label")) for row in shadow_rows if normalize_label(row.get("label"))}
    production_pairs = {
        (normalize_label(row.get("label")), normalize_value(row.get("value")))
        for row in production_rows
        if normalize_label(row.get("label")) and normalize_value(row.get("value"))
    }
    shadow_pairs = {
        (normalize_label(row.get("label")), normalize_value(row.get("value")))
        for row in shadow_rows
        if normalize_label(row.get("label")) and normalize_value(row.get("value"))
    }
    return {
        "normalized_label_overlap_count": len(production_labels & shadow_labels),
        "normalized_label_value_overlap_count": len(production_pairs & shadow_pairs),
        "labels_only_in_production": sorted(production_labels - shadow_labels)[:25],
        "labels_only_in_shadow": sorted(shadow_labels - production_labels)[:25],
    }


def _job_comparison(job_id: int, production_rows: Sequence[dict[str, Any]], shadow_rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    production_summary = summarize_rows(production_rows, source="production")
    shadow_summary = summarize_rows(shadow_rows, source="shadow")
    production_mapped = sum(1 for row in production_rows if row.get("template_field_id") or row.get("confirmed_tag_id"))
    production_unmapped = len(production_rows) - production_mapped
    shadow_numeric = sum(1 for row in shadow_rows if row.get("row_type") in {"numeric_fact", "subtotal_or_total"})
    weak_or_no_label = sum(1 for row in shadow_rows if not normalize_label(row.get("label")) or _has_warning(row, "weak_label"))
    suspicious_sign = sum(1 for row in shadow_rows if _has_warning(row, "possible_sign_issue"))
    prior_year = sum(1 for row in shadow_rows if _has_warning(row, "possible_prior_year_confusion"))
    text_blocks = sum(1 for row in shadow_rows if row.get("row_type") == "text_block")
    numeric_facts = sum(1 for row in shadow_rows if row.get("row_type") == "numeric_fact")
    overlap = _overlap_metrics(production_rows, shadow_rows)
    high_risk_differences = []
    if shadow_summary["duplicate_label_count"] > production_summary["duplicate_label_count"]:
        high_risk_differences.append("shadow_duplicate_label_count_exceeds_production")
    if suspicious_sign:
        high_risk_differences.append("shadow_possible_sign_issues_present")
    if prior_year:
        high_risk_differences.append("shadow_possible_prior_year_confusion_present")
    if weak_or_no_label:
        high_risk_differences.append("shadow_weak_or_missing_labels_present")
    if overlap["normalized_label_overlap_count"] == 0 and production_rows and shadow_rows:
        high_risk_differences.append("no_normalized_label_overlap")

    return {
        "job_id": job_id,
        "production_row_count": len(production_rows),
        "shadow_row_count": len(shadow_rows),
        "production_mapped_rows": production_mapped,
        "production_unmapped_rows": production_unmapped,
        "shadow_candidate_numeric_rows": shadow_numeric,
        "shadow_rows_with_weak_or_no_label": weak_or_no_label,
        "duplicate_label_count": {
            "production": production_summary["duplicate_label_count"],
            "shadow": shadow_summary["duplicate_label_count"],
        },
        "duplicate_label_value_count": {
            "production": production_summary["duplicate_label_value_count"],
            "shadow": shadow_summary["duplicate_label_value_count"],
        },
        "suspicious_sign_count": suspicious_sign,
        "possible_prior_year_confusion_count": prior_year,
        "text_block_count": text_blocks,
        "numeric_fact_count": numeric_facts,
        "production_rows_by_statement_type": production_summary["rows_by_statement"],
        "shadow_rows_by_statement_hint": shadow_summary["rows_by_statement"],
        **overlap,
        "top_high_risk_differences": high_risk_differences[:10],
    }


def build_comparison_report(
    job_ids: Sequence[int],
    production_rows: Sequence[dict[str, Any]],
    shadow_candidates: Sequence[dict[str, Any]],
    *,
    shadow_report_path: str,
    shadow_job_status_counts: dict[str, int] | None = None,
    output_json: Path | None = None,
) -> dict[str, Any]:
    selected_jobs = list(dict.fromkeys(job_ids))
    production_by_job = _group_by_job(production_rows)
    shadow_by_job = _group_by_job(shadow_candidates)
    job_comparisons = [
        _job_comparison(job_id, production_by_job.get(job_id, []), shadow_by_job.get(job_id, []))
        for job_id in selected_jobs
    ]
    output_path = output_json or REPORTS_DIR / "pipeline_side_by_side_comparison_13j.json"
    totals = {
        "jobs_compared": len(job_comparisons),
        "production_row_count": sum(item["production_row_count"] for item in job_comparisons),
        "shadow_row_count": sum(item["shadow_row_count"] for item in job_comparisons),
        "production_mapped_rows": sum(item["production_mapped_rows"] for item in job_comparisons),
        "production_unmapped_rows": sum(item["production_unmapped_rows"] for item in job_comparisons),
        "shadow_candidate_numeric_rows": sum(item["shadow_candidate_numeric_rows"] for item in job_comparisons),
        "shadow_weak_or_no_label_rows": sum(item["shadow_rows_with_weak_or_no_label"] for item in job_comparisons),
        "shadow_suspicious_sign_count": sum(item["suspicious_sign_count"] for item in job_comparisons),
        "shadow_prior_year_confusion_count": sum(item["possible_prior_year_confusion_count"] for item in job_comparisons),
        "shadow_text_block_count": sum(item["text_block_count"] for item in job_comparisons),
        "shadow_numeric_fact_count": sum(item["numeric_fact_count"] for item in job_comparisons),
        "shadow_job_status_counts": dict(sorted((shadow_job_status_counts or {}).items())),
    }
    promising_signal = (
        totals["shadow_candidate_numeric_rows"] > 0
        and totals["shadow_row_count"] > 0
        and totals["shadow_weak_or_no_label_rows"] < totals["shadow_row_count"]
    )
    all_selected_pdfs_missing = (
        totals["shadow_job_status_counts"].get("missing_pdf", 0) == len(selected_jobs)
        and len(selected_jobs) > 0
    )
    if all_selected_pdfs_missing:
        assessment_summary = (
            "Shadow extraction could not evaluate candidates because all selected source PDFs are missing locally."
        )
    elif promising_signal:
        assessment_summary = (
            "Shadow extractor produced numeric candidates and enough labeled rows to justify further analysis."
        )
    else:
        assessment_summary = "Shadow extractor output is too sparse or weakly labeled for cutover consideration."
    return {
        "run_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "script": "scripts/compare_extraction_pipelines.py",
            "read_only": True,
            "database_mutated": False,
            "production_behavior_changed": False,
            "shadow_report_path": shadow_report_path,
            "output_path": str(output_path),
        },
        "selected_jobs": selected_jobs,
        "aggregate_metrics": totals,
        "job_comparisons": job_comparisons,
        "assessment": {
            "shadow_pipeline_looks_promising": promising_signal,
            "summary": assessment_summary,
            "recommended_next_step": (
                "Analyze side-by-side results and decide whether to improve shadow heuristics, mapping prompts, or production extraction architecture."
            ),
        },
        "limitations": [
            "Comparison is approximate and uses normalized labels/values, not human ground truth.",
            "Shadow candidates are not mapped to taxonomy concepts and are not written to the database.",
            "No XBRL generation, Arelle validation, or production extraction cutover is performed.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate_metrics"]
    lines = [
        "# Pipeline Side-by-Side Comparison",
        "",
        "## Executive Summary",
        "",
        f"- Jobs compared: {aggregate['jobs_compared']}",
        f"- Production rows: {aggregate['production_row_count']}",
        f"- Shadow rows: {aggregate['shadow_row_count']}",
        f"- Production mapped rows: {aggregate['production_mapped_rows']}",
        f"- Production unmapped rows: {aggregate['production_unmapped_rows']}",
        f"- Shadow numeric candidates: {aggregate['shadow_candidate_numeric_rows']}",
        f"- Shadow weak/no-label rows: {aggregate['shadow_weak_or_no_label_rows']}",
        f"- Shadow suspicious signs: {aggregate['shadow_suspicious_sign_count']}",
        f"- Shadow possible prior-year confusion: {aggregate['shadow_prior_year_confusion_count']}",
        f"- Shadow pipeline looks promising: {report['assessment']['shadow_pipeline_looks_promising']}",
        f"- Shadow job statuses: {aggregate.get('shadow_job_status_counts') or {}}",
        "",
        "## Jobs",
        "",
        "| Job | Production Rows | Shadow Rows | Prod Mapped | Prod Unmapped | Shadow Numeric | Label Overlap | Label+Value Overlap | Risks |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in report["job_comparisons"]:
        risks = ", ".join(item.get("top_high_risk_differences") or []) or "none"
        lines.append(
            "| {job_id} | {prod} | {shadow} | {mapped} | {unmapped} | {numeric} | {label_overlap} | {pair_overlap} | {risks} |".format(
                job_id=item["job_id"],
                prod=item["production_row_count"],
                shadow=item["shadow_row_count"],
                mapped=item["production_mapped_rows"],
                unmapped=item["production_unmapped_rows"],
                numeric=item["shadow_candidate_numeric_rows"],
                label_overlap=item["normalized_label_overlap_count"],
                pair_overlap=item["normalized_label_value_overlap_count"],
                risks=risks.replace("|", "\\|"),
            )
        )
    lines.extend([
        "",
        "## Assessment",
        "",
        report["assessment"]["summary"],
        "",
        "## Recommended Next Step",
        "",
        report["assessment"]["recommended_next_step"],
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in report.get("limitations", [])],
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare production DB rows with shadow extraction candidates.")
    parser.add_argument("--jobs", nargs="+", type=int, default=DEFAULT_BENCHMARK_JOBS)
    parser.add_argument("--shadow-report", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=REPORTS_DIR / "pipeline_side_by_side_comparison_13j.json")
    parser.add_argument("--output-md", type=Path)
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    selected_jobs = list(dict.fromkeys(args.jobs))
    shadow_report = json.loads(args.shadow_report.read_text(encoding="utf-8"))
    shadow_candidates = [
        candidate
        for candidate in shadow_report.get("candidates", [])
        if int(candidate.get("job_id") or 0) in set(selected_jobs)
    ]
    production_rows = await load_production_rows(selected_jobs)
    report = build_comparison_report(
        selected_jobs,
        production_rows,
        shadow_candidates,
        shadow_report_path=str(args.shadow_report),
        shadow_job_status_counts=dict(
            Counter(str(job_report.get("status") or "unknown") for job_report in shadow_report.get("job_reports", []))
        ),
        output_json=args.output_json,
    )
    output_md = args.output_md or args.output_json.with_suffix(".md")
    args.output_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"Comparison report: {args.output_json}")
    print(f"Markdown summary: {output_md}")
    print(f"Jobs compared: {report['aggregate_metrics']['jobs_compared']}")
    print(f"Production rows: {report['aggregate_metrics']['production_row_count']}")
    print(f"Shadow rows: {report['aggregate_metrics']['shadow_row_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
