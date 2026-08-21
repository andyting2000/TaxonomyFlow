"""Reusable lexical quality rules for TOC titles and body heading anchors."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from services.section_title_normalization import normalize_title_text


MEANINGLESS_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
    }
)
SECTION_MARKER_RE = re.compile(r"^\s*\(?\s*(?:[a-z]|[ivxlcdm]+|\d+)\s*\)?[.)\-:]?\s*$", re.I)
ADDRESS_RE = re.compile(
    r"^\s*(?:no\.?|lot|unit|level|floor|suite|block)\s*\d+\b|"
    r"\b(?:jalan|jln\.?|persiaran|lorong|street|road|avenue)\b.*\b\d+\b",
    re.I,
)
COMPANY_NUMBER_RE = re.compile(
    r"\b(?:company|registration|business)\s+(?:no\.?|number)\b",
    re.I,
)
CONTACT_DETAIL_RE = re.compile(
    r"\b(?:tel(?:ephone)?|fax|mobile|account)\s*(?:no\.?|number|:)\s*[+()\d]",
    re.I,
)
DATE_ONLY_RE = re.compile(
    r"^\s*(?:\d{1,2}[./-]){2}\d{2,4}\s*$|"
    r"^\s*\d{1,2}\s+(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|"
    r"jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|"
    r"nov(?:ember)?|dec(?:ember)?)\s+\d{2,4}\s*$",
    re.I,
)
CONTROLLED_TOKEN_EQUIVALENTS = {
    "accounts": "account",
    "auditors": "auditor",
    "directors": "director",
    "flows": "flow",
    "reports": "report",
    "statements": "statement",
}


@dataclass(frozen=True)
class HeadingQuality:
    normalized_text: str
    tokens: tuple[str, ...]
    meaningful_tokens: tuple[str, ...]
    meaningful_character_count: int
    score: float
    accepted: bool
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "normalized_text": self.normalized_text,
            "tokens": list(self.tokens),
            "meaningful_tokens": list(self.meaningful_tokens),
            "meaningful_character_count": self.meaningful_character_count,
            "score": self.score,
            "accepted": self.accepted,
            "rejection_reason": self.rejection_reason,
        }


def meaningful_title_tokens(value: Any) -> tuple[str, ...]:
    return tuple(
        token
        for token in normalize_title_text(value).split()
        if token not in MEANINGLESS_TOKENS and not token.isdigit()
    )


def controlled_title_tokens(value: Any) -> tuple[str, ...]:
    """Normalize only explicit, safe financial-heading singular/plural pairs."""
    return tuple(
        CONTROLLED_TOKEN_EQUIVALENTS.get(token, token)
        for token in normalize_title_text(value).split()
    )


def core_title_tokens(value: Any) -> tuple[str, ...]:
    return tuple(
        token
        for token in controlled_title_tokens(value)
        if token not in MEANINGLESS_TOKENS and not token.isdigit()
    )


def evaluate_heading_quality(value: Any) -> HeadingQuality:
    raw = " ".join(str(value or "").split())
    normalized = normalize_title_text(raw)
    tokens = tuple(normalized.split())
    meaningful = meaningful_title_tokens(raw)
    meaningful_characters = sum(len(token) for token in meaningful)
    rejection_reason = None
    if not normalized:
        rejection_reason = "empty_heading"
    elif SECTION_MARKER_RE.fullmatch(raw):
        rejection_reason = "section_marker_only"
    elif normalized.isdigit():
        rejection_reason = "numeric_only"
    elif len(tokens) == 1 and re.fullmatch(r"[ivxlcdm]+", tokens[0], re.I):
        rejection_reason = "roman_numeral_only"
    elif not meaningful:
        rejection_reason = "stop_words_only"
    elif meaningful_characters < 3:
        rejection_reason = "heading_too_short"
    elif len(meaningful) == 1 and len(meaningful[0]) <= 2:
        rejection_reason = "short_fragment"

    accepted = rejection_reason is None
    score = 0.0
    if accepted:
        score = min(
            1.0,
            0.48
            + min(0.30, meaningful_characters / 80.0)
            + min(0.22, len(meaningful) * 0.075),
        )
    return HeadingQuality(
        normalized_text=normalized,
        tokens=tokens,
        meaningful_tokens=meaningful,
        meaningful_character_count=meaningful_characters,
        score=round(score, 4),
        accepted=accepted,
        rejection_reason=rejection_reason,
    )


def toc_title_rejection_reason(value: Any) -> str | None:
    raw = " ".join(str(value or "").split())
    quality = evaluate_heading_quality(raw)
    if not quality.accepted:
        return quality.rejection_reason
    if ADDRESS_RE.search(raw):
        return "address_pattern"
    if COMPANY_NUMBER_RE.search(raw):
        return "company_number_pattern"
    if CONTACT_DETAIL_RE.search(raw):
        return "contact_or_account_detail_pattern"
    if DATE_ONLY_RE.fullmatch(raw):
        return "date_only"
    return None
