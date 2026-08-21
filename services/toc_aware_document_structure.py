"""Versioned, deterministic TOC-aware document structure orchestration."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any, Iterable, Mapping
from uuid import uuid4

from config import settings
from file_safety import assert_upload_child, uploads_root
from schemas import (
    DocumentStructureCapabilitiesRead,
    DocumentStructureResult,
)
from services.document_page_alignment import (
    align_document_pages,
    detect_heading_anchors,
)
from services.document_section_grouper import (
    build_content_evidence,
    build_content_inventory,
    build_document_sections,
    group_document_content,
    summarize_section_range_topology,
    validate_section_page_mapping_consistency,
)
from services.section_title_normalization import normalize_title_text
from services.toc_detection import detect_toc_pages
from services.toc_entry_extractor import extract_toc_entries, infer_toc_page_ranges


FEATURE_VERSION = "19A-v4"
ARTIFACT_SUBDIRECTORY = "document-structures"
ARTIFACT_FILENAME = "structure_19a_v4.json"
MAX_ARTIFACT_BYTES = 25 * 1024 * 1024
MAX_PAGE_TEXT_EVIDENCE_UNITS = 50000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _azure_page_numbers(azure_result: Mapping[str, Any]) -> list[int]:
    values = {
        int(page.get("page_number") or 0)
        for page in azure_result.get("pages") or []
        if int(page.get("page_number") or 0) > 0
    }
    for collection in ("lines", "paragraphs", "table_cells"):
        values.update(
            int(item.get("page_number") or 0)
            for item in azure_result.get(collection) or []
            if int(item.get("page_number") or 0) > 0
        )
    for table in azure_result.get("tables") or []:
        values.update(int(value) for value in table.get("page_numbers") or [] if int(value) > 0)
    return sorted(values)


def _table_row_units(azure_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for fallback_table_index, table in enumerate(azure_result.get("tables") or []):
        table_index = int(
            table.get("table_index")
            if table.get("table_index") is not None
            else fallback_table_index
        )
        rows: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
        for cell in table.get("cells") or []:
            rows[int(cell.get("row_index") or 0)].append(cell)
        for row_index, cells in sorted(rows.items()):
            cells = sorted(cells, key=lambda cell: int(cell.get("column_index") or 0))
            text = _text(" ".join(_text(cell.get("content")) for cell in cells))
            page_number = next(
                (
                    int(cell.get("page_number") or 0)
                    for cell in cells
                    if int(cell.get("page_number") or 0) > 0
                ),
                0,
            )
            if text and page_number > 0:
                if len(units) >= MAX_PAGE_TEXT_EVIDENCE_UNITS:
                    raise ValueError("Page text evidence limit exceeded")
                units.append(
                    {
                        "text": text,
                        "azure_page_number": page_number,
                        "pdf_page_index": page_number - 1,
                        "source_content_id": f"table:{table_index}:row:{row_index}",
                        "source_type": "table_row",
                        "source_group_order": table_index,
                        "source_order": row_index,
                    }
                )
    return units


def build_page_text_evidence(azure_result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Create de-duplicated page text evidence without copying the Azure payload."""
    units = _table_row_units(azure_result)
    for fallback_paragraph_index, paragraph in enumerate(
        azure_result.get("paragraphs") or []
    ):
        page_number = int(paragraph.get("page_number") or 0)
        text = _text(paragraph.get("content"))
        if page_number > 0 and text:
            paragraph_index = int(
                paragraph.get("paragraph_index")
                if paragraph.get("paragraph_index") is not None
                else fallback_paragraph_index
            )
            if len(units) >= MAX_PAGE_TEXT_EVIDENCE_UNITS:
                raise ValueError("Page text evidence limit exceeded")
            units.append(
                {
                    "text": text,
                    "azure_page_number": page_number,
                    "pdf_page_index": page_number - 1,
                    "source_content_id": f"paragraph:{paragraph_index}",
                    "source_type": "paragraph",
                    "source_group_order": 0,
                    "source_order": paragraph_index,
                }
            )

    pages_by_number = {
        int(page.get("page_number") or 0): page
        for page in azure_result.get("pages") or []
        if int(page.get("page_number") or 0) > 0
    }
    line_groups: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for page_number, page in pages_by_number.items():
        line_groups[page_number].extend(page.get("lines") or [])
    for line in azure_result.get("lines") or []:
        page_number = int(line.get("page_number") or 0)
        if page_number > 0 and line not in line_groups[page_number]:
            line_groups[page_number].append(line)
    for page_number, lines in sorted(line_groups.items()):
        for index, line in enumerate(lines):
            text = _text(line.get("content"))
            if text:
                if len(units) >= MAX_PAGE_TEXT_EVIDENCE_UNITS:
                    raise ValueError("Page text evidence limit exceeded")
                units.append(
                    {
                        "text": text,
                        "azure_page_number": page_number,
                        "pdf_page_index": page_number - 1,
                        "source_content_id": f"page:{page_number}:line:{index}",
                        "source_type": "line",
                        "source_group_order": 0,
                        "source_order": index,
                    }
                )

    # Prefer table rows, then paragraphs, then lines. Azure often exposes the
    # same visible text through more than one representation.
    priority = {"table_row": 0, "paragraph": 1, "line": 2}
    units.sort(
        key=lambda unit: (
            int(unit["pdf_page_index"]),
            priority.get(str(unit["source_type"]), 9),
            int(unit.get("source_group_order") or 0),
            int(unit.get("source_order") or 0),
            str(unit["source_content_id"]),
        )
    )
    seen: set[tuple[int, str]] = set()
    deduplicated = []
    for unit in units:
        key = (int(unit["pdf_page_index"]), normalize_title_text(unit["text"]))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        deduplicated.append(unit)

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for unit in deduplicated:
        grouped[int(unit["azure_page_number"])].append(unit)
    return [
        {
            "azure_page_number": page_number,
            "pdf_page_index": page_number - 1,
            "lines": grouped.get(page_number, []),
        }
        for page_number in _azure_page_numbers(azure_result)
    ]


def _structure_warnings(
    *,
    detection_warnings: Iterable[str],
    entry_warnings: Iterable[str],
    alignment_warnings: Iterable[str],
    sections,
    unassigned_count: int,
) -> list[str]:
    warnings = [*detection_warnings, *entry_warnings, *alignment_warnings]
    if any("overlapping_section_ranges" in section.warnings for section in sections):
        warnings.append("overlapping_section_ranges")
    if any("heading_anchor_missing" in section.warnings for section in sections):
        warnings.append("heading_anchor_missing")
    if any(
        "heading_anchor_same_page_near_tie" in section.warnings
        for section in sections
    ):
        warnings.append("heading_anchor_same_page_near_tie")
    if any(
        "section_range_conflicts_with_page_mapping" in section.warnings
        for section in sections
    ):
        warnings.append("section_range_conflicts_with_page_mapping")
    if unassigned_count:
        warnings.append("unassigned_document_content")
    return list(dict.fromkeys(str(item) for item in warnings if str(item)))


def analyze_document_structure(
    *,
    job_id: int,
    azure_result: Mapping[str, Any],
    normalized_candidates: Iterable[Mapping[str, Any]],
    generated_at: datetime | None = None,
) -> DocumentStructureResult:
    candidates = [dict(candidate) for candidate in normalized_candidates]
    azure_page_numbers = _azure_page_numbers(azure_result)
    final_azure_page_number = max(azure_page_numbers, default=0)
    page_evidence = build_page_text_evidence(azure_result)
    detection = detect_toc_pages(page_evidence)
    toc_pages = list(detection.candidate_page_indexes)
    source_lines = [
        unit
        for page in page_evidence
        if int(page["pdf_page_index"]) in set(toc_pages)
        for unit in page.get("lines") or []
    ]
    parsed_entries = extract_toc_entries(source_lines) if detection.detected else []
    for entry in parsed_entries:
        if (
            entry.printed_page_start is not None
            and entry.printed_page_start > final_azure_page_number
        ):
            entry.parse_warnings = list(
                dict.fromkeys(
                    [
                        *entry.parse_warnings,
                        "printed_page_start_outside_document",
                    ]
                )
            )
            entry.confidence = round(entry.confidence * 0.5, 4)
    boundary_entries = [
        entry
        for entry in parsed_entries
        if entry.printed_page_start is not None
        and entry.printed_page_start <= final_azure_page_number
    ]
    anchors = detect_heading_anchors(
        boundary_entries,
        azure_result,
        toc_page_indexes=toc_pages,
    )
    alignment = align_document_pages(
        boundary_entries,
        anchors,
        azure_page_numbers=azure_page_numbers,
    )
    entries = infer_toc_page_ranges(
        parsed_entries,
        final_printed_page=alignment.final_printed_page,
        final_numbering_scheme=alignment.final_numbering_scheme,
    )
    section_entries = [
        entry
        for entry in entries
        if entry.printed_page_start is not None
        and entry.printed_page_start <= final_azure_page_number
    ]
    sections = build_document_sections(job_id, section_entries, anchors, alignment)
    consistency = validate_section_page_mapping_consistency(sections, alignment)
    range_topology = summarize_section_range_topology(sections)
    inventory = build_content_inventory(azure_result, candidates)
    unassigned, ambiguous, conservation = group_document_content(
        sections,
        inventory,
        anchors,
        toc_page_indexes=toc_pages,
    )
    content_evidence = build_content_evidence(inventory)

    entry_warning_codes = [
        warning
        for entry in entries
        for warning in entry.parse_warnings
        if warning in {
            "page_reference_unparsed",
            "printed_page_start_invalid",
            "printed_page_range_reversed",
            "printed_page_start_outside_document",
        }
    ]
    if detection.detected and not entries:
        entry_warning_codes.append("toc_parse_low_confidence")
    warnings = _structure_warnings(
        detection_warnings=detection.warnings,
        entry_warnings=entry_warning_codes,
        alignment_warnings=alignment.warnings,
        sections=sections,
        unassigned_count=sum(
            1
            for item in unassigned
            if item.reason != "toc_page_excluded"
        ),
    )
    toc_excluded_count = sum(
        1
        for item in unassigned
        if item.reason == "toc_page_excluded"
    )
    eligible_content_count = max(
        0,
        int(conservation["content_inventory_count"]) - toc_excluded_count,
    )
    non_toc_unassigned_count = sum(
        1
        for item in unassigned
        if item.reason != "toc_page_excluded"
    )
    explicit_range_projection_success_count = sum(
        1
        for section in sections
        if section.provenance.get("range_method") == "explicit_range"
        and section.pdf_page_start is not None
        and section.pdf_page_end is not None
        and bool(section.provenance.get("authoritative_page_mapping"))
    )
    resolved_range_projection_success_count = sum(
        1
        for section in sections
        if section.printed_page_start is not None
        and section.printed_page_end is not None
        and section.pdf_page_start is not None
        and section.pdf_page_end is not None
        and bool(section.provenance.get("authoritative_page_mapping"))
    )
    safety_summary = {
        **conservation,
        **consistency,
        **range_topology,
        "content_evidence_count": len(content_evidence),
        "toc_excluded_content_count": toc_excluded_count,
        "content_inventory_excluding_toc_count": eligible_content_count,
        "unassigned_content_excluding_toc_count": non_toc_unassigned_count,
        "assignment_rate_excluding_toc": round(
            int(conservation["assigned_content_count"])
            / max(1, eligible_content_count),
            6,
        ),
        "unassigned_rate_excluding_toc": round(
            non_toc_unassigned_count / max(1, eligible_content_count),
            6,
        ),
        "explicit_range_projection_success_count": explicit_range_projection_success_count,
        "resolved_range_projection_success_count": resolved_range_projection_success_count,
        "deterministic_local_analysis": True,
        "structure_algorithm_version": FEATURE_VERSION,
        "azure_provider_calls_made": 0,
        "llm_calls_made": 0,
        "supervisor_calls_made": 0,
        "source_extraction_mutated": False,
        "statement_assignments_mutated": False,
        "mapping_suggestions_mutated": False,
        "confirmed_tag_id_mutations": 0,
        "final_mapping_mutations": 0,
        "xbrl_generated": False,
        "arelle_run": False,
    }
    return DocumentStructureResult(
        job_id=job_id,
        document_id=f"filing-job-{job_id}",
        feature_version=FEATURE_VERSION,
        toc_detected=detection.detected,
        toc_page_indexes=toc_pages,
        toc_confidence=detection.confidence,
        toc_detection=detection.to_dict(),
        page_mapping_confidence=alignment.confidence,
        page_alignment_summary=alignment.to_dict(),
        section_count=len(sections),
        toc_entries=entries,
        heading_anchors=anchors,
        page_mappings=list(alignment.page_mappings),
        sections=sections,
        content_evidence=content_evidence,
        unassigned_content=unassigned,
        ambiguous_content=ambiguous,
        warnings=warnings,
        safety_summary=safety_summary,
        generated_at=generated_at or _utc_now(),
    )


def attach_persisted_extracted_row_ids(
    result: DocumentStructureResult,
    item_ids_by_original_candidate: Mapping[str, str],
) -> DocumentStructureResult:
    updated = result.model_copy(deep=True)
    original_references = [
        reference
        for section in updated.sections
        for reference in section.extracted_row_ids
    ]
    original_references.extend(
        disposition.content_id
        for disposition in [*updated.unassigned_content, *updated.ambiguous_content]
        if disposition.content_type == "extracted_row"
    )
    resolved_count = sum(
        1
        for reference in original_references
        if reference in item_ids_by_original_candidate
    )
    for section in updated.sections:
        section.extracted_row_ids = [
            str(item_ids_by_original_candidate.get(reference, reference))
            for reference in section.extracted_row_ids
        ]
    for evidence in updated.content_evidence:
        if evidence.content_type != "extracted_row":
            continue
        original = str(
            evidence.provenance.get("original_candidate_id")
            or evidence.content_id
        )
        evidence.provenance["original_candidate_id"] = original
        evidence.content_id = str(
            item_ids_by_original_candidate.get(original, evidence.content_id)
        )
    for disposition in [*updated.unassigned_content, *updated.ambiguous_content]:
        if disposition.content_type != "extracted_row":
            continue
        original = str(disposition.provenance.get("original_candidate_id") or disposition.content_id)
        disposition.content_id = str(item_ids_by_original_candidate.get(original, disposition.content_id))
    updated.safety_summary["persisted_extracted_row_reference_count"] = resolved_count
    updated.safety_summary["unresolved_extracted_row_reference_count"] = (
        len(original_references) - resolved_count
    )
    return updated


def document_structure_artifact_path(job_id: int) -> Path:
    resolved_job_id = int(job_id)
    if resolved_job_id <= 0:
        raise ValueError("job_id must be positive")
    path = uploads_root() / ARTIFACT_SUBDIRECTORY / f"job_{resolved_job_id}" / ARTIFACT_FILENAME
    return assert_upload_child(str(path), ARTIFACT_SUBDIRECTORY)


def persist_document_structure(result: DocumentStructureResult) -> Path:
    path = document_structure_artifact_path(result.job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = assert_upload_child(
        str(path.with_name(f".{path.name}.{uuid4().hex}.tmp")),
        ARTIFACT_SUBDIRECTORY,
    )
    payload = result.model_dump_json(indent=2)
    if len(payload.encode("utf-8")) > MAX_ARTIFACT_BYTES:
        raise ValueError("Document structure artifact exceeds size limit")
    try:
        temporary.write_text(payload + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return path


def load_document_structure(job_id: int) -> DocumentStructureResult:
    path = document_structure_artifact_path(job_id)
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("Document structure artifact exceeds size limit")
    result = DocumentStructureResult.model_validate_json(path.read_text(encoding="utf-8"))
    if result.job_id != int(job_id) or result.feature_version != FEATURE_VERSION:
        raise ValueError("Document structure artifact identity mismatch")
    return result


def discard_document_structure_artifact(job_id: int) -> bool:
    """Remove only the fixed derived artifact for a job, if it exists."""
    path = document_structure_artifact_path(job_id)
    if not path.exists():
        return False
    if not path.is_file():
        raise ValueError("Document structure artifact path is not a file")
    path.unlink()
    return True


def document_structure_capabilities(
    job_id: int,
    *,
    job_status: str | None = None,
) -> DocumentStructureCapabilitiesRead:
    enabled = bool(getattr(settings, "toc_aware_pipeline_enabled", False))
    persistence_enabled = bool(
        getattr(settings, "toc_aware_structure_persistence_enabled", False)
    )
    llm_fallback_enabled = bool(
        getattr(settings, "toc_aware_llm_fallback_enabled", False)
    )
    persisted = document_structure_artifact_path(job_id).is_file()
    resolved_job_status = getattr(job_status, "value", job_status)
    status_allows_result = (
        job_status is None
        or str(resolved_job_status).upper() in {"REVIEW", "COMPLETED"}
    )
    warnings: list[str] = []
    if persistence_enabled and not enabled:
        warnings.append("structure_persistence_inactive_without_pipeline")
    if llm_fallback_enabled:
        warnings.append("toc_aware_llm_fallback_not_implemented")
    if enabled and persistence_enabled and not persisted:
        warnings.append("document_structure_not_generated")
    if persisted and not status_allows_result:
        warnings.append("document_structure_unavailable_for_job_status")
    return DocumentStructureCapabilitiesRead(
        feature_version=FEATURE_VERSION,
        enabled=enabled,
        persistence_enabled=persistence_enabled,
        llm_fallback_enabled=llm_fallback_enabled,
        llm_fallback_implemented=False,
        available=enabled and persistence_enabled and persisted and status_allows_result,
        result_persisted=persisted,
        warnings=warnings,
    )


def artifact_cleanup_candidate(job_id: int) -> tuple[str, str]:
    return str(document_structure_artifact_path(job_id)), ARTIFACT_SUBDIRECTORY
