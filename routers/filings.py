import json
import logging
from pathlib import Path
import os
from typing import List, Optional
from datetime import datetime, date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db, FilingJob, FinancialStatementPage, ExtractedDataItem, MBRSTaxonomyTag, User, LLMMappingSuggestion
from schemas import (
    FilingJobCreate, FilingJobResponse, FilingJobUpdate, PaginatedResponse,
    BulkUpdateRequest, BulkUpdateResponse, XBRLGenerationResponse, DashboardStats,
    ExtractedDataItemCreate, ExtractedDataItemResponse,
    MappingSupervisorReviewBatchRunRequest, MappingSupervisorReviewBatchRunResponse,
    MappingSupervisorReviewRead, MappingSupervisorReviewRunRequest, SupervisorReviewRunMode,
    SupervisorGuidedMappingCorrectionResponse, SupervisorGuidedMappingRevisionRead,
    SupervisorMapperFeedbackCapabilitiesRead,
    SupervisorOrchestrationCapabilitiesRead, SupervisorOrchestrationPlanResponse,
    RankedCandidateAdvisoryRequest, RankedCandidateAdvisoryResponse,
    RankedCandidateCapabilitiesRead,
    RulebookMapperCapabilitiesRead, RulebookMapperRunResponse,
    DocumentStructureCapabilitiesRead, DocumentStructureResult,
    DocumentTemplateClassificationResult, TemplateClassificationCapabilitiesRead,
    DocumentInitialMappingResult, InitialMappingCapabilitiesRead,
    InitialTaxonomyMappingResult,
)
from services.smart_ai_processor import smart_ai_processor, status_tracker
from services.xbrl_generator import generate_xbrl_for_job
from services.xbrl_template_service import get_xbrl_template_service
from services.llm_taxonomy_mapping import (
    HuggingFaceQwenMappingClient,
    LLMMappingRateLimitError,
    run_llm_mapping_for_job,
    suggestion_template_metadata,
)
from services.supervisor_production_review import (
    LIVE_SUPERVISOR_SOURCE,
    MOCK_SUPERVISOR_SOURCE,
    SupervisorLiveBatchSizeExceeded,
    SupervisorReviewNotExecutable,
    get_supervisor_review_for_job,
    list_supervisor_reviews_for_job,
    load_owned_supervisor_job,
    run_supervisor_review_for_suggestion,
    run_supervisor_reviews_for_job,
    serialize_supervisor_review,
    serialize_supervisor_reviews,
)
from services.supervisor_guided_mapping_correction import (
    SupervisorGuidedCorrectionConfig,
    SupervisorGuidedCorrectionDisabled,
    SupervisorGuidedCorrectionExecutionError,
    SupervisorGuidedCorrectionForbidden,
    SupervisorGuidedCorrectionNotEligible,
    SupervisorGuidedCorrectionNotFound,
    SupervisorGuidedCorrectionRetryLimit,
    list_supervisor_guided_revisions_for_job,
    run_supervisor_guided_mapping_correction,
    serialize_supervisor_guided_revision,
    supervisor_mapper_feedback_capabilities,
)
from services.supervisor_mapping_orchestrator import (
    SupervisorOrchestrationConfig,
    SupervisorOrchestrationDisabled,
    SupervisorOrchestrationForbidden,
    SupervisorOrchestrationNotFound,
    SupervisorOrchestrationUnsafeConfig,
    plan_supervisor_orchestration_for_job,
    supervisor_orchestration_capabilities,
)
from services.supervisor_rollout_authorization import (
    authorize_supervisor_rollout_user,
    supervisor_rollout_denial_reason,
)
from services.rulebook_mapper_advisory_service import (
    RulebookMapperAdvisoryError,
    run_rulebook_mapper_advisory_for_job,
)
from services.ranked_candidate_advisory_service import (
    RankedCandidateAdvisoryConfig,
    RankedCandidateAdvisoryError,
    advisory_capabilities,
    run_ranked_candidate_advisory_for_job,
)
from services.toc_aware_document_structure import (
    artifact_cleanup_candidate,
    document_structure_capabilities,
    load_document_structure,
)
from services.toc_aware_template_classification import (
    classification_artifact_cleanup_candidate,
    load_template_classification,
    template_classification_capabilities,
)
from services.section_aware_initial_mapping import (
    initial_mapping_artifact_cleanup_candidates,
    initial_mapping_capabilities,
    load_initial_mapping,
)
from services.toc_pipeline_execution_status import (
    pipeline_execution_status_cleanup_candidate,
)
from tasks import process_pdf_task, get_task_status
from file_safety import (
    assert_upload_child,
    build_upload_pdf_path,
    resolve_upload_path,
    safe_filename_component,
    save_bounded_pdf_upload,
    uploads_root,
    validate_pdf_upload_metadata,
)
from security import get_current_user, get_current_workspace_user, require_admin_route_token

logger = logging.getLogger(__name__)
router = APIRouter()

AI_MAPPING_STATUSES = {"not_started", "running", "completed", "failed", "rate_limited"}
AI_PROVIDER_RATE_LIMIT_MESSAGE = (
    "AI provider is temporarily rate limited. Please wait a few minutes and try again."
)
AI_MAPPING_RUNS_IN_PROGRESS: set[int] = set()
RULEBOOK_MAPPER_DISABLED_MESSAGE = "Deterministic rulebook advisory mapper is disabled."
RANKED_CANDIDATE_ADVISORY_DISABLED_MESSAGE = "Ranked candidate advisory generation is disabled."


def _normalize_template_field_id(field_id: Optional[str]) -> Optional[str]:
    if not field_id:
        return field_id
    value = str(field_id)
    underscore_index = value.find("_")
    if underscore_index > 0:
        return value[underscore_index + 1:]
    return value


def _normalize_statement_label(value: Optional[str]) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _xbrl_template_field_info(
    field_id: Optional[str],
    statement_type: Optional[str],
) -> Optional[dict]:
    normalized_field_id = _normalize_template_field_id(field_id)
    if not normalized_field_id:
        return None

    try:
        service = get_xbrl_template_service()
        concept = service.get_concept_info(normalized_field_id)
        if not concept:
            return None

        statement_code = None
        requested_statement = _normalize_statement_label(statement_type)
        for code in concept.get("templates") or []:
            description = service.get_template_description(code)
            if requested_statement and requested_statement in {
                _normalize_statement_label(code),
                _normalize_statement_label(description),
            }:
                statement_code = code
                break

        if statement_code is None:
            templates = concept.get("templates") or []
            statement_code = templates[0] if templates else None

        return {
            "id": normalized_field_id,
            "field_id": normalized_field_id,
            "label": concept.get("label"),
            "xbrl_tag": normalized_field_id,
            "statement_type": (
                service.get_template_description(statement_code)
                if statement_code
                else statement_type
            ),
            "statement_code": statement_code,
        }
    except Exception as exc:
        logger.debug("XBRL template fallback lookup failed for %s: %s", field_id, exc)
        return None


def _resolve_upload_artifact_path(path: str, subdirectory: str) -> Path:
    return resolve_upload_path(path, subdirectory)


def _display_artifact_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _safe_unlink_upload_artifact(path: str, subdirectory: str):
    if not path:
        return None, {"path": "", "reason": "missing_path"}

    try:
        candidate = assert_upload_child(path, subdirectory)
    except ValueError:
        return None, {"path": str(path), "reason": "unsafe_or_not_owned_by_job"}

    display_path = _display_artifact_path(candidate)

    if not candidate.exists():
        return None, {"path": display_path, "reason": "missing"}

    if not candidate.is_file():
        return None, {"path": display_path, "reason": "not_file"}

    try:
        candidate.unlink()
        return display_path, None
    except OSError as exc:
        return None, {
            "path": display_path,
            "reason": "delete_failed",
            "detail": str(exc),
        }


def _expected_xbrl_artifact_paths(job: FilingJob) -> List[str]:
    safe_registration_number = safe_filename_component(
        job.registration_number, "UNKNOWN")
    fye = job.financial_year_end.strftime("%Y%m%d")
    xbrl_filename = f"SSM_FS-MPERS_{safe_registration_number}_{fye}.xbrl"
    xbrl_dir = (uploads_root() / "xbrl").resolve()
    xbrl_path = xbrl_dir / xbrl_filename
    xml_path = xbrl_path.with_suffix(".xml")
    return [str(xbrl_path), str(xml_path)]


def _build_filing_job_cleanup_plan(job: FilingJob) -> dict:
    pages = list(job.pages or [])
    page_image_paths = [page.image_path for page in pages if page.image_path]
    deleted_pages_count = len(pages)
    deleted_extracted_items_count = sum(
        len(page.extracted_items or []) for page in pages)

    file_candidates = []
    if job.source_pdf_path:
        file_candidates.append((job.source_pdf_path, "pdfs"))
    file_candidates.extend((path, "pages") for path in page_image_paths)
    file_candidates.extend(
        (path, "xbrl") for path in _expected_xbrl_artifact_paths(job))
    file_candidates.append(artifact_cleanup_candidate(job.id))
    file_candidates.append(classification_artifact_cleanup_candidate(job.id))
    file_candidates.extend(initial_mapping_artifact_cleanup_candidates(job.id))
    file_candidates.append(pipeline_execution_status_cleanup_candidate(job.id))

    return {
        "file_candidates": file_candidates,
        "deleted_pages_count": deleted_pages_count,
        "deleted_extracted_items_count": deleted_extracted_items_count,
    }


def _delete_upload_artifacts(file_candidates) -> dict:
    deleted_files = []
    skipped_files = []
    warnings = []

    for path, subdirectory in file_candidates:
        deleted_path, skipped = _safe_unlink_upload_artifact(path, subdirectory)
        if deleted_path:
            deleted_files.append(deleted_path)
        elif skipped:
            skipped_files.append(skipped)
            if skipped["reason"] == "delete_failed":
                warnings.append(
                    f"Could not delete {skipped['path']}: {skipped.get('detail', 'delete failed')}"
                )

    return {
        "deleted_files": deleted_files,
        "skipped_files": skipped_files,
        "warnings": warnings,
        "deleted_files_count": len(deleted_files),
        "skipped_missing_files_count": sum(
            1 for skipped in skipped_files if skipped.get("reason") == "missing"
        ),
    }


async def _get_owned_job_or_404(
    db: AsyncSession,
    job_id: int,
    current_user: User,
    *options,
) -> FilingJob:
    stmt = select(FilingJob).where(
        FilingJob.id == job_id,
        FilingJob.user_id == current_user.id,
    )
    if options:
        stmt = stmt.options(*options)

    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Filing job not found")
    return job


async def _get_owned_page_or_404(
    db: AsyncSession,
    page_id: str,
    current_user: User,
) -> FinancialStatementPage:
    result = await db.execute(
        select(FinancialStatementPage)
        .join(FilingJob)
        .where(
            FinancialStatementPage.id == page_id,
            FilingJob.user_id == current_user.id,
        )
    )
    page = result.scalar_one_or_none()
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return page


async def _get_owned_item_or_404(
    db: AsyncSession,
    item_id: str,
    current_user: User,
) -> ExtractedDataItem:
    result = await db.execute(
        select(ExtractedDataItem)
        .join(FinancialStatementPage)
        .join(FilingJob)
        .where(
            ExtractedDataItem.id == item_id,
            FilingJob.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def _safe_json_value(value: Optional[str], fallback):
    if not value:
        return fallback
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return decoded


def _enrich_ranked_candidates(raw_candidates) -> list:
    candidates = raw_candidates if isinstance(raw_candidates, list) else []
    enriched = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        row = dict(candidate)
        template_field_id = row.get("template_field_id")
        metadata = suggestion_template_metadata(template_field_id) if template_field_id else None
        if metadata:
            row.setdefault("label", metadata.get("label"))
            row.setdefault("statement_type", metadata.get("statement_type"))
            row.setdefault("template_code", metadata.get("template_code"))
        enriched.append(row)
    return enriched


def _confidence_category(confidence: float) -> str:
    value = max(0.0, min(1.0, float(confidence or 0.0)))
    if value >= settings.llm_mapping_high_confidence_threshold:
        return "high"
    if value >= settings.llm_mapping_min_display_confidence:
        return "medium"
    return "low"


def _serialize_ai_mapping_suggestion(suggestion: LLMMappingSuggestion) -> dict:
    item = suggestion.extracted_data_item
    page = item.page if item is not None else None
    metadata = (
        suggestion_template_metadata(suggestion.suggested_template_field_id)
        if suggestion.suggested_template_field_id
        else None
    )
    diagnostic = _safe_json_value(suggestion.diagnostic_json, {})
    diagnostic_suggestion = (
        diagnostic.get("suggestion") if isinstance(diagnostic, dict) else {}
    ) or {}

    return {
        "id": suggestion.id,
        "job_id": suggestion.job_id,
        "extracted_data_item_id": suggestion.extracted_data_item_id,
        "extracted_label": item.extracted_label if item is not None else None,
        "extracted_value": item.extracted_value if item is not None else None,
        "item_statement_type": item.statement_type if item is not None else None,
        "page_number": page.page_number if page is not None else None,
        "suggested_template_field_id": suggestion.suggested_template_field_id,
        "suggested_template_field_label": metadata.get("label") if metadata else None,
        "suggested_statement_type": metadata.get("statement_type") if metadata else None,
        "suggested_template_code": metadata.get("template_code") if metadata else None,
        "confidence": suggestion.confidence or 0.0,
        "reason": suggestion.reason,
        "ranked_candidates": _enrich_ranked_candidates(
            _safe_json_value(suggestion.ranked_candidates_json, [])
        ),
        "status": suggestion.status,
        "model_id": suggestion.model_id,
        "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        "requires_human_confirmation": bool(
            diagnostic_suggestion.get("requires_human_confirmation", suggestion.status == "suggested")
        ),
        "rejection_reason": diagnostic_suggestion.get("rejection_reason"),
        "warning_level": diagnostic_suggestion.get("warning_level"),
        "confidence_category": diagnostic_suggestion.get("confidence_category")
        or _confidence_category(suggestion.confidence or 0.0),
        "prompt_mode": diagnostic.get("prompt_mode") if isinstance(diagnostic, dict) else None,
        "fewshot_examples_count": (
            diagnostic.get("fewshot_examples_count") if isinstance(diagnostic, dict) else 0
        ) or 0,
        "fewshot_example_ids": (
            diagnostic.get("fewshot_example_ids") if isinstance(diagnostic, dict) else []
        ) or [],
        "fewshot_source_case_ids": (
            diagnostic.get("fewshot_source_case_ids") if isinstance(diagnostic, dict) else []
        ) or [],
        "candidate_count": diagnostic.get("candidate_count") if isinstance(diagnostic, dict) else None,
    }


async def _list_owned_ai_mapping_suggestions(
    db: AsyncSession,
    job_id: int,
) -> list[LLMMappingSuggestion]:
    result = await db.execute(
        select(LLMMappingSuggestion)
        .join(
            ExtractedDataItem,
            LLMMappingSuggestion.extracted_data_item_id == ExtractedDataItem.id,
        )
        .join(FinancialStatementPage, ExtractedDataItem.page_id == FinancialStatementPage.id)
        .where(
            LLMMappingSuggestion.job_id == job_id,
            FinancialStatementPage.job_id == job_id,
        )
        .options(
            selectinload(LLMMappingSuggestion.extracted_data_item).selectinload(
                ExtractedDataItem.page
            )
        )
        .order_by(
            LLMMappingSuggestion.status,
            LLMMappingSuggestion.created_at.desc(),
            LLMMappingSuggestion.id,
        )
    )
    return result.scalars().unique().all()


def _normalize_ai_mapping_status(status: Optional[str]) -> str:
    value = str(status or "not_started").strip().lower()
    return value if value in AI_MAPPING_STATUSES else "not_started"


def _ai_mapping_counts(suggestions: list[LLMMappingSuggestion]) -> dict:
    pending = sum(1 for suggestion in suggestions if suggestion.status == "suggested")
    accepted = sum(1 for suggestion in suggestions if suggestion.status == "accepted")
    no_safe = sum(1 for suggestion in suggestions if suggestion.status == "rejected")
    rejected = sum(
        1
        for suggestion in suggestions
        if suggestion.status in {"ignored", "rejected"}
    )
    return {
        "suggestions_count": len(suggestions),
        "pending_suggestions_count": pending,
        "accepted_suggestions_count": accepted,
        "rejected_suggestions_count": rejected,
        "no_safe_mapping_count": no_safe,
    }


def _datetime_iso_or_none(value) -> Optional[str]:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else None


def _serialize_ai_mapping_status(
    job: FilingJob,
    suggestions: list[LLMMappingSuggestion],
) -> dict:
    counts = _ai_mapping_counts(suggestions)
    status = _normalize_ai_mapping_status(getattr(job, "ai_mapping_status", None))
    if status == "not_started" and counts["suggestions_count"] > 0:
        status = "completed"
    rate_limited_rows_count = int(getattr(job, "ai_mapping_rate_limited_rows_count", 0) or 0)
    if status == "rate_limited" and rate_limited_rows_count <= 0:
        rate_limited_rows_count = 1
    return {
        "job_id": job.id,
        "ai_mapping_status": status,
        **counts,
        "rate_limited_rows_count": rate_limited_rows_count if status == "rate_limited" else 0,
        "started_at": _datetime_iso_or_none(getattr(job, "ai_mapping_started_at", None)),
        "finished_at": _datetime_iso_or_none(getattr(job, "ai_mapping_finished_at", None)),
        "last_error_message": getattr(job, "ai_mapping_last_error_message", None),
    }


def _supervisor_mode_source(mode: SupervisorReviewRunMode) -> str:
    return LIVE_SUPERVISOR_SOURCE if mode == SupervisorReviewRunMode.LIVE else MOCK_SUPERVISOR_SOURCE


def _ensure_supervisor_live_allowed(mode: SupervisorReviewRunMode, current_user: User) -> None:
    if mode != SupervisorReviewRunMode.LIVE:
        return
    if not settings.supervisor_production_live_enabled:
        raise HTTPException(
            status_code=403,
            detail=(
                "Live Supervisor execution is disabled. "
                "Set SUPERVISOR_PRODUCTION_LIVE_ENABLED=true to allow explicit live runs."
            ),
        )
    authorization = authorize_supervisor_rollout_user(
        user_id=current_user.id,
        is_admin=bool(current_user.is_admin),
        allowed_user_ids=settings.supervisor_orchestration_allowed_user_ids,
    )
    if not authorization.authorized:
        raise HTTPException(
            status_code=403,
            detail=supervisor_rollout_denial_reason(authorization),
        )


def _rulebook_mapper_advisory_mode() -> str:
    mode = str(
        getattr(settings, "rulebook_mapper_advisory_default_mode", "dry_run") or "dry_run"
    ).strip().lower()
    return mode if mode == "dry_run" else "dry_run"


def _rulebook_mapper_capabilities(job_id: int) -> dict:
    return {
        "job_id": job_id,
        "enabled": bool(getattr(settings, "rulebook_mapper_advisory_enabled", False)),
        "default_mode": _rulebook_mapper_advisory_mode(),
        "allow_persistence": False,
        "supported_modes": ["dry_run"],
        "endpoints": [
            f"/api/v1/filings/jobs/{job_id}/rulebook-mapper/capabilities",
            f"/api/v1/filings/jobs/{job_id}/rulebook-mapper/run",
        ],
        "safety": {
            "advisory_only": True,
            "dry_run_only": True,
            "persistence_enabled": False,
            "auto_apply_enabled": False,
            "safe_for_auto_apply_always_false": True,
            "confirmed_mapping_mutation_allowed": False,
            "ai_mapping_suggestion_mutation_allowed": False,
            "external_llm_called": False,
            "supervisor_called": False,
            "qwen_called": False,
        },
    }


def _ranked_candidate_advisory_config() -> RankedCandidateAdvisoryConfig:
    return RankedCandidateAdvisoryConfig.from_settings(settings)


def _ensure_ranked_candidate_advisory_admin_allowed(
    config: RankedCandidateAdvisoryConfig,
    current_user: User,
) -> None:
    if config.admin_only and not bool(getattr(current_user, "is_admin", False)):
        raise HTTPException(
            status_code=403,
            detail="Admin access required for ranked candidate advisory generation.",
        )


async def _set_ai_mapping_status(
    job: FilingJob,
    status: str,
    *,
    error_message: Optional[str] = None,
) -> None:
    job.ai_mapping_status = _normalize_ai_mapping_status(status)
    job.ai_mapping_last_error_message = error_message


async def _delete_refreshable_ai_mapping_suggestions(
    db: AsyncSession,
    job_id: int,
) -> int:
    """Remove stale machine states while preserving explicit user decisions."""
    result = await db.execute(
        select(LLMMappingSuggestion).where(
            LLMMappingSuggestion.job_id == job_id,
            LLMMappingSuggestion.status.in_(("suggested", "rejected")),
        )
    )
    suggestions = result.scalars().all()
    for suggestion in suggestions:
        maybe_awaitable = db.delete(suggestion)
        if hasattr(maybe_awaitable, "__await__"):
            await maybe_awaitable
    if suggestions:
        await db.flush()
    return len(suggestions)


async def _get_suggestion_for_owned_item_or_404(
    db: AsyncSession,
    item_id: str,
    suggestion_id: str,
) -> LLMMappingSuggestion:
    result = await db.execute(
        select(LLMMappingSuggestion)
        .where(
            LLMMappingSuggestion.id == suggestion_id,
            LLMMappingSuggestion.extracted_data_item_id == item_id,
        )
        .options(
            selectinload(LLMMappingSuggestion.extracted_data_item).selectinload(
                ExtractedDataItem.page
            )
        )
    )
    suggestion = result.scalar_one_or_none()
    if not suggestion:
        raise HTTPException(status_code=404, detail="AI mapping suggestion not found")
    return suggestion


@router.post("/upload", response_model=FilingJobResponse)
async def upload_filing(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
    company_name: str = Form(...),
    registration_number: Optional[str] = Form(None),
    financial_year_end: date = Form(...),
    file: UploadFile = File(...)
):
    """Upload a new filing PDF and start background processing with Celery - FIXED VERSION"""

    validate_pdf_upload_metadata(file)
    file_path = build_upload_pdf_path()

    try:
        save_bounded_pdf_upload(file, file_path)

        # Create filing job record
        job = FilingJob(
            user_id=current_user.id,
            company_name=company_name,
            registration_number=registration_number,
            financial_year_end=financial_year_end,
            source_pdf_path=str(file_path),
            status="PROCESSING"
        )

        db.add(job)
        await db.flush()  # Get the job ID
        await db.commit()

        # FIXED: Import and start background processing with Celery
        try:
            from tasks import process_pdf_task
            task = process_pdf_task.delay(job.id)

            logger.info(
                f"鉁?Created filing job {job.id} with Celery task {task.id}")

            # Store task ID for tracking (optional)
            # You could add a task_id field to FilingJob model if needed

        except Exception as celery_error:
            logger.error(
                f"鉂?Failed to start Celery task for job {job.id}: {celery_error}")
            # Update job status to ERROR if Celery task fails to start
            job.status = "ERROR"
            await db.commit()
            raise HTTPException(
                status_code=500, detail=f"Failed to start processing: {str(celery_error)}")

        return job

    except Exception as e:
        logger.error(f"Error uploading filing: {e}")
        # Clean up file if job creation failed
        if file_path.exists():
            file_path.unlink()
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail="Failed to upload filing")


@router.get("/jobs", response_model=List[FilingJobResponse])
async def get_filing_jobs(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
    status: Optional[str] = Query(None),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0)
):
    """Get list of filing jobs with optional filtering"""

    stmt = (
        select(FilingJob)
        .where(FilingJob.user_id == current_user.id)
        .order_by(FilingJob.uploaded_at.desc())
    )

    if status:
        stmt = stmt.where(FilingJob.status == status.upper())

    stmt = stmt.limit(limit).offset(offset)

    result = await db.execute(stmt)
    jobs = result.scalars().all()

    return jobs


@router.get("/jobs/{job_id}", response_model=FilingJobResponse)
async def get_filing_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Get specific filing job with eager-loaded relationships"""

    # Eagerly load relationships to ensure we get the latest saved data
    job = await _get_owned_job_or_404(
        db,
        job_id,
        current_user,
        (
            selectinload(FilingJob.pages).selectinload(
                FinancialStatementPage.extracted_items)
        ),
    )

    return job


@router.put("/jobs/{job_id}", response_model=FilingJobResponse)
async def update_filing_job(
    job_id: int,
    job_update: FilingJobUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Update filing job details"""

    job = await _get_owned_job_or_404(db, job_id, current_user)

    # Update fields
    update_data = job_update.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(job, field, value)

    await db.commit()

    return job


@router.get("/jobs/{job_id}/status")
async def get_job_status(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Get current processing status of a job"""

    await _get_owned_job_or_404(db, job_id, current_user)
    status = await status_tracker.get_status(job_id, db)
    return {
        "job_id": status.job_id,
        "status": status.status,
        "progress": status.progress,
        "message": status.message,
        "error": status.error
    }


@router.get("/jobs/{job_id}/pages")
async def get_job_pages(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Get pages for a filing job"""

    await _get_owned_job_or_404(db, job_id, current_user)
    result = await db.execute(
        select(FinancialStatementPage)
        .where(FinancialStatementPage.job_id == job_id)
        .order_by(FinancialStatementPage.page_number)
    )
    pages = result.scalars().all()

    return [
        {
            "id": page.id,
            "page_number": page.page_number,
            "image_url": f"/filings/jobs/{job_id}/pages/{page.page_number}/image"
        }
        for page in pages
    ]


@router.get("/jobs/{job_id}/pages/{page_number}/image")
async def get_job_page_image(
    job_id: int,
    page_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Render a page image on demand for review screens."""
    job = await _get_owned_job_or_404(db, job_id, current_user)
    page_result = await db.execute(
        select(FinancialStatementPage)
        .where(FinancialStatementPage.job_id == job_id)
        .where(FinancialStatementPage.page_number == page_number)
    )
    page = page_result.scalar_one_or_none()

    if not page:
        raise HTTPException(status_code=404, detail="Page not found")

    image_path = page.image_path
    if not image_path or not os.path.exists(image_path):
        try:
            image_path = smart_ai_processor.ensure_page_image_for_job(
                source_pdf_path=job.source_pdf_path,
                job_id=job_id,
                page_number=page_number
            )
        except IndexError:
            raise HTTPException(status_code=404, detail="Page image not available")

    safe_image_path = _resolve_upload_artifact_path(image_path, "pages")
    return FileResponse(safe_image_path, media_type="image/png")

# routers/filings.py - Fix the get_extracted_data endpoint


@router.get("/jobs/{job_id}/extracted-data", response_model=PaginatedResponse)
async def get_extracted_data(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=1000),
    reviewed_only: bool = Query(False)
):
    """Get extracted data items for a job with pagination - FIXED for template fields"""

    logger.info(
        f"馃摜 Fetching extracted data for job {job_id}, page {page}, size {size}")

    try:
        await _get_owned_job_or_404(db, job_id, current_user)
        # Build query with proper joins for template fields
        stmt = (
            select(ExtractedDataItem)
            .join(FinancialStatementPage)
            .where(FinancialStatementPage.job_id == job_id)
            .options(
                selectinload(ExtractedDataItem.confirmed_tag),
                selectinload(ExtractedDataItem.page)
            )
            .order_by(FinancialStatementPage.page_number, ExtractedDataItem.id)
        )

        if reviewed_only:
            stmt = stmt.where(ExtractedDataItem.is_reviewed == True)

        # Get total count
        count_stmt = (
            select(func.count(ExtractedDataItem.id))
            .join(FinancialStatementPage)
            .where(FinancialStatementPage.job_id == job_id)
        )

        if reviewed_only:
            count_stmt = count_stmt.where(
                ExtractedDataItem.is_reviewed == True)

        total_result = await db.execute(count_stmt)
        total = total_result.scalar()

        # Get paginated results
        offset = (page - 1) * size
        paginated_stmt = stmt.limit(size).offset(offset)

        result = await db.execute(paginated_stmt)
        items = result.scalars().all()

        # Get ALL unique template field IDs from items
        template_field_ids = list(set([
            item.template_field_id for item in items
            if item.template_field_id
        ]))

        template_fields = {}

        if template_field_ids:
            from database import XMLTemplateField
            # Fetch template fields in bulk
            template_stmt = select(XMLTemplateField).where(
                XMLTemplateField.field_id.in_(template_field_ids)
            )
            template_result = await db.execute(template_stmt)
            template_rows = template_result.scalars().all()

            # Create lookup dictionary by field_id
            for template_field in template_rows:
                template_fields[template_field.field_id] = {
                    'id': template_field.id,
                    'field_id': template_field.field_id,
                    'label': template_field.label,
                    'xbrl_tag': template_field.xbrl_tag,
                    'statement_type': template_field.statement_type,
                    'statement_code': template_field.statement_code
                }

        # Format response with proper template field information
        formatted_items = []
        for item in items:
            # Get template field info if available
            template_field_info = None
            if item.template_field_id and item.template_field_id in template_fields:
                template_field_info = template_fields[item.template_field_id]
            if template_field_info is None and item.template_field_id:
                template_field_info = _xbrl_template_field_info(
                    item.template_field_id,
                    item.statement_type,
                )

            item_data = {
                "id": item.id,
                "page_id": item.page_id,
                "extracted_label": item.extracted_label,
                "extracted_value": item.extracted_value,
                "financial_year": item.financial_year,
                "is_reviewed": item.is_reviewed,
                "confirmed_tag_id": item.confirmed_tag_id,
                "page_number": item.page.page_number,
                "statement_type": item.statement_type,

                # Template field information - PROPERLY STRUCTURED
                "template_field_id": item.template_field_id,
                "template_field_label": template_field_info['label'] if template_field_info else None,
                "template_xbrl_tag": template_field_info['xbrl_tag'] if template_field_info else None,

                # For backward compatibility - use template field label if available
                "confirmed_tag_label": (
                    template_field_info['label'] if template_field_info
                    else (item.confirmed_tag.label if item.confirmed_tag else None)
                )
            }

            # Add multi-year fields if they exist
            if hasattr(item, 'value_previous_year'):
                item_data["value_previous_year"] = item.value_previous_year
            if hasattr(item, 'financial_year_previous'):
                item_data["financial_year_previous"] = item.financial_year_previous

            formatted_items.append(item_data)

        pages = (total + size - 1) // size

        logger.info(
            f"Fetched {len(formatted_items)} items for job {job_id}, {len(template_field_ids)} template matches")

        return PaginatedResponse(
            items=formatted_items,
            total=total,
            page=page,
            size=size,
            pages=pages,
            has_next=page < pages,
            has_previous=page > 1
        )

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error(f"Error fetching extracted data: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch data: {str(e)}")


@router.get(
    "/jobs/{job_id}/document-structure/capabilities",
    response_model=DocumentStructureCapabilitiesRead,
)
async def get_document_structure_capabilities(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return disabled-by-default #19A capability state for an owned job."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    return document_structure_capabilities(job_id, job_status=job.status)


@router.get(
    "/jobs/{job_id}/document-structure",
    response_model=DocumentStructureResult,
)
async def get_document_structure(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return a persisted, validated #19A structure artifact for an owned job."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    capabilities = document_structure_capabilities(job_id, job_status=job.status)
    if not capabilities.available:
        raise HTTPException(status_code=404, detail="Document structure is unavailable")
    try:
        return load_document_structure(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Document structure is unavailable")
    except (ValueError, TypeError):
        logger.exception("Document structure artifact is invalid for job %s", job_id)
        raise HTTPException(status_code=500, detail="Document structure artifact is invalid")


@router.get(
    "/jobs/{job_id}/template-classification/capabilities",
    response_model=TemplateClassificationCapabilitiesRead,
)
async def get_template_classification_capabilities(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return false-default #19B capability state for an owned job."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    return template_classification_capabilities(job_id, job_status=job.status)


@router.get(
    "/jobs/{job_id}/template-classification",
    response_model=DocumentTemplateClassificationResult,
)
async def get_template_classification(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return a persisted, source-validated #19B artifact for an owned job."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    capabilities = template_classification_capabilities(
        job_id,
        job_status=job.status,
    )
    if not capabilities.available:
        raise HTTPException(
            status_code=404,
            detail="Template classification is unavailable",
        )
    try:
        return load_template_classification(job_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail="Template classification is unavailable",
        )
    except (ValueError, TypeError):
        logger.exception(
            "Template classification artifact is invalid for job %s",
            job_id,
        )
        raise HTTPException(
            status_code=500,
            detail="Template classification artifact is invalid",
        )


@router.get(
    "/jobs/{job_id}/initial-mapping/capabilities",
    response_model=InitialMappingCapabilitiesRead,
)
async def get_initial_mapping_capabilities(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return false-default #19C capability state for an owned job."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    return initial_mapping_capabilities(job_id, job_status=job.status)


@router.get(
    "/jobs/{job_id}/initial-mapping",
    response_model=DocumentInitialMappingResult,
)
async def get_initial_mapping(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return a persisted, source-validated advisory #19C artifact."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    capabilities = initial_mapping_capabilities(job_id, job_status=job.status)
    if not capabilities.available:
        raise HTTPException(status_code=404, detail="Initial mapping is unavailable")
    try:
        return load_initial_mapping(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Initial mapping is unavailable")
    except (ValueError, TypeError):
        logger.exception("Initial mapping artifact is stale or invalid for job %s", job_id)
        raise HTTPException(status_code=409, detail="Initial mapping artifact is stale or invalid")


@router.get(
    "/jobs/{job_id}/initial-mapping/rows/{row_id}",
    response_model=InitialTaxonomyMappingResult,
)
async def get_initial_mapping_row(
    job_id: int,
    row_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return one bounded row result from an owned, validated #19C artifact."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    capabilities = initial_mapping_capabilities(job_id, job_status=job.status)
    if not capabilities.available:
        raise HTTPException(status_code=404, detail="Initial mapping is unavailable")
    try:
        artifact = load_initial_mapping(job_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Initial mapping is unavailable")
    except (ValueError, TypeError):
        raise HTTPException(status_code=409, detail="Initial mapping artifact is stale or invalid")
    mapping = next((item for item in artifact.mappings if item.source_row_id == row_id), None)
    if mapping is None:
        raise HTTPException(status_code=404, detail="Initial mapping row is unavailable")
    return mapping


@router.get("/jobs/{job_id}/ai-mapping-suggestions")
async def get_ai_mapping_suggestions(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return persisted Qwen AI mapping suggestions for an owned filing job."""

    await _get_owned_job_or_404(db, job_id, current_user)
    suggestions = await _list_owned_ai_mapping_suggestions(db, job_id)
    return {
        "job_id": job_id,
        "suggestions": [
            _serialize_ai_mapping_suggestion(suggestion)
            for suggestion in suggestions
        ],
    }


@router.get("/jobs/{job_id}/ai-mapping-suggestions/status")
async def get_ai_mapping_suggestions_status(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return Qwen AI mapping suggestion generation status and counts."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    suggestions = await _list_owned_ai_mapping_suggestions(db, job_id)
    return _serialize_ai_mapping_status(job, suggestions)


@router.get(
    "/jobs/{job_id}/supervisor-reviews",
    response_model=List[MappingSupervisorReviewRead],
)
async def get_supervisor_reviews(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return persisted advisory Supervisor reviews for an owned filing job."""

    job = await load_owned_supervisor_job(db, job_id=job_id, user_id=current_user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Filing job not found")
    reviews = await list_supervisor_reviews_for_job(db, job_id=job.id)
    return serialize_supervisor_reviews(reviews)


@router.get(
    "/jobs/{job_id}/supervisor-reviews/{review_id}",
    response_model=MappingSupervisorReviewRead,
)
async def get_supervisor_review(
    job_id: int,
    review_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return one persisted advisory Supervisor review for an owned filing job."""

    job = await load_owned_supervisor_job(db, job_id=job_id, user_id=current_user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Filing job not found")
    review = await get_supervisor_review_for_job(db, job_id=job.id, review_id=review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Supervisor review not found")
    return serialize_supervisor_review(review)


@router.post(
    "/jobs/{job_id}/supervisor-reviews/run",
    response_model=MappingSupervisorReviewRead,
)
async def run_supervisor_review(
    job_id: int,
    request: Optional[MappingSupervisorReviewRunRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Explicitly run one advisory Supervisor review for an AI mapping suggestion."""

    body = request or MappingSupervisorReviewRunRequest()
    suggestion_id = body.suggestion_id
    if not suggestion_id:
        raise HTTPException(status_code=400, detail="llm_mapping_suggestion_id is required")

    job = await load_owned_supervisor_job(db, job_id=job_id, user_id=current_user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Filing job not found")
    _ensure_supervisor_live_allowed(body.mode, current_user)

    try:
        review, _created = await run_supervisor_review_for_suggestion(
            db,
            job_id=job.id,
            suggestion_id=suggestion_id,
            user_id=current_user.id,
            force_refresh=body.force_refresh,
            source=_supervisor_mode_source(body.mode),
        )
    except SupervisorReviewNotExecutable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if review is None:
        raise HTTPException(status_code=404, detail="AI mapping suggestion not found")
    return serialize_supervisor_review(review)


@router.post(
    "/jobs/{job_id}/supervisor-reviews/run-batch",
    response_model=MappingSupervisorReviewBatchRunResponse,
)
async def run_supervisor_reviews_batch(
    job_id: int,
    request: Optional[MappingSupervisorReviewBatchRunRequest] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Explicitly run advisory Supervisor reviews for all AI suggestions in an owned job."""

    body = request or MappingSupervisorReviewBatchRunRequest()
    job = await load_owned_supervisor_job(db, job_id=job_id, user_id=current_user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Filing job not found")
    _ensure_supervisor_live_allowed(body.mode, current_user)

    try:
        result = await run_supervisor_reviews_for_job(
            db,
            job_id=job_id,
            user_id=current_user.id,
            force_refresh=body.force_refresh,
            source=_supervisor_mode_source(body.mode),
            max_batch_size=(
                settings.supervisor_production_live_max_batch_size
                if body.mode == SupervisorReviewRunMode.LIVE
                else None
            ),
            suggestion_ids=body.suggestion_ids,
        )
    except SupervisorLiveBatchSizeExceeded as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SupervisorReviewNotExecutable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Filing job not found")

    reviews, created_count, reused_count = result
    return {
        "job_id": job_id,
        "mode": body.mode,
        "force_refresh": body.force_refresh,
        "reviews_created": created_count,
        "reviews_reused": reused_count,
        "reviews": serialize_supervisor_reviews(reviews),
    }


@router.get(
    "/jobs/{job_id}/supervisor-mapper-feedback/capabilities",
    response_model=SupervisorMapperFeedbackCapabilitiesRead,
)
async def get_supervisor_mapper_feedback_capabilities(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return effective visibility gates for the explicit correction action."""

    job = await load_owned_supervisor_job(db, job_id=job_id, user_id=current_user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Filing job not found")
    return supervisor_mapper_feedback_capabilities(
        job_id=job.id,
        is_admin=bool(current_user.is_admin),
        user_id=current_user.id,
    )


@router.get(
    "/jobs/{job_id}/supervisor-guided-mapping-revisions",
    response_model=List[SupervisorGuidedMappingRevisionRead],
)
async def get_supervisor_guided_mapping_revisions(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List separate advisory revisions for an owned filing job."""

    job = await load_owned_supervisor_job(db, job_id=job_id, user_id=current_user.id)
    if job is None:
        raise HTTPException(status_code=404, detail="Filing job not found")
    revisions = await list_supervisor_guided_revisions_for_job(db, job_id=job.id)
    return [serialize_supervisor_guided_revision(revision) for revision in revisions]


@router.post(
    "/jobs/{job_id}/suggestions/{suggestion_id}/remap-with-supervisor-feedback",
    response_model=SupervisorGuidedMappingCorrectionResponse,
)
async def remap_with_supervisor_feedback(
    job_id: int,
    suggestion_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Explicitly create one human-review-required mapping revision."""

    try:
        return await run_supervisor_guided_mapping_correction(
            db,
            job_id=job_id,
            suggestion_id=suggestion_id,
            user_id=current_user.id,
            is_admin=bool(current_user.is_admin),
            config=SupervisorGuidedCorrectionConfig.from_settings(),
        )
    except SupervisorGuidedCorrectionDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SupervisorGuidedCorrectionForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SupervisorGuidedCorrectionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisorGuidedCorrectionRetryLimit as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SupervisorGuidedCorrectionNotEligible as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SupervisorGuidedCorrectionExecutionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get(
    "/jobs/{job_id}/supervisor-orchestration/capabilities",
    response_model=SupervisorOrchestrationCapabilitiesRead,
)
async def get_supervisor_orchestration_capabilities(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return owned-job gates for local, plan-only Supervisor orchestration."""

    job = await load_owned_supervisor_job(
        db,
        job_id=job_id,
        user_id=current_user.id,
    )
    if job is None:
        raise HTTPException(status_code=404, detail="Filing job not found")
    return supervisor_orchestration_capabilities(
        job_id=job.id,
        is_admin=bool(current_user.is_admin),
        user_id=current_user.id,
        config=SupervisorOrchestrationConfig.from_settings(),
    )


@router.get(
    "/jobs/{job_id}/supervisor-orchestration/plan",
    response_model=SupervisorOrchestrationPlanResponse,
)
async def get_supervisor_orchestration_plan(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Evaluate local queue eligibility without calling Supervisor or mapper."""

    try:
        plan = await plan_supervisor_orchestration_for_job(
            db,
            job_id=job_id,
            user_id=current_user.id,
            is_admin=bool(current_user.is_admin),
            config=SupervisorOrchestrationConfig.from_settings(),
        )
        logger.info(
            "supervisor_orchestration_plan_requested user_id=%s job_id=%s "
            "eligible=%s high=%s medium=%s review_executable=%s",
            current_user.id,
            job_id,
            plan["policy_eligible_count"],
            plan["high_priority_count"],
            plan["medium_priority_count"],
            plan["review_executable_count"],
        )
        return plan
    except SupervisorOrchestrationDisabled as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SupervisorOrchestrationForbidden as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except SupervisorOrchestrationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SupervisorOrchestrationUnsafeConfig as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/jobs/{job_id}/rulebook-mapper/capabilities",
    response_model=RulebookMapperCapabilitiesRead,
)
async def get_rulebook_mapper_capabilities(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return read-only capability metadata for deterministic advisory mapping."""

    await _get_owned_job_or_404(db, job_id, current_user)
    return _rulebook_mapper_capabilities(job_id)


@router.post(
    "/jobs/{job_id}/rulebook-mapper/run",
    response_model=RulebookMapperRunResponse,
)
async def run_rulebook_mapper_advisory(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Run deterministic rulebook suggestions as advisory-only dry-run evidence."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    if not bool(getattr(settings, "rulebook_mapper_advisory_enabled", False)):
        raise HTTPException(status_code=403, detail=RULEBOOK_MAPPER_DISABLED_MESSAGE)

    try:
        return await run_rulebook_mapper_advisory_for_job(
            db,
            job=job,
            mode=_rulebook_mapper_advisory_mode(),
        )
    except RulebookMapperAdvisoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/jobs/{job_id}/ranked-candidates/capabilities",
    response_model=RankedCandidateCapabilitiesRead,
)
async def get_ranked_candidate_advisory_capabilities(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Return read-only capability metadata for ranked candidate advisory."""

    await _get_owned_job_or_404(db, job_id, current_user)
    return advisory_capabilities(
        job_id,
        config=_ranked_candidate_advisory_config(),
    )


@router.post(
    "/jobs/{job_id}/ranked-candidates/run",
    response_model=RankedCandidateAdvisoryResponse,
)
async def run_ranked_candidate_advisory(
    job_id: int,
    body: RankedCandidateAdvisoryRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Run ranked candidate generation as advisory-only dry-run evidence."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    config = _ranked_candidate_advisory_config()
    if not config.enabled:
        raise HTTPException(
            status_code=403,
            detail=RANKED_CANDIDATE_ADVISORY_DISABLED_MESSAGE,
        )
    _ensure_ranked_candidate_advisory_admin_allowed(config, current_user)

    try:
        return await run_ranked_candidate_advisory_for_job(
            db,
            job=job,
            request=body,
            config=config,
        )
    except RankedCandidateAdvisoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/{job_id}/ai-mapping-suggestions/run")
async def run_ai_mapping_suggestions(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Run Qwen suggestion generation for an owned job without auto-applying results."""

    job = await _get_owned_job_or_404(db, job_id, current_user)
    existing_suggestions = await _list_owned_ai_mapping_suggestions(db, job_id)
    current_status = _normalize_ai_mapping_status(getattr(job, "ai_mapping_status", None))

    if job_id in AI_MAPPING_RUNS_IN_PROGRESS or current_status == "running":
        status = _serialize_ai_mapping_status(job, existing_suggestions)
        status["ai_mapping_status"] = "running"
        return {
            "job_id": job_id,
            "run_skipped": True,
            "already_running": True,
            "message": "AI mapping suggestions are already being generated.",
            "status": status,
            "suggestions": [
                _serialize_ai_mapping_suggestion(suggestion)
                for suggestion in existing_suggestions
            ],
        }

    if not bool(getattr(settings, "llm_mapping_enabled", False)):
        if existing_suggestions:
            return {
                "job_id": job_id,
                "run_skipped": True,
                "message": "LLM mapping is disabled. Existing AI mapping suggestions loaded.",
                "status": _serialize_ai_mapping_status(job, existing_suggestions),
                "summary": {
                    "suggestions_returned": len(existing_suggestions),
                    "db_mutated_extracted_data_items": False,
                },
                "suggestions": [
                    _serialize_ai_mapping_suggestion(suggestion)
                    for suggestion in existing_suggestions
                ],
            }
        raise HTTPException(
            status_code=400,
            detail="LLM mapping is disabled. Set LLM_MAPPING_ENABLED=true to run AI suggestions.",
        )

    if existing_suggestions and current_status not in {"failed", "rate_limited"}:
        return {
            "job_id": job_id,
            "run_skipped": True,
            "already_has_suggestions": True,
            "message": "Existing AI mapping suggestions loaded.",
            "status": _serialize_ai_mapping_status(job, existing_suggestions),
            "summary": {
                "suggestions_returned": len(existing_suggestions),
                "db_mutated_extracted_data_items": False,
            },
            "suggestions": [
                _serialize_ai_mapping_suggestion(suggestion)
                for suggestion in existing_suggestions
            ],
        }

    AI_MAPPING_RUNS_IN_PROGRESS.add(job_id)
    try:
        await _set_ai_mapping_status(job, "running")
        await db.commit()
        refreshed_suggestions = 0
        report = await run_llm_mapping_for_job(
            db,
            job_id,
            llm_client=HuggingFaceQwenMappingClient(),
            include_mapped=False,
            apply_high_confidence=False,
            persist_suggestions=True,
        )
        await _set_ai_mapping_status(job, "completed")
        await db.commit()
    except LLMMappingRateLimitError as exc:
        await db.rollback()
        await _set_ai_mapping_status(job, "rate_limited", error_message=AI_PROVIDER_RATE_LIMIT_MESSAGE)
        await db.commit()
        suggestions = await _list_owned_ai_mapping_suggestions(db, job_id)
        return {
            "job_id": job_id,
            "run_skipped": True,
            "rate_limited": True,
            "message": AI_PROVIDER_RATE_LIMIT_MESSAGE,
            "status": _serialize_ai_mapping_status(job, suggestions),
            "summary": exc.to_summary(),
            "suggestions": [
                _serialize_ai_mapping_suggestion(suggestion)
                for suggestion in suggestions
            ],
        }
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        await _set_ai_mapping_status(job, "failed", error_message=str(exc))
        await db.commit()
        logger.error("AI mapping suggestion run failed for job %s: %s", job_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"AI mapping suggestion run failed: {exc}")
    finally:
        AI_MAPPING_RUNS_IN_PROGRESS.discard(job_id)

    suggestions = await _list_owned_ai_mapping_suggestions(db, job_id)
    return {
        "job_id": job_id,
        "run_skipped": False,
        "refreshed_suggestions": refreshed_suggestions,
        "status": _serialize_ai_mapping_status(job, suggestions),
        "summary": report.get("summary", {}),
        "suggestions": [
            _serialize_ai_mapping_suggestion(suggestion)
            for suggestion in suggestions
        ],
    }


@router.post("/extracted-data/{item_id}/ai-mapping-suggestions/{suggestion_id}/accept")
async def accept_ai_mapping_suggestion(
    item_id: str,
    suggestion_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Accept one AI suggestion and promote it to the extracted row mapping."""

    item = await _get_owned_item_or_404(db, item_id, current_user)
    suggestion = await _get_suggestion_for_owned_item_or_404(db, item_id, suggestion_id)

    selected_template_field_id = str(suggestion.suggested_template_field_id or "").strip()
    if not selected_template_field_id:
        raise HTTPException(status_code=400, detail="AI suggestion has no template field to accept")

    metadata = suggestion_template_metadata(selected_template_field_id)
    if not metadata:
        raise HTTPException(status_code=400, detail="AI suggestion template field is not valid")

    item.template_field_id = selected_template_field_id
    if metadata.get("statement_type"):
        item.statement_type = metadata["statement_type"]
    item.template_position = metadata.get("position")
    item.is_required_field = bool(metadata.get("required", False))
    item.is_reviewed = True
    suggestion.status = "accepted"

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to accept AI mapping suggestion %s: %s", suggestion_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to accept AI suggestion")

    return {
        "success": True,
        "item_id": item_id,
        "suggestion": _serialize_ai_mapping_suggestion(suggestion),
        "updated_item": {
            "id": item.id,
            "template_field_id": item.template_field_id,
            "statement_type": item.statement_type,
            "is_reviewed": item.is_reviewed,
            "confirmed_tag_id": item.confirmed_tag_id,
        },
    }


@router.post("/extracted-data/{item_id}/ai-mapping-suggestions/{suggestion_id}/ignore")
async def ignore_ai_mapping_suggestion(
    item_id: str,
    suggestion_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Ignore one AI suggestion without changing the extracted row mapping."""

    await _get_owned_item_or_404(db, item_id, current_user)
    suggestion = await _get_suggestion_for_owned_item_or_404(db, item_id, suggestion_id)
    suggestion.status = "ignored"

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.error("Failed to ignore AI mapping suggestion %s: %s", suggestion_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to ignore AI suggestion")

    return {
        "success": True,
        "item_id": item_id,
        "suggestion": _serialize_ai_mapping_suggestion(suggestion),
    }


@router.post("/extracted-data/create", response_model=ExtractedDataItemResponse)
async def create_extracted_data_item(
    item_data: ExtractedDataItemCreate,
    page_id: str = Query(...,
                         description="Page ID to associate the item with"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Create a new extracted data item"""

    try:
        page = await _get_owned_page_or_404(db, page_id, current_user)

        # Create new extracted data item
        new_item = ExtractedDataItem(
            page_id=page_id,
            extracted_label=item_data.extracted_label,
            extracted_value=item_data.extracted_value,
            financial_year=item_data.financial_year,
            statement_type=item_data.statement_type,
            template_field_id=item_data.template_field_id,  # Save template field mapping
            is_reviewed=item_data.is_reviewed if item_data.is_reviewed is not None else False,
            confirmed_tag_id=None  # No tag assigned initially
        )

        db.add(new_item)
        await db.flush()  # Get the new ID
        await db.commit()

        logger.info(f"鉁?Created new extracted data item {new_item.id} for page {page_id}, "
                    f"template_field_id={item_data.template_field_id}, label={item_data.extracted_label}")

        # Return the created item with page info
        return ExtractedDataItemResponse(
            id=new_item.id,
            page_id=new_item.page_id,
            extracted_label=new_item.extracted_label,
            extracted_value=new_item.extracted_value,
            financial_year=new_item.financial_year,
            is_reviewed=new_item.is_reviewed,
            confirmed_tag_id=new_item.confirmed_tag_id,
            page_number=page.page_number,
            confirmed_tag_label=None
        )

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error(f"Error creating extracted data item: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create item")


@router.put("/extracted-data/bulk-update", response_model=BulkUpdateResponse)
async def bulk_update_extracted_data(
    request: BulkUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Bulk update extracted data items - UPDATED for template fields"""

    try:
        updated_count = 0
        deleted_count = 0
        updated_item_ids = []

        logger.info(f"Bulk update request for {len(request.items)} items")

        for item_data in request.items:
            item_id = item_data.get('id')
            if not item_id:
                logger.warning(f"Skipping item without ID: {item_data}")
                continue

            # Check if this is a deletion request
            if item_data.get('_delete', False):
                item = await _get_owned_item_or_404(db, item_id, current_user)
                await db.delete(item)
                deleted_count += 1
                logger.info(f"Deleted item {item_id}")
                continue

            # Get item for update
            item = await _get_owned_item_or_404(db, item_id, current_user)

            # Track what's being updated for debugging
            changes = {}

            # Update fields including template field ID
            update_fields = [
                'extracted_label', 'extracted_value', 'confirmed_tag_id',
                'is_reviewed', 'financial_year', 'template_field_id',
                'value_previous_year', 'financial_year_previous'
            ]

            for field in update_fields:
                if field in item_data:
                    old_value = getattr(item, field)
                    new_value = item_data[field]
                    if old_value != new_value:
                        changes[field] = {'old': old_value, 'new': new_value}
                        setattr(item, field, new_value)

            if changes:
                updated_count += 1
                updated_item_ids.append(item_id)
                logger.info(f"Updated item {item_id}: {changes}")

        # Explicitly flush and commit
        await db.flush()
        await db.commit()

        logger.info(
            f"鉁?Successfully committed {updated_count} updates and {deleted_count} deletions")
        logger.info(f"Updated item IDs: {updated_item_ids}")

        # Verify the updates were persisted by re-querying a sample
        if updated_item_ids:
            sample_id = updated_item_ids[0]
            verify_result = await db.execute(
                select(ExtractedDataItem).where(
                    ExtractedDataItem.id == sample_id)
            )
            verified_item = verify_result.scalar_one_or_none()
            if verified_item:
                logger.info(f"鉁?Verified item {sample_id} persisted: label={verified_item.extracted_label}, "
                            f"value={verified_item.extracted_value}, reviewed={verified_item.is_reviewed}")
            else:
                logger.error(
                    f"鉁?Could not verify item {sample_id} after commit!")

        message = f"Successfully updated {updated_count} items"
        if deleted_count > 0:
            message += f" and deleted {deleted_count} items"

        return BulkUpdateResponse(
            success=True,
            updated_count=updated_count,
            message=message
        )

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error(f"鉂?Error in bulk update: {e}")
        import traceback
        traceback.print_exc()
        await db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Failed to update items: {str(e)}")


@router.delete(
    "/extracted-data/{item_id}",
    dependencies=[Depends(require_admin_route_token)]
)
async def delete_extracted_data_item(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Delete a specific extracted data item"""

    try:
        item = await _get_owned_item_or_404(db, item_id, current_user)

        await db.delete(item)
        await db.commit()

        logger.info(f"Deleted extracted data item {item_id}")

        return {"message": "Item deleted successfully", "item_id": item_id}

    except Exception as e:
        if isinstance(e, HTTPException):
            raise
        logger.error(f"Error deleting item {item_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete item")


@router.post(
    "/jobs/{job_id}/generate-xbrl",
    response_model=XBRLGenerationResponse,
    dependencies=[Depends(require_admin_route_token)]
)
async def generate_xbrl(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
    include_unreviewed: bool = Query(
        False, description="Include unreviewed items")
):
    """Generate XBRL file for a filing job"""

    await _get_owned_job_or_404(db, job_id, current_user)
    response = await generate_xbrl_for_job(job_id, db, include_unreviewed)

    if not response.success:
        raise HTTPException(status_code=400, detail=response.error)

    return response


@router.get("/jobs/{job_id}/validate-xbrl")
async def validate_xbrl_readiness(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Validate if a job is ready for XBRL generation"""

    await _get_owned_job_or_404(db, job_id, current_user)
    from services.xbrl_validator import xbrl_validator

    validation_result = await xbrl_validator.validate_job_for_xbrl(job_id, db)

    return validation_result


@router.get("/jobs/{job_id}/download-xbrl")
async def download_xbrl(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
    force: bool = Query(
        False, description="Force download even if validation fails")
):
    """Download XBRL file as ZIP archive containing XML files

    Note: Validation warnings are allowed. Use force=true to bypass validation entirely.
    """

    import zipfile
    import io
    from datetime import datetime

    # Always allow download (removed validation blocking)
    # Validation is now only for informational purposes via the validate endpoint

    job = await _get_owned_job_or_404(db, job_id, current_user)

    # Generate XBRL - include unreviewed items for download
    response = await generate_xbrl_for_job(job_id, db, include_unreviewed=True)

    if not response.success:
        raise HTTPException(status_code=400, detail=response.error)

    # Create ZIP file in memory
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        # Main XBRL instance document
        safe_registration_number = safe_filename_component(
            job.registration_number, "UNKNOWN")
        instance_filename = f"SSM_FS-MPERS_{safe_registration_number}_{job.financial_year_end.strftime('%Y%m%d')}.xml"
        zip_file.writestr(instance_filename, response.content.encode('utf-8'))

        # Add a readme file
        readme_content = f"""XBRL Filing Package
=====================

Company: {job.company_name}
Registration Number: {job.registration_number or 'N/A'}
Financial Year End: {job.financial_year_end.strftime('%Y-%m-%d')}
Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

Contents:
- {instance_filename}: XBRL instance document

This package contains XBRL financial statements compliant with:
- Malaysian Business Reporting System (MBRS)
- SSMxT 2022 taxonomy
- MPERS (Malaysian Private Entity Reporting Standards)

For more information, visit: https://mbrs.ssm.com.my/
"""
        zip_file.writestr("README.txt", readme_content)

    # Prepare ZIP for download
    zip_buffer.seek(0)

    safe_company_name = safe_filename_component(job.company_name, "company")
    zip_filename = f"{safe_company_name}_MBRS_{job.financial_year_end.strftime('%Y%m%d')}.zip"

    return StreamingResponse(
        iter([zip_buffer.getvalue()]),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
    )


@router.delete("/jobs/{job_id}")
async def delete_filing_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Delete a filing job and owned local artifacts.

    Requires auth ownership; legacy unassigned jobs are not visible here.
    """

    job = await _get_owned_job_or_404(
        db,
        job_id,
        current_user,
        (
            selectinload(FilingJob.pages).selectinload(
                FinancialStatementPage.extracted_items)
        ),
    )

    cleanup_plan = _build_filing_job_cleanup_plan(job)

    try:
        # FilingJob.pages and FinancialStatementPage.extracted_items are
        # configured with delete-orphan cascades in database.py.
        await db.delete(job)
        await db.commit()
    except Exception as e:
        logger.error(f"Error deleting job {job_id}: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="Failed to delete job")

    artifact_cleanup = _delete_upload_artifacts(cleanup_plan["file_candidates"])

    # Clear cache after durable DB deletion. File cleanup failures are reported
    # but do not resurrect DB records.
    status_tracker.clear_status(job_id)

    logger.info(
        "Deleted filing job %s with %s pages, %s extracted items, %s files",
        job_id,
        cleanup_plan["deleted_pages_count"],
        cleanup_plan["deleted_extracted_items_count"],
        artifact_cleanup["deleted_files_count"],
    )

    return {
        "deleted_job": True,
        "job_id": job_id,
        "deleted_pages_count": cleanup_plan["deleted_pages_count"],
        "deleted_extracted_items_count": cleanup_plan["deleted_extracted_items_count"],
        "deleted_files_count": artifact_cleanup["deleted_files_count"],
        "deleted_files": artifact_cleanup["deleted_files"],
        "skipped_files": artifact_cleanup["skipped_files"],
        "warnings": artifact_cleanup["warnings"],
    }


@router.get("/dashboard/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_workspace_user),
):
    """Get dashboard statistics"""

    # Get job counts by status
    job_stats = await db.execute(
        select(
            FilingJob.status,
            func.count(FilingJob.id).label('count')
        )
        .where(FilingJob.user_id == current_user.id)
        .group_by(FilingJob.status)
    )

    status_counts = {row.status: row.count for row in job_stats}

    # Get extracted data stats
    extracted_stats = await db.execute(
        select(
            func.count(ExtractedDataItem.id).label('total'),
            func.count(ExtractedDataItem.id).filter(
                ExtractedDataItem.is_reviewed == True
            ).label('reviewed')
        )
        .join(FinancialStatementPage)
        .join(FilingJob)
        .where(FilingJob.user_id == current_user.id)
    )

    extracted_row = extracted_stats.first()

    # Get taxonomy count
    from database import MBRSTaxonomyTag
    taxonomy_count = await db.execute(select(func.count(MBRSTaxonomyTag.id)))

    return DashboardStats(
        total_jobs=sum(status_counts.values()),
        processing_jobs=status_counts.get('PROCESSING', 0),
        completed_jobs=status_counts.get('COMPLETED', 0),
        error_jobs=status_counts.get('ERROR', 0),
        total_extracted_items=extracted_row.total or 0,
        reviewed_items=extracted_row.reviewed or 0,
        taxonomy_tags=taxonomy_count.scalar() or 0
    )
