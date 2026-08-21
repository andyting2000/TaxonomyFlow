"""Report-only Azure DI candidate normalization before mapping."""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from services.extraction_v2_azure_di_pipeline import (
    SOURCE_METHOD,
    TEXT_BLOCK_TIMEOUT_WARNING,
    is_amount_like,
    is_percent,
    parse_amount,
)
from services.extraction_v2_azure_di_sandbox import no_side_effect_metadata
from services.extraction_v2_duplicate_resolver import (
    render_duplicate_conflict_markdown,
    resolve_extraction_v2_duplicates,
)
from services.extraction_v2_mapping_handoff import (
    build_mapping_handoff_reports,
    render_candidates_markdown as render_mapping_handoff_markdown,
)
from services.extraction_v2_manual_review_policy import (
    build_manual_review_policy_reports,
    render_queue_markdown,
)
from services.extraction_v2_quality_analyzer import (
    analyze_candidate_quality_reports,
    render_candidate_quality_markdown,
)


NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
DEFAULT_INPUT_REPORT = Path("reports/azure_di_sandbox_extraction_v2_report_13x.json")
DEFAULT_OUTPUT_DIR = Path("reports")
NORMALIZATION_LOG_INTERVAL = 100
TEXT_BLOCK_MERGE_LOG_INTERVAL = 1000
MAX_TEXT_BLOCK_MERGE_COMPARISONS = 100000

TOC_SECTION_RE = re.compile(r"\b(index|contents?|page\s*no\.?)\b", re.IGNORECASE)
TOC_ENTRY_RE = re.compile(
    r"^\s*(?:\d+[\.)]?\s+)?[A-Z][A-Z0-9'&().,\-/ ]{2,}\s+\d{1,3}(?:\s*[-]\s*\d{1,3})?\s*$"
)
ENUM_ONLY_RE = re.compile(r"^\s*(?:\d+[\.)]?|[ivxlcdm]+[\.)]?|[A-Za-z][\.)]?|\([a-zivxlcdm]+\))\s*$", re.IGNORECASE)
YEAR_ONLY_RE = re.compile(r"^(?:19|20)\d{2}$")
PAGE_HEADER_RE = re.compile(
    r"\b(registration\s+no\.?|company\s+no\.?|incorporated\s+in\s+malaysia|sdn\.?\s*bhd\.?)\b",
    re.IGNORECASE,
)
USEFUL_SECTION_RE = re.compile(
    r"\b("
    r"directors?'?\s+report|statement\s+by\s+directors|statutory\s+declaration|financial\s+results|"
    r"statement\s+of\s+financial\s+position|statement\s+of\s+comprehensive\s+income|"
    r"statement\s+of\s+changes\s+in\s+equity|statement\s+of\s+cash\s+flows?|"
    r"notes\s+to\s+the\s+financial\s+statements|basis\s+of\s+preparation|"
    r"significant\s+accounting\s+polic|corporate\s+information|principal\s+activit|"
    r"other\s+receivable|contributed\s+share\s+capital|other\s+payable|amount\s+due\s+to\s+director|"
    r"bank\s+overdraft|related\s+party\s+disclosures"
    r")\b",
    re.IGNORECASE,
)
NARRATIVE_SECTION_RE = re.compile(
    r"\b(directors?'?\s+report|statement\s+by\s+directors|statutory\s+declaration|notes\s+to\s+the\s+financial\s+statements|"
    r"accounting\s+polic|basis\s+of\s+preparation|corporate\s+information|principal\s+activit|"
    r"other\s+statutory\s+information|directors?'?\s+benefits|directors?'?\s+interests|dividends)\b",
    re.IGNORECASE,
)
STATEMENT_SECTION_RE = re.compile(
    r"\b(statement\s+of\s+financial\s+position|statement\s+of\s+comprehensive\s+income|"
    r"statement\s+of\s+changes\s+in\s+equity|statement\s+of\s+cash\s+flows?|notes\s+to\s+the\s+financial\s+statements)\b",
    re.IGNORECASE,
)
TOTAL_RE = re.compile(r"\b(total|subtotal|sub-total|net\s+assets?|net\s+loss|loss\s+before|loss\s+after|capital\s+deficiency)\b", re.IGNORECASE)

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 3)


def _timeout_exceeded(started: float, timeout_seconds: float | None) -> bool:
    if timeout_seconds is None:
        return False
    return timeout_seconds <= 0 or (time.monotonic() - started) > timeout_seconds


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_label(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


@dataclass(frozen=True)
class NormalizationOutputPaths:
    extraction_json: Path
    extraction_md: Path
    quality_json: Path
    quality_md: Path
    duplicate_json: Path
    duplicate_md: Path
    manual_review_queue_json: Path
    manual_review_queue_md: Path
    mapping_handoff_json: Path
    mapping_handoff_md: Path
    summary_json: Path
    summary_md: Path


def output_paths_from_prefix(output_prefix: str | Path | None = None) -> NormalizationOutputPaths:
    if output_prefix is None:
        root = DEFAULT_OUTPUT_DIR
        return NormalizationOutputPaths(
            extraction_json=root / "azure_di_normalized_extraction_v2_report_13y.json",
            extraction_md=root / "azure_di_normalized_extraction_v2_report_13y.md",
            quality_json=root / "azure_di_normalized_candidate_quality_13y.json",
            quality_md=root / "azure_di_normalized_candidate_quality_13y.md",
            duplicate_json=root / "azure_di_normalized_duplicate_conflict_13y.json",
            duplicate_md=root / "azure_di_normalized_duplicate_conflict_13y.md",
            manual_review_queue_json=root / "azure_di_normalized_manual_review_queue_13y.json",
            manual_review_queue_md=root / "azure_di_normalized_manual_review_queue_13y.md",
            mapping_handoff_json=root / "azure_di_normalized_mapping_handoff_13y.json",
            mapping_handoff_md=root / "azure_di_normalized_mapping_handoff_13y.md",
            summary_json=root / "azure_di_normalization_summary_13y.json",
            summary_md=root / "azure_di_normalization_summary_13y.md",
        )
    prefix = Path(output_prefix)
    return NormalizationOutputPaths(
        extraction_json=Path(f"{prefix}_extraction_v2_report_13y.json"),
        extraction_md=Path(f"{prefix}_extraction_v2_report_13y.md"),
        quality_json=Path(f"{prefix}_candidate_quality_13y.json"),
        quality_md=Path(f"{prefix}_candidate_quality_13y.md"),
        duplicate_json=Path(f"{prefix}_duplicate_conflict_13y.json"),
        duplicate_md=Path(f"{prefix}_duplicate_conflict_13y.md"),
        manual_review_queue_json=Path(f"{prefix}_manual_review_queue_13y.json"),
        manual_review_queue_md=Path(f"{prefix}_manual_review_queue_13y.md"),
        mapping_handoff_json=Path(f"{prefix}_mapping_handoff_13y.json"),
        mapping_handoff_md=Path(f"{prefix}_mapping_handoff_13y.md"),
        summary_json=Path(f"{prefix}_normalization_summary_13y.json"),
        summary_md=Path(f"{prefix}_normalization_summary_13y.md"),
    )


def _candidate_sort_key(candidate: Mapping[str, Any], fallback_index: int) -> tuple[int, int, int, int]:
    provenance = candidate.get("provenance") or {}
    paragraph = provenance.get("paragraph_index")
    table = provenance.get("table_index")
    row = provenance.get("row_index")
    if paragraph is not None:
        return (int(candidate.get("page_number") or 0), 1, int(paragraph or 0), fallback_index)
    if table is not None or row is not None:
        return (int(candidate.get("page_number") or 0), 2, int(row or 0), fallback_index)
    return (int(candidate.get("page_number") or 0), 3, fallback_index, fallback_index)


def _original_candidate_id(candidate: Mapping[str, Any], case_id: str, case_index: int, global_index: int) -> str:
    return str(
        candidate.get("original_candidate_id")
        or candidate.get("candidate_id")
        or f"{case_id}:candidate:{case_index}:{global_index}"
    )


def _flatten_with_ids(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    global_index = 0
    for case_report in report.get("case_reports") or []:
        case_id = str(case_report.get("case_id") or "")
        for case_index, candidate in enumerate(case_report.get("candidates") or []):
            item = deepcopy(candidate)
            item.setdefault("case_id", case_id)
            item["_original_case_index"] = case_index
            item["_original_global_index"] = global_index
            item["_original_candidate_id"] = _original_candidate_id(item, case_id, case_index, global_index)
            rows.append(item)
            global_index += 1
    return rows


def _row_type_counts(candidates: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(candidate.get("row_type") or "unknown") for candidate in candidates).items()))


def _is_toc_or_index(candidate: Mapping[str, Any]) -> bool:
    label = clean_text(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
    section = clean_text(candidate.get("statement_section"))
    page = int(candidate.get("page_number") or 0)
    row_type = str(candidate.get("row_type") or "")
    if normalize_label(section) in {"index contents", "index", "contents"}:
        return True
    if row_type in NUMERIC_ROW_TYPES:
        return False
    if page == 1 and TOC_SECTION_RE.search(label):
        return True
    if page == 1 and TOC_ENTRY_RE.fullmatch(label) and not is_amount_like(label):
        return True
    if page == 1 and ENUM_ONLY_RE.fullmatch(label):
        return True
    return False


def _is_page_header_footer(candidate: Mapping[str, Any], repeated_labels: set[str]) -> bool:
    label = clean_text(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
    normalized = normalize_label(label)
    if not label:
        return False
    if PAGE_HEADER_RE.search(label):
        return True
    return normalized in repeated_labels and len(normalized) >= 8 and not USEFUL_SECTION_RE.search(label)


def _is_weak_heading(candidate: Mapping[str, Any]) -> bool:
    label = clean_text(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
    if not label:
        return True
    if USEFUL_SECTION_RE.search(label):
        return False
    if ENUM_ONLY_RE.fullmatch(label) or YEAR_ONLY_RE.fullmatch(label):
        return True
    if parse_amount(label) is not None or is_percent(label):
        return True
    if normalize_label(label) in {"rm", "myr", "note", "notes", "at", "amount", "shares"}:
        return True
    return False


def _is_useful_section_heading(candidate: Mapping[str, Any]) -> bool:
    label = clean_text(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
    return bool(USEFUL_SECTION_RE.search(label)) and not _is_toc_or_index(candidate)


def _is_section_event(candidate: Mapping[str, Any]) -> bool:
    label = clean_text(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
    section = clean_text(candidate.get("statement_section"))
    return bool(USEFUL_SECTION_RE.search(label) or USEFUL_SECTION_RE.search(section)) and not _is_toc_or_index(candidate)


def _canonical_section(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    normalized = normalize_label(text)
    aliases = {
        "directors report": "Directors Report",
        "director s report": "Directors Report",
        "statement by directors": "Statement by Directors",
        "statutory declaration": "Statutory Declaration",
        "statement of financial position": "Statement of Financial Position",
        "statement of comprehensive income": "Statement of Comprehensive Income",
        "statement of changes in equity": "Statement of Changes in Equity",
        "statement of cash flows": "Statement of Cash Flows",
        "statement of cash flow": "Statement of Cash Flows",
        "notes to the financial statements": "Notes to the Financial Statements",
        "basis of preparation": "Basis of Preparation",
        "significant accounting policies": "Significant Accounting Policies",
        "corporate information": "Corporate Information",
        "principal activity": "Principal Activity",
        "principal activities": "Principal Activities",
        "financial results": "Financial Results",
        "other statutory information": "Other Statutory Information",
    }
    for key, section in aliases.items():
        if key in normalized:
            return section
    if USEFUL_SECTION_RE.search(text):
        return re.sub(r"\s+", " ", text.title().replace("Sdn. Bhd.", "SDN. BHD.")).strip()
    return text


def _page_statement_sections(candidates: list[dict[str, Any]]) -> dict[int, str]:
    page_sections: dict[int, str] = {}
    for candidate in candidates:
        if str(candidate.get("row_type") or "") not in {"heading", "metadata"}:
            continue
        page = int(candidate.get("page_number") or 0)
        text = clean_text(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
        section_text = clean_text(candidate.get("statement_section"))
        match = STATEMENT_SECTION_RE.search(text) or STATEMENT_SECTION_RE.search(section_text)
        if page and match:
            page_sections.setdefault(page, _canonical_section(match.group(1)) or match.group(1))
    return page_sections


def _section_at_candidate(
    candidate: Mapping[str, Any],
    *,
    original_index: int,
    section_events: list[tuple[tuple[int, int, int, int], str]],
    page_sections: Mapping[int, str],
) -> str | None:
    page = int(candidate.get("page_number") or 0)
    key = _candidate_sort_key(candidate, original_index)
    section = _canonical_section(candidate.get("statement_section"))
    same_page_numeric_section = None
    for event_key, event_section in section_events:
        if str(candidate.get("row_type") or "") in NUMERIC_ROW_TYPES and event_key[0] != key[0]:
            continue
        if event_key <= key:
            section = event_section
            if str(candidate.get("row_type") or "") in NUMERIC_ROW_TYPES:
                same_page_numeric_section = event_section
        elif event_key[0] > key[0]:
            break
    if str(candidate.get("row_type") or "") in NUMERIC_ROW_TYPES:
        if same_page_numeric_section:
            return same_page_numeric_section
        if page in page_sections:
            return page_sections[page]
    if section:
        return section
    if page in page_sections:
        return page_sections[page]
    return None


def _build_section_events(candidates: list[dict[str, Any]]) -> list[tuple[tuple[int, int, int, int], str]]:
    events: list[tuple[tuple[int, int, int, int], str]] = []
    for candidate in candidates:
        if str(candidate.get("row_type") or "") != "heading":
            continue
        if not _is_section_event(candidate):
            continue
        label_text = clean_text(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
        section = (
            _canonical_section(label_text)
            if USEFUL_SECTION_RE.search(label_text)
            else _canonical_section(candidate.get("statement_section"))
        )
        if section:
            events.append((_candidate_sort_key(candidate, int(candidate["_original_global_index"])), section))
    return sorted(events, key=lambda item: item[0])


def _repeated_page_header_labels(candidates: list[dict[str, Any]]) -> set[str]:
    pages_by_label: dict[str, set[int]] = defaultdict(set)
    for candidate in candidates:
        label = normalize_label(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
        if label:
            pages_by_label[label].add(int(candidate.get("page_number") or 0))
    return {label for label, pages in pages_by_label.items() if len(pages) >= 3}


def _text_label(section: str | None, text: str) -> str:
    prefix = section or "Narrative Disclosure"
    words = clean_text(text).split()
    summary = " ".join(words[:10])
    if len(summary) > 90:
        summary = summary[:90].rsplit(" ", 1)[0]
    return f"{prefix}: {summary}" if summary else prefix


def _normalize_numeric_candidate(candidate: dict[str, Any], reasons: list[str]) -> str:
    row_type = str(candidate.get("row_type") or "unknown")
    label = clean_text(candidate.get("label"))
    value = parse_amount(candidate.get("value"))
    previous = parse_amount(candidate.get("previous_value"))
    provenance = candidate.get("provenance") or {}
    percentages = [item for item in provenance.get("percentage_cells") or [] if clean_text(item)]
    if is_percent(candidate.get("previous_value")):
        candidate["previous_value"] = None
        candidate["row_type"] = "numeric_fact"
        candidate.setdefault("warnings", [])
        _append_unique(candidate["warnings"], "percentage_previous_value_removed")
        reasons.append("percentage-only previous_value was not treated as a prior-year amount.")
        return "keep_with_warning"
    if row_type == "numeric_fact" and previous is not None:
        candidate["row_type"] = "comparative_numeric_fact"
        reasons.append("numeric candidate had previous_value and was normalized to comparative.")
        return "convert_numeric_to_comparative"
    if previous is not None and percentages and len(provenance.get("raw_amounts") or []) <= 1:
        candidate["previous_value"] = None
        candidate["row_type"] = "numeric_fact"
        candidate.setdefault("warnings", [])
        _append_unique(candidate["warnings"], "percentage_column_not_prior_year")
        reasons.append("percentage-only column was not treated as prior-year amount.")
        return "keep_with_warning"
    if TOTAL_RE.search(label) and row_type in {"numeric_fact", "comparative_numeric_fact"}:
        candidate["row_type"] = "subtotal_or_total"
        reasons.append("total/subtotal label normalized to subtotal_or_total.")
        return "keep"
    if value is None and previous is None:
        candidate["row_type"] = "heading" if USEFUL_SECTION_RE.search(label) else "metadata"
        candidate["value"] = None
        candidate["previous_value"] = None
        reasons.append("numeric-like row had no numeric amount and was downgraded.")
        return "convert_heading_like_fact_to_heading" if candidate["row_type"] == "heading" else "downgrade_to_metadata"
    if (YEAR_ONLY_RE.fullmatch(label) or ENUM_ONLY_RE.fullmatch(label)) and (value is not None or previous is not None):
        candidate["row_type"] = "metadata"
        reasons.append("year/enumeration label with amount-like cell is context, not a fact.")
        return "downgrade_to_metadata"
    return "keep"


def _normalize_single_candidate(
    candidate: dict[str, Any],
    *,
    repeated_labels: set[str],
    section_events: list[tuple[tuple[int, int, int, int], str]],
    page_sections: Mapping[int, str],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    original = {key: deepcopy(value) for key, value in candidate.items() if not key.startswith("_")}
    original_id = candidate["_original_candidate_id"]
    cleaned = deepcopy(original)
    cleaned["original_candidate_id"] = original_id
    cleaned.setdefault("source_method", SOURCE_METHOD)
    cleaned.setdefault("extraction_method", SOURCE_METHOD)
    cleaned.setdefault("warnings", [])
    reasons: list[str] = []
    action = "keep"
    retained = True
    row_type = str(cleaned.get("row_type") or "unknown")
    label = clean_text(cleaned.get("label") or cleaned.get("text") or cleaned.get("source_snippet"))

    inherited_section = _section_at_candidate(
        cleaned,
        original_index=int(candidate["_original_global_index"]),
        section_events=section_events,
        page_sections=page_sections,
    )
    if inherited_section:
        cleaned["statement_section"] = inherited_section

    if _is_toc_or_index(cleaned):
        action = "suppress_index_or_toc_row"
        retained = False
        reasons.append("table of contents/index row excluded from normalized mapping input.")
    elif _is_page_header_footer(cleaned, repeated_labels):
        action = "keep_for_context_only" if row_type == "metadata" else "downgrade_to_metadata"
        cleaned["row_type"] = "metadata"
        retained = False
        reasons.append("repeated page header/footer retained only in audit trail.")
    elif row_type == "heading":
        if _is_weak_heading(cleaned):
            action = "downgrade_to_metadata"
            cleaned["row_type"] = "metadata"
            retained = False
            reasons.append("weak heading/table fragment is context, not a mapping candidate.")
        elif _is_useful_section_heading(cleaned):
            action = "keep"
            cleaned["normalization_heading_class"] = "useful_section_heading"
            reasons.append("useful section heading preserved for section inheritance.")
        else:
            action = "keep_for_context_only"
            cleaned["row_type"] = "metadata"
            retained = False
            reasons.append("non-section heading retained only as context.")
    elif row_type == "metadata":
        if _is_toc_or_index(cleaned):
            action = "suppress_index_or_toc_row"
            retained = False
            reasons.append("index metadata suppressed from normalized rows.")
        elif _is_page_header_footer(cleaned, repeated_labels):
            action = "keep_for_context_only"
            retained = False
            reasons.append("page header/footer metadata retained only in audit trail.")
    elif row_type == "text_block":
        text = clean_text(cleaned.get("text") or cleaned.get("source_snippet"))
        if _is_toc_or_index(cleaned) or (len(text.split()) <= 8 and TOC_ENTRY_RE.fullmatch(text)):
            action = "suppress_index_or_toc_row"
            retained = False
            reasons.append("index entry was not converted to a text block.")
        elif len(text.split()) < 8 and not NARRATIVE_SECTION_RE.search(clean_text(cleaned.get("statement_section"))):
            action = "downgrade_to_metadata"
            cleaned["row_type"] = "metadata"
            retained = False
            reasons.append("short weak text block downgraded to context.")
        else:
            cleaned["label"] = _text_label(cleaned.get("statement_section"), text)
            reasons.append("text block label normalized with section and text preview.")
    elif row_type in NUMERIC_ROW_TYPES:
        action = _normalize_numeric_candidate(cleaned, reasons)

    cleaned.setdefault("provenance", {})
    cleaned["provenance"] = deepcopy(cleaned.get("provenance") or {})
    cleaned["provenance"]["azure_di_normalization"] = {
        "feature": "13Y",
        "action": action,
        "original_candidate_id": original_id,
        "action_reasons": list(reasons),
    }
    cleaned["normalization_action"] = action
    cleaned["normalization_reasons"] = list(reasons)

    audit = {
        "original_candidate_id": original_id,
        "original_global_index": candidate["_original_global_index"],
        "original_case_index": candidate["_original_case_index"],
        "case_id": cleaned.get("case_id"),
        "page_number": cleaned.get("page_number"),
        "original_row_type": original.get("row_type"),
        "proposed_row_type": cleaned.get("row_type"),
        "original_label": original.get("label"),
        "normalized_label": cleaned.get("label"),
        "original_text": original.get("text"),
        "normalized_text": cleaned.get("text"),
        "original_statement_section": original.get("statement_section"),
        "normalized_statement_section": cleaned.get("statement_section"),
        "action": action,
        "action_reasons": reasons,
        "confidence_readiness_impact": _confidence_impact(action),
        "retained_in_normalized_rows": retained,
        "source_provenance": deepcopy(original.get("provenance") or {}),
        "page_number_provenance": {
            "page_number": original.get("page_number"),
            "table_index": (original.get("provenance") or {}).get("table_index"),
            "row_index": (original.get("provenance") or {}).get("row_index"),
            "cell_indexes": (original.get("provenance") or {}).get("cell_indexes"),
            "paragraph_index": (original.get("provenance") or {}).get("paragraph_index"),
        },
        "original_candidate": original,
        "normalized_candidate": deepcopy(cleaned) if retained else None,
    }
    return (cleaned if retained else None), audit


def _confidence_impact(action: str) -> str:
    if action in {"suppress_index_or_toc_row", "keep_for_context_only", "downgrade_to_metadata", "downgrade_to_heading"}:
        return "reduces_mapping_noise"
    if action in {"convert_numeric_to_comparative", "convert_heading_like_fact_to_heading", "merge_text_block_fragment"}:
        return "improves_candidate_shape"
    if action in {"manual_review_required", "keep_with_warning"}:
        return "preserves_candidate_with_review_signal"
    return "preserves_candidate"


def _can_merge_text_blocks(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    if left.get("row_type") != "text_block" or right.get("row_type") != "text_block":
        return False
    if clean_text(left.get("statement_section")) != clean_text(right.get("statement_section")):
        return False
    if int(left.get("page_number") or 0) != int(right.get("page_number") or 0):
        return False
    left_index = ((left.get("provenance") or {}).get("paragraph_index"))
    right_index = ((right.get("provenance") or {}).get("paragraph_index"))
    if left_index is None or right_index is None or int(right_index) - int(left_index) > 2:
        return False
    left_text = clean_text(left.get("text"))
    right_text = clean_text(right.get("text"))
    return len(left_text.split()) < 18 or len(right_text.split()) < 18 or left_text.endswith((":",";"))


def _merge_text_blocks(
    candidates: list[dict[str, Any]],
    audit: list[dict[str, Any]],
    *,
    run_id: str | None = None,
    started: float | None = None,
    timeout_seconds: float | None = None,
    max_merge_comparisons: int = MAX_TEXT_BLOCK_MERGE_COMPARISONS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int, bool]:
    merged: list[dict[str, Any]] = []
    updated_audit = deepcopy(audit)
    audit_by_id = {entry["original_candidate_id"]: entry for entry in updated_audit}
    merge_count = 0
    started = started or time.monotonic()
    for index, candidate in enumerate(candidates, start=1):
        if index > max_merge_comparisons:
            logger.warning(
                "Azure DI report normalization text block merge comparison limit reached: run_id=%s processed=%s limit=%s",
                run_id,
                index - 1,
                max_merge_comparisons,
            )
            merged.extend(candidates[index - 1 :])
            return merged, updated_audit, merge_count, True
        if index == 1 or index == len(candidates) or index % TEXT_BLOCK_MERGE_LOG_INTERVAL == 0:
            if _timeout_exceeded(started, timeout_seconds):
                logger.warning(
                    "%s run_id=%s stage=text_block_merge processed=%s total=%s elapsed_seconds=%s",
                    TEXT_BLOCK_TIMEOUT_WARNING,
                    run_id,
                    index - 1,
                    len(candidates),
                    _elapsed(started),
                )
                merged.extend(candidates[index - 1 :])
                return merged, updated_audit, merge_count, True
        if merged and _can_merge_text_blocks(merged[-1], candidate):
            target = merged[-1]
            source_id = candidate.get("original_candidate_id")
            target["text"] = clean_text(f"{target.get('text')} {candidate.get('text')}")
            target["source_snippet"] = clean_text(f"{target.get('source_snippet')} {candidate.get('source_snippet') or candidate.get('text')}")[:1000]
            target["label"] = _text_label(target.get("statement_section"), target["text"])
            target.setdefault("warnings", [])
            _append_unique(target["warnings"], "merged_adjacent_text_block_fragment")
            target.setdefault("provenance", {})
            merged_ids = target["provenance"].setdefault("merged_candidate_ids", [])
            _append_unique(merged_ids, str(source_id))
            if source_id in audit_by_id:
                entry = audit_by_id[str(source_id)]
                entry["action"] = "merge_text_block_fragment"
                entry["action_reasons"].append("adjacent short narrative fragment merged into previous text block in same section.")
                entry["retained_in_normalized_rows"] = False
                entry["normalized_candidate"] = None
                entry["confidence_readiness_impact"] = _confidence_impact("merge_text_block_fragment")
            merge_count += 1
            continue
        merged.append(candidate)
    return merged, updated_audit, merge_count, False


def normalize_azure_di_extraction_report(
    azure_di_report: Mapping[str, Any],
    *,
    run_id: str | None = None,
    input_report_path: str | Path | None = None,
    output_path: str | Path | None = None,
    text_blocks_enabled: bool = True,
    text_block_timeout_seconds: float | None = None,
    max_text_block_merge_comparisons: int = MAX_TEXT_BLOCK_MERGE_COMPARISONS,
) -> tuple[dict[str, Any], dict[str, Any]]:
    started = time.monotonic()
    logger.info("Azure DI report normalization started: run_id=%s", run_id)
    flatten_started = time.monotonic()
    original_candidates = _flatten_with_ids(azure_di_report)
    logger.info(
        "Azure DI report normalization candidate flatten finished: run_id=%s candidate_count=%s elapsed_seconds=%s",
        run_id,
        len(original_candidates),
        _elapsed(flatten_started),
    )

    section_started = time.monotonic()
    logger.info(
        "Azure DI report normalization heading/section precompute started: run_id=%s candidate_count=%s",
        run_id,
        len(original_candidates),
    )
    repeated_labels = _repeated_page_header_labels(original_candidates)
    section_events = _build_section_events(original_candidates)
    page_sections = _page_statement_sections(original_candidates)
    logger.info(
        "Azure DI report normalization heading/section precompute finished: run_id=%s repeated_labels=%s section_events=%s page_sections=%s elapsed_seconds=%s",
        run_id,
        len(repeated_labels),
        len(section_events),
        len(page_sections),
        _elapsed(section_started),
    )

    normalized_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    audit: list[dict[str, Any]] = []
    candidate_started = time.monotonic()
    logger.info(
        "Azure DI report normalization candidate loop started: run_id=%s candidate_count=%s",
        run_id,
        len(original_candidates),
    )
    for index, candidate in enumerate(original_candidates, start=1):
        if (
            index == 1
            or index == len(original_candidates)
            or index % NORMALIZATION_LOG_INTERVAL == 0
        ):
            provenance = candidate.get("provenance") or {}
            logger.info(
                "Azure DI report normalization candidate progress: run_id=%s candidate_index=%s/%s page_number=%s row_type=%s table_index=%s row_index=%s paragraph_index=%s elapsed_seconds=%s",
                run_id,
                index,
                len(original_candidates),
                candidate.get("page_number"),
                candidate.get("row_type"),
                provenance.get("table_index"),
                provenance.get("row_index"),
                provenance.get("paragraph_index"),
                _elapsed(candidate_started),
            )
        normalized, entry = _normalize_single_candidate(
            candidate,
            repeated_labels=repeated_labels,
            section_events=section_events,
            page_sections=page_sections,
        )
        audit.append(entry)
        if normalized:
            normalized_by_case[str(normalized.get("case_id") or "")].append(normalized)
    normalized_total = sum(len(rows) for rows in normalized_by_case.values())
    logger.info(
        "Azure DI report normalization candidate loop finished: run_id=%s retained_candidates=%s audit_count=%s elapsed_seconds=%s",
        run_id,
        normalized_total,
        len(audit),
        _elapsed(candidate_started),
    )

    merged_by_case: dict[str, list[dict[str, Any]]] = {}
    merged_total = 0
    updated_audit = audit
    merge_started = time.monotonic()
    logger.info(
        "Azure DI report normalization text block merge started: run_id=%s case_count=%s",
        run_id,
        len(normalized_by_case),
    )
    merge_timed_out = False
    for case_id, candidates in normalized_by_case.items():
        candidates = sorted(candidates, key=lambda item: _candidate_sort_key(item, 0))
        if not text_blocks_enabled:
            logger.info(
                "Azure DI report normalization text block merge skipped: run_id=%s case_id=%s reason=disabled candidate_count=%s",
                run_id,
                case_id,
                len(candidates),
            )
            merged_by_case[case_id] = candidates
            continue
        if merge_timed_out or _timeout_exceeded(merge_started, text_block_timeout_seconds):
            if not merge_timed_out:
                logger.warning(
                    "%s run_id=%s stage=text_block_merge elapsed_seconds=%s",
                    TEXT_BLOCK_TIMEOUT_WARNING,
                    run_id,
                    _elapsed(merge_started),
                )
            merge_timed_out = True
            merged_by_case[case_id] = candidates
            continue
        merged, updated_audit, merge_count, case_timed_out = _merge_text_blocks(
            candidates,
            updated_audit,
            run_id=run_id,
            started=merge_started,
            timeout_seconds=text_block_timeout_seconds,
            max_merge_comparisons=max_text_block_merge_comparisons,
        )
        merged_by_case[case_id] = merged
        merged_total += merge_count
        merge_timed_out = merge_timed_out or case_timed_out
    logger.info(
        "Azure DI report normalization text block merge finished: run_id=%s merged_fragments=%s timed_out=%s elapsed_seconds=%s",
        run_id,
        merged_total,
        merge_timed_out,
        _elapsed(merge_started),
    )
    logger.info(
        "Azure DI report normalization duplicate/conflict cleanup skipped: run_id=%s reason=not_used_in_production_normalization",
        run_id,
    )

    build_started = time.monotonic()
    logger.info("Azure DI report normalization output build started: run_id=%s", run_id)
    normalized_report = _build_normalized_report(
        azure_di_report,
        normalized_by_case=merged_by_case,
        audit=updated_audit,
        run_id=run_id,
        input_report_path=input_report_path,
        output_path=output_path,
        merged_text_block_fragments=merged_total,
    )
    logger.info(
        "Azure DI report normalization output build finished: run_id=%s elapsed_seconds=%s",
        run_id,
        _elapsed(build_started),
    )
    summary_started = time.monotonic()
    logger.info("Azure DI report normalization summary build started: run_id=%s", run_id)
    summary = build_normalization_summary(
        original_report=azure_di_report,
        normalized_report=normalized_report,
        audit=updated_audit,
        gate_reports=None,
        input_report_path=input_report_path,
        output_path=None,
    )
    logger.info(
        "Azure DI report normalization summary build finished: run_id=%s elapsed_seconds=%s",
        run_id,
        _elapsed(summary_started),
    )
    logger.info(
        "Azure DI report normalization finished: run_id=%s normalized_candidates=%s elapsed_seconds=%s",
        run_id,
        sum(len(rows) for rows in merged_by_case.values()),
        _elapsed(started),
    )
    return normalized_report, summary


def _build_normalized_report(
    original_report: Mapping[str, Any],
    *,
    normalized_by_case: Mapping[str, list[dict[str, Any]]],
    audit: list[dict[str, Any]],
    run_id: str | None,
    input_report_path: str | Path | None,
    output_path: str | Path | None,
    merged_text_block_fragments: int,
) -> dict[str, Any]:
    report = deepcopy(dict(original_report))
    original_meta = dict((original_report.get("run_metadata") or {}))
    metadata = {
        **original_meta,
        **no_side_effect_metadata(),
        "feature": "13Y",
        "generated_at": utc_now_iso(),
        "run_id": run_id,
        "script": "scripts/normalize_azure_di_extraction_v2_candidates.py",
        "report_type": "azure_di_normalized_extraction_v2",
        "source_report_type": original_meta.get("report_type"),
        "input_report": str(input_report_path) if input_report_path else None,
        "output_path": str(output_path) if output_path else None,
        "provider": SOURCE_METHOD,
        "source_method": SOURCE_METHOD,
        "live_external_provider_call": False,
        "external_provider_calls": False,
        "live_model_calls": False,
        "azure_di_live_call_made": False,
        "huggingface_used": False,
        "openai_used": False,
        "approval_flag_used": False,
        "source_report_approval_flag_used": original_meta.get("approval_flag_used"),
    }
    report["run_metadata"] = metadata
    report["pipeline_name"] = "Azure DI Normalized Extraction v2 Candidates"

    case_reports = []
    all_candidates: list[dict[str, Any]] = []
    for case_report in original_report.get("case_reports") or []:
        case_id = str(case_report.get("case_id") or "")
        candidates = list(normalized_by_case.get(case_id, []))
        all_candidates.extend(candidates)
        updated = deepcopy({key: value for key, value in case_report.items() if key != "candidates"})
        updated["candidate_count"] = len(candidates)
        updated["azure_di_candidate_count"] = len(candidates)
        updated["row_type_counts"] = _row_type_counts(candidates)
        updated["candidates"] = candidates
        case_reports.append(updated)
    report["case_reports"] = case_reports
    report["sample_candidates"] = all_candidates[:25]

    before_counts = _row_type_counts(_flatten_with_ids(original_report))
    after_counts = _row_type_counts(all_candidates)
    aggregate = deepcopy(report.get("aggregate_metrics") or {})
    aggregate.update(_aggregate_candidate_metrics(all_candidates))
    report["aggregate_metrics"] = aggregate
    action_counts = Counter(entry["action"] for entry in audit)
    report["normalization"] = {
        "input_report": str(input_report_path) if input_report_path else None,
        "original_candidate_count": len(audit),
        "normalized_candidate_count": len(all_candidates),
        "before_row_type_counts": before_counts,
        "after_row_type_counts": after_counts,
        "action_counts": dict(sorted(action_counts.items())),
        "suppressed_candidates": sum(1 for entry in audit if not entry["retained_in_normalized_rows"]),
        "index_toc_rows_suppressed": action_counts.get("suppress_index_or_toc_row", 0),
        "page_header_footer_rows_downgraded": action_counts.get("keep_for_context_only", 0) + action_counts.get("downgrade_to_metadata", 0),
        "merged_text_block_fragments": merged_text_block_fragments,
        "candidate_audit_trail": audit,
    }
    report["limitations"] = [
        "Report-only Azure DI normalization; no production cutover.",
        "No Azure DI, Hugging Face, OpenAI, semantic matcher, DB, XBRL, Arelle, API, or UI call is performed.",
        "Suppressed candidates remain preserved in the normalization audit trail.",
    ]
    return report


def _aggregate_candidate_metrics(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(candidate.get("row_type") or "unknown") for candidate in candidates)
    return {
        "total_candidates": len(candidates),
        "total_candidate_rows": len(candidates),
        "numeric_candidate_count": counts.get("numeric_fact", 0),
        "comparative_numeric_candidate_count": counts.get("comparative_numeric_fact", 0),
        "subtotal_or_total_candidate_count": counts.get("subtotal_or_total", 0),
        "text_block_candidate_count": counts.get("text_block", 0),
        "heading_candidate_count": counts.get("heading", 0),
        "metadata_candidate_count": counts.get("metadata", 0),
        "unknown_candidate_count": counts.get("unknown", 0),
        "numeric_fact_count": counts.get("numeric_fact", 0),
        "comparative_numeric_fact_count": counts.get("comparative_numeric_fact", 0),
        "subtotal_or_total_count": counts.get("subtotal_or_total", 0),
        "text_block_count": counts.get("text_block", 0),
        "heading_count": counts.get("heading", 0),
        "metadata_count": counts.get("metadata", 0),
        "unknown_count": counts.get("unknown", 0),
        "row_type_counts": dict(sorted(counts.items())),
    }


def render_normalized_extraction_markdown(report: Mapping[str, Any]) -> str:
    aggregate = report.get("aggregate_metrics") or {}
    normalization = report.get("normalization") or {}
    lines = [
        "# Azure DI Normalized Extraction v2 Candidates - Feature #13Y",
        "",
        "## Summary",
        "",
        f"- Input report: {normalization.get('input_report')}",
        f"- Original candidates: {normalization.get('original_candidate_count', 0)}",
        f"- Normalized candidates: {normalization.get('normalized_candidate_count', 0)}",
        f"- Row type counts before: {normalization.get('before_row_type_counts', {})}",
        f"- Row type counts after: {normalization.get('after_row_type_counts', {})}",
        f"- Total candidates: {aggregate.get('total_candidates', 0)}",
        f"- Numeric facts: {aggregate.get('numeric_fact_count', 0)}",
        f"- Comparative numeric facts: {aggregate.get('comparative_numeric_fact_count', 0)}",
        f"- Subtotal/total: {aggregate.get('subtotal_or_total_count', 0)}",
        f"- Text blocks: {aggregate.get('text_block_count', 0)}",
        f"- Headings: {aggregate.get('heading_count', 0)}",
        f"- Metadata: {aggregate.get('metadata_count', 0)}",
        f"- Index/TOC rows suppressed: {normalization.get('index_toc_rows_suppressed', 0)}",
        f"- Header/footer/context rows removed from normalized rows: {normalization.get('page_header_footer_rows_downgraded', 0)}",
        f"- Merged text-block fragments: {normalization.get('merged_text_block_fragments', 0)}",
        f"- Database mutated: {report.get('run_metadata', {}).get('database_mutated')}",
        f"- Production behavior changed: {report.get('run_metadata', {}).get('production_behavior_changed')}",
        f"- Live provider calls: {report.get('run_metadata', {}).get('live_external_provider_call')}",
        "",
        "## Action Counts",
        "",
    ]
    for action, count in (normalization.get("action_counts") or {}).items():
        lines.append(f"- {action}: {count}")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def _empty_reference_report() -> dict[str, Any]:
    return {"run_metadata": {"database_mutated": False}, "case_reports": [], "aggregate_metrics": {}}


def _empty_comparison_report() -> dict[str, Any]:
    return {"run_metadata": {"database_mutated": False}, "per_case": [], "aggregate_metrics": {"missing_text_block_cases": []}}


def _retag(report: dict[str, Any], *, report_type: str, output_path: Path) -> dict[str, Any]:
    metadata = dict(report.get("run_metadata") or {})
    metadata.update(
        {
            **no_side_effect_metadata(),
            "feature": "13Y",
            "generated_at": metadata.get("generated_at") or utc_now_iso(),
            "report_type": report_type,
            "output_path": str(output_path),
            "source_pipeline": "azure_di_normalized_report",
            "live_external_provider_call": False,
            "azure_di_live_call_made": False,
        }
    )
    report["run_metadata"] = metadata
    return report


def build_normalized_gate_reports(
    normalized_report: dict[str, Any],
    *,
    paths: NormalizationOutputPaths,
) -> dict[str, dict[str, Any]]:
    quality_report, readiness_report = analyze_candidate_quality_reports(
        v2_report=normalized_report,
        comparison_report=_empty_comparison_report(),
        reference_report=_empty_reference_report(),
        input_paths={"v2_report": str(paths.extraction_json)},
    )
    _retag(quality_report, report_type="azure_di_normalized_candidate_quality", output_path=paths.quality_json)
    _retag(readiness_report, report_type="azure_di_normalized_mapping_readiness", output_path=paths.quality_json)

    duplicate_report, cleaned_report, readiness_after = resolve_extraction_v2_duplicates(
        v2_report=normalized_report,
        quality_report=quality_report,
        readiness_report=readiness_report,
        comparison_report=_empty_comparison_report(),
        reference_report=_empty_reference_report(),
        input_paths={
            "v2_report": str(paths.extraction_json),
            "quality_report": str(paths.quality_json),
            "readiness_report": "in_memory_azure_di_normalized_readiness",
        },
        output_paths={
            "duplicate": str(paths.duplicate_json),
            "cleaned": "in_memory_azure_di_normalized_cleaned_candidates",
            "readiness_after": "in_memory_azure_di_normalized_readiness_after",
        },
    )
    _retag(duplicate_report, report_type="azure_di_normalized_duplicate_conflict", output_path=paths.duplicate_json)
    _retag(cleaned_report, report_type="azure_di_normalized_cleaned_candidates", output_path=paths.duplicate_json)
    _retag(readiness_after, report_type="azure_di_normalized_mapping_readiness_after_duplicates", output_path=paths.duplicate_json)

    policy_report, gate_report, queue_report = build_manual_review_policy_reports(
        cleaned_report=cleaned_report,
        duplicate_report=duplicate_report,
        readiness_report=readiness_after,
        quality_report=quality_report,
        reference_report=_empty_reference_report(),
        input_paths={
            "cleaned_candidates": "in_memory_azure_di_normalized_cleaned_candidates",
            "duplicate_report": str(paths.duplicate_json),
            "readiness_report": "in_memory_azure_di_normalized_readiness_after",
            "quality_report": str(paths.quality_json),
        },
        output_paths={
            "policy": "in_memory_azure_di_normalized_manual_review_policy",
            "gate": "in_memory_azure_di_normalized_mapping_gate",
            "queue": str(paths.manual_review_queue_json),
        },
    )
    _retag(policy_report, report_type="azure_di_normalized_manual_review_policy", output_path=paths.manual_review_queue_json)
    _retag(gate_report, report_type="azure_di_normalized_mapping_candidate_gate", output_path=paths.manual_review_queue_json)
    _retag(queue_report, report_type="azure_di_normalized_manual_review_queue", output_path=paths.manual_review_queue_json)

    handoff_report, validation_report, contract_report = build_mapping_handoff_reports(
        cleaned_report=cleaned_report,
        mapping_gate_report=gate_report,
        manual_review_queue=queue_report,
        data_contract={},
        ui_api_plan={},
        input_paths={
            "cleaned_candidates": "in_memory_azure_di_normalized_cleaned_candidates",
            "mapping_gate_report": "in_memory_azure_di_normalized_mapping_gate",
            "manual_review_queue": str(paths.manual_review_queue_json),
        },
    )
    _retag(handoff_report, report_type="azure_di_normalized_mapping_handoff", output_path=paths.mapping_handoff_json)
    _retag(validation_report, report_type="azure_di_normalized_mapping_handoff_validation", output_path=paths.mapping_handoff_json)
    _retag(contract_report, report_type="azure_di_normalized_mapping_handoff_contract", output_path=paths.mapping_handoff_json)
    return {
        "quality": quality_report,
        "readiness": readiness_report,
        "duplicate": duplicate_report,
        "cleaned": cleaned_report,
        "readiness_after": readiness_after,
        "policy": policy_report,
        "gate": gate_report,
        "queue": queue_report,
        "handoff": handoff_report,
        "handoff_validation": validation_report,
        "handoff_contract": contract_report,
    }


def _issue_count(report: Mapping[str, Any], code: str) -> int:
    return int((report.get("quality_issue_counts") or {}).get(code, 0))


def _gate_count(report: Mapping[str, Any], status: str) -> int:
    return int((report.get("aggregate_gate_counts") or {}).get(status, 0))


def build_normalization_summary(
    *,
    original_report: Mapping[str, Any],
    normalized_report: Mapping[str, Any],
    audit: list[dict[str, Any]],
    gate_reports: Mapping[str, Mapping[str, Any]] | None,
    input_report_path: str | Path | None,
    output_path: str | Path | None,
    before_quality_report: Mapping[str, Any] | None = None,
    before_duplicate_report: Mapping[str, Any] | None = None,
    before_queue_report: Mapping[str, Any] | None = None,
    before_handoff_report: Mapping[str, Any] | None = None,
    before_summary_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    del before_summary_report
    original_counts = _row_type_counts(_flatten_with_ids(original_report))
    normalized_candidates = _flatten_with_ids(normalized_report)
    normalized_counts = _row_type_counts(normalized_candidates)
    action_counts = Counter(entry["action"] for entry in audit)
    quality = (gate_reports or {}).get("quality") or {}
    duplicate = (gate_reports or {}).get("duplicate") or {}
    queue = (gate_reports or {}).get("queue") or {}
    handoff = (gate_reports or {}).get("handoff") or {}
    gate = (gate_reports or {}).get("gate") or {}
    before_issues = before_quality_report or {}
    before_duplicate = before_duplicate_report or {}
    before_handoff = before_handoff_report or {}
    before_expected_gate_counts = before_handoff.get("expected_13t_counts") or {}
    before_duplicate_aggregate = before_duplicate.get("aggregate") or {}
    after_duplicate_aggregate = duplicate.get("aggregate") or {}
    after_gate_counts = gate.get("aggregate_gate_counts") or {}
    before_handoff_candidates = int(before_handoff.get("total_handoff_candidates") or 0)
    after_handoff_candidates = int(handoff.get("total_handoff_candidates") or 0)
    summary = {
        "total_candidates": _before_after(sum(original_counts.values()), len(normalized_candidates)),
        "numeric_fact": _before_after(original_counts.get("numeric_fact", 0), normalized_counts.get("numeric_fact", 0)),
        "comparative_numeric_fact": _before_after(original_counts.get("comparative_numeric_fact", 0), normalized_counts.get("comparative_numeric_fact", 0)),
        "subtotal_or_total": _before_after(original_counts.get("subtotal_or_total", 0), normalized_counts.get("subtotal_or_total", 0)),
        "text_block": _before_after(original_counts.get("text_block", 0), normalized_counts.get("text_block", 0)),
        "heading": _before_after(original_counts.get("heading", 0), normalized_counts.get("heading", 0)),
        "metadata": _before_after(original_counts.get("metadata", 0), normalized_counts.get("metadata", 0)),
        "unknown": _before_after(original_counts.get("unknown", 0), normalized_counts.get("unknown", 0)),
        "mapping_handoff_candidates": _before_after(before_handoff_candidates, after_handoff_candidates),
        "auto_mappable": _before_after(int(before_handoff.get("auto_mappable_count") or 0), int(handoff.get("auto_mappable_count") or 0)),
        "suggest_mapping_only": _before_after(int(before_handoff.get("suggest_mapping_only_count") or 0), int(handoff.get("suggest_mapping_only_count") or 0)),
        "manual_review_required": _before_after(
            int(before_expected_gate_counts.get("manual_review_required") or 0),
            _gate_count(gate, "manual_review_required"),
        ),
        "blocked": _before_after(
            int(before_expected_gate_counts.get("blocked_from_mapping") or 0),
            _gate_count(gate, "blocked_from_mapping"),
        ),
        "reference_context_only": _before_after(
            int(before_expected_gate_counts.get("reference_only_or_context") or 0),
            _gate_count(gate, "reference_only_or_context"),
        ),
        "duplicate_label_value_same_case": _before_after(_issue_count(before_issues, "duplicate_label_value_same_case"), _issue_count(quality, "duplicate_label_value_same_case")),
        "exact_duplicate_same_page": _before_after(_issue_count(before_issues, "exact_duplicate_same_page"), _issue_count(quality, "exact_duplicate_same_page")),
        "too_short_label": _before_after(_issue_count(before_issues, "too_short_label"), _issue_count(quality, "too_short_label")),
        "heading_like_numeric_fact": _before_after(_issue_count(before_issues, "heading_like_numeric_fact"), _issue_count(quality, "heading_like_numeric_fact")),
        "year_only_label": _before_after(_issue_count(before_issues, "year_only_label"), _issue_count(quality, "year_only_label")),
        "conflicting_duplicate_groups": _before_after(
            int(before_duplicate_aggregate.get("conflicting_duplicate_groups") or 0),
            int(after_duplicate_aggregate.get("conflicting_duplicate_groups") or 0),
        ),
        "manual_review_queue_count": _before_after(
            int((before_queue_report or {}).get("queue_item_count") or 0),
            int(queue.get("queue_item_count") or 0),
        ),
    }
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "feature": "13Y",
            "generated_at": utc_now_iso(),
            "script": "scripts/normalize_azure_di_extraction_v2_candidates.py",
            "report_type": "azure_di_normalization_summary",
            "input_report": str(input_report_path) if input_report_path else None,
            "output_path": str(output_path) if output_path else None,
            "live_external_provider_call": False,
            "azure_di_live_call_made": False,
        },
        "input_reports": {
            "azure_di_report": str(input_report_path) if input_report_path else None,
        },
        "output_reports": {},
        "before_after": summary,
        "normalization_actions": dict(sorted(action_counts.items())),
        "normalization_effects": {
            "index_toc_rows_suppressed": action_counts.get("suppress_index_or_toc_row", 0),
            "page_header_footer_rows_downgraded": action_counts.get("keep_for_context_only", 0) + action_counts.get("downgrade_to_metadata", 0),
            "merged_text_block_fragments": action_counts.get("merge_text_block_fragment", 0),
            "downgraded_candidates": action_counts.get("downgrade_to_metadata", 0) + action_counts.get("downgrade_to_heading", 0),
            "suppressed_candidates": sum(1 for entry in audit if not entry["retained_in_normalized_rows"]),
            "manual_review_required_actions": action_counts.get("manual_review_required", 0),
        },
        "gate_outputs": {
            "quality_report_status": quality.get("status", "ok") if quality else "skipped",
            "duplicate_report_status": duplicate.get("status", "ok") if duplicate else "skipped",
            "manual_review_queue_count": int(queue.get("queue_item_count") or 0),
            "mapping_handoff_candidates": after_handoff_candidates,
            "auto_mappable": int(handoff.get("auto_mappable_count") or 0),
            "suggest_mapping_only": int(handoff.get("suggest_mapping_only_count") or 0),
            "excluded": int(handoff.get("excluded_count") or 0),
            "aggregate_gate_counts": dict(after_gate_counts),
        },
        "assessment": {
            "heading_context_index_noise_reduced_or_categorized": normalized_counts.get("heading", 0) <= original_counts.get("heading", 0),
            "text_blocks_preserved": normalized_counts.get("text_block", 0) > 0,
            "financial_table_candidates_preserved": sum(normalized_counts.get(item, 0) for item in NUMERIC_ROW_TYPES) > 0,
            "ready_for_mapping_candidate_generation": after_handoff_candidates > 0,
            "recommended_next_feature": _recommended_next_feature(after_handoff_candidates, normalized_counts, action_counts),
        },
        "limitations": [
            "Normalization is heuristic and report-only.",
            "No live provider call, DB mutation, production behavior change, taxonomy mapping, XBRL generation, or Arelle validation occurred.",
            "Reference XML is not sent to any provider or model.",
        ],
    }


def _before_after(before: int, after: int) -> dict[str, int]:
    return {"before": int(before), "after": int(after), "delta": int(after) - int(before)}


def _recommended_next_feature(handoff_count: int, row_counts: Mapping[str, int], action_counts: Counter[str]) -> str:
    if handoff_count and (row_counts.get("heading", 0) or 0) < 100:
        return "Feature #13Z - Azure DI normalized mapping handoff to mapping candidate generation."
    if action_counts.get("downgrade_to_metadata", 0) or action_counts.get("suppress_index_or_toc_row", 0):
        return "Feature #13Z - Continue Azure DI table/text-block normalization before mapping candidate generation."
    return "Feature #13Z - Azure DI-first extraction route planning for production upload flow."


def render_normalization_summary_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Normalization Summary - Feature #13Y",
        "",
        "## Summary",
        "",
    ]
    before_after = report.get("before_after") or {}
    for key in [
        "total_candidates",
        "comparative_numeric_fact",
        "numeric_fact",
        "subtotal_or_total",
        "text_block",
        "heading",
        "metadata",
        "mapping_handoff_candidates",
        "auto_mappable",
        "suggest_mapping_only",
        "manual_review_required",
        "reference_context_only",
        "duplicate_label_value_same_case",
        "exact_duplicate_same_page",
        "too_short_label",
        "heading_like_numeric_fact",
        "year_only_label",
    ]:
        values = before_after.get(key, {})
        lines.append(f"- {key}: {values.get('before', 0)} -> {values.get('after', 0)} ({values.get('delta', 0):+d})")
    effects = report.get("normalization_effects") or {}
    lines.extend(
        [
            "",
            "## Normalization Effects",
            "",
            f"- Index/TOC rows suppressed: {effects.get('index_toc_rows_suppressed', 0)}",
            f"- Header/footer/context rows removed from normalized rows: {effects.get('page_header_footer_rows_downgraded', 0)}",
            f"- Text-block fragments merged: {effects.get('merged_text_block_fragments', 0)}",
            f"- Downgraded candidates: {effects.get('downgraded_candidates', 0)}",
            f"- Suppressed candidates: {effects.get('suppressed_candidates', 0)}",
            "",
            "## Gate Outputs",
            "",
        ]
    )
    gate = report.get("gate_outputs") or {}
    lines.extend(
        [
            f"- Mapping handoff candidates: {gate.get('mapping_handoff_candidates', 0)}",
            f"- Auto mappable: {gate.get('auto_mappable', 0)}",
            f"- Suggest mapping only: {gate.get('suggest_mapping_only', 0)}",
            f"- Manual review queue count: {gate.get('manual_review_queue_count', 0)}",
            f"- Excluded: {gate.get('excluded', 0)}",
            "",
            "## Assessment",
            "",
            f"- Ready for mapping-candidate generation: {report.get('assessment', {}).get('ready_for_mapping_candidate_generation')}",
            f"- Recommended next feature: {report.get('assessment', {}).get('recommended_next_feature')}",
            f"- Database mutated: {report.get('run_metadata', {}).get('database_mutated')}",
            f"- Production behavior changed: {report.get('run_metadata', {}).get('production_behavior_changed')}",
            f"- Live provider call: {report.get('run_metadata', {}).get('live_external_provider_call')}",
            "",
            "## Limitations",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def run_azure_di_normalization(
    *,
    azure_di_report_path: str | Path = DEFAULT_INPUT_REPORT,
    run_id: str | None = None,
    output_prefix: str | Path | None = None,
    skip_gates: bool = False,
    verbose: bool = False,
) -> dict[str, Any]:
    del verbose
    input_path = Path(azure_di_report_path)
    azure_report = json.loads(input_path.read_text(encoding="utf-8"))
    paths = output_paths_from_prefix(output_prefix)
    normalized_report, _summary = normalize_azure_di_extraction_report(
        azure_report,
        run_id=run_id,
        input_report_path=input_path,
        output_path=paths.extraction_json,
    )
    _write_json(paths.extraction_json, normalized_report)
    _write_text(paths.extraction_md, render_normalized_extraction_markdown(normalized_report))

    gate_reports: dict[str, dict[str, Any]] = {}
    if not skip_gates:
        gate_reports = build_normalized_gate_reports(normalized_report, paths=paths)
        _write_json(paths.quality_json, gate_reports["quality"])
        _write_text(paths.quality_md, render_candidate_quality_markdown(gate_reports["quality"]))
        _write_json(paths.duplicate_json, gate_reports["duplicate"])
        _write_text(paths.duplicate_md, render_duplicate_conflict_markdown(gate_reports["duplicate"]))
        _write_json(paths.manual_review_queue_json, gate_reports["queue"])
        _write_text(paths.manual_review_queue_md, render_queue_markdown(gate_reports["queue"]))
        _write_json(paths.mapping_handoff_json, gate_reports["handoff"])
        _write_text(paths.mapping_handoff_md, render_mapping_handoff_markdown(gate_reports["handoff"]))

    summary = build_normalization_summary(
        original_report=azure_report,
        normalized_report=normalized_report,
        audit=(normalized_report.get("normalization") or {}).get("candidate_audit_trail") or [],
        gate_reports=gate_reports,
        input_report_path=input_path,
        output_path=paths.summary_json,
        before_quality_report=_load_optional_json(Path("reports/azure_di_sandbox_candidate_quality_13x.json")),
        before_duplicate_report=_load_optional_json(Path("reports/azure_di_sandbox_duplicate_conflict_13x.json")),
        before_queue_report=_load_optional_json(Path("reports/azure_di_sandbox_manual_review_queue_13x.json")),
        before_handoff_report=_load_optional_json(Path("reports/azure_di_sandbox_mapping_handoff_13x.json")),
        before_summary_report=_load_optional_json(Path("reports/azure_di_sandbox_summary_13x.json")),
    )
    summary["output_reports"] = {
        "normalized_extraction_json": str(paths.extraction_json),
        "normalized_extraction_md": str(paths.extraction_md),
        "candidate_quality_json": str(paths.quality_json),
        "candidate_quality_md": str(paths.quality_md),
        "duplicate_conflict_json": str(paths.duplicate_json),
        "duplicate_conflict_md": str(paths.duplicate_md),
        "manual_review_queue_json": str(paths.manual_review_queue_json),
        "manual_review_queue_md": str(paths.manual_review_queue_md),
        "mapping_handoff_json": str(paths.mapping_handoff_json),
        "mapping_handoff_md": str(paths.mapping_handoff_md),
        "summary_json": str(paths.summary_json),
        "summary_md": str(paths.summary_md),
    }
    _write_json(paths.summary_json, summary)
    _write_text(paths.summary_md, render_normalization_summary_markdown(summary))
    return {
        "paths": paths,
        "normalized_report": normalized_report,
        "gate_reports": gate_reports,
        "summary_report": summary,
    }
