#!/usr/bin/env python3
"""Local, read-only diagnostic for one TOC-aware pipeline job."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import settings  # noqa: E402
from file_safety import uploads_root  # noqa: E402
from schemas import (  # noqa: E402
    DocumentInitialMappingResult,
    DocumentStructureResult,
    DocumentTemplateClassificationResult,
)
from scripts.report_toc_aware_real_pdf_smoke import (  # noqa: E402
    build_classification_metrics,
    build_mapping_metrics,
    build_structure_metrics,
)
from services.document_section_template_classifier import (  # noqa: E402
    load_template_group_cards,
)
from services.section_aware_initial_mapping import (  # noqa: E402
    ARTIFACT_FILENAME as INITIAL_MAPPING_ARTIFACT_FILENAME,
    MAPPING_VERSION,
    template_classification_hash,
)
from services.section_aware_taxonomy_concept_cards import (  # noqa: E402
    build_taxonomy_concept_inventory,
)
from services.template_group_registry import (  # noqa: E402
    load_template_group_registry,
    semantic_inventory_sha256,
)
from services.toc_pipeline_execution_status import (  # noqa: E402
    ARTIFACT_FILENAME as EXECUTION_STATUS_FILENAME,
    MAX_ARTIFACT_BYTES as MAX_EXECUTION_STATUS_BYTES,
    build_safe_config_snapshot,
    load_pipeline_execution_status,
    safe_config_hash,
)
from services.toc_aware_document_structure import (  # noqa: E402
    ARTIFACT_FILENAME as STRUCTURE_ARTIFACT_FILENAME,
    FEATURE_VERSION as STRUCTURE_VERSION,
)
from services.toc_aware_template_classification import (  # noqa: E402
    ARTIFACT_FILENAME as CLASSIFICATION_ARTIFACT_FILENAME,
    CLASSIFICATION_VERSION,
    document_structure_hash,
)


ARTIFACT_SUBDIRECTORY = "document-structures"
ARTIFACT_SPECS = {
    "19A": {
        "current": STRUCTURE_ARTIFACT_FILENAME,
        "pattern": "structure_19a_v*.json",
        "version": STRUCTURE_VERSION,
        "max_bytes": 100 * 1024 * 1024,
    },
    "19B": {
        "current": CLASSIFICATION_ARTIFACT_FILENAME,
        "pattern": "template_classification_19b_v*.json",
        "version": CLASSIFICATION_VERSION,
        "max_bytes": 25 * 1024 * 1024,
    },
    "19C": {
        "current": INITIAL_MAPPING_ARTIFACT_FILENAME,
        "pattern": "initial_mapping_19c_v*.json",
        "version": MAPPING_VERSION,
        "max_bytes": 128 * 1024 * 1024,
    },
}

SAFE_CONFIG_FIELDS = {
    "extraction_pipeline": "EXTRACTION_PIPELINE",
    "toc_aware_pipeline_enabled": "TOC_AWARE_PIPELINE_ENABLED",
    "toc_aware_structure_persistence_enabled": "TOC_AWARE_STRUCTURE_PERSISTENCE_ENABLED",
    "toc_aware_llm_fallback_enabled": "TOC_AWARE_LLM_FALLBACK_ENABLED",
    "toc_aware_template_classification_enabled": "TOC_AWARE_TEMPLATE_CLASSIFICATION_ENABLED",
    "toc_aware_template_classification_persistence_enabled": "TOC_AWARE_TEMPLATE_CLASSIFICATION_PERSISTENCE_ENABLED",
    "toc_aware_template_classification_live_llm_enabled": "TOC_AWARE_TEMPLATE_CLASSIFICATION_LIVE_LLM_ENABLED",
    "toc_aware_taxonomy_candidate_retrieval_enabled": "TOC_AWARE_TAXONOMY_CANDIDATE_RETRIEVAL_ENABLED",
    "toc_aware_initial_mapping_enabled": "TOC_AWARE_INITIAL_MAPPING_ENABLED",
    "toc_aware_initial_mapping_persistence_enabled": "TOC_AWARE_INITIAL_MAPPING_PERSISTENCE_ENABLED",
    "toc_aware_initial_mapping_live_llm_enabled": "TOC_AWARE_INITIAL_MAPPING_LIVE_LLM_ENABLED",
    "toc_aware_initial_mapping_mode": "TOC_AWARE_INITIAL_MAPPING_MODE",
    "toc_aware_initial_mapping_max_candidates": "TOC_AWARE_INITIAL_MAPPING_MAX_CANDIDATES",
    "toc_aware_initial_mapping_max_rows_per_job": "TOC_AWARE_INITIAL_MAPPING_MAX_ROWS_PER_JOB",
    "toc_aware_initial_mapping_max_concurrent_calls": "TOC_AWARE_INITIAL_MAPPING_MAX_CONCURRENT_CALLS",
    "toc_aware_initial_mapping_row_timeout_seconds": "TOC_AWARE_INITIAL_MAPPING_ROW_TIMEOUT_SECONDS",
}

SENSITIVE_SETTING_FIELDS = (
    "model_api_token",
    "hugging_face_token",
    "openai_api_key",
    "azure_document_intelligence_key",
    "secret_key",
    "admin_route_token",
    "database_url",
    "redis_url",
    "celery_broker_url",
    "celery_result_backend",
)

ELIGIBLE_JOB_STATUSES = {"REVIEW", "COMPLETED"}
INITIAL_MAPPING_WARNING_CODES = {
    "toc_aware_initial_mapping_failed",
    "toc_aware_initial_mapping_persistence_failed",
}


class InvalidJobError(ValueError):
    """The requested job identifier is invalid or is known not to exist."""


def _bool_word(value: Any) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "unknown"
    return str(value)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_bounded(path: Path, maximum: int) -> str:
    if path.stat().st_size > maximum:
        raise ValueError("artifact_size_limit_exceeded")
    return path.read_text(encoding="utf-8")


def _sensitive_values(settings_obj: Any) -> list[str]:
    values = []
    for name in SENSITIVE_SETTING_FIELDS:
        value = str(getattr(settings_obj, name, "") or "").strip()
        if len(value) >= 4:
            values.append(value)
    return sorted(set(values), key=len, reverse=True)


def _redact_text(value: str, sensitive_values: list[str]) -> str:
    text = str(value)
    for secret in sensitive_values:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"\bhf_[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", text)
    text = re.sub(r"(?i)\bbearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    text = re.sub(
        r"(?i)\b(password|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+",
        lambda match: f"{match.group(1)}=[REDACTED]",
        text,
    )
    return text


def _redact(value: Any, sensitive_values: list[str]) -> Any:
    if isinstance(value, dict):
        return {
            _redact_text(str(key), sensitive_values): _redact(item, sensitive_values)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, sensitive_values) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, sensitive_values) for item in value]
    if isinstance(value, str):
        return _redact_text(value, sensitive_values)
    return value


def _effective_config(settings_obj: Any) -> dict[str, Any]:
    return {
        name: getattr(settings_obj, name, None)
        for name in SAFE_CONFIG_FIELDS
    }


def _env_declarations(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {
            "path": str(path) if path is not None else None,
            "available": False,
            "duplicates": [],
            "conflicts": [],
        }
    declarations: dict[str, list[str]] = {}
    safe_names = set(SAFE_CONFIG_FIELDS.values())
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        if name not in safe_names:
            continue
        declarations.setdefault(name, []).append(value.strip())
    duplicates = [
        {"name": name, "declaration_count": len(values)}
        for name, values in sorted(declarations.items())
        if len(values) > 1
    ]
    conflicts = [
        {
            "name": name,
            "declaration_count": len(values),
            "distinct_value_count": len(set(values)),
        }
        for name, values in sorted(declarations.items())
        if len(set(values)) > 1
    ]
    return {
        "path": str(path),
        "available": True,
        "duplicates": duplicates,
        "conflicts": conflicts,
    }


def _extract_warning_codes(raw_values: Any) -> list[str]:
    if raw_values is None:
        return []
    if not isinstance(raw_values, (list, tuple, set)):
        raw_values = [raw_values]
    codes = []
    for raw in raw_values:
        if isinstance(raw, Mapping):
            code = raw.get("code")
            if code:
                codes.append(str(code))
            continue
        text = str(raw or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            codes.extend(_extract_warning_codes(parsed))
        elif isinstance(parsed, dict):
            codes.extend(_extract_warning_codes([parsed]))
        elif re.fullmatch(r"[a-z][a-z0-9_.:-]{0,127}", text):
            codes.append(text)
    return sorted(set(codes))


def _error_code(message: Any) -> str | None:
    if not message:
        return None
    match = re.match(r"\[([A-Za-z0-9_.:-]+)\]", str(message).strip())
    return match.group(1) if match else "job_error_recorded"


async def _load_job_metadata_async(job_id: int) -> dict[str, Any]:
    """Run SELECT-only metadata queries; never flush or commit."""
    from sqlalchemy import func, select

    from database import (
        AsyncSessionLocal,
        ExtractedDataItem,
        FilingJob,
        FinancialStatementPage,
    )

    async with AsyncSessionLocal() as session:
        job = (
            await session.execute(
                select(
                    FilingJob.id,
                    FilingJob.status,
                    FilingJob.user_id,
                    FilingJob.progress,
                    FilingJob.error_message,
                ).where(FilingJob.id == int(job_id))
            )
        ).one_or_none()
        if job is None:
            return {"available": True, "exists": False, "id": int(job_id)}
        row_count = (
            await session.execute(
                select(func.count(ExtractedDataItem.id))
                .join(
                    FinancialStatementPage,
                    ExtractedDataItem.page_id == FinancialStatementPage.id,
                )
                .where(FinancialStatementPage.job_id == int(job_id))
            )
        ).scalar_one()
        warning_rows = (
            await session.execute(
                select(ExtractedDataItem.validation_warnings)
                .join(
                    FinancialStatementPage,
                    ExtractedDataItem.page_id == FinancialStatementPage.id,
                )
                .where(FinancialStatementPage.job_id == int(job_id))
                .where(ExtractedDataItem.validation_warnings.is_not(None))
            )
        ).scalars().all()
        return {
            "available": True,
            "exists": True,
            "id": int(job.id),
            "status": str(getattr(job.status, "value", job.status)),
            "owner_id": job.user_id,
            "progress": job.progress,
            "extracted_row_count": int(row_count or 0),
            "warning_codes": _extract_warning_codes(warning_rows),
            "error_code": _error_code(job.error_message),
        }


def load_job_metadata(job_id: int) -> dict[str, Any]:
    try:
        return asyncio.run(_load_job_metadata_async(job_id))
    except Exception as exc:
        return {
            "available": False,
            "exists": None,
            "id": int(job_id),
            "error_type": type(exc).__name__,
            "warning_codes": [],
        }


def _load_authorities() -> dict[str, Any]:
    output = {
        "classification_registry": {"available": False},
        "mapping_registry": {"available": False},
        "concept_inventory": {"available": False},
    }
    try:
        cards, metadata = load_template_group_cards()
        output["classification_registry"] = {
            "available": True,
            "version": metadata["registry_version"],
            "hash": metadata["registry_hash"],
            "template_count": len(cards),
        }
    except Exception as exc:
        output["classification_registry"]["error_type"] = type(exc).__name__
    try:
        registry = load_template_group_registry()
        output["mapping_registry"] = {
            "available": True,
            "version": str(
                registry.get("semantic_inventory_version") or "mpers-2022-v1"
            ),
            "hash": semantic_inventory_sha256(registry),
            "template_count": len(registry.get("template_groups") or []),
        }
    except Exception as exc:
        output["mapping_registry"]["error_type"] = type(exc).__name__
    try:
        cards, inventory = build_taxonomy_concept_inventory()
        output["concept_inventory"] = {
            "available": True,
            "hash": inventory["concept_inventory_hash"],
            "taxonomy_version": inventory["taxonomy_version"],
            "concept_count": len(cards),
        }
    except Exception as exc:
        output["concept_inventory"]["error_type"] = type(exc).__name__
    return output


def _artifact_base(job_dir: Path, stage: str) -> dict[str, Any]:
    spec = ARTIFACT_SPECS[stage]
    current_path = job_dir / spec["current"]
    stale = sorted(
        path.name
        for path in job_dir.glob(spec["pattern"])
        if path.is_file() and path.name != spec["current"]
    ) if job_dir.is_dir() else []
    if current_path.is_file():
        status = "PRESENT"
    elif stale:
        status = "STALE_ONLY"
    else:
        status = "MISSING"
    return {
        "status": status,
        "expected_version": spec["version"],
        "expected_file": spec["current"],
        "file": str(current_path) if current_path.is_file() else None,
        "file_sha256": _sha256_file(current_path) if current_path.is_file() else None,
        "stale_files": stale,
        "warnings": [],
    }


def _inspect_artifacts(
    job_id: int,
    job_dir: Path,
    authorities: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = {
        stage: _artifact_base(job_dir, stage)
        for stage in ("19A", "19B", "19C")
    }
    loaded: dict[str, Any] = {}

    record = records["19A"]
    if record["status"] == "PRESENT":
        try:
            path = Path(record["file"])
            structure = DocumentStructureResult.model_validate_json(
                _read_bounded(path, ARTIFACT_SPECS["19A"]["max_bytes"])
            )
            identity = (
                structure.job_id == int(job_id)
                and structure.feature_version == STRUCTURE_VERSION
            )
            record.update(
                {
                    "version": structure.feature_version,
                    "source_hash_validation": "PASS" if identity else "FAIL",
                    "semantic_hash": document_structure_hash(structure),
                    "warnings": list(structure.warnings),
                }
            )
            if identity:
                loaded["19A"] = structure
            else:
                record["status"] = "INVALID"
        except Exception as exc:
            record.update(
                {
                    "status": "INVALID",
                    "source_hash_validation": "FAIL",
                    "error_type": type(exc).__name__,
                }
            )
    else:
        record["source_hash_validation"] = "UNKNOWN"

    record = records["19B"]
    if record["status"] == "PRESENT":
        try:
            path = Path(record["file"])
            classification = DocumentTemplateClassificationResult.model_validate_json(
                _read_bounded(path, ARTIFACT_SPECS["19B"]["max_bytes"])
            )
            structure = loaded.get("19A")
            registry = authorities["classification_registry"]
            identity = (
                classification.job_id == int(job_id)
                and classification.filing_id == int(job_id)
                and classification.classification_version == CLASSIFICATION_VERSION
            )
            structure_link = bool(
                structure is not None
                and classification.source_structure_artifact_version
                == structure.feature_version
                and classification.source_structure_hash
                == document_structure_hash(structure)
            )
            registry_link = bool(
                registry.get("available")
                and classification.canonical_registry_version
                == registry.get("version")
                and classification.canonical_registry_hash == registry.get("hash")
            )
            record.update(
                {
                    "version": classification.classification_version,
                    "identity_validation": "PASS" if identity else "FAIL",
                    "structure_linkage": "PASS" if structure_link else "FAIL",
                    "registry_linkage": "PASS" if registry_link else "FAIL",
                    "semantic_hash": template_classification_hash(classification),
                    "warnings": list(classification.warnings),
                }
            )
            if identity and structure_link and registry_link:
                loaded["19B"] = classification
            else:
                record["status"] = "INVALID"
        except Exception as exc:
            record.update(
                {
                    "status": "INVALID",
                    "identity_validation": "FAIL",
                    "structure_linkage": "UNKNOWN",
                    "registry_linkage": "UNKNOWN",
                    "error_type": type(exc).__name__,
                }
            )
    else:
        record.update(
            {"identity_validation": "UNKNOWN", "structure_linkage": "UNKNOWN", "registry_linkage": "UNKNOWN"}
        )

    record = records["19C"]
    if record["status"] == "PRESENT":
        try:
            path = Path(record["file"])
            mapping = DocumentInitialMappingResult.model_validate_json(
                _read_bounded(path, ARTIFACT_SPECS["19C"]["max_bytes"])
            )
            structure = loaded.get("19A")
            classification = loaded.get("19B")
            registry = authorities["mapping_registry"]
            inventory = authorities["concept_inventory"]
            checks = {
                "job": mapping.job_id == int(job_id),
                "mapping_version": mapping.mapping_version == MAPPING_VERSION,
                "structure_version": bool(
                    structure is not None
                    and mapping.source_structure_version == structure.feature_version
                ),
                "structure_hash": bool(
                    structure is not None
                    and mapping.source_structure_hash
                    == document_structure_hash(structure)
                ),
                "classification_version": bool(
                    classification is not None
                    and mapping.source_classification_version
                    == classification.classification_version
                ),
                "classification_hash": bool(
                    classification is not None
                    and mapping.source_classification_hash
                    == template_classification_hash(classification)
                ),
                "registry_hash": bool(
                    registry.get("available")
                    and mapping.registry_hash == registry.get("hash")
                ),
                "concept_inventory_hash": bool(
                    inventory.get("available")
                    and mapping.concept_inventory_hash == inventory.get("hash")
                    and all(
                        item.concept_inventory_hash == inventory.get("hash")
                        for item in mapping.mappings
                    )
                ),
            }
            record.update(
                {
                    "version": mapping.mapping_version,
                    "identity_validation": "PASS" if checks["job"] and checks["mapping_version"] else "FAIL",
                    "structure_linkage": "PASS" if checks["structure_version"] and checks["structure_hash"] else "FAIL",
                    "classification_linkage": "PASS" if checks["classification_version"] and checks["classification_hash"] else "FAIL",
                    "registry_linkage": "PASS" if checks["registry_hash"] else "FAIL",
                    "concept_inventory_linkage": "PASS" if checks["concept_inventory_hash"] else "FAIL",
                    "failed_validations": sorted(
                        name for name, passed in checks.items() if not passed
                    ),
                    "warnings": list(mapping.warnings),
                }
            )
            if all(checks.values()):
                loaded["19C"] = mapping
            else:
                record["status"] = "INVALID"
        except Exception as exc:
            record.update(
                {
                    "status": "INVALID",
                    "identity_validation": "FAIL",
                    "structure_linkage": "UNKNOWN",
                    "classification_linkage": "UNKNOWN",
                    "registry_linkage": "UNKNOWN",
                    "concept_inventory_linkage": "UNKNOWN",
                    "error_type": type(exc).__name__,
                }
            )
    else:
        record.update(
            {
                "identity_validation": "UNKNOWN",
                "structure_linkage": "UNKNOWN",
                "classification_linkage": "UNKNOWN",
                "registry_linkage": "UNKNOWN",
                "concept_inventory_linkage": "UNKNOWN",
            }
        )
    return records, loaded


def _inspect_execution_status(
    job_id: int,
    job_dir: Path,
    settings_obj: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    path = job_dir / EXECUTION_STATUS_FILENAME
    current_snapshot = build_safe_config_snapshot(settings_obj)
    current_hash = safe_config_hash(current_snapshot)
    record: dict[str, Any] = {
        "status": "MISSING",
        "expected_file": EXECUTION_STATUS_FILENAME,
        "file": None,
        "file_sha256": None,
        "current_safe_config_hash": current_hash,
        "execution_safe_config_hash": None,
        "safe_config_comparison": "UNKNOWN",
        "config_differences": [],
    }
    if not path.is_file():
        return record, None
    record.update(
        {
            "status": "PRESENT",
            "file": str(path),
            "file_sha256": _sha256_file(path),
        }
    )
    try:
        if path.stat().st_size > MAX_EXECUTION_STATUS_BYTES:
            raise ValueError("execution_status_size_limit_exceeded")
        payload = load_pipeline_execution_status(job_id)
        execution_config = payload["effective_safe_config"]
        execution_hash = payload["safe_config_hash"]
        differences = [
            {
                "name": name,
                "execution_value": execution_config.get(name),
                "current_value": current_snapshot.get(name),
            }
            for name in sorted(current_snapshot)
            if execution_config.get(name) != current_snapshot.get(name)
        ]
        record.update(
            {
                "pipeline_run_id": payload["pipeline_run_id"],
                "run_status": payload["status"],
                "started_at": payload["started_at"],
                "completed_at": payload["completed_at"],
                "execution_safe_config_hash": execution_hash,
                "safe_config_comparison": (
                    "MATCH" if execution_hash == current_hash else "DIFFERENT"
                ),
                "config_differences": differences,
                "effective_safe_config": execution_config,
                "stages": payload["stages"],
            }
        )
        return record, payload
    except Exception as exc:
        record.update(
            {
                "status": "INVALID",
                "safe_config_comparison": "UNKNOWN",
                "error_type": type(exc).__name__,
            }
        )
        return record, None


def _gate(
    name: str,
    value: Any,
    status: str,
    *,
    required: bool,
    evidence: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "current_value": value,
        "status": status,
        "required_for_execution": required,
        "evidence": evidence,
    }


def _execution_gates(
    config: Mapping[str, Any],
    job: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    loaded: Mapping[str, Any],
    authorities: Mapping[str, Any],
    execution_status: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    flags = {
        "retrieval": bool(config["toc_aware_taxonomy_candidate_retrieval_enabled"]),
        "mapping": bool(config["toc_aware_initial_mapping_enabled"]),
        "persistence": bool(config["toc_aware_initial_mapping_persistence_enabled"]),
    }
    flag_complete = all(flags.values())
    mode = str(config["toc_aware_initial_mapping_mode"] or "deterministic_only")
    live_authorized = mode != "live_llm" or bool(
        config["toc_aware_initial_mapping_live_llm_enabled"]
    )
    row_count = job.get("extracted_row_count")
    row_limit = int(config["toc_aware_initial_mapping_max_rows_per_job"] or 0)
    row_limit_status = (
        "UNKNOWN"
        if row_count is None
        else "PASS" if int(row_count) <= row_limit else "FAIL"
    )
    warning_codes = set(job.get("warning_codes") or [])
    execution_stages = dict((execution_status or {}).get("stages") or {})
    candidate_stage = dict(execution_stages.get("19C_candidate_retrieval") or {})
    mapping_stage = dict(execution_stages.get("19C_mapping_build") or {})
    persistence_stage = dict(execution_stages.get("19C_persistence") or {})
    stage_failure_recorded = bool(
        warning_codes.intersection(INITIAL_MAPPING_WARNING_CODES)
        or any(
            stage.get("status") == "failed"
            for stage in (candidate_stage, mapping_stage, persistence_stage)
        )
    )
    mapping = loaded.get("19C")
    if mapping is not None:
        stage_status = "PASS"
        stage_value = True
        writer_status = "PASS"
        writer_value = True
        publication_status = "PASS"
    elif execution_status is not None:
        recorded_statuses = {
            str(stage.get("status") or "not_started")
            for stage in (candidate_stage, mapping_stage, persistence_stage)
        }
        stage_value = bool(recorded_statuses.intersection({"started", "completed", "failed"}))
        stage_status = "PASS" if stage_value else "NOT_RUN"
        writer_value = bool(persistence_stage.get("writer_invoked"))
        writer_status = "PASS" if writer_value else (
            "FAIL" if persistence_stage.get("status") == "failed" else "NOT_RUN"
        )
        publication_status = (
            "FAIL"
            if persistence_stage.get("status") in {"completed", "failed"}
            else "NOT_RUN"
        )
    elif stage_failure_recorded:
        stage_status = "PASS"
        stage_value = True
        writer_status = "UNKNOWN"
        writer_value = None
        publication_status = "FAIL"
    elif not flag_complete:
        stage_status = "NOT_RUN"
        stage_value = False
        writer_status = "NOT_RUN"
        writer_value = False
        publication_status = "NOT_RUN"
    else:
        stage_status = "UNKNOWN"
        stage_value = None
        writer_status = "UNKNOWN"
        writer_value = None
        publication_status = "FAIL"
    eligible_value = (
        mapping.eligible_rows
        if mapping is not None
        else candidate_stage.get("eligible_rows")
    )
    eligible_status = (
        "UNKNOWN"
        if eligible_value is None
        else "PASS" if eligible_value > 0 else "FAIL"
    )
    status_value = str(job.get("status") or "").upper()
    return [
        _gate("azure_di_pipeline_selected", config["extraction_pipeline"], "PASS" if config["extraction_pipeline"] == "azure_di" else "FAIL", required=True, evidence="services.azure_di_production_extraction orchestration branch"),
        _gate("19A_analysis_enabled", config["toc_aware_pipeline_enabled"], "PASS" if config["toc_aware_pipeline_enabled"] else "FAIL", required=True, evidence="effective config.Settings"),
        _gate("19A_persistence_enabled", config["toc_aware_structure_persistence_enabled"], "PASS" if config["toc_aware_structure_persistence_enabled"] else "FAIL", required=True, evidence="effective config.Settings"),
        _gate("19B_enabled", config["toc_aware_template_classification_enabled"], "PASS" if config["toc_aware_template_classification_enabled"] else "FAIL", required=True, evidence="effective config.Settings"),
        _gate("19B_persistence_enabled", config["toc_aware_template_classification_persistence_enabled"], "PASS" if config["toc_aware_template_classification_persistence_enabled"] else "FAIL", required=True, evidence="effective config.Settings"),
        _gate("candidate_retrieval_enabled", flags["retrieval"], "PASS" if flags["retrieval"] else "FAIL", required=True, evidence="effective config.Settings"),
        _gate("initial_mapping_enabled", flags["mapping"], "PASS" if flags["mapping"] else "FAIL", required=True, evidence="effective config.Settings"),
        _gate("initial_mapping_persistence_enabled", flags["persistence"], "PASS" if flags["persistence"] else "FAIL", required=True, evidence="effective config.Settings"),
        _gate("19C_configuration_complete", flags, "PASS" if flag_complete else "FAIL", required=True, evidence="all three #19C flags must be true; partial configuration is skipped"),
        _gate("mapping_mode_authorized", mode, "PASS" if live_authorized else "FAIL", required=True, evidence="deterministic_only needs no live provider; live_llm needs its explicit flag"),
        _gate("required_19A_artifact_accepted", artifacts["19A"]["status"], "PASS" if "19A" in loaded else "FAIL", required=True, evidence=f"current contract {STRUCTURE_VERSION}"),
        _gate("required_19B_artifact_accepted", artifacts["19B"]["status"], "PASS" if "19B" in loaded else "FAIL", required=True, evidence=f"current contract {CLASSIFICATION_VERSION}"),
        _gate("19B_registry_linkage_accepted", artifacts["19B"].get("registry_linkage"), "PASS" if artifacts["19B"].get("registry_linkage") == "PASS" else "FAIL", required=True, evidence="canonical 24-template registry version/hash"),
        _gate("concept_inventory_available", authorities["concept_inventory"].get("concept_count"), "PASS" if authorities["concept_inventory"].get("available") else "FAIL", required=True, evidence="local taxonomy concept inventory build"),
        _gate("source_row_limit", {"rows": row_count, "maximum": row_limit}, row_limit_status, required=True, evidence="persisted extracted-row count; normalized source snapshot is not persisted"),
        _gate("eligible_rows_greater_than_zero", eligible_value, eligible_status, required=False, evidence="not an execution/publication gate in current #19C code; exact value exists only in a produced #19C artifact"),
        _gate("job_status_allows_artifact_read", status_value or None, "PASS" if not status_value or status_value in ELIGIBLE_JOB_STATUSES else "FAIL", required=False, evidence="API availability gate, not the production stage invocation gate"),
        _gate("pipeline_stage_reached", stage_value, stage_status, required=False, evidence="execution-status stage transitions, current artifact, or retained stage warning"),
        _gate("warning_only_exception_caught", True if stage_failure_recorded else None, "PASS" if stage_failure_recorded else "UNKNOWN", required=False, evidence="durable failed stage or legacy transient warning"),
        _gate("artifact_writer_invoked", writer_value, writer_status, required=False, evidence="19C_persistence.writer_invoked"),
        _gate("artifact_serialization_completed", persistence_stage.get("serialization_completed") if execution_status else (True if mapping is not None else None), "PASS" if persistence_stage.get("serialization_completed") or mapping is not None else "FAIL" if execution_status else "UNKNOWN", required=False, evidence="19C_persistence.serialization_completed"),
        _gate("atomic_temp_write_completed", persistence_stage.get("atomic_temp_write_completed") if execution_status else (True if mapping is not None else None), "PASS" if persistence_stage.get("atomic_temp_write_completed") or mapping is not None else "FAIL" if execution_status else "UNKNOWN", required=False, evidence="19C_persistence.atomic_temp_write_completed"),
        _gate("artifact_rename_completed", persistence_stage.get("rename_completed") if execution_status else (True if mapping is not None else None), "PASS" if persistence_stage.get("rename_completed") or mapping is not None else "FAIL" if execution_status else "UNKNOWN", required=False, evidence="19C_persistence.rename_completed"),
        _gate("post_write_validation_completed", persistence_stage.get("post_write_validation_completed") if execution_status else (True if mapping is not None else None), "PASS" if persistence_stage.get("post_write_validation_completed") or mapping is not None else "FAIL" if execution_status else "UNKNOWN", required=False, evidence="19C_persistence.post_write_validation_completed"),
        _gate("artifact_publication_succeeded", mapping is not None, publication_status, required=False, evidence=f"current {INITIAL_MAPPING_ARTIFACT_FILENAME} validation"),
    ]


def _structure_conflict_details(structure: DocumentStructureResult) -> list[dict[str, Any]]:
    projected_by_printed = {
        int(mapping.printed_page_number): int(mapping.pdf_page_index)
        for mapping in structure.page_mappings
        if mapping.printed_page_number is not None
    }
    details = []
    for section in structure.sections:
        if "section_range_conflicts_with_page_mapping" not in section.warnings:
            continue
        projected_start = projected_by_printed.get(section.printed_page_start)
        projected_end = projected_by_printed.get(section.printed_page_end)
        stored_range = [section.pdf_page_start, section.pdf_page_end]
        projected_range = [projected_start, projected_end]
        reconciled = (
            None not in projected_range
            and stored_range == projected_range
            and section.grouping_method != "unresolved_page_mapping_conflict"
        )
        details.append(
            {
                "section_id": section.section_id,
                "raw_title": section.raw_title,
                "printed_range": [
                    section.printed_page_start,
                    section.printed_page_end,
                ],
                "projected_pdf_range": projected_range,
                "stored_pdf_range": stored_range,
                "conflict_reason": "section_range_conflicts_with_page_mapping",
                "grouping_method": section.grouping_method,
                "reconciled": reconciled,
                "blocks_downstream_analysis": False,
                "blocks_19C_execution": False,
            }
        )
    return details


def _smoke_summary(loaded: Mapping[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    structure = loaded.get("19A")
    classification = loaded.get("19B")
    mapping = loaded.get("19C")
    if structure is not None:
        metrics = build_structure_metrics(structure)
        output["19A"] = {
            "toc_count": metrics["toc_entry_count"],
            "suspicious_toc_entries": metrics["suspicious_toc_entry_count"],
            "alignment_confidence": metrics["alignment_confidence"],
            "dominant_offsets": metrics["dominant_offsets"],
            "requires_human_review": metrics["requires_human_review"],
            "section_page_conflicts": metrics["section_page_mapping_conflict_count"],
            "assignment_rate": metrics["assignment_rate"],
            "assignment_rate_excluding_toc": metrics["assignment_rate_excluding_toc"],
            "unassigned_rate": metrics["unassigned_rate"],
            "unassigned_rate_excluding_toc": metrics["unassigned_rate_excluding_toc"],
            "dropped_count": metrics["dropped_evidence"],
            "notes_range": metrics["notes_ranges"][0] if metrics["notes_ranges"] else None,
            "conflicts": _structure_conflict_details(structure),
        }
    if classification is not None:
        metrics = build_classification_metrics(classification, structure=structure)
        output["19B"] = {
            "primary_outcomes": metrics["primary_classification_summary"],
            "notes_child_count": metrics["note_subsection_count"],
            "notes_conservation": metrics["notes_conservation"],
            "notes_segmentation_metrics": metrics["notes_segmentation_metrics"],
            "notes_children_outside_parent": metrics["notes_children_outside_parent_range_count"],
            "notes_child_page_distribution": metrics["notes_child_page_distribution"],
        }
    if mapping is not None:
        metrics = build_mapping_metrics(mapping)
        output["19C"] = {
            **metrics,
            "provider_calls": mapping.llm_calls,
        }
    return output


def _gating_reasons(gates: list[dict[str, Any]]) -> list[str]:
    reasons = []
    labels = {
        "azure_di_pipeline_selected": "extraction_pipeline_is_not_azure_di",
        "19A_analysis_enabled": "toc_aware_pipeline_enabled=false",
        "19A_persistence_enabled": "structure_persistence_enabled=false",
        "19B_enabled": "template_classification_enabled=false",
        "19B_persistence_enabled": "template_classification_persistence_enabled=false",
        "candidate_retrieval_enabled": "candidate_retrieval_enabled=false",
        "initial_mapping_enabled": "initial_mapping_enabled=false",
        "initial_mapping_persistence_enabled": "initial_mapping_persistence_enabled=false",
        "19C_configuration_complete": "retrieval_mapping_persistence_not_all_enabled",
        "mapping_mode_authorized": "live_mapping_mode_not_authorized",
        "required_19A_artifact_accepted": "current_19A_artifact_not_accepted",
        "required_19B_artifact_accepted": "current_19B_artifact_not_accepted",
        "19B_registry_linkage_accepted": "19B_registry_linkage_not_accepted",
        "concept_inventory_available": "concept_inventory_unavailable",
        "source_row_limit": "source_row_limit_exceeded",
    }
    for gate in gates:
        if gate["required_for_execution"] and gate["status"] != "PASS":
            reasons.append(labels.get(gate["name"], f"{gate['name']}={gate['status'].lower()}"))
    return list(dict.fromkeys(reasons))


def _diagnosis(
    artifacts: Mapping[str, Any],
    job: Mapping[str, Any],
    gates: list[dict[str, Any]],
    execution_record: Mapping[str, Any],
    execution_status: Mapping[str, Any] | None,
) -> dict[str, Any]:
    reasons = _gating_reasons(gates)
    warning_codes = set(job.get("warning_codes") or [])
    execution_config = dict((execution_status or {}).get("effective_safe_config") or {})
    expected = (
        all(
            bool(execution_config.get(name))
            for name in (
                "TOC_AWARE_TAXONOMY_CANDIDATE_RETRIEVAL_ENABLED",
                "TOC_AWARE_INITIAL_MAPPING_ENABLED",
                "TOC_AWARE_INITIAL_MAPPING_PERSISTENCE_ENABLED",
            )
        )
        if execution_status is not None
        else not reasons
    )
    config_comparison = execution_record.get("safe_config_comparison")
    if artifacts["19C"]["status"] == "PRESENT":
        return {
            "expected_to_run": expected,
            "diagnosis": "COMPLETE",
            "gating_reasons": reasons,
            "pipeline_stage_reached": True,
            "reason_code": None,
            "stage": "19C_persistence",
            "stage_status": "completed",
            "safe_config_comparison": config_comparison,
            "likely_execution_branches": [],
            "missing_evidence": [],
        }
    if artifacts["19C"]["status"] == "INVALID":
        return {
            "expected_to_run": expected,
            "diagnosis": "STALE_OR_INVALID_19C_ARTIFACT",
            "gating_reasons": reasons,
            "pipeline_stage_reached": True,
            "reason_code": "artifact_validation_failed",
            "stage": "19C_persistence",
            "stage_status": "failed",
            "safe_config_comparison": config_comparison,
            "likely_execution_branches": ["artifact publication produced an incompatible artifact"],
            "missing_evidence": [],
        }
    if execution_status is not None:
        stages = dict(execution_status.get("stages") or {})
        stage_order = (
            "19C_candidate_retrieval",
            "19C_mapping_build",
            "19C_persistence",
        )
        failed = next(
            (
                (name, stages.get(name) or {})
                for name in stage_order
                if (stages.get(name) or {}).get("status") == "failed"
            ),
            None,
        )
        if failed is not None:
            name, stage = failed
            return {
                "expected_to_run": expected,
                "diagnosis": "INITIAL_MAPPING_STAGE_FAILED",
                "gating_reasons": reasons,
                "pipeline_stage_reached": True,
                "reason_code": stage.get("reason_code") or "unexpected_exception",
                "stage": name,
                "stage_status": "failed",
                "safe_config_comparison": config_comparison,
                "safe_error_summary": stage.get("safe_error_summary"),
                "exception_class": stage.get("exception_class"),
                "likely_execution_branches": [],
                "missing_evidence": [],
            }
        skipped = next(
            (
                (name, stages.get(name) or {})
                for name in stage_order
                if (stages.get(name) or {}).get("status") == "skipped"
            ),
            None,
        )
        if skipped is not None:
            name, stage = skipped
            return {
                "expected_to_run": expected,
                "diagnosis": "INITIAL_MAPPING_STAGE_SKIPPED",
                "gating_reasons": reasons,
                "pipeline_stage_reached": False,
                "reason_code": stage.get("reason_code") or "unexpected_exception",
                "stage": name,
                "stage_status": "skipped",
                "safe_config_comparison": config_comparison,
                "safe_error_summary": stage.get("safe_error_summary"),
                "likely_execution_branches": [],
                "missing_evidence": [],
            }
        persistence = dict(stages.get("19C_persistence") or {})
        if persistence.get("status") == "completed":
            return {
                "expected_to_run": expected,
                "diagnosis": "ARTIFACT_MISSING_AFTER_RECORDED_PUBLICATION",
                "gating_reasons": reasons,
                "pipeline_stage_reached": True,
                "reason_code": "artifact_missing_after_publication",
                "stage": "19C_persistence",
                "stage_status": "completed",
                "safe_config_comparison": config_comparison,
                "likely_execution_branches": [],
                "missing_evidence": [],
            }
        return {
            "expected_to_run": expected,
            "diagnosis": "INSTRUMENTED_PIPELINE_RUN_INCOMPLETE",
            "gating_reasons": reasons,
            "pipeline_stage_reached": False,
            "reason_code": "unexpected_exception",
            "stage": "19C_candidate_retrieval",
            "stage_status": "not_started",
            "safe_config_comparison": config_comparison,
            "likely_execution_branches": [],
            "missing_evidence": [],
        }
    if warning_codes.intersection(INITIAL_MAPPING_WARNING_CODES):
        return {
            "expected_to_run": expected,
            "diagnosis": "INITIAL_MAPPING_STAGE_FAILED",
            "gating_reasons": reasons,
            "pipeline_stage_reached": True,
            "reason_code": "unexpected_exception",
            "stage": "19C_mapping_build",
            "stage_status": "failed",
            "safe_config_comparison": config_comparison,
            "likely_execution_branches": [
                "upstream artifact rejected during build",
                "source-row/context/inventory build exception",
                "artifact writer or publication exception",
            ],
            "missing_evidence": ["safe_stage_exception_detail"],
        }
    if reasons:
        config_reason = any("false" in reason or "not_all_enabled" in reason or "not_authorized" in reason for reason in reasons)
        return {
            "expected_to_run": False,
            "diagnosis": "CONFIGURATION_GATED" if config_reason else "UPSTREAM_OR_LOCAL_INPUT_GATED",
            "gating_reasons": reasons,
            "pipeline_stage_reached": False,
            "reason_code": None,
            "stage": "19C_candidate_retrieval",
            "stage_status": "skipped",
            "safe_config_comparison": config_comparison,
            "likely_execution_branches": ["pipeline stage skipped or failed its documented prerequisite"],
            "missing_evidence": [],
        }
    return {
        "expected_to_run": True,
        "diagnosis": "UNKNOWN",
        "gating_reasons": [],
        "pipeline_stage_reached": None,
        "reason_code": None,
        "stage": None,
        "stage_status": None,
        "safe_config_comparison": config_comparison,
        "likely_execution_branches": [
            "historical worker feature flags differed from current effective settings",
            "initial mapping build raised and the warning-only exception was not retained",
            "artifact writer or atomic publication raised and the warning was not retained",
        ],
        "missing_evidence": [
            "historical_worker_effective_config",
            "persisted_stage_warning_or_exception",
            "artifact_writer_invocation",
            "artifact_publication_outcome",
            "normalized_source_rows_and_eligibility",
        ],
    }


def _problems(
    config: Mapping[str, Any],
    artifacts: Mapping[str, Any],
    smoke: Mapping[str, Any],
    diagnosis: Mapping[str, Any],
) -> list[str]:
    problems = []
    for stage in ("19A", "19B", "19C"):
        status = artifacts[stage]["status"]
        if status in {"INVALID", "STALE_ONLY"}:
            problems.append(f"{stage.lower()}_artifact_{status.lower()}")
    if diagnosis["diagnosis"] in {
        "CONFIGURATION_GATED",
        "UPSTREAM_OR_LOCAL_INPUT_GATED",
        "INITIAL_MAPPING_STAGE_FAILED",
        "INITIAL_MAPPING_STAGE_SKIPPED",
        "ARTIFACT_MISSING_AFTER_RECORDED_PUBLICATION",
        "INSTRUMENTED_PIPELINE_RUN_INCOMPLETE",
        "STALE_OR_INVALID_19C_ARTIFACT",
    }:
        problems.append(diagnosis["diagnosis"].lower())
    structure = smoke.get("19A") or {}
    if int(structure.get("section_page_conflicts") or 0):
        problems.append("section_page_mapping_conflicts")
    if int(structure.get("dropped_count") or 0):
        problems.append("dropped_structure_evidence")
    if structure.get("requires_human_review"):
        problems.append("structure_requires_human_review")
    classification = smoke.get("19B") or {}
    conservation = classification.get("notes_conservation") or {}
    if conservation and not conservation.get("passed", False):
        problems.append("notes_conservation_failed")
    if int(classification.get("notes_children_outside_parent") or 0):
        problems.append("notes_children_outside_parent")
    mapping = smoke.get("19C") or {}
    if mapping and int(mapping.get("eligible_rows") or 0) == 0:
        problems.append("initial_mapping_has_zero_eligible_rows")
    if int(mapping.get("candidate_leakage") or 0):
        problems.append("initial_mapping_candidate_leakage")
    if int(mapping.get("abstract_selection_count") or 0):
        problems.append("initial_mapping_abstract_selection")
    if any(int(value or 0) for value in (mapping.get("mutation_counts") or {}).values()):
        problems.append("initial_mapping_mutation_detected")
    if (
        str(config.get("toc_aware_initial_mapping_mode")) == "deterministic_only"
        and int(mapping.get("provider_calls") or 0)
    ):
        problems.append("provider_calls_in_deterministic_mode")
    return list(dict.fromkeys(problems))


def exit_code_for(report: Mapping[str, Any]) -> int:
    return {"PASS": 0, "FAIL": 1, "INCOMPLETE": 2}.get(
        str(report.get("overall") or ""),
        4,
    )


def build_diagnostic(
    job_id: int,
    *,
    job_metadata: Mapping[str, Any] | None = None,
    settings_obj: Any = settings,
    env_path: Path | None = None,
) -> dict[str, Any]:
    if int(job_id) <= 0:
        raise InvalidJobError("job_id_must_be_positive")
    resolved_job_id = int(job_id)
    job = dict(job_metadata) if job_metadata is not None else load_job_metadata(resolved_job_id)
    job_dir = (
        uploads_root()
        / ARTIFACT_SUBDIRECTORY
        / f"job_{resolved_job_id}"
    ).resolve()
    if job.get("available") and job.get("exists") is False and not job_dir.is_dir():
        raise InvalidJobError("job_not_found")
    if not job.get("available") and not job_dir.is_dir():
        raise RuntimeError("job_metadata_and_artifact_directory_unavailable")

    config = _effective_config(settings_obj)
    authorities = _load_authorities()
    artifacts, loaded = _inspect_artifacts(
        resolved_job_id,
        job_dir,
        authorities,
    )
    execution_record, execution_status = _inspect_execution_status(
        resolved_job_id,
        job_dir,
        settings_obj,
    )
    gates = _execution_gates(
        config,
        job,
        artifacts,
        loaded,
        authorities,
        execution_status,
    )
    smoke = _smoke_summary(loaded)
    diagnosis = _diagnosis(
        artifacts,
        job,
        gates,
        execution_record,
        execution_status,
    )
    problems = _problems(config, artifacts, smoke, diagnosis)
    if execution_record["status"] == "INVALID":
        problems.append("pipeline_execution_status_invalid")
    missing = [
        stage for stage in ("19A", "19B", "19C")
        if artifacts[stage]["status"] == "MISSING"
    ]
    if problems:
        overall = "FAIL"
    elif missing:
        overall = "INCOMPLETE"
    else:
        overall = "PASS"

    report = {
        "utility": "TaxonomyFlow TOC Pipeline Diagnostic",
        "job_id": resolved_job_id,
        "read_only": True,
        "job": job,
        "effective_config": config,
        "env_declarations": _env_declarations(
            env_path if env_path is not None else PROJECT_ROOT / ".env"
        ),
        "authorities": authorities,
        "artifacts": artifacts,
        "pipeline_execution_status": execution_record,
        "initial_mapping_execution_gates": gates,
        "diagnosis": diagnosis,
        "smoke_summary": smoke,
        "problems": problems,
        "missing_artifacts": missing,
        "overall": overall,
        "safety": {
            "database_queries": "SELECT_ONLY",
            "database_writes": 0,
            "artifact_writes": 0,
            "http_calls": 0,
            "azure_calls": 0,
            "llm_calls": 0,
            "supervisor_calls": 0,
            "mapping_builds": 0,
            "template_field_mutations": 0,
            "xbrl_generations": 0,
            "arelle_runs": 0,
        },
    }
    report["exit_code"] = exit_code_for(report)
    return _redact(report, _sensitive_values(settings_obj))


def render_text(report: Mapping[str, Any]) -> str:
    job = report.get("job") or {}
    config = report.get("effective_config") or {}
    lines = [
        "TaxonomyFlow TOC Pipeline Diagnostic",
        f"Job: {report.get('job_id')}",
        "",
        "JOB",
        f"status: {job.get('status') or 'UNKNOWN'}",
        f"owner: {job.get('owner_id') if job.get('owner_id') is not None else 'UNKNOWN'}",
        f"progress: {job.get('progress') if job.get('progress') is not None else 'UNKNOWN'}",
        f"extracted rows: {job.get('extracted_row_count') if job.get('extracted_row_count') is not None else 'UNKNOWN'}",
        "",
        "EFFECTIVE CONFIG",
        f"pipeline: {config.get('extraction_pipeline')}",
        f"19A enabled: {_bool_word(config.get('toc_aware_pipeline_enabled'))}",
        f"19A persistence: {_bool_word(config.get('toc_aware_structure_persistence_enabled'))}",
        f"19B enabled: {_bool_word(config.get('toc_aware_template_classification_enabled'))}",
        f"19B persistence: {_bool_word(config.get('toc_aware_template_classification_persistence_enabled'))}",
        f"19B live LLM: {_bool_word(config.get('toc_aware_template_classification_live_llm_enabled'))}",
        f"19C candidate retrieval: {_bool_word(config.get('toc_aware_taxonomy_candidate_retrieval_enabled'))}",
        f"19C enabled: {_bool_word(config.get('toc_aware_initial_mapping_enabled'))}",
        f"19C persistence: {_bool_word(config.get('toc_aware_initial_mapping_persistence_enabled'))}",
        f"19C live LLM: {_bool_word(config.get('toc_aware_initial_mapping_live_llm_enabled'))}",
        f"19C mode: {config.get('toc_aware_initial_mapping_mode')}",
    ]
    conflicts = (report.get("env_declarations") or {}).get("conflicts") or []
    if conflicts:
        lines.extend(["", "ENV DECLARATION CONFLICTS"])
        lines.extend(
            f"{item['name']}: {item['declaration_count']} declarations / {item['distinct_value_count']} values"
            for item in conflicts
        )
    execution = report.get("pipeline_execution_status") or {}
    lines.extend(
        [
            "",
            "PIPELINE EXECUTION STATUS",
            f"status artifact: {execution.get('status')}",
            f"run status: {execution.get('run_status') or 'UNKNOWN'}",
            f"run id: {execution.get('pipeline_run_id') or 'UNKNOWN'}",
            f"safe config: {execution.get('safe_config_comparison') or 'UNKNOWN'}",
        ]
    )
    for stage_name in (
        "19C_candidate_retrieval",
        "19C_mapping_build",
        "19C_persistence",
    ):
        stage = (execution.get("stages") or {}).get(stage_name)
        if stage:
            lines.append(
                f"{stage_name}: {stage.get('status')}"
                + (
                    f" reason={stage.get('reason_code')}"
                    if stage.get("reason_code")
                    else ""
                )
            )
    lines.extend(["", "ARTIFACTS"])
    for stage in ("19A", "19B", "19C"):
        artifact = report["artifacts"][stage]
        lines.extend(
            [
                "",
                f"{stage}:",
                f"status: {artifact['status']}",
                f"version: {artifact.get('version') or artifact.get('expected_version')}",
                f"file: {artifact.get('file') or artifact.get('expected_file')}",
            ]
        )
        if artifact.get("stale_files"):
            lines.append("stale: " + ", ".join(artifact["stale_files"]))
        for label, key in (
            ("source/hash validation", "source_hash_validation"),
            ("19A linkage", "structure_linkage"),
            ("19B linkage", "classification_linkage"),
            ("registry linkage", "registry_linkage"),
            ("concept inventory linkage", "concept_inventory_linkage"),
        ):
            if key in artifact:
                lines.append(f"{label}: {artifact[key]}")

    lines.extend(["", "19C EXECUTION GATES"])
    for gate in report.get("initial_mapping_execution_gates") or []:
        required = "required" if gate["required_for_execution"] else "diagnostic"
        lines.append(
            f"{gate['name']}: {gate['status']} ({required}; value={_bool_word(gate['current_value'])})"
        )

    diagnosis = report.get("diagnosis") or {}
    lines.extend(
        [
            "",
            "DIAGNOSIS",
            f"Expected to run: {'YES' if diagnosis.get('expected_to_run') else 'NO'}",
            f"diagnosis: {diagnosis.get('diagnosis')}",
        ]
    )
    if diagnosis.get("reason_code"):
        lines.append(f"reason: {diagnosis.get('reason_code')}")
    if diagnosis.get("stage"):
        lines.append(
            f"stage: {diagnosis.get('stage')} ({diagnosis.get('stage_status')})"
        )
    if diagnosis.get("safe_config_comparison"):
        lines.append(
            f"execution/current safe config: {diagnosis.get('safe_config_comparison')}"
        )
    for reason in diagnosis.get("gating_reasons") or []:
        lines.append(f"gate: {reason}")
    for branch in diagnosis.get("likely_execution_branches") or []:
        lines.append(f"possible branch: {branch}")
    for missing in diagnosis.get("missing_evidence") or []:
        lines.append(f"missing evidence: {missing}")

    smoke = report.get("smoke_summary") or {}
    if smoke:
        lines.extend(["", "SMOKE SUMMARY"])
        if "19A" in smoke:
            value = smoke["19A"]
            lines.append(
                "19A: "
                f"toc={value['toc_count']} suspicious={value['suspicious_toc_entries']} "
                f"alignment={value['alignment_confidence']} offsets={value['dominant_offsets']} "
                f"conflicts={value['section_page_conflicts']} assignment={value['assignment_rate']} "
                f"unassigned={value['unassigned_rate']} dropped={value['dropped_count']} "
                f"notes={value['notes_range']}"
            )
            for conflict in value.get("conflicts") or []:
                lines.append(
                    "19A conflict: "
                    f"section={conflict['section_id']} title={conflict['raw_title']!r} "
                    f"printed={conflict['printed_range']} "
                    f"projected_pdf={conflict['projected_pdf_range']} "
                    f"stored_pdf={conflict['stored_pdf_range']} "
                    f"reason={conflict['conflict_reason']} "
                    f"reconciled={_bool_word(conflict['reconciled'])} "
                    f"blocks_downstream={_bool_word(conflict['blocks_downstream_analysis'])}"
                )
        if "19B" in smoke:
            value = smoke["19B"]
            lines.append(
                "19B: "
                f"outcomes={value['primary_outcomes']} notes={value['notes_child_count']} "
                f"conservation={value['notes_conservation'].get('passed')} "
                f"outside_parent={value['notes_children_outside_parent']} "
                f"segmentation={value['notes_segmentation_metrics']}"
            )
        if "19C" in smoke:
            value = smoke["19C"]
            lines.append(
                "19C: "
                f"with_section={value['rows_with_section_id']} without_section={value['rows_without_section_id']} "
                f"eligible={value['eligible_rows']} mapped={value['mapped_rows']} "
                f"ambiguous={value['ambiguous_rows']} abstain={value['abstain_rows']} "
                f"leakage={value['candidate_leakage']} abstract={value['abstract_selection_count']} "
                f"provider_calls={value['provider_calls']} mutations={value['mutation_counts']}"
            )
    lines.extend(["", f"OVERALL: {report.get('overall')}"])
    if report.get("problems"):
        lines.append("problems: " + ", ".join(report["problems"]))
    lines.append(f"exit code: {report.get('exit_code', exit_code_for(report))}")
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace | None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--json", action="store_true", dest="as_json")
    try:
        return parser.parse_args(argv)
    except SystemExit:
        return None


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args is None:
        return 3
    try:
        job_id = int(args.job_id)
        if job_id <= 0:
            raise InvalidJobError("job_id_must_be_positive")
    except (TypeError, ValueError, InvalidJobError):
        payload = {
            "overall": "INVALID",
            "exit_code": 3,
            "error": {"code": "invalid_job_or_input"},
        }
        print(json.dumps(payload, indent=2, sort_keys=True) if args.as_json else "Invalid job/input.")
        return 3
    try:
        report = build_diagnostic(job_id)
    except InvalidJobError:
        payload = {
            "job_id": job_id,
            "overall": "INVALID",
            "exit_code": 3,
            "error": {"code": "invalid_job_or_input"},
        }
        print(json.dumps(payload, indent=2, sort_keys=True) if args.as_json else f"Job {job_id}: invalid or not found.")
        return 3
    except Exception as exc:
        payload = {
            "job_id": job_id,
            "overall": "ERROR",
            "exit_code": 4,
            "read_only": True,
            "error": {
                "code": "diagnostic_failed",
                "type": type(exc).__name__,
            },
        }
        payload = _redact(payload, _sensitive_values(settings))
        print(json.dumps(payload, indent=2, sort_keys=True) if args.as_json else f"Diagnostic failed safely: {payload['error']['type']}")
        return 4
    code = exit_code_for(report)
    report["exit_code"] = code
    print(json.dumps(report, indent=2, sort_keys=True, default=str) if args.as_json else render_text(report))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
