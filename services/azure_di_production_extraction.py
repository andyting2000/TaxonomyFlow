"""Production Azure Document Intelligence extraction persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from collections import Counter
from datetime import datetime, timezone
from inspect import isawaitable
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import ExtractedDataItem, FilingJob, FinancialStatementPage
from file_safety import assert_upload_child
from schemas import JobStatus, ProcessingStatus, ProgressUpdate
from services.azure_document_intelligence_provider import (
    AzureDocumentIntelligenceConfigError,
    AzureDocumentIntelligenceProvider,
    normalize_azure_document_result,
)
from services.extraction_v2_azure_di_normalizer import normalize_azure_di_extraction_report
from services.extraction_v2_azure_di_pipeline import (
    TEXT_BLOCK_DISABLED_WARNING,
    TEXT_BLOCK_FAILED_WARNING,
    TEXT_BLOCK_TIMEOUT_WARNING,
    build_case_report,
    convert_azure_di_result_to_candidates,
)
from services.azure_di_production_mapping import (
    AzureDITemplateMapping,
    classify_azure_di_statement,
    map_azure_di_candidate_to_template_field,
)
from services.llm_taxonomy_mapping import LLMMappingRateLimitError
from services.toc_pipeline_execution_status import PipelineExecutionStatusRecorder

logger = logging.getLogger(__name__)

NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
PERSISTABLE_ROW_TYPES = NUMERIC_ROW_TYPES | {"text_block"}
MAX_ERROR_MESSAGE_LENGTH = 5000
MAX_PLAIN_RESULT_DEPTH = 20
MAX_PLAIN_RESULT_ITEMS = 100000
MAPPING_SUGGESTION_ASYNC_RESOURCE_ERROR_CODE = "async_resource_loop_mismatch"
MAPPING_SUGGESTION_FAILED_ERROR_CODE = "mapping_suggestion_failed"

ProgressCallback = Callable[..., Any]


class AzureDINormalizationTimeoutError(RuntimeError):
    """Raised when local Azure DI normalization exceeds the production timeout."""


def _mark_execution_failed(
    recorder: PipelineExecutionStatusRecorder | None,
) -> None:
    if recorder is None:
        return
    try:
        recorder.fail_unfinished("unexpected_exception")
    except Exception:
        logger.exception("Could not finalize TOC pipeline execution telemetry")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def _update_progress(
    job_id: int,
    progress: int,
    status: JobStatus,
    message: str,
    *,
    progress_callback: ProgressCallback | None = None,
    current_page: int | None = None,
    total_pages: int | None = None,
    items_extracted: int | None = None,
) -> None:
    update = ProgressUpdate(
        job_id=job_id,
        progress=progress,
        status=status,
        message=message,
        current_page=current_page,
        total_pages=total_pages,
        items_extracted=items_extracted,
    )
    try:
        from services.redis_status_tracker import redis_status_tracker

        if redis_status_tracker.initialized:
            await redis_status_tracker.update_progress(update)
    except Exception as exc:
        logger.debug("Azure DI progress update skipped for job %s: %s", job_id, exc)

    if progress_callback is not None:
        try:
            callback_result = progress_callback(
                job_id=job_id,
                progress=progress,
                status=status,
                message=message,
                current_page=current_page,
                total_pages=total_pages,
                items_extracted=items_extracted,
            )
            if isawaitable(callback_result):
                await callback_result
        except Exception as exc:
            logger.warning("Azure DI Celery progress callback failed for job %s: %s", job_id, exc)


def _safe_error_message(message: str) -> str:
    return (message or "Azure Document Intelligence processing failed.").strip()[:MAX_ERROR_MESSAGE_LENGTH]


def _mapping_suggestion_error_metadata(exc: Exception) -> str:
    message = _safe_error_message(str(exc))
    normalized = message.casefold()
    error_code = MAPPING_SUGGESTION_FAILED_ERROR_CODE
    if (
        "future attached to a different loop" in normalized
        or "got result for unknown protocol state" in normalized
    ):
        error_code = MAPPING_SUGGESTION_ASYNC_RESOURCE_ERROR_CODE
    return f"[{error_code}] {message}"


def _set_job_tracking(
    job: FilingJob,
    *,
    status: JobStatus | None = None,
    progress: int | None = None,
    error_message: str | None = None,
    clear_error: bool = False,
) -> None:
    if status is not None:
        job.status = status.value
    if hasattr(job, "progress"):
        job.progress = progress
    if clear_error and hasattr(job, "error_message"):
        job.error_message = None
    elif error_message is not None and hasattr(job, "error_message"):
        job.error_message = _safe_error_message(error_message)


async def _stage_progress(
    db: AsyncSession,
    job: FilingJob,
    *,
    progress: int,
    message: str,
    progress_callback: ProgressCallback | None,
    total_pages: int | None = None,
    items_extracted: int | None = None,
) -> None:
    _set_job_tracking(
        job,
        status=JobStatus.PROCESSING,
        progress=progress,
        clear_error=True,
    )
    await db.commit()
    await _update_progress(
        job.id,
        progress,
        JobStatus.PROCESSING,
        message,
        progress_callback=progress_callback,
        total_pages=total_pages,
        items_extracted=items_extracted,
    )


def _plain_value(value: Any, *, depth: int = 0) -> Any:
    if depth > MAX_PLAIN_RESULT_DEPTH:
        return str(value)[:1000]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        rows: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_PLAIN_RESULT_ITEMS:
                rows["__truncated__"] = True
                break
            rows[str(key)] = _plain_value(item, depth=depth + 1)
        return rows
    if isinstance(value, (list, tuple)):
        rows = []
        for index, item in enumerate(value):
            if index >= MAX_PLAIN_RESULT_ITEMS:
                rows.append({"__truncated__": True})
                break
            rows.append(_plain_value(item, depth=depth + 1))
        return rows
    if hasattr(value, "as_dict"):
        try:
            return _plain_value(value.as_dict(), depth=depth + 1)
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            return _plain_value(value.to_dict(), depth=depth + 1)
        except Exception:
            pass
    return str(value)[:1000]


def _coerce_azure_result(
    raw_result: Any,
    *,
    provider: AzureDocumentIntelligenceProvider,
    source_pdf_path: str,
    runtime_seconds: float,
) -> dict[str, Any]:
    if isinstance(raw_result, Mapping):
        return _plain_value(raw_result)

    return normalize_azure_document_result(
        raw_result,
        model_id=provider.model_id,
        runtime_seconds=runtime_seconds,
        source_pdf=source_pdf_path,
        warnings=["azure_di_sdk_result_coerced_to_plain_result"],
    )


def _page_image_path(job_id: int, page_number: int) -> str:
    image_filename = f"job_{job_id}_page_{page_number}.png"
    return os.path.join(settings.upload_directory, "pages", image_filename)


def _candidate_page_number(candidate: Mapping[str, Any]) -> int:
    try:
        return max(1, int(candidate.get("page_number") or 1))
    except (TypeError, ValueError):
        return 1


def _candidate_label(candidate: Mapping[str, Any]) -> str:
    label = (
        candidate.get("label")
        or candidate.get("statement_section")
        or candidate.get("source_snippet")
        or candidate.get("text")
        or "Azure DI extracted row"
    )
    return str(label).strip()[:1000] or "Azure DI extracted row"


def _candidate_value(candidate: Mapping[str, Any]) -> str:
    row_type = str(candidate.get("row_type") or "")
    if row_type == "text_block":
        value = candidate.get("text") or candidate.get("source_snippet") or candidate.get("value")
    else:
        value = candidate.get("value") or candidate.get("text") or candidate.get("source_snippet")
    return str(value or "").strip()[:5000]


def _candidate_warnings(
    candidate: Mapping[str, Any],
    mapping: AzureDITemplateMapping | None = None,
) -> str | None:
    warnings = list(candidate.get("warnings") or [])
    if mapping and mapping.warning:
        warnings.append(mapping.warning)
    provenance = candidate.get("provenance") or {}
    if provenance:
        warnings.append(
            "azure_di_provenance="
            + json.dumps(provenance, default=str, ensure_ascii=True)[:1500]
        )
    return json.dumps(warnings, ensure_ascii=True) if warnings else None


def _no_usable_rows_message(azure_result: Mapping[str, Any]) -> str:
    warnings = [str(item) for item in (azure_result.get("warnings") or [])]
    if any(TEXT_BLOCK_TIMEOUT_WARNING in warning for warning in warnings):
        return "Azure DI text block normalization timed out and Azure DI returned no usable table candidates."
    if any(TEXT_BLOCK_FAILED_WARNING in warning for warning in warnings):
        return "Azure DI text block normalization failed and Azure DI returned no usable table candidates."
    if any(TEXT_BLOCK_DISABLED_WARNING in warning for warning in warnings):
        return "Azure DI text block normalization is disabled and Azure DI returned no usable table candidates."
    return "Azure DI returned no usable financial rows."


def _page_numbers_from_result(
    azure_result: Mapping[str, Any],
    candidates: list[dict[str, Any]],
) -> list[int]:
    page_numbers = {
        int(page.get("page_number") or 0)
        for page in azure_result.get("pages") or []
        if page.get("page_number")
    }
    page_numbers.update(
        _candidate_page_number(candidate)
        for candidate in candidates
        if candidate.get("page_number")
    )
    pages_count = int(azure_result.get("pages_count") or 0)
    if pages_count:
        page_numbers.update(range(1, pages_count + 1))
    return sorted(page for page in page_numbers if page > 0)


def _build_raw_report(
    *,
    job: FilingJob,
    source_pdf_path: str,
    azure_result: dict[str, Any],
    raw_candidates: list[dict[str, Any]],
    provider: AzureDocumentIntelligenceProvider,
    runtime_seconds: float,
) -> dict[str, Any]:
    case = {
        "case_id": f"filing_job_{job.id}",
        "case_dir": str(Path(source_pdf_path).parent),
        "pdf_path": source_pdf_path,
        "reference_available": False,
        "reference_path": None,
        "reference_type": None,
    }
    case_report = build_case_report(
        case=case,
        azure_result=azure_result,
        candidates=raw_candidates,
    )
    row_counts = Counter(str(candidate.get("row_type") or "unknown") for candidate in raw_candidates)
    return {
        "run_metadata": {
            "feature": "16B-hotfix-3",
            "generated_at": _utc_now().isoformat(),
            "report_type": "azure_di_production_extraction",
            "provider": "azure_document_intelligence",
            "source_method": "azure_document_intelligence",
            "model_id": provider.model_id,
            "database_mutated": True,
            "production_behavior_changed": True,
            "production_extraction_behavior_changed": True,
            "reference_xml_sent_to_provider": False,
            "legacy_smart_ai_processor_called": False,
        },
        "pipeline_name": "Azure DI Production Extraction",
        "aggregate_metrics": {
            "total_cases_processed": 1,
            "total_pdfs_processed": 1,
            "pages_processed": int(azure_result.get("pages_count") or 0),
            "azure_di_pages_processed": int(azure_result.get("pages_count") or 0),
            "tables_detected": len(azure_result.get("tables") or []),
            "azure_di_tables_detected": len(azure_result.get("tables") or []),
            "content_characters": int(azure_result.get("content_length") or 0),
            "azure_di_characters_detected": int(azure_result.get("content_length") or 0),
            "runtime_seconds": round(runtime_seconds, 3),
            "total_runtime_seconds": round(runtime_seconds, 3),
            "total_candidates": len(raw_candidates),
            "total_candidate_rows": len(raw_candidates),
            "row_type_counts": dict(sorted(row_counts.items())),
        },
        "case_reports": [case_report],
        "sample_candidates": raw_candidates[:25],
        "warnings": list(azure_result.get("warnings") or []),
        "errors": list(azure_result.get("errors") or []),
    }


def _run_local_normalization(
    *,
    job: FilingJob,
    job_id: int,
    source_pdf_path: str,
    azure_result: dict[str, Any],
    provider: AzureDocumentIntelligenceProvider,
    runtime_seconds: float,
    text_blocks_enabled: bool | None = None,
    text_block_timeout_seconds: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    resolved_text_blocks_enabled = (
        bool(getattr(settings, "azure_di_text_blocks_enabled", True))
        if text_blocks_enabled is None
        else bool(text_blocks_enabled)
    )
    resolved_text_block_timeout = (
        float(getattr(settings, "azure_di_text_block_timeout_seconds", 15) or 0)
        if text_block_timeout_seconds is None
        else float(text_block_timeout_seconds)
    )
    conversion_started = time.monotonic()
    raw_candidates = convert_azure_di_result_to_candidates(
        azure_result,
        case_id=f"filing_job_{job_id}",
        source_pdf=source_pdf_path,
        text_blocks_enabled=resolved_text_blocks_enabled,
        text_block_timeout_seconds=resolved_text_block_timeout,
    )
    logger.info(
        "Azure DI raw candidate conversion finished for job %s: candidate_count=%s elapsed_seconds=%s",
        job_id,
        len(raw_candidates),
        round(time.monotonic() - conversion_started, 3),
    )

    report_started = time.monotonic()
    raw_report = _build_raw_report(
        job=job,
        source_pdf_path=source_pdf_path,
        azure_result=azure_result,
        raw_candidates=raw_candidates,
        provider=provider,
        runtime_seconds=runtime_seconds,
    )
    logger.info(
        "Azure DI raw normalization report built for job %s: candidate_count=%s elapsed_seconds=%s",
        job_id,
        len(raw_candidates),
        round(time.monotonic() - report_started, 3),
    )

    normalizer_started = time.monotonic()
    normalized_report, summary = normalize_azure_di_extraction_report(
        raw_report,
        run_id=f"filing_job_{job_id}",
        text_blocks_enabled=resolved_text_blocks_enabled,
        text_block_timeout_seconds=resolved_text_block_timeout,
    )
    logger.info(
        "Azure DI #13Y normalizer returned for job %s: elapsed_seconds=%s",
        job_id,
        round(time.monotonic() - normalizer_started, 3),
    )
    return raw_candidates, normalized_report, summary


def _report_candidates(normalized_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        candidate
        for case in normalized_report.get("case_reports") or []
        for candidate in case.get("candidates") or []
    ]


def _persistable_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        candidate
        for candidate in candidates
        if str(candidate.get("row_type") or "") in PERSISTABLE_ROW_TYPES
        and _candidate_value(candidate)
    ]


def _table_fallback_is_eligible(azure_result: Mapping[str, Any]) -> bool:
    return bool(
        int(azure_result.get("pages_count") or len(azure_result.get("pages") or [])) > 0
        and (azure_result.get("tables") or azure_result.get("table_cells"))
    )


def _record_timeout_fallback_warning(
    *,
    azure_result: dict[str, Any],
    candidates: list[dict[str, Any]],
    raw_candidate_count: int,
    elapsed_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    warnings = azure_result.setdefault("warnings", [])
    if TEXT_BLOCK_TIMEOUT_WARNING not in warnings:
        warnings.append(TEXT_BLOCK_TIMEOUT_WARNING)
    metadata = {
        "warning_code": "azure_di_text_block_normalization_timeout",
        "warning_message": "Text block normalization timed out; table candidates were used.",
        "fallback_used": "table_candidates_only",
        "pages_count": int(azure_result.get("pages_count") or len(azure_result.get("pages") or [])),
        "tables_count": len(azure_result.get("tables") or []),
        "table_candidate_count": int(raw_candidate_count),
        "normalized_candidates_count": len(candidates),
        "paragraph_index_at_timeout": None,
        "paragraph_count": len(azure_result.get("paragraphs") or []),
        "elapsed_seconds": round(elapsed_seconds, 3),
        "timeout_seconds": float(timeout_seconds),
    }
    for candidate in candidates:
        candidate_warnings = candidate.setdefault("warnings", [])
        if TEXT_BLOCK_TIMEOUT_WARNING not in candidate_warnings:
            candidate_warnings.append(TEXT_BLOCK_TIMEOUT_WARNING)
        candidate_warnings.append(dict(metadata))
    return metadata


async def _clear_existing_extraction_rows(db: AsyncSession, job_id: int) -> None:
    page_ids = select(FinancialStatementPage.id).where(FinancialStatementPage.job_id == job_id)
    await db.execute(delete(ExtractedDataItem).where(ExtractedDataItem.page_id.in_(page_ids)))
    await db.execute(delete(FinancialStatementPage).where(FinancialStatementPage.job_id == job_id))


async def _persist_candidates(
    db: AsyncSession,
    *,
    job_id: int,
    azure_result: Mapping[str, Any],
    candidates: list[dict[str, Any]],
    item_ids_by_original_candidate: dict[str, str] | None = None,
) -> tuple[int, int]:
    await _clear_existing_extraction_rows(db, job_id)

    page_numbers = _page_numbers_from_result(azure_result, candidates)
    pages_by_number: dict[int, FinancialStatementPage] = {}
    for page_number in page_numbers:
        page = FinancialStatementPage(
            id=str(uuid.uuid4()),
            job_id=job_id,
            page_number=page_number,
            image_path=_page_image_path(job_id, page_number),
        )
        db.add(page)
        pages_by_number[page_number] = page

    await db.flush()

    persisted_items = 0
    for candidate in candidates:
        row_type = str(candidate.get("row_type") or "")
        if row_type not in PERSISTABLE_ROW_TYPES:
            continue

        extracted_value = _candidate_value(candidate)
        if not extracted_value:
            continue

        page_number = _candidate_page_number(candidate)
        page = pages_by_number.get(page_number)
        if page is None:
            page = FinancialStatementPage(
                id=str(uuid.uuid4()),
                job_id=job_id,
                page_number=page_number,
                image_path=_page_image_path(job_id, page_number),
            )
            db.add(page)
            pages_by_number[page_number] = page
            await db.flush()

        mapping = map_azure_di_candidate_to_template_field(candidate)
        classified_statement_type, _classified_template_code, _classification_evidence = (
            classify_azure_di_statement(candidate)
        )

        item = ExtractedDataItem(
            id=str(uuid.uuid4()),
            page_id=page.id,
            extracted_label=_candidate_label(candidate),
            extracted_value=extracted_value,
            financial_year=candidate.get("current_year"),
            value_previous_year=candidate.get("previous_value"),
            financial_year_previous=candidate.get("prior_year"),
            statement_type=mapping.statement_type or classified_statement_type or candidate.get("statement_section"),
            template_field_id=mapping.template_field_id,
            template_position=mapping.template_position,
            is_required_field=mapping.is_required_field,
            is_reviewed=mapping.is_reviewed,
            confirmed_tag_id=None,
            validation_warnings=_candidate_warnings(candidate, mapping),
            has_calculation_warning=False,
        )
        db.add(item)
        if item_ids_by_original_candidate is not None:
            original_candidate_id = candidate.get("original_candidate_id")
            if original_candidate_id:
                item_ids_by_original_candidate[str(original_candidate_id)] = item.id
        persisted_items += 1

    return len(pages_by_number), persisted_items


async def process_azure_di_filing_job(
    job_id: int,
    db: AsyncSession,
    *,
    provider: AzureDocumentIntelligenceProvider | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ProcessingStatus:
    started_at = _utc_now()
    execution_status: PipelineExecutionStatusRecorder | None = None
    logger.info("Azure DI processing started for job %s", job_id)
    await _update_progress(
        job_id,
        0,
        JobStatus.PROCESSING,
        "Processing with Azure Document Intelligence",
        progress_callback=progress_callback,
    )

    try:
        result = await db.execute(select(FilingJob).where(FilingJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            return ProcessingStatus(
                job_id=job_id,
                status=JobStatus.ERROR,
                progress=0,
                error="Filing job not found",
            )

        execution_status = PipelineExecutionStatusRecorder.create(job_id)
        execution_status.transition("azure_di_extraction", "started")

        _set_job_tracking(
            job,
            status=JobStatus.PROCESSING,
            progress=0,
            clear_error=True,
        )
        await db.commit()
        # A retry invalidates any artifact from the prior processing attempt,
        # even when #19A is currently disabled. Otherwise a later flag change
        # could expose structure whose row references belong to an old run.
        try:
            from services.toc_aware_document_structure import (
                discard_document_structure_artifact,
            )

            await asyncio.to_thread(
                discard_document_structure_artifact,
                job_id,
            )
        except Exception:
            logger.exception(
                "Could not invalidate prior TOC-aware artifact at processing start for job %s",
                job_id,
            )
        try:
            from services.toc_aware_template_classification import (
                discard_template_classification_artifact,
            )

            await asyncio.to_thread(
                discard_template_classification_artifact,
                job_id,
            )
        except Exception:
            logger.exception(
                "Could not invalidate prior template-classification artifact "
                "at processing start for job %s",
                job_id,
            )
        try:
            from services.section_aware_initial_mapping import (
                discard_initial_mapping_artifact,
            )

            await asyncio.to_thread(
                discard_initial_mapping_artifact,
                job_id,
            )
        except Exception:
            logger.exception(
                "Could not invalidate prior initial-mapping artifact at processing start for job %s",
                job_id,
            )

        source_pdf_path = str(assert_upload_child(job.source_pdf_path, "pdfs"))
        provider = provider or AzureDocumentIntelligenceProvider()
        provider.validate_config()

        await _stage_progress(
            db,
            job,
            progress=10,
            message="Azure DI submitted",
            progress_callback=progress_callback,
        )

        started = time.monotonic()
        raw_azure_result = provider.analyze_pdf_path(source_pdf_path)
        runtime_seconds = time.monotonic() - started
        azure_result = _coerce_azure_result(
            raw_azure_result,
            provider=provider,
            source_pdf_path=source_pdf_path,
            runtime_seconds=runtime_seconds,
        )

        page_count = int(azure_result.get("pages_count") or 0)
        table_count = len(azure_result.get("tables") or [])
        logger.info("Azure DI result received for job %s", job_id)
        logger.info("Azure DI result page count for job %s: %s", job_id, page_count)
        logger.info("Azure DI result table count for job %s: %s", job_id, table_count)
        await _stage_progress(
            db,
            job,
            progress=35,
            message="Azure DI result received",
            progress_callback=progress_callback,
            total_pages=page_count,
        )

        if not azure_result.get("ok"):
            errors = azure_result.get("errors") or []
            detail = "; ".join(str(error.get("message") or error) for error in errors[:3])
            raise RuntimeError(
                "Azure Document Intelligence extraction failed"
                + (f": {detail}" if detail else ".")
            )

        execution_status.transition(
            "azure_di_extraction",
            "completed",
            page_count=page_count,
            table_count=table_count,
        )

        logger.info(
            "Azure DI normalized plain result received for job %s: pages=%s tables=%s table_cells=%s content_length=%s",
            job_id,
            len(azure_result.get("pages") or []),
            len(azure_result.get("tables") or []),
            len(azure_result.get("table_cells") or []),
            azure_result.get("content_length"),
        )
        logger.info("Azure DI normalization started for job %s", job_id)
        execution_status.transition("normalization", "started")
        await _stage_progress(
            db,
            job,
            progress=50,
            message="Normalizing Azure DI result",
            progress_callback=progress_callback,
            total_pages=page_count,
        )

        normalization_timeout = float(
            getattr(settings, "azure_di_normalization_timeout_seconds", 120) or 120
        )
        normalization_started = time.monotonic()
        timeout_fallback_warning: dict[str, Any] | None = None
        try:
            raw_candidates, normalized_report, _summary = await asyncio.wait_for(
                asyncio.to_thread(
                    _run_local_normalization,
                    job=job,
                    job_id=job_id,
                    source_pdf_path=source_pdf_path,
                    azure_result=azure_result,
                    provider=provider,
                    runtime_seconds=runtime_seconds,
                ),
                timeout=normalization_timeout,
            )
        except TimeoutError as exc:
            fallback_allowed = bool(
                getattr(settings, "azure_di_allow_table_fallback_on_text_timeout", True)
            )
            if not fallback_allowed or not _table_fallback_is_eligible(azure_result):
                raise AzureDINormalizationTimeoutError("Azure DI normalization timed out.") from exc

            logger.warning(
                "Azure DI local normalization timed out for job %s after %s seconds; attempting bounded table-only fallback",
                job_id,
                normalization_timeout,
            )
            fallback_timeout = max(1.0, min(normalization_timeout, 30.0))
            try:
                raw_candidates, normalized_report, _summary = await asyncio.wait_for(
                    asyncio.to_thread(
                        _run_local_normalization,
                        job=job,
                        job_id=job_id,
                        source_pdf_path=source_pdf_path,
                        azure_result=azure_result,
                        provider=provider,
                        runtime_seconds=runtime_seconds,
                        text_blocks_enabled=False,
                        text_block_timeout_seconds=0,
                    ),
                    timeout=fallback_timeout,
                )
            except Exception as fallback_exc:
                raise AzureDINormalizationTimeoutError("Azure DI normalization timed out.") from fallback_exc

            fallback_candidates = _report_candidates(normalized_report)
            if not _persistable_candidates(fallback_candidates):
                raise AzureDINormalizationTimeoutError("Azure DI normalization timed out.") from exc
            timeout_fallback_warning = _record_timeout_fallback_warning(
                azure_result=azure_result,
                candidates=fallback_candidates,
                raw_candidate_count=len(raw_candidates),
                elapsed_seconds=time.monotonic() - normalization_started,
                timeout_seconds=normalization_timeout,
            )
            logger.warning(
                "Azure DI normalization degraded to table-only fallback for job %s: %s",
                job_id,
                json.dumps(timeout_fallback_warning, ensure_ascii=True, sort_keys=True),
            )
        except Exception as exc:
            raise RuntimeError(f"Azure DI normalization failed: {exc}") from exc

        logger.info("Azure DI normalization finished for job %s", job_id)
        normalized_candidates = _report_candidates(normalized_report)
        persistable_candidates = _persistable_candidates(normalized_candidates)
        logger.info(
            "Azure DI normalized candidate count for job %s: %s; usable row count: %s",
            job_id,
            len(normalized_candidates),
            len(persistable_candidates),
        )
        if not persistable_candidates:
            raise RuntimeError(_no_usable_rows_message(azure_result))
        execution_status.transition(
            "normalization",
            "completed",
            normalized_rows=len(normalized_candidates),
        )

        structure_result = None
        structure_task_warnings: list[dict[str, str]] = []
        classification_result = None
        classification_task_warnings: list[dict[str, str]] = []
        initial_mapping_task_warnings: list[dict[str, str]] = []
        if bool(getattr(settings, "toc_aware_pipeline_enabled", False)):
            execution_status.transition("19A_analysis", "started")
            try:
                from services.toc_aware_document_structure import (
                    analyze_document_structure,
                )

                structure_result = await asyncio.to_thread(
                    analyze_document_structure,
                    job_id=job_id,
                    azure_result=azure_result,
                    normalized_candidates=persistable_candidates,
                )
                logger.info(
                    "TOC-aware structure analysis finished for job %s: toc_detected=%s sections=%s warnings=%s",
                    job_id,
                    structure_result.toc_detected,
                    structure_result.section_count,
                    structure_result.warnings,
                )
                execution_status.transition(
                    "19A_analysis",
                    "completed",
                    version=structure_result.feature_version,
                    requires_human_review=bool(
                        any(
                            section.requires_human_review
                            for section in structure_result.sections
                        )
                    ),
                    warning_count=len(structure_result.warnings),
                )
            except Exception as exc:
                logger.exception(
                    "TOC-aware structure analysis failed safely for job %s",
                    job_id,
                )
                execution_status.fail(
                    "19A_analysis",
                    "unexpected_exception",
                    exc,
                )
                structure_task_warnings.append(
                    {
                        "code": "toc_aware_structure_analysis_failed",
                        "message": (
                            "Optional document structure analysis failed; "
                            "extraction and the existing mapping workflow continued."
                        ),
                    }
                )
        else:
            execution_status.transition(
                "19A_analysis",
                "skipped",
                reason_code="feature_disabled",
            )

        logger.info("Azure DI persistence started for job %s", job_id)
        await _stage_progress(
            db,
            job,
            progress=70,
            message="Persisting extracted data",
            progress_callback=progress_callback,
            total_pages=page_count,
        )

        item_ids_by_original_candidate = {} if structure_result is not None else None
        try:
            pages_count, items_count = await _persist_candidates(
                db,
                job_id=job_id,
                azure_result=azure_result,
                candidates=normalized_candidates,
                item_ids_by_original_candidate=item_ids_by_original_candidate,
            )
        except Exception as exc:
            raise RuntimeError(f"Azure DI persistence failed: {exc}") from exc

        logger.info("Azure DI pages persisted count for job %s: %s", job_id, pages_count)
        logger.info("Azure DI extracted items persisted count for job %s: %s", job_id, items_count)
        if items_count <= 0:
            raise RuntimeError(_no_usable_rows_message(azure_result))

        if structure_result is not None:
            from services.toc_aware_document_structure import (
                attach_persisted_extracted_row_ids,
            )

            structure_result = attach_persisted_extracted_row_ids(
                structure_result,
                item_ids_by_original_candidate or {},
            )
            for warning in structure_result.warnings:
                structure_task_warnings.append(
                    {
                        "code": str(warning),
                        "message": f"Document structure warning: {warning}.",
                    }
                )

        if bool(
            getattr(
                settings,
                "toc_aware_template_classification_enabled",
                False,
            )
        ):
            if structure_result is None:
                execution_status.transition(
                    "19B_classification",
                    "skipped",
                    reason_code="upstream_structure_missing",
                )
                classification_task_warnings.append(
                    {
                        "code": "template_classification_source_structure_unavailable",
                        "message": (
                            "Optional template classification was skipped because "
                            "the document structure result was unavailable."
                        ),
                    }
                )
            else:
                execution_status.transition("19B_classification", "started")
                try:
                    from services.toc_aware_template_classification import (
                        analyze_template_classification,
                    )

                    classification_result = await analyze_template_classification(
                        job_id=job_id,
                        filing_id=job_id,
                        structure=structure_result,
                    )
                    logger.info(
                        "Template classification finished for job %s: "
                        "primary=%s notes=%s deterministic=%s llm=%s warnings=%s",
                        job_id,
                        classification_result.total_primary_sections,
                        classification_result.total_note_subsections,
                        classification_result.deterministic_count,
                        classification_result.llm_count,
                        classification_result.warnings,
                    )
                    for warning in classification_result.warnings:
                        classification_task_warnings.append(
                            {
                                "code": str(warning),
                                "message": f"Template classification warning: {warning}.",
                            }
                        )
                    execution_status.transition(
                        "19B_classification",
                        "completed",
                        version=classification_result.classification_version,
                        requires_human_review=any(
                            outcome.requires_human_review
                            for outcome in classification_result.outcomes
                        ),
                        warning_count=len(classification_result.warnings),
                    )
                except Exception as exc:
                    logger.exception(
                        "Template classification failed safely for job %s",
                        job_id,
                    )
                    execution_status.fail(
                        "19B_classification",
                        "unexpected_exception",
                        exc,
                    )
                    classification_task_warnings.append(
                        {
                            "code": "template_classification_analysis_failed",
                            "message": (
                                "Optional template classification failed; "
                                "extraction and the existing mapping workflow continued."
                            ),
                        }
                    )
        else:
            execution_status.transition(
                "19B_classification",
                "skipped",
                reason_code="feature_disabled",
            )

        await _update_progress(
            job_id,
            90,
            JobStatus.PROCESSING,
            "Finalizing review workspace",
            progress_callback=progress_callback,
            total_pages=pages_count,
            items_extracted=items_count,
        )

        structure_artifact_persisted = False
        classification_artifact_persisted = False
        if (
            bool(getattr(settings, "toc_aware_pipeline_enabled", False))
            and bool(
                getattr(settings, "toc_aware_structure_persistence_enabled", False)
            )
        ):
            from services.toc_aware_document_structure import (
                discard_document_structure_artifact,
                persist_document_structure,
            )

            if structure_result is not None:
                execution_status.transition("19A_persistence", "started")
                try:
                    artifact_path = await asyncio.to_thread(
                        persist_document_structure,
                        structure_result,
                    )
                    logger.info(
                        "TOC-aware structure artifact persisted for job %s at %s",
                        job_id,
                        artifact_path,
                    )
                    structure_artifact_persisted = True
                    execution_status.transition(
                        "19A_persistence",
                        "completed",
                        artifact=artifact_path.name,
                        version=structure_result.feature_version,
                    )
                except Exception as exc:
                    logger.exception(
                        "TOC-aware structure artifact persistence failed safely for job %s",
                        job_id,
                    )
                    execution_status.fail(
                        "19A_persistence",
                        "artifact_write_failed",
                        exc,
                    )
                    try:
                        await asyncio.to_thread(
                            discard_document_structure_artifact,
                            job_id,
                        )
                    except Exception:
                        logger.exception(
                            "Could not discard stale TOC-aware artifact for job %s",
                            job_id,
                        )
                    structure_task_warnings.append(
                        {
                            "code": "toc_aware_structure_persistence_failed",
                            "message": (
                                "Optional document structure persistence failed; "
                                "extraction and the existing mapping workflow continued."
                            ),
                        }
                    )
            else:
                execution_status.transition(
                    "19A_persistence",
                    "skipped",
                    reason_code="upstream_structure_invalid",
                )
                try:
                    await asyncio.to_thread(
                        discard_document_structure_artifact,
                        job_id,
                    )
                except Exception:
                    logger.exception(
                        "Could not discard stale TOC-aware artifact for job %s",
                        job_id,
                    )
        else:
            execution_status.transition(
                "19A_persistence",
                "skipped",
                reason_code=(
                    "feature_disabled"
                    if not bool(getattr(settings, "toc_aware_pipeline_enabled", False))
                    else "persistence_disabled"
                ),
            )

        if (
            bool(
                getattr(
                    settings,
                    "toc_aware_template_classification_enabled",
                    False,
                )
            )
            and bool(
                getattr(
                    settings,
                    "toc_aware_template_classification_persistence_enabled",
                    False,
                )
            )
        ):
            from services.toc_aware_template_classification import (
                discard_template_classification_artifact,
                persist_template_classification,
            )

            if (
                classification_result is not None
                and structure_result is not None
                and structure_artifact_persisted
            ):
                execution_status.transition("19B_persistence", "started")
                try:
                    artifact_path = await asyncio.to_thread(
                        persist_template_classification,
                        classification_result,
                        structure=structure_result,
                    )
                    logger.info(
                        "Template classification artifact persisted for job %s at %s",
                        job_id,
                        artifact_path,
                    )
                    classification_artifact_persisted = True
                    execution_status.transition(
                        "19B_persistence",
                        "completed",
                        artifact=artifact_path.name,
                        version=classification_result.classification_version,
                    )
                except Exception as exc:
                    logger.exception(
                        "Template classification artifact persistence failed "
                        "safely for job %s",
                        job_id,
                    )
                    execution_status.fail(
                        "19B_persistence",
                        "artifact_write_failed",
                        exc,
                    )
                    try:
                        await asyncio.to_thread(
                            discard_template_classification_artifact,
                            job_id,
                        )
                    except Exception:
                        logger.exception(
                            "Could not discard stale template-classification "
                            "artifact for job %s",
                            job_id,
                        )
                    classification_task_warnings.append(
                        {
                            "code": "template_classification_persistence_failed",
                            "message": (
                                "Optional template classification persistence "
                                "failed; extraction and the existing mapping "
                                "workflow continued."
                            ),
                        }
                    )
            else:
                execution_status.transition(
                    "19B_persistence",
                    "skipped",
                    reason_code=(
                        "upstream_structure_missing"
                        if not structure_artifact_persisted
                        else "upstream_classification_missing"
                    ),
                )
                try:
                    await asyncio.to_thread(
                        discard_template_classification_artifact,
                        job_id,
                    )
                except Exception:
                    logger.exception(
                        "Could not discard stale template-classification artifact "
                        "for job %s",
                        job_id,
                    )
                classification_task_warnings.append(
                    {
                        "code": "template_classification_not_published",
                        "message": (
                            "Template classification was not published because "
                            "its validated source structure artifact was unavailable."
                        ),
                    }
                )
        else:
            execution_status.transition(
                "19B_persistence",
                "skipped",
                reason_code=(
                    "feature_disabled"
                    if not bool(
                        getattr(
                            settings,
                            "toc_aware_template_classification_enabled",
                            False,
                        )
                    )
                    else "persistence_disabled"
                ),
            )

        initial_mapping_flags = {
            "retrieval": bool(
                getattr(
                    settings,
                    "toc_aware_taxonomy_candidate_retrieval_enabled",
                    False,
                )
            ),
            "mapping": bool(
                getattr(settings, "toc_aware_initial_mapping_enabled", False)
            ),
            "persistence": bool(
                getattr(
                    settings,
                    "toc_aware_initial_mapping_persistence_enabled",
                    False,
                )
            ),
        }
        def skip_initial_mapping(reason_code: str) -> None:
            for stage_name in (
                "19C_candidate_retrieval",
                "19C_mapping_build",
                "19C_persistence",
            ):
                if execution_status.data["stages"][stage_name]["status"] == "not_started":
                    execution_status.transition(
                        stage_name,
                        "skipped",
                        reason_code=reason_code,
                    )

        def record_initial_mapping_stage(
            stage_name: str,
            stage_status: str,
            details: Mapping[str, Any],
        ) -> None:
            values = dict(details)
            reason_code = values.pop("reason_code", None)
            execution_status.transition(
                stage_name,
                stage_status,
                reason_code=reason_code,
                **values,
            )

        if not all(initial_mapping_flags.values()):
            skip_reason = (
                "persistence_disabled"
                if not initial_mapping_flags["persistence"]
                and initial_mapping_flags["retrieval"]
                and initial_mapping_flags["mapping"]
                else "feature_disabled"
            )
            skip_initial_mapping(skip_reason)
        if any(initial_mapping_flags.values()) and not all(initial_mapping_flags.values()):
            initial_mapping_task_warnings.append(
                {
                    "code": "toc_aware_initial_mapping_incomplete_configuration",
                    "message": (
                        "Optional initial mapping was skipped because retrieval, "
                        "mapping, and persistence are not all enabled."
                    ),
                }
            )
        elif all(initial_mapping_flags.values()):
            if not structure_artifact_persisted:
                skip_initial_mapping("upstream_structure_missing")
            elif not classification_artifact_persisted:
                skip_initial_mapping("upstream_classification_missing")
            else:
                try:
                    from services.section_aware_initial_mapping import (
                        InitialMappingArtifactPersistenceError,
                        InitialMappingStageError,
                        build_document_initial_mapping,
                        discard_initial_mapping_artifact,
                        persist_initial_mapping,
                        source_rows_from_normalized_candidates,
                    )

                    initial_source_rows = source_rows_from_normalized_candidates(
                        normalized_candidates,
                        item_ids_by_original_candidate=item_ids_by_original_candidate or {},
                    )
                    initial_mapping_result = await build_document_initial_mapping(
                        job_id=job_id,
                        filing_id=job_id,
                        source_rows=initial_source_rows,
                        stage_callback=record_initial_mapping_stage,
                    )
                    execution_status.transition(
                        "19C_persistence",
                        "started",
                    )
                    initial_mapping_path = await asyncio.to_thread(
                        persist_initial_mapping,
                        initial_mapping_result,
                        lifecycle_callback=execution_status.writer_transition,
                    )
                    execution_status.transition(
                        "19C_persistence",
                        "completed",
                        artifact=initial_mapping_path.name,
                        version=initial_mapping_result.mapping_version,
                    )
                    logger.info(
                        "Section-aware initial mapping artifact persisted for job %s at %s: rows=%s eligible=%s llm_calls=%s",
                        job_id,
                        initial_mapping_path,
                        initial_mapping_result.total_rows,
                        initial_mapping_result.eligible_rows,
                        initial_mapping_result.llm_calls,
                    )
                except Exception as exc:
                    if isinstance(exc, InitialMappingStageError):
                        failed_stage = exc.stage
                        reason_code = exc.reason_code
                    elif isinstance(exc, InitialMappingArtifactPersistenceError):
                        failed_stage = "19C_persistence"
                        reason_code = exc.reason_code
                    else:
                        stage_states = execution_status.data["stages"]
                        if stage_states["19C_persistence"]["status"] == "started":
                            failed_stage = "19C_persistence"
                            reason_code = "unexpected_exception"
                        elif stage_states["19C_mapping_build"]["status"] == "started":
                            failed_stage = "19C_mapping_build"
                            reason_code = "mapping_build_failed"
                        else:
                            failed_stage = "19C_mapping_build"
                            reason_code = "mapping_build_failed"
                    if execution_status.data["stages"][failed_stage]["status"] != "failed":
                        execution_status.fail(failed_stage, reason_code, exc)
                    skip_initial_mapping(reason_code)
                    logger.exception(
                        "Section-aware initial mapping failed safely for job %s",
                        job_id,
                    )
                    try:
                        await asyncio.to_thread(discard_initial_mapping_artifact, job_id)
                    except Exception:
                        logger.exception(
                            "Could not discard stale initial-mapping artifact for job %s",
                            job_id,
                        )
                    initial_mapping_task_warnings.append(
                        {
                            "code": "toc_aware_initial_mapping_failed",
                            "message": (
                                "Optional initial mapping failed; extraction and the "
                                "existing mapping workflow continued."
                            ),
                        }
                    )

        _set_job_tracking(
            job,
            status=JobStatus.REVIEW,
            progress=100,
            clear_error=True,
        )
        await db.commit()
        execution_status.finish("completed")
        logger.info("Azure DI final job status set to REVIEW for job %s", job_id)

        ai_suggestion_count: int | None = 0
        optional_stage: str | None = None
        optional_stage_status: str | None = None
        optional_stage_error_code: str | None = None
        optional_stage_error_message: str | None = None
        task_warnings: list[dict[str, str]] = []
        task_warnings.extend(structure_task_warnings)
        task_warnings.extend(classification_task_warnings)
        task_warnings.extend(initial_mapping_task_warnings)
        if timeout_fallback_warning:
            task_warnings.append(
                {
                    "code": "azure_di_text_block_normalization_timeout",
                    "message": "Text block normalization timed out; table candidates were used.",
                }
            )

        if bool(getattr(settings, "llm_mapping_enabled", False)):
            try:
                from services.llm_taxonomy_mapping import (
                    HuggingFaceQwenMappingClient,
                    run_llm_mapping_for_job,
                )

                logger.info("LLM taxonomy mapping suggestions started for job %s", job_id)
                job.ai_mapping_status = "running"
                job.ai_mapping_last_error_message = None
                await db.commit()
                suggestion_report = await run_llm_mapping_for_job(
                    db,
                    job_id,
                    llm_client=HuggingFaceQwenMappingClient(),
                    apply_high_confidence=bool(
                        getattr(settings, "llm_mapping_auto_apply_high_confidence", False)
                    ),
                    persist_suggestions=True,
                )
                job.ai_mapping_status = "completed"
                job.ai_mapping_last_error_message = None
                await db.commit()
                ai_suggestion_count = int(
                    suggestion_report.get("summary", {}).get("suggestions_generated") or 0
                )
                logger.info(
                    "LLM taxonomy mapping suggestions finished for job %s: rows_sent_to_llm=%s suggestions=%s applied=%s",
                    job_id,
                    suggestion_report.get("summary", {}).get("rows_sent_to_llm"),
                    suggestion_report.get("summary", {}).get("suggestions_generated"),
                    suggestion_report.get("summary", {}).get("applied_suggestions"),
                )
            except LLMMappingRateLimitError as exc:
                logger.warning("LLM taxonomy mapping suggestions rate limited for job %s: %s", job_id, exc)
                ai_suggestion_count = int(getattr(exc, "saved_suggestions", 0) or 0)
                optional_stage = "mapping"
                optional_stage_status = "rate_limited"
                optional_stage_error_code = str(
                    getattr(exc, "provider_error_type", "provider_rate_limited")
                    or "provider_rate_limited"
                )
                optional_stage_error_message = exc.safe_message
                task_warnings.append(
                    {
                        "code": optional_stage_error_code,
                        "message": optional_stage_error_message,
                    }
                )
                try:
                    await db.rollback()
                    job.ai_mapping_status = "rate_limited"
                    job.ai_mapping_last_error_message = exc.safe_message
                    await db.commit()
                except Exception:
                    pass
            except Exception as exc:
                logger.exception("LLM taxonomy mapping suggestions failed for job %s: %s", job_id, exc)
                error_metadata = _mapping_suggestion_error_metadata(exc)
                optional_stage = "mapping"
                optional_stage_status = "failed"
                optional_stage_error_code = error_metadata[1:].split("]", 1)[0]
                optional_stage_error_message = (
                    "AI mapping suggestions failed after extraction completed."
                )
                ai_suggestion_count = None
                task_warnings.append(
                    {
                        "code": optional_stage_error_code,
                        "message": optional_stage_error_message,
                    }
                )
                try:
                    await db.rollback()
                    job.ai_mapping_status = "failed"
                    job.ai_mapping_last_error_message = error_metadata
                    await db.commit()
                except Exception:
                    pass

        message = (
            "Azure Document Intelligence processing complete: "
            f"{items_count} rows across {pages_count} pages."
        )
        if timeout_fallback_warning:
            message += " Warning: text block normalization timed out; table candidates were used."
        await _update_progress(
            job_id,
            100,
            JobStatus.REVIEW,
            message,
            progress_callback=progress_callback,
            total_pages=pages_count,
            items_extracted=items_count,
        )
        return ProcessingStatus(
            job_id=job_id,
            status=JobStatus.REVIEW,
            progress=100,
            message=message,
            started_at=started_at,
            updated_at=_utc_now(),
            extracted_row_count=items_count,
            ai_mapping_status=job.ai_mapping_status,
            ai_suggestion_count=ai_suggestion_count,
            warnings=task_warnings,
            optional_stage=optional_stage,
            optional_stage_status=optional_stage_status,
            optional_stage_error_code=optional_stage_error_code,
            optional_stage_error_message=optional_stage_error_message,
        )
    except AzureDocumentIntelligenceConfigError as exc:
        _mark_execution_failed(execution_status)
        logger.exception("Azure DI production processing failed for job %s", job_id)
        return await _fail_job(
            db,
            job_id,
            f"Azure Document Intelligence is not configured: {exc}",
            started_at,
            progress_callback=progress_callback,
        )
    except AzureDINormalizationTimeoutError as exc:
        _mark_execution_failed(execution_status)
        logger.exception("Azure DI production normalization timed out for job %s", job_id)
        return await _fail_job(
            db,
            job_id,
            str(exc),
            started_at,
            progress_callback=progress_callback,
        )
    except TimeoutError as exc:
        _mark_execution_failed(execution_status)
        logger.exception("Azure DI production processing failed for job %s", job_id)
        return await _fail_job(
            db,
            job_id,
            f"Azure Document Intelligence timed out: {exc}",
            started_at,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        _mark_execution_failed(execution_status)
        logger.exception("Azure DI production processing failed for job %s", job_id)
        return await _fail_job(
            db,
            job_id,
            str(exc),
            started_at,
            progress_callback=progress_callback,
        )


async def _fail_job(
    db: AsyncSession,
    job_id: int,
    message: str,
    started_at: datetime,
    *,
    progress_callback: ProgressCallback | None = None,
) -> ProcessingStatus:
    safe_message = _safe_error_message(message)
    try:
        try:
            await db.rollback()
        except Exception:
            pass
        result = await db.execute(select(FilingJob).where(FilingJob.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            _set_job_tracking(
                job,
                status=JobStatus.ERROR,
                progress=0,
                error_message=safe_message,
            )
            await db.commit()
            logger.error("Azure DI final job status set to ERROR for job %s: %s", job_id, safe_message)
    except Exception as db_error:
        logger.error("Could not mark Azure DI job %s failed: %s", job_id, db_error)
        try:
            await db.rollback()
        except Exception:
            pass

    await _update_progress(
        job_id,
        0,
        JobStatus.ERROR,
        safe_message,
        progress_callback=progress_callback,
    )
    return ProcessingStatus(
        job_id=job_id,
        status=JobStatus.ERROR,
        progress=0,
        message=safe_message,
        error=safe_message,
        started_at=started_at,
        updated_at=_utc_now(),
    )
