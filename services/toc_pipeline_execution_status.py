"""Bounded, non-sensitive execution telemetry for the TOC-aware pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4

from config import settings
from file_safety import assert_upload_child, uploads_root


STATUS_VERSION = "toc-pipeline-execution-v1"
ARTIFACT_SUBDIRECTORY = "document-structures"
ARTIFACT_FILENAME = "pipeline_execution_status.json"
MAX_ARTIFACT_BYTES = 128 * 1024

PIPELINE_STAGE_NAMES = (
    "azure_di_extraction",
    "normalization",
    "19A_analysis",
    "19A_persistence",
    "19B_classification",
    "19B_persistence",
    "19C_candidate_retrieval",
    "19C_mapping_build",
    "19C_persistence",
)
STAGE_STATUSES = {"not_started", "started", "completed", "skipped", "failed"}
TERMINAL_STAGE_STATUSES = {"completed", "skipped", "failed"}
PIPELINE_STATUSES = {"running", "completed", "failed"}

REASON_CODES = {
    "feature_disabled",
    "persistence_disabled",
    "upstream_structure_missing",
    "upstream_structure_invalid",
    "upstream_classification_missing",
    "upstream_classification_invalid",
    "upstream_hash_mismatch",
    "registry_hash_mismatch",
    "concept_inventory_unavailable",
    "row_limit_exceeded",
    "zero_eligible_rows",
    "candidate_retrieval_failed",
    "mapping_build_failed",
    "artifact_serialization_failed",
    "artifact_write_failed",
    "artifact_validation_failed",
    "artifact_missing_after_publication",
    "upstream_requires_review",
    "unexpected_exception",
}

SAFE_CONFIG_FIELDS = {
    "EXTRACTION_PIPELINE": "extraction_pipeline",
    "TOC_AWARE_PIPELINE_ENABLED": "toc_aware_pipeline_enabled",
    "TOC_AWARE_STRUCTURE_PERSISTENCE_ENABLED": "toc_aware_structure_persistence_enabled",
    "TOC_AWARE_TEMPLATE_CLASSIFICATION_ENABLED": "toc_aware_template_classification_enabled",
    "TOC_AWARE_TEMPLATE_CLASSIFICATION_PERSISTENCE_ENABLED": "toc_aware_template_classification_persistence_enabled",
    "TOC_AWARE_TEMPLATE_CLASSIFICATION_LIVE_LLM_ENABLED": "toc_aware_template_classification_live_llm_enabled",
    "TOC_AWARE_TAXONOMY_CANDIDATE_RETRIEVAL_ENABLED": "toc_aware_taxonomy_candidate_retrieval_enabled",
    "TOC_AWARE_INITIAL_MAPPING_ENABLED": "toc_aware_initial_mapping_enabled",
    "TOC_AWARE_INITIAL_MAPPING_PERSISTENCE_ENABLED": "toc_aware_initial_mapping_persistence_enabled",
    "TOC_AWARE_INITIAL_MAPPING_MODE": "toc_aware_initial_mapping_mode",
    "TOC_AWARE_INITIAL_MAPPING_LIVE_LLM_ENABLED": "toc_aware_initial_mapping_live_llm_enabled",
    "TOC_AWARE_INITIAL_MAPPING_MAX_ROWS_PER_JOB": "toc_aware_initial_mapping_max_rows_per_job",
    "TOC_AWARE_INITIAL_MAPPING_MAX_CANDIDATES": "toc_aware_initial_mapping_max_candidates",
    "TOC_AWARE_INITIAL_MAPPING_MAX_CONCURRENT_CALLS": "toc_aware_initial_mapping_max_concurrent_calls",
    "TOC_AWARE_INITIAL_MAPPING_ROW_TIMEOUT_SECONDS": "toc_aware_initial_mapping_row_timeout_seconds",
}

WRITER_FIELDS = (
    "writer_invoked",
    "serialization_completed",
    "atomic_temp_write_completed",
    "rename_completed",
    "post_write_validation_completed",
)

_DETAIL_FIELDS = {
    "artifact",
    "artifact_path",
    "version",
    "mode",
    "source_rows",
    "eligible_rows",
    "candidate_sets",
    "mapped_rows",
    "requires_human_review",
    "warning_count",
    "page_count",
    "table_count",
    "normalized_rows",
    "persisted_rows",
    "source_rows_received",
    "rows_structurally_skipped",
    "rows_eligible",
    "rows_attempted",
    "rows_successful",
    "rows_with_zero_safe_candidates",
    "rows_failed_locally",
    "stage_fatal_error_count",
    "row_errors",
}

ROW_ERROR_REASON_CODES = {
    "missing_section_context",
    "unclassified_section",
    "ambiguous_template_group",
    "unsupported_row_context",
    "unsupported_period_type",
    "unsupported_datatype",
    "empty_candidate_scope",
    "candidate_scoring_failed",
    "candidate_sort_failed",
    "candidate_card_invalid",
}
MAX_ROW_ERRORS = 100

_SAFE_REASON_SUMMARIES = {
    "feature_disabled": "The stage was disabled by its execution-time feature configuration.",
    "persistence_disabled": "Publication was disabled by its execution-time feature configuration.",
    "upstream_structure_missing": "The required current document-structure artifact was unavailable.",
    "upstream_structure_invalid": "The required document-structure artifact failed validation.",
    "upstream_classification_missing": "The required current classification artifact was unavailable.",
    "upstream_classification_invalid": "The required classification artifact failed validation.",
    "upstream_hash_mismatch": "An upstream artifact did not match its current source artifact.",
    "registry_hash_mismatch": "The classification or mapping registry hash did not match.",
    "concept_inventory_unavailable": "The local taxonomy concept inventory could not be loaded.",
    "row_limit_exceeded": "The normalized source-row count exceeded the configured maximum.",
    "zero_eligible_rows": "No source rows were eligible for taxonomy candidate mapping.",
    "candidate_retrieval_failed": "Section-aware taxonomy candidate retrieval failed.",
    "mapping_build_failed": "The bounded advisory initial-mapping build failed.",
    "artifact_serialization_failed": "The initial-mapping artifact could not be serialized.",
    "artifact_write_failed": "The initial-mapping artifact could not be atomically published.",
    "artifact_validation_failed": "The published initial-mapping artifact failed post-write validation.",
    "artifact_missing_after_publication": "Telemetry recorded a validated publication, but the artifact is no longer present.",
    "upstream_requires_review": "Upstream structure evidence requires human review.",
    "unexpected_exception": "The pipeline stopped because of an unexpected exception.",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_row_errors(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise ValueError("Pipeline row_errors must be an array")
    bounded = []
    for raw in value[:MAX_ROW_ERRORS]:
        if not isinstance(raw, Mapping):
            raise ValueError("Pipeline row error must be an object")
        reason_code = str(raw.get("reason_code") or "")
        if reason_code not in ROW_ERROR_REASON_CODES:
            raise ValueError("Pipeline row error reason_code is invalid")
        row_identifier = str(raw.get("row_identifier") or "")[:128]
        if not row_identifier:
            raise ValueError("Pipeline row error identifier is required")
        exception_class = re.sub(
            r"[^A-Za-z0-9_.]",
            "",
            str(raw.get("exception_class") or ""),
        )[:80]
        bounded.append(
            {
                "row_identifier": row_identifier,
                "reason_code": reason_code,
                "exception_class": exception_class,
            }
        )
    return bounded


def build_safe_config_snapshot(settings_obj: Any = settings) -> dict[str, Any]:
    """Return only explicitly whitelisted, non-secret pipeline configuration."""
    return {
        public_name: getattr(settings_obj, setting_name, None)
        for public_name, setting_name in SAFE_CONFIG_FIELDS.items()
    }


def safe_config_hash(snapshot: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(snapshot),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def pipeline_execution_status_artifact_path(job_id: int) -> Path:
    resolved_job_id = int(job_id)
    if resolved_job_id <= 0:
        raise ValueError("job_id must be positive")
    path = (
        uploads_root()
        / ARTIFACT_SUBDIRECTORY
        / f"job_{resolved_job_id}"
        / ARTIFACT_FILENAME
    )
    return assert_upload_child(str(path), ARTIFACT_SUBDIRECTORY)


def pipeline_execution_status_cleanup_candidate(job_id: int) -> tuple[str, str]:
    return (
        str(pipeline_execution_status_artifact_path(job_id)),
        ARTIFACT_SUBDIRECTORY,
    )


def _validate_payload(payload: Mapping[str, Any], *, job_id: int) -> dict[str, Any]:
    data = dict(payload)
    if data.get("status_version") != STATUS_VERSION:
        raise ValueError("Pipeline execution status version mismatch")
    if int(data.get("job_id") or 0) != int(job_id):
        raise ValueError("Pipeline execution status identity mismatch")
    config = data.get("effective_safe_config")
    if not isinstance(config, dict) or set(config) != set(SAFE_CONFIG_FIELDS):
        raise ValueError("Pipeline execution safe config is invalid")
    if data.get("safe_config_hash") != safe_config_hash(config):
        raise ValueError("Pipeline execution safe config hash mismatch")
    if data.get("status") not in PIPELINE_STATUSES:
        raise ValueError("Pipeline execution status is invalid")
    stages = data.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(PIPELINE_STAGE_NAMES):
        raise ValueError("Pipeline execution stage inventory is invalid")
    for name, stage in stages.items():
        if not isinstance(stage, dict) or stage.get("status") not in STAGE_STATUSES:
            raise ValueError(f"Pipeline execution stage is invalid: {name}")
        reason = stage.get("reason_code")
        if reason is not None and reason not in REASON_CODES:
            raise ValueError(f"Pipeline execution reason_code is invalid: {name}")
    return data


def load_pipeline_execution_status(job_id: int) -> dict[str, Any]:
    path = pipeline_execution_status_artifact_path(job_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("Pipeline execution status exceeds size limit")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Pipeline execution status must be an object")
    return _validate_payload(payload, job_id=int(job_id))


class PipelineExecutionStatusRecorder:
    """Persist every stage transition immediately using bounded atomic writes."""

    def __init__(self, data: dict[str, Any]):
        self.data = data

    @classmethod
    def create(
        cls,
        job_id: int,
        *,
        settings_obj: Any = settings,
        pipeline_run_id: str | None = None,
    ) -> "PipelineExecutionStatusRecorder":
        resolved_job_id = int(job_id)
        if resolved_job_id <= 0:
            raise ValueError("job_id must be positive")
        snapshot = build_safe_config_snapshot(settings_obj)
        stages = {
            name: {
                "status": "not_started",
                "started_at": None,
                "completed_at": None,
                "reason_code": None,
            }
            for name in PIPELINE_STAGE_NAMES
        }
        stages["19C_persistence"].update({field: False for field in WRITER_FIELDS})
        recorder = cls(
            {
                "status_version": STATUS_VERSION,
                "job_id": resolved_job_id,
                "pipeline_run_id": str(pipeline_run_id or uuid4()),
                "status": "running",
                "started_at": _utc_now(),
                "completed_at": None,
                "effective_safe_config": snapshot,
                "safe_config_hash": safe_config_hash(snapshot),
                "stages": stages,
            }
        )
        recorder._persist()
        return recorder

    def _persist(self) -> None:
        payload = json.dumps(
            _validate_payload(self.data, job_id=int(self.data["job_id"])),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        ) + "\n"
        if len(payload.encode("utf-8")) > MAX_ARTIFACT_BYTES:
            raise ValueError("Pipeline execution status exceeds size limit")
        path = pipeline_execution_status_artifact_path(int(self.data["job_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = assert_upload_child(
            str(path.with_name(f".{path.name}.{uuid4().hex}.tmp")),
            ARTIFACT_SUBDIRECTORY,
        )
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def transition(
        self,
        stage_name: str,
        status: str,
        *,
        reason_code: str | None = None,
        **details: Any,
    ) -> None:
        if stage_name not in PIPELINE_STAGE_NAMES:
            raise ValueError(f"Unknown pipeline stage: {stage_name}")
        if status not in STAGE_STATUSES:
            raise ValueError(f"Invalid pipeline stage status: {status}")
        if reason_code is not None and reason_code not in REASON_CODES:
            raise ValueError(f"Invalid pipeline reason_code: {reason_code}")
        unknown_details = set(details).difference(_DETAIL_FIELDS)
        if unknown_details:
            raise ValueError(
                "Unsupported pipeline stage detail: " + ", ".join(sorted(unknown_details))
            )
        stage = self.data["stages"][stage_name]
        timestamp = _utc_now()
        if status == "started" and not stage.get("started_at"):
            stage["started_at"] = timestamp
        if status in TERMINAL_STAGE_STATUSES:
            if not stage.get("started_at") and status == "completed":
                stage["started_at"] = timestamp
            stage["completed_at"] = timestamp
        stage["status"] = status
        stage["reason_code"] = reason_code
        if reason_code:
            stage["safe_error_summary"] = _SAFE_REASON_SUMMARIES[reason_code]
        else:
            stage.pop("safe_error_summary", None)
            stage.pop("exception_class", None)
        for key, value in details.items():
            if key == "row_errors":
                value = _bounded_row_errors(value)
            elif isinstance(value, str):
                value = value[:256]
            stage[key] = value
        self._persist()

    def fail(self, stage_name: str, reason_code: str, exc: BaseException | None = None) -> None:
        self.transition(stage_name, "failed", reason_code=reason_code)
        if exc is not None:
            stage = self.data["stages"][stage_name]
            stage["exception_class"] = re.sub(
                r"[^A-Za-z0-9_.]",
                "",
                type(exc).__name__,
            )[:80]
            self._persist()

    def writer_transition(self, field: str) -> None:
        if field not in WRITER_FIELDS:
            raise ValueError(f"Invalid initial-mapping writer field: {field}")
        stage = self.data["stages"]["19C_persistence"]
        if stage["status"] == "not_started":
            stage["status"] = "started"
            stage["started_at"] = _utc_now()
        stage[field] = True
        self._persist()

    def finish(self, status: str) -> None:
        if status not in {"completed", "failed"}:
            raise ValueError(f"Invalid final pipeline status: {status}")
        self.data["status"] = status
        self.data["completed_at"] = _utc_now()
        self._persist()

    def fail_unfinished(self, reason_code: str = "unexpected_exception") -> None:
        for stage_name in PIPELINE_STAGE_NAMES:
            stage = self.data["stages"][stage_name]
            if stage["status"] == "started":
                self.transition(stage_name, "failed", reason_code=reason_code)
            elif stage["status"] == "not_started":
                self.transition(stage_name, "skipped", reason_code=reason_code)
        self.finish("failed")
