"""Deterministic section-title normalization for the #19A structure layer."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Any


UNKNOWN_SECTION = "unknown_section"
FUZZY_MATCH_THRESHOLD = 0.88
SELECTION_STATE_MARKER_RE = re.compile(
    r"[:;]\s*(?:unselected|selected)\b(?:\s*[,;.!?])?",
    re.I,
)

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "directors_report": (
        "directors report",
        "director report",
        "report of the directors",
    ),
    "statement_by_directors": (
        "statement by directors",
        "directors statement",
    ),
    "statutory_declaration": (
        "statutory declaration",
        "declaration by officer primarily responsible for the financial management",
    ),
    "independent_auditors_report": (
        "independent auditors report",
        "independent auditor report",
        "auditors report",
        "auditor report",
        "report of the independent auditors",
    ),
    "statement_of_financial_position": (
        "statement of financial position",
        "balance sheet",
    ),
    "statement_of_comprehensive_income": (
        "statement of comprehensive income",
        "statement of profit or loss and other comprehensive income",
        "statement of profit and loss and other comprehensive income",
        "profit or loss and other comprehensive income",
    ),
    "income_statement": (
        "income statement",
        "statement of income",
        "profit and loss account",
        "statement of profit or loss",
    ),
    "statement_of_changes_in_equity": (
        "statement of changes in equity",
        "changes in equity",
    ),
    "statement_of_cash_flows": (
        "statement of cash flows",
        "statement of cash flow",
        "cash flow statement",
        "cash flows statement",
    ),
    "notes_to_financial_statements": (
        "notes to the financial statements",
        "notes to financial statements",
        "notes to the accounts",
        "notes to accounts",
    ),
    "company_information": (
        "company information",
        "corporate information",
        "general information",
    ),
}


@dataclass(frozen=True)
class NormalizedSectionTitle:
    raw_title: str
    normalized_title: str
    canonical_section_type: str
    match_method: str
    confidence: float
    matched_alias: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_title": self.raw_title,
            "normalized_title": self.normalized_title,
            "canonical_section_type": self.canonical_section_type,
            "match_method": self.match_method,
            "confidence": self.confidence,
            "matched_alias": self.matched_alias,
        }


def semantic_text(value: Any) -> str:
    """Remove Azure presentation markers without changing source provenance."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = SELECTION_STATE_MARKER_RE.sub(" ", text)
    return " ".join(text.split())


def normalize_title_text(value: Any) -> str:
    text = semantic_text(value)
    text = (
        text.replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u02bc", "'")
        .replace("&", " and ")
    )
    text = re.sub(r"^\s*(?:\(?\d{1,3}\)?|[A-Za-z]|[ivxlcdm]+)\s*[.)\-:]\s*", "", text, flags=re.I)
    text = re.sub(r"\.{2,}", " ", text)
    text = re.sub(r"[\u2010-\u2015\u2212]", " ", text)
    text = re.sub(r"['`]", "", text)
    text = re.sub(r"[^0-9A-Za-z]+", " ", text)
    return " ".join(text.lower().split())


def _alias_rows() -> list[tuple[str, str]]:
    return [
        (normalize_title_text(alias), canonical)
        for canonical, aliases in SECTION_ALIASES.items()
        for alias in aliases
    ]


NORMALIZED_ALIAS_ROWS = _alias_rows()
EXACT_ALIAS_MAP = {alias: canonical for alias, canonical in NORMALIZED_ALIAS_ROWS}


def normalize_section_title(value: Any) -> NormalizedSectionTitle:
    raw = " ".join(str(value or "").split())
    normalized = normalize_title_text(raw)
    if not normalized:
        return NormalizedSectionTitle(raw, normalized, UNKNOWN_SECTION, "empty", 0.0)

    exact = EXACT_ALIAS_MAP.get(normalized)
    if exact:
        return NormalizedSectionTitle(raw, normalized, exact, "exact_alias", 1.0, normalized)

    best_alias = None
    best_canonical = UNKNOWN_SECTION
    best_score = 0.0
    for alias, canonical in NORMALIZED_ALIAS_ROWS:
        score = SequenceMatcher(None, normalized, alias).ratio()
        if score > best_score:
            best_alias = alias
            best_canonical = canonical
            best_score = score

    if best_score >= FUZZY_MATCH_THRESHOLD:
        return NormalizedSectionTitle(
            raw,
            normalized,
            best_canonical,
            "fuzzy_alias",
            round(best_score, 4),
            best_alias,
        )
    return NormalizedSectionTitle(raw, normalized, UNKNOWN_SECTION, "unresolved", 0.0)


def is_known_section_title(value: Any) -> bool:
    return normalize_section_title(value).canonical_section_type != UNKNOWN_SECTION
