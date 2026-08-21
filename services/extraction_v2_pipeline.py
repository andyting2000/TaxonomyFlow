"""Read-only Industrial Extraction Pipeline v2 for benchmark cases."""

from __future__ import annotations

import re
import json
import base64
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Sequence

from services.extraction_v2_schema import ExtractionV2Candidate
from services.shadow_text_table_extractor import normalize_text, utc_timestamp


PIPELINE_STAGES = [
    "document_ingestion",
    "native_text_extraction",
    "layout_or_table_heuristics",
    "row_type_classification",
    "numeric_fact_normalization",
    "text_block_grouping",
    "provenance_capture",
    "report_generation",
]
OPENAI_PAGE_MODES = {"failed-native-only", "all"}
OPENAI_LOW_TEXT_CHAR_THRESHOLD = 80
VISION_PROVIDERS = {"huggingface", "openai"}
VISION_FALLBACK_METHODS = {"huggingface_vision_fallback", "openai_vision_fallback"}


@dataclass
class BenchmarkCase:
    case_id: str
    case_dir: str
    pdf_path: str
    reference_path: str | None = None
    reference_type: str | None = None
    reference_available: bool = False
    warnings: list[str] = field(default_factory=list)


def benchmark_case_from_manifest(case: dict[str, Any]) -> BenchmarkCase:
    return BenchmarkCase(
        case_id=str(case.get("case_id") or ""),
        case_dir=str(case.get("case_dir") or ""),
        pdf_path=str(case.get("pdf_path") or ""),
        reference_path=case.get("reference_path"),
        reference_type=case.get("reference_type"),
        reference_available=bool(case.get("reference_available")),
        warnings=list(case.get("warnings") or []),
    )


def openai_v2_candidate_schema() -> dict[str, Any]:
    nullable_string = {"type": ["string", "null"]}
    nullable_number = {"type": ["number", "null"]}
    nullable_integer = {"type": ["integer", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "page_number": {"type": "integer"},
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "row_type": {
                            "type": "string",
                            "enum": [
                                "numeric_fact",
                                "comparative_numeric_fact",
                                "text_block",
                                "metadata",
                                "heading",
                                "subtotal_or_total",
                                "unknown",
                            ],
                        },
                        "statement_section": nullable_string,
                        "label": nullable_string,
                        "value": nullable_string,
                        "previous_value": nullable_string,
                        "current_year": nullable_integer,
                        "prior_year": nullable_integer,
                        "text": nullable_string,
                        "source_snippet": nullable_string,
                        "confidence": nullable_number,
                        "warnings": {"type": "array", "items": {"type": "string"}},
                        "provenance": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "page_number": nullable_integer,
                                "text_snippet": nullable_string,
                                "image_source": nullable_string,
                                "notes": nullable_string,
                            },
                            "required": ["page_number", "text_snippet", "image_source", "notes"],
                        },
                    },
                    "required": [
                        "row_type",
                        "statement_section",
                        "label",
                        "value",
                        "previous_value",
                        "current_year",
                        "prior_year",
                        "text",
                        "source_snippet",
                        "confidence",
                        "warnings",
                        "provenance",
                    ],
                },
            },
        },
        "required": ["page_number", "candidates"],
    }


def huggingface_v2_candidate_schema() -> dict[str, Any]:
    return openai_v2_candidate_schema()


def build_openai_v2_prompt(*, page_number: int, case_id: str, fallback_reason: str) -> str:
    return (
        "You are extracting benchmark-only candidates from a single rendered financial statement PDF page image. "
        "Use only the page image. Do not use or infer from any reference XML, taxonomy file, database row, or prior answer.\n\n"
        f"Case id: {case_id}\n"
        f"Page number: {page_number}\n"
        f"Fallback reason: {fallback_reason}\n\n"
        "Return structured JSON matching the provided schema. Extract financial table rows and narrative disclosure blocks. "
        "Separate numeric facts from text blocks. Do not map to taxonomy concepts. Do not invent values. Preserve labels, "
        "negative parentheses, current/prior comparative values, page number, and a short source snippet. Group narrative "
        "paragraphs into meaningful text_block candidates instead of returning every line separately. Use low confidence "
        "and warnings such as ocr_uncertain, weak_label, possible_prior_year_confusion, low_confidence_table_row, or "
        "section_unknown when evidence is unclear."
    )


def build_huggingface_v2_prompt(*, page_number: int, case_id: str, fallback_reason: str) -> str:
    return (
        "You are extracting benchmark-only candidates from a single rendered financial statement PDF page image. "
        "Use only the page image. Do not use reference XML, taxonomy files, database rows, or prior answers.\n\n"
        f"Case id: {case_id}\n"
        f"Page number: {page_number}\n"
        f"Fallback reason: {fallback_reason}\n\n"
        "Return JSON only.\n\n"
        "Preferred schema:\n"
        "{\n"
        '  "page_number": "<page number>",\n'
        '  "candidates": [\n'
        "    {\n"
        '      "row_type": "numeric_fact | comparative_numeric_fact | text_block | metadata | heading | subtotal_or_total | unknown",\n'
        '      "statement_section": "...",\n'
        '      "label": "...",\n'
        '      "value": "...",\n'
        '      "previous_value": "...",\n'
        '      "current_year": "...",\n'
        '      "prior_year": "...",\n'
        '      "text": "...",\n'
        '      "source_snippet": "...",\n'
        '      "confidence": "high | medium | low",\n'
        '      "warnings": []\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "If the page is a cover page, blank, or has no relevant financial data, return an object with page_number "
        "and an empty candidates array. Do not invent facts. Separate numeric facts from text blocks. For tables with "
        "two year columns, return current and prior values separately. Preserve negative parentheses. Group narrative "
        "paragraphs into meaningful text blocks, not line by line. Do not map to taxonomy concepts. Do not use "
        "reference XML."
    )


async def call_openai_vision_json_from_base64(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from services.openai_provider import async_openai_vision_json_response_from_base64

    return await async_openai_vision_json_response_from_base64(*args, **kwargs)


async def call_huggingface_vision_json_from_base64(image_base64: str, prompt: str, **_kwargs: Any) -> dict[str, Any]:
    from config import settings
    from huggingface_hub import AsyncInferenceClient

    if not image_base64:
        return {
            "ok": False,
            "provider": "huggingface",
            "operation": "extraction_v2_vision_fallback",
            "error_type": "missing_image",
            "error": "Image payload is empty.",
            "model": settings.ai_vlm_model_id,
        }
    token = settings.model_api_token or settings.hugging_face_token
    if token in {"", "replace-with-your-model-provider-token", "YOUR_MODEL_API_TOKEN_HERE"}:
        return {
            "ok": False,
            "provider": "huggingface",
            "operation": "extraction_v2_vision_fallback",
            "error_type": "configuration",
            "error": "MODEL_API_TOKEN is not configured; set it before running Hugging Face vision fallback.",
            "model": settings.ai_vlm_model_id,
        }

    try:
        client = AsyncInferenceClient(model=settings.ai_vlm_model_id, token=token)
        response = await client.chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                    ],
                }
            ],
            max_tokens=6000,
            temperature=0.1,
        )
        output_text = response.choices[0].message.content
    except Exception as exc:
        return {
            "ok": False,
            "provider": "huggingface",
            "operation": "extraction_v2_vision_fallback",
            "error_type": type(exc).__name__,
            "error": str(exc).replace(token, "[redacted]") if token else str(exc),
            "model": settings.ai_vlm_model_id,
        }
    return {
        "ok": True,
        "provider": "huggingface",
        "operation": "extraction_v2_vision_fallback",
        "model": settings.ai_vlm_model_id,
        "output_text": output_text,
    }


SECTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bstatement of financial position\b|balance sheet", re.IGNORECASE), "Statement of Financial Position"),
    (re.compile(r"\bstatement of profit or loss\b|\bprofit or loss\b|income statement", re.IGNORECASE), "Statement of Profit or Loss"),
    (re.compile(r"\bstatement of comprehensive income\b|comprehensive income", re.IGNORECASE), "Statement of Comprehensive Income"),
    (re.compile(r"\bstatement of changes in equity\b|changes in equity", re.IGNORECASE), "Statement of Changes in Equity"),
    (re.compile(r"\bstatement of cash flows?\b|cash flows?", re.IGNORECASE), "Statement of Cash Flows"),
    (re.compile(r"\bnotes to (the )?financial statements\b|\baccounting policies\b|basis of preparation", re.IGNORECASE), "Notes to the Financial Statements"),
    (re.compile(r"\bdirectors'? report\b", re.IGNORECASE), "Directors Report"),
    (re.compile(r"\bstatement by directors\b", re.IGNORECASE), "Statement by Directors"),
    (re.compile(r"\bstatutory declaration\b", re.IGNORECASE), "Statutory Declaration"),
    (re.compile(r"\bindependent auditors'? report\b|\bauditors'? report\b", re.IGNORECASE), "Auditors Report"),
]
NARRATIVE_HEADING_RE = re.compile(
    r"\b("
    r"directors'? report|statement by directors|statutory declaration|independent auditors'? report|"
    r"notes to (the )?financial statements|accounting policies|principal activities|basis of preparation|"
    r"revenue recognition|taxation|going concern|significant accounting estimates|financial risk management|"
    r"directors'? benefits|directors'? interests|auditors'? remuneration|approval of financial statements"
    r")\b",
    re.IGNORECASE,
)
TOTAL_LABEL_RE = re.compile(r"\b(total|subtotal|sub-total|net assets|net current|profit before|loss before|profit after|loss after)\b", re.IGNORECASE)
NEGATIVE_ALLOWED_LABEL_RE = re.compile(
    r"\b(loss|expense|expenses|cost|costs|tax|depreciation|deprn|amortisation|amortization|amort|"
    r"impairment|liabilit|payable|owing|deficit|accumulated|decrease|outflow|allowance)\b",
    re.IGNORECASE,
)
POSITIVE_NATURE_LABEL_RE = re.compile(
    r"\b(revenue|income|profit|asset|cash|bank|receivable|equity|capital|reserve|"
    r"retained profit|current assets|non-current assets|inventory|deposit|prepayment)\b",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
NOTE_PREFIX_RE = re.compile(r"^\s*(?:note\s*)?\d+[A-Za-z]?\s+")
CODE_ONLY_RE = re.compile(r"^[A-Z]{1,5}[-/]\d+[A-Z0-9/-]*$")
AMOUNT_TOKEN_RE = re.compile(
    r"(?<![\w/])(?:RM|MYR|\$)?\s*(?:\(\s*-?\d[\d,]*(?:\.\d+)?\s*\)|-?\d[\d,]*(?:\.\d+)?|[-–—])",
    re.IGNORECASE,
)
ZERO_DASHES = {"-", "–", "—"}


def clean_line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def detect_statement_section(text: str, current_section: str | None = None) -> str | None:
    for pattern, section in SECTION_PATTERNS:
        if pattern.search(text or ""):
            return section
    return current_section


def detect_year_pair(text: str, current_year: int | None = None, prior_year: int | None = None) -> tuple[int | None, int | None]:
    years = [int(match.group(1)) for match in YEAR_RE.finditer(text or "")]
    if len(years) >= 2:
        ordered = sorted(set(years), reverse=True)
        return ordered[0], ordered[1]
    if len(years) == 1:
        year = years[0]
        if current_year is None or year >= current_year:
            return year, prior_year
        return current_year, year
    return current_year, prior_year


def parse_v2_amount(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text in ZERO_DASHES:
        return "0"
    text = re.sub(r"\b(?:RM|MYR)\b|\$", "", text, flags=re.IGNORECASE).strip()
    negative = text.startswith("-") or (text.startswith("(") and text.endswith(")"))
    cleaned = text.replace(",", "").replace("(", "").replace(")", "").replace(" ", "")
    if cleaned.startswith("-"):
        cleaned = cleaned[1:]
    if not cleaned or not re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
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


def _is_usable_amount_token(raw: str) -> bool:
    token = clean_line(raw)
    if token in ZERO_DASHES:
        return True
    if re.fullmatch(r"(?:19|20)\d{2}", token):
        return False
    if "," in token or "." in token or "(" in token or "-" in token:
        return True
    if re.search(r"\b(?:RM|MYR)\b|\$", token, re.IGNORECASE):
        return True
    digits = re.sub(r"\D", "", token)
    return len(digits) >= 4 or token == "0"


def _amount_matches(line: str) -> list[re.Match[str]]:
    return [match for match in AMOUNT_TOKEN_RE.finditer(line) if _is_usable_amount_token(match.group(0))]


def _trailing_amounts(line: str) -> tuple[str, list[str], list[str]]:
    matches = _amount_matches(line)
    if not matches:
        return clean_line(line), [], []
    trailing: list[re.Match[str]] = []
    cursor = len(line)
    for match in reversed(matches):
        between = line[match.end():cursor]
        if between.strip():
            break
        trailing.insert(0, match)
        cursor = match.start()
    if not trailing:
        return clean_line(line), [], []
    label = clean_line(line[: trailing[0].start()]).strip(" .:-")
    raw_values = [clean_line(match.group(0)) for match in trailing]
    values = [value for value in (parse_v2_amount(raw) for raw in raw_values) if value is not None]
    if len(values) != len(raw_values):
        return clean_line(line), [], []
    return label, values, raw_values


def is_amount_only_line(line: str) -> bool:
    label, values, _raw_values = _trailing_amounts(line)
    return not label and len(values) == 1


def is_values_only_line(line: str) -> bool:
    label, values, _raw_values = _trailing_amounts(line)
    return not label and bool(values)


def is_code_only_line(line: str) -> bool:
    clean = clean_line(line)
    return bool(CODE_ONLY_RE.fullmatch(clean))


def is_page_metadata_line(line: str) -> bool:
    clean = clean_line(line)
    return bool(re.match(r"^\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}", clean)) or bool(
        re.match(r"^page\s+\d+\s+of\s+\d+$", clean, re.IGNORECASE)
    )


def is_probable_heading(line: str) -> bool:
    clean = clean_line(line)
    if not clean or len(clean) > 120 or _amount_matches(clean):
        return False
    if detect_statement_section(clean, None) is not None or NARRATIVE_HEADING_RE.search(clean):
        return True
    words = clean.split()
    if len(words) > 10:
        return False
    alpha_chars = [char for char in clean if char.isalpha()]
    if len(alpha_chars) < 3:
        return False
    return clean.isupper() or clean.istitle()


def is_long_paragraph(line: str) -> bool:
    clean = clean_line(line)
    if not clean or _amount_matches(clean):
        return False
    return len(clean) >= 140 or len(clean.split()) >= 24


def _candidate_warnings(
    *,
    label: str | None,
    value: str | None,
    previous_value: str | None,
    statement_section: str | None,
    current_year: int | None,
    prior_year: int | None,
    raw_values: Sequence[str] = (),
    inferred_from_pending_label: bool = False,
) -> list[str]:
    warnings: list[str] = []
    label_norm = normalize_text(label)
    if not label_norm or len(label_norm) < 3:
        warnings.append("weak_label")
    if not value:
        warnings.append("no_value_detected")
    if previous_value and not (current_year and prior_year):
        warnings.append("possible_prior_year_confusion")
    if not statement_section:
        warnings.append("section_unknown")
    if inferred_from_pending_label:
        warnings.append("low_confidence_table_row")
    if any(raw in ZERO_DASHES for raw in raw_values):
        warnings.append("low_confidence_table_row")
    numeric_values = [value, previous_value]
    has_negative = any(str(item or "").startswith("-") for item in numeric_values)
    if has_negative and label and not NEGATIVE_ALLOWED_LABEL_RE.search(label):
        if POSITIVE_NATURE_LABEL_RE.search(label) or label_norm:
            warnings.append("possible_sign_issue")
    return list(dict.fromkeys(warnings))


def _numeric_candidate(
    *,
    case_id: str,
    source_pdf: str,
    page_number: int,
    line_number: int,
    label: str,
    values: Sequence[str],
    raw_values: Sequence[str],
    statement_section: str | None,
    current_year: int | None,
    prior_year: int | None,
    snippet: str,
    inferred_from_pending_label: bool = False,
) -> ExtractionV2Candidate:
    previous_value = values[1] if len(values) > 1 else None
    row_type = "comparative_numeric_fact" if previous_value is not None else "numeric_fact"
    if row_type == "numeric_fact" and TOTAL_LABEL_RE.search(label or ""):
        row_type = "subtotal_or_total"
    warnings = _candidate_warnings(
        label=label,
        value=values[0] if values else None,
        previous_value=previous_value,
        statement_section=statement_section,
        current_year=current_year,
        prior_year=prior_year,
        raw_values=raw_values,
        inferred_from_pending_label=inferred_from_pending_label,
    )
    return ExtractionV2Candidate(
        case_id=case_id,
        source_pdf=source_pdf,
        page_number=page_number,
        extraction_method="native_table_heuristic" if previous_value is not None or inferred_from_pending_label else "native_text",
        row_type=row_type,
        statement_section=statement_section,
        label=NOTE_PREFIX_RE.sub("", label).strip(" .:-") or label,
        value=values[0] if values else None,
        previous_value=previous_value,
        current_year=current_year,
        prior_year=prior_year,
        source_snippet=snippet,
        confidence=0.78 if previous_value is not None else 0.68,
        warnings=warnings,
        provenance={"page_number": page_number, "line_number": line_number, "text_snippet": snippet[:500]},
    )


def _heading_candidate(
    *,
    case_id: str,
    source_pdf: str,
    page_number: int,
    line_number: int,
    label: str,
    statement_section: str | None,
) -> ExtractionV2Candidate:
    return ExtractionV2Candidate(
        case_id=case_id,
        source_pdf=source_pdf,
        page_number=page_number,
        extraction_method="native_text",
        row_type="heading",
        statement_section=statement_section,
        label=label,
        source_snippet=label,
        confidence=0.48,
        warnings=["no_value_detected"],
        provenance={"page_number": page_number, "line_number": line_number, "text_snippet": label[:500]},
    )


def _text_block_candidate(
    *,
    case_id: str,
    source_pdf: str,
    page_number: int,
    start_line: int,
    end_line: int,
    title: str | None,
    text: str,
    statement_section: str | None,
) -> ExtractionV2Candidate:
    label = clean_line(title or text[:100]).rstrip(" ,.;:")
    warnings = ["text_block_not_numeric"]
    if not statement_section:
        warnings.append("section_unknown")
    return ExtractionV2Candidate(
        case_id=case_id,
        source_pdf=source_pdf,
        page_number=page_number,
        extraction_method="native_text",
        row_type="text_block",
        statement_section=statement_section,
        label=label,
        text=text,
        source_snippet=text[:1000],
        confidence=0.7,
        warnings=warnings,
        provenance={
            "page_number": page_number,
            "line_number": start_line,
            "end_line_number": end_line,
            "text_snippet": text[:500],
        },
    )


def extract_candidates_from_lines(
    lines: Sequence[str],
    *,
    case_id: str,
    source_pdf: str,
    page_number: int = 1,
    initial_section: str | None = None,
    initial_current_year: int | None = None,
    initial_prior_year: int | None = None,
) -> tuple[list[ExtractionV2Candidate], dict[str, Any], list[str]]:
    """Extract v2 candidates from already ordered native PDF text lines."""
    candidates: list[ExtractionV2Candidate] = []
    warnings: list[str] = []
    section = initial_section
    current_year = initial_current_year
    prior_year = initial_prior_year
    pending_label: tuple[str, int, str] | None = None
    paragraph_lines: list[tuple[int, str]] = []
    paragraph_title: str | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph_lines, paragraph_title
        if not paragraph_lines:
            return
        text = clean_line(" ".join(line for _line_number, line in paragraph_lines))
        word_count = len(text.split())
        should_emit = len(text) >= 140 or word_count >= 24 or (
            paragraph_title is not None and len(text) >= 80 and len(paragraph_lines) >= 2
        )
        if should_emit:
            candidates.append(
                _text_block_candidate(
                    case_id=case_id,
                    source_pdf=source_pdf,
                    page_number=page_number,
                    start_line=paragraph_lines[0][0],
                    end_line=paragraph_lines[-1][0],
                    title=paragraph_title,
                    text=text,
                    statement_section=section,
                )
            )
        paragraph_lines = []
        paragraph_title = None

    index = 0
    clean_lines = [clean_line(line) for line in lines]
    while index < len(clean_lines):
        line_number = index + 1
        line = clean_lines[index]
        if not line:
            flush_paragraph()
            pending_label = None
            index += 1
            continue
        if is_page_metadata_line(line):
            index += 1
            continue

        new_section = detect_statement_section(line, section)
        if new_section != section and new_section is not None:
            flush_paragraph()
            section = new_section
        current_year, prior_year = detect_year_pair(line, current_year, prior_year)

        if is_code_only_line(line):
            index += 1
            continue

        label, values, raw_values = _trailing_amounts(line)
        if label and values and len(label) <= 160 and len(label.split()) <= 18:
            flush_paragraph()
            pending_label = None
            candidates.append(
                _numeric_candidate(
                    case_id=case_id,
                    source_pdf=source_pdf,
                    page_number=page_number,
                    line_number=line_number,
                    label=label,
                    values=values[:2],
                    raw_values=raw_values[:2],
                    statement_section=section,
                    current_year=current_year,
                    prior_year=prior_year,
                    snippet=line,
                )
            )
            index += 1
            continue

        if is_values_only_line(line) and pending_label:
            flush_paragraph()
            pending_text, pending_line_number, pending_snippet = pending_label
            next_values = list(values[:2] if current_year and prior_year else values[:1])
            next_raw_values = list(raw_values[: len(next_values)])
            next_index = index + 1
            if (
                len(next_values) == 1
                and current_year
                and prior_year
                and next_index < len(clean_lines)
                and is_amount_only_line(clean_lines[next_index])
            ):
                _next_label, found_next_values, found_next_raw_values = _trailing_amounts(clean_lines[next_index])
                if found_next_values:
                    next_values.append(found_next_values[0])
                    next_raw_values.append(found_next_raw_values[0])
                    next_index += 1
            candidates.append(
                _numeric_candidate(
                    case_id=case_id,
                    source_pdf=source_pdf,
                    page_number=page_number,
                    line_number=pending_line_number,
                    label=pending_text,
                    values=next_values[:2],
                    raw_values=next_raw_values[:2],
                    statement_section=section,
                    current_year=current_year,
                    prior_year=prior_year,
                    snippet=f"{pending_snippet} {' '.join(next_raw_values[:2])}",
                    inferred_from_pending_label=True,
                )
            )
            pending_label = None
            index = next_index
            continue

        if is_probable_heading(line):
            flush_paragraph()
            candidates.append(
                _heading_candidate(
                    case_id=case_id,
                    source_pdf=source_pdf,
                    page_number=page_number,
                    line_number=line_number,
                    label=line,
                    statement_section=section,
                )
            )
            paragraph_title = line if NARRATIVE_HEADING_RE.search(line) else paragraph_title
            pending_label = (line, line_number, line) if detect_statement_section(line, None) is None else None
            index += 1
            continue

        if is_long_paragraph(line):
            flush_paragraph()
            candidates.append(
                _text_block_candidate(
                    case_id=case_id,
                    source_pdf=source_pdf,
                    page_number=page_number,
                    start_line=line_number,
                    end_line=line_number,
                    title=paragraph_title,
                    text=line,
                    statement_section=section,
                )
            )
            pending_label = None
            index += 1
            continue

        if not _amount_matches(line) and not is_code_only_line(line) and len(line) <= 140 and re.search(r"[A-Za-z]{3,}", line):
            if section in {"Directors Report", "Statement by Directors", "Statutory Declaration", "Auditors Report", "Notes to the Financial Statements"} or paragraph_title:
                paragraph_lines.append((line_number, line))
                if paragraph_title is None and NARRATIVE_HEADING_RE.search(line):
                    paragraph_title = line
            if len(line.split()) <= 14:
                pending_label = (line, line_number, line)
            index += 1
            continue

        flush_paragraph()
        index += 1

    flush_paragraph()
    state = {"statement_section": section, "current_year": current_year, "prior_year": prior_year}
    _mark_duplicate_warnings(candidates)
    return candidates, state, warnings


def _mark_duplicate_warnings(candidates: Sequence[ExtractionV2Candidate]) -> None:
    label_counts = Counter(normalize_text(candidate.label) for candidate in candidates if candidate.label)
    label_value_counts = Counter(
        (normalize_text(candidate.label), normalize_text(candidate.value))
        for candidate in candidates
        if candidate.label and candidate.value
    )
    for candidate in candidates:
        normalized_label = normalize_text(candidate.label)
        normalized_value = normalize_text(candidate.value)
        if normalized_label and label_counts[normalized_label] > 1 and "possible_duplicate" not in candidate.warnings:
            candidate.warnings.append("possible_duplicate")
        if (
            normalized_label
            and normalized_value
            and label_value_counts[(normalized_label, normalized_value)] > 1
            and "possible_duplicate" not in candidate.warnings
        ):
            candidate.warnings.append("possible_duplicate")


def should_run_openai_fallback(page_report: dict[str, Any], *, page_mode: str = "failed-native-only") -> tuple[bool, str]:
    if page_mode == "all":
        return True, "openai_page_mode_all"
    native_text_length = int(page_report.get("native_text_length") or 0)
    native_candidate_count = int(page_report.get("native_candidate_count") or 0)
    native_numeric_or_text_count = int(page_report.get("native_numeric_or_text_count") or 0)
    page_number = int(page_report.get("page_number") or 0)
    if native_text_length == 0:
        return True, f"page_{page_number}_no_native_text_detected"
    if native_text_length < OPENAI_LOW_TEXT_CHAR_THRESHOLD:
        return True, f"page_{page_number}_low_native_text_detected"
    if native_candidate_count == 0 or native_numeric_or_text_count == 0:
        return True, f"page_{page_number}_no_native_numeric_or_text_candidates"
    return False, "native_extraction_sufficient"


def select_openai_fallback_pages(
    page_reports: Sequence[dict[str, Any]],
    *,
    page_mode: str = "failed-native-only",
    max_pages: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    selected: list[dict[str, Any]] = []
    skipped_for_limit = 0
    limit = max_pages if max_pages is not None and max_pages >= 0 else None
    for page_report in page_reports:
        should_run, reason = should_run_openai_fallback(page_report, page_mode=page_mode)
        if not should_run:
            continue
        enriched = dict(page_report)
        enriched["openai_fallback_reason"] = reason
        if limit is not None and len(selected) >= limit:
            skipped_for_limit += 1
            continue
        selected.append(enriched)
    return selected, skipped_for_limit


def _candidate_identity(candidate: ExtractionV2Candidate) -> tuple[Any, ...]:
    page_number = candidate.page_number
    row_type = candidate.row_type
    if row_type in {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}:
        return (
            "numeric",
            page_number,
            normalize_text(candidate.label),
            normalize_text(candidate.value),
            normalize_text(candidate.previous_value),
        )
    if row_type == "text_block":
        return ("text_block", page_number, normalize_text(candidate.text or candidate.source_snippet)[:220])
    return (row_type, page_number, normalize_text(candidate.label or candidate.source_snippet))


def merge_candidates_dedup(
    native_candidates: Sequence[ExtractionV2Candidate],
    fallback_candidates: Sequence[ExtractionV2Candidate],
) -> tuple[list[ExtractionV2Candidate], int]:
    merged = list(native_candidates)
    seen = {_candidate_identity(candidate) for candidate in merged}
    skipped = 0
    for candidate in fallback_candidates:
        identity = _candidate_identity(candidate)
        if identity in seen:
            skipped += 1
            continue
        seen.add(identity)
        merged.append(candidate)
    return merged, skipped


def candidate_from_report_dict(data: Any) -> ExtractionV2Candidate | None:
    if isinstance(data, ExtractionV2Candidate):
        return data
    if not isinstance(data, dict):
        return None
    try:
        candidate = ExtractionV2Candidate(**data)
    except Exception:
        return None
    extraction_method = str(data.get("extraction_method") or "")
    if extraction_method in VISION_FALLBACK_METHODS:
        candidate.extraction_method = extraction_method
    return candidate


def openai_candidate_from_item(
    item: dict[str, Any],
    *,
    case: BenchmarkCase,
    page_number: int,
    fallback_reason: str,
) -> ExtractionV2Candidate:
    return vision_candidate_from_item(
        item,
        case=case,
        page_number=page_number,
        fallback_reason=fallback_reason,
        provider="openai",
    )


def huggingface_candidate_from_item(
    item: dict[str, Any],
    *,
    case: BenchmarkCase,
    page_number: int,
    fallback_reason: str,
) -> ExtractionV2Candidate:
    return vision_candidate_from_item(
        item,
        case=case,
        page_number=page_number,
        fallback_reason=fallback_reason,
        provider="huggingface",
    )


HF_RAW_RESPONSE_PREVIEW_CHARS = 1500
HF_QWEN_ROW_COLLECTION_KEYS = ("items", "rows", "table")
HF_QWEN_LABEL_KEYS = ("label", "description", "name", "item", "account", "line_item")
HF_QWEN_VALUE_KEYS = ("value", "current_period", "current", "amount")
HF_QWEN_PREVIOUS_VALUE_KEYS = ("previous_value", "previous_period", "prior_period", "prior", "previous")


def _first_present(item: dict[str, Any], keys: Sequence[str]) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return value
    return None


def _normalize_confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip().lower()
        if text == "high":
            return 0.85
        if text == "medium":
            return 0.65
        if text == "low":
            return 0.4
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_year_like(value: Any) -> bool:
    if value in (None, ""):
        return False
    text = str(value).strip()
    if not re.fullmatch(r"(?:19|20)\d{2}", text):
        return False
    return 1900 <= int(text) <= 2100


def _normalize_year_value(value: Any) -> int | None:
    return int(str(value).strip()) if _is_year_like(value) else None


def _normalize_numeric_value(value: Any) -> str | None:
    parsed = parse_v2_amount(value)
    if parsed is not None:
        return parsed
    if value in (None, ""):
        return None
    return clean_line(value)


def _is_numeric_looking(value: Any) -> bool:
    return parse_v2_amount(value) is not None


def _looks_like_no_relevant_content(parsed: Any) -> bool:
    if not isinstance(parsed, dict):
        return False
    if parsed.get("no_relevant_content") is True:
        return True
    text = " ".join(clean_line(parsed.get(key)).lower() for key in ("reason", "status", "message", "description"))
    return any(phrase in text for phrase in ("no relevant", "blank page", "cover page", "no financial data"))


def _raw_response_payload(result: dict[str, Any]) -> Any:
    if result.get("output_text") not in (None, ""):
        return result.get("output_text")
    if result.get("parsed_json") is not None:
        return result.get("parsed_json")
    if result.get("error") not in (None, ""):
        return result.get("error")
    return None


def _raw_response_preview(result: dict[str, Any], limit: int = HF_RAW_RESPONSE_PREVIEW_CHARS) -> tuple[str | None, str]:
    payload = _raw_response_payload(result)
    payload_type = type(payload).__name__
    if payload is None:
        return None, "NoneType"
    if isinstance(payload, (dict, list)):
        text = json.dumps(payload, ensure_ascii=False, default=str)
    else:
        text = str(payload)
    return text[:limit], payload_type


def _extract_json_from_text(text: str) -> tuple[Any | None, str | None]:
    clean = (text or "").strip()
    if not clean:
        return None, "no_model_output"
    fence = re.search(r"```(?:json)?\s*(.*?)```", clean, re.IGNORECASE | re.DOTALL)
    parse_candidates = [fence.group(1).strip()] if fence else []
    parse_candidates.append(clean)
    embedded = _extract_embedded_json_object(clean)
    if embedded and embedded not in parse_candidates:
        parse_candidates.append(embedded)
    for candidate in parse_candidates:
        try:
            return json.loads(candidate), None
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return None, "output_not_json"


def _extract_embedded_json_object(text: str) -> str | None:
    start_positions = [index for index, char in enumerate(text or "") if char in "{["]
    for start in start_positions:
        opener = text[start]
        closer = "}" if opener == "{" else "]"
        stack = [closer]
        in_string = False
        escape = False
        for index in range(start + 1, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char in "{[":
                stack.append("}" if char == "{" else "]")
                continue
            if stack and char == stack[-1]:
                stack.pop()
                if not stack:
                    return text[start : index + 1]
                continue
            if char in "}]":
                break
    return None


def _normalize_qwen_candidate_item(item: dict[str, Any], *, parent_statement: str | None = None) -> dict[str, Any] | None:
    label = _first_present(item, HF_QWEN_LABEL_KEYS)
    text = _first_present(item, ("text", "narrative", "paragraph", "content"))
    value = _first_present(item, HF_QWEN_VALUE_KEYS)
    previous_value = _first_present(item, HF_QWEN_PREVIOUS_VALUE_KEYS)
    current_year = item.get("current_year")
    previous_year = item.get("previous_year")
    prior_year = item.get("prior_year")

    if _is_year_like(current_year):
        current_year = _normalize_year_value(current_year)
    elif value in (None, "") and _is_numeric_looking(current_year):
        value = current_year
        current_year = None
    else:
        current_year = _normalize_year_value(item.get("year")) or None

    if _is_year_like(previous_year):
        prior_year = _normalize_year_value(previous_year)
    elif previous_value in (None, "") and _is_numeric_looking(previous_year):
        previous_value = previous_year
    if _is_year_like(prior_year):
        prior_year = _normalize_year_value(prior_year)

    normalized_value = _normalize_numeric_value(value)
    normalized_previous = _normalize_numeric_value(previous_value)
    statement_section = _first_present(item, ("statement_section", "statement", "section")) or parent_statement
    label_text = clean_line(label)
    text_value = clean_line(text)
    source_snippet = clean_line(item.get("source_snippet") or item.get("snippet") or text_value or label_text)
    row_type = clean_line(item.get("row_type"))
    if row_type not in {
        "numeric_fact",
        "comparative_numeric_fact",
        "text_block",
        "metadata",
        "heading",
        "subtotal_or_total",
        "unknown",
    }:
        if normalized_value and normalized_previous:
            row_type = "comparative_numeric_fact"
        elif normalized_value and TOTAL_LABEL_RE.search(label_text):
            row_type = "subtotal_or_total"
        elif normalized_value and _is_numeric_looking(normalized_value):
            row_type = "numeric_fact"
        elif text_value and is_long_paragraph(text_value):
            row_type = "text_block"
        elif label_text:
            row_type = "heading" if is_probable_heading(label_text) else "unknown"
        else:
            row_type = "unknown"

    if row_type == "text_block" and not text_value:
        text_value = source_snippet or label_text
    if not any((label_text, normalized_value, normalized_previous, text_value, source_snippet)):
        return None
    return {
        "row_type": row_type,
        "statement_section": statement_section,
        "label": label_text or None,
        "value": normalized_value if row_type != "text_block" else None,
        "previous_value": normalized_previous if row_type != "text_block" else None,
        "current_year": current_year,
        "prior_year": prior_year,
        "text": text_value if row_type == "text_block" else None,
        "source_snippet": source_snippet or label_text or text_value,
        "confidence": _normalize_confidence(item.get("confidence")),
        "warnings": item.get("warnings") or [],
        "provenance": item.get("provenance") or {},
    }


def _candidate_items_from_parsed(parsed: Any) -> tuple[list[dict[str, Any]], str, bool]:
    if isinstance(parsed, dict):
        parent_statement = clean_line(parsed.get("statement") or parsed.get("section")) or None
        if "candidates" in parsed:
            raw_candidates = parsed.get("candidates")
            if isinstance(raw_candidates, list):
                return [item for item in raw_candidates if isinstance(item, dict)], "candidates", True
            return [], "candidates", True
        for key in HF_QWEN_ROW_COLLECTION_KEYS:
            raw_rows = parsed.get(key)
            if isinstance(raw_rows, list):
                normalized = [
                    item
                    for item in (
                        _normalize_qwen_candidate_item(row, parent_statement=parent_statement)
                        for row in raw_rows
                        if isinstance(row, dict)
                    )
                    if item is not None
                ]
                return normalized, key, False
        return [], "missing_candidates", False
    if isinstance(parsed, list):
        normalized = [
            item
            for item in (
                _normalize_qwen_candidate_item(row)
                for row in parsed
                if isinstance(row, dict)
            )
            if item is not None
        ]
        return normalized, "table", False
    return [], "invalid_json_type", False


def vision_candidate_from_item(
    item: dict[str, Any],
    *,
    case: BenchmarkCase,
    page_number: int,
    fallback_reason: str,
    provider: str,
) -> ExtractionV2Candidate:
    provider = provider if provider in VISION_PROVIDERS else "huggingface"
    method = f"{provider}_vision_fallback"
    warnings = list(item.get("warnings") or [])
    if method not in warnings:
        warnings.append(method)
    confidence = _normalize_confidence(item.get("confidence"))
    if confidence is None or (isinstance(confidence, (int, float)) and float(confidence) < 0.55):
        if "ocr_uncertain" not in warnings:
            warnings.append("ocr_uncertain")
    if item.get("row_type") == "text_block" and "text_block_not_numeric" not in warnings:
        warnings.append("text_block_not_numeric")
    provenance = dict(item.get("provenance") or {})
    provenance.update(
        {
            "page_number": page_number,
            "image_source": provenance.get("image_source") or "rendered_pdf_page",
            f"{provider}_fallback_reason": fallback_reason,
        }
    )
    source_snippet = clean_line(item.get("source_snippet") or item.get("text") or item.get("label") or "")
    candidate = ExtractionV2Candidate(
        case_id=case.case_id,
        source_pdf=case.pdf_path,
        page_number=page_number,
        extraction_method=method,
        row_type=item.get("row_type") or "unknown",
        statement_section=item.get("statement_section"),
        label=item.get("label"),
        value=item.get("value"),
        previous_value=item.get("previous_value"),
        current_year=item.get("current_year"),
        prior_year=item.get("prior_year"),
        text=item.get("text"),
        source_snippet=source_snippet,
        confidence=confidence,
        warnings=warnings,
        provenance=provenance,
    )
    candidate.extraction_method = method
    return candidate


def parse_openai_fallback_result(
    result: dict[str, Any],
    *,
    case: BenchmarkCase,
    page_number: int,
    fallback_reason: str,
) -> tuple[list[ExtractionV2Candidate], list[str]]:
    return parse_vision_fallback_result(
        result,
        case=case,
        page_number=page_number,
        fallback_reason=fallback_reason,
        provider="openai",
    )


def parse_huggingface_fallback_result(
    result: dict[str, Any],
    *,
    case: BenchmarkCase,
    page_number: int,
    fallback_reason: str,
) -> tuple[list[ExtractionV2Candidate], list[str]]:
    parsed = parse_vision_fallback_result_detailed(
        result,
        case=case,
        page_number=page_number,
        fallback_reason=fallback_reason,
        provider="huggingface",
    )
    return parsed["candidates"], parsed["warnings"]


def parse_vision_fallback_result(
    result: dict[str, Any],
    *,
    case: BenchmarkCase,
    page_number: int,
    fallback_reason: str,
    provider: str,
) -> tuple[list[ExtractionV2Candidate], list[str]]:
    parsed = parse_vision_fallback_result_detailed(
        result,
        case=case,
        page_number=page_number,
        fallback_reason=fallback_reason,
        provider=provider,
    )
    return parsed["candidates"], parsed["warnings"]


def parse_vision_fallback_result_detailed(
    result: dict[str, Any],
    *,
    case: BenchmarkCase,
    page_number: int,
    fallback_reason: str,
    provider: str,
) -> dict[str, Any]:
    provider = provider if provider in VISION_PROVIDERS else "huggingface"
    warnings: list[str] = []
    raw_preview, raw_response_type = _raw_response_preview(result)
    diagnostics: dict[str, Any] = {
        "provider": provider,
        "raw_response_preview": raw_preview,
        "raw_response_type": raw_response_type,
        "parsed_json_detected": False,
        "parsed_json_top_level_keys": [],
        "normalized_candidate_count": 0,
        "parser_failure_reason": None,
        "parser_status": None,
        "candidate_source": None,
    }
    if not result.get("ok"):
        error_type = result.get("error_type") or f"{provider}_error"
        error_text = result.get("error") or f"{provider} fallback failed."
        warnings.append(f"page_{page_number}_{provider}_fallback_failed:{error_type}:{error_text}")
        diagnostics["parser_failure_reason"] = "no_model_output"
        return {"candidates": [], "warnings": warnings, "diagnostics": diagnostics}

    parsed = result.get("parsed_json")
    parse_reason = None
    if parsed is None:
        parsed, parse_reason = _extract_json_from_text(str(result.get("output_text") or ""))
    if parsed is None:
        reason = parse_reason or "output_not_json"
        warnings.append(f"page_{page_number}_{provider}_fallback_parse_failed:{reason}")
        diagnostics["parser_failure_reason"] = reason
        diagnostics["parser_status"] = reason
        return {"candidates": [], "warnings": warnings, "diagnostics": diagnostics}

    diagnostics["parsed_json_detected"] = True
    if isinstance(parsed, dict):
        diagnostics["parsed_json_top_level_keys"] = sorted(str(key) for key in parsed.keys())
    raw_candidates, candidate_source, preferred_schema = _candidate_items_from_parsed(parsed)
    diagnostics["candidate_source"] = candidate_source
    if not raw_candidates:
        if candidate_source == "candidates" and isinstance(parsed, dict) and isinstance(parsed.get("candidates"), list):
            reason = "no_relevant_content_detected" if _looks_like_no_relevant_content(parsed) else "empty_candidates_returned"
        elif candidate_source in HF_QWEN_ROW_COLLECTION_KEYS or candidate_source == "table":
            reason = "qwen_items_parsed_no_candidates_after_normalization"
        else:
            reason = "json_parsed_but_no_candidates_key"
        if not (provider == "openai" and reason == "empty_candidates_returned"):
            warnings.append(f"page_{page_number}_{provider}_fallback_parse_failed:{reason}")
        diagnostics["parser_failure_reason"] = reason
        diagnostics["parser_status"] = reason
        return {"candidates": [], "warnings": warnings, "diagnostics": diagnostics}

    candidates: list[ExtractionV2Candidate] = []
    for raw_candidate in raw_candidates:
        if not isinstance(raw_candidate, dict):
            warnings.append(f"page_{page_number}_{provider}_fallback_candidate_skipped:non_object")
            continue
        try:
            candidates.append(
                vision_candidate_from_item(
                    raw_candidate,
                    case=case,
                    page_number=page_number,
                    fallback_reason=fallback_reason,
                    provider=provider,
                )
            )
        except Exception as exc:
            warnings.append(f"page_{page_number}_{provider}_fallback_candidate_skipped:{exc}")
    diagnostics["normalized_candidate_count"] = len(candidates)
    diagnostics["parser_status"] = "preferred_candidates_returned" if preferred_schema else "normalized_candidates_returned"
    if not candidates:
        reason = (
            "empty_candidates_returned"
            if candidate_source == "candidates"
            else "qwen_items_parsed_no_candidates_after_normalization"
        )
        diagnostics["parser_failure_reason"] = reason
        warnings.append(f"page_{page_number}_{provider}_fallback_parse_failed:{reason}")
    return {"candidates": candidates, "warnings": warnings, "diagnostics": diagnostics}


class ExtractionV2Pipeline:
    """Deterministic benchmark-only v2 pipeline."""

    def __init__(
        self,
        *,
        use_vision_fallback: bool = False,
        vision_provider: str = "huggingface",
        vision_max_pages: int | None = None,
        vision_page_mode: str = "failed-native-only",
        use_openai: bool = False,
        openai_max_pages: int | None = None,
        openai_page_mode: str = "failed-native-only",
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        completed_vision_pages: dict[str, set[int]] | None = None,
        previous_vision_pages_attempted: int = 0,
    ):
        self.vision_provider = "openai" if use_openai else (
            vision_provider if vision_provider in VISION_PROVIDERS else "huggingface"
        )
        self.use_vision_fallback = bool(use_vision_fallback or use_openai)
        self.vision_max_pages = openai_max_pages if use_openai else vision_max_pages
        selected_page_mode = openai_page_mode if use_openai else vision_page_mode
        self.vision_page_mode = selected_page_mode if selected_page_mode in OPENAI_PAGE_MODES else "failed-native-only"
        self.use_openai = bool(use_openai)
        self.openai_max_pages = self.vision_max_pages if self.vision_provider == "openai" else openai_max_pages
        self.openai_page_mode = self.vision_page_mode if self.vision_provider == "openai" else openai_page_mode
        self._vision_pages_attempted_total = max(int(previous_vision_pages_attempted or 0), 0)
        self._openai_pages_attempted_total = self._vision_pages_attempted_total if self.vision_provider == "openai" else 0
        self.progress_callback = progress_callback
        self.completed_vision_pages = completed_vision_pages or {}

    def _emit_progress(self, event: dict[str, Any]) -> None:
        if not self.progress_callback:
            return
        try:
            self.progress_callback(event)
        except Exception:
            return

    async def run_case(
        self,
        case: BenchmarkCase,
        *,
        limit_pages: int | None = None,
        initial_candidates: Sequence[dict[str, Any] | ExtractionV2Candidate] | None = None,
        completed_vision_pages: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        pdf_path = Path(case.pdf_path)
        warnings = list(case.warnings)
        candidates: list[ExtractionV2Candidate] = [
            candidate
            for candidate in (candidate_from_report_dict(item) for item in (initial_candidates or []))
            if candidate is not None
        ]
        status = "ok"
        pages_analyzed = 0
        vision_page_timings: list[dict[str, Any]] = []
        vision_fallback = {
            "enabled": bool(self.use_vision_fallback),
            "provider": self.vision_provider,
            "page_mode": self.vision_page_mode,
            "max_pages": self.vision_max_pages,
            "pages_attempted": 0,
            "pages_succeeded": 0,
            "pages_failed": 0,
            "pages_skipped_max_limit": 0,
            "candidates_returned": 0,
            "candidates_kept": 0,
            "duplicate_candidates_skipped": 0,
            "pages_skipped_resume": 0,
            "failures": [],
        }

        if not pdf_path.exists():
            status = "missing_pdf"
            warnings.append(f"Source PDF missing: {case.pdf_path}")
        else:
            native_report = self._extract_native_pdf(pdf_path, case=case, limit_pages=limit_pages)
            pages_analyzed = int(native_report.get("pages_analyzed") or 0)
            status = str(native_report.get("status") or "error")
            warnings.extend(native_report.get("warnings") or [])
            if candidates:
                candidates, _native_duplicate_skips = merge_candidates_dedup(
                    candidates,
                    native_report.get("candidates") or [],
                )
            else:
                candidates.extend(native_report.get("candidates") or [])
            if self.use_vision_fallback:
                fallback_runner = self._run_openai_fallbacks if self.use_openai else self._run_vision_fallbacks
                fallback_report = await fallback_runner(
                    pdf_path,
                    case=case,
                    page_reports=native_report.get("page_reports") or [],
                    completed_pages=set(completed_vision_pages or self.completed_vision_pages.get(case.case_id, set())),
                )
                vision_fallback.update(fallback_report.get("vision_fallback") or {})
                vision_page_timings.extend(fallback_report.get("vision_page_timings") or [])
                warnings.extend(fallback_report.get("warnings") or [])
                fallback_candidates = fallback_report.get("candidates") or []
                merged, duplicate_skips = merge_candidates_dedup(candidates, fallback_candidates)
                candidates = merged
                vision_fallback["duplicate_candidates_skipped"] += duplicate_skips
                vision_fallback["candidates_kept"] = sum(
                    1 for candidate in candidates if candidate.extraction_method == f"{self.vision_provider}_vision_fallback"
                )

        row_counts = Counter(candidate.row_type for candidate in candidates)
        if pages_analyzed > 0 and not candidates:
            warnings.append("no_candidates_detected")
        has_numeric = any(
            row_counts.get(row_type, 0)
            for row_type in ("numeric_fact", "comparative_numeric_fact", "subtotal_or_total")
        )
        has_text_blocks = row_counts.get("text_block", 0) > 0
        if has_numeric:
            warnings = [warning for warning in warnings if warning != "no_numeric_facts_detected"]
        if has_text_blocks:
            warnings = [warning for warning in warnings if warning != "no_text_blocks_detected"]
        if pages_analyzed > 0 and not has_numeric and "no_numeric_facts_detected" not in warnings:
            warnings.append("no_numeric_facts_detected")
        if pages_analyzed > 0 and not has_text_blocks and "no_text_blocks_detected" not in warnings:
            warnings.append("no_text_blocks_detected")
        warning_counts = Counter(warning for candidate in candidates for warning in candidate.warnings)
        warning_counts.update(warnings)
        return {
            "case_id": case.case_id,
            "case_dir": case.case_dir,
            "source_pdf": case.pdf_path,
            "reference_available": case.reference_available,
            "reference_path": case.reference_path,
            "reference_type": case.reference_type,
            "status": status,
            "stages": PIPELINE_STAGES,
            "pages_analyzed": pages_analyzed,
            "candidate_count": len(candidates),
            "native_candidate_count": sum(1 for candidate in candidates if candidate.extraction_method not in VISION_FALLBACK_METHODS),
            "huggingface_candidate_count": sum(1 for candidate in candidates if candidate.extraction_method == "huggingface_vision_fallback"),
            "openai_candidate_count": sum(1 for candidate in candidates if candidate.extraction_method == "openai_vision_fallback"),
            "vision_fallback": vision_fallback,
            "huggingface_fallback": vision_fallback if self.vision_provider == "huggingface" else {"enabled": False},
            "openai_fallback": vision_fallback if self.vision_provider == "openai" else {"enabled": False},
            "vision_page_timings": vision_page_timings,
            "row_type_counts": dict(sorted(row_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "warnings": warnings,
            "candidates": [candidate.to_dict() for candidate in candidates],
        }

    def _extract_native_pdf(
        self,
        pdf_path: Path,
        *,
        case: BenchmarkCase,
        limit_pages: int | None,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        candidates: list[ExtractionV2Candidate] = []
        page_reports: list[dict[str, Any]] = []
        pages_analyzed = 0
        state: dict[str, Any] = {"statement_section": None, "current_year": None, "prior_year": None}
        try:
            import fitz
        except ImportError:
            return {
                "status": "error",
                "pages_analyzed": 0,
                "warnings": ["PyMuPDF is not installed; native PDF text extraction unavailable."],
                "candidates": [],
                "page_reports": [],
            }

        try:
            with fitz.open(str(pdf_path)) as document:
                page_count = len(document)
                max_pages = page_count if limit_pages is None else min(max(limit_pages, 0), page_count)
                self._emit_progress(
                    {
                        "event": "case_start",
                        "case_id": case.case_id,
                        "source_pdf": case.pdf_path,
                        "total_pages": max_pages,
                        "pdf_pages": page_count,
                    }
                )
                for page_index in range(max_pages):
                    page_started = time.monotonic()
                    page = document[page_index]
                    page_number = page_index + 1
                    text = page.get_text("text") or ""
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                    pages_analyzed += 1
                    page_candidates: list[ExtractionV2Candidate] = []
                    if not lines:
                        warnings.append(f"page_{page_number}_no_native_text_detected")
                        page_reports.append(
                            {
                                "page_number": page_number,
                                "native_text_length": 0,
                                "native_line_count": 0,
                                "native_candidate_count": 0,
                                "native_numeric_or_text_count": 0,
                            }
                        )
                        self._emit_progress(
                            {
                                "event": "native_page_complete",
                                "case_id": case.case_id,
                                "source_pdf": case.pdf_path,
                                "page_number": page_number,
                                "total_pages": max_pages,
                                "native_candidate_count": 0,
                                "native_numeric_or_text_count": 0,
                                "native_text_length": 0,
                                "native_line_count": 0,
                                "elapsed_seconds": round(time.monotonic() - page_started, 3),
                            }
                        )
                        continue
                    page_candidates, state, page_warnings = extract_candidates_from_lines(
                        lines,
                        case_id=case.case_id,
                        source_pdf=case.pdf_path,
                        page_number=page_number,
                        initial_section=state.get("statement_section"),
                        initial_current_year=state.get("current_year"),
                        initial_prior_year=state.get("prior_year"),
                    )
                    candidates.extend(page_candidates)
                    warnings.extend(page_warnings)
                    page_reports.append(
                        {
                            "page_number": page_number,
                            "native_text_length": len(text.strip()),
                            "native_line_count": len(lines),
                            "native_candidate_count": len(page_candidates),
                            "native_numeric_or_text_count": sum(
                                1
                                for candidate in page_candidates
                                if candidate.row_type
                                in {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total", "text_block"}
                            ),
                        }
                    )
                    self._emit_progress(
                        {
                            "event": "native_page_complete",
                            "case_id": case.case_id,
                            "source_pdf": case.pdf_path,
                            "page_number": page_number,
                            "total_pages": max_pages,
                            "native_candidate_count": len(page_candidates),
                            "native_numeric_or_text_count": sum(
                                1
                                for candidate in page_candidates
                                if candidate.row_type
                                in {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total", "text_block"}
                            ),
                            "native_text_length": len(text.strip()),
                            "native_line_count": len(lines),
                            "elapsed_seconds": round(time.monotonic() - page_started, 3),
                        }
                    )
        except Exception as exc:  # pragma: no cover - depends on local PDFs
            warnings.append(f"PDF extraction failed: {exc}")
            return {
                "status": "error",
                "pages_analyzed": pages_analyzed,
                "warnings": warnings,
                "candidates": candidates,
                "page_reports": page_reports,
            }

        _mark_duplicate_warnings(candidates)
        if pages_analyzed > 0 and not any(
            candidate.row_type in {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
            for candidate in candidates
        ):
            warnings.append("no_numeric_facts_detected")
        if pages_analyzed > 0 and not any(candidate.row_type == "text_block" for candidate in candidates):
            warnings.append("no_text_blocks_detected")
        return {
            "status": "ok",
            "pages_analyzed": pages_analyzed,
            "warnings": warnings,
            "candidates": candidates,
            "page_reports": page_reports,
        }

    async def _run_openai_fallbacks(
        self,
        pdf_path: Path,
        *,
        case: BenchmarkCase,
        page_reports: Sequence[dict[str, Any]],
        completed_pages: set[int] | None = None,
    ) -> dict[str, Any]:
        return await self._run_vision_fallbacks(
            pdf_path,
            case=case,
            page_reports=page_reports,
            completed_pages=completed_pages,
        )

    async def _run_vision_fallbacks(
        self,
        pdf_path: Path,
        *,
        case: BenchmarkCase,
        page_reports: Sequence[dict[str, Any]],
        completed_pages: set[int] | None = None,
    ) -> dict[str, Any]:
        provider = self.vision_provider
        completed_pages = completed_pages or set()
        effective_max_pages = self.vision_max_pages
        if effective_max_pages is not None and effective_max_pages >= 0:
            effective_max_pages = max(effective_max_pages - self._vision_pages_attempted_total, 0)
        eligible_pages, _initial_skipped_for_limit = select_openai_fallback_pages(
            page_reports,
            page_mode=self.vision_page_mode,
            max_pages=None,
        )
        resume_skipped = 0
        if completed_pages:
            pending_pages: list[dict[str, Any]] = []
            for page_report in eligible_pages:
                page_number = int(page_report.get("page_number") or 0)
                if page_number in completed_pages:
                    resume_skipped += 1
                    self._emit_progress(
                        {
                            "event": "vision_page_skipped",
                            "case_id": case.case_id,
                            "source_pdf": case.pdf_path,
                            "page_number": page_number,
                            "provider": provider,
                            "reason": "resume_completed",
                        }
                    )
                    continue
                pending_pages.append(page_report)
            eligible_pages = pending_pages
        skipped_for_limit = 0
        selected_pages = eligible_pages
        if effective_max_pages is not None and effective_max_pages >= 0 and len(selected_pages) > effective_max_pages:
            selected_pages = eligible_pages[:effective_max_pages]
            skipped_for_limit = len(eligible_pages) - len(selected_pages)
            for page_report in eligible_pages[effective_max_pages:]:
                self._emit_progress(
                    {
                        "event": "vision_page_skipped",
                        "case_id": case.case_id,
                        "source_pdf": case.pdf_path,
                        "page_number": int(page_report.get("page_number") or 0),
                        "provider": provider,
                        "reason": "max_limit_reached",
                    }
                )
        metrics = {
            "enabled": True,
            "provider": provider,
            "page_mode": self.vision_page_mode,
            "max_pages": self.vision_max_pages,
            "pages_attempted": 0,
            "pages_succeeded": 0,
            "pages_failed": 0,
            "pages_skipped_max_limit": skipped_for_limit,
            "candidates_returned": 0,
            "candidates_kept": 0,
            "duplicate_candidates_skipped": 0,
            "pages_skipped_resume": resume_skipped,
            "failures": [],
            "raw_response_preview_count": 0,
            "parser_recovered_candidates": 0,
            "parser_failed_pages": 0,
            "empty_candidate_pages": 0,
            "no_relevant_content_pages": 0,
            "parser_failure_reasons": {},
        }
        warnings: list[str] = []
        candidates: list[ExtractionV2Candidate] = []
        page_timings: list[dict[str, Any]] = []
        if not selected_pages:
            return {
                "vision_fallback": metrics,
                f"{provider}_fallback": metrics,
                "warnings": warnings,
                "candidates": candidates,
                "vision_page_timings": page_timings,
            }

        try:
            import fitz
        except ImportError:
            warnings.append(f"{provider}_fallback_unavailable:pymupdf_not_installed")
            metrics["pages_failed"] = len(selected_pages)
            metrics["failures"].append("pymupdf_not_installed")
            return {
                "vision_fallback": metrics,
                f"{provider}_fallback": metrics,
                "warnings": warnings,
                "candidates": candidates,
                "vision_page_timings": page_timings,
            }

        try:
            with fitz.open(str(pdf_path)) as document:
                for page_report in selected_pages:
                    page_number = int(page_report.get("page_number") or 0)
                    fallback_reason = str(page_report.get("openai_fallback_reason") or "fallback_requested")
                    if page_number < 1 or page_number > len(document):
                        warnings.append(f"page_{page_number}_{provider}_fallback_failed:page_out_of_range")
                        metrics["pages_failed"] += 1
                        metrics["failures"].append(f"page_{page_number}:page_out_of_range")
                        self._emit_progress(
                            {
                                "event": "vision_page_complete",
                                "case_id": case.case_id,
                                "source_pdf": case.pdf_path,
                                "page_number": page_number,
                                "provider": provider,
                                "succeeded": False,
                                "candidate_count": 0,
                                "elapsed_seconds": 0.0,
                                "failure_reason": "page_out_of_range",
                                "candidates": [],
                            }
                        )
                        continue
                    metrics["pages_attempted"] += 1
                    self._vision_pages_attempted_total += 1
                    if provider == "openai":
                        self._openai_pages_attempted_total += 1
                    page = document[page_number - 1]
                    page_started = time.monotonic()
                    self._emit_progress(
                        {
                            "event": "vision_page_start",
                            "case_id": case.case_id,
                            "source_pdf": case.pdf_path,
                            "page_number": page_number,
                            "total_pages": len(document),
                            "provider": provider,
                            "fallback_reason": fallback_reason,
                        }
                    )
                    if provider == "openai":
                        page_candidates, page_warnings = await self._openai_fallback_for_page(
                            page,
                            case=case,
                            page_number=page_number,
                            fallback_reason=fallback_reason,
                        )
                        diagnostics = {}
                    else:
                        page_candidates, page_warnings, diagnostics = await self._huggingface_fallback_for_page_detailed(
                            page,
                            case=case,
                            page_number=page_number,
                            fallback_reason=fallback_reason,
                        )
                    elapsed_seconds = round(time.monotonic() - page_started, 3)
                    warnings.extend(page_warnings)
                    failure_reason = None
                    parser_failure_reason = diagnostics.get("parser_failure_reason") if diagnostics else None
                    parser_status = diagnostics.get("parser_status") if diagnostics else None
                    if provider == "huggingface" and diagnostics:
                        if diagnostics.get("raw_response_preview"):
                            metrics["raw_response_preview_count"] += 1
                        metrics["parser_recovered_candidates"] += int(diagnostics.get("normalized_candidate_count") or 0)
                        if parser_failure_reason in {"output_not_json", "json_parsed_but_no_candidates_key", "qwen_items_parsed_no_candidates_after_normalization", "no_model_output"}:
                            metrics["parser_failed_pages"] += 1
                        if parser_failure_reason == "empty_candidates_returned":
                            metrics["empty_candidate_pages"] += 1
                        if parser_failure_reason == "no_relevant_content_detected":
                            metrics["no_relevant_content_pages"] += 1
                        if parser_failure_reason:
                            parser_reasons = dict(metrics.get("parser_failure_reasons") or {})
                            parser_reasons[parser_failure_reason] = int(parser_reasons.get(parser_failure_reason) or 0) + 1
                            metrics["parser_failure_reasons"] = parser_reasons
                    if page_candidates:
                        metrics["pages_succeeded"] += 1
                        metrics["candidates_returned"] += len(page_candidates)
                        candidates.extend(page_candidates)
                    else:
                        metrics["pages_failed"] += 1
                        failure_reason = parser_failure_reason or "no_candidates_returned"
                        metrics["failures"].append(f"page_{page_number}:{failure_reason}")
                    timing = {
                        "case_id": case.case_id,
                        "page_number": page_number,
                        "provider": provider,
                        "elapsed_seconds": elapsed_seconds,
                        "succeeded": bool(page_candidates),
                        "candidate_count": len(page_candidates),
                        "failure_reason": failure_reason,
                        "parser_status": parser_status,
                        "parser_failure_reason": parser_failure_reason,
                    }
                    if diagnostics:
                        timing["diagnostics"] = diagnostics
                    page_timings.append(timing)
                    self._emit_progress(
                        {
                            "event": "vision_page_complete",
                            "case_id": case.case_id,
                            "source_pdf": case.pdf_path,
                            "page_number": page_number,
                            "total_pages": len(document),
                            "provider": provider,
                            "succeeded": bool(page_candidates),
                            "candidate_count": len(page_candidates),
                            "elapsed_seconds": elapsed_seconds,
                            "failure_reason": failure_reason,
                            "parser_status": parser_status,
                            "diagnostics": diagnostics,
                            "warnings": page_warnings,
                            "candidates": [candidate.to_dict() for candidate in page_candidates],
                        }
                    )
        except Exception as exc:  # pragma: no cover - depends on local PDFs/live model
            warnings.append(f"{provider}_fallback_failed:{exc}")
            metrics["failures"].append(str(exc))
        return {
            "vision_fallback": metrics,
            f"{provider}_fallback": metrics,
            "warnings": warnings,
            "candidates": candidates,
            "vision_page_timings": page_timings,
        }

    async def _openai_fallback_for_page(
        self,
        page: Any,
        *,
        case: BenchmarkCase,
        page_number: int,
        fallback_reason: str,
    ) -> tuple[list[ExtractionV2Candidate], list[str]]:
        try:
            pixmap = page.get_pixmap(dpi=150, alpha=False)
            image_base64 = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
        except Exception as exc:
            return [], [f"page_{page_number}_openai_fallback_render_failed:{exc}"]

        prompt = build_openai_v2_prompt(page_number=page_number, case_id=case.case_id, fallback_reason=fallback_reason)
        result = await call_openai_vision_json_from_base64(
            image_base64,
            prompt,
            operation="extraction_v2_vision_fallback",
            schema_name="extraction_v2_page_candidates",
            schema=openai_v2_candidate_schema(),
            max_output_tokens=6000,
        )
        return parse_openai_fallback_result(
            result,
            case=case,
            page_number=page_number,
            fallback_reason=fallback_reason,
        )

    async def _huggingface_fallback_for_page(
        self,
        page: Any,
        *,
        case: BenchmarkCase,
        page_number: int,
        fallback_reason: str,
    ) -> tuple[list[ExtractionV2Candidate], list[str]]:
        candidates, warnings, _diagnostics = await self._huggingface_fallback_for_page_detailed(
            page,
            case=case,
            page_number=page_number,
            fallback_reason=fallback_reason,
        )
        return candidates, warnings

    async def _huggingface_fallback_for_page_detailed(
        self,
        page: Any,
        *,
        case: BenchmarkCase,
        page_number: int,
        fallback_reason: str,
    ) -> tuple[list[ExtractionV2Candidate], list[str], dict[str, Any]]:
        try:
            pixmap = page.get_pixmap(dpi=150, alpha=False)
            image_base64 = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
        except Exception as exc:
            return [], [f"page_{page_number}_huggingface_fallback_render_failed:{exc}"], {
                "provider": "huggingface",
                "raw_response_preview": None,
                "raw_response_type": "NoneType",
                "parsed_json_detected": False,
                "parsed_json_top_level_keys": [],
                "normalized_candidate_count": 0,
                "parser_failure_reason": "render_failed",
                "parser_status": "render_failed",
            }

        prompt = build_huggingface_v2_prompt(
            page_number=page_number,
            case_id=case.case_id,
            fallback_reason=fallback_reason,
        )
        result = await call_huggingface_vision_json_from_base64(
            image_base64,
            prompt,
            operation="extraction_v2_vision_fallback",
            schema_name="extraction_v2_page_candidates",
            schema=huggingface_v2_candidate_schema(),
            max_output_tokens=6000,
        )
        parsed = parse_vision_fallback_result_detailed(
            result,
            case=case,
            page_number=page_number,
            fallback_reason=fallback_reason,
            provider="huggingface",
        )
        return parsed["candidates"], parsed["warnings"], parsed["diagnostics"]


def build_report(
    case_reports: Sequence[dict[str, Any]],
    *,
    cases_dir: str,
    output_json: Path,
    limit_pages: int | None,
    use_openai: bool = False,
    use_vision_fallback: bool = False,
    vision_provider: str = "huggingface",
    vision_page_mode: str | None = None,
    vision_max_pages: int | None = None,
    openai_page_mode: str | None = None,
    openai_max_pages: int | None = None,
    private_pdf_openai_approved: bool = False,
    reference_xml_sent_to_openai: bool = False,
    run_id: str | None = None,
    interrupted: bool = False,
    resumed_from_checkpoint: bool = False,
    checkpoint_path: str | None = None,
    duration_seconds: float | None = None,
    flags: dict[str, Any] | None = None,
    text_model_id: str | None = None,
    vision_model_id: str | None = None,
    embedding_model_id: str | None = None,
    checkpoint_vision_max_pages: int | None = None,
    effective_vision_max_pages: int | None = None,
    previous_vision_pages_attempted: int = 0,
    additional_vision_pages_attempted: int = 0,
    total_vision_pages_attempted: int | None = None,
    cases_skipped_because_fully_resolved: int = 0,
    cases_partially_resumed: int = 0,
) -> dict[str, Any]:
    all_candidates = [
        candidate
        for case_report in case_reports
        for candidate in case_report.get("candidates", [])
    ]
    row_counts = Counter(candidate.get("row_type") or "unknown" for candidate in all_candidates)
    method_counts = Counter(candidate.get("extraction_method") or "unknown" for candidate in all_candidates)
    warning_counts = Counter(
        warning
        for case_report in case_reports
        for warning in (case_report.get("warnings") or [])
    )
    warning_counts.update(
        warning
        for candidate in all_candidates
        for warning in (candidate.get("warnings") or [])
    )
    huggingface_metrics = Counter()
    openai_metrics = Counter()
    failure_reasons = Counter()
    hf_parser_failure_reasons = Counter()
    slowest_pages: list[dict[str, Any]] = []
    for case_report in case_reports:
        hf_fallback = case_report.get("huggingface_fallback") or {}
        openai_fallback = case_report.get("openai_fallback") or {}
        for key in (
            "pages_attempted",
            "pages_succeeded",
            "pages_failed",
            "pages_skipped_max_limit",
            "pages_skipped_resume",
            "candidates_returned",
            "candidates_kept",
            "duplicate_candidates_skipped",
            "raw_response_preview_count",
            "parser_recovered_candidates",
            "parser_failed_pages",
            "empty_candidate_pages",
            "no_relevant_content_pages",
        ):
            huggingface_metrics[key] += int(hf_fallback.get(key) or 0)
            openai_metrics[key] += int(openai_fallback.get(key) or 0)
        for reason, count in (hf_fallback.get("parser_failure_reasons") or {}).items():
            hf_parser_failure_reasons[str(reason) or "unknown"] += int(count or 0)
        for failure in list(hf_fallback.get("failures") or []) + list(openai_fallback.get("failures") or []):
            failure_reasons[str(failure).split(":", 1)[-1] or "unknown"] += 1
        slowest_pages.extend(case_report.get("vision_page_timings") or [])
    active_provider = "openai" if use_openai else vision_provider
    active_use_vision = bool(use_vision_fallback or use_openai)
    active_attempts = openai_metrics["pages_attempted"] if active_provider == "openai" else huggingface_metrics["pages_attempted"]
    total_vision_pages_attempted = (
        int(total_vision_pages_attempted)
        if total_vision_pages_attempted is not None
        else int(previous_vision_pages_attempted or 0) + int(active_attempts or 0)
    )
    active_elapsed = sum(float(page.get("elapsed_seconds") or 0) for page in slowest_pages if page.get("provider") == active_provider)
    average_seconds_per_vision_page = round(active_elapsed / active_attempts, 3) if active_attempts else None
    slowest_pages = sorted(
        slowest_pages,
        key=lambda page: float(page.get("elapsed_seconds") or 0),
        reverse=True,
    )[:10]
    if text_model_id is None or vision_model_id is None or embedding_model_id is None:
        try:
            from config import settings

            text_model_id = text_model_id or settings.ai_text_model_id
            vision_model_id = vision_model_id or settings.ai_vlm_model_id
            embedding_model_id = embedding_model_id or settings.embedding_model_id
        except Exception:
            pass
    return {
        "run_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "script": "scripts/run_extraction_v2.py",
            "read_only": True,
            "database_mutated": False,
            "production_behavior_changed": False,
            "ui_upload_required": False,
            "interrupted": bool(interrupted),
            "resumed_from_checkpoint": bool(resumed_from_checkpoint),
            "checkpoint_path": checkpoint_path,
            "checkpoint_vision_max_pages": checkpoint_vision_max_pages,
            "effective_vision_max_pages": effective_vision_max_pages,
            "previous_vision_pages_attempted": int(previous_vision_pages_attempted or 0),
            "additional_vision_pages_attempted": int(additional_vision_pages_attempted or 0),
            "total_vision_pages_attempted": total_vision_pages_attempted,
            "pages_skipped_because_already_attempted": (
                openai_metrics["pages_skipped_resume"] if active_provider == "openai" else huggingface_metrics["pages_skipped_resume"]
            ),
            "pages_remaining_unattempted_due_max_limit": (
                openai_metrics["pages_skipped_max_limit"] if active_provider == "openai" else huggingface_metrics["pages_skipped_max_limit"]
            ),
            "cases_skipped_because_fully_resolved": int(cases_skipped_because_fully_resolved or 0),
            "cases_partially_resumed": int(cases_partially_resumed or 0),
            "duration_seconds": duration_seconds,
            "average_seconds_per_vision_page": average_seconds_per_vision_page,
            "slowest_pages": slowest_pages,
            "flags": flags or {},
            "vision_fallback_used": active_use_vision,
            "vision_provider": active_provider if active_use_vision else None,
            "vision_model_id": vision_model_id if active_use_vision else None,
            "text_model_id": text_model_id,
            "embedding_model_id": embedding_model_id,
            "vision_page_mode": (openai_page_mode if use_openai else vision_page_mode) if active_use_vision else None,
            "vision_max_pages": (openai_max_pages if use_openai else vision_max_pages) if active_use_vision else None,
            "huggingface_used": active_use_vision and active_provider == "huggingface",
            "openai_used": bool(use_openai),
            "private_pdf_openai_approved": bool(private_pdf_openai_approved),
            "reference_xml_sent_to_openai": bool(reference_xml_sent_to_openai),
            "reference_xml_sent_to_model": False,
            "openai_page_mode": openai_page_mode,
            "openai_max_pages": openai_max_pages,
            "limit_pages": limit_pages,
            "cases_dir": cases_dir,
            "output_path": str(output_json),
        },
        "pipeline_name": "Industrial Extraction Pipeline v2",
        "pipeline_stages": PIPELINE_STAGES,
        "aggregate_metrics": {
            "total_cases_processed": len(case_reports),
            "total_pdfs_processed": sum(1 for report in case_reports if report.get("source_pdf")),
            "total_candidate_rows": len(all_candidates),
            "numeric_fact_count": row_counts.get("numeric_fact", 0),
            "comparative_numeric_fact_count": row_counts.get("comparative_numeric_fact", 0),
            "text_block_count": row_counts.get("text_block", 0),
            "metadata_count": row_counts.get("metadata", 0),
            "heading_count": row_counts.get("heading", 0),
            "subtotal_or_total_count": row_counts.get("subtotal_or_total", 0),
            "unknown_count": row_counts.get("unknown", 0),
            "row_type_counts": dict(sorted(row_counts.items())),
            "extraction_method_counts": dict(sorted(method_counts.items())),
            "native_candidate_count": len(all_candidates)
            - method_counts.get("openai_vision_fallback", 0)
            - method_counts.get("huggingface_vision_fallback", 0),
            "huggingface_candidate_count": method_counts.get("huggingface_vision_fallback", 0),
            "openai_candidate_count": method_counts.get("openai_vision_fallback", 0),
            "huggingface_fallback_pages_attempted": huggingface_metrics["pages_attempted"],
            "huggingface_fallback_pages_succeeded": huggingface_metrics["pages_succeeded"],
            "huggingface_fallback_pages_failed": huggingface_metrics["pages_failed"],
            "huggingface_fallback_pages_skipped_max_limit": huggingface_metrics["pages_skipped_max_limit"],
            "huggingface_fallback_pages_skipped_resume": huggingface_metrics["pages_skipped_resume"],
            "huggingface_candidates_returned": huggingface_metrics["candidates_returned"],
            "huggingface_candidates_kept": huggingface_metrics["candidates_kept"],
            "huggingface_duplicate_candidates_skipped": huggingface_metrics["duplicate_candidates_skipped"],
            "hf_raw_response_preview_count": huggingface_metrics["raw_response_preview_count"],
            "hf_parser_recovered_candidates": huggingface_metrics["parser_recovered_candidates"],
            "hf_parser_failed_pages": huggingface_metrics["parser_failed_pages"],
            "hf_empty_candidate_pages": huggingface_metrics["empty_candidate_pages"],
            "hf_no_relevant_content_pages": huggingface_metrics["no_relevant_content_pages"],
            "hf_parser_failure_reasons": dict(sorted(hf_parser_failure_reasons.items())),
            "openai_fallback_pages_attempted": openai_metrics["pages_attempted"],
            "openai_fallback_pages_succeeded": openai_metrics["pages_succeeded"],
            "openai_fallback_pages_failed": openai_metrics["pages_failed"],
            "openai_fallback_pages_skipped_max_limit": openai_metrics["pages_skipped_max_limit"],
            "openai_fallback_pages_skipped_resume": openai_metrics["pages_skipped_resume"],
            "openai_candidates_returned": openai_metrics["candidates_returned"],
            "openai_candidates_kept": openai_metrics["candidates_kept"],
            "openai_duplicate_candidates_skipped": openai_metrics["duplicate_candidates_skipped"],
            "vision_failures_by_reason": dict(sorted(failure_reasons.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
        },
        "case_reports": list(case_reports),
        "sample_candidates": all_candidates[:20],
        "limitations": [
            "Benchmark-only v2 extraction; no production cutover.",
            "Native text/table heuristics are deterministic and intentionally conservative.",
            "Hugging Face vision fallback is opt-in only and benchmark-scoped when enabled.",
            "OpenAI fallback metrics may appear only for historical/legacy reports.",
            "No DB writes, XBRL generation, Arelle validation, UI upload, or production mapping are performed.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report["aggregate_metrics"]
    lines = [
        "# Extraction v2 Benchmark Report",
        "",
        "## Executive Summary",
        "",
        f"- Cases processed: {aggregate['total_cases_processed']}",
        f"- PDFs processed: {aggregate['total_pdfs_processed']}",
        f"- Candidate rows: {aggregate['total_candidate_rows']}",
        f"- Numeric facts: {aggregate['numeric_fact_count']}",
        f"- Comparative numeric facts: {aggregate['comparative_numeric_fact_count']}",
        f"- Text blocks: {aggregate['text_block_count']}",
        f"- Metadata rows: {aggregate['metadata_count']}",
        f"- Headings: {aggregate['heading_count']}",
        f"- Unknown rows: {aggregate['unknown_count']}",
        f"- Vision fallback used: {report['run_metadata'].get('vision_fallback_used', False)}",
        f"- Vision provider: {report['run_metadata'].get('vision_provider')}",
        f"- Resumed from checkpoint: {report['run_metadata'].get('resumed_from_checkpoint', False)}",
        f"- Effective vision max pages: {report['run_metadata'].get('effective_vision_max_pages')}",
        f"- Additional vision pages attempted after resume: {report['run_metadata'].get('additional_vision_pages_attempted', 0)}",
        f"- Hugging Face used: {report['run_metadata'].get('huggingface_used', False)}",
        f"- OpenAI used: {report['run_metadata']['openai_used']}",
        f"- Private PDF OpenAI approval: {report['run_metadata'].get('private_pdf_openai_approved', False)}",
        f"- Reference XML sent to OpenAI: {report['run_metadata'].get('reference_xml_sent_to_openai', False)}",
        f"- Native candidates: {aggregate.get('native_candidate_count', 0)}",
        f"- Hugging Face candidates: {aggregate.get('huggingface_candidate_count', 0)}",
        f"- OpenAI candidates: {aggregate.get('openai_candidate_count', 0)}",
        f"- Hugging Face fallback pages attempted: {aggregate.get('huggingface_fallback_pages_attempted', 0)}",
        f"- Hugging Face fallback pages succeeded: {aggregate.get('huggingface_fallback_pages_succeeded', 0)}",
        f"- Hugging Face fallback pages failed: {aggregate.get('huggingface_fallback_pages_failed', 0)}",
        f"- Hugging Face parser recovered candidates: {aggregate.get('hf_parser_recovered_candidates', 0)}",
        f"- Hugging Face parser failed pages: {aggregate.get('hf_parser_failed_pages', 0)}",
        f"- Hugging Face raw response previews: {aggregate.get('hf_raw_response_preview_count', 0)}",
        f"- OpenAI fallback pages attempted: {aggregate.get('openai_fallback_pages_attempted', 0)}",
        f"- OpenAI fallback pages succeeded: {aggregate.get('openai_fallback_pages_succeeded', 0)}",
        f"- OpenAI fallback pages failed: {aggregate.get('openai_fallback_pages_failed', 0)}",
        f"- OpenAI fallback pages skipped by limit: {aggregate.get('openai_fallback_pages_skipped_max_limit', 0)}",
        f"- UI upload required: {report['run_metadata']['ui_upload_required']}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        "",
        "## Cases",
        "",
        "| Case | Status | Reference | Pages | Candidates | Native | Hugging Face | OpenAI | Numeric | Comparative | Text Blocks | Warnings |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case_report in report["case_reports"]:
        row_counts = case_report.get("row_type_counts") or {}
        lines.append(
            "| {case_id} | {status} | {reference} | {pages} | {candidates} | {native} | {huggingface} | {openai} | {numeric} | {comparative} | {text_blocks} | {warnings} |".format(
                case_id=case_report["case_id"],
                status=case_report["status"],
                reference=case_report.get("reference_type") or "missing",
                pages=case_report.get("pages_analyzed", 0),
                candidates=case_report.get("candidate_count", 0),
                native=case_report.get("native_candidate_count", 0),
                huggingface=case_report.get("huggingface_candidate_count", 0),
                openai=case_report.get("openai_candidate_count", 0),
                numeric=row_counts.get("numeric_fact", 0),
                comparative=row_counts.get("comparative_numeric_fact", 0),
                text_blocks=row_counts.get("text_block", 0),
                warnings=sum((case_report.get("warning_counts") or {}).values()),
            )
        )
    lines.extend(["", "## Pipeline Stages", ""])
    lines.extend(f"- {stage}" for stage in report.get("pipeline_stages", []))
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def default_output_path(reports_dir: Path) -> Path:
    return reports_dir / f"extraction_v2_report_{utc_timestamp()}.json"
