"""Schemas for read-only reference XML/XBRL parsing reports."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


TEXT_BLOCK_LOCAL_NAME_HINTS = (
    "textblock",
    "disclosure",
    "explanation",
    "description",
    "policy",
    "policies",
    "notes",
    "directorsreport",
    "auditorsreport",
)


def stable_warnings(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    try:
        return [str(item) for item in value if str(item)]
    except TypeError:
        return [str(value)]


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    return cleaned or None


def normalize_numeric_value(value: Any) -> str | None:
    text = clean_text(value)
    if text is None:
        return None
    cleaned = text.replace(",", "").replace(" ", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    cleaned = re.sub(r"^[A-Za-z$]+", "", cleaned)
    cleaned = re.sub(r"[^0-9.+-]", "", cleaned)
    if cleaned in {"", "-", "+", ".", "-.", "+."}:
        return None
    try:
        decimal_value = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    normalized = format(decimal_value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def looks_numeric(value: Any) -> bool:
    return normalize_numeric_value(value) is not None


def is_text_block_candidate(local_name: str | None, value: Any) -> bool:
    local_raw = local_name or ""
    local = re.sub(r"[^a-z0-9]", "", local_raw.lower())
    text = clean_text(value) or ""
    if any(hint in local for hint in TEXT_BLOCK_LOCAL_NAME_HINTS):
        return True
    if local.endswith("report") and "reporting" not in local:
        return True
    return len(text) >= 240 or len(text.split()) >= 36


@dataclass
class ReferenceFact:
    case_id: str
    reference_path: str
    fact_id: str | None
    concept_name: str
    namespace_uri: str | None
    local_name: str
    qname: str
    context_ref: str | None
    unit_ref: str | None
    decimals: str | None
    precision: str | None
    value: str | None
    normalized_value: str | None
    is_numeric: bool
    is_text_block: bool
    is_nil: bool
    period_start: str | None
    period_end: str | None
    instant: str | None
    entity_identifier: str | None
    dimensions: list[dict[str, Any]] = field(default_factory=list)
    source_line_or_position: int | None = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.case_id = str(self.case_id or "").strip()
        self.reference_path = str(self.reference_path or "").strip()
        self.fact_id = str(self.fact_id).strip() if self.fact_id not in (None, "") else None
        self.concept_name = str(self.concept_name or self.local_name or "").strip()
        self.namespace_uri = str(self.namespace_uri).strip() if self.namespace_uri else None
        self.local_name = str(self.local_name or "").strip()
        self.qname = str(self.qname or self.local_name or "").strip()
        self.context_ref = str(self.context_ref).strip() if self.context_ref else None
        self.unit_ref = str(self.unit_ref).strip() if self.unit_ref else None
        self.decimals = str(self.decimals).strip() if self.decimals is not None else None
        self.precision = str(self.precision).strip() if self.precision is not None else None
        self.value = clean_text(self.value)
        self.normalized_value = normalize_numeric_value(self.value) if self.normalized_value is None else self.normalized_value
        self.is_numeric = bool(self.is_numeric)
        self.is_text_block = bool(self.is_text_block)
        self.is_nil = bool(self.is_nil)
        self.period_start = str(self.period_start).strip() if self.period_start else None
        self.period_end = str(self.period_end).strip() if self.period_end else None
        self.instant = str(self.instant).strip() if self.instant else None
        self.entity_identifier = str(self.entity_identifier).strip() if self.entity_identifier else None
        self.dimensions = list(self.dimensions or [])
        self.warnings = stable_warnings(self.warnings)

        if self.is_numeric and self.unit_ref is None:
            self.warnings.append("numeric_looking_fact_without_unit_ref")
        if self.is_text_block and self.is_numeric:
            self.warnings.append("text_block_marked_numeric")

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.instant:
            payload["period"] = {"type": "instant", "instant": self.instant}
        elif self.period_start or self.period_end:
            payload["period"] = {
                "type": "duration",
                "start_date": self.period_start,
                "end_date": self.period_end,
            }
        else:
            payload["period"] = {"type": "unknown"}
        return payload


@dataclass
class ReferenceCaseReport:
    case_id: str
    reference_path: str
    reference_type: str | None
    total_facts: int
    numeric_fact_count: int
    text_fact_count: int
    text_block_count: int
    nil_fact_count: int
    contexts_count: int
    units_count: int
    concepts_count: int
    facts_by_namespace: dict[str, int]
    facts_by_context: dict[str, int]
    parse_warnings: list[str] = field(default_factory=list)
    facts: list[dict[str, Any]] = field(default_factory=list)
    sample_facts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
