"""Dry-run ranked candidate advisory service for Feature #18F-D.

The service serializes local ranked candidate evidence for an owned filing job.
It remains feature-flagged, dry-run only, and does not persist candidates,
mutate final mappings, or call external providers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings as app_settings
from database import ExtractedDataItem, FilingJob, FinancialStatementPage
from schemas import RankedCandidateAdvisoryRequest, RankedCandidateAdvisoryResponse
from services.hybrid_candidate_calibration import (
    apply_ranking_profile_to_rows,
    available_ranking_profiles,
)
from services.hybrid_candidate_ranking_mapper import (
    DEFAULT_TAXONOMY_METADATA,
    load_taxonomy_concept_metadata,
    rank_candidate_rows,
)
from services.local_candidate_sources import load_concept_playbook_cards
from services.pdf_xbrl_deterministic_alignment import (
    PdfRowValue,
    canonical_label,
    pdf_row_values,
)


DEFAULT_PROFILE = "balanced"
CALIBRATION_VERSION = "18F-B-balanced"
DEFAULT_BASELINE_REPORT = Path("reports/hybrid_candidate_ranking_non_lexical_18e_f_a2.json")

FEATURE_FLAG_NAMES = {
    "enabled": "RANKED_CANDIDATES_ADVISORY_ENABLED",
    "default_mode": "RANKED_CANDIDATES_ADVISORY_DEFAULT_MODE",
    "allow_persistence": "RANKED_CANDIDATES_ADVISORY_ALLOW_PERSISTENCE",
    "default_profile": "RANKED_CANDIDATES_ADVISORY_DEFAULT_PROFILE",
    "max_rows": "RANKED_CANDIDATES_ADVISORY_MAX_ROWS",
    "max_candidates_per_row": "RANKED_CANDIDATES_ADVISORY_MAX_CANDIDATES_PER_ROW",
    "admin_only": "RANKED_CANDIDATES_ADVISORY_ADMIN_ONLY",
}

SAFETY_GUARANTEES = {
    "advisory_only": True,
    "dry_run_only": True,
    "persistence_enabled": False,
    "auto_apply_enabled": False,
    "auto_accept_enabled": False,
    "auto_reject_enabled": False,
    "safe_for_auto_apply_always_false": True,
    "requires_human_review_always_true": True,
    "confirmed_tag_id_mutation_allowed": False,
    "final_mapping_mutation_allowed": False,
    "ai_mapping_suggestion_mutation_allowed": False,
    "external_llm_called": False,
    "supervisor_called": False,
    "qwen_called": False,
    "azure_di_live_call_made": False,
    "xbrl_generation_allowed": False,
    "arelle_run_allowed": False,
}


class RankedCandidateAdvisoryError(RuntimeError):
    """Safe error for unavailable or unsafe advisory candidate inputs."""


@dataclass(frozen=True)
class RankedCandidateAdvisoryConfig:
    enabled: bool = False
    default_mode: str = "dry_run"
    allow_persistence: bool = False
    default_profile: str = DEFAULT_PROFILE
    max_rows: int = 1000
    max_candidates_per_row: int = 5
    admin_only: bool = True

    @classmethod
    def from_settings(cls, settings: Any = app_settings) -> "RankedCandidateAdvisoryConfig":
        return cls(
            enabled=bool(getattr(settings, "ranked_candidates_advisory_enabled", False)),
            default_mode=str(getattr(settings, "ranked_candidates_advisory_default_mode", "dry_run") or "dry_run"),
            allow_persistence=bool(getattr(settings, "ranked_candidates_advisory_allow_persistence", False)),
            default_profile=str(getattr(settings, "ranked_candidates_advisory_default_profile", DEFAULT_PROFILE) or DEFAULT_PROFILE),
            max_rows=max(1, int(getattr(settings, "ranked_candidates_advisory_max_rows", 1000) or 1000)),
            max_candidates_per_row=max(1, int(getattr(settings, "ranked_candidates_advisory_max_candidates_per_row", 5) or 5)),
            admin_only=bool(getattr(settings, "ranked_candidates_advisory_admin_only", True)),
        )

    def effective_mode(self) -> str:
        return "dry_run"

    def effective_allow_persistence(self) -> bool:
        return False

    def effective_profile(self, profile: str | None = None) -> str:
        candidate = str(profile or self.default_profile or DEFAULT_PROFILE).strip().lower()
        if candidate not in set(available_ranking_profiles()):
            raise RankedCandidateAdvisoryError(f"Unknown ranked candidate profile: {candidate}")
        return candidate


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def advisory_capabilities(
    job_id: int,
    *,
    config: RankedCandidateAdvisoryConfig | None = None,
) -> dict[str, Any]:
    cfg = config or RankedCandidateAdvisoryConfig.from_settings()
    return {
        "job_id": int(job_id),
        "enabled": bool(cfg.enabled),
        "default_mode": cfg.effective_mode(),
        "allow_persistence": cfg.effective_allow_persistence(),
        "default_profile": cfg.default_profile,
        "supported_profiles": available_ranking_profiles(),
        "supported_modes": ["dry_run"],
        "supported_actions": [
            "review_candidate",
            "keep_for_human_review",
            "no_candidate",
            "blocked",
        ],
        "max_rows": cfg.max_rows,
        "max_candidates_per_row": cfg.max_candidates_per_row,
        "admin_only": cfg.admin_only,
        "feature_flags": feature_flags(cfg),
        "endpoints": [
            f"/api/v1/filings/jobs/{job_id}/ranked-candidates/capabilities",
            f"/api/v1/filings/jobs/{job_id}/ranked-candidates/run",
        ],
        "safety": dict(SAFETY_GUARANTEES),
    }


def feature_flags(config: RankedCandidateAdvisoryConfig) -> dict[str, Any]:
    return {
        FEATURE_FLAG_NAMES["enabled"]: bool(config.enabled),
        FEATURE_FLAG_NAMES["default_mode"]: config.effective_mode(),
        FEATURE_FLAG_NAMES["allow_persistence"]: config.effective_allow_persistence(),
        FEATURE_FLAG_NAMES["default_profile"]: config.default_profile,
        FEATURE_FLAG_NAMES["max_rows"]: config.max_rows,
        FEATURE_FLAG_NAMES["max_candidates_per_row"]: config.max_candidates_per_row,
        FEATURE_FLAG_NAMES["admin_only"]: bool(config.admin_only),
    }


def load_ranked_rows_from_report(
    path: str | Path = DEFAULT_BASELINE_REPORT,
) -> list[dict[str, Any]]:
    report_path = Path(path)
    if not report_path.exists():
        raise RankedCandidateAdvisoryError("Ranked candidate baseline report is unavailable.")
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RankedCandidateAdvisoryError("Ranked candidate baseline report could not be loaded.") from exc
    rows = payload.get("ranked_rows") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list):
        raise RankedCandidateAdvisoryError("Ranked candidate baseline report has an invalid shape.")
    return [dict(row) for row in rows if isinstance(row, Mapping)]


def _as_string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def config_for_request(
    config: RankedCandidateAdvisoryConfig,
    request: RankedCandidateAdvisoryRequest | None = None,
) -> tuple[RankedCandidateAdvisoryConfig, str]:
    """Return a request-scoped config after enforcing feature caps."""

    if request is None:
        profile = config.effective_profile()
        return config, profile

    mode = str(getattr(request.mode, "value", request.mode) or "").strip().lower()
    if mode != "dry_run":
        raise RankedCandidateAdvisoryError("Ranked candidate advisory only supports dry_run mode.")

    requested_max_rows = int(request.max_rows)
    requested_max_candidates = int(request.max_candidates_per_row)
    if requested_max_rows > config.max_rows:
        raise RankedCandidateAdvisoryError(
            f"Requested max_rows exceeds configured limit: {config.max_rows}"
        )
    if requested_max_candidates > config.max_candidates_per_row:
        raise RankedCandidateAdvisoryError(
            "Requested max_candidates_per_row exceeds configured limit: "
            f"{config.max_candidates_per_row}"
        )

    profile = config.effective_profile(request.profile)
    return (
        replace(
            config,
            default_mode="dry_run",
            allow_persistence=False,
            default_profile=profile,
            max_rows=requested_max_rows,
            max_candidates_per_row=requested_max_candidates,
        ),
        profile,
    )


def _namespace(qname: Any) -> str | None:
    text = str(qname or "")
    return text.split(":", 1)[0] if ":" in text else None


def _note_boundary_type(row: Mapping[str, Any]) -> str | None:
    boundary = _as_dict(row.get("note_boundary"))
    if boundary.get("is_note_reconciliation_row"):
        return "note_reconciliation"
    if boundary.get("is_note_movement_row"):
        return "note_movement"
    if boundary.get("is_note_detail_row"):
        return "note_detail"
    if boundary.get("is_note_summary_row"):
        return "note_summary"
    return None


def _candidate_action(candidate: Mapping[str, Any]) -> str:
    blocking = _as_string_list(candidate.get("blocking_reasons"))
    profile_filters = _as_string_list(candidate.get("profile_filter_reasons"))
    if blocking or profile_filters:
        return "keep_for_human_review"
    return "review_candidate"


def _serialize_candidate(
    candidate: Mapping[str, Any],
    *,
    profile: str,
    rank: int,
) -> dict[str, Any]:
    qname = str(candidate.get("qname") or "")
    return {
        "rank": int(candidate.get("rank") or rank),
        "qname": qname,
        "concept_label": candidate.get("concept_label"),
        "namespace": _namespace(qname),
        "candidate_sources_combined": _as_string_list(candidate.get("candidate_sources_combined") or candidate.get("candidate_source")),
        "score": round(float(candidate.get("score") or 0.0), 4),
        "confidence_bucket": str(candidate.get("confidence_bucket") or "candidate_review_only"),
        "risk_level": str(candidate.get("risk_level") or "medium"),
        "evidence": {
            "match_reasons": _as_string_list(candidate.get("match_reasons")),
            "risk_reasons": _as_string_list(candidate.get("risk_reasons")),
            "profile_filter_reasons": _as_string_list(candidate.get("profile_filter_reasons")),
            "source_weight": candidate.get("source_weight"),
            "raw_evidence": _as_dict(candidate.get("evidence")),
        },
        "ambiguity_reasons": _as_string_list(candidate.get("ambiguity_reasons")),
        "blocking_reasons": _as_string_list(candidate.get("blocking_reasons")),
        "requires_human_review": True,
        "safe_for_auto_apply": False,
        "recommended_action": _candidate_action(candidate),
        "profile": profile,
        "calibration_version": CALIBRATION_VERSION,
    }


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


def _job_sample_id(job: FilingJob) -> str:
    return f"filing_job:{job.id}"


def _job_default_year(job: FilingJob) -> int | None:
    fye = getattr(job, "financial_year_end", None)
    return getattr(fye, "year", None)


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


def _job_row_values(job: FilingJob, items: Sequence[ExtractedDataItem]) -> list[PdfRowValue]:
    sample_id = _job_sample_id(job)
    company_name = str(getattr(job, "company_name", None) or sample_id)
    default_year = _job_default_year(job)
    values: list[PdfRowValue] = []
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


def _record_from_row_value(row_value: PdfRowValue) -> dict[str, Any]:
    normalized = canonical_label(row_value.pdf_label)
    row_context = {
        "sample_id": row_value.sample_id,
        "row_id": row_value.pdf_row_id,
        "original_label": row_value.pdf_label,
        "normalized_label": normalized,
        "statement_family": row_value.pdf_statement_family,
        "row_role": "main_statement",
        "context_confidence": "database_extracted_data",
        "is_main_statement": row_value.pdf_statement_family not in {None, "notes"},
        "is_notes_context": row_value.pdf_statement_family == "notes",
    }
    return {
        "sample_id": row_value.sample_id,
        "company_name": row_value.company_name,
        "pdf_row_id": row_value.pdf_row_id,
        "row_id": row_value.pdf_row_id,
        "source_pdf_row_id": row_value.source_pdf_row_id,
        "pdf_label": row_value.pdf_label,
        "normalized_label": normalized,
        "pdf_value": row_value.pdf_value,
        "pdf_period": {
            "value_role": row_value.value_role,
            "expected_year": row_value.expected_year,
        },
        "statement_type": row_value.pdf_statement_type,
        "statement_family": row_value.pdf_statement_family,
        "pdf_statement_family": row_value.pdf_statement_family,
        "section_block": None,
        "row_role": "main_statement",
        "is_main_statement": row_value.pdf_statement_family not in {None, "notes"},
        "is_notes_context": row_value.pdf_statement_family == "notes",
        "row_context": row_context,
    }


def _load_runtime_concepts(
    taxonomy_metadata_path: str | Path | None = DEFAULT_TAXONOMY_METADATA,
) -> list[dict[str, Any]]:
    try:
        concepts, diagnostics = load_taxonomy_concept_metadata(
            taxonomy_metadata_path,
            allow_missing=False,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RankedCandidateAdvisoryError(
            "Ranked candidate taxonomy metadata is unavailable."
        ) from exc
    if not concepts:
        raise RankedCandidateAdvisoryError(
            "Ranked candidate taxonomy metadata is unavailable."
        )
    if diagnostics.get("status") != "loaded":
        raise RankedCandidateAdvisoryError(
            "Ranked candidate taxonomy metadata is unavailable."
        )
    return concepts


def _load_runtime_concept_cards(
    concept_playbook_paths: Sequence[str | Path] | None = None,
) -> list[dict[str, Any]]:
    try:
        cards, diagnostics = load_concept_playbook_cards(
            concept_playbook_paths,
            allow_missing=False,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RankedCandidateAdvisoryError(
            "Ranked candidate concept card artifacts are unavailable."
        ) from exc
    if not cards or diagnostics.get("status") != "loaded":
        raise RankedCandidateAdvisoryError(
            "Ranked candidate concept card artifacts are unavailable."
        )
    return cards


def _serialize_row(row: Mapping[str, Any], *, profile: str, max_candidates: int) -> dict[str, Any]:
    candidates = [
        _serialize_candidate(candidate, profile=profile, rank=index)
        for index, candidate in enumerate((row.get("candidates") or [])[:max_candidates], start=1)
        if isinstance(candidate, Mapping)
    ]
    status = str(row.get("candidate_coverage_status") or "")
    if not candidates and status in {"", "ranked_candidates_available", "deterministic_candidate_available"}:
        status = "no_candidate"
    return {
        "row_id": str(row.get("row_id") or ""),
        "statement_family": row.get("statement_family"),
        "section_block": row.get("section_block"),
        "row_label": row.get("pdf_label"),
        "normalized_label": row.get("normalized_label"),
        "row_value": row.get("value"),
        "period": _as_dict(row.get("pdf_period")),
        "note_boundary_type": _note_boundary_type(row),
        "candidate_coverage_status": status,
        "candidates": candidates,
    }


def build_ranked_candidate_advisory_response(
    *,
    job_id: int,
    filing_id: int | None = None,
    ranked_rows: Sequence[Mapping[str, Any]],
    config: RankedCandidateAdvisoryConfig | None = None,
    profile: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    cfg = config or RankedCandidateAdvisoryConfig.from_settings()
    if not cfg.enabled:
        raise RankedCandidateAdvisoryError("Ranked candidate advisory generation is disabled.")

    selected_profile = cfg.effective_profile(profile)
    max_rows = max(1, int(cfg.max_rows))
    max_candidates = max(1, int(cfg.max_candidates_per_row))
    calibrated_rows = apply_ranking_profile_to_rows(
        [dict(row) for row in ranked_rows[:max_rows]],
        selected_profile,
        top_n=max_candidates,
    )
    rows = [
        _serialize_row(row, profile=selected_profile, max_candidates=max_candidates)
        for row in calibrated_rows
    ]
    total_candidates = sum(len(row["candidates"]) for row in rows)
    rows_with_candidates = sum(1 for row in rows if row["candidates"])
    payload = {
        "job_id": int(job_id),
        "filing_id": filing_id,
        "profile": selected_profile,
        "mode": cfg.effective_mode(),
        "candidate_generation_status": "completed",
        "total_rows": len(rows),
        "rows_with_candidates": rows_with_candidates,
        "candidate_coverage": round(rows_with_candidates / len(rows), 4) if rows else None,
        "generated_at": generated_at or utc_now(),
        "feature_flags": feature_flags(cfg),
        "safety": {
            "safe_for_auto_apply_count": 0,
            "requires_human_review_count": total_candidates,
            "confirmed_tag_id_mutations": 0,
            "final_mapping_mutations": 0,
            "persistence_writes": 0,
            "ai_suggestion_table_writes": 0,
            "external_calls": 0,
            "xbrl_generation_count": 0,
            "arelle_runs": 0,
            "no_auto_apply_guarantee": True,
        },
        "rows": rows,
    }
    return RankedCandidateAdvisoryResponse(**payload).model_dump(mode="json")


def build_ranked_candidate_advisory_response_from_report(
    *,
    job_id: int,
    filing_id: int | None = None,
    report_path: str | Path = DEFAULT_BASELINE_REPORT,
    config: RankedCandidateAdvisoryConfig | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    return build_ranked_candidate_advisory_response(
        job_id=job_id,
        filing_id=filing_id,
        ranked_rows=load_ranked_rows_from_report(report_path),
        config=config,
        profile=profile,
    )


async def run_ranked_candidate_advisory_for_job(
    db: AsyncSession,
    *,
    job: FilingJob,
    request: RankedCandidateAdvisoryRequest | None = None,
    config: RankedCandidateAdvisoryConfig | None = None,
    taxonomy_metadata_path: str | Path | None = DEFAULT_TAXONOMY_METADATA,
    concept_playbook_paths: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    """Generate ranked candidates for one job without mutating state."""

    base_config = config or RankedCandidateAdvisoryConfig.from_settings()
    if not base_config.enabled:
        raise RankedCandidateAdvisoryError("Ranked candidate advisory generation is disabled.")

    run_config, selected_profile = config_for_request(base_config, request)
    concepts = _load_runtime_concepts(taxonomy_metadata_path)
    concept_cards = _load_runtime_concept_cards(concept_playbook_paths)

    items = await _load_job_extracted_items(db, job.id)
    row_values = _job_row_values(job, items)[: run_config.max_rows]
    records = [_record_from_row_value(row_value) for row_value in row_values]
    ranked_rows = rank_candidate_rows(
        records,
        concepts=concepts,
        evaluation_report=None,
        qwen_index={},
        local_concept_cards=concept_cards,
        top_n=run_config.max_candidates_per_row,
        filter_mode="tightened",
        enable_local_sources=True,
        include_existing_candidates=False,
        include_standard_sources=True,
        ranking_profile=selected_profile,
    )
    return build_ranked_candidate_advisory_response(
        job_id=job.id,
        filing_id=None,
        ranked_rows=ranked_rows,
        config=run_config,
        profile=selected_profile,
    )
