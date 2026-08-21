"""Azure Document Intelligence to Extraction v2-style candidate conversion."""

from __future__ import annotations

import re
import logging
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Sequence

from services.extraction_v2_pipeline import (
    TOTAL_LABEL_RE,
    clean_line,
    detect_statement_section,
)


SOURCE_METHOD = "azure_document_intelligence"
NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
MAX_AZURE_DI_CONVERSION_PAGES = 500
MAX_AZURE_DI_CONVERSION_LINES = 50000
MAX_AZURE_DI_CONVERSION_PARAGRAPHS = 20000
MAX_AZURE_DI_CONVERSION_TABLES = 1000
MAX_AZURE_DI_TABLE_ROWS = 1000
MAX_AZURE_DI_TABLE_COLUMNS = 100
MAX_AZURE_DI_TABLE_CELLS = 100000
MAX_AZURE_DI_TABLE_MATRIX_CELLS = 100000
MAX_AZURE_DI_TEXT_BLOCK_PARAGRAPHS = 2000
MAX_AZURE_DI_TEXT_BLOCK_PARAGRAPH_CHARS = 4000
MAX_AZURE_DI_DEDUPE_COMPARISONS = 100000
PAGE_LOG_INTERVAL = 5
TEXT_BLOCK_LOG_INTERVAL = 50
DEDUPE_LOG_INTERVAL = 1000
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
CODE_RE = re.compile(r"^[A-Z]{1,6}[-/]\d+[A-Z0-9/-]*$")
PERCENT_RE = re.compile(r"^-?\(?\d+(?:\.\d+)?\)?%$")
AMOUNTISH_RE = re.compile(r"^(?:RM|MYR|\$)?\s*\(?-?\d[\d,]*(?:\.\d+)?\)?$")
INDEX_ROW_RE = re.compile(r"\b(index|contents?|page)\b", re.IGNORECASE)
NARRATIVE_HEADING_RE = re.compile(
    r"\b("
    r"directors'? report|statement by directors|statutory declaration|independent auditors'? report|"
    r"notes to (the )?financial statements|accounting policies|principal activities|basis of preparation|"
    r"directors'? benefits|directors'? interests|auditors'? remuneration|financial risk management"
    r")\b",
    re.IGNORECASE,
)
METADATA_RE = re.compile(
    r"\b(registration no\.?|company no\.?|financial year ended|incorporated in malaysia|sdn\.?\s*bhd\.?)\b",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


class AzureDINormalizationGuardError(RuntimeError):
    """Raised when Azure DI local normalization input exceeds bounded limits."""


class AzureDITextBlockNormalizationTimeout(TimeoutError):
    """Raised when best-effort Azure DI text-block normalization exceeds its budget."""


TEXT_BLOCK_TIMEOUT_WARNING = "Azure DI text block normalization timed out; continuing with table candidates."
TEXT_BLOCK_FAILED_WARNING = "Azure DI text block normalization failed; continuing with table candidates."
TEXT_BLOCK_DISABLED_WARNING = "Azure DI text block normalization skipped because AZURE_DI_TEXT_BLOCKS_ENABLED=false."


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 3)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _guard_count(*, name: str, count: int, limit: int) -> None:
    if count > limit:
        raise AzureDINormalizationGuardError(
            f"Azure DI normalization input exceeded {name} limit: count={count}, limit={limit}."
        )


def _append_unique(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _append_result_warning(result: dict[str, Any], warning: str) -> None:
    warnings = result.setdefault("warnings", [])
    if isinstance(warnings, list):
        _append_unique(warnings, warning)


def _append_candidate_warning(candidates: list[dict[str, Any]], warning: str) -> None:
    for candidate in candidates:
        candidate.setdefault("warnings", [])
        if isinstance(candidate["warnings"], list):
            _append_unique(candidate["warnings"], warning)


def _check_text_block_timeout(
    *,
    started: float,
    timeout_seconds: float | None,
    case_id: str,
    stage: str,
    index: int | None = None,
    total: int | None = None,
) -> None:
    if timeout_seconds is None:
        return
    elapsed = time.monotonic() - started
    if timeout_seconds <= 0 or elapsed > timeout_seconds:
        detail = f" stage={stage}"
        if index is not None and total is not None:
            detail += f" index={index}/{total}"
        raise AzureDITextBlockNormalizationTimeout(
            f"Azure DI text block normalization timed out for case_id={case_id}:{detail} "
            f"elapsed_seconds={round(elapsed, 3)} limit_seconds={timeout_seconds}."
        )


def _bounded_clean_line(value: Any, *, max_chars: int) -> tuple[str, bool]:
    raw = str(value or "")
    truncated = len(raw) > max_chars
    if truncated:
        raw = raw[:max_chars]
    return clean_line(raw), truncated


def _table_shape(table: dict[str, Any]) -> tuple[int, int, int]:
    cells = list(table.get("cells") or [])
    rows = _safe_int(table.get("row_count"))
    cols = _safe_int(table.get("column_count"))
    for cell in cells:
        rows = max(rows, _safe_int(cell.get("row_index")) + 1)
        cols = max(cols, _safe_int(cell.get("column_index")) + 1)
    return rows, cols, len(cells)


def _guard_table_shape(table: dict[str, Any]) -> tuple[int, int, int]:
    table_index = table.get("table_index")
    rows, cols, cells = _table_shape(table)
    if rows > MAX_AZURE_DI_TABLE_ROWS:
        raise AzureDINormalizationGuardError(
            "Azure DI normalization input exceeded table row limit: "
            f"table_index={table_index}, rows={rows}, limit={MAX_AZURE_DI_TABLE_ROWS}."
        )
    if cols > MAX_AZURE_DI_TABLE_COLUMNS:
        raise AzureDINormalizationGuardError(
            "Azure DI normalization input exceeded table column limit: "
            f"table_index={table_index}, columns={cols}, limit={MAX_AZURE_DI_TABLE_COLUMNS}."
        )
    if cells > MAX_AZURE_DI_TABLE_CELLS:
        raise AzureDINormalizationGuardError(
            "Azure DI normalization input exceeded table cell limit: "
            f"table_index={table_index}, cells={cells}, limit={MAX_AZURE_DI_TABLE_CELLS}."
        )
    if rows * cols > MAX_AZURE_DI_TABLE_MATRIX_CELLS:
        raise AzureDINormalizationGuardError(
            "Azure DI normalization input exceeded table matrix limit: "
            f"table_index={table_index}, rows={rows}, columns={cols}, "
            f"matrix_cells={rows * cols}, limit={MAX_AZURE_DI_TABLE_MATRIX_CELLS}."
        )
    return rows, cols, cells


def _page_number_for_log(page: dict[str, Any], fallback: int) -> int:
    return _safe_int(page.get("page_number"), fallback)


def no_side_effect_metadata() -> dict[str, Any]:
    return {
        "feature": "13W-AzureDI-spike",
        "read_only": True,
        "database_mutated": False,
        "db_schema_changed": False,
        "migration_created": False,
        "api_routes_implemented": False,
        "frontend_code_modified": False,
        "production_behavior_changed": False,
        "production_extraction_behavior_changed": False,
        "production_mapping_behavior_changed": False,
        "taxonomy_mapping_performed": False,
        "semantic_matcher_called": False,
        "xbrl_generated": False,
        "arelle_validation_run": False,
        "live_huggingface_calls_made": False,
        "live_openai_calls_made": False,
        "reference_xml_sent_to_provider": False,
        "reference_xml_sent_to_model": False,
    }


def parse_amount(value: Any) -> str | None:
    text = clean_line(value)
    if not text:
        return None
    if text in {"-", "--"}:
        return "0"
    text = re.sub(r"\b(?:RM|MYR|USD)\b|\$", "", text, flags=re.IGNORECASE).strip()
    if PERCENT_RE.fullmatch(text):
        return None
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    cleaned = text.replace(",", "").replace("(", "").replace(")", "").replace(" ", "")
    if cleaned.startswith("-"):
        cleaned = cleaned[1:]
    if not re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        return None
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if negative and amount != 0:
        amount = -amount
    normalized = format(amount, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def is_percent(value: Any) -> bool:
    return bool(PERCENT_RE.fullmatch(clean_line(value).replace(" ", "")))


def is_amount_like(value: Any) -> bool:
    text = clean_line(value)
    if not text or re.fullmatch(r"(?:19|20)\d{2}", text) or is_percent(text):
        return False
    return parse_amount(text) is not None or bool(AMOUNTISH_RE.fullmatch(text))


def is_code(value: Any) -> bool:
    return bool(CODE_RE.fullmatch(clean_line(value)))


def _year_values(values: Iterable[Any]) -> list[int]:
    years: list[int] = []
    for value in values:
        for match in YEAR_RE.finditer(clean_line(value)):
            year = int(match.group(1))
            if year not in years:
                years.append(year)
    return sorted(years, reverse=True)


def _source_pdf_name(source_pdf: str | None) -> str:
    return Path(str(source_pdf or "")).name


def _candidate(
    *,
    case_id: str,
    source_pdf: str,
    page_number: int,
    model_id: str,
    row_type: str,
    statement_section: str | None,
    label: str | None = None,
    value: str | None = None,
    previous_value: str | None = None,
    current_year: int | None = None,
    prior_year: int | None = None,
    text: str | None = None,
    source_snippet: str | None = None,
    confidence: float = 0.75,
    warnings: Sequence[str] = (),
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = {
        "case_id": case_id,
        "source_pdf": source_pdf,
        "pdf_filename": _source_pdf_name(source_pdf),
        "page_number": int(page_number or 0),
        "source_method": SOURCE_METHOD,
        "extraction_method": SOURCE_METHOD,
        "model_id": model_id,
        "row_type": row_type,
        "statement_section": statement_section,
        "label": clean_line(label) or None,
        "value": clean_line(value) or None,
        "previous_value": clean_line(previous_value) or None,
        "current_year": current_year,
        "prior_year": prior_year,
        "text": clean_line(text) or None,
        "source_snippet": clean_line(source_snippet or text or label or "")[:1000],
        "confidence": max(0.0, min(1.0, float(confidence))),
        "warnings": list(dict.fromkeys(str(item) for item in warnings if str(item))),
        "provenance": provenance or {},
    }
    row["provenance"].setdefault("source_method", SOURCE_METHOD)
    row["provenance"].setdefault("model_id", model_id)
    row["provenance"].setdefault("page_number", row["page_number"])
    return row


def _cell_matrix(table: dict[str, Any]) -> list[list[dict[str, Any] | None]]:
    rows, cols, _cells = _guard_table_shape(table)
    matrix: list[list[dict[str, Any] | None]] = [[None for _ in range(cols)] for _ in range(rows)]
    for cell in table.get("cells") or []:
        row = _safe_int(cell.get("row_index"))
        col = _safe_int(cell.get("column_index"))
        if 0 <= row < rows and 0 <= col < cols:
            matrix[row][col] = cell
    return matrix


def _row_text(row: Sequence[dict[str, Any] | None]) -> str:
    return " ".join(clean_line((cell or {}).get("content")) for cell in row if clean_line((cell or {}).get("content")))


def _table_page(table: dict[str, Any], row: Sequence[dict[str, Any] | None] | None = None) -> int:
    cells = [cell for cell in (row or []) if cell] or list(table.get("cells") or [])
    for cell in cells:
        if cell.get("page_number"):
            return int(cell.get("page_number"))
    pages = table.get("page_numbers") or []
    return int(pages[0]) if pages else 0


def _is_index_or_toc_row(row_text: str, table_text: str) -> bool:
    text = clean_line(row_text)
    if not text:
        return True
    if INDEX_ROW_RE.search(table_text) and re.search(r"\b\d{1,3}$", text) and not is_amount_like(text):
        return True
    if re.fullmatch(r"(?:[A-Za-z'()&.\-/ ]+\s+){0,8}\d{1,3}", text) and not re.search(r"\d[,.\d]{3,}", text):
        return True
    return False


def _header_years(matrix: Sequence[Sequence[dict[str, Any] | None]]) -> dict[int, int]:
    years_by_col: dict[int, int] = {}
    for row in matrix[:3]:
        for col_index, cell in enumerate(row):
            content = clean_line((cell or {}).get("content"))
            years = _year_values([content])
            if years:
                years_by_col[col_index] = years[0]
    return years_by_col


def _header_text_by_col(matrix: Sequence[Sequence[dict[str, Any] | None]]) -> dict[int, str]:
    headers: dict[int, list[str]] = {}
    for row in matrix[:3]:
        for col_index, cell in enumerate(row):
            content = clean_line((cell or {}).get("content"))
            if content:
                headers.setdefault(col_index, []).append(content)
    return {col_index: clean_line(" ".join(values)) for col_index, values in headers.items()}


def _note_columns(matrix: Sequence[Sequence[dict[str, Any] | None]]) -> set[int]:
    note_columns: set[int] = set()
    for col_index, header in _header_text_by_col(matrix).items():
        normalized = re.sub(r"[^a-z]+", " ", header.lower()).strip()
        if normalized in {"note", "notes", "no", "note no", "notes no"}:
            note_columns.add(col_index)
    return note_columns


def _looks_like_note_number(value: Any) -> bool:
    return bool(re.fullmatch(r"\d{1,2}[A-Za-z]?", clean_line(value)))


def _table_candidates(
    *,
    result: dict[str, Any],
    table: dict[str, Any],
    case_id: str,
    source_pdf: str,
    statement_section: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    started = time.monotonic()
    table_index = table.get("table_index")
    rows, cols, cells = _table_shape(table)
    logger.info(
        "Azure DI table normalization started: case_id=%s table_index=%s rows=%s columns=%s cells=%s pages=%s",
        case_id,
        table_index,
        rows,
        cols,
        cells,
        table.get("page_numbers") or [],
    )
    matrix = _cell_matrix(table)
    table_text = " ".join(_row_text(row) for row in matrix)
    statement_section = detect_statement_section(table_text, statement_section)
    if INDEX_ROW_RE.search(table_text) and len(matrix) <= 20:
        statement_section = statement_section or "Index / Contents"

    years_by_col = _header_years(matrix)
    note_cols = _note_columns(matrix)
    candidates: list[dict[str, Any]] = []
    for row_index, row in enumerate(matrix):
        text = _row_text(row)
        if not text:
            continue
        if row_index <= 1 and (_year_values([text]) or re.search(r"\b(note|rm|myr|this year|previous year)\b", text, re.IGNORECASE)):
            statement_section = detect_statement_section(text, statement_section)
            continue
        if _is_index_or_toc_row(text, table_text):
            if INDEX_ROW_RE.search(table_text):
                candidates.append(
                    _candidate(
                        case_id=case_id,
                        source_pdf=source_pdf,
                        page_number=_table_page(table, row),
                        model_id=result.get("model_id") or "prebuilt-layout",
                        row_type="metadata",
                        statement_section="Index / Contents",
                        label=text,
                        source_snippet=text,
                        confidence=0.6,
                        warnings=["index_or_page_number_row_not_financial_fact"],
                        provenance={
                            "table_index": table.get("table_index"),
                            "row_index": row_index,
                            "cell_indexes": [int((cell or {}).get("column_index") or 0) for cell in row if cell],
                            "table_page_numbers": table.get("page_numbers") or [],
                        },
                    )
                )
            continue

        cells = [(idx, cell, clean_line((cell or {}).get("content"))) for idx, cell in enumerate(row) if cell]
        raw_amount_cells = [(idx, cell, content) for idx, cell, content in cells if is_amount_like(content)]
        amount_cells = [
            (idx, cell, content)
            for idx, cell, content in raw_amount_cells
            if idx not in note_cols
        ]
        if len(amount_cells) < len(raw_amount_cells):
            raw_non_note_amounts = [item for item in raw_amount_cells if item[0] not in note_cols]
            if raw_non_note_amounts:
                amount_cells = raw_non_note_amounts
            elif all(_looks_like_note_number(content) for _idx, _cell, content in raw_amount_cells):
                amount_cells = []
        elif len(raw_amount_cells) > 1:
            amount_cells = [
                item
                for item in raw_amount_cells
                if not (
                    _looks_like_note_number(item[2])
                    and item[0] not in years_by_col
                    and any(other[0] > item[0] for other in raw_amount_cells)
                )
            ] or raw_amount_cells
        percent_cells = [(idx, cell, content) for idx, cell, content in cells if is_percent(content)]
        if not amount_cells:
            if detect_statement_section(text, None) or NARRATIVE_HEADING_RE.search(text):
                statement_section = detect_statement_section(text, statement_section) or text
                candidates.append(
                    _candidate(
                        case_id=case_id,
                        source_pdf=source_pdf,
                        page_number=_table_page(table, row),
                        model_id=result.get("model_id") or "prebuilt-layout",
                        row_type="heading",
                        statement_section=statement_section,
                        label=text,
                        text=text,
                        source_snippet=text,
                        confidence=0.65,
                        provenance={"table_index": table.get("table_index"), "row_index": row_index},
                    )
                )
            continue

        code_value = None
        label_parts: list[str] = []
        for idx, _cell, content in cells:
            if idx in note_cols:
                continue
            if any(idx == amount_idx for amount_idx, _amount_cell, _amount_content in amount_cells):
                continue
            if any(idx == percent_idx for percent_idx, _percent_cell, _percent_content in percent_cells):
                continue
            if is_code(content) and code_value is None:
                code_value = content
                continue
            if not _year_values([content]) and content.lower() not in {"rm", "myr", "note", "notes"}:
                label_parts.append(content)
        label = clean_line(" ".join(label_parts))
        if not label:
            continue

        sorted_amounts = sorted(amount_cells, key=lambda item: item[0])
        value = parse_amount(sorted_amounts[0][2])
        previous_value = parse_amount(sorted_amounts[1][2]) if len(sorted_amounts) > 1 else None
        sorted_years = sorted(
            [years_by_col.get(col) for col, _cell, _content in sorted_amounts if years_by_col.get(col)],
            reverse=True,
        )
        current_year = sorted_years[0] if sorted_years else None
        prior_year = sorted_years[1] if len(sorted_years) > 1 else None
        row_type = "comparative_numeric_fact" if previous_value is not None else "numeric_fact"
        if row_type == "numeric_fact" and TOTAL_LABEL_RE.search(label):
            row_type = "subtotal_or_total"
        if row_type == "comparative_numeric_fact" and TOTAL_LABEL_RE.search(label):
            row_type = "subtotal_or_total"
        warnings: list[str] = []
        ignored_note_values = [
            content
            for idx, _cell, content in raw_amount_cells
            if idx not in {amount_idx for amount_idx, _amount_cell, _amount_content in amount_cells}
            and (idx in note_cols or _looks_like_note_number(content))
        ]
        if ignored_note_values:
            warnings.append("note_column_values_ignored")
        if percent_cells and len(amount_cells) == 1:
            warnings.append("percent_column_preserved_not_prior_year")
        if not statement_section:
            warnings.append("section_unknown")
        provenance_cells = [
            {
                "row_index": int((cell or {}).get("row_index") or row_index),
                "column_index": int((cell or {}).get("column_index") or col_index),
                "content": content,
                "kind": (cell or {}).get("kind"),
                "bounding_regions": (cell or {}).get("bounding_regions") or [],
            }
            for col_index, cell, content in cells
        ]
        candidates.append(
            _candidate(
                case_id=case_id,
                source_pdf=source_pdf,
                page_number=_table_page(table, row),
                model_id=result.get("model_id") or "prebuilt-layout",
                row_type=row_type,
                statement_section=statement_section,
                label=label,
                value=value,
                previous_value=previous_value,
                current_year=current_year,
                prior_year=prior_year,
                source_snippet=text,
                confidence=0.78,
                warnings=warnings,
                provenance={
                    "table_index": table.get("table_index"),
                    "row_index": row_index,
                    "cell_indexes": [item["column_index"] for item in provenance_cells],
                    "cells": provenance_cells,
                    "account_code": code_value,
                    "percentage_cells": [content for _idx, _cell, content in percent_cells],
                    "raw_amounts": [content for _idx, _cell, content in sorted_amounts],
                    "ignored_note_values": ignored_note_values,
                    "table_page_numbers": table.get("page_numbers") or [],
                },
            )
        )
    logger.info(
        "Azure DI table normalization finished: case_id=%s table_index=%s candidate_count=%s elapsed_seconds=%s",
        case_id,
        table_index,
        len(candidates),
        _elapsed(started),
    )
    return candidates, statement_section


def _line_heading_candidate(
    *,
    result: dict[str, Any],
    line: dict[str, Any],
    case_id: str,
    source_pdf: str,
    statement_section: str | None,
) -> dict[str, Any]:
    text = clean_line(line.get("content"))
    return _candidate(
        case_id=case_id,
        source_pdf=source_pdf,
        page_number=int(line.get("page_number") or 0),
        model_id=result.get("model_id") or "prebuilt-layout",
        row_type="heading",
        statement_section=statement_section or text,
        label=text,
        text=text,
        source_snippet=text,
        confidence=0.62,
        provenance={
            "line_polygon": line.get("polygon") or [],
            "line_spans": line.get("spans") or [],
        },
    )


def _paragraph_candidates(
    *,
    result: dict[str, Any],
    case_id: str,
    source_pdf: str,
    initial_section: str | None,
    started: float,
    timeout_seconds: float | None = None,
    max_paragraphs: int = MAX_AZURE_DI_TEXT_BLOCK_PARAGRAPHS,
    max_paragraph_chars: int = MAX_AZURE_DI_TEXT_BLOCK_PARAGRAPH_CHARS,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    section = initial_section
    paragraphs = result.get("paragraphs") or []
    if not paragraphs:
        lines = list(result.get("lines") or [])
        if len(lines) > max_paragraphs:
            logger.warning(
                "Azure DI text block fallback lines truncated: case_id=%s line_count=%s limit=%s",
                case_id,
                len(lines),
                max_paragraphs,
            )
            lines = lines[:max_paragraphs]
        for index, line in enumerate(lines, start=1):
            if index == 1 or index == len(lines) or index % TEXT_BLOCK_LOG_INTERVAL == 0:
                _check_text_block_timeout(
                    started=started,
                    timeout_seconds=timeout_seconds,
                    case_id=case_id,
                    stage="fallback_line_scan",
                    index=index,
                    total=len(lines),
                )
                logger.info(
                    "Azure DI text block fallback line progress: case_id=%s line_index=%s/%s elapsed_seconds=%s",
                    case_id,
                    index,
                    len(lines),
                    _elapsed(started),
                )
            text, truncated = _bounded_clean_line(line.get("content"), max_chars=max_paragraph_chars)
            if not text:
                continue
            detected = detect_statement_section(text, section)
            if detected != section or (NARRATIVE_HEADING_RE.search(text) and len(text.split()) <= 10):
                section = detected or text
                bounded_line = {**line, "content": text}
                heading = _line_heading_candidate(
                    result=result,
                    line=bounded_line,
                    case_id=case_id,
                    source_pdf=source_pdf,
                    statement_section=section,
                )
                if truncated:
                    heading.setdefault("warnings", [])
                    _append_unique(heading["warnings"], "azure_di_text_block_input_truncated")
                candidates.append(
                    heading
                )
        return candidates

    if len(paragraphs) > max_paragraphs:
        logger.warning(
            "Azure DI text block paragraphs truncated: case_id=%s paragraph_count=%s limit=%s",
            case_id,
            len(paragraphs),
            max_paragraphs,
        )
        paragraphs = paragraphs[:max_paragraphs]

    for index, paragraph in enumerate(paragraphs, start=1):
        if index == 1 or index == len(paragraphs) or index % TEXT_BLOCK_LOG_INTERVAL == 0:
            _check_text_block_timeout(
                started=started,
                timeout_seconds=timeout_seconds,
                case_id=case_id,
                stage="paragraph_scan",
                index=index,
                total=len(paragraphs),
            )
            logger.info(
                "Azure DI text block paragraph progress: case_id=%s paragraph_index=%s/%s elapsed_seconds=%s",
                case_id,
                index,
                len(paragraphs),
                _elapsed(started),
            )
        text, truncated = _bounded_clean_line(paragraph.get("content"), max_chars=max_paragraph_chars)
        if not text:
            continue
        if _is_index_or_toc_row(text, "index"):
            continue
        detected = detect_statement_section(text, section)
        if detected:
            section = detected
        word_count = len(text.split())
        page_number = int(paragraph.get("page_number") or 0)
        provenance = {
            "paragraph_index": paragraph.get("paragraph_index"),
            "paragraph_role": paragraph.get("role"),
            "bounding_regions": paragraph.get("bounding_regions") or [],
            "spans": paragraph.get("spans") or [],
        }
        warnings = ["azure_di_text_block_input_truncated"] if truncated else []
        if METADATA_RE.search(text) and word_count <= 18:
            candidates.append(
                _candidate(
                    case_id=case_id,
                    source_pdf=source_pdf,
                    page_number=page_number,
                    model_id=result.get("model_id") or "prebuilt-layout",
                    row_type="metadata",
                    statement_section=section or "Document Metadata",
                    label=text,
                    text=text,
                    source_snippet=text,
                    confidence=0.68,
                    warnings=warnings,
                    provenance=provenance,
                )
            )
            continue
        if word_count <= 10 and (NARRATIVE_HEADING_RE.search(text) or detected):
            section = detected or text
            candidates.append(
                _candidate(
                    case_id=case_id,
                    source_pdf=source_pdf,
                    page_number=page_number,
                    model_id=result.get("model_id") or "prebuilt-layout",
                    row_type="heading",
                    statement_section=section,
                    label=text,
                    text=text,
                    source_snippet=text,
                    confidence=0.68,
                    warnings=warnings,
                    provenance=provenance,
                )
            )
            continue
        if word_count >= 8 and NARRATIVE_HEADING_RE.search(section or text):
            candidates.append(
                _candidate(
                    case_id=case_id,
                    source_pdf=source_pdf,
                    page_number=page_number,
                    model_id=result.get("model_id") or "prebuilt-layout",
                    row_type="text_block",
                    statement_section=section or "Narrative Disclosure",
                    label=(section or text[:80]),
                    text=text,
                    source_snippet=text,
                    confidence=0.74,
                    warnings=["text_block_not_numeric", *warnings],
                    provenance=provenance,
                )
            )
    return candidates


def convert_azure_di_result_to_candidates(
    result: dict[str, Any],
    *,
    case_id: str,
    source_pdf: str,
    text_blocks_enabled: bool = True,
    text_block_timeout_seconds: float | None = None,
    max_text_block_paragraphs: int = MAX_AZURE_DI_TEXT_BLOCK_PARAGRAPHS,
    max_text_block_paragraph_chars: int = MAX_AZURE_DI_TEXT_BLOCK_PARAGRAPH_CHARS,
) -> list[dict[str, Any]]:
    if not result.get("ok", False):
        logger.info("Azure DI candidate conversion skipped for case_id=%s because result ok=false", case_id)
        return []
    started = time.monotonic()
    pages = list(result.get("pages") or [])
    lines = list(result.get("lines") or [])
    paragraphs = list(result.get("paragraphs") or [])
    tables = list(result.get("tables") or [])
    _guard_count(name="pages", count=len(pages), limit=MAX_AZURE_DI_CONVERSION_PAGES)
    _guard_count(name="lines", count=len(lines), limit=MAX_AZURE_DI_CONVERSION_LINES)
    _guard_count(name="paragraphs", count=len(paragraphs), limit=MAX_AZURE_DI_CONVERSION_PARAGRAPHS)
    _guard_count(name="tables", count=len(tables), limit=MAX_AZURE_DI_CONVERSION_TABLES)
    logger.info(
        "Azure DI normalized plain result received: case_id=%s pages_count=%s pages=%s lines=%s paragraphs=%s tables=%s table_cells=%s content_length=%s",
        case_id,
        result.get("pages_count"),
        len(pages),
        len(lines),
        len(paragraphs),
        len(tables),
        len(result.get("table_cells") or []),
        result.get("content_length"),
    )
    logger.info("Azure DI candidate building started: case_id=%s", case_id)

    page_started = time.monotonic()
    logger.info("Azure DI pages loop started: case_id=%s page_count=%s", case_id, len(pages))
    for index, page in enumerate(pages, start=1):
        page_number = _page_number_for_log(page, index)
        if index == 1 or index == len(pages) or index % PAGE_LOG_INTERVAL == 0:
            logger.info(
                "Azure DI page normalization progress: case_id=%s page_number=%s page_index=%s/%s lines=%s words=%s elapsed_seconds=%s",
                case_id,
                page_number,
                index,
                len(pages),
                len(page.get("lines") or []),
                len(page.get("words") or []),
                _elapsed(page_started),
            )
    logger.info(
        "Azure DI pages loop finished: case_id=%s page_count=%s elapsed_seconds=%s",
        case_id,
        len(pages),
        _elapsed(page_started),
    )

    candidates: list[dict[str, Any]] = []
    section: str | None = None
    section_started = time.monotonic()
    logger.info("Azure DI heading/section normalization started: case_id=%s line_count=%s", case_id, len(lines))
    for line in lines:
        text = clean_line(line.get("content"))
        if text:
            section = detect_statement_section(text, section)
    logger.info(
        "Azure DI heading/section normalization finished: case_id=%s current_section=%s elapsed_seconds=%s",
        case_id,
        section,
        _elapsed(section_started),
    )

    table_started = time.monotonic()
    logger.info("Azure DI tables loop started: case_id=%s table_count=%s", case_id, len(tables))
    for table_index, table in enumerate(tables):
        try:
            table_candidates, section = _table_candidates(
                result=result,
                table=table,
                case_id=case_id,
                source_pdf=source_pdf,
                statement_section=section,
            )
            candidates.extend(table_candidates)
        except Exception:
            rows, cols, cells = _table_shape(table)
            logger.exception(
                "Azure DI table normalization failed: case_id=%s table_index=%s rows=%s columns=%s cells=%s",
                case_id,
                table.get("table_index", table_index),
                rows,
                cols,
                cells,
            )
            raise
    logger.info(
        "Azure DI tables loop finished: case_id=%s table_count=%s candidate_count=%s elapsed_seconds=%s",
        case_id,
        len(tables),
        len(candidates),
        _elapsed(table_started),
    )

    text_started = time.monotonic()
    logger.info(
        "Azure DI text block normalization started: case_id=%s paragraph_count=%s fallback_line_count=%s",
        case_id,
        len(paragraphs),
        len(lines) if not paragraphs else 0,
    )
    paragraph_candidates: list[dict[str, Any]] = []
    if not text_blocks_enabled:
        _append_result_warning(result, TEXT_BLOCK_DISABLED_WARNING)
        _append_candidate_warning(candidates, TEXT_BLOCK_DISABLED_WARNING)
        logger.info(
            "Azure DI text block normalization skipped: case_id=%s reason=disabled table_candidate_count=%s elapsed_seconds=%s",
            case_id,
            len(candidates),
            _elapsed(text_started),
        )
    else:
        try:
            paragraph_candidates = _paragraph_candidates(
                result=result,
                case_id=case_id,
                source_pdf=source_pdf,
                initial_section=section,
                started=text_started,
                timeout_seconds=text_block_timeout_seconds,
                max_paragraphs=max_text_block_paragraphs,
                max_paragraph_chars=max_text_block_paragraph_chars,
            )
            candidates.extend(paragraph_candidates)
            logger.info(
                "Azure DI text block normalization finished: case_id=%s candidate_count=%s elapsed_seconds=%s",
                case_id,
                len(paragraph_candidates),
                _elapsed(text_started),
            )
        except AzureDITextBlockNormalizationTimeout as exc:
            _append_result_warning(result, TEXT_BLOCK_TIMEOUT_WARNING)
            _append_candidate_warning(candidates, TEXT_BLOCK_TIMEOUT_WARNING)
            logger.warning(
                "%s case_id=%s table_candidate_count=%s elapsed_seconds=%s detail=%s",
                TEXT_BLOCK_TIMEOUT_WARNING,
                case_id,
                len(candidates),
                _elapsed(text_started),
                exc,
            )
        except Exception as exc:
            _append_result_warning(result, TEXT_BLOCK_FAILED_WARNING)
            _append_candidate_warning(candidates, TEXT_BLOCK_FAILED_WARNING)
            logger.exception(
                "%s case_id=%s table_candidate_count=%s elapsed_seconds=%s detail=%s",
                TEXT_BLOCK_FAILED_WARNING,
                case_id,
                len(candidates),
                _elapsed(text_started),
                exc,
            )

    dedupe_started = time.monotonic()
    logger.info("Azure DI duplicate/conflict cleanup started: case_id=%s candidate_count=%s", case_id, len(candidates))
    dedupe_timeout_seconds = (
        max(float(text_block_timeout_seconds), 1.0)
        if text_block_timeout_seconds is not None
        else None
    )
    deduped = _dedupe_candidates(
        candidates,
        started=dedupe_started,
        timeout_seconds=dedupe_timeout_seconds,
        case_id=case_id,
    )
    logger.info(
        "Azure DI duplicate/conflict cleanup finished: case_id=%s candidate_count=%s deduped_count=%s elapsed_seconds=%s",
        case_id,
        len(candidates),
        len(deduped),
        _elapsed(dedupe_started),
    )
    logger.info(
        "Azure DI candidate building finished: case_id=%s candidate_count=%s elapsed_seconds=%s",
        case_id,
        len(deduped),
        _elapsed(started),
    )
    return deduped


def _dedupe_candidates(
    candidates: list[dict[str, Any]],
    *,
    started: float | None = None,
    timeout_seconds: float | None = None,
    case_id: str | None = None,
    max_comparisons: int = MAX_AZURE_DI_DEDUPE_COMPARISONS,
) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    rows: list[dict[str, Any]] = []
    started = started or time.monotonic()
    for index, candidate in enumerate(candidates, start=1):
        if index > max_comparisons:
            logger.warning(
                "Azure DI duplicate/conflict cleanup comparison limit reached: case_id=%s processed=%s limit=%s",
                case_id,
                index - 1,
                max_comparisons,
            )
            break
        if index == 1 or index == len(candidates) or index % DEDUPE_LOG_INTERVAL == 0:
            try:
                _check_text_block_timeout(
                    started=started,
                    timeout_seconds=timeout_seconds,
                    case_id=case_id or "unknown",
                    stage="duplicate_cleanup",
                    index=index,
                    total=len(candidates),
                )
            except AzureDITextBlockNormalizationTimeout as exc:
                logger.warning(
                    "Azure DI duplicate/conflict cleanup timed out; returning processed candidates: case_id=%s processed=%s total=%s detail=%s",
                    case_id,
                    index - 1,
                    len(candidates),
                    exc,
                )
                break
        key = (
            candidate.get("case_id"),
            candidate.get("page_number"),
            candidate.get("row_type"),
            candidate.get("label"),
            candidate.get("value"),
            candidate.get("previous_value"),
            candidate.get("text"),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(candidate)
    return rows


def build_case_report(
    *,
    case: dict[str, Any],
    azure_result: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    row_counts = Counter(str(candidate.get("row_type") or "unknown") for candidate in candidates)
    return {
        "case_id": case.get("case_id"),
        "case_dir": case.get("case_dir"),
        "source_pdf": case.get("pdf_path"),
        "reference_available": bool(case.get("reference_available")),
        "reference_path": case.get("reference_path"),
        "reference_type": case.get("reference_type"),
        "status": "ok" if azure_result.get("ok") else "error",
        "pages_analyzed": int(azure_result.get("pages_count") or 0),
        "azure_di_tables_detected": len(azure_result.get("tables") or []),
        "azure_di_characters_detected": int(azure_result.get("content_length") or 0),
        "azure_di_runtime_seconds": float(azure_result.get("runtime_seconds") or 0),
        "candidate_count": len(candidates),
        "azure_di_candidate_count": len(candidates),
        "row_type_counts": dict(sorted(row_counts.items())),
        "warning_counts": dict(Counter(w for item in candidates for w in (item.get("warnings") or []))),
        "warnings": list(azure_result.get("warnings") or []),
        "errors": list(azure_result.get("errors") or []),
        "candidates": candidates,
        "azure_document_intelligence": {
            "ok": azure_result.get("ok"),
            "model_id": azure_result.get("model_id"),
            "pages_count": azure_result.get("pages_count"),
            "content_length": azure_result.get("content_length"),
            "tables_count": len(azure_result.get("tables") or []),
            "table_cells_count": len(azure_result.get("table_cells") or []),
            "runtime_seconds": azure_result.get("runtime_seconds"),
            "reference_xml_sent_to_provider": azure_result.get("reference_xml_sent_to_provider", False),
        },
    }


def build_azure_di_report(
    case_reports: Sequence[dict[str, Any]],
    *,
    cases_dir: str,
    output_json: str,
    run_id: str | None,
    model_id: str,
    started_at: str | None = None,
    total_runtime_seconds: float | None = None,
    pages_option: str | None = None,
) -> dict[str, Any]:
    all_candidates = [candidate for case in case_reports for candidate in case.get("candidates") or []]
    row_counts = Counter(str(candidate.get("row_type") or "unknown") for candidate in all_candidates)
    pages = sum(int(case.get("pages_analyzed") or 0) for case in case_reports)
    tables = sum(int(case.get("azure_di_tables_detected") or 0) for case in case_reports)
    chars = sum(int(case.get("azure_di_characters_detected") or 0) for case in case_reports)
    runtime = float(total_runtime_seconds if total_runtime_seconds is not None else sum(float(case.get("azure_di_runtime_seconds") or 0) for case in case_reports))
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "generated_at": utc_now_iso(),
            "started_at": started_at,
            "run_id": run_id,
            "script": "scripts/run_extraction_v2_azure_di_spike.py",
            "report_type": "azure_di_extraction_v2_spike",
            "provider": SOURCE_METHOD,
            "model_id": model_id,
            "database_mutated": False,
            "production_behavior_changed": False,
            "reference_xml_sent_to_provider": False,
            "live_model_calls": True,
            "external_provider_calls": True,
            "huggingface_used": False,
            "openai_used": False,
            "semantic_matcher_called": False,
            "cases_dir": cases_dir,
            "pages_option": pages_option,
            "output_path": output_json,
        },
        "pipeline_name": "Azure Document Intelligence Extraction v2 Spike",
        "aggregate_metrics": {
            "total_cases_processed": len(case_reports),
            "total_pdfs_processed": sum(1 for case in case_reports if case.get("source_pdf")),
            "total_candidate_rows": len(all_candidates),
            "numeric_fact_count": row_counts.get("numeric_fact", 0),
            "comparative_numeric_fact_count": row_counts.get("comparative_numeric_fact", 0),
            "subtotal_or_total_count": row_counts.get("subtotal_or_total", 0),
            "text_block_count": row_counts.get("text_block", 0),
            "metadata_count": row_counts.get("metadata", 0),
            "heading_count": row_counts.get("heading", 0),
            "unknown_count": row_counts.get("unknown", 0),
            "row_type_counts": dict(sorted(row_counts.items())),
            "azure_di_candidate_count": len(all_candidates),
            "azure_di_pages_processed": pages,
            "azure_di_tables_detected": tables,
            "azure_di_characters_detected": chars,
            "total_runtime_seconds": round(runtime, 3),
            "average_seconds_per_page": round(runtime / pages, 3) if pages else None,
            "estimated_pages_billable": pages,
            "documents_processed": len(case_reports),
        },
        "case_reports": list(case_reports),
        "sample_candidates": all_candidates[:25],
        "limitations": [
            "Read-only Azure DI spike only; no production cutover.",
            "prebuilt-layout output is converted with conservative heuristics and is not final mapping evidence.",
            "Reference XML is used only for offline comparison reports and is not sent to Azure DI.",
            "No DB writes, API/UI changes, Hugging Face/OpenAI calls, XBRL generation, or Arelle validation are performed.",
        ],
    }


def render_azure_di_report_markdown(report: dict[str, Any]) -> str:
    agg = report.get("aggregate_metrics", {})
    lines = [
        "# Azure Document Intelligence Extraction v2 Spike - Feature #13W",
        "",
        "## Summary",
        "",
        f"- Provider: {report.get('run_metadata', {}).get('provider')}",
        f"- Model ID: {report.get('run_metadata', {}).get('model_id')}",
        f"- Cases processed: {agg.get('total_cases_processed', 0)}",
        f"- Pages processed: {agg.get('azure_di_pages_processed', 0)}",
        f"- Tables detected: {agg.get('azure_di_tables_detected', 0)}",
        f"- Characters detected: {agg.get('azure_di_characters_detected', 0)}",
        f"- Candidate rows: {agg.get('total_candidate_rows', 0)}",
        f"- Numeric facts: {agg.get('numeric_fact_count', 0)}",
        f"- Comparative numeric facts: {agg.get('comparative_numeric_fact_count', 0)}",
        f"- Text blocks: {agg.get('text_block_count', 0)}",
        f"- Runtime seconds: {agg.get('total_runtime_seconds')}",
        f"- Average seconds/page: {agg.get('average_seconds_per_page')}",
        f"- Database mutated: {report.get('run_metadata', {}).get('database_mutated')}",
        f"- Production behavior changed: {report.get('run_metadata', {}).get('production_behavior_changed')}",
        f"- Reference XML sent to provider: {report.get('run_metadata', {}).get('reference_xml_sent_to_provider')}",
        "",
        "## Per Case",
        "",
        "| Case | Status | Pages | Tables | Chars | Candidates | Numeric | Comparative | Text Blocks | Runtime s |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report.get("case_reports") or []:
        counts = case.get("row_type_counts") or {}
        lines.append(
            "| {case_id} | {status} | {pages} | {tables} | {chars} | {candidates} | {numeric} | {comparative} | {text_blocks} | {runtime} |".format(
                case_id=case.get("case_id"),
                status=case.get("status"),
                pages=case.get("pages_analyzed", 0),
                tables=case.get("azure_di_tables_detected", 0),
                chars=case.get("azure_di_characters_detected", 0),
                candidates=case.get("candidate_count", 0),
                numeric=counts.get("numeric_fact", 0),
                comparative=counts.get("comparative_numeric_fact", 0),
                text_blocks=counts.get("text_block", 0),
                runtime=case.get("azure_di_runtime_seconds", 0),
            )
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def build_cost_runtime_report(azure_report: dict[str, Any], *, output_path: str | None = None) -> dict[str, Any]:
    agg = azure_report.get("aggregate_metrics") or {}
    docs = int(agg.get("documents_processed") or agg.get("total_pdfs_processed") or 0)
    pages = int(agg.get("azure_di_pages_processed") or 0)
    chars = int(agg.get("azure_di_characters_detected") or 0)
    tables = int(agg.get("azure_di_tables_detected") or 0)
    runtime = float(agg.get("total_runtime_seconds") or 0)
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "generated_at": utc_now_iso(),
            "report_type": "azure_di_cost_runtime_estimate",
            "script": "scripts/run_extraction_v2_azure_di_spike.py",
            "output_path": output_path,
            "pricing_source": "not_configured",
            "dollar_cost_estimated": False,
        },
        "summary": {
            "documents_processed": docs,
            "total_pages_processed": pages,
            "billable_pages_estimate": pages,
            "total_runtime_seconds": round(runtime, 3),
            "average_seconds_per_page": round(runtime / pages, 3) if pages else None,
            "average_seconds_per_document": round(runtime / docs, 3) if docs else None,
            "tables_per_document": round(tables / docs, 3) if docs else None,
            "characters_per_page": round(chars / pages, 3) if pages else None,
        },
        "cost_tracking_instructions": [
            "Azure Portal -> Document Intelligence resource -> Monitoring -> Metrics -> Processed Pages",
            "Azure Portal -> Cost Management + Billing -> Cost Analysis",
        ],
        "limitations": [
            "Pricing is not hard-coded in this report.",
            "No dollar estimate is produced unless pricing is explicitly supplied in a future approved feature.",
        ],
    }


def render_cost_runtime_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# Azure DI Cost and Runtime Estimate - Feature #13W",
        "",
        "## Summary",
        "",
        f"- Documents processed: {summary.get('documents_processed', 0)}",
        f"- Total pages processed: {summary.get('total_pages_processed', 0)}",
        f"- Billable pages estimate: {summary.get('billable_pages_estimate', 0)}",
        f"- Total runtime seconds: {summary.get('total_runtime_seconds')}",
        f"- Average seconds/page: {summary.get('average_seconds_per_page')}",
        f"- Average seconds/document: {summary.get('average_seconds_per_document')}",
        f"- Tables/document: {summary.get('tables_per_document')}",
        f"- Characters/page: {summary.get('characters_per_page')}",
        f"- Dollar cost estimated: {report.get('run_metadata', {}).get('dollar_cost_estimated')}",
        "",
        "## Cost Tracking",
        "",
    ]
    lines.extend(f"- {item}" for item in report.get("cost_tracking_instructions", []))
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)
