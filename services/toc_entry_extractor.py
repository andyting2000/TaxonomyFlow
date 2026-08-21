"""Deterministic TOC entry parsing and printed-range inference."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping

from schemas import TocEntry
from services.document_heading_quality import toc_title_rejection_reason
from services.section_title_normalization import (
    UNKNOWN_SECTION,
    normalize_section_title,
    semantic_text,
)


TOC_LABELS = {
    "index",
    "contents",
    "table of contents",
    "page",
    "pages",
    "page no",
    "page no.",
}
ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.I)
TRAILING_PAGE_RE = re.compile(
    r"(?<![A-Za-z])(?P<page_text>(?:pages?(?:\s+no\.?)?\s*)?"
    r"(?P<start>\d{1,4}|[ivxlcdm]{1,12})"
    r"(?:\s*-\s*(?P<end>\d{1,4}|[ivxlcdm]{1,12}))?)\s*$",
    re.I,
)
LEADING_NUMBER_RE = re.compile(
    r"^\s*(?:\(?\d{1,3}\)?|[A-Za-z]|[ivxlcdm]+)\s*[.)\-:]\s+",
    re.I,
)
MAX_TOC_SOURCE_LINES = 5000
MAX_TOC_ENTRIES = 500
MAX_CONSECUTIVE_NON_ENTRY_LINES = 2


def _entry_numbering_scheme(entry: TocEntry) -> str:
    label = str(entry.printed_page_start_label or "").strip()
    return "roman" if ROMAN_RE.fullmatch(label) else "arabic"


def _format_page_label(value: int, scheme: str) -> str:
    if scheme != "roman":
        return str(value)
    numerals = (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    )
    remaining = value
    encoded: list[str] = []
    for amount, token in numerals:
        while remaining >= amount:
            encoded.append(token)
            remaining -= amount
    return "".join(encoded).lower() if encoded else str(value)


def _clean_source_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"(?<=\d)\s*[~_=]\s*(?=\d)", "-", text)
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    return " ".join(text.split())


def _roman_to_int(value: str) -> int | None:
    text = value.upper()
    if not ROMAN_RE.fullmatch(text):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    result = 0
    previous = 0
    for char in reversed(text):
        current = values[char]
        if current < previous:
            result -= current
        else:
            result += current
            previous = current
    # Re-encode to reject malformed forms such as IIII or IIX.
    if result <= 0 or result > 3999:
        return None
    numerals = (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    )
    remaining = result
    encoded = []
    for amount, token in numerals:
        while remaining >= amount:
            encoded.append(token)
            remaining -= amount
    return result if "".join(encoded) == text else None


def _page_number(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        parsed = int(value)
        return parsed if parsed > 0 else None
    return _roman_to_int(value)


def _raw_title(text: str, page_match: re.Match[str] | None) -> tuple[str, list[str]]:
    warnings: list[str] = []
    title = text[:page_match.start()] if page_match else text
    title = re.sub(r"\.{2,}\s*$", "", title).strip(" .:\t")
    stripped = LEADING_NUMBER_RE.sub("", title)
    if stripped != title:
        warnings.append("leading_numbering_removed")
        title = stripped
    semantic_title = semantic_text(title)
    if semantic_title != title:
        warnings.append("selection_state_marker_removed")
        title = semantic_title
    return title, warnings


def _is_heading_or_column(text: str) -> bool:
    normalized_text = re.sub(r"(?<=[A-Za-z])0|0(?=[A-Za-z])", "o", text)
    normalized = re.sub(r"[^a-z]+", " ", normalized_text.lower()).strip()
    return normalized in {re.sub(r"[^a-z]+", " ", item).strip() for item in TOC_LABELS}


def extract_toc_entries(source_lines: Iterable[Mapping[str, Any]]) -> list[TocEntry]:
    lines = list(source_lines)
    if len(lines) > MAX_TOC_SOURCE_LINES:
        raise ValueError("TOC entry source line limit exceeded")
    entries: list[TocEntry] = []
    block_started = False
    consecutive_non_entries = 0
    for line in lines:
        original_source_text = " ".join(
            unicodedata.normalize("NFKC", str(line.get("text") or "")).split()
        )
        working_text = _clean_source_text(original_source_text)
        if not working_text:
            continue
        if _is_heading_or_column(working_text):
            if re.sub(r"[^a-z]+", " ", working_text.lower()).strip() in {
                "index",
                "contents",
                "table of contents",
            }:
                block_started = True
            consecutive_non_entries = 0
            continue

        page_match = TRAILING_PAGE_RE.search(working_text)
        title, warnings = _raw_title(working_text, page_match)
        start = _page_number(page_match.group("start")) if page_match else None
        rejection_reason = toc_title_rejection_reason(title)
        if (
            start is not None
            and 1900 <= start <= 2100
            and re.search(r"\b(?:financial\s+year|year\s+ended|date|dated|as\s+at)\b", title, re.I)
        ):
            rejection_reason = "date_or_year_pattern"
        credible_entry = (
            page_match is not None
            and start is not None
            and bool(title)
            and bool(re.search(r"[A-Za-z]", title))
            and rejection_reason is None
        )
        if not credible_entry:
            if block_started and entries:
                consecutive_non_entries += 1
                if consecutive_non_entries >= MAX_CONSECUTIVE_NON_ENTRY_LINES:
                    break
            continue
        block_started = True
        consecutive_non_entries = 0

        normalized = normalize_section_title(title)
        end = _page_number(page_match.group("end")) if page_match and page_match.group("end") else None
        printed_page_text = page_match.group("page_text") if page_match else None
        confidence = 0.9
        range_method = "explicit_range" if end is not None else "start_only"

        if end is not None and end < start:
            warnings.append("printed_page_range_reversed")
            end = None
            confidence = 0.45
            range_method = "start_only"
        elif ROMAN_RE.fullmatch(page_match.group("start")):
            warnings.append("roman_printed_page_label")
            confidence = 0.75

        if normalized.canonical_section_type == UNKNOWN_SECTION:
            warnings.append("canonical_section_unknown")
            confidence -= 0.12
        if re.search(r"[^\w\s'&(),./\-]", title):
            warnings.append("ocr_punctuation_present")
            confidence -= 0.08

        entries.append(
            TocEntry(
                entry_id=f"toc-entry-{len(entries) + 1}",
                raw_title=title,
                normalized_title=normalized.normalized_title,
                canonical_section_hint=normalized.canonical_section_type,
                printed_page_start=start,
                printed_page_end=end,
                printed_page_start_label=(
                    page_match.group("start") if page_match else None
                ),
                printed_page_end_label=(
                    page_match.group("end")
                    if page_match and page_match.group("end")
                    else None
                ),
                printed_page_text=printed_page_text,
                source_pdf_page_index=max(0, int(line.get("pdf_page_index") or 0)),
                source_text=original_source_text,
                confidence=round(max(0.0, min(1.0, confidence)), 4),
                range_method=range_method,
                parse_warnings=list(dict.fromkeys(warnings)),
            )
        )
        if len(entries) > MAX_TOC_ENTRIES:
            raise ValueError("TOC entry limit exceeded")
    return entries


def infer_toc_page_ranges(
    entries: Iterable[TocEntry],
    *,
    final_printed_page: int | None,
    final_numbering_scheme: str | None = None,
) -> list[TocEntry]:
    rows = [entry.model_copy(deep=True) for entry in entries]
    start_keys = [
        (_entry_numbering_scheme(entry), entry.printed_page_start)
        for entry in rows
        if entry.printed_page_start is not None
    ]
    duplicate_starts = {
        start_key
        for start_key in start_keys
        if start_keys.count(start_key) > 1
    }

    for index, entry in enumerate(rows):
        if entry.printed_page_start is None or entry.printed_page_end is not None:
            continue
        next_entry = next(
            (
                later
                for later in rows[index + 1:]
                if later.printed_page_start is not None
            ),
            None,
        )
        next_start = next_entry.printed_page_start if next_entry else None
        scheme = _entry_numbering_scheme(entry)
        next_scheme = _entry_numbering_scheme(next_entry) if next_entry else None
        start_key = (scheme, entry.printed_page_start)
        warnings = list(entry.parse_warnings)
        if start_key in duplicate_starts:
            warnings.append("duplicate_start_page")
        if next_entry is not None and next_scheme != scheme:
            warnings.append("printed_page_numbering_regime_change")
            warnings.append("printed_page_end_unresolved")
            entry.range_method = "unresolved_end"
        elif next_start is not None and next_start > entry.printed_page_start:
            entry.printed_page_end = next_start - 1
            entry.printed_page_end_label = _format_page_label(
                entry.printed_page_end,
                scheme,
            )
            entry.range_method = (
                "inferred_shared_start" if start_key in duplicate_starts
                else "inferred_from_next_start"
            )
        elif next_start == entry.printed_page_start:
            # Two headings may legitimately share a printed page. Preserve the
            # overlap for later heading-boundary refinement.
            entry.printed_page_end = entry.printed_page_start
            entry.printed_page_end_label = entry.printed_page_start_label
            entry.range_method = "inferred_shared_start"
        elif next_start is not None:
            warnings.append("printed_page_number_reset_or_decrease")
            warnings.append("printed_page_end_unresolved")
            entry.range_method = "unresolved_end"
        elif (
            final_printed_page is not None
            and final_printed_page >= entry.printed_page_start
            and (
                final_numbering_scheme is None
                or final_numbering_scheme == scheme
            )
        ):
            entry.printed_page_end = final_printed_page
            entry.printed_page_end_label = _format_page_label(
                final_printed_page,
                scheme,
            )
            entry.range_method = "inferred_from_document_end"
        else:
            warnings.append("printed_page_end_unresolved")
            entry.range_method = "unresolved_end"
        entry.parse_warnings = list(dict.fromkeys(warnings))
    return rows
