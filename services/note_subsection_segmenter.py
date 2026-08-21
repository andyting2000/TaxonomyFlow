"""Lossless Notes child segmentation over the bounded #19A structure artifact."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from schemas import (
    DocumentContentEvidence,
    DocumentSection,
    DocumentStructureResult,
    NoteSubsection,
    NotesContentConservation,
    NotesSegmentationMetrics,
)
from services.section_title_normalization import normalize_title_text


NOTES_CONTAINER_ID = "notes_container"
NOTE_HEADING_PATTERN = re.compile(
    r"^\s*(?:n[o0]te\s+)?"
    r"(?P<number>(?:\d{1,3}(?:\.\d+)*(?:\([a-z]\))?|[a-z]|[ivxlcdm]{2,8}))"
    r"(?:\s*[.)\-:]\s*|\s+)(?P<label>\S.*)$",
    re.I,
)
NUMBER_ONLY_PATTERN = re.compile(
    r"^\s*(?:n[o0]te\s+)?"
    r"(?P<number>(?:\d{1,3}(?:\.\d+)*(?:\([a-z]\))?|[a-z]|[ivxlcdm]{2,8}))"
    r"\s*[.)\-:]?\s*$",
    re.I,
)
CONTINUED_SUFFIX_PATTERN = re.compile(r"\s*[\[(]?continued[\])]?\s*$", re.I)
WATERMARK_PATTERN = re.compile(r"^dr(?:a(?:f(?:t)?)?)?$", re.I)
UNIT_FRAGMENT_PATTERN = re.compile(r"^(?:rm|to)$", re.I)
PAGE_NUMBER_PATTERN = re.compile(r"^(?P<left>\d{1,3})\s+(?P<right>\d{1,3})$")
COMPANY_NAME_PATTERN = re.compile(
    r"\b(?:sdn\.?\s*bhd\.?|berhad|limited|ltd\.?|inc\.?|plc)\s*$",
    re.I,
)
PROSE_VERB_PATTERN = re.compile(
    r"\b(?:are|has|have|is|measures|recognises?|represents|was|were)\b",
    re.I,
)
MAX_NOTE_EVIDENCE_ITEMS = 100_000
MAX_PLAUSIBLE_NOTE_NUMBER = 99
PHYSICAL_HEADING_TOP_TOLERANCE = 0.075


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _top(evidence: DocumentContentEvidence) -> float:
    values: list[float] = []
    for region in evidence.bounding_evidence:
        polygon = region.get("polygon") if isinstance(region, dict) else None
        if not isinstance(polygon, list) or not polygon:
            continue
        first = polygon[0]
        try:
            if isinstance(first, dict):
                values.append(float(first.get("y")))
            elif len(polygon) >= 2:
                values.append(float(polygon[1]))
        except (TypeError, ValueError, IndexError):
            continue
    return min(values) if values else 1_000_000.0


def _role_is_section_heading(evidence: DocumentContentEvidence) -> bool:
    role = str((evidence.provenance or {}).get("role") or "").casefold()
    return role.endswith("section_heading") or role.endswith("sectionheading")


def _strip_continued(value: str) -> str:
    return _text(CONTINUED_SUFFIX_PATTERN.sub("", value))


def _is_continued(value: str) -> bool:
    return bool(CONTINUED_SUFFIX_PATTERN.search(_text(value)))


def _polygon_bounds(region: Any) -> tuple[float, float, float, float] | None:
    polygon = region.get("polygon") if isinstance(region, dict) else None
    if not isinstance(polygon, list) or not polygon:
        return None
    coordinates: list[tuple[float, float]] = []
    try:
        if isinstance(polygon[0], dict):
            coordinates = [
                (float(point["x"]), float(point["y"]))
                for point in polygon
                if isinstance(point, dict) and "x" in point and "y" in point
            ]
        else:
            coordinates = [
                (float(polygon[index]), float(polygon[index + 1]))
                for index in range(0, len(polygon) - 1, 2)
            ]
    except (TypeError, ValueError, KeyError):
        return None
    if not coordinates:
        return None
    xs = [point[0] for point in coordinates]
    ys = [point[1] for point in coordinates]
    return min(xs), min(ys), max(xs), max(ys)


def _regions_overlap(first: Any, second: Any) -> bool:
    first_bounds = _polygon_bounds(first)
    second_bounds = _polygon_bounds(second)
    if first_bounds is None or second_bounds is None:
        return False
    first_left, first_top, first_right, first_bottom = first_bounds
    second_left, second_top, second_right, second_bottom = second_bounds
    return not (
        first_right < second_left
        or second_right < first_left
        or first_bottom < second_top
        or second_bottom < first_top
    )


def _overlaps_table_region(
    evidence: DocumentContentEvidence,
    table_regions: list[dict[str, Any]],
) -> bool:
    if bool((evidence.provenance or {}).get("table_member")):
        return True
    if evidence.content_type in {"table", "table_cell", "extracted_row"}:
        return True
    for region in evidence.bounding_evidence:
        page_number = int(region.get("page_number") or 0) if isinstance(region, dict) else 0
        for table_region in table_regions:
            if int(table_region.get("page_number") or 0) != page_number:
                continue
            if _regions_overlap(region, table_region):
                return True
    return False


def _sort_key(evidence: DocumentContentEvidence) -> tuple[int, float, str]:
    page = min(evidence.pdf_page_indexes, default=1_000_000)
    return page, _top(evidence), evidence.content_id


def _top_on_pdf_page(
    evidence: DocumentContentEvidence,
    pdf_page_index: int,
) -> float | None:
    scoped = [
        region
        for region in evidence.bounding_evidence
        if isinstance(region, dict)
        and int(region.get("page_number") or 0) == pdf_page_index + 1
    ]
    if not scoped:
        return None
    copy = evidence.model_copy(deep=True)
    copy.bounding_evidence = scoped
    return _top(copy)


def parse_note_heading(value: Any) -> tuple[str | None, str, str] | None:
    """Return note number, display label, and normalized label."""
    raw = _text(value)
    if not raw:
        return None
    match = NOTE_HEADING_PATTERN.match(raw)
    if match:
        label = _text(match.group("label"))
        normalized = normalize_title_text(label)
        return match.group("number"), label, normalized
    normalized = normalize_title_text(raw)
    if not normalized or normalized in {
        "notes to financial statements",
        "notes to the financial statements",
        "notes to accounts",
    }:
        return None
    return None, raw, normalized


def _plausible_note_number(value: str | None) -> bool:
    if not value:
        return True
    numeric = re.match(r"^(?P<base>\d{1,3}(?:\.\d+)*)(?:\([a-z]\))?$", value, re.I)
    if not numeric:
        return bool(re.fullmatch(r"[a-z]|[ivxlcdm]{2,8}", value, re.I))
    parts = [int(part) for part in numeric.group("base").split(".")]
    return bool(parts) and all(0 < part <= MAX_PLAUSIBLE_NOTE_NUMBER for part in parts)


def _section_reference_ids(section: DocumentSection) -> set[str]:
    return {
        *section.text_block_ids,
        *section.heading_ids,
        *section.table_ids,
        *section.table_cell_ids,
        *section.extracted_row_ids,
    }


def _notes_range_membership(
    evidence: DocumentContentEvidence,
    section: DocumentSection,
) -> str:
    if section.pdf_page_start is None or section.pdf_page_end is None:
        return (
            "inside"
            if evidence.content_id in _section_reference_ids(section)
            else "outside"
        )
    if not evidence.pdf_page_indexes:
        return "outside"
    inside = [
        section.pdf_page_start <= page <= section.pdf_page_end
        for page in evidence.pdf_page_indexes
    ]
    if all(inside):
        return "inside"
    if any(inside):
        return "ambiguous_boundary"
    return "outside"


def _looks_like_unnumbered_heading(evidence: DocumentContentEvidence) -> bool:
    text = _text(evidence.text_evidence)
    if evidence.content_type != "heading" or not text or len(text) > 160:
        return False
    if normalize_title_text(text) in {
        "notes to financial statements",
        "notes to the financial statements",
        "notes to accounts",
    }:
        return False
    words = [word for word in re.findall(r"[A-Za-z]+", text) if word]
    if not words:
        return False
    uppercase_ratio = sum(word.isupper() for word in words) / len(words)
    title_ratio = sum(word[:1].isupper() for word in words) / len(words)
    return uppercase_ratio >= 0.6 or title_ratio >= 0.75


def _candidate_rejection_reason(
    candidate: dict[str, Any],
    *,
    repeated_pages: dict[str, set[int]],
) -> str | None:
    raw = candidate["raw_heading"]
    lowered = raw.casefold()
    number = candidate["note_number"]
    label = candidate["logical_label"]
    label_lower = label.casefold()
    normalized = candidate["normalized_heading"]
    evidence = candidate["evidence"]
    words = re.findall(r"[A-Za-z]+", label)
    alpha_count = sum(character.isalpha() for character in label)
    nonspace_count = sum(not character.isspace() for character in label)
    alpha_ratio = alpha_count / max(1, nonspace_count)

    if (
        lowered.startswith(("company no", "company number"))
        or label_lower.startswith(("company no", "company number"))
        or re.match(r"^notes\s+to\s+(?:the\s+)?financial\s+statements\b", lowered)
        or re.match(r"^notes\s+to\s+(?:the\s+)?financial\s+statements\b", label_lower)
        or COMPANY_NAME_PATTERN.search(raw)
        or COMPANY_NAME_PATTERN.search(label)
    ):
        return "boilerplate"
    if WATERMARK_PATTERN.fullmatch(raw) or WATERMARK_PATTERN.fullmatch(label):
        return "boilerplate"
    page_number = PAGE_NUMBER_PATTERN.fullmatch(raw)
    if page_number and page_number.group("left") == page_number.group("right"):
        return "boilerplate"
    if UNIT_FRAGMENT_PATTERN.fullmatch(raw) or UNIT_FRAGMENT_PATTERN.fullmatch(label):
        return "table_value"
    if number and not _plausible_note_number(number):
        return "invalid_numeric"
    if not alpha_count:
        return "table_value"
    if candidate["in_table"] and not (
        candidate["forced"] or candidate["section_heading_role"]
    ):
        return "table_value"

    prose_like = (
        len(raw) > 160
        or len(words) > 14
        or bool(re.search(r"[.;!?]\s*$|:\s*\-\s*$", label))
        or (
            len(words) >= 6
            and (
                label_lower.startswith(("the ", "after ", "turnover "))
                or bool(PROSE_VERB_PATTERN.search(label))
            )
        )
    )
    if prose_like:
        return "prose"
    if alpha_count < 3 or alpha_ratio < 0.45:
        return "other"

    alphabetic_number = bool(number and not number[:1].isdigit())
    if alphabetic_number and not (
        candidate["forced"]
        or candidate["section_heading_role"]
        or evidence.content_type == "heading"
    ):
        return "prose"
    if number:
        return None

    pages = repeated_pages.get(normalized, set())
    top = _top(evidence)
    if len(pages) >= 2 and (top <= 1.25 or top >= 10.0):
        return "boilerplate"
    if not (
        candidate["forced"]
        or candidate["section_heading_role"]
        or _looks_like_unnumbered_heading(evidence)
    ):
        return "other"
    if len(words) > 12:
        return "prose"
    return None


def _raw_heading_candidates(
    evidence_rows: list[DocumentContentEvidence],
    note_section: DocumentSection,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    explicit_ids = set(note_section.candidate_note_heading_ids)
    table_regions = [
        region
        for evidence in evidence_rows
        if evidence.content_type in {"table", "table_cell"}
        for region in evidence.bounding_evidence
        if isinstance(region, dict)
    ]
    candidates: list[dict[str, Any]] = []
    consumed: set[str] = set()
    for index, evidence in enumerate(evidence_rows):
        if evidence.content_id in consumed:
            continue
        raw = _text(evidence.text_evidence)
        numbered = NOTE_HEADING_PATTERN.match(raw)
        number_only = NUMBER_ONLY_PATTERN.match(raw)
        forced = evidence.content_id in explicit_ids
        section_heading_role = _role_is_section_heading(evidence)
        eligible = bool(
            numbered
            or number_only
            or forced
            or section_heading_role
            or _looks_like_unnumbered_heading(evidence)
        )
        combined_ids = [evidence.content_id]
        if number_only and index + 1 < len(evidence_rows):
            following = evidence_rows[index + 1]
            same_page = (
                min(evidence.pdf_page_indexes, default=-1)
                == min(following.pdf_page_indexes, default=-2)
            )
            following_text = _text(following.text_evidence)
            if (
                same_page
                and following_text
                and len(following_text) <= 160
                and following.content_type in {"heading", "paragraph", "text_block"}
                and sum(character.isalpha() for character in following_text) >= 3
            ):
                following_numbered = NOTE_HEADING_PATTERN.match(following_text)
                if (
                    following_numbered
                    and following_numbered.group("number").casefold()
                    == number_only.group("number").casefold()
                ):
                    raw = following_text
                else:
                    raw = f"{raw} {following_text}"
                numbered = NOTE_HEADING_PATTERN.match(raw)
                eligible = bool(numbered)
                combined_ids.append(following.content_id)
                consumed.add(following.content_id)
                forced = forced or following.content_id in explicit_ids
                section_heading_role = (
                    section_heading_role or _role_is_section_heading(following)
                )
        if not eligible:
            continue
        parsed = parse_note_heading(raw)
        if parsed is None:
            continue
        number, label, normalized = parsed
        logical_label = _strip_continued(label)
        normalized = normalize_title_text(logical_label)
        candidates.append(
            {
                "evidence": evidence,
                "evidence_ids": combined_ids,
                "raw_heading": raw,
                "note_number": number,
                "note_label": logical_label,
                "logical_label": logical_label,
                "normalized_heading": normalized,
                "continued": _is_continued(label),
                "forced": forced,
                "section_heading_role": section_heading_role,
                "in_table": _overlaps_table_region(evidence, table_regions),
                "confidence": 0.96 if number else (0.82 if forced else 0.76),
            }
        )
    repeated_pages: dict[str, set[int]] = {}
    for candidate in candidates:
        repeated_pages.setdefault(candidate["normalized_heading"], set()).update(
            candidate["evidence"].pdf_page_indexes
        )
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for candidate in candidates:
        reason = _candidate_rejection_reason(
            candidate,
            repeated_pages=repeated_pages,
        )
        if reason is None:
            accepted.append(candidate)
        else:
            candidate["rejection_reason"] = reason
            rejected.append(candidate)
    return accepted, rejected


def _candidate_preference(candidate: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        int(candidate["section_heading_role"] or candidate["forced"]),
        int(bool(candidate["note_number"])),
        int(candidate["evidence"].content_type == "paragraph"),
        len(candidate["logical_label"]),
    )


def _same_physical_heading(
    first: dict[str, Any],
    second: dict[str, Any],
) -> bool:
    first_page = min(first["evidence"].pdf_page_indexes, default=-1)
    second_page = min(second["evidence"].pdf_page_indexes, default=-2)
    if first_page != second_page:
        return False
    if first["normalized_heading"] != second["normalized_heading"]:
        return False
    first_number = str(first["note_number"] or "").casefold()
    second_number = str(second["note_number"] or "").casefold()
    if first_number and second_number and first_number != second_number:
        return False
    return abs(_top(first["evidence"]) - _top(second["evidence"])) <= PHYSICAL_HEADING_TOP_TOLERANCE


def _collapse_physical_duplicates(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    physical: list[dict[str, Any]] = []
    duplicate_count = 0
    for candidate in candidates:
        match = next(
            (item for item in reversed(physical) if _same_physical_heading(item, candidate)),
            None,
        )
        if match is None:
            copy = dict(candidate)
            copy["evidence_ids"] = list(candidate["evidence_ids"])
            copy["positions"] = [_sort_key(candidate["evidence"])]
            physical.append(copy)
            continue
        duplicate_count += 1
        match["evidence_ids"] = list(
            dict.fromkeys([*match["evidence_ids"], *candidate["evidence_ids"]])
        )
        if _candidate_preference(candidate) > _candidate_preference(match):
            evidence_ids = match["evidence_ids"]
            positions = match["positions"]
            match.update(candidate)
            match["evidence_ids"] = evidence_ids
            match["positions"] = positions
    return physical, duplicate_count


def _logical_identity(candidate: dict[str, Any]) -> str:
    number = str(candidate["note_number"] or "").casefold()
    if number:
        return f"numbered|{number}|{candidate['normalized_heading']}"
    evidence = candidate["evidence"]
    page = min(evidence.pdf_page_indexes, default=-1)
    top_bucket = round(_top(evidence), 1)
    return f"unnumbered|{candidate['normalized_heading']}|{page}|{top_bucket}"


def _stable_child_id(parent_section_id: str, identity: str) -> str:
    digest = hashlib.sha256(f"{parent_section_id}|{identity}".encode("utf-8")).hexdigest()[:12]
    return f"{parent_section_id}:note:{digest}"


def _logical_headings(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    physical, duplicate_count = _collapse_physical_duplicates(candidates)
    logical: list[dict[str, Any]] = []
    by_identity: dict[str, dict[str, Any]] = {}
    continuation_count = 0
    for candidate in physical:
        identity = _logical_identity(candidate)
        existing = by_identity.get(identity)
        if existing is None:
            candidate["identity"] = identity
            logical.append(candidate)
            by_identity[identity] = candidate
            continue
        if candidate["continued"]:
            continuation_count += 1
            warning = "continued_note_heading_merged"
        else:
            duplicate_count += 1
            warning = "duplicate_note_heading_merged"
        existing["warnings"] = list(
            dict.fromkeys([*existing.get("warnings", []), warning])
        )
        existing["evidence_ids"] = list(
            dict.fromkeys([*existing["evidence_ids"], *candidate["evidence_ids"]])
        )
        existing["positions"].extend(candidate["positions"])
        if existing["continued"] and not candidate["continued"]:
            evidence_ids = existing["evidence_ids"]
            positions = existing["positions"]
            warnings = existing["warnings"]
            identity = existing["identity"]
            existing.update(candidate)
            existing["evidence_ids"] = evidence_ids
            existing["positions"] = positions
            existing["warnings"] = warnings
            existing["identity"] = identity
    return logical, duplicate_count, continuation_count


def _add_reference(subsection: NoteSubsection, evidence: DocumentContentEvidence) -> None:
    content_id = evidence.content_id
    if evidence.content_type in {"paragraph", "text_block", "heading"}:
        subsection.paragraph_references.append(content_id)
    elif evidence.content_type == "table":
        subsection.table_references.append(content_id)
    elif evidence.content_type == "table_cell":
        subsection.table_cell_references.append(content_id)
    elif evidence.content_type == "extracted_row":
        subsection.extracted_row_references.append(content_id)
    else:
        subsection.other_evidence_references.append(content_id)


def segment_note_subsections(
    structure: DocumentStructureResult,
) -> tuple[list[NoteSubsection], NotesContentConservation, list[str]]:
    """Segment one Notes range while conserving every scoped evidence item."""
    note_sections = [
        section
        for section in structure.sections
        if section.canonical_section_type == "notes_to_financial_statements"
    ]
    if not note_sections:
        return [], NotesContentConservation(passed=True), ["notes_section_not_present"]
    if len(note_sections) > 1:
        raise ValueError("Multiple primary Notes sections require human reconciliation")
    note_section = note_sections[0]
    memberships = {
        evidence.content_id: _notes_range_membership(evidence, note_section)
        for evidence in structure.content_evidence
    }
    scoped = [
        evidence
        for evidence in structure.content_evidence
        if memberships[evidence.content_id] != "outside"
    ]
    if len(scoped) > MAX_NOTE_EVIDENCE_ITEMS:
        raise ValueError("Notes evidence item limit exceeded")
    scoped.sort(key=_sort_key)
    if len({item.content_id for item in scoped}) != len(scoped):
        raise ValueError("Duplicate Notes evidence IDs violate conservation")

    accepted_candidates, rejected_candidates = _raw_heading_candidates(
        [
            evidence
            for evidence in scoped
            if memberships[evidence.content_id] == "inside"
        ],
        note_section,
    )
    headings, duplicate_count, continuation_count = _logical_headings(
        accepted_candidates
    )
    rejected_counts = {
        reason: sum(
            1
            for candidate in rejected_candidates
            if candidate.get("rejection_reason") == reason
        )
        for reason in {"boilerplate", "table_value", "invalid_numeric", "prose", "other"}
    }
    segmentation_metrics = NotesSegmentationMetrics(
        raw_heading_candidate_count=(
            len(accepted_candidates) + len(rejected_candidates)
        ),
        accepted_heading_candidate_count=len(accepted_candidates),
        accepted_logical_subsection_count=len(headings),
        duplicate_headings_merged=duplicate_count,
        continuation_headings_merged=continuation_count,
        boilerplate_lines_suppressed=rejected_counts["boilerplate"],
        table_value_fragments_suppressed=rejected_counts["table_value"],
        invalid_numeric_note_numbers_rejected=rejected_counts["invalid_numeric"],
        prose_candidates_rejected=rejected_counts["prose"],
        other_low_quality_candidates_rejected=rejected_counts["other"],
    )
    subsections: list[NoteSubsection] = []
    normalized_seen: set[str] = set()
    for heading in headings:
        evidence = heading["evidence"]
        pages = evidence.pdf_page_indexes
        azure_pages = evidence.azure_page_numbers
        heading_warnings = list(heading.get("warnings", []))
        if heading["normalized_heading"] in normalized_seen:
            heading_warnings.append("repeated_note_heading")
        normalized_seen.add(heading["normalized_heading"])
        subsections.append(
            NoteSubsection(
                child_section_id=_stable_child_id(
                    note_section.section_id,
                    heading["identity"],
                ),
                raw_heading=heading["raw_heading"],
                normalized_heading=heading["normalized_heading"],
                note_number=heading["note_number"],
                note_label=heading["note_label"],
                pdf_page_start=min(pages, default=None),
                pdf_page_end=max(pages, default=None),
                azure_page_start=min(azure_pages, default=None),
                azure_page_end=max(azure_pages, default=None),
                heading_evidence=list(heading["evidence_ids"]),
                confidence=heading["confidence"],
                warnings=list(dict.fromkeys(heading_warnings)),
            )
        )

    positions = sorted(
        [
            (position, subsection)
            for heading, subsection in zip(headings, subsections)
            for position in heading["positions"]
        ],
        key=lambda row: row[0],
    )
    assigned: set[str] = set()
    ambiguous: set[str] = set()
    unassigned: set[str] = set()
    other_section_ids = {
        content_id
        for section in structure.sections
        if section.section_id != note_section.section_id
        for content_id in _section_reference_ids(section)
    }

    for evidence in scoped:
        evidence_id = evidence.content_id
        if memberships[evidence_id] == "ambiguous_boundary":
            ambiguous.add(evidence_id)
            continue
        if evidence_id in other_section_ids and evidence_id not in _section_reference_ids(
            note_section
        ):
            ambiguous.add(evidence_id)
            continue
        key = _sort_key(evidence)
        prior = [row for row in positions if row[0] <= key]
        if not prior:
            if not positions:
                unassigned.add(evidence_id)
                continue
            selected = positions[0][1]
        else:
            selected = prior[-1][1]
        evidence_pages = evidence.pdf_page_indexes
        crossed = []
        for row in positions:
            heading_page, heading_top, _heading_id = row[0]
            if (
                not evidence_pages
                or not (min(evidence_pages) < heading_page <= max(evidence_pages))
                or row[1].child_section_id == selected.child_section_id
            ):
                continue
            final_page_top = _top_on_pdf_page(evidence, heading_page)
            if (
                evidence.content_type in {"table", "table_cell", "extracted_row"}
                and final_page_top is not None
                and final_page_top < heading_top
            ):
                continue
            crossed.append(row)
        if crossed:
            ambiguous.add(evidence_id)
            continue
        _add_reference(selected, evidence)
        assigned.add(evidence_id)
        if evidence_pages:
            selected.pdf_page_start = min(
                value
                for value in [selected.pdf_page_start, *evidence_pages]
                if value is not None
            )
            selected.pdf_page_end = max(
                value
                for value in [selected.pdf_page_end, *evidence_pages]
                if value is not None
            )
        if evidence.azure_page_numbers:
            selected.azure_page_start = min(
                value
                for value in [selected.azure_page_start, *evidence.azure_page_numbers]
                if value is not None
            )
            selected.azure_page_end = max(
                value
                for value in [selected.azure_page_end, *evidence.azure_page_numbers]
                if value is not None
            )

    for subsection in subsections:
        subsection.paragraph_references = list(
            dict.fromkeys(subsection.paragraph_references)
        )
        subsection.table_references = list(dict.fromkeys(subsection.table_references))
        subsection.table_cell_references = list(
            dict.fromkeys(subsection.table_cell_references)
        )
        subsection.extracted_row_references = list(
            dict.fromkeys(subsection.extracted_row_references)
        )
        subsection.other_evidence_references = list(
            dict.fromkeys(subsection.other_evidence_references)
        )
        if (
            note_section.pdf_page_start is not None
            and note_section.pdf_page_end is not None
            and (
                subsection.pdf_page_start is None
                or subsection.pdf_page_end is None
                or subsection.pdf_page_start < note_section.pdf_page_start
                or subsection.pdf_page_end > note_section.pdf_page_end
            )
        ):
            raise ValueError("Notes child range falls outside parent Notes range")

    all_ids = {evidence.content_id for evidence in scoped}
    terminal = assigned | ambiguous | unassigned
    dropped = all_ids - terminal
    passed = (
        not dropped
        and terminal == all_ids
        and not (assigned & ambiguous)
        and not (assigned & unassigned)
        and not (ambiguous & unassigned)
    )
    segmentation_metrics.extracted_rows_attached = sum(
        len(subsection.extracted_row_references) for subsection in subsections
    )
    segmentation_metrics.child_sections_with_zero_meaningful_content = sum(
        1
        for subsection in subsections
        if (
            sum(character.isalpha() for character in subsection.note_label) < 3
            and not (
                {
                    *subsection.paragraph_references,
                    *subsection.table_references,
                    *subsection.table_cell_references,
                    *subsection.extracted_row_references,
                    *subsection.other_evidence_references,
                }
                - set(subsection.heading_evidence)
            )
        )
    )
    conservation = NotesContentConservation(
        total_notes_evidence_items=len(all_ids),
        assigned_items=len(assigned),
        ambiguous_items=len(ambiguous),
        unassigned_items=len(unassigned),
        dropped_items=len(dropped),
        assigned_evidence_ids=sorted(assigned),
        ambiguous_evidence_ids=sorted(ambiguous),
        unassigned_evidence_ids=sorted(unassigned),
        segmentation_metrics=segmentation_metrics,
        passed=passed,
    )
    if not passed:
        raise ValueError("Notes content conservation invariant failed")
    warnings = []
    if not subsections:
        warnings.append("note_subsections_not_detected")
    if ambiguous:
        warnings.append("ambiguous_notes_content")
    if unassigned:
        warnings.append("unassigned_notes_content")
    return subsections, conservation, warnings
