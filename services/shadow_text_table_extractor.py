"""Read-only text/table-first shadow extraction prototype.

This module intentionally does not import production processors or write to the
database. It produces candidate rows for side-by-side comparison only.
"""

from __future__ import annotations

import base64
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Sequence


AMOUNT_RE = re.compile(
    r"(?<![\w/])(?:RM\s*)?(?:\(\s*)?-?\d{1,3}(?:,\d{3})+(?:\.\d+)?\s*\)?"
    r"|(?<![\w/])(?:RM\s*)?(?:\(\s*)?-?\d+(?:\.\d{2})\s*\)?",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
TOTAL_LABEL_RE = re.compile(r"\b(total|subtotal|sub-total)\b", re.IGNORECASE)
WEAK_LABEL_RE = re.compile(r"^(rm|myr|no\.?|note|notes?|total|amount)$", re.IGNORECASE)
NEGATIVE_ALLOWED_LABEL_RE = re.compile(
    r"\b(loss|expense|expenses|cost|costs|tax|depreciation|amortisation|amortization|"
    r"impairment|liabilit|payable|owing|deficit|accumulated loss|decrease|outflow)\b",
    re.IGNORECASE,
)
POSITIVE_NATURE_LABEL_RE = re.compile(
    r"\b(revenue|income|profit|asset|cash|bank|receivable|equity|capital|reserve|"
    r"retained profit|current assets|non-current assets|inventory|deposit)\b",
    re.IGNORECASE,
)

STATEMENT_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"statement of financial position|balance sheet", re.IGNORECASE), "Statement of Financial Position"),
    (re.compile(r"profit or loss|comprehensive income|income statement", re.IGNORECASE), "Statement of Comprehensive Income"),
    (re.compile(r"cash flows?", re.IGNORECASE), "Statement of Cash Flows"),
    (re.compile(r"changes in equity|retained earnings", re.IGNORECASE), "Statement of Changes in Equity"),
    (re.compile(r"directors'? report", re.IGNORECASE), "Directors Report"),
    (re.compile(r"auditors'? report|independent auditors", re.IGNORECASE), "Auditors Report"),
    (re.compile(r"significant accounting policies", re.IGNORECASE), "Notes - Significant Accounting Policies"),
    (re.compile(r"corporate information", re.IGNORECASE), "Notes - Corporate Information"),
    (re.compile(r"notes to (the )?financial statements|notes?$", re.IGNORECASE), "Notes to Financial Statements"),
]


@dataclass(frozen=True)
class AmountToken:
    raw: str
    value: Decimal
    start: int
    end: int
    is_negative: bool


@dataclass
class ShadowCandidate:
    job_id: int | None
    page_id: str | None
    page_number: int
    source_file: str
    extraction_method: str
    statement_hint: str | None
    label: str
    value: str | None
    previous_value: str | None
    year_hint: int | None
    row_type: str
    confidence: float | None = None
    confidence_note: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["confidence"] is None:
            data.pop("confidence")
        return data


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def normalize_text(value: Any) -> str:
    text = re.sub(r"[^a-z0-9&().'\-/ ]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", text).strip()


def parse_amount(value: Any) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    if not re.fullmatch(AMOUNT_RE, text):
        return None

    cleaned = re.sub(r"\b(?:RM|MYR)\b", "", text, flags=re.IGNORECASE).strip()
    negative = cleaned.startswith("-") or (cleaned.startswith("(") and cleaned.endswith(")"))
    cleaned = cleaned.replace(",", "").replace("(", "").replace(")", "").replace(" ", "")
    if cleaned.startswith("-"):
        cleaned = cleaned[1:]

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    return -amount if negative else amount


def find_amount_tokens(line: str) -> list[AmountToken]:
    tokens: list[AmountToken] = []
    for match in AMOUNT_RE.finditer(line):
        raw = match.group(0).strip()
        amount = parse_amount(raw)
        if amount is None:
            continue
        tokens.append(
            AmountToken(
                raw=raw,
                value=amount,
                start=match.start(),
                end=match.end(),
                is_negative=amount < 0,
            )
        )
    return tokens


def detect_statement_hint(text: str, current_hint: str | None = None) -> str | None:
    for pattern, hint in STATEMENT_HINTS:
        if pattern.search(text or ""):
            return hint
    return current_hint


def detect_year_hint(text: str) -> int | None:
    matches = [int(match.group(0)) for match in YEAR_RE.finditer(text or "")]
    if not matches:
        return None
    return max(matches)


def detect_suspicious_sign(label: str, value: str | None, previous_value: str | None = None) -> bool:
    amounts = [parse_amount(value), parse_amount(previous_value)]
    if not any(amount is not None and amount < 0 for amount in amounts):
        return False
    if NEGATIVE_ALLOWED_LABEL_RE.search(label or ""):
        return False
    return bool(POSITIVE_NATURE_LABEL_RE.search(label or "")) or bool(label)


def _clean_label(label: str) -> str:
    label = re.sub(r"\s+", " ", label or "").strip(" .:\t")
    label = re.sub(r"\b(?:RM|MYR)\s*$", "", label, flags=re.IGNORECASE).strip()
    return label


def _is_probable_table_row(line: str, tokens: Sequence[AmountToken]) -> bool:
    if not tokens:
        return False
    first = tokens[0]
    label = _clean_label(line[: first.start])
    if not label or len(label) > 180:
        return False
    if first.start < 3:
        return False
    if len(line) > 220 and first.start < int(len(line) * 0.45):
        return False
    return True


def _base_warnings(
    label: str,
    value: str | None,
    previous_value: str | None,
    row_type: str,
) -> list[str]:
    warnings: list[str] = []
    if not label or len(normalize_text(label)) < 3 or WEAK_LABEL_RE.match(label):
        warnings.append("weak_label")
    if not value:
        warnings.append("no_value_detected")
    if previous_value:
        warnings.append("possible_prior_year_confusion")
    if row_type == "text_block":
        warnings.append("text_block_not_numeric")
    if detect_suspicious_sign(label, value, previous_value):
        warnings.append("possible_sign_issue")
    return warnings


def parse_table_row(
    line: str,
    *,
    job_id: int | None = None,
    page_id: str | None = None,
    page_number: int = 1,
    source_file: str = "",
    statement_hint: str | None = None,
    line_number: int | None = None,
) -> ShadowCandidate | None:
    tokens = find_amount_tokens(line)
    if not _is_probable_table_row(line, tokens):
        return None

    label = _clean_label(line[: tokens[0].start])
    current = tokens[0].raw
    previous = tokens[1].raw if len(tokens) > 1 else None
    row_type = "subtotal_or_total" if TOTAL_LABEL_RE.search(label) else "numeric_fact"
    warnings = _base_warnings(label, current, previous, row_type)

    return ShadowCandidate(
        job_id=job_id,
        page_id=page_id,
        page_number=page_number,
        source_file=source_file,
        extraction_method="native_table_heuristic" if len(tokens) > 1 else "native_text",
        statement_hint=statement_hint,
        label=label,
        value=current,
        previous_value=previous,
        year_hint=detect_year_hint(line),
        row_type=row_type,
        confidence=0.72 if len(tokens) > 1 else 0.62,
        confidence_note="heuristic table row from native PDF text",
        provenance={
            "page_number": page_number,
            "line_number": line_number,
            "text_snippet": line[:500],
        },
        warnings=warnings,
    )


def classify_text_line(
    line: str,
    *,
    job_id: int | None = None,
    page_id: str | None = None,
    page_number: int = 1,
    source_file: str = "",
    statement_hint: str | None = None,
    line_number: int | None = None,
) -> ShadowCandidate | None:
    clean = re.sub(r"\s+", " ", line or "").strip()
    if not clean:
        return None

    table_row = parse_table_row(
        clean,
        job_id=job_id,
        page_id=page_id,
        page_number=page_number,
        source_file=source_file,
        statement_hint=statement_hint,
        line_number=line_number,
    )
    if table_row:
        return table_row

    tokens = find_amount_tokens(clean)
    word_count = len(clean.split())
    is_long_paragraph = len(clean) >= 140 or word_count >= 24
    if is_long_paragraph:
        label = clean[:100].rstrip(" ,.;:")
        return ShadowCandidate(
            job_id=job_id,
            page_id=page_id,
            page_number=page_number,
            source_file=source_file,
            extraction_method="native_text",
            statement_hint=statement_hint,
            label=label,
            value=clean,
            previous_value=None,
            year_hint=detect_year_hint(clean),
            row_type="text_block",
            confidence=0.55,
            confidence_note="long native-text paragraph classified as disclosure text",
            provenance={
                "page_number": page_number,
                "line_number": line_number,
                "text_snippet": clean[:500],
            },
            warnings=_base_warnings(label, None, None, "text_block"),
        )

    if not tokens and (clean.isupper() or detect_statement_hint(clean) != statement_hint):
        return ShadowCandidate(
            job_id=job_id,
            page_id=page_id,
            page_number=page_number,
            source_file=source_file,
            extraction_method="native_text",
            statement_hint=detect_statement_hint(clean, statement_hint),
            label=clean,
            value=None,
            previous_value=None,
            year_hint=detect_year_hint(clean),
            row_type="heading",
            confidence=0.45,
            confidence_note="short native-text heading with no numeric value",
            provenance={
                "page_number": page_number,
                "line_number": line_number,
                "text_snippet": clean[:500],
            },
            warnings=["no_value_detected"],
        )

    return None


def mark_duplicate_warnings(candidates: Sequence[ShadowCandidate]) -> None:
    label_counts = Counter(normalize_text(candidate.label) for candidate in candidates if candidate.label)
    label_value_counts = Counter(
        (normalize_text(candidate.label), normalize_text(candidate.value))
        for candidate in candidates
        if candidate.label and candidate.value
    )
    for candidate in candidates:
        normalized_label = normalize_text(candidate.label)
        normalized_value = normalize_text(candidate.value)
        if normalized_label and label_counts[normalized_label] > 1:
            if "possible_duplicate" not in candidate.warnings:
                candidate.warnings.append("possible_duplicate")
        if normalized_label and normalized_value and label_value_counts[(normalized_label, normalized_value)] > 1:
            if "possible_duplicate" not in candidate.warnings:
                candidate.warnings.append("possible_duplicate")


def shadow_vision_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "statement_hint": {"type": ["string", "null"]},
                        "label": {"type": "string"},
                        "value": {"type": ["string", "null"]},
                        "previous_value": {"type": ["string", "null"]},
                        "year_hint": {"type": ["integer", "null"]},
                        "row_type": {
                            "type": "string",
                            "enum": ["numeric_fact", "text_block", "heading", "subtotal_or_total", "unknown"],
                        },
                        "confidence_note": {"type": "string"},
                        "text_snippet": {"type": "string"},
                        "warnings": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                    },
                    "required": [
                        "statement_hint",
                        "label",
                        "value",
                        "previous_value",
                        "year_hint",
                        "row_type",
                        "confidence_note",
                        "text_snippet",
                        "warnings",
                    ],
                },
            }
        },
        "required": ["candidates"],
    }


class ShadowTextTableExtractor:
    """Native text/table-first extractor for read-only shadow reports."""

    def __init__(self, openai_enabled: bool = False):
        self.openai_enabled = openai_enabled

    async def extract_pdf(
        self,
        source_file: str | Path,
        *,
        job_id: int | None = None,
        page_ids_by_number: dict[int, str] | None = None,
        limit_pages: int | None = None,
        use_openai: bool | None = None,
    ) -> dict[str, Any]:
        use_openai = self.openai_enabled if use_openai is None else use_openai
        path = Path(source_file)
        candidates: list[ShadowCandidate] = []
        warnings: list[str] = []

        if not path.exists():
            return self._report(
                job_id=job_id,
                source_file=str(path),
                status="missing_pdf",
                pages_analyzed=0,
                candidates=[],
                warnings=[f"Source PDF missing: {path}"],
                use_openai=bool(use_openai),
            )

        try:
            import fitz
        except ImportError:
            return self._report(
                job_id=job_id,
                source_file=str(path),
                status="error",
                pages_analyzed=0,
                candidates=[],
                warnings=["PyMuPDF is not installed; native PDF text extraction unavailable."],
                use_openai=bool(use_openai),
            )

        pages_analyzed = 0
        try:
            with fitz.open(str(path)) as document:
                page_count = len(document)
                max_pages = page_count if limit_pages is None else min(max(limit_pages, 0), page_count)
                current_statement_hint: str | None = None

                for page_index in range(max_pages):
                    page = document[page_index]
                    page_number = page_index + 1
                    page_id = (page_ids_by_number or {}).get(page_number)
                    text = page.get_text("text") or ""
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                    pages_analyzed += 1
                    page_candidates_before = len(candidates)

                    for line_number, line in enumerate(lines, start=1):
                        current_statement_hint = detect_statement_hint(line, current_statement_hint)
                        candidate = classify_text_line(
                            line,
                            job_id=job_id,
                            page_id=page_id,
                            page_number=page_number,
                            source_file=str(path),
                            statement_hint=current_statement_hint,
                            line_number=line_number,
                        )
                        if candidate:
                            candidates.append(candidate)

                    if use_openai and (not lines or len(candidates) == page_candidates_before):
                        fallback = await self._openai_vision_fallback(
                            page=page,
                            job_id=job_id,
                            page_id=page_id,
                            page_number=page_number,
                            source_file=str(path),
                        )
                        candidates.extend(fallback["candidates"])
                        warnings.extend(fallback["warnings"])
        except Exception as exc:  # pragma: no cover - depends on local PDFs
            warnings.append(f"PDF extraction failed: {exc}")
            status = "error"
        else:
            status = "ok"

        mark_duplicate_warnings(candidates)
        return self._report(
            job_id=job_id,
            source_file=str(path),
            status=status,
            pages_analyzed=pages_analyzed,
            candidates=[candidate.to_dict() for candidate in candidates],
            warnings=warnings,
            use_openai=bool(use_openai),
        )

    async def _openai_vision_fallback(
        self,
        *,
        page: Any,
        job_id: int | None,
        page_id: str | None,
        page_number: int,
        source_file: str,
    ) -> dict[str, Any]:
        prompt = (
            "Extract conservative financial statement table/text candidates from this page. "
            "Return only rows visible on the page. Preserve labels, current values, prior values, "
            "statement hints, and short provenance snippets. Do not map to taxonomy concepts."
        )
        try:
            pixmap = page.get_pixmap(dpi=160, alpha=False)
            image_base64 = base64.b64encode(pixmap.tobytes("png")).decode("ascii")
            from services.openai_provider import async_openai_vision_json_response_from_base64

            result = await async_openai_vision_json_response_from_base64(
                image_base64,
                prompt,
                operation="shadow_text_table_vision_extraction",
                schema_name="shadow_text_table_candidates",
                schema=shadow_vision_schema(),
                max_output_tokens=4096,
            )
        except Exception as exc:  # pragma: no cover - live fallback not used in tests
            return {"candidates": [], "warnings": [f"OpenAI vision fallback failed on page {page_number}: {exc}"]}

        if not result.get("ok"):
            return {
                "candidates": [],
                "warnings": [f"OpenAI vision fallback skipped page {page_number}: {result.get('error')}"],
            }

        try:
            parsed = json.loads(str(result.get("output_text") or "{}"))
        except json.JSONDecodeError as exc:
            return {"candidates": [], "warnings": [f"OpenAI vision JSON parse failed on page {page_number}: {exc}"]}

        candidates: list[ShadowCandidate] = []
        for item in parsed.get("candidates") or []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "").strip()
            value = item.get("value")
            previous_value = item.get("previous_value")
            row_type = str(item.get("row_type") or "unknown")
            warnings = list(item.get("warnings") or [])
            for warning in _base_warnings(label, value, previous_value, row_type):
                if warning not in warnings:
                    warnings.append(warning)
            candidates.append(
                ShadowCandidate(
                    job_id=job_id,
                    page_id=page_id,
                    page_number=page_number,
                    source_file=source_file,
                    extraction_method="openai_vision_fallback",
                    statement_hint=item.get("statement_hint"),
                    label=label,
                    value=value,
                    previous_value=previous_value,
                    year_hint=item.get("year_hint"),
                    row_type=row_type,
                    confidence=None,
                    confidence_note=item.get("confidence_note") or "OpenAI vision fallback candidate",
                    provenance={
                        "page_number": page_number,
                        "text_snippet": str(item.get("text_snippet") or "")[:500],
                    },
                    warnings=warnings,
                )
            )
        return {"candidates": candidates, "warnings": []}

    @staticmethod
    def _report(
        *,
        job_id: int | None,
        source_file: str,
        status: str,
        pages_analyzed: int,
        candidates: list[dict[str, Any]],
        warnings: list[str],
        use_openai: bool,
    ) -> dict[str, Any]:
        method_counts = Counter(candidate.get("extraction_method") or "unknown" for candidate in candidates)
        row_type_counts = Counter(candidate.get("row_type") or "unknown" for candidate in candidates)
        warning_counts = Counter(
            warning
            for candidate in candidates
            for warning in candidate.get("warnings", [])
        )
        return {
            "job_id": job_id,
            "source_file": source_file,
            "status": status,
            "pages_analyzed": pages_analyzed,
            "candidate_count": len(candidates),
            "numeric_fact_count": row_type_counts.get("numeric_fact", 0),
            "text_block_count": row_type_counts.get("text_block", 0),
            "method_counts": dict(sorted(method_counts.items())),
            "row_type_counts": dict(sorted(row_type_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
            "warnings": warnings,
            "openai_allowed": use_openai,
            "candidates": candidates,
        }


def flatten_candidates(job_reports: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        candidate
        for job_report in job_reports
        for candidate in job_report.get("candidates", [])
    ]
