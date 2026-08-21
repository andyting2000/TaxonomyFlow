"""Read-only backend adapter for deterministic rulebook mapper advisory evidence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import ExtractedDataItem, FilingJob, FinancialStatementPage
from services.pdf_xbrl_deterministic_alignment import pdf_row_values
from services.pdf_xbrl_rulebook_mapper import SAFETY, SUGGESTION_SOURCE, build_mapper_reports


HARDENED_RULEBOOK_REPORT_PATH = Path("reports/pdf_xbrl_rulebook_hardening_18d_b.json")


class RulebookMapperAdvisoryError(RuntimeError):
    """Safe error for unavailable advisory mapper inputs."""


def _read_hardened_rulebook_report(path: str | Path = HARDENED_RULEBOOK_REPORT_PATH) -> dict[str, Any]:
    report_path = Path(path)
    if not report_path.exists():
        raise RulebookMapperAdvisoryError(
            "Deterministic rulebook advisory report is unavailable."
        )
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RulebookMapperAdvisoryError(
            "Deterministic rulebook advisory report could not be loaded."
        ) from exc
    if not isinstance(payload, dict):
        raise RulebookMapperAdvisoryError(
            "Deterministic rulebook advisory report has an invalid shape."
        )
    return payload


def _job_sample_id(job: FilingJob) -> str:
    return f"filing_job:{job.id}"


def _job_default_year(job: FilingJob) -> int | None:
    fye = getattr(job, "financial_year_end", None)
    return getattr(fye, "year", None)


async def _load_job_extracted_items(db: AsyncSession, job_id: int) -> list[ExtractedDataItem]:
    result = await db.execute(
        select(ExtractedDataItem)
        .join(FinancialStatementPage)
        .where(FinancialStatementPage.job_id == job_id)
        .options(selectinload(ExtractedDataItem.page))
        .order_by(FinancialStatementPage.page_number, ExtractedDataItem.id)
    )
    scalars = result.scalars()
    if hasattr(scalars, "unique"):
        scalars = scalars.unique()
    return list(scalars.all())


def _row_mapping_from_item(item: ExtractedDataItem, fallback_index: int) -> dict[str, Any]:
    page = getattr(item, "page", None)
    return {
        "row_type": "numeric_fact",
        "row_id": str(item.id),
        "label": getattr(item, "extracted_label", None),
        "value": getattr(item, "extracted_value", None),
        "previous_value": getattr(item, "value_previous_year", None),
        "current_year": getattr(item, "financial_year", None),
        "prior_year": getattr(item, "financial_year_previous", None),
        "statement_type": getattr(item, "statement_type", None),
        "page_number": getattr(page, "page_number", None),
        "provenance": {"row_index": fallback_index},
    }


def _job_row_values(job: FilingJob, items: Sequence[ExtractedDataItem]) -> list[Any]:
    sample_id = _job_sample_id(job)
    company_name = str(getattr(job, "company_name", None) or sample_id)
    default_year = _job_default_year(job)
    values = []
    for index, item in enumerate(items, start=1):
        values.extend(
            pdf_row_values(
                sample_id=sample_id,
                company_name=company_name,
                row=_row_mapping_from_item(item, index),
                fallback_index=index,
                default_current_year=default_year,
            )
        )
    return values


def _as_string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def serialize_rulebook_mapper_suggestion(
    record: Mapping[str, Any],
    *,
    job_id: int,
) -> dict[str, Any]:
    """Serialize one #18D-C mapper record into the public advisory API shape."""
    return {
        "job_id": job_id,
        "sample_id": record.get("sample_id"),
        "row_id": str(record.get("pdf_row_id") or record.get("row_id") or ""),
        "pdf_label": str(record.get("pdf_label") or ""),
        "normalized_label": str(record.get("normalized_label") or ""),
        "pdf_value": record.get("pdf_value"),
        "statement_family": record.get("pdf_statement_family"),
        "period": _as_dict(record.get("pdf_period")),
        "suggestion_source": str(record.get("suggestion_source") or SUGGESTION_SOURCE),
        "matched_rule_id": record.get("matched_rule_id"),
        "rule_readiness": str(record.get("rule_readiness") or "no_match"),
        "predicted_qname": record.get("predicted_qname"),
        "predicted_concept_label": record.get("predicted_concept_label"),
        "confidence_score": float(record.get("confidence_score") or 0.0),
        "confidence_bucket": str(record.get("confidence_bucket") or "no_match"),
        "requires_human_review": True,
        "safe_for_auto_apply": False,
        "match_reasons": _as_string_list(record.get("match_reasons")),
        "blocking_reasons": _as_string_list(record.get("blocking_reasons")),
        "evidence_summary": _as_dict(record.get("evidence_summary")),
        "competing_rules": _as_dict_list(record.get("competing_rules")),
        "false_positive_risk_notes": _as_dict_list(
            record.get("false_positive_risk_notes")
        ),
    }


def serialize_rulebook_mapper_summary(
    summary: Mapping[str, Any],
    *,
    job_id: int,
) -> dict[str, Any]:
    safety = {
        key: value
        for key, value in dict(SAFETY).items()
        if key != "confirmed_tag_id_mutated"
    }
    safety.update(
        {
            key: value
            for key, value in _as_dict(summary.get("safety")).items()
            if key != "confirmed_tag_id_mutated"
        }
    )
    safety.update(
        {
            "api_changed": True,
            "database_mutated": False,
            "production_behavior_changed": False,
            "auto_applied": False,
            "confirmed_mapping_mutated": False,
            "persistence_enabled": False,
        }
    )
    return {
        "job_id": job_id,
        "total_pdf_row_value_observations": int(
            summary.get("total_pdf_row_value_observations") or 0
        ),
        "hardened_rules_loaded": int(summary.get("hardened_rules_loaded") or 0),
        "advisory_suggestions_count": int(
            summary.get("advisory_suggestions_count") or 0
        ),
        "review_required_suggestions_count": int(
            summary.get("review_required_suggestions_count") or 0
        ),
        "conflicts_count": int(summary.get("conflicts_count") or 0),
        "no_match_count": int(summary.get("no_match_count") or 0),
        "safe_for_auto_apply_count": 0,
        "requires_human_review_count": int(
            summary.get("requires_human_review_count") or 0
        ),
        "no_suggestion_safe_for_auto_apply": True,
        "confidence_bucket_counts": _as_dict(summary.get("confidence_bucket_counts")),
        "rule_readiness_counts": _as_dict(summary.get("rule_readiness_counts")),
        "per_sample_summary": _as_dict_list(summary.get("per_sample_summary")),
        "recommendation": _as_dict(summary.get("recommendation")),
        "safety": safety,
    }


async def run_rulebook_mapper_advisory_for_job(
    db: AsyncSession,
    *,
    job: FilingJob,
    mode: str = "dry_run",
    hardened_rulebook_path: str | Path = HARDENED_RULEBOOK_REPORT_PATH,
) -> dict[str, Any]:
    """Return deterministic rulebook suggestions for a job without mutating state."""
    if mode != "dry_run":
        mode = "dry_run"

    hardened_rulebook = _read_hardened_rulebook_report(hardened_rulebook_path)
    items = await _load_job_extracted_items(db, job.id)
    row_values = _job_row_values(job, items)
    sample_id = _job_sample_id(job)
    reports = build_mapper_reports(
        dataset_dir="database_extracted_data_items",
        hardened_rulebook=hardened_rulebook,
        sample_data_by_id={
            sample_id: {
                "company_name": getattr(job, "company_name", None) or sample_id,
                "pdf_rows_found": len(items),
                "row_values": row_values,
            }
        },
    )
    records = reports["suggestions"]["suggestions"]
    summary = reports["summary"]["summary"]
    return {
        "job_id": job.id,
        "mode": mode,
        "feature_enabled": True,
        "persistence_enabled": False,
        "summary": serialize_rulebook_mapper_summary(summary, job_id=job.id),
        "suggestions": [
            serialize_rulebook_mapper_suggestion(record, job_id=job.id)
            for record in records
        ],
    }
