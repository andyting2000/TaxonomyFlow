"""Read-only multi-job extraction and mapping benchmark report."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any, Iterable, Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database import AsyncSessionLocal, ExtractedDataItem, FilingJob, FinancialStatementPage
from scripts.audit_generated_xbrl_instance import build_report as build_xbrl_audit_report


REPORTS_DIR = PROJECT_ROOT / "reports"
NEGATIVE_VALUE_RE = re.compile(r"(^|[^\d])- ?\d|\(\s*[\d,]+(?:\.\d+)?\s*\)")
COMPANY_NAME_LABEL_RE = re.compile(
    r"\b(?:sdn\.?\s*bhd\.?|berhad|bhd\.?|pte\.?|limited|ltd\.?)\b",
    re.IGNORECASE,
)
TOTAL_LABEL_RE = re.compile(r"\b(total|subtotal|sub-total)\b", re.IGNORECASE)
KEYWORD_GROUPS = {
    "cash_bank": re.compile(r"\b(cash|bank|cimb|deposit|fixed deposit)\b", re.IGNORECASE),
    "receivable": re.compile(r"\b(receivable|debtor|amount due)\b", re.IGNORECASE),
    "payable": re.compile(r"\b(payable|creditor|accrual|amount owing)\b", re.IGNORECASE),
    "equity": re.compile(r"\b(equity|share capital|retained earnings|reserve)\b", re.IGNORECASE),
}
GUARDRAIL_PATTERNS = {
    "biological_assets": re.compile(r"biologicalassets", re.IGNORECASE),
    "trade_and_other_current_receivables": re.compile(
        r"tradeandothercurrentreceivables", re.IGNORECASE
    ),
}
BROAD_CONCEPT_PATTERNS = {
    "total_assets": re.compile(r"totalassets$", re.IGNORECASE),
    "total_liabilities": re.compile(r"totalliabilities$", re.IGNORECASE),
    "total_equity": re.compile(r"totalequity$", re.IGNORECASE),
    "profit_loss": re.compile(r"profitorloss|profitloss", re.IGNORECASE),
    "revenue": re.compile(r"revenue$", re.IGNORECASE),
}


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def safe_rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def duplicate_excess_count(keys: Iterable[str]) -> int:
    counts = Counter(key for key in keys if key)
    return sum(count - 1 for count in counts.values() if count > 1)


def duplicate_groups(keys: Iterable[str], limit: int = 25) -> list[dict[str, Any]]:
    counts = Counter(key for key in keys if key)
    groups = [
        {"key": key, "count": count}
        for key, count in counts.items()
        if count > 1
    ]
    return sorted(groups, key=lambda item: (-item["count"], item["key"]))[:limit]


def has_suspicious_signed_value(item: Any) -> bool:
    values = [getattr(item, "extracted_value", None), getattr(item, "value_previous_year", None)]
    return any(NEGATIVE_VALUE_RE.search(str(value or "")) for value in values)


def classify_job_role(job_id: int, include_job_9: bool) -> str:
    if job_id == 9:
        return "smoke_test_only"
    return "benchmark_candidate" if include_job_9 or job_id != 9 else "unknown"


def _item_concept(item: Any) -> str | None:
    confirmed_tag = getattr(item, "confirmed_tag", None)
    if confirmed_tag is not None:
        namespace = getattr(confirmed_tag, "namespace", None)
        tag = getattr(confirmed_tag, "xbrl_tag", None)
        if namespace and tag:
            return f"{namespace}:{tag}"
    template_field_id = getattr(item, "template_field_id", None)
    if template_field_id:
        return str(template_field_id)
    return None


def _mapping_source(item: Any) -> str:
    if getattr(item, "confirmed_tag_id", None):
        return "confirmed_tag_id"
    if getattr(item, "template_field_id", None):
        return "template_field_id"
    return "none"


def _confidence_value(item: Any) -> float | None:
    value = getattr(item, "confidence", None)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _confidence_bucket(value: float | None) -> str:
    if value is None:
        return "unavailable"
    if value >= 0.8:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


def _keyword_counts(items: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, pattern in KEYWORD_GROUPS.items():
        counts[name] = sum(
            1
            for item in items
            if pattern.search(str(getattr(item, "extracted_label", "") or ""))
        )
    return counts


def _pattern_concept_counts(items: Sequence[Any], patterns: dict[str, re.Pattern[str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name, pattern in patterns.items():
        counts[name] = sum(
            1
            for item in items
            if (concept := _item_concept(item)) and pattern.search(concept)
        )
    return counts


def _possible_year_confusion_count(items: Sequence[Any]) -> int:
    count = 0
    for item in items:
        current_year = getattr(item, "financial_year", None)
        previous_year = getattr(item, "financial_year_previous", None)
        previous_value = getattr(item, "value_previous_year", None)
        if previous_value and (not current_year or not previous_year):
            count += 1
        elif current_year and previous_year and int(previous_year) >= int(current_year):
            count += 1
    return count


def _date_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _all_items(job: Any) -> list[Any]:
    pages = sorted(getattr(job, "pages", []) or [], key=lambda page: getattr(page, "page_number", 0) or 0)
    return [
        item
        for page in pages
        for item in (getattr(page, "extracted_items", []) or [])
    ]


def calculate_job_metrics(job: Any, include_job_9: bool = False) -> dict[str, Any]:
    items = _all_items(job)
    total_rows = len(items)
    labels = [normalize_text(getattr(item, "extracted_label", None)) for item in items]
    label_values = [
        f"{normalize_text(getattr(item, 'extracted_label', None))}|{normalize_text(getattr(item, 'extracted_value', None))}"
        for item in items
    ]
    concepts = [_item_concept(item) for item in items]
    mapping_sources = Counter(_mapping_source(item) for item in items)
    statement_counter = Counter(
        str(getattr(item, "statement_type", "") or "").strip() or "<blank>"
        for item in items
    )
    confidence_values = [_confidence_value(item) for item in items]
    available_confidences = [value for value in confidence_values if value is not None]
    template_rows = mapping_sources["template_field_id"] + mapping_sources["confirmed_tag_id"]
    confirmed_rows = mapping_sources["confirmed_tag_id"]
    blank_statement_count = statement_counter.get("<blank>", 0)
    suspicious_sign_count = sum(1 for item in items if has_suspicious_signed_value(item))
    duplicate_label_count = duplicate_excess_count(labels)
    duplicate_label_value_count = duplicate_excess_count(label_values)

    return {
        "job_metadata": {
            "job_id": getattr(job, "id", None),
            "company_name": getattr(job, "company_name", None),
            "registration_number": getattr(job, "registration_number", None),
            "financial_year_end": _date_or_none(getattr(job, "financial_year_end", None)),
            "status": getattr(job, "status", None),
            "created_at": _date_or_none(getattr(job, "uploaded_at", None)),
            "updated_at": _date_or_none(getattr(job, "updated_at", None)),
            "pdf_path": getattr(job, "source_pdf_path", None),
            "page_count": len(getattr(job, "pages", []) or []),
            "job_role": classify_job_role(int(getattr(job, "id", 0) or 0), include_job_9),
        },
        "extraction_metrics": {
            "total_extracted_rows": total_rows,
            "rows_with_template_field_id": sum(1 for item in items if getattr(item, "template_field_id", None)),
            "rows_without_template_field_id": sum(1 for item in items if not getattr(item, "template_field_id", None)),
            "rows_with_confirmed_tag_id": sum(1 for item in items if getattr(item, "confirmed_tag_id", None)),
            "rows_without_confirmed_tag_id": sum(1 for item in items if not getattr(item, "confirmed_tag_id", None)),
            "rows_with_blank_statement_type": blank_statement_count,
            "rows_with_value": sum(1 for item in items if str(getattr(item, "extracted_value", "") or "").strip()),
            "rows_without_value": sum(1 for item in items if not str(getattr(item, "extracted_value", "") or "").strip()),
            "reviewed_count": sum(1 for item in items if bool(getattr(item, "is_reviewed", False))),
            "unreviewed_count": sum(1 for item in items if not bool(getattr(item, "is_reviewed", False))),
            "average_confidence": round(mean(available_confidences), 4) if available_confidences else None,
            "confidence_distribution": dict(sorted(Counter(_confidence_bucket(value) for value in confidence_values).items())),
        },
        "statement_metrics": {
            "rows_by_statement_type": dict(sorted(statement_counter.items())),
            "blank_statement_type_count": blank_statement_count,
            "statement_type_diversity": len([key for key in statement_counter if key != "<blank>"]),
            "pages_by_classified_statement": _pages_by_statement(job),
        },
        "mapping_metrics": {
            "template_field_id_coverage_rate": safe_rate(template_rows, total_rows),
            "confirmed_tag_coverage_rate": safe_rate(confirmed_rows, total_rows),
            "unmapped_rows": mapping_sources["none"],
            "unmapped_rate": safe_rate(mapping_sources["none"], total_rows),
            "mapping_source_counts": dict(sorted(mapping_sources.items())),
            "recurring_template_field_id_concepts": duplicate_groups(
                [str(getattr(item, "template_field_id", "") or "") for item in items]
            ),
            "guardrail_sensitive_mappings": _pattern_concept_counts(items, GUARDRAIL_PATTERNS),
            "broad_concept_candidates": _pattern_concept_counts(items, BROAD_CONCEPT_PATTERNS),
        },
        "data_quality_metrics": {
            "duplicate_label_count": duplicate_label_count,
            "duplicate_label_rate": safe_rate(duplicate_label_count, total_rows),
            "duplicate_label_value_count": duplicate_label_value_count,
            "duplicate_label_value_rate": safe_rate(duplicate_label_value_count, total_rows),
            "suspicious_signed_value_count": suspicious_sign_count,
            "suspicious_signed_value_rate": safe_rate(suspicious_sign_count, total_rows),
            "possible_current_prior_year_confusion_count": _possible_year_confusion_count(items),
            "rows_with_company_name_like_labels": sum(
                1 for item in items if COMPANY_NAME_LABEL_RE.search(str(getattr(item, "extracted_label", "") or ""))
            ),
            "rows_with_total_or_subtotal_labels": sum(
                1 for item in items if TOTAL_LABEL_RE.search(str(getattr(item, "extracted_label", "") or ""))
            ),
            "keyword_counts": _keyword_counts(items),
        },
        "xbrl_metrics": {"status": "not_requested"},
        "arelle_metrics": {"status": "not_requested"},
        "samples": {
            "duplicate_label_groups": duplicate_groups(labels, limit=10),
            "duplicate_label_value_groups": duplicate_groups(label_values, limit=10),
            "unmapped_rows": [
                {
                    "label": getattr(item, "extracted_label", None),
                    "value": getattr(item, "extracted_value", None),
                    "statement_type": getattr(item, "statement_type", None),
                }
                for item in items
                if _mapping_source(item) == "none"
            ][:10],
            "suspicious_signed_rows": [
                {
                    "label": getattr(item, "extracted_label", None),
                    "value": getattr(item, "extracted_value", None),
                    "previous_value": getattr(item, "value_previous_year", None),
                    "statement_type": getattr(item, "statement_type", None),
                }
                for item in items
                if has_suspicious_signed_value(item)
            ][:10],
        },
    }


def _pages_by_statement(job: Any) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for page in getattr(job, "pages", []) or []:
        statements = {
            str(getattr(item, "statement_type", "") or "").strip() or "<blank>"
            for item in (getattr(page, "extracted_items", []) or [])
        }
        for statement in statements:
            counts[statement] += 1
    return dict(sorted(counts.items()))


def summarize_xbrl_audit(audit_report: dict[str, Any]) -> dict[str, Any]:
    generated = audit_report.get("generated_facts", {})
    coverage = audit_report.get("coverage", {})
    context_unit = audit_report.get("context_unit_summary", {})
    contexts = context_unit.get("contexts", {})
    units = context_unit.get("units", {})
    extracted_rows = audit_report.get("extracted_rows", {})
    return {
        "status": "loaded",
        "xbrl_path": audit_report.get("xbrl_path"),
        "generated_fact_count": generated.get("total_generated_facts"),
        "expected_extracted_fact_count": coverage.get("expected_generated_fact_count"),
        "represented_expected_fact_count": coverage.get("represented_expected_fact_count"),
        "missing_context_refs": contexts.get("missing_context_refs", []),
        "missing_unit_refs": units.get("missing_unit_refs", []),
        "duplicate_fact_groups": generated.get("duplicate_concept_context_unit_facts", {}).get("group_count"),
        "identical_duplicate_fact_groups": generated.get("concepts_multiple_times_identical_value_context_unit", {}).get("group_count"),
        "suspicious_signed_values_in_xbrl": extracted_rows.get("suspicious_signed_values_carried_into_xbrl", {}).get("count"),
    }


def load_existing_arelle_baseline(job_id: int, reports_dir: Path = REPORTS_DIR) -> dict[str, Any]:
    path = reports_dir / f"arelle_validation_baseline_report_{job_id}.json"
    if not path.exists():
        return {
            "status": "not_run_existing_report_missing",
            "report_path": str(path),
            "limitations": [
                "Arelle baseline was requested, but no existing baseline report was found.",
                "The benchmark harness does not generate XBRL or mutate database state.",
                "Arelle baseline is structural context only, not full MBRS/FS-MPERS submission readiness.",
            ],
        }
    report = json.loads(path.read_text(encoding="utf-8"))
    recommendation = report.get("final_recommendation") or {}
    mode_summaries = report.get("mode_summaries") or {}
    selected_mode = recommendation.get("recommended_baseline_mode")
    selected_summary = mode_summaries.get(selected_mode or "", {})
    return {
        "status": "loaded_existing_report",
        "report_path": str(path),
        "baseline_mode": selected_mode,
        "is_valid": selected_summary.get("is_valid"),
        "return_code": selected_summary.get("return_code"),
        "error_count": sum(
            summary.get("error_families", {}).get("generated_instance_defect", {}).get("count", 0)
            for summary in mode_summaries.values()
            if isinstance(summary, dict)
        ),
        "warning_count": None,
        "limitations": report.get("limitations", [
            "Arelle baseline is structural context only, not full MBRS/FS-MPERS submission readiness."
        ]),
    }


def aggregate_metrics(per_job_metrics: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not per_job_metrics:
        return {
            "total_jobs_analyzed": 0,
            "total_rows": 0,
            "average_template_field_coverage": 0.0,
            "average_confirmed_tag_coverage": 0.0,
            "average_blank_statement_type_rate": 0.0,
            "average_unmapped_rate": 0.0,
            "average_duplicate_label_rate": 0.0,
            "average_suspicious_sign_rate": 0.0,
            "jobs_with_xbrl_audit": 0,
            "jobs_with_arelle_baseline": 0,
        }
    return {
        "total_jobs_analyzed": len(per_job_metrics),
        "total_rows": sum(metric["extraction_metrics"]["total_extracted_rows"] for metric in per_job_metrics),
        "average_template_field_coverage": round(mean(metric["mapping_metrics"]["template_field_id_coverage_rate"] for metric in per_job_metrics), 4),
        "average_confirmed_tag_coverage": round(mean(metric["mapping_metrics"]["confirmed_tag_coverage_rate"] for metric in per_job_metrics), 4),
        "average_blank_statement_type_rate": round(mean(
            safe_rate(metric["extraction_metrics"]["rows_with_blank_statement_type"], metric["extraction_metrics"]["total_extracted_rows"])
            for metric in per_job_metrics
        ), 4),
        "average_unmapped_rate": round(mean(metric["mapping_metrics"]["unmapped_rate"] for metric in per_job_metrics), 4),
        "average_duplicate_label_rate": round(mean(metric["data_quality_metrics"]["duplicate_label_rate"] for metric in per_job_metrics), 4),
        "average_suspicious_sign_rate": round(mean(metric["data_quality_metrics"]["suspicious_signed_value_rate"] for metric in per_job_metrics), 4),
        "jobs_with_xbrl_audit": sum(1 for metric in per_job_metrics if metric["xbrl_metrics"].get("status") == "loaded"),
        "jobs_with_arelle_baseline": sum(1 for metric in per_job_metrics if metric["arelle_metrics"].get("status") == "loaded_existing_report"),
    }


def build_risk_summary(per_job_metrics: Sequence[dict[str, Any]]) -> dict[str, Any]:
    def job_ids(predicate: Any) -> list[int]:
        return [
            int(metric["job_metadata"]["job_id"])
            for metric in per_job_metrics
            if predicate(metric)
        ]

    return {
        "jobs_with_high_unmapped_rate": job_ids(lambda m: m["mapping_metrics"]["unmapped_rate"] >= 0.25),
        "jobs_with_high_duplicate_rate": job_ids(lambda m: m["data_quality_metrics"]["duplicate_label_rate"] >= 0.25),
        "jobs_with_high_suspicious_sign_rate": job_ids(lambda m: m["data_quality_metrics"]["suspicious_signed_value_rate"] >= 0.10),
        "jobs_with_low_template_coverage": job_ids(lambda m: m["mapping_metrics"]["template_field_id_coverage_rate"] < 0.50),
        "jobs_with_missing_blank_statement_types": job_ids(lambda m: m["extraction_metrics"]["rows_with_blank_statement_type"] > 0),
        "jobs_that_should_not_be_used_as_benchmark": job_ids(lambda m: m["job_metadata"]["job_role"] == "smoke_test_only"),
    }


def benchmark_policy() -> dict[str, Any]:
    return {
        "minimum_future_dataset": [
            "3-5 representative PDFs/jobs minimum",
            "one standard financial statement PDF",
            "one complex table PDF",
            "one notes-heavy PDF",
            "one scanned/image-heavy PDF if available",
            "one real or near-real customer-like PDF",
        ],
        "job_9_policy": [
            "Job 9 is smoke-test only.",
            "It can test whether commands run.",
            "It must not be used as main benchmark or ground truth.",
            "Do not optimize architecture around Job 9.",
        ],
        "ground_truth_note": [
            "This benchmark initially measures system output quality signals.",
            "It does not prove extraction correctness unless human ground-truth labels are later added.",
            "A future feature may add ground_truth JSON support.",
        ],
        "future_ground_truth_design": {
            "path_pattern": "benchmark_cases/<case_id>/expected_rows.json",
            "fields": [
                "expected labels",
                "expected values",
                "expected years",
                "expected statement sections",
                "expected concept ids where known",
                "tolerance rules for numeric comparison",
            ],
        },
    }


def build_benchmark_report(
    selected_jobs: Sequence[int],
    per_job_metrics: Sequence[dict[str, Any]],
    missing_jobs: Sequence[int],
    include_job_9: bool,
    with_xbrl_audit: bool,
    with_arelle_baseline: bool,
    output_path: Path,
) -> dict[str, Any]:
    benchmark_jobs = [
        metric["job_metadata"]["job_id"]
        for metric in per_job_metrics
        if metric["job_metadata"]["job_role"] != "smoke_test_only"
    ]
    smoke_jobs = [
        metric["job_metadata"]["job_id"]
        for metric in per_job_metrics
        if metric["job_metadata"]["job_role"] == "smoke_test_only"
    ]
    warnings = []
    if 9 in selected_jobs and not include_job_9:
        warnings.append(
            "Job 9 was requested without --include-job-9. It is included only as smoke_test_only and must not be treated as benchmark ground truth."
        )
    recommended_next_step = (
        "Feature #13I Side-by-side text/table-first extraction prototype, no production cutover"
        if len(benchmark_jobs) >= 3
        else "Feature #13I Representative PDF benchmark set creation and upload/runbook"
    )

    return {
        "run_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "script": "scripts/benchmark_extraction_mapping.py",
            "read_only": True,
            "database_mutated": False,
            "production_behavior_changed": False,
            "with_xbrl_audit": with_xbrl_audit,
            "with_arelle_baseline": with_arelle_baseline,
            "output_path": str(output_path),
            "warnings": warnings,
        },
        "selected_jobs": list(selected_jobs),
        "job_9_policy": "Job 9 is smoke-test only and must not be used as the primary benchmark or ground truth.",
        "benchmark_jobs_analyzed": benchmark_jobs,
        "smoke_test_jobs_analyzed": smoke_jobs,
        "missing_jobs": list(missing_jobs),
        "benchmark_dataset_policy": benchmark_policy(),
        "per_job_metrics": list(per_job_metrics),
        "aggregate_metrics": aggregate_metrics(per_job_metrics),
        "risk_summary": build_risk_summary(per_job_metrics),
        "recommended_next_step": recommended_next_step,
    }


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate_metrics"]
    lines = [
        "# Extraction and Mapping Benchmark",
        "",
        "## Executive Summary",
        "",
        f"- Jobs analyzed: {aggregate['total_jobs_analyzed']}",
        f"- Total extracted rows: {aggregate['total_rows']}",
        f"- Average template-field coverage: {aggregate['average_template_field_coverage']:.1%}",
        f"- Average confirmed-tag coverage: {aggregate['average_confirmed_tag_coverage']:.1%}",
        f"- Average unmapped rate: {aggregate['average_unmapped_rate']:.1%}",
        f"- XBRL audits loaded: {aggregate['jobs_with_xbrl_audit']}",
        f"- Arelle baselines loaded: {aggregate['jobs_with_arelle_baseline']}",
        "",
    ]
    if report["smoke_test_jobs_analyzed"]:
        lines.extend([
            "## Job 9 Warning",
            "",
            "Job 9 is included only as a smoke-test regression sample. It must not be used as the main benchmark or ground truth.",
            "",
        ])

    lines.extend([
        "## Jobs Analyzed",
        "",
        "| Job | Role | Status | Company | Rows | Template Coverage | Confirmed Tags | Unmapped | Duplicate Labels | Suspicious Signs |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for metric in report["per_job_metrics"]:
        meta = metric["job_metadata"]
        extraction = metric["extraction_metrics"]
        mapping = metric["mapping_metrics"]
        quality = metric["data_quality_metrics"]
        lines.append(
            "| {job_id} | {role} | {status} | {company} | {rows} | {template:.1%} | {tags:.1%} | {unmapped} | {dupes} | {signs} |".format(
                job_id=meta["job_id"],
                role=meta["job_role"],
                status=meta.get("status") or "",
                company=(meta.get("company_name") or "").replace("|", "\\|"),
                rows=extraction["total_extracted_rows"],
                template=mapping["template_field_id_coverage_rate"],
                tags=mapping["confirmed_tag_coverage_rate"],
                unmapped=mapping["unmapped_rows"],
                dupes=quality["duplicate_label_count"],
                signs=quality["suspicious_signed_value_count"],
            )
        )
    lines.extend(["", "## Key Risks", ""])
    risk_summary = report["risk_summary"]
    for key, value in risk_summary.items():
        lines.append(f"- {key}: {value or 'none'}")
    lines.extend([
        "",
        "## Benchmark Policy",
        "",
        "- The benchmark set should eventually include 3-5 representative PDFs/jobs.",
        "- Job 9 is smoke-test only.",
        "- This report measures system output quality signals; it does not prove extraction correctness without human ground truth.",
        "",
        "## Recommended Next Action",
        "",
        report["recommended_next_step"],
        "",
    ])
    return "\n".join(lines)


async def load_jobs(job_ids: Sequence[int]) -> tuple[list[FilingJob], list[int]]:
    unique_job_ids = list(dict.fromkeys(job_ids))
    async with AsyncSessionLocal() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        stmt = (
            select(FilingJob)
            .options(
                selectinload(FilingJob.pages)
                .selectinload(FinancialStatementPage.extracted_items)
                .selectinload(ExtractedDataItem.confirmed_tag)
            )
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


async def enrich_optional_metrics(
    metrics: list[dict[str, Any]],
    with_xbrl_audit: bool,
    with_arelle_baseline: bool,
) -> None:
    for metric in metrics:
        job_id = int(metric["job_metadata"]["job_id"])
        if with_xbrl_audit:
            try:
                audit_report = await build_xbrl_audit_report(job_id)
                metric["xbrl_metrics"] = summarize_xbrl_audit(audit_report)
            except FileNotFoundError as exc:
                metric["xbrl_metrics"] = {"status": "skipped_missing_xbrl", "error": str(exc)}
            except Exception as exc:  # pragma: no cover - defensive for local DB/file variations
                metric["xbrl_metrics"] = {"status": "error", "error": str(exc)}
        if with_arelle_baseline:
            metric["arelle_metrics"] = load_existing_arelle_baseline(job_id)


async def build_report_from_db(
    job_ids: Sequence[int],
    include_job_9: bool,
    with_xbrl_audit: bool,
    with_arelle_baseline: bool,
    output_path: Path,
) -> dict[str, Any]:
    jobs, missing_jobs = await load_jobs(job_ids)
    metrics = [calculate_job_metrics(job, include_job_9=include_job_9) for job in jobs]
    await enrich_optional_metrics(metrics, with_xbrl_audit, with_arelle_baseline)
    return build_benchmark_report(
        selected_jobs=list(dict.fromkeys(job_ids)),
        per_job_metrics=metrics,
        missing_jobs=missing_jobs,
        include_job_9=include_job_9,
        with_xbrl_audit=with_xbrl_audit,
        with_arelle_baseline=with_arelle_baseline,
        output_path=output_path,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only multi-job extraction/mapping benchmark harness."
    )
    parser.add_argument("--jobs", nargs="+", type=int, required=True)
    parser.add_argument("--include-job-9", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--with-xbrl-audit", action="store_true")
    parser.add_argument("--with-arelle-baseline", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", action="store_true", help="Print JSON report to console.")
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    selected_jobs = list(dict.fromkeys(args.jobs))
    if args.limit is not None:
        selected_jobs = selected_jobs[: max(args.limit, 0)]

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = args.output or REPORTS_DIR / f"extraction_mapping_benchmark_{_utc_timestamp()}.json"
    report = await build_report_from_db(
        job_ids=selected_jobs,
        include_job_9=args.include_job_9,
        with_xbrl_audit=args.with_xbrl_audit,
        with_arelle_baseline=args.with_arelle_baseline,
        output_path=output_path,
    )
    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    markdown_path = None
    if args.markdown:
        markdown_path = output_path.with_suffix(".md")
        markdown_path.write_text(render_markdown(report), encoding="utf-8")

    if 9 in selected_jobs and not args.include_job_9:
        print("Warning: Job 9 is smoke-test only and is not benchmark ground truth.", file=sys.stderr)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"Benchmark report: {output_path}")
        if markdown_path:
            print(f"Markdown summary: {markdown_path}")
        print(f"Jobs analyzed: {report['aggregate_metrics']['total_jobs_analyzed']}")
        if report["missing_jobs"]:
            print(f"Missing jobs: {', '.join(str(job_id) for job_id in report['missing_jobs'])}")
        if report["smoke_test_jobs_analyzed"]:
            print(f"Smoke-test-only jobs: {', '.join(str(job_id) for job_id in report['smoke_test_jobs_analyzed'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
