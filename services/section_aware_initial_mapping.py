"""#19C orchestration, source binding, artifact persistence, and capabilities."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

from config import settings
from file_safety import assert_upload_child, uploads_root
from schemas import (
    DocumentInitialMappingResult,
    InitialMappingCapabilitiesRead,
    InitialTaxonomyMappingResult,
    RowMappingEligibility,
    SectionAwareCandidateSet,
)
from services.section_aware_initial_mapping_llm import (
    InitialMappingLLMConfig,
    PROMPT_VERSION,
    run_bounded_initial_mapping_llm,
)
from services.section_aware_mapping_context_builder import (
    MappingContextLimits,
    build_section_aware_mapping_context,
)
from services.section_aware_row_mapping_eligibility import (
    classify_row_mapping_eligibility,
)
from services.section_aware_taxonomy_candidate_retriever import (
    CandidateRetrievalSystemError,
    RETRIEVAL_VERSION,
    retrieve_section_aware_candidates,
)
from services.section_aware_taxonomy_concept_cards import (
    build_taxonomy_concept_inventory,
    normalize_concept_label,
)
from services.template_group_registry import (
    load_template_group_registry,
    semantic_inventory_sha256,
)
from services.toc_aware_document_structure import (
    load_document_structure,
)
from services.toc_aware_template_classification import (
    document_structure_hash,
    load_template_classification,
)


MAPPING_VERSION = "19C-v2"
ARTIFACT_SUBDIRECTORY = "document-structures"
ARTIFACT_FILENAME = "initial_mapping_19c_v2.json"
STALE_ARTIFACT_FILENAMES = ("initial_mapping_19c_v1.json",)
# 5,000 rows * 8 compact cards * ~2.5 KiB/card is about 100 MiB. The
# additional 28 MiB allows row/result metadata while retaining a hard bound.
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
ELIGIBLE_JOB_STATUSES = {"REVIEW", "COMPLETED"}


class InitialMappingSourceError(ValueError):
    pass


class InitialMappingStageError(RuntimeError):
    def __init__(self, stage: str, reason_code: str, message: str):
        super().__init__(message)
        self.stage = stage
        self.reason_code = reason_code


class InitialMappingArtifactPersistenceError(RuntimeError):
    def __init__(self, reason_code: str, writer_phase: str, message: str):
        super().__init__(message)
        self.reason_code = reason_code
        self.writer_phase = writer_phase


StageCallback = Callable[[str, str, Mapping[str, Any]], None]
WriterLifecycleCallback = Callable[[str], None]


def _notify_stage(
    callback: StageCallback | None,
    stage: str,
    status: str,
    **details: Any,
) -> None:
    if callback is not None:
        callback(stage, status, details)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def template_classification_hash(classification) -> str:
    return _canonical_json_hash(classification.model_dump(mode="json"))


def _candidate_value(candidate: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in candidate:
            return candidate.get(name)
    return None


def source_rows_from_normalized_candidates(
    candidates: Iterable[Mapping[str, Any]],
    *,
    item_ids_by_original_candidate: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    persisted_ids = {str(key): str(value) for key, value in (item_ids_by_original_candidate or {}).items()}
    rows = []
    seen: set[str] = set()
    for index, raw in enumerate(candidates):
        candidate = dict(raw)
        provenance = dict(candidate.get("provenance") or {})
        original_id = str(
            candidate.get("original_candidate_id")
            or candidate.get("candidate_id")
            or f"normalized-{index + 1}"
        )
        source_row_id = persisted_ids.get(original_id, f"candidate:{original_id}")
        if source_row_id in seen:
            raise InitialMappingSourceError(f"Duplicate source row identity: {source_row_id}")
        seen.add(source_row_id)
        current_value = _candidate_value(candidate, "value", "current_value", "extracted_value")
        prior_value = _candidate_value(candidate, "previous_value", "prior_value", "value_previous_year")
        sign = None
        if current_value not in (None, ""):
            text = str(current_value).strip()
            sign = "negative" if text.startswith("-") or (text.startswith("(") and text.endswith(")")) else "positive"
        rows.append(
            {
                "source_row_id": source_row_id,
                "original_candidate_id": original_id,
                "persisted_extracted_data_item_id": persisted_ids.get(original_id),
                "label": str(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet") or "").strip(),
                "normalized_label": normalize_concept_label(candidate.get("label") or candidate.get("text") or ""),
                "row_type": str(candidate.get("row_type") or "unknown"),
                "current_value": current_value,
                "prior_value": prior_value,
                "current_year": candidate.get("current_year"),
                "prior_year": candidate.get("prior_year"),
                "statement_section": candidate.get("statement_section"),
                "page_number": int(candidate.get("page_number") or provenance.get("page_number") or 0) or None,
                "table_id": candidate.get("table_id") or provenance.get("table_id") or (
                    f"table:{provenance.get('table_index')}" if provenance.get("table_index") is not None else None
                ),
                "table_title": candidate.get("table_title") or provenance.get("table_title"),
                "table_headers": candidate.get("table_headers") or provenance.get("table_headers") or [],
                "column_headers": candidate.get("column_headers") or provenance.get("column_headers") or [],
                "currency": candidate.get("currency") or provenance.get("currency"),
                "unit": candidate.get("unit") or provenance.get("unit"),
                "sign": sign,
                "indentation": candidate.get("indentation") or provenance.get("indentation"),
                "parent_row_id": candidate.get("parent_row_id") or provenance.get("parent_row_id"),
                "provenance": {
                    **provenance,
                    "source_candidate_index": index,
                    "original_candidate_id": original_id,
                },
                "warnings": list(candidate.get("warnings") or []),
            }
        )
    return rows


def _row_values_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        normalize_concept_label(row.get("label")),
        str(row.get("current_value") or "").strip(),
        str(row.get("prior_value") or "").strip(),
    )


def detect_duplicate_and_competing_rows(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    by_label: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    by_exact: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        label = normalize_concept_label(row.get("label"))
        if label:
            by_label[label].append(row)
            by_exact[_row_values_key(row)].append(row)
    row_metadata: dict[str, dict[str, Any]] = {str(row["source_row_id"]): {} for row in rows}
    conflicts: list[dict[str, Any]] = []
    for key, group in sorted(by_exact.items()):
        if len(group) < 2:
            continue
        ids = [str(item["source_row_id"]) for item in group]
        group_id = "duplicate-" + _canonical_json_hash([*key, *ids])[:16]
        for rank, row in enumerate(group):
            row_metadata[str(row["source_row_id"])].update(
                {"duplicate_group_id": group_id, "duplicate_rank": rank}
            )
        conflicts.append(
            {
                "conflict_type": "exact_duplicate",
                "duplicate_group_id": group_id,
                "source_row_ids": ids,
                "context_differences": [
                    {"source_row_id": str(item["source_row_id"]), "page_number": item.get("page_number"), "table_id": item.get("table_id")}
                    for item in group
                ],
                "preferred_source_hint": ids[0],
                "requires_human_review": True,
            }
        )
    for label, group in sorted(by_label.items()):
        if len(group) < 2:
            continue
        ids = [str(item["source_row_id"]) for item in group]
        for row in group:
            row_metadata[str(row["source_row_id"])]["competing_source_row_ids"] = [
                item for item in ids if item != str(row["source_row_id"])
            ]
        if len({_row_values_key(item) for item in group}) > 1:
            conflicts.append(
                {
                    "conflict_type": "competing_source_rows",
                    "normalized_label": label,
                    "source_row_ids": ids,
                    "context_differences": [
                        {
                            "source_row_id": str(item["source_row_id"]),
                            "page_number": item.get("page_number"),
                            "table_id": item.get("table_id"),
                            "statement_section": item.get("statement_section"),
                        }
                        for item in group
                    ],
                    "preferred_source_hint": None,
                    "requires_human_review": True,
                }
            )
    return row_metadata, conflicts


def _page_in_range(page_number: int | None, start: int | None, end: int | None) -> bool:
    if not page_number or start is None:
        return False
    resolved_end = end if end is not None else start
    return int(start) <= int(page_number) <= int(resolved_end)


def _classification_contexts(
    structure,
    classification,
    rows: Sequence[Mapping[str, Any]],
    *,
    registry: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    outcomes = {outcome.section_id: outcome for outcome in classification.outcomes}
    sections = {section.section_id: section for section in structure.sections}
    subsections = {item.child_section_id: item for item in classification.note_subsections}
    explicit: dict[str, list[str]] = defaultdict(list)
    for section in structure.sections:
        for row_id in section.extracted_row_ids:
            explicit[str(row_id)].append(section.section_id)
    for subsection in classification.note_subsections:
        for row_id in subsection.extracted_row_references:
            explicit[str(row_id)].insert(0, subsection.child_section_id)

    contexts: dict[str, dict[str, Any]] = {}
    for row in rows:
        row_id = str(row["source_row_id"])
        candidates = list(dict.fromkeys(explicit.get(row_id, [])))
        page = row.get("page_number")
        if not candidates:
            candidates.extend(
                item.child_section_id
                for item in classification.note_subsections
                if _page_in_range(page, item.azure_page_start, item.azure_page_end)
            )
        if not candidates:
            candidates.extend(
                section.section_id
                for section in structure.sections
                if _page_in_range(page, section.azure_page_start, section.azure_page_end)
            )
        section_id = candidates[0] if candidates else None
        outcome = outcomes.get(section_id)
        subsection = subsections.get(section_id)
        parent = sections.get(subsection.parent_section_id) if subsection else sections.get(section_id)
        assignments = list(outcome.assignments) if outcome else []
        group_ids = sorted({assignment.template_group_id for assignment in assignments})
        source_registry = registry or load_template_group_registry()
        group_index = {
            str(item["template_group_id"]): item
            for item in source_registry.get("template_groups") or []
        }
        statement_families = sorted(
            {
                str(group_index[group].get("statement_family"))
                for group in group_ids
                if group in group_index and group_index[group].get("statement_family")
            }
        )
        contexts[row_id] = {
            "section_id": subsection.parent_section_id if subsection else section_id,
            "subsection_id": subsection.child_section_id if subsection else None,
            "section_title": parent.raw_title if parent else None,
            "subsection_title": subsection.raw_heading if subsection else None,
            "canonical_section_type": outcome.canonical_section_type if outcome else None,
            "classification_outcome": str(getattr(outcome.outcome, "value", outcome.outcome)) if outcome else "unassigned",
            "template_group_ids": group_ids,
            "statement_families": statement_families,
            "requires_human_review": bool(len(candidates) != 1 or (outcome and outcome.requires_human_review)),
            "candidate_section_ids": candidates,
        }
    return contexts


def _nearby_paragraphs(structure, row: Mapping[str, Any]) -> list[str]:
    page = row.get("page_number")
    if not page:
        return []
    return [
        evidence.text_evidence
        for evidence in structure.content_evidence
        if evidence.text_evidence
        and evidence.content_type in {"paragraph", "text_block", "heading"}
        and int(page) in evidence.azure_page_numbers
    ]


def nearest_structural_context_label(
    peers: Sequence[Mapping[str, Any]],
    peer_index: int,
) -> str | None:
    """Return the nearest following-preferred total/subtotal as local hierarchy evidence."""

    current = normalize_concept_label(peers[peer_index].get("label"))
    if "total" in current or "subtotal" in current:
        return None
    desired_family = None
    if "receiv" in current or "cash" in current:
        desired_family = "asset"
    elif "payab" in current or "accrual" in current or "due to" in current:
        desired_family = "liabilit"
    elif any(term in current for term in ("capital", "retained", "shareholder")):
        desired_family = "equity"
    candidates: list[tuple[int, int, int, str]] = []
    for index, peer in enumerate(peers):
        if index == peer_index:
            continue
        label = str(peer.get("label") or "")
        normalized = normalize_concept_label(label)
        if "total" not in normalized and "subtotal" not in normalized:
            continue
        candidates.append(
            (
                abs(index - peer_index),
                0 if index > peer_index else 1,
                index,
                label,
            )
        )
    if desired_family:
        matching = [
            item
            for item in candidates
            if desired_family in normalize_concept_label(item[3])
        ]
        if matching:
            candidates = matching
    return min(candidates)[3] if candidates else None


def _mapping_id(job_id: int, row_id: str, classification_hash: str) -> str:
    return "mapping-" + hashlib.sha256(f"{job_id}:{row_id}:{classification_hash}".encode("utf-8")).hexdigest()[:24]


def _safe_exception_class(exc: BaseException) -> str:
    return "".join(
        character
        for character in type(exc).__name__
        if character.isalnum() or character in {"_", "."}
    )[:80]


def _retrieval_failed_candidate_set(
    *,
    row_id: str,
    eligibility: RowMappingEligibility,
    context: Mapping[str, Any],
    concept_inventory_hash: str,
    reason_code: str,
    exception_class: str,
    top_k: int,
) -> SectionAwareCandidateSet:
    return SectionAwareCandidateSet(
        source_row_id=row_id,
        section_id=context.get("section_id"),
        subsection_id=context.get("subsection_id"),
        template_group_ids=sorted(set(context.get("template_group_ids") or [])),
        row_eligibility=eligibility,
        candidate_outcome="retrieval_failed",
        top_k=top_k,
        retrieval_version=RETRIEVAL_VERSION,
        concept_inventory_hash=concept_inventory_hash,
        requires_human_review=True,
        warnings=[
            f"row_local_retrieval_failure:{reason_code}",
            f"exception_class:{exception_class}",
        ],
    )


async def build_document_initial_mapping(
    *,
    job_id: int,
    filing_id: int,
    source_rows: Sequence[Mapping[str, Any]],
    llm_client: Any | None = None,
    llm_config: InitialMappingLLMConfig | None = None,
    generated_at: datetime | None = None,
    stage_callback: StageCallback | None = None,
) -> DocumentInitialMappingResult:
    try:
        structure = load_document_structure(job_id)
    except FileNotFoundError as exc:
        raise InitialMappingStageError(
            "19C_candidate_retrieval",
            "upstream_structure_missing",
            "Current document structure is unavailable.",
        ) from exc
    except Exception as exc:
        raise InitialMappingStageError(
            "19C_candidate_retrieval",
            "upstream_structure_invalid",
            "Current document structure is invalid.",
        ) from exc
    try:
        classification = load_template_classification(job_id, structure=structure)
    except FileNotFoundError as exc:
        raise InitialMappingStageError(
            "19C_candidate_retrieval",
            "upstream_classification_missing",
            "Current template classification is unavailable.",
        ) from exc
    except Exception as exc:
        raise InitialMappingStageError(
            "19C_candidate_retrieval",
            str(
                getattr(
                    exc,
                    "reason_code",
                    "upstream_classification_invalid",
                )
            ),
            "Current template classification is invalid.",
        ) from exc
    if classification.filing_id != int(filing_id):
        raise InitialMappingStageError(
            "19C_candidate_retrieval",
            "upstream_classification_invalid",
            "Template classification filing identity mismatch.",
        )
    max_rows = max(1, int(getattr(settings, "toc_aware_initial_mapping_max_rows_per_job", 5000) or 5000))
    if len(source_rows) > max_rows:
        raise InitialMappingStageError(
            "19C_candidate_retrieval",
            "row_limit_exceeded",
            "Source row count exceeds the configured maximum.",
        )

    try:
        cards, inventory = build_taxonomy_concept_inventory()
    except Exception as exc:
        raise InitialMappingStageError(
            "19C_candidate_retrieval",
            "concept_inventory_unavailable",
            "Taxonomy concept inventory is unavailable.",
        ) from exc
    try:
        registry = load_template_group_registry()
    except Exception as exc:
        raise InitialMappingStageError(
            "19C_candidate_retrieval",
            "registry_hash_mismatch",
            "Template registry is unavailable or invalid.",
        ) from exc
    _notify_stage(
        stage_callback,
        "19C_candidate_retrieval",
        "started",
        source_rows=len(source_rows),
    )
    try:
        registry_hash = semantic_inventory_sha256(registry)
        structure_hash = document_structure_hash(structure)
        classification_hash = template_classification_hash(classification)
        rows = [dict(row) for row in source_rows]
        row_metadata, conflicts = detect_duplicate_and_competing_rows(rows)
        section_contexts = _classification_contexts(
            structure,
            classification,
            rows,
            registry=registry,
        )
        rows_by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            context = section_contexts[str(row["source_row_id"])]
            rows_by_section[
                str(
                    context.get("subsection_id")
                    or context.get("section_id")
                    or "unassigned"
                )
            ].append(row)

        config = llm_config or InitialMappingLLMConfig.from_settings()
        max_candidates = min(20, max(1, int(getattr(settings, "toc_aware_initial_mapping_max_candidates", 8) or 8)))
        min_score = max(0.0, min(1.0, float(getattr(settings, "toc_aware_initial_mapping_min_candidate_score", 0.0) or 0.0)))
        limits = MappingContextLimits(
            max_characters=int(getattr(settings, "toc_aware_initial_mapping_max_context_characters", 12000) or 12000),
            max_siblings=int(getattr(settings, "toc_aware_initial_mapping_max_siblings", 4) or 0),
            max_ancestors=int(getattr(settings, "toc_aware_initial_mapping_max_ancestors", 3) or 0),
            max_descendants=int(getattr(settings, "toc_aware_initial_mapping_max_descendants", 3) or 0),
            max_candidate_cards=max_candidates,
            max_nearby_paragraphs=int(getattr(settings, "toc_aware_initial_mapping_max_nearby_paragraphs", 2) or 0),
        )
        semaphore = asyncio.Semaphore(max(1, int(getattr(settings, "toc_aware_initial_mapping_max_concurrent_calls", 1) or 1)))
        timestamp = generated_at or _utc_now()
    except Exception as exc:
        _notify_stage(
            stage_callback,
            "19C_candidate_retrieval",
            "failed",
            reason_code="candidate_retrieval_failed",
            source_rows_received=len(source_rows),
            rows_structurally_skipped=0,
            rows_eligible=0,
            rows_attempted=0,
            rows_successful=0,
            rows_with_zero_safe_candidates=0,
            rows_failed_locally=0,
            stage_fatal_error_count=1,
            row_errors=[],
        )
        raise InitialMappingStageError(
            "19C_candidate_retrieval",
            "candidate_retrieval_failed",
            "Section-aware candidate preparation failed.",
        ) from exc

    prepared_rows: list[dict[str, Any]] = []
    retrieval_metrics: dict[str, int] = {
        "source_rows_received": len(rows),
        "rows_structurally_skipped": 0,
        "rows_eligible": 0,
        "rows_attempted": 0,
        "rows_successful": 0,
        "rows_with_zero_safe_candidates": 0,
        "rows_failed_locally": 0,
        "stage_fatal_error_count": 0,
    }
    row_errors: list[dict[str, str]] = []
    for row in rows:
        row_id = str(row["source_row_id"])
        context = section_contexts[row_id]
        duplicate = row_metadata.get(row_id, {})
        try:
            eligibility = classify_row_mapping_eligibility(
                row,
                section_outcome=context["classification_outcome"],
                duplicate_group_id=duplicate.get("duplicate_group_id"),
                duplicate_rank=int(duplicate.get("duplicate_rank") or 0),
                competing_source_row_ids=duplicate.get("competing_source_row_ids") or [],
            )
        except Exception as exc:
            eligibility = RowMappingEligibility(
                source_row_id=row_id,
                outcome="unsupported_context",
                eligible=False,
                reasons=["unsupported_row_context"],
                requires_human_review=True,
            )
            exception_class = _safe_exception_class(exc)
            reason_code = "unsupported_row_context"
            retrieval_metrics["rows_failed_locally"] += 1
            row_errors.append(
                {
                    "row_identifier": row_id,
                    "reason_code": reason_code,
                    "exception_class": exception_class,
                }
            )
            candidate_set = _retrieval_failed_candidate_set(
                row_id=row_id,
                eligibility=eligibility,
                context=context,
                concept_inventory_hash=inventory["concept_inventory_hash"],
                reason_code=reason_code,
                exception_class=exception_class,
                top_k=max_candidates,
            )
            prepared_rows.append(
                {
                    "row": row,
                    "row_id": row_id,
                    "context": context,
                    "duplicate": duplicate,
                    "eligibility": eligibility,
                    "candidate_set": candidate_set,
                    "mapping_context": {},
                }
            )
            continue

        if eligibility.eligible:
            retrieval_metrics["rows_eligible"] += 1
            retrieval_metrics["rows_attempted"] += 1
        else:
            retrieval_metrics["rows_structurally_skipped"] += 1

        try:
            peers = rows_by_section[
                str(
                    context.get("subsection_id")
                    or context.get("section_id")
                    or "unassigned"
                )
            ]
            peer_index = next(
                index
                for index, item in enumerate(peers)
                if str(item["source_row_id"]) == row_id
            )
            sibling_labels = [
                str(item.get("label") or "")
                for index, item in enumerate(peers)
                if index != peer_index and abs(index - peer_index) <= 3
            ]
            parent = next(
                (
                    item
                    for item in peers
                    if str(item.get("source_row_id"))
                    == str(row.get("parent_row_id"))
                ),
                None,
            )
            parent_label = (
                parent.get("label")
                if parent
                else nearest_structural_context_label(peers, peer_index)
            )
            candidate_set = retrieve_section_aware_candidates(
                row=row,
                row_eligibility=eligibility,
                section_id=context.get("section_id"),
                subsection_id=context.get("subsection_id"),
                template_group_ids=context.get("template_group_ids") or [],
                statement_families=context.get("statement_families") or [],
                inventory_cards=cards,
                concept_inventory_hash=inventory["concept_inventory_hash"],
                max_candidates=max_candidates,
                min_candidate_score=min_score,
                sibling_labels=sibling_labels,
                parent_label=parent_label,
            )
            mapping_context = build_section_aware_mapping_context(
                row=row,
                section=context,
                rows_in_section=peers,
                candidate_set=candidate_set,
                limits=limits,
                nearby_paragraphs=_nearby_paragraphs(structure, row),
            )
        except CandidateRetrievalSystemError as exc:
            retrieval_metrics["stage_fatal_error_count"] = 1
            _notify_stage(
                stage_callback,
                "19C_candidate_retrieval",
                "failed",
                reason_code="concept_inventory_unavailable",
                **retrieval_metrics,
                row_errors=row_errors,
            )
            raise InitialMappingStageError(
                "19C_candidate_retrieval",
                "concept_inventory_unavailable",
                "Taxonomy candidate inventory is invalid.",
            ) from exc
        except Exception as exc:
            reason_code = str(
                getattr(exc, "reason_code", "unsupported_row_context")
            )
            if reason_code not in {
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
            }:
                reason_code = "unsupported_row_context"
            exception_class = _safe_exception_class(exc)
            retrieval_metrics["rows_failed_locally"] += 1
            row_errors.append(
                {
                    "row_identifier": row_id,
                    "reason_code": reason_code,
                    "exception_class": exception_class,
                }
            )
            candidate_set = _retrieval_failed_candidate_set(
                row_id=row_id,
                eligibility=eligibility,
                context=context,
                concept_inventory_hash=inventory["concept_inventory_hash"],
                reason_code=reason_code,
                exception_class=exception_class,
                top_k=max_candidates,
            )
            mapping_context = {}
        else:
            if eligibility.eligible:
                retrieval_metrics["rows_successful"] += 1
                if not candidate_set.candidates:
                    retrieval_metrics["rows_with_zero_safe_candidates"] += 1

        prepared_rows.append(
            {
                "row": row,
                "row_id": row_id,
                "context": context,
                "duplicate": duplicate,
                "eligibility": eligibility,
                "candidate_set": candidate_set,
                "mapping_context": mapping_context,
            }
        )

    eligible_rows = sum(
        1 for item in prepared_rows if item["eligibility"].eligible
    )
    _notify_stage(
        stage_callback,
        "19C_candidate_retrieval",
        "completed",
        eligible_rows=eligible_rows,
        candidate_sets=eligible_rows,
        **retrieval_metrics,
        row_errors=row_errors,
        reason_code="zero_eligible_rows" if eligible_rows == 0 else None,
    )
    _notify_stage(
        stage_callback,
        "19C_mapping_build",
        "started",
        mode=config.mode,
    )

    async def map_row(prepared: Mapping[str, Any]) -> InitialTaxonomyMappingResult:
        row = prepared["row"]
        row_id = str(prepared["row_id"])
        context = prepared["context"]
        duplicate = prepared["duplicate"]
        eligibility = prepared["eligibility"]
        candidate_set = prepared["candidate_set"]
        async with semaphore:
            decision = await run_bounded_initial_mapping_llm(
                context=prepared["mapping_context"],
                candidate_set=candidate_set,
                config=config,
                llm_client=llm_client,
            )
        warnings = list(candidate_set.warnings)
        if context.get("requires_human_review"):
            warnings.append("section_assignment_requires_human_review")
        return InitialTaxonomyMappingResult(
            mapping_id=_mapping_id(job_id, row_id, classification_hash),
            source_row_id=row_id,
            section_id=context.get("section_id"),
            subsection_id=context.get("subsection_id"),
            template_group_ids=context.get("template_group_ids") or [],
            source_label=str(row.get("label") or ""),
            source_values={
                "current_value": row.get("current_value"),
                "prior_value": row.get("prior_value"),
                "current_year": row.get("current_year"),
                "prior_year": row.get("prior_year"),
                "currency": row.get("currency"),
                "unit": row.get("unit"),
                "sign": row.get("sign"),
            },
            row_eligibility=eligibility,
            decision=decision["decision"],
            selected_concept_id=decision.get("selected_concept_id"),
            selected_qname=decision.get("selected_qname"),
            candidate_set=candidate_set,
            confidence=decision.get("confidence", 0.0),
            reason=decision.get("reason") or "No mapping reason was produced.",
            alternatives=decision.get("alternative_concept_ids") or [],
            requires_human_review=True,
            mapping_method=decision.get("mapping_method") or "failed",
            provider=decision.get("provider"),
            model=decision.get("model"),
            provider_call_count=int(decision.get("provider_calls") or 0),
            prompt_hash=decision.get("prompt_hash"),
            prompt_version=PROMPT_VERSION,
            retrieval_version=RETRIEVAL_VERSION,
            concept_inventory_hash=inventory["concept_inventory_hash"],
            source_structure_hash=structure_hash,
            source_classification_hash=classification_hash,
            registry_hash=registry_hash,
            duplicate_group_id=duplicate.get("duplicate_group_id"),
            competing_source_row_ids=duplicate.get("competing_source_row_ids") or [],
            warnings=list(dict.fromkeys(warnings)),
            generated_at=timestamp,
        )

    try:
        mappings = list(
            await asyncio.gather(*(map_row(prepared) for prepared in prepared_rows))
        )
    except Exception as exc:
        _notify_stage(
            stage_callback,
            "19C_mapping_build",
            "failed",
            reason_code="mapping_build_failed",
        )
        raise InitialMappingStageError(
            "19C_mapping_build",
            "mapping_build_failed",
            "Bounded initial mapping build failed.",
        ) from exc
    _notify_stage(
        stage_callback,
        "19C_mapping_build",
        "completed",
        mapped_rows=sum(1 for item in mappings if item.decision == "mapped"),
    )
    decision_counts = defaultdict(int)
    for mapping in mappings:
        decision_counts[mapping.decision] += 1
    llm_calls = sum(mapping.provider_call_count for mapping in mappings)
    safety_summary = {
        "advisory_only": True,
        "requires_human_review_count": len(mappings),
        "safe_for_auto_apply_count": 0,
        "source_rows_dropped": 0,
        "template_group_leakage_count": sum(
            1
            for mapping in mappings
            for candidate in mapping.candidate_set.candidates
            if not set(candidate.concept_card.template_group_ids).intersection(mapping.template_group_ids)
        ),
        "abstract_fact_selection_count": sum(
            1
            for mapping in mappings
            if mapping.selected_concept_id
            and any(candidate.concept_id == mapping.selected_concept_id and candidate.concept_card.abstract for candidate in mapping.candidate_set.candidates)
        ),
        "narrative_or_container_mapping_count": sum(
            1
            for mapping in mappings
            if mapping.row_eligibility.outcome in {"narrative_row", "structural_only"} and mapping.decision == "mapped"
        ),
        "payload_boundary_violations": 0,
        "provider_calls": llm_calls,
        "maximum_provider_calls_per_eligible_row": 1,
        "recursive_retries": 0,
        "existing_mapping_suggestion_mutations": 0,
        "template_field_mutations": 0,
        "confirmed_tag_id_mutations": 0,
        "final_mapping_mutations": 0,
        "xbrl_generation_count": 0,
        "arelle_runs": 0,
        "auditor_xml_used": False,
        "benchmark_gold_used": False,
    }
    return DocumentInitialMappingResult(
        job_id=job_id,
        filing_id=filing_id,
        source_structure_version=structure.feature_version,
        source_structure_hash=structure_hash,
        source_classification_version=classification.classification_version,
        source_classification_hash=classification_hash,
        registry_version=str(registry.get("semantic_inventory_version") or "mpers-2022-v1"),
        registry_hash=registry_hash,
        taxonomy_version=inventory["taxonomy_version"],
        concept_inventory_hash=inventory["concept_inventory_hash"],
        mapping_version=MAPPING_VERSION,
        total_rows=len(mappings),
        eligible_rows=sum(1 for item in mappings if item.row_eligibility.eligible),
        mapped_rows=decision_counts["mapped"],
        ambiguous_rows=decision_counts["ambiguous"],
        abstained_rows=decision_counts["abstain"],
        no_safe_mapping_rows=decision_counts["no_safe_mapping"],
        structural_rows=decision_counts["structural_only"],
        failed_rows=(
            decision_counts["provider_failed"]
            + decision_counts["validation_failed"]
            + decision_counts["retrieval_failed"]
        ),
        deterministic_candidate_sets=sum(1 for item in mappings if item.candidate_set.candidates),
        llm_calls=llm_calls,
        mappings=mappings,
        conflicts=conflicts,
        warnings=[],
        safety_summary=safety_summary,
        generated_at=timestamp,
    )


def initial_mapping_artifact_path(job_id: int) -> Path:
    resolved_job_id = int(job_id)
    if resolved_job_id <= 0:
        raise ValueError("job_id must be positive")
    path = uploads_root() / ARTIFACT_SUBDIRECTORY / f"job_{resolved_job_id}" / ARTIFACT_FILENAME
    return assert_upload_child(str(path), ARTIFACT_SUBDIRECTORY)


def stale_initial_mapping_artifact_paths(job_id: int) -> list[Path]:
    current = initial_mapping_artifact_path(job_id)
    return [
        assert_upload_child(
            str(current.with_name(filename)),
            ARTIFACT_SUBDIRECTORY,
        )
        for filename in STALE_ARTIFACT_FILENAMES
    ]


def _serialize_initial_mapping(result: DocumentInitialMappingResult) -> str:
    return result.model_dump_json(indent=2)


def _write_initial_mapping_temp(path: Path, payload: str) -> None:
    path.write_text(payload + "\n", encoding="utf-8")


def _replace_initial_mapping_artifact(temporary: Path, path: Path) -> None:
    os.replace(temporary, path)


def _validate_published_initial_mapping(job_id: int) -> None:
    load_initial_mapping(job_id)


def persist_initial_mapping(
    result: DocumentInitialMappingResult,
    *,
    lifecycle_callback: WriterLifecycleCallback | None = None,
) -> Path:
    path = initial_mapping_artifact_path(result.job_id)
    if lifecycle_callback is not None:
        lifecycle_callback("writer_invoked")
    try:
        payload = _serialize_initial_mapping(result)
        if len(payload.encode("utf-8")) > MAX_ARTIFACT_BYTES:
            raise ValueError("Initial mapping artifact exceeds size limit")
    except Exception as exc:
        raise InitialMappingArtifactPersistenceError(
            "artifact_serialization_failed",
            "serialization",
            "Initial mapping artifact serialization failed.",
        ) from exc
    if lifecycle_callback is not None:
        lifecycle_callback("serialization_completed")
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = assert_upload_child(
            str(path.with_name(f".{path.name}.{uuid4().hex}.tmp")),
            ARTIFACT_SUBDIRECTORY,
        )
        _write_initial_mapping_temp(temporary, payload)
        if lifecycle_callback is not None:
            lifecycle_callback("atomic_temp_write_completed")
        _replace_initial_mapping_artifact(temporary, path)
        if lifecycle_callback is not None:
            lifecycle_callback("rename_completed")
    except Exception as exc:
        raise InitialMappingArtifactPersistenceError(
            "artifact_write_failed",
            "atomic_publication",
            "Initial mapping artifact atomic publication failed.",
        ) from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    try:
        _validate_published_initial_mapping(result.job_id)
    except Exception as exc:
        if path.is_file():
            path.unlink()
        raise InitialMappingArtifactPersistenceError(
            "artifact_validation_failed",
            "post_write_validation",
            "Initial mapping artifact post-write validation failed.",
        ) from exc
    if lifecycle_callback is not None:
        lifecycle_callback("post_write_validation_completed")
    return path


def load_initial_mapping(job_id: int) -> DocumentInitialMappingResult:
    path = initial_mapping_artifact_path(job_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("Initial mapping artifact exceeds size limit")
    result = DocumentInitialMappingResult.model_validate_json(path.read_text(encoding="utf-8"))
    structure = load_document_structure(job_id)
    classification = load_template_classification(job_id)
    _cards, inventory = build_taxonomy_concept_inventory()
    registry = load_template_group_registry()
    expected = {
        "job": result.job_id == int(job_id),
        "mapping_version": result.mapping_version == MAPPING_VERSION,
        "structure_version": result.source_structure_version == structure.feature_version,
        "structure_hash": result.source_structure_hash == document_structure_hash(structure),
        "classification_version": result.source_classification_version == classification.classification_version,
        "classification_hash": result.source_classification_hash == template_classification_hash(classification),
        "registry_hash": result.registry_hash == semantic_inventory_sha256(registry),
        "concept_inventory_hash": result.concept_inventory_hash == inventory["concept_inventory_hash"]
        and all(item.concept_inventory_hash == inventory["concept_inventory_hash"] for item in result.mappings),
    }
    if not all(expected.values()):
        failed = sorted(key for key, passed in expected.items() if not passed)
        raise ValueError("Initial mapping artifact is stale or invalid: " + ", ".join(failed))
    return result


def discard_initial_mapping_artifact(job_id: int) -> bool:
    removed = False
    for path in [initial_mapping_artifact_path(job_id), *stale_initial_mapping_artifact_paths(job_id)]:
        if not path.exists():
            continue
        if not path.is_file():
            raise ValueError("Initial mapping artifact path is not a file")
        path.unlink()
        removed = True
    return removed


def initial_mapping_capabilities(job_id: int, *, job_status: str | None = None) -> InitialMappingCapabilitiesRead:
    retrieval_enabled = bool(getattr(settings, "toc_aware_taxonomy_candidate_retrieval_enabled", False))
    mapping_enabled = bool(getattr(settings, "toc_aware_initial_mapping_enabled", False))
    persistence_enabled = bool(getattr(settings, "toc_aware_initial_mapping_persistence_enabled", False))
    live_enabled = bool(getattr(settings, "toc_aware_initial_mapping_live_llm_enabled", False))
    mode = str(getattr(settings, "toc_aware_initial_mapping_mode", "deterministic_only") or "deterministic_only")
    path = initial_mapping_artifact_path(job_id)
    persisted = path.is_file()
    status_value = str(getattr(job_status, "value", job_status) or "").upper()
    status_allowed = not status_value or status_value in ELIGIBLE_JOB_STATUSES
    warnings: list[str] = []
    hashes: dict[str, Any] = {}
    provider_calls = 0
    if persistence_enabled and not (retrieval_enabled and mapping_enabled):
        warnings.append("initial_mapping_persistence_inactive_without_core_features")
    if mode == "live_llm" and not live_enabled:
        warnings.append("live_initial_mapping_mode_blocked_by_flag")
    if persisted:
        try:
            result = load_initial_mapping(job_id)
            hashes = {
                "source_structure_hash": result.source_structure_hash,
                "source_classification_hash": result.source_classification_hash,
                "registry_hash": result.registry_hash,
                "concept_inventory_hash": result.concept_inventory_hash,
            }
            provider_calls = result.llm_calls
        except (FileNotFoundError, ValueError, TypeError):
            warnings.append("initial_mapping_artifact_stale_or_invalid")
    if persisted and not status_allowed:
        warnings.append("initial_mapping_unavailable_for_job_status")
    available = (
        retrieval_enabled
        and mapping_enabled
        and persistence_enabled
        and persisted
        and status_allowed
        and "initial_mapping_artifact_stale_or_invalid" not in warnings
    )
    return InitialMappingCapabilitiesRead(
        mapping_version=MAPPING_VERSION,
        candidate_retrieval_enabled=retrieval_enabled,
        initial_mapping_enabled=mapping_enabled,
        persistence_enabled=persistence_enabled,
        live_llm_enabled=live_enabled,
        mode=mode,
        available=available,
        result_persisted=persisted,
        max_candidates=min(20, max(1, int(getattr(settings, "toc_aware_initial_mapping_max_candidates", 8) or 8))),
        max_rows_per_job=max(1, int(getattr(settings, "toc_aware_initial_mapping_max_rows_per_job", 5000) or 5000)),
        provider_call_count=provider_calls,
        warnings=warnings,
        **hashes,
    )


def initial_mapping_artifact_cleanup_candidate(job_id: int) -> tuple[str, str]:
    return str(initial_mapping_artifact_path(job_id)), ARTIFACT_SUBDIRECTORY


def initial_mapping_artifact_cleanup_candidates(job_id: int) -> list[tuple[str, str]]:
    return [
        initial_mapping_artifact_cleanup_candidate(job_id),
        *(
            (str(path), ARTIFACT_SUBDIRECTORY)
            for path in stale_initial_mapping_artifact_paths(job_id)
        ),
    ]
