"""Cached PDF note-link extraction for Feature #18E-B."""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.golden_mbrs_dataset import discover_golden_cases, load_normalized_extraction_rows
from services.pdf_row_context_extraction import (
    NUMERIC_ROW_TYPES,
    _case_selected,
    _sample_display_name,
    extract_row_contexts_for_case,
)
from services.pdf_xbrl_deterministic_alignment import clean_text, normalize_label


SAFETY = {
    "external_llm_called": False,
    "external_provider_called": False,
    "azure_di_live_call_made": False,
    "database_mutated": False,
    "production_behavior_changed": False,
    "api_changed": False,
    "ui_changed": False,
    "xbrl_generated": False,
    "arelle_run": False,
    "auto_applied": False,
    "confirmed_tag_id_mutated": False,
}

NOTE_LABEL_RE = re.compile(r"\bnotes?\s*(?:no\.?|number|#|:|-)?\s*(\d{1,2}[A-Za-z]?)\b", re.IGNORECASE)
PAREN_NOTE_RE = re.compile(r"\((?:\s*notes?\s*)?(\d{1,2}[A-Za-z]?)\s*\)", re.IGNORECASE)
NOTE_HEADING_RE = re.compile(r"^\s*(\d{1,2}[A-Za-z]?)\s*[\.\)]?\s+(.+?)\s*$", re.IGNORECASE)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _unique(values: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value or "").strip()))


def _candidate_id(row: Mapping[str, Any]) -> str | None:
    for key in ("original_candidate_id", "source_candidate_id", "candidate_id", "mapping_input_id", "row_id"):
        if row.get(key):
            return str(row[key])
    normalization = (row.get("provenance") or {}).get("azure_di_normalization") or {}
    if normalization.get("original_candidate_id"):
        return str(normalization["original_candidate_id"])
    return None


def _note_number_valid(value: str) -> bool:
    number = re.sub(r"[^0-9]", "", str(value or ""))
    parsed = _safe_int(number)
    return parsed is not None and 0 < parsed <= 60


def _normalize_note_number(value: Any) -> str | None:
    text = str(value or "").strip()
    match = re.search(r"\d{1,2}[A-Za-z]?", text)
    if not match:
        return None
    note = match.group(0).upper()
    return note if _note_number_valid(note) else None


def extract_note_references_from_label(value: Any) -> list[str]:
    """Extract explicit note references from a label or text snippet."""
    text = str(value or "")
    notes: list[str] = []
    for match in NOTE_LABEL_RE.finditer(text):
        normalized = _normalize_note_number(match.group(1))
        if normalized:
            notes.append(normalized)
    for match in PAREN_NOTE_RE.finditer(text):
        normalized = _normalize_note_number(match.group(1))
        if normalized:
            notes.append(normalized)
    return _unique(notes)


def extract_note_references_from_row(row: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    notes: list[str] = []
    reasons: list[str] = []
    for key in ("label", "text", "source_snippet", "statement_section"):
        found = extract_note_references_from_label(row.get(key))
        if found:
            notes.extend(found)
            reasons.append(f"{key}_note_reference")
    provenance = row.get("provenance") or {}
    for key in ("ignored_note_values", "note_values", "note_column_values"):
        for value in provenance.get(key) or []:
            normalized = _normalize_note_number(value)
            if normalized:
                notes.append(normalized)
                reasons.append(f"provenance_{key}")
    for cell in provenance.get("cells") or []:
        if not isinstance(cell, Mapping):
            continue
        header = normalize_label(cell.get("header") or cell.get("column_header") or "")
        content = str(cell.get("content") or "").strip()
        if "note" in header or (content.isdigit() and len(content) <= 2 and normalize_label(row.get("label")) not in {content}):
            normalized = _normalize_note_number(content)
            if normalized:
                notes.append(normalized)
                reasons.append("provenance_cell_note_value")
    return _unique(notes), _unique(reasons)


def _note_heading_candidate(row: Mapping[str, Any]) -> tuple[str, str] | None:
    values = [
        row.get("statement_section"),
        row.get("label"),
        row.get("text"),
        row.get("source_snippet"),
    ]
    for value in values:
        text = clean_text(value)
        if not text:
            continue
        match = NOTE_HEADING_RE.match(text)
        if not match:
            continue
        note_number = _normalize_note_number(match.group(1))
        title = clean_text(match.group(2))
        if not note_number or not title:
            continue
        title_norm = normalize_label(title)
        if not title_norm or "december" in title_norm or "financial statements" in title_norm:
            continue
        return note_number, title
    return None


def extract_note_headings(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    headings: dict[str, dict[str, Any]] = {}
    for row in rows:
        candidate = _note_heading_candidate(row)
        if not candidate:
            continue
        number, title = candidate
        headings.setdefault(
            number,
            {
                "note_number": number,
                "note_title": title,
                "note_page": _safe_int(row.get("page_number") or row.get("pdf_page")),
                "note_section_label": clean_text(row.get("statement_section") or row.get("label")),
                "source_row_id": _candidate_id(row),
            },
        )
    return headings


def _context_index_by_source(row_contexts: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    index: dict[str, list[Mapping[str, Any]]] = {}
    for context in row_contexts:
        source_id = str(context.get("source_row_id") or "")
        if source_id:
            index.setdefault(source_id, []).append(context)
    return index


def _confidence(reasons: Sequence[str], heading: Mapping[str, Any] | None) -> float:
    score = 0.55
    if any("provenance" in reason for reason in reasons):
        score += 0.25
    if any("label" in reason for reason in reasons):
        score += 0.15
    if heading:
        score += 0.1
    return round(min(score, 0.95), 4)


def extract_note_links_for_case(
    *,
    sample_id: str,
    company_name: str,
    rows: Sequence[Mapping[str, Any]],
    row_contexts: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return one note link per row-value observation and note reference."""
    contexts = list(row_contexts) if row_contexts is not None else extract_row_contexts_for_case(
        sample_id=sample_id,
        company_name=company_name,
        rows=rows,
    )
    contexts_by_source = _context_index_by_source(contexts)
    headings = extract_note_headings(rows)
    links: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("row_type") or "") not in NUMERIC_ROW_TYPES:
            continue
        source_id = _candidate_id(row)
        if not source_id:
            continue
        note_numbers, reasons = extract_note_references_from_row(row)
        if not note_numbers:
            continue
        for context in contexts_by_source.get(source_id, []):
            for note_number in note_numbers:
                heading = headings.get(note_number)
                links.append(
                    {
                        "sample_id": sample_id,
                        "company_name": company_name,
                        "row_id": context.get("row_id"),
                        "source_row_id": source_id,
                        "original_label": context.get("original_label") or clean_text(row.get("label")),
                        "normalized_label": context.get("normalized_label") or normalize_label(row.get("label")),
                        "statement_family": context.get("statement_family"),
                        "section_block": context.get("section_block"),
                        "note_number": note_number,
                        "note_title": (heading or {}).get("note_title"),
                        "note_page": (heading or {}).get("note_page"),
                        "note_section_label": (heading or {}).get("note_section_label"),
                        "note_link_confidence": _confidence(reasons, heading),
                        "note_link_reasons": _unique([*reasons, "cached_note_link_extraction"]),
                    }
                )
    links.sort(key=lambda item: (str(item.get("sample_id")), str(item.get("row_id")), str(item.get("note_number"))))
    return links


def load_pdf_note_links(
    *,
    dataset_dir: str | Path,
    include_samples: Sequence[str] = (),
    exclude_samples: Sequence[str] = (),
    include_outlier: bool = False,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    for case in discover_golden_cases(dataset_dir):
        sample_id = str(case.get("case_id") or "")
        selected, reason = _case_selected(
            case,
            include_samples=include_samples,
            exclude_samples=exclude_samples,
            include_outlier=include_outlier,
        )
        if not selected:
            samples.append({"sample_id": sample_id, "status": "skipped", "reason": reason, "note_links": 0})
            continue
        rows, sources = load_normalized_extraction_rows(case)
        company_name = _sample_display_name(case)
        contexts = extract_row_contexts_for_case(sample_id=sample_id, company_name=company_name, rows=rows)
        sample_links = extract_note_links_for_case(
            sample_id=sample_id,
            company_name=company_name,
            rows=rows,
            row_contexts=contexts,
        )
        samples.append(
            {
                "sample_id": sample_id,
                "company_name": company_name,
                "status": "included",
                "reason": reason,
                "pdf_rows_found": len(rows),
                "note_links": len(sample_links),
                "normalized_extraction_sources": sources,
            }
        )
        links.extend(sample_links)
    return {"samples": samples, "note_links": links}


def note_link_index(note_links: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    for link in note_links:
        key = (str(link.get("sample_id") or ""), str(link.get("row_id") or ""))
        if key not in index:
            index[key] = link
    return index


def summarize_note_links(note_links: Sequence[Mapping[str, Any]], samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    labels = Counter(str(item.get("normalized_label") or "") for item in note_links)
    notes = Counter(str(item.get("note_number") or "") for item in note_links)
    with_titles = sum(1 for item in note_links if item.get("note_title"))
    high_confidence = sum(1 for item in note_links if float(item.get("note_link_confidence") or 0) >= 0.8)
    return {
        "feature": "18E-B",
        "total_note_links": len(note_links),
        "included_samples": sum(1 for item in samples if item.get("status") == "included"),
        "note_links_with_titles": with_titles,
        "high_confidence_note_links": high_confidence,
        "safe_for_auto_apply_count": 0,
        "top_note_numbers": [{"note_number": note, "count": count} for note, count in notes.most_common(20) if note],
        "top_note_linked_labels": [{"normalized_label": label, "count": count} for label, count in labels.most_common(30) if label],
        "per_sample_summary": samples,
        "safety": SAFETY,
    }


def build_note_link_report(
    *,
    dataset_dir: str | Path,
    include_samples: Sequence[str] = (),
    exclude_samples: Sequence[str] = (),
    include_outlier: bool = False,
) -> dict[str, Any]:
    loaded = load_pdf_note_links(
        dataset_dir=dataset_dir,
        include_samples=include_samples,
        exclude_samples=exclude_samples,
        include_outlier=include_outlier,
    )
    return {
        "run_metadata": {
            "feature": "18E-B",
            "generated_at": _utc_now(),
            "dataset_dir": str(dataset_dir),
            "include_samples": list(include_samples),
            "exclude_samples": list(exclude_samples),
            "include_outlier": include_outlier,
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": summarize_note_links(loaded["note_links"], loaded["samples"]),
        "note_links": loaded["note_links"],
    }


def render_note_link_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF Note Links - Feature #18E-B",
        "",
        f"- Total note links: {summary.get('total_note_links', 0)}",
        f"- Links with note titles: {summary.get('note_links_with_titles', 0)}",
        f"- High-confidence links: {summary.get('high_confidence_note_links', 0)}",
        f"- Safe for auto-apply: {summary.get('safe_for_auto_apply_count', 0)}",
        "",
        "| Note | Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("top_note_numbers") or []:
        lines.append(f"| {item.get('note_number')} | {item.get('count')} |")
    lines.extend(["", "## Top Linked Labels", "", "| Label | Count |", "| --- | ---: |"])
    for item in summary.get("top_note_linked_labels") or []:
        lines.append(f"| {item.get('normalized_label')} | {item.get('count')} |")
    lines.append("")
    return "\n".join(lines)
