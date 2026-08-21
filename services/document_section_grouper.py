"""Build document sections and conservatively group Azure DI content."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Iterable, Mapping

from schemas import (
    DocumentContentEvidence,
    DocumentContentDisposition,
    DocumentSection,
    HeadingAnchor,
    TocEntry,
)
from services.document_page_alignment import PageAlignmentResult
from services.section_title_normalization import UNKNOWN_SECTION, normalize_section_title


NOTE_HEADING_RE = re.compile(
    r"^\s*(?:note\s+)?\d{1,3}[A-Za-z]?\s*[.)\-:]\s+\S+",
    re.I,
)
MAX_CONTENT_INVENTORY_ITEMS = 125000
MAX_GROUPING_COMPARISONS = 5_000_000


def _compact_regions(regions: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for region in regions:
        if not isinstance(region, Mapping):
            continue
        compact: dict[str, Any] = {}
        try:
            page_number = int(region.get("page_number") or 0)
        except (TypeError, ValueError):
            page_number = 0
        if page_number > 0:
            compact["page_number"] = page_number
        polygon = region.get("polygon")
        if isinstance(polygon, list):
            compact["polygon"] = list(polygon)
        if compact:
            evidence.append(compact)
    return evidence


def _polygon_top(value: Any) -> float | None:
    if not isinstance(value, list) or not value:
        return None
    first = value[0]
    if isinstance(first, Mapping):
        try:
            return float(first.get("y"))
        except (TypeError, ValueError):
            return None
    if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
        return float(value[1])
    return None


def _regions_top(regions: Iterable[Mapping[str, Any]]) -> float | None:
    values = [_polygon_top(region.get("polygon")) for region in regions]
    values = [value for value in values if value is not None]
    return min(values) if values else None


def _candidate_top(candidate: Mapping[str, Any]) -> float | None:
    provenance = candidate.get("provenance") or {}
    cells = provenance.get("cells") or []
    values = [
        _regions_top(cell.get("bounding_regions") or [])
        for cell in cells
        if isinstance(cell, Mapping)
    ]
    values.extend(
        [
            _regions_top(provenance.get("bounding_regions") or []),
            _polygon_top(provenance.get("line_polygon") or []),
        ]
    )
    values = [value for value in values if value is not None]
    return min(values) if values else None


def _candidate_reference(candidate: Mapping[str, Any], index: int) -> str:
    return str(
        candidate.get("original_candidate_id")
        or candidate.get("candidate_id")
        or f"normalized-row:{index}"
    )


def build_content_inventory(
    azure_result: Mapping[str, Any],
    normalized_candidates: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []

    def add_inventory_item(item: dict[str, Any]) -> None:
        if len(inventory) >= MAX_CONTENT_INVENTORY_ITEMS:
            raise ValueError("Document content inventory limit exceeded")
        inventory.append(item)

    pages_by_number = {
        int(page.get("page_number") or 0): page
        for page in azure_result.get("pages") or []
        if int(page.get("page_number") or 0) > 0
    }

    for fallback_paragraph_index, paragraph in enumerate(
        azure_result.get("paragraphs") or []
    ):
        page_number = int(paragraph.get("page_number") or 0)
        paragraph_index = int(
            paragraph.get("paragraph_index")
            if paragraph.get("paragraph_index") is not None
            else fallback_paragraph_index
        )
        role = str(paragraph.get("role") or "")
        content_type = "heading" if role.lower() in {
            "title", "sectionheading", "section_heading", "heading"
        } else "paragraph"
        regions = list(paragraph.get("bounding_regions") or [])
        add_inventory_item(
            {
                "content_id": f"paragraph:{paragraph_index}",
                "content_type": content_type,
                "text": str(paragraph.get("content") or ""),
                "azure_page_numbers": [page_number] if page_number > 0 else [],
                "pdf_page_indexes": [page_number - 1] if page_number > 0 else [],
                "top": _regions_top(regions),
                "bounding_evidence": _compact_regions(regions),
                "provenance": {
                    "source": "azure_di_paragraph",
                    "paragraph_index": paragraph_index,
                    "role": role or None,
                },
            }
        )

    line_groups: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for page_number, page in pages_by_number.items():
        line_groups[page_number].extend(page.get("lines") or [])
    for line in azure_result.get("lines") or []:
        page_number = int(line.get("page_number") or 0)
        if page_number > 0 and line not in line_groups[page_number]:
            line_groups[page_number].append(line)
    for page_number, lines in sorted(line_groups.items()):
        for line_index, line in enumerate(lines):
            text = " ".join(str(line.get("content") or "").split())
            normalized = normalize_section_title(text)
            letters = [char for char in text if char.isalpha()]
            uppercase = bool(letters) and sum(char.isupper() for char in letters) / len(letters) >= 0.8
            content_type = (
                "heading"
                if normalized.canonical_section_type != UNKNOWN_SECTION
                or (uppercase and len(text) <= 160)
                else "text_block"
            )
            add_inventory_item(
                {
                    "content_id": f"page:{page_number}:line:{line_index}",
                    "content_type": content_type,
                    "text": text,
                    "azure_page_numbers": [page_number],
                    "pdf_page_indexes": [page_number - 1],
                    "top": _polygon_top(line.get("polygon") or []),
                    "bounding_evidence": _compact_regions(
                        [
                            {
                                "page_number": page_number,
                                "polygon": line.get("polygon") or [],
                            }
                        ]
                    ),
                    "provenance": {
                        "source": "azure_di_line",
                        "line_index": line_index,
                        "span_count": len(line.get("spans") or []),
                    },
                }
            )

    for fallback_table_index, table in enumerate(azure_result.get("tables") or []):
        table_index = int(
            table.get("table_index")
            if table.get("table_index") is not None
            else fallback_table_index
        )
        page_numbers = sorted(
            {
                int(value)
                for value in table.get("page_numbers") or []
                if int(value) > 0
            }
        )
        if not page_numbers:
            page_numbers = sorted(
                {
                    int(cell.get("page_number") or 0)
                    for cell in table.get("cells") or []
                    if int(cell.get("page_number") or 0) > 0
                }
            )
        regions = list(table.get("bounding_regions") or [])
        add_inventory_item(
            {
                "content_id": f"table:{table_index}",
                "content_type": "table",
                "text": "",
                "azure_page_numbers": page_numbers,
                "pdf_page_indexes": [value - 1 for value in page_numbers],
                "top": _regions_top(regions),
                "bounding_evidence": _compact_regions(regions),
                "provenance": {
                    "source": "azure_di_table",
                    "table_index": table_index,
                    "row_count": int(table.get("row_count") or 0),
                    "column_count": int(table.get("column_count") or 0),
                },
            }
        )
        for cell_index, cell in enumerate(table.get("cells") or []):
            page_number = int(cell.get("page_number") or 0)
            cell_regions = list(cell.get("bounding_regions") or [])
            row_index = int(cell.get("row_index") or 0)
            column_index = int(cell.get("column_index") or 0)
            add_inventory_item(
                {
                    "content_id": f"table:{table_index}:r{row_index}:c{column_index}",
                    "content_type": "table_cell",
                    "text": str(cell.get("content") or ""),
                    "azure_page_numbers": [page_number] if page_number > 0 else [],
                    "pdf_page_indexes": [page_number - 1] if page_number > 0 else [],
                    "top": _regions_top(cell_regions),
                    "bounding_evidence": _compact_regions(cell_regions),
                    "provenance": {
                        "source": "azure_di_table_cell",
                        "table_index": table_index,
                        "cell_index": cell_index,
                        "row_index": row_index,
                        "column_index": column_index,
                        "kind": cell.get("kind"),
                    },
                }
            )

    for index, candidate in enumerate(normalized_candidates):
        page_number = int(candidate.get("page_number") or 0)
        reference = _candidate_reference(candidate, index)
        candidate_provenance = candidate.get("provenance") or {}
        candidate_regions: list[Mapping[str, Any]] = list(
            candidate_provenance.get("bounding_regions") or []
        )
        for cell in candidate_provenance.get("cells") or []:
            if isinstance(cell, Mapping):
                candidate_regions.extend(cell.get("bounding_regions") or [])
        line_polygon = candidate_provenance.get("line_polygon") or []
        if line_polygon and page_number > 0:
            candidate_regions.append(
                {"page_number": page_number, "polygon": line_polygon}
            )
        add_inventory_item(
            {
                "content_id": reference,
                "content_type": "extracted_row",
                "text": str(
                    candidate.get("label")
                    or candidate.get("text")
                    or candidate.get("source_snippet")
                    or ""
                ),
                "azure_page_numbers": [page_number] if page_number > 0 else [],
                "pdf_page_indexes": [page_number - 1] if page_number > 0 else [],
                "top": _candidate_top(candidate),
                "bounding_evidence": _compact_regions(candidate_regions),
                "provenance": {
                    "source": "normalized_azure_di_candidate",
                    "original_candidate_id": reference,
                    "row_type": candidate.get("row_type"),
                    "table_index": candidate_provenance.get("table_index"),
                    "row_index": candidate_provenance.get("row_index"),
                    "paragraph_index": candidate_provenance.get("paragraph_index"),
                },
            }
        )
    return inventory


def build_content_evidence(
    inventory: Iterable[Mapping[str, Any]],
) -> list[DocumentContentEvidence]:
    """Make artifact references self-contained without copying the Azure payload."""
    return [
        DocumentContentEvidence(
            content_id=str(item["content_id"]),
            content_type=str(item["content_type"]),
            text_evidence=str(item.get("text") or "") or None,
            pdf_page_indexes=[
                int(value) for value in item.get("pdf_page_indexes") or []
            ],
            azure_page_numbers=[
                int(value) for value in item.get("azure_page_numbers") or []
            ],
            bounding_evidence=list(item.get("bounding_evidence") or []),
            provenance=dict(item.get("provenance") or {}),
        )
        for item in inventory
    ]


def build_document_sections(
    job_id: int,
    entries: Iterable[TocEntry],
    anchors: Iterable[HeadingAnchor],
    alignment: PageAlignmentResult,
) -> list[DocumentSection]:
    rows = list(entries)
    trusted_anchors_by_entry = {
        anchor.toc_entry_id: anchor
        for anchor in anchors
        if anchor.trusted
    }
    anchors_by_entry = {
        anchor.toc_entry_id: anchor
        for anchor in anchors
        if anchor.trusted and "heading_anchor_near_tie" not in anchor.warnings
    }
    mappings_by_printed: dict[int, list[Any]] = defaultdict(list)
    for mapping in alignment.page_mappings:
        if mapping.printed_page_number is not None:
            mappings_by_printed[mapping.printed_page_number].append(mapping)
    mappings_by_pdf = {
        mapping.pdf_page_index: mapping
        for mapping in alignment.page_mappings
    }
    sections: list[DocumentSection] = []
    reliable_alignment = (
        alignment.confidence >= 0.80
        and not alignment.requires_human_review
        and alignment.mapping_method
        in {"weighted_heading_anchor_consensus", "heading_anchor_piecewise"}
    )
    unsafe_range_projection = not reliable_alignment

    for order, entry in enumerate(rows):
        anchor = anchors_by_entry.get(entry.entry_id)
        geometry_anchor = trusted_anchors_by_entry.get(entry.entry_id)
        warnings = list(entry.parse_warnings)
        if anchor is not None:
            warnings.extend(anchor.warnings)
        start = None
        end = None
        selected_offset = None
        grouping_method = "toc_page_range"
        authoritative_projection = False

        start_candidates = list(
            mappings_by_printed.get(entry.printed_page_start, [])
        )
        end_candidates = list(
            mappings_by_printed.get(entry.printed_page_end, [])
        )
        if (
            reliable_alignment
            and entry.printed_page_start is not None
            and entry.printed_page_end is not None
            and len(start_candidates) == 1
            and len(end_candidates) == 1
            and start_candidates[0].offset == end_candidates[0].offset
            and end_candidates[0].pdf_page_index >= start_candidates[0].pdf_page_index
        ):
            start = start_candidates[0].pdf_page_index
            end = end_candidates[0].pdf_page_index
            selected_offset = start_candidates[0].offset
            authoritative_projection = True
            grouping_method = "authoritative_toc_page_mapping"

        if (
            authoritative_projection
            and geometry_anchor is not None
            and geometry_anchor.pdf_page_index == start
        ):
            anchor = geometry_anchor
            warnings.extend(anchor.warnings)

        if anchor is not None:
            anchor_mapping = mappings_by_pdf.get(anchor.pdf_page_index)
            if (
                anchor_mapping is not None
                and entry.printed_page_start is not None
                and anchor_mapping.printed_page_number is not None
                and anchor_mapping.printed_page_number != entry.printed_page_start
            ):
                warnings.append("toc_anchor_page_mismatch")
            if authoritative_projection:
                if anchor.pdf_page_index != start:
                    warnings.append("heading_anchor_outside_authoritative_range")
                else:
                    grouping_method = "authoritative_toc_page_mapping_with_heading_confirmation"
            else:
                start = anchor.pdf_page_index
                if entry.printed_page_start is not None:
                    selected_offset = anchor.pdf_page_index - entry.printed_page_start
                grouping_method = "toc_page_range_with_heading_anchor"
        elif not authoritative_projection:
            warnings.append("heading_anchor_missing")
            if len(start_candidates) == 1:
                start_mapping = start_candidates[0]
                start = start_mapping.pdf_page_index
                selected_offset = start_mapping.offset
            elif len(start_candidates) > 1:
                warnings.append("duplicate_printed_page_mapping")

        if (
            not authoritative_projection
            and entry.printed_page_end is not None
            and start is not None
        ):
            if entry.printed_page_end == entry.printed_page_start:
                end = start
            elif selected_offset is not None:
                end_candidates = [
                    mapping
                    for mapping in mappings_by_printed.get(
                        entry.printed_page_end,
                        [],
                    )
                    if mapping.offset == selected_offset
                    and mapping.pdf_page_index >= start
                ]
                if len(end_candidates) == 1:
                    end = end_candidates[0].pdf_page_index
                elif len(end_candidates) > 1:
                    warnings.append("duplicate_printed_page_mapping")
                else:
                    warnings.append(
                        "printed_page_end_not_mapped_in_anchor_regime"
                    )

        if unsafe_range_projection and not authoritative_projection:
            # Exact anchors remain useful evidence, but ambiguous offsets must
            # not project broad page ranges.
            end = start if anchor is not None else None
            grouping_method = "heading_anchor_only_ambiguous_alignment"
        elif (
            start is not None
            and end is None
            and entry.printed_page_end is None
        ):
            later_starts = [
                value
                for later in rows[order + 1:]
                for value in [
                    (
                        anchors_by_entry[later.entry_id].pdf_page_index
                        if later.entry_id in anchors_by_entry
                        else (
                            mappings_by_printed[later.printed_page_start][0].pdf_page_index
                            if later.printed_page_start in mappings_by_printed
                            and len(mappings_by_printed[later.printed_page_start]) == 1
                            else None
                        )
                    )
                ]
                if value is not None and value >= start
            ]
            if later_starts:
                next_start = min(later_starts)
                end = next_start if next_start == start else next_start - 1
                warnings.append("pdf_page_end_inferred_from_next_section")
            else:
                available_pages = [mapping.pdf_page_index for mapping in alignment.page_mappings]
                end = max(available_pages) if available_pages else start
                warnings.append("pdf_page_end_inferred_from_document_end")

        if start is not None and end is not None and end < start:
            warnings.append("invalid_pdf_page_range")
            end = None
        confidence_parts = [entry.confidence, alignment.confidence]
        if anchor is not None:
            confidence_parts.append(anchor.match_score)
        confidence = sum(confidence_parts) / len(confidence_parts)
        if start is None or end is None:
            confidence *= 0.55
        requires_review = (
            confidence < 0.7
            or entry.canonical_section_hint == UNKNOWN_SECTION
            or (anchor is None and not authoritative_projection)
            or (alignment.requires_human_review and not authoritative_projection)
            or bool(
                anchor
                and anchor.warnings
                and not (
                    authoritative_projection
                    and anchor.pdf_page_index == start
                    and set(anchor.warnings).issubset(
                        {
                            "heading_anchor_near_tie",
                            "heading_anchor_same_page_near_tie",
                        }
                    )
                )
            )
            or start is None
            or end is None
        )
        sections.append(
            DocumentSection(
                section_id=f"section-{order + 1}",
                job_id=job_id,
                raw_title=entry.raw_title,
                normalized_title=entry.normalized_title,
                canonical_section_type=entry.canonical_section_hint,
                toc_entry_id=entry.entry_id,
                parent_section_id=None,
                section_level=1,
                section_order=order,
                printed_page_start=entry.printed_page_start,
                printed_page_end=entry.printed_page_end,
                pdf_page_start=start,
                pdf_page_end=end,
                azure_page_start=start + 1 if start is not None else None,
                azure_page_end=end + 1 if end is not None else None,
                heading_anchor_page=anchor.pdf_page_index if anchor else None,
                heading_anchor_id=anchor.anchor_id if anchor else None,
                start_heading_bbox=(
                    list(anchor.bounding_evidence) if anchor else []
                ),
                start_heading_offset=_anchor_top(anchor),
                confidence=round(max(0.0, min(1.0, confidence)), 4),
                grouping_method=grouping_method,
                requires_human_review=requires_review,
                warnings=list(dict.fromkeys(warnings)),
                provenance={
                    "range_method": entry.range_method,
                    "page_alignment_method": alignment.mapping_method,
                    "heading_anchor_match_method": anchor.match_method if anchor else None,
                    "authoritative_page_mapping": authoritative_projection,
                    "page_range_source": (
                        "toc_endpoint_page_mapping"
                        if authoritative_projection
                        else grouping_method
                    ),
                    "start_boundary_source": (
                        "mapped_toc_start"
                        if authoritative_projection
                        else "heading_anchor" if anchor else None
                    ),
                    "end_boundary_source": (
                        "mapped_toc_end"
                        if authoritative_projection
                        else "mapped_or_inferred_end"
                    ),
                    "heading_geometry_separate_from_page_range": True,
                },
            )
        )

    for left_index, left in enumerate(sections):
        if left.pdf_page_start is None or left.pdf_page_end is None:
            continue
        for right in sections[left_index + 1:]:
            if right.pdf_page_start is None or right.pdf_page_end is None:
                continue
            overlap_start = max(left.pdf_page_start, right.pdf_page_start)
            overlap_end = min(left.pdf_page_end, right.pdf_page_end)
            if overlap_start > overlap_end:
                continue
            left_anchor = trusted_anchors_by_entry.get(left.toc_entry_id)
            right_anchor = trusted_anchors_by_entry.get(right.toc_entry_id)
            left_top = _anchor_top(left_anchor)
            right_top = _anchor_top(right_anchor)
            legitimate_same_page_boundary = (
                overlap_start == overlap_end
                and left.pdf_page_end == right.pdf_page_start
                and left_anchor is not None
                and right_anchor is not None
                and left_anchor.pdf_page_index == overlap_start
                and right_anchor.pdf_page_index == overlap_start
                and left_top is not None
                and right_top is not None
                and left_top != right_top
            )
            if legitimate_same_page_boundary:
                left.end_heading_bbox = list(right_anchor.bounding_evidence)
                left.end_heading_offset = right_top
                left.provenance["end_boundary_source"] = (
                    "next_section_heading_geometry"
                )
                left.provenance["same_page_boundary_pdf_page"] = overlap_start
                right.provenance["same_page_boundary_pdf_page"] = overlap_start
                continue
            if overlap_start <= overlap_end:
                left.warnings = list(dict.fromkeys([*left.warnings, "overlapping_section_ranges"]))
                right.warnings = list(dict.fromkeys([*right.warnings, "overlapping_section_ranges"]))
                left.requires_human_review = True
                right.requires_human_review = True
    return sections


def validate_section_page_mapping_consistency(
    sections: Iterable[DocumentSection],
    alignment: PageAlignmentResult,
) -> dict[str, Any]:
    """Reconcile unique mapped ranges and fail closed on unresolved contradictions."""
    mappings_by_printed: dict[int, list[Any]] = defaultdict(list)
    for mapping in alignment.page_mappings:
        if mapping.printed_page_number is not None:
            mappings_by_printed[mapping.printed_page_number].append(mapping)
    detected = 0
    reconciled = 0
    unresolved = 0
    validated = 0
    conflict_details: list[dict[str, Any]] = []

    def projection_is_reliable(start_mapping, end_mapping) -> bool:
        regimes = list(getattr(alignment, "regimes", ()) or ())
        matching_regimes = [
            regime
            for regime in regimes
            if int(regime.get("offset")) == int(start_mapping.offset)
            and int(regime.get("supporting_anchor_count") or 0) >= 2
            and float(regime.get("weighted_support_ratio") or 1.0) >= 0.72
        ]
        return (
            alignment.confidence >= 0.80
            and getattr(
                alignment,
                "mapping_method",
                getattr(start_mapping, "mapping_method", ""),
            )
            in {"weighted_heading_anchor_consensus", "heading_anchor_piecewise"}
            and start_mapping.confidence >= 0.80
            and end_mapping.confidence >= 0.80
            and getattr(alignment, "competing_high_quality_offset_count", 0) == 0
            and (
                bool(matching_regimes)
                or (
                    not regimes
                    and not bool(getattr(alignment, "requires_human_review", True))
                )
            )
            and "single_heading_anchor" not in getattr(alignment, "warnings", ())
            and "inconsistent_heading_anchors" not in getattr(
                alignment, "warnings", ()
            )
        )

    for section in sections:
        if section.printed_page_start is None or section.printed_page_end is None:
            continue
        starts = mappings_by_printed.get(section.printed_page_start, [])
        ends = mappings_by_printed.get(section.printed_page_end, [])
        endpoints_unresolved = (
            len(starts) != 1
            or len(ends) != 1
            or starts[0].offset != ends[0].offset
            or ends[0].pdf_page_index < starts[0].pdf_page_index
        )
        if endpoints_unresolved:
            section.range_consistency = {
                "status": "unresolved",
                "expected_pdf_range": None,
                "observed_pdf_range": [
                    section.pdf_page_start,
                    section.pdf_page_end,
                ],
                "conflict_dimensions": ["missing_endpoint_mapping"],
                "observed_boundary_sources": {
                    "start": section.provenance.get("start_boundary_source"),
                    "end": section.provenance.get("end_boundary_source"),
                },
                "safe_reconciliation": False,
            }
            section.pdf_page_start = None
            section.pdf_page_end = None
            section.azure_page_start = None
            section.azure_page_end = None
            section.requires_human_review = True
            section.grouping_method = "unresolved_page_mapping_conflict"
            section.warnings = list(
                dict.fromkeys(
                    [*section.warnings, "section_range_conflicts_with_page_mapping"]
                )
            )
            detected += 1
            unresolved += 1
            conflict_details.append(
                {
                    "section_id": section.section_id,
                    "expected_pdf_range": None,
                    "observed_pdf_range": section.range_consistency[
                        "observed_pdf_range"
                    ],
                    "conflict_dimensions": ["missing_endpoint_mapping"],
                    "safe_reconciliation": False,
                    "status": "unresolved",
                }
            )
            continue
        expected_start = starts[0].pdf_page_index
        expected_end = ends[0].pdf_page_index
        observed_start = section.pdf_page_start
        observed_end = section.pdf_page_end
        conflict_dimensions: list[str] = []
        if observed_start != expected_start:
            conflict_dimensions.append("start_page_conflict")
        if observed_end != expected_end:
            conflict_dimensions.append("end_page_conflict")
        if (
            observed_start is not None
            and observed_end is not None
            and observed_start == observed_end
            and expected_start < expected_end
        ):
            conflict_dimensions.append("range_collapsed")
        if (
            section.heading_anchor_page is not None
            and section.printed_page_start is not None
            and section.heading_anchor_page - section.printed_page_start
            != starts[0].offset
        ):
            conflict_dimensions.append("off_regime_anchor")
        if "overlapping_section_ranges" in section.warnings:
            conflict_dimensions.append("overlapping_section_range")
        safe_reconciliation = projection_is_reliable(starts[0], ends[0])
        base_consistency = {
            "expected_pdf_range": [expected_start, expected_end],
            "observed_pdf_range": [observed_start, observed_end],
            "conflict_dimensions": conflict_dimensions,
            "observed_boundary_sources": {
                "start": section.provenance.get("start_boundary_source"),
                "end": section.provenance.get("end_boundary_source"),
            },
            "safe_reconciliation": safe_reconciliation,
        }
        if (
            observed_start == expected_start
            and observed_end == expected_end
        ):
            section.range_consistency = {
                **base_consistency,
                "status": "validated",
            }
            validated += 1
            continue
        detected += 1
        if safe_reconciliation:
            section.pdf_page_start = expected_start
            section.pdf_page_end = expected_end
            section.azure_page_start = expected_start + 1
            section.azure_page_end = expected_end + 1
            section.grouping_method = "authoritative_toc_page_mapping_reconciled"
            section.provenance["authoritative_page_mapping"] = True
            section.provenance["page_range_source"] = "toc_endpoint_page_mapping"
            section.provenance["start_boundary_source"] = "mapped_toc_start"
            section.provenance["end_boundary_source"] = "mapped_toc_end"
            section.range_consistency = {
                **base_consistency,
                "status": "reconciled",
            }
            section.warnings = list(
                dict.fromkeys(
                    [
                        *section.warnings,
                        "section_range_conflicts_with_page_mapping",
                        "section_range_reconciled_to_page_mapping",
                    ]
                )
            )
            reconciled += 1
            validated += 1
        else:
            section.pdf_page_start = None
            section.pdf_page_end = None
            section.azure_page_start = None
            section.azure_page_end = None
            section.requires_human_review = True
            section.grouping_method = "unresolved_page_mapping_conflict"
            section.range_consistency = {
                **base_consistency,
                "status": "unresolved",
            }
            section.warnings = list(
                dict.fromkeys(
                    [*section.warnings, "section_range_conflicts_with_page_mapping"]
                )
            )
            unresolved += 1
        conflict_details.append(
            {
                "section_id": section.section_id,
                "expected_pdf_range": [expected_start, expected_end],
                "observed_pdf_range": [observed_start, observed_end],
                "conflict_dimensions": conflict_dimensions,
                "safe_reconciliation": safe_reconciliation,
                "status": section.range_consistency["status"],
            }
        )
    return {
        "section_page_mapping_validated_count": validated,
        "section_page_mapping_conflicts_detected_count": detected,
        "section_page_mapping_conflicts_reconciled_count": reconciled,
        "section_page_mapping_conflict_count": unresolved,
        "section_page_mapping_conflicts": conflict_details,
    }


def summarize_section_range_topology(
    sections: Iterable[DocumentSection],
) -> dict[str, int]:
    """Summarize finalized full-page ownership gaps and overlaps."""
    ordered = sorted(
        (
            section
            for section in sections
            if section.pdf_page_start is not None
            and section.pdf_page_end is not None
        ),
        key=lambda section: (section.section_order, section.section_id),
    )
    gaps = 0
    overlaps = 0
    geometry_boundaries = 0
    for left, right in zip(ordered, ordered[1:]):
        if right.pdf_page_start > left.pdf_page_end + 1:
            gaps += 1
        elif right.pdf_page_start <= left.pdf_page_end:
            if (
                right.pdf_page_start == left.pdf_page_end
                and left.end_heading_offset is not None
                and right.start_heading_offset is not None
            ):
                geometry_boundaries += 1
            else:
                overlaps += 1
    return {
        "section_page_gap_count": gaps,
        "section_page_overlap_count": overlaps,
        "section_same_page_geometry_boundary_count": geometry_boundaries,
    }


def _anchor_top(anchor: HeadingAnchor | None) -> float | None:
    return _regions_top(anchor.bounding_evidence) if anchor else None


def _same_page_resolution(
    item: Mapping[str, Any],
    candidate_sections: list[DocumentSection],
    anchors_by_id: Mapping[str, HeadingAnchor],
) -> DocumentSection | None:
    for section in candidate_sections:
        anchor = anchors_by_id.get(section.heading_anchor_id or "")
        if anchor and anchor.source_content_id == item["content_id"]:
            return section
    item_top = item.get("top")
    if not isinstance(item_top, (int, float)):
        return None
    positioned = []
    for section in candidate_sections:
        anchor = anchors_by_id.get(section.heading_anchor_id or "")
        top = _anchor_top(anchor)
        if (
            anchor is not None
            and isinstance(top, (int, float))
            and anchor.pdf_page_index in item.get("pdf_page_indexes", [])
        ):
            positioned.append((top, section))
    if (
        len(positioned) != len(candidate_sections)
        or len({top for top, _section in positioned}) != len(positioned)
    ):
        return None
    positioned.sort(key=lambda row: (row[0], row[1].section_order))
    preceding = [row for row in positioned if row[0] <= item_top]
    return preceding[-1][1] if preceding else None


def _append_reference(section: DocumentSection, item: Mapping[str, Any]) -> None:
    content_id = str(item["content_id"])
    content_type = str(item["content_type"])
    if content_type in {"paragraph", "text_block"}:
        section.text_block_ids.append(content_id)
    elif content_type == "heading":
        section.heading_ids.append(content_id)
    elif content_type == "table":
        section.table_ids.append(content_id)
    elif content_type == "table_cell":
        section.table_cell_ids.append(content_id)
    elif content_type == "extracted_row":
        section.extracted_row_ids.append(content_id)

    if (
        section.canonical_section_type == "notes_to_financial_statements"
        and content_type in {"heading", "paragraph", "text_block"}
        and NOTE_HEADING_RE.search(str(item.get("text") or ""))
    ):
        section.candidate_note_heading_ids.append(content_id)


def _disposition(
    item: Mapping[str, Any],
    *,
    reason: str,
    candidate_section_ids: Iterable[str] = (),
) -> DocumentContentDisposition:
    page_numbers = list(item.get("azure_page_numbers") or [])
    pdf_indexes = list(item.get("pdf_page_indexes") or [])
    return DocumentContentDisposition(
        content_id=str(item["content_id"]),
        content_type=str(item["content_type"]),
        pdf_page_index=pdf_indexes[0] if len(pdf_indexes) == 1 else None,
        azure_page_number=page_numbers[0] if len(page_numbers) == 1 else None,
        pdf_page_indexes=pdf_indexes,
        azure_page_numbers=page_numbers,
        reason=reason,
        candidate_section_ids=list(candidate_section_ids),
        provenance=dict(item.get("provenance") or {}),
    )


def group_document_content(
    sections: list[DocumentSection],
    inventory: Iterable[Mapping[str, Any]],
    anchors: Iterable[HeadingAnchor],
    *,
    toc_page_indexes: Iterable[int],
) -> tuple[list[DocumentContentDisposition], list[DocumentContentDisposition], dict[str, Any]]:
    toc_pages = set(int(value) for value in toc_page_indexes)
    inventory_rows = list(inventory)
    if len(sections) * len(inventory_rows) > MAX_GROUPING_COMPARISONS:
        raise ValueError("Document section grouping comparison limit exceeded")
    anchors_by_id = {
        anchor.anchor_id: anchor
        for anchor in anchors
        if anchor.trusted
        and not {
            "heading_anchor_near_tie",
            "heading_anchor_same_page_near_tie",
        }.intersection(anchor.warnings)
    }
    unassigned: list[DocumentContentDisposition] = []
    ambiguous: list[DocumentContentDisposition] = []
    all_ids: list[str] = []
    assigned_ids: set[str] = set()

    for item in inventory_rows:
        content_id = str(item["content_id"])
        all_ids.append(content_id)
        item_pages = set(int(value) for value in item.get("pdf_page_indexes") or [])
        if not item_pages:
            unassigned.append(_disposition(item, reason="page_provenance_missing"))
            continue
        if item_pages.issubset(toc_pages):
            unassigned.append(_disposition(item, reason="toc_page_excluded"))
            continue
        if item_pages & toc_pages:
            ambiguous.append(_disposition(item, reason="content_spans_toc_and_document_pages"))
            continue

        candidates = [
            section
            for section in sections
            if section.pdf_page_start is not None
            and section.pdf_page_end is not None
            and any(section.pdf_page_start <= page <= section.pdf_page_end for page in item_pages)
        ]
        unique_candidates = {
            section.section_id: section
            for section in candidates
        }
        candidates = list(unique_candidates.values())
        if len(item_pages) > 1:
            fully_containing = [
                section
                for section in candidates
                if section.pdf_page_start is not None
                and section.pdf_page_end is not None
                and all(
                    section.pdf_page_start <= page <= section.pdf_page_end
                    for page in item_pages
                )
            ]
            if len(fully_containing) == 1 and len(candidates) == 1:
                _append_reference(fully_containing[0], item)
                assigned_ids.add(content_id)
                continue
            if candidates:
                ambiguous.append(
                    _disposition(
                        item,
                        reason="content_spans_multiple_section_ranges",
                        candidate_section_ids=[
                            section.section_id for section in candidates
                        ],
                    )
                )
            else:
                unassigned.append(
                    _disposition(item, reason="outside_reliable_section_ranges")
                )
            continue
        if not candidates:
            unassigned.append(_disposition(item, reason="outside_reliable_section_ranges"))
            continue
        if len(candidates) == 1:
            _append_reference(candidates[0], item)
            assigned_ids.add(content_id)
            continue

        resolved = _same_page_resolution(item, candidates, anchors_by_id)
        if resolved is not None:
            _append_reference(resolved, item)
            assigned_ids.add(content_id)
            continue
        ambiguous.append(
            _disposition(
                item,
                reason="overlapping_section_ranges_without_decisive_heading_boundary",
                candidate_section_ids=[section.section_id for section in candidates],
            )
        )

    ambiguous_ids = {item.content_id for item in ambiguous}
    unassigned_ids = {item.content_id for item in unassigned}
    inventory_ids = set(all_ids)
    terminal_ids = assigned_ids | ambiguous_ids | unassigned_ids
    conservation_passed = (
        inventory_ids == terminal_ids
        and not (assigned_ids & ambiguous_ids)
        and not (assigned_ids & unassigned_ids)
        and not (ambiguous_ids & unassigned_ids)
        and len(inventory_ids) == len(all_ids)
    )
    summary = {
        "content_inventory_count": len(inventory_ids),
        "assigned_content_count": len(assigned_ids),
        "ambiguous_content_count": len(ambiguous_ids),
        "unassigned_content_count": len(unassigned_ids),
        "dropped_content_count": len(inventory_ids - terminal_ids),
        "duplicate_content_id_count": len(all_ids) - len(inventory_ids),
        "content_conservation_passed": conservation_passed,
        "assignment_rate": round(len(assigned_ids) / max(1, len(inventory_ids)), 6),
        "ambiguity_rate": round(len(ambiguous_ids) / max(1, len(inventory_ids)), 6),
        "unassigned_rate": round(len(unassigned_ids) / max(1, len(inventory_ids)), 6),
        "dropped_rate": round(
            len(inventory_ids - terminal_ids) / max(1, len(inventory_ids)),
            6,
        ),
    }
    if not conservation_passed:
        raise ValueError("Document content conservation invariant failed")
    for section in sections:
        section.text_block_ids = list(dict.fromkeys(section.text_block_ids))
        section.heading_ids = list(dict.fromkeys(section.heading_ids))
        section.table_ids = list(dict.fromkeys(section.table_ids))
        section.table_cell_ids = list(dict.fromkeys(section.table_cell_ids))
        section.extracted_row_ids = list(dict.fromkeys(section.extracted_row_ids))
        section.candidate_note_heading_ids = list(dict.fromkeys(section.candidate_note_heading_ids))
    return unassigned, ambiguous, summary
