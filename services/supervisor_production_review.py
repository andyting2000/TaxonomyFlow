"""Production Supervisor review service.

This module creates advisory MappingSupervisorReview records only. It does not
mutate extracted row mappings, accept/reject AI suggestions, set
confirmed_tag_id, generate XBRL, or run Arelle.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
import weakref
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import (
    ExtractedDataItem,
    FilingJob,
    FinancialStatementPage,
    LLMMappingSuggestion,
    MappingSupervisorReview,
)
from schemas import mapping_supervisor_review_read_from_model
from services.suggestion_actionability import is_human_terminal
from services.llm_taxonomy_mapping import suggestion_template_metadata
from services.supervisor_mapping_review import (
    assert_supervisor_payload_is_leakage_safe,
    build_supervisor_prompt,
    build_supervisor_review_payload,
    mock_supervisor_review,
    validate_supervisor_response,
)
from services.supervisor_llm_client import (
    SupervisorLLMClient,
    SupervisorLLMConfig,
    SupervisorLLMConfigurationError,
    SupervisorLLMInvalidResponseError,
    SupervisorLLMRateLimitError,
    SupervisorProviderHTTPError,
)


_LIVE_CALL_SEMAPHORES: weakref.WeakKeyDictionary[
    asyncio.AbstractEventLoop,
    tuple[int, asyncio.Semaphore],
] = weakref.WeakKeyDictionary()


@asynccontextmanager
async def supervisor_live_call_slot(
    *,
    max_concurrent: int | None = None,
    wait_timeout_seconds: float | None = None,
):
    """Bound live provider calls per API process without scheduling retries."""

    limit = max(
        1,
        int(
            max_concurrent
            or settings.supervisor_orchestration_max_concurrent_live_calls
        ),
    )
    timeout = max(
        1.0,
        float(
            wait_timeout_seconds
            or settings.supervisor_orchestration_per_row_timeout_seconds
        ),
    )
    loop = asyncio.get_running_loop()
    configured = _LIVE_CALL_SEMAPHORES.get(loop)
    if configured is None or configured[0] != limit:
        configured = (limit, asyncio.Semaphore(limit))
        _LIVE_CALL_SEMAPHORES[loop] = configured
    semaphore = configured[1]
    await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
    try:
        yield
    finally:
        semaphore.release()


MOCK_SUPERVISOR_SOURCE = "mock"
MOCK_SUPERVISOR_MODEL_PROVIDER = "mock"
MOCK_SUPERVISOR_MODEL_ID = "mock-supervisor-17d-c-c"
MOCK_SUPERVISOR_PROMPT_VERSION = "supervisor-production-mock-v1"
LIVE_SUPERVISOR_SOURCE = "live"
LIVE_SUPERVISOR_PROMPT_VERSION = "supervisor-production-live-v1"
SUPERVISOR_SCHEMA_VERSION = "mapping-supervisor-review-v1"

FORBIDDEN_PRODUCTION_PAYLOAD_KEYS = {
    "auditor_xml",
    "parsed_xml_fact",
    "parsed_xml_facts",
    "xml_facts",
    "gold_answer",
    "expected_qname",
    "target_correct_qname",
    "target_template_field_id",
    "evaluation_label",
    "benchmark_label",
    "strict_accuracy",
    "accuracy_when_predicted",
    "is_correct",
    "correct_concept_qname",
    "correct_template_field_id",
}


def _safe_json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return decoded


def _json_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _forbidden_payload_paths(value: Any, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_text = str(key)
            next_path = f"{path}.{key_text}"
            if key_text.lower() in FORBIDDEN_PRODUCTION_PAYLOAD_KEYS:
                paths.append(next_path)
            paths.extend(_forbidden_payload_paths(nested, next_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_payload_paths(nested, f"{path}[{index}]"))
    return paths


def assert_production_supervisor_payload_safe(payload: Mapping[str, Any]) -> None:
    """Reject benchmark/evaluation leakage keys in production Supervisor payloads."""

    assert_supervisor_payload_is_leakage_safe(payload)
    forbidden_paths = _forbidden_payload_paths(payload)
    if forbidden_paths:
        raise ValueError(
            "Production Supervisor payload contains forbidden keys: "
            + ", ".join(sorted(forbidden_paths))
        )


def _template_metadata(template_field_id: str | None) -> dict[str, Any] | None:
    if not template_field_id:
        return None
    try:
        return suggestion_template_metadata(template_field_id)
    except Exception:
        return None


def _candidate_from_metadata(template_field_id: str | None) -> dict[str, Any] | None:
    metadata = _template_metadata(template_field_id)
    if not template_field_id and not metadata:
        return None
    return {
        "template_field_id": template_field_id,
        "concept_qname": template_field_id,
        "label": metadata.get("label") if metadata else None,
        "statement_type": metadata.get("statement_type") if metadata else None,
        "template_code": metadata.get("template_code") if metadata else None,
        "position": metadata.get("position") if metadata else None,
        "required": metadata.get("required") if metadata else None,
    }


def _candidate_concepts_from_suggestion(suggestion: LLMMappingSuggestion) -> list[dict[str, Any]]:
    raw_candidates = _safe_json_loads(suggestion.ranked_candidates_json, [])
    candidates: list[dict[str, Any]] = []

    for raw_candidate in raw_candidates if isinstance(raw_candidates, list) else []:
        if not isinstance(raw_candidate, Mapping):
            continue
        candidate = dict(raw_candidate)
        template_field_id = (
            candidate.get("template_field_id")
            or candidate.get("concept_qname")
            or candidate.get("qname")
        )
        metadata = _template_metadata(str(template_field_id)) if template_field_id else None
        if template_field_id:
            candidate.setdefault("template_field_id", str(template_field_id))
            candidate.setdefault("concept_qname", str(template_field_id))
        if metadata:
            candidate.setdefault("label", metadata.get("label"))
            candidate.setdefault("statement_type", metadata.get("statement_type"))
            candidate.setdefault("template_code", metadata.get("template_code"))
            candidate.setdefault("position", metadata.get("position"))
            candidate.setdefault("required", metadata.get("required"))
        candidates.append(candidate)

    selected = suggestion.suggested_template_field_id
    if selected and not any(
        selected in {
            str(candidate.get("template_field_id") or ""),
            str(candidate.get("concept_qname") or ""),
            str(candidate.get("qname") or ""),
        }
        for candidate in candidates
    ):
        selected_candidate = _candidate_from_metadata(selected)
        if selected_candidate:
            selected_candidate["deterministic_score"] = suggestion.confidence
            selected_candidate["deterministic_method"] = "mapper_selected_template_field"
            candidates.insert(0, selected_candidate)

    return candidates[:10]


def build_production_supervisor_payload(
    suggestion: LLMMappingSuggestion,
    *,
    source: str = MOCK_SUPERVISOR_SOURCE,
) -> dict[str, Any]:
    """Build a production-safe Supervisor review payload from a persisted suggestion."""

    normalized_source = str(source or MOCK_SUPERVISOR_SOURCE).strip().lower()
    live_review = normalized_source == LIVE_SUPERVISOR_SOURCE
    item = suggestion.extracted_data_item
    page = item.page if item is not None else None
    candidates = _candidate_concepts_from_suggestion(suggestion)
    row = {
        "extracted_row_id": suggestion.extracted_data_item_id,
        "label": item.extracted_label if item is not None else None,
        "value": item.extracted_value if item is not None else None,
        "previous_value": getattr(item, "value_previous_year", None) if item is not None else None,
        "statement_type": item.statement_type if item is not None else None,
        "row_type": "numeric_fact" if item is not None and item.extracted_value else None,
        "page_number": page.page_number if page is not None else None,
    }
    mapper = {
        "status": suggestion.status,
        "selected_template_field_id": suggestion.suggested_template_field_id,
        "selected_concept_qname": suggestion.suggested_template_field_id,
        "confidence": suggestion.confidence,
        "reason": suggestion.reason,
        "candidate_concepts": candidates,
        "ranked_candidates": [
            {
                "template_field_id": candidate.get("template_field_id"),
                "concept_qname": candidate.get("concept_qname"),
                "confidence": candidate.get("confidence") or candidate.get("deterministic_score"),
                "reason": candidate.get("reason") or candidate.get("deterministic_method"),
            }
            for candidate in candidates[:5]
        ],
    }
    payload = build_supervisor_review_payload(
        row,
        mapper_suggestion=mapper,
        candidate_concepts=candidates,
    )
    payload["run_metadata"].update(
        {
            "feature": "17D-C-E-A" if live_review else "17D-C-C",
            "production_context": True,
            "local_only": not live_review,
            "external_llm_called": live_review,
            "mock_review_only": not live_review,
            "review_source": LIVE_SUPERVISOR_SOURCE if live_review else MOCK_SUPERVISOR_SOURCE,
        }
    )
    payload["safety"].update(
        {
            "production_safe_payload": True,
            "auditor_source_included": False,
            "reference_fact_details_included": False,
            "target_answer_included": False,
            "scoring_labels_included": False,
            "external_llm_required": live_review,
        }
    )
    assert_production_supervisor_payload_safe(payload)
    return payload


async def load_owned_supervisor_job(
    db: AsyncSession,
    *,
    job_id: int,
    user_id: int,
) -> FilingJob | None:
    result = await db.execute(
        select(FilingJob).where(
            FilingJob.id == job_id,
            FilingJob.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def list_supervisor_reviews_for_job(
    db: AsyncSession,
    *,
    job_id: int,
) -> list[MappingSupervisorReview]:
    result = await db.execute(
        select(MappingSupervisorReview)
        .where(MappingSupervisorReview.job_id == job_id)
        .order_by(
            MappingSupervisorReview.is_latest.desc(),
            MappingSupervisorReview.created_at.desc(),
            MappingSupervisorReview.id,
        )
    )
    return result.scalars().unique().all()


async def get_supervisor_review_for_job(
    db: AsyncSession,
    *,
    job_id: int,
    review_id: str,
) -> MappingSupervisorReview | None:
    result = await db.execute(
        select(MappingSupervisorReview).where(
            MappingSupervisorReview.id == review_id,
            MappingSupervisorReview.job_id == job_id,
        )
    )
    return result.scalar_one_or_none()


async def list_ai_mapping_suggestions_for_supervisor(
    db: AsyncSession,
    *,
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
        .order_by(LLMMappingSuggestion.created_at.desc(), LLMMappingSuggestion.id)
    )
    return result.scalars().unique().all()


async def load_ai_mapping_suggestion_for_supervisor(
    db: AsyncSession,
    *,
    job_id: int,
    suggestion_id: str,
    lock_for_update: bool = False,
) -> LLMMappingSuggestion | None:
    statement = (
        select(LLMMappingSuggestion)
        .join(
            ExtractedDataItem,
            LLMMappingSuggestion.extracted_data_item_id == ExtractedDataItem.id,
        )
        .join(FinancialStatementPage, ExtractedDataItem.page_id == FinancialStatementPage.id)
        .where(
            LLMMappingSuggestion.id == suggestion_id,
            LLMMappingSuggestion.job_id == job_id,
            FinancialStatementPage.job_id == job_id,
        )
        .options(
            selectinload(LLMMappingSuggestion.extracted_data_item).selectinload(
                ExtractedDataItem.page
            )
        )
    )
    if lock_for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def _existing_reviews_for_suggestion(
    db: AsyncSession,
    *,
    job_id: int,
    suggestion_id: str,
    source: str = MOCK_SUPERVISOR_SOURCE,
) -> list[MappingSupervisorReview]:
    result = await db.execute(
        select(MappingSupervisorReview)
        .where(
            MappingSupervisorReview.job_id == job_id,
            MappingSupervisorReview.llm_mapping_suggestion_id == suggestion_id,
            MappingSupervisorReview.source == source,
        )
        .order_by(
            MappingSupervisorReview.review_attempt.desc(),
            MappingSupervisorReview.created_at.desc(),
            MappingSupervisorReview.id,
        )
    )
    return result.scalars().unique().all()


class SupervisorLiveBatchSizeExceeded(ValueError):
    """Raised when an explicit live batch would exceed the configured limit."""

    def __init__(self, *, count: int, max_batch_size: int) -> None:
        super().__init__(
            f"Live Supervisor batch size {count} exceeds maximum {max_batch_size}."
        )
        self.count = count
        self.max_batch_size = max_batch_size


class SupervisorReviewNotExecutable(ValueError):
    """Raised when persisted human state forbids another Supervisor review."""


def _normalize_source(source: str | Any) -> str:
    value = getattr(source, "value", source)
    normalized = str(value or MOCK_SUPERVISOR_SOURCE).strip().lower()
    if normalized not in {MOCK_SUPERVISOR_SOURCE, LIVE_SUPERVISOR_SOURCE}:
        raise ValueError("Supervisor review source must be mock or live")
    return normalized


def _redact_live_error_message(message: Any, *, config: SupervisorLLMConfig | None) -> str:
    sanitized = str(message or "")
    token = str(getattr(config, "api_token", "") or "").strip() if config is not None else ""
    if token:
        sanitized = sanitized.replace(token, "[REDACTED_SUPERVISOR_TOKEN]")
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"hf_[A-Za-z0-9]{20,}", "hf_[REDACTED]", sanitized)
    return sanitized[:1500]


def _live_error_summary(
    exc: BaseException,
    *,
    config: SupervisorLLMConfig | None,
) -> tuple[str, str]:
    if isinstance(exc, SupervisorLLMConfigurationError):
        return "configuration_error", _redact_live_error_message(str(exc), config=config)
    if isinstance(exc, SupervisorLLMRateLimitError):
        return "provider_rate_limited", _redact_live_error_message(str(exc), config=config)
    if isinstance(exc, SupervisorProviderHTTPError):
        detail = f"{exc.status_code} {exc.reason}: {exc.sanitized_error_body}"
        return "provider_http_error", _redact_live_error_message(detail, config=config)
    if isinstance(exc, SupervisorLLMInvalidResponseError):
        detail = f"{exc.category}: {exc.validator_error_message}"
        if exc.repair_attempted and not exc.repair_succeeded:
            detail += " Repair was attempted but did not produce valid Supervisor JSON."
        return "invalid_supervisor_response", _redact_live_error_message(detail, config=config)
    return exc.__class__.__name__, _redact_live_error_message(str(exc), config=config)


def _review_base_fields(
    *,
    job: FilingJob,
    suggestion: LLMMappingSuggestion,
    user_id: int,
    attempt: int,
    source: str,
    payload: Mapping[str, Any],
    now: datetime,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "job_id": job.id,
        "extracted_data_item_id": suggestion.extracted_data_item_id,
        "llm_mapping_suggestion_id": suggestion.id,
        "mapper_selected_template_field_id": suggestion.suggested_template_field_id,
        "mapper_selected_qname": suggestion.suggested_template_field_id,
        "mapper_confidence": suggestion.confidence,
        "mapper_status": suggestion.status,
        "supervisor_schema_version": SUPERVISOR_SCHEMA_VERSION,
        "supervisor_payload_hash": _json_hash(payload),
        "started_at": now,
        "completed_at": now,
        "review_attempt": attempt,
        "source": source,
        "is_latest": True,
        "created_at": now,
        "updated_at": now,
    }


def _completed_review_fields(
    response: Mapping[str, Any],
    *,
    source: str,
    config: SupervisorLLMConfig | None = None,
) -> dict[str, Any]:
    if source == MOCK_SUPERVISOR_SOURCE:
        provider = MOCK_SUPERVISOR_MODEL_PROVIDER
        model_id = MOCK_SUPERVISOR_MODEL_ID
        prompt_version = MOCK_SUPERVISOR_PROMPT_VERSION
    else:
        provider = str(getattr(config, "provider", "") or "").strip() or "unknown"
        model_id = str(getattr(config, "model_id", "") or "").strip()
        prompt_version = LIVE_SUPERVISOR_PROMPT_VERSION

    return {
        "review_status": "completed",
        "supervisor_decision": response["review_decision"],
        "supervisor_risk_level": response["risk_level"],
        "supervisor_recommended_action": response["recommended_action"],
        "supervisor_safe_to_accept": bool(response["safe_to_accept"]),
        "calibrated_safe_to_accept": bool(response["safe_to_accept"]),
        "supervisor_confidence_adjustment": response["confidence_adjustment"],
        "supervisor_issues_json": json.dumps(response.get("issues") or [], ensure_ascii=True),
        "supervisor_reason": response["reason"],
        "supervisor_model_provider": provider,
        "supervisor_model_id": model_id,
        "supervisor_prompt_version": prompt_version,
        "supervisor_response_hash": _json_hash(dict(response)),
    }


def _failed_review_fields(
    exc: BaseException,
    *,
    config: SupervisorLLMConfig | None,
) -> dict[str, Any]:
    error_type, error_message = _live_error_summary(exc, config=config)
    provider = str(getattr(config, "provider", "") or "").strip() or "unknown"
    model_id = str(getattr(config, "model_id", "") or "").strip()
    error_summary = {"error_type": error_type, "error_message_sanitized": error_message}
    return {
        "review_status": "failed",
        "supervisor_decision": None,
        "supervisor_risk_level": None,
        "supervisor_recommended_action": None,
        "supervisor_safe_to_accept": False,
        "calibrated_safe_to_accept": False,
        "supervisor_confidence_adjustment": None,
        "supervisor_issues_json": json.dumps([], ensure_ascii=True),
        "supervisor_reason": None,
        "supervisor_model_provider": provider,
        "supervisor_model_id": model_id,
        "supervisor_prompt_version": LIVE_SUPERVISOR_PROMPT_VERSION,
        "supervisor_response_hash": _json_hash(error_summary),
        "error_type": error_type,
        "error_message_sanitized": error_message,
    }


async def _create_supervisor_review_for_suggestion(
    db: AsyncSession,
    *,
    job: FilingJob,
    suggestion: LLMMappingSuggestion,
    user_id: int,
    force_refresh: bool,
    source: str = MOCK_SUPERVISOR_SOURCE,
    live_client: SupervisorLLMClient | None = None,
    live_config: SupervisorLLMConfig | None = None,
) -> tuple[MappingSupervisorReview, bool]:
    normalized_source = _normalize_source(source)
    locked_suggestion = await load_ai_mapping_suggestion_for_supervisor(
        db,
        job_id=job.id,
        suggestion_id=suggestion.id,
        lock_for_update=True,
    )
    if locked_suggestion is None:
        raise SupervisorReviewNotExecutable("AI mapping suggestion is no longer available.")
    suggestion = locked_suggestion
    existing_reviews = await _existing_reviews_for_suggestion(
        db,
        job_id=job.id,
        suggestion_id=suggestion.id,
        source=normalized_source,
    )
    latest_completed = next(
        (
            review
            for review in existing_reviews
            if review.is_latest and review.review_status == "completed"
        ),
        None,
    )
    if latest_completed is not None and not force_refresh:
        return latest_completed, False

    for review in existing_reviews:
        review.is_latest = False

    attempt = max([review.review_attempt for review in existing_reviews] or [0]) + 1
    payload = build_production_supervisor_payload(suggestion, source=normalized_source)
    now = datetime.utcnow()
    base_fields = _review_base_fields(
        job=job,
        suggestion=suggestion,
        user_id=user_id,
        attempt=attempt,
        source=normalized_source,
        payload=payload,
        now=now,
    )

    if normalized_source == MOCK_SUPERVISOR_SOURCE:
        mock_response = mock_supervisor_review(payload)
        review_fields = _completed_review_fields(mock_response, source=MOCK_SUPERVISOR_SOURCE)
    else:
        config = live_config or SupervisorLLMConfig.from_settings()
        client = live_client or SupervisorLLMClient()
        try:
            async with supervisor_live_call_slot():
                live_result = await client.complete_review(
                    build_supervisor_prompt(payload),
                    payload=payload,
                    config=config,
                )
            live_response = validate_supervisor_response(
                live_result.get("review") or {},
                payload=payload,
            )
            review_fields = _completed_review_fields(
                live_response,
                source=LIVE_SUPERVISOR_SOURCE,
                config=config,
            )
        except Exception as exc:
            review_fields = _failed_review_fields(exc, config=config)

    review = MappingSupervisorReview(**base_fields, **review_fields)
    db.add(review)
    maybe_flush = db.flush()
    if hasattr(maybe_flush, "__await__"):
        await maybe_flush
    return review, True


async def run_supervisor_review_for_suggestion(
    db: AsyncSession,
    *,
    job_id: int,
    suggestion_id: str,
    user_id: int,
    force_refresh: bool = False,
    source: str = MOCK_SUPERVISOR_SOURCE,
    live_client: SupervisorLLMClient | None = None,
    live_config: SupervisorLLMConfig | None = None,
) -> tuple[MappingSupervisorReview | None, bool]:
    normalized_source = _normalize_source(source)
    job = await load_owned_supervisor_job(db, job_id=job_id, user_id=user_id)
    if job is None:
        return None, False
    suggestion = await load_ai_mapping_suggestion_for_supervisor(
        db,
        job_id=job.id,
        suggestion_id=suggestion_id,
    )
    if suggestion is None:
        return None, False
    if is_human_terminal(suggestion):
        raise SupervisorReviewNotExecutable(
            "Human-terminal suggestions with status accepted or ignored "
            "cannot be reviewed again."
        )

    review, created = await _create_supervisor_review_for_suggestion(
        db,
        job=job,
        suggestion=suggestion,
        user_id=user_id,
        force_refresh=force_refresh,
        source=normalized_source,
        live_client=live_client,
        live_config=live_config,
    )
    if created:
        await db.commit()
    return review, created


async def run_mock_supervisor_review_for_suggestion(
    db: AsyncSession,
    *,
    job_id: int,
    suggestion_id: str,
    user_id: int,
    force_refresh: bool = False,
) -> tuple[MappingSupervisorReview | None, bool]:
    return await run_supervisor_review_for_suggestion(
        db,
        job_id=job_id,
        suggestion_id=suggestion_id,
        user_id=user_id,
        force_refresh=force_refresh,
        source=MOCK_SUPERVISOR_SOURCE,
    )


async def run_supervisor_reviews_for_job(
    db: AsyncSession,
    *,
    job_id: int,
    user_id: int,
    force_refresh: bool = False,
    source: str = MOCK_SUPERVISOR_SOURCE,
    live_client: SupervisorLLMClient | None = None,
    live_config: SupervisorLLMConfig | None = None,
    max_batch_size: int | None = None,
    suggestion_ids: Sequence[str] | None = None,
) -> tuple[list[MappingSupervisorReview], int, int] | None:
    normalized_source = _normalize_source(source)
    job = await load_owned_supervisor_job(db, job_id=job_id, user_id=user_id)
    if job is None:
        return None

    suggestions = await list_ai_mapping_suggestions_for_supervisor(db, job_id=job.id)
    if suggestion_ids is not None:
        requested_ids = {str(suggestion_id) for suggestion_id in suggestion_ids}
        suggestions = [
            suggestion
            for suggestion in suggestions
            if str(suggestion.id) in requested_ids
        ]
        if any(is_human_terminal(suggestion) for suggestion in suggestions):
            raise SupervisorReviewNotExecutable(
                "Batch contains a human-terminal suggestion with status "
                "accepted or ignored."
            )
    else:
        suggestions = [
            suggestion
            for suggestion in suggestions
            if not is_human_terminal(suggestion)
        ]
    if (
        normalized_source == LIVE_SUPERVISOR_SOURCE
        and max_batch_size is not None
        and len(suggestions) > max_batch_size
    ):
        raise SupervisorLiveBatchSizeExceeded(
            count=len(suggestions),
            max_batch_size=max_batch_size,
        )

    reviews: list[MappingSupervisorReview] = []
    created_count = 0
    reused_count = 0
    for suggestion in suggestions:
        review, created = await _create_supervisor_review_for_suggestion(
            db,
            job=job,
            suggestion=suggestion,
            user_id=user_id,
            force_refresh=force_refresh,
            source=normalized_source,
            live_client=live_client,
            live_config=live_config,
        )
        reviews.append(review)
        if created:
            created_count += 1
        else:
            reused_count += 1

    if created_count:
        await db.commit()
    return reviews, created_count, reused_count


async def run_mock_supervisor_reviews_for_job(
    db: AsyncSession,
    *,
    job_id: int,
    user_id: int,
    force_refresh: bool = False,
) -> tuple[list[MappingSupervisorReview], int, int] | None:
    return await run_supervisor_reviews_for_job(
        db,
        job_id=job_id,
        user_id=user_id,
        force_refresh=force_refresh,
        source=MOCK_SUPERVISOR_SOURCE,
    )


def serialize_supervisor_review(review: MappingSupervisorReview) -> dict[str, Any]:
    return mapping_supervisor_review_read_from_model(review).model_dump(mode="json")


def serialize_supervisor_reviews(reviews: Sequence[MappingSupervisorReview]) -> list[dict[str, Any]]:
    return [serialize_supervisor_review(review) for review in reviews]
