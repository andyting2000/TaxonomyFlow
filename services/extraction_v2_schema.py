"""Schema primitives for the read-only Industrial Extraction Pipeline v2."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from services.shadow_text_table_extractor import classify_text_line, parse_amount


EXTRACTION_METHODS = {
    "native_text",
    "native_table_heuristic",
    "openai_vision_fallback",
    "unknown",
}
ROW_TYPES = {
    "numeric_fact",
    "comparative_numeric_fact",
    "text_block",
    "metadata",
    "heading",
    "subtotal_or_total",
    "unknown",
}


def stable_warnings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    try:
        return [str(item) for item in value if str(item)]
    except TypeError:
        return [str(value)]


def normalize_extraction_method(value: Any) -> str:
    value = str(value or "").strip()
    return value if value in EXTRACTION_METHODS else "unknown"


def normalize_row_type(value: Any) -> str:
    value = str(value or "").strip()
    return value if value in ROW_TYPES else "unknown"


def _normalize_year(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    if 1900 <= year <= 2100:
        return year
    return None


@dataclass
class ExtractionV2Candidate:
    case_id: str
    source_pdf: str
    page_number: int
    extraction_method: str
    row_type: str
    statement_section: str | None
    label: str | None = None
    value: str | None = None
    previous_value: str | None = None
    current_year: int | None = None
    prior_year: int | None = None
    text: str | None = None
    source_snippet: str | None = None
    confidence: float | None = None
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.case_id = str(self.case_id or "").strip()
        self.source_pdf = str(self.source_pdf or "").strip()
        self.page_number = int(self.page_number or 0)
        self.extraction_method = normalize_extraction_method(self.extraction_method)
        self.row_type = normalize_row_type(self.row_type)
        self.statement_section = str(self.statement_section).strip() if self.statement_section else None
        self.label = str(self.label).strip() if self.label is not None else None
        self.value = str(self.value).strip() if self.value is not None else None
        self.previous_value = str(self.previous_value).strip() if self.previous_value is not None else None
        self.current_year = _normalize_year(self.current_year)
        self.prior_year = _normalize_year(self.prior_year)
        self.text = str(self.text).strip() if self.text is not None else None
        self.source_snippet = str(self.source_snippet or self.text or self.label or "").strip()[:1000]
        self.warnings = stable_warnings(self.warnings)
        if self.confidence is not None:
            self.confidence = max(0.0, min(1.0, float(self.confidence)))

        if self.row_type in {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"} and not self.value:
            if "no_value_detected" not in self.warnings:
                self.warnings.append("no_value_detected")
        if self.row_type == "comparative_numeric_fact" and not self.previous_value:
            if "missing_prior_value" not in self.warnings:
                self.warnings.append("missing_prior_value")
        if self.row_type == "text_block" and self.value:
            self.text = self.text or self.value
            self.value = None
            if "text_block_not_numeric" not in self.warnings:
                self.warnings.append("text_block_not_numeric")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_candidate(data: dict[str, Any]) -> ExtractionV2Candidate:
    return ExtractionV2Candidate(**data)


def candidate_from_shadow(
    shadow_candidate: Any,
    *,
    case_id: str,
    source_pdf: str,
) -> ExtractionV2Candidate:
    if hasattr(shadow_candidate, "to_dict"):
        data = shadow_candidate.to_dict()
    else:
        data = dict(shadow_candidate)

    row_type = data.get("row_type") or "unknown"
    previous_value = data.get("previous_value")
    if row_type == "numeric_fact" and previous_value:
        row_type = "comparative_numeric_fact"

    return ExtractionV2Candidate(
        case_id=case_id,
        source_pdf=source_pdf,
        page_number=data.get("page_number") or 0,
        extraction_method=data.get("extraction_method") or "unknown",
        row_type=row_type,
        statement_section=data.get("statement_hint"),
        label=data.get("label"),
        value=data.get("value") if row_type != "text_block" else None,
        previous_value=previous_value,
        current_year=data.get("year_hint"),
        prior_year=None,
        text=data.get("value") if row_type == "text_block" else data.get("text"),
        source_snippet=(data.get("provenance") or {}).get("text_snippet") or data.get("label"),
        confidence=data.get("confidence"),
        warnings=data.get("warnings") or [],
        provenance=data.get("provenance") or {},
    )


def candidate_from_text_line(
    line: str,
    *,
    case_id: str,
    source_pdf: str,
    page_number: int = 1,
    statement_section: str | None = None,
    line_number: int | None = None,
) -> ExtractionV2Candidate | None:
    shadow = classify_text_line(
        line,
        page_number=page_number,
        source_file=source_pdf,
        statement_hint=statement_section,
        line_number=line_number,
    )
    if shadow is None:
        clean = re.sub(r"\s+", " ", line or "").strip()
        if not clean:
            return None
        if parse_amount(clean) is None and (len(clean) >= 140 or len(clean.split()) >= 24):
            return ExtractionV2Candidate(
                case_id=case_id,
                source_pdf=source_pdf,
                page_number=page_number,
                extraction_method="native_text",
                row_type="text_block",
                statement_section=statement_section,
                label=clean[:100],
                text=clean,
                source_snippet=clean[:1000],
                confidence=0.5,
                warnings=["text_block_not_numeric"],
                provenance={"page_number": page_number, "line_number": line_number, "text_snippet": clean[:500]},
            )
        return None
    return candidate_from_shadow(shadow, case_id=case_id, source_pdf=source_pdf)
