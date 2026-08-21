"""Candidate-constrained LLM taxonomy/template mapping suggestions.

This module runs after Azure DI extraction and deterministic mapping. It does
not re-extract PDFs and it never asks the model to invent concepts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from database import (
    ExtractedDataItem,
    FilingJob,
    FinancialStatementPage,
    LLMMappingSuggestion,
)
from services.azure_di_production_mapping import (
    azure_di_candidate_template_matches,
    diagnose_azure_di_candidate_mapping,
    normalize_text,
    strip_note_references,
)
from services.xbrl_template_service import get_xbrl_template_service

logger = logging.getLogger(__name__)

PLACEHOLDER_TOKENS = {"", "replace-with-your-model-provider-token", "YOUR_MODEL_API_TOKEN_HERE"}
RAW_RESPONSE_PREVIEW_CHARS = 1200
DISQUALIFYING_REJECTION_REASONS = {
    "rejected_generic_label",
    "rejected_note_number_only",
    "rejected_person_or_company_name",
}
VALID_SUGGESTION_STATUSES = {"suggested", "accepted", "ignored", "rejected"}
LLM_HARD_AMBIGUOUS_LABELS = {
    "trade and other receivables",
    "trade and other current receivables",
    "trade and other payables",
    "trade and other current payables",
}

LLM_BROAD_TEMPLATE_CODES = (
    "210000",
    "210100",
    "220000",
    "220100",
    "310000",
    "320000",
    "410000",
    "420000",
    "510000",
    "520000",
    "610000",
    "620000",
)
LLM_TOKEN_STOPWORDS = {
    "and",
    "at",
    "for",
    "from",
    "in",
    "of",
    "the",
    "to",
    "year",
}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FEWSHOT_ALIGNMENT_REPORT = PROJECT_ROOT / "reports" / "golden_mbrs_mapping_alignment_17a.json"
DEFAULT_FEWSHOT_TRAINING_CASE_COUNT = 4
MIN_FEWSHOT_RETRIEVAL_SCORE = 0.45
HIGH_SIMILARITY_FEWSHOT_SCORE = 0.75
GENERIC_FEWSHOT_LABELS = {
    "assets",
    "current assets",
    "current liabilities",
    "equity",
    "liabilities",
    "other",
    "total assets",
    "total current assets",
    "total current liabilities",
    "total liabilities",
    "total operating expenses",
}

LLM_FEWSHOT_SYNONYM_GROUPS = (
    {"capital", "share capital", "contributed share capital", "issued capital"},
    {"bank overdraft", "overdraft", "unsecured bank overdraft"},
    {"receivable", "receivables", "other receivable", "trade receivables"},
    {"payable", "payables", "other payable", "trade payables", "director account"},
    {"accrual", "accruals"},
    {"cash", "cash equivalents", "cash and cash equivalents", "bank balances"},
    {"loss", "net loss", "profit loss", "profit"},
    {"tax", "tax expense", "taxation"},
    {"administrative expenses", "administration expenses", "operating expenses"},
)


class LLMMappingRateLimitError(RuntimeError):
    """Raised when the provider reports a temporary rate limit."""

    safe_message = "AI provider is temporarily rate limited. Please wait and try again later."

    def __init__(
        self,
        message: str | None = None,
        *,
        retry_after_seconds: float | None = None,
        attempt_count: int | None = None,
        provider_error_type: str = "provider_rate_limited",
        rows_sent_to_llm: int = 0,
        processed_rows: int = 0,
        saved_suggestions: int = 0,
        rate_limited_rows: int = 1,
        pending_rows: int = 0,
        failed_row_id: str | None = None,
    ) -> None:
        super().__init__(message or self.safe_message)
        self.retry_after_seconds = retry_after_seconds
        self.attempt_count = attempt_count
        self.provider_error_type = provider_error_type
        self.rows_sent_to_llm = rows_sent_to_llm
        self.processed_rows = processed_rows
        self.saved_suggestions = saved_suggestions
        self.rate_limited_rows = rate_limited_rows
        self.pending_rows = pending_rows
        self.failed_row_id = failed_row_id

    def with_run_progress(
        self,
        *,
        rows_sent_to_llm: int,
        processed_rows: int,
        saved_suggestions: int,
        pending_rows: int,
        failed_row_id: str | None,
    ) -> "LLMMappingRateLimitError":
        self.rows_sent_to_llm = rows_sent_to_llm
        self.processed_rows = processed_rows
        self.saved_suggestions = saved_suggestions
        self.pending_rows = pending_rows
        self.failed_row_id = failed_row_id
        return self

    def to_summary(self) -> dict[str, Any]:
        return {
            "provider_error_type": self.provider_error_type,
            "retry_after_seconds": self.retry_after_seconds,
            "attempt_count": self.attempt_count,
            "rows_sent_to_llm": self.rows_sent_to_llm,
            "processed_rows_before_rate_limit": self.processed_rows,
            "saved_suggestions_before_rate_limit": self.saved_suggestions,
            "rate_limited_rows": self.rate_limited_rows,
            "pending_rows": self.pending_rows,
            "failed_row_id": self.failed_row_id,
            "db_mutated_extracted_data_items": False,
        }


def is_rate_limit_error(exc: BaseException) -> bool:
    if isinstance(exc, LLMMappingRateLimitError):
        return True

    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True

    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if response_status == 429:
        return True

    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "rate_limited" in text


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or getattr(exc, "headers", None) or {}
    if not isinstance(headers, Mapping):
        return None

    retry_after = None
    for key, value in headers.items():
        if str(key).lower() == "retry-after":
            retry_after = value
            break
    if retry_after in {None, ""}:
        return None

    try:
        return max(0.0, float(str(retry_after).strip()))
    except (TypeError, ValueError):
        pass

    try:
        retry_at = parsedate_to_datetime(str(retry_after))
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _bounded_rate_limit_delay(
    *,
    retry_after_seconds: float | None,
    attempt_index: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
) -> float:
    delay = retry_after_seconds
    if delay is None:
        delay = max(0.0, base_delay_seconds) * (2 ** max(0, attempt_index - 1))
    return min(max(0.0, delay), max(0.0, max_delay_seconds))
LLM_CONCEPT_ALIASES = {
    "ifrs-smes:IssuedCapital": {
        "contributed share capital",
        "contributed capital",
        "share capital",
        "issued capital",
    },
    "ifrs-smes:Equity": {
        "capital deficiency",
        "deficiency in equity",
        "net capital deficiency",
        "equity deficit",
    },
    "ifrs-smes:EquityAttributableToOwnersOfParent": {
        "capital deficiency and liabilities",
        "capital deficiency",
        "equity attributable to owners",
    },
    "ifrs-smes:TradeAndOtherCurrentReceivables": {
        "other receivable",
        "other receivables",
        "receivable",
        "receivables",
        "decrease in receivable",
        "increase in receivable",
    },
    "ssmt-mpers:OtherCurrentReceivables": {
        "other receivable",
        "other receivables",
    },
    "ifrs-smes:TradeAndOtherCurrentPayables": {
        "other payable",
        "other payables",
        "payable",
        "payables",
        "decrease in payable",
        "increase in payable",
        "director account",
        "director's account",
        "increase in director account",
        "increase in director's account",
        "amount due to director",
    },
    "ssmt-mpers:OtherCurrentPayables": {
        "other payable",
        "other payables",
    },
    "ssmt-mpers:CurrentNontradeAccruals": {
        "accrual",
        "accruals",
    },
    "ssmt-mpers:OtherNontradeAccruals": {
        "accrual",
        "accruals",
    },
    "ssmt-mpers:UnsecuredBankOverdrafts": {
        "bank overdraft",
        "bank overdraft unsecured",
        "unsecured bank overdraft",
        "bank overdraft unsecured current liability",
    },
    "ssmt-mpers:CurrentPortionOfNoncurrentUnsecuredBankOverdrafts": {
        "bank overdraft",
        "bank overdraft unsecured",
        "unsecured bank overdraft",
    },
    "ifrs-smes:BankOverdraftsClassifiedAsCashEquivalents": {
        "bank overdraft",
        "bank overdrafts",
        "bank overdraft classified as cash equivalents",
    },
    "ifrs-smes:CashAndCashEquivalents": {
        "cash and cash equivalents",
        "cash and cash equivalents at beginning of year",
        "cash and cash equivalents at end of year",
        "cash and cash equivalents at beginning of period",
        "cash and cash equivalents at end of period",
    },
    "ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents": {
        "net increase in cash and cash equivalents",
        "net decrease in cash and cash equivalents",
        "net increase decrease in cash and cash equivalents",
    },
    "ifrs-smes:AdjustmentsForIncreaseDecreaseInTradeAccountPayable": {
        "decrease in payable",
        "increase in payable",
        "decrease in payables",
        "increase in payables",
        "increase in director account",
        "increase in director's account",
    },
    "ifrs-smes:AdjustmentsForDecreaseIncreaseInTradeAccountReceivable": {
        "decrease in receivable",
        "increase in receivable",
        "decrease in receivables",
        "increase in receivables",
    },
    "ifrs-smes:ProfitLoss": {
        "net loss for the year",
        "loss for the year",
        "net profit for the year",
        "profit for the year",
        "loss after tax",
        "profit after tax",
        "loss after tax and total comprehensive loss",
        "loss after tax and representing total comprehensive loss for the year",
    },
    "ifrs-smes:ComprehensiveIncome": {
        "total comprehensive loss",
        "total comprehensive income",
        "loss after tax and total comprehensive loss",
        "loss after tax and representing total comprehensive loss for the year",
    },
    "ifrs-smes:OtherComprehensiveIncome": {
        "other comprehensive loss",
        "other comprehensive income",
    },
}


@dataclass(frozen=True)
class LLMMappingConfig:
    model_id: str
    max_candidates: int
    timeout_seconds: float
    high_confidence_threshold: float
    min_display_confidence: float
    min_manual_confidence: float
    max_rows_per_job: int
    auto_apply_high_confidence: bool = False
    fewshot_enabled: bool = True
    fewshot_max_examples: int = 3
    fewshot_case_split_mode: str = "training_only"
    fewshot_guardrails_enabled: bool = True
    fewshot_fallback_to_base_prompt: bool = True
    provider_rate_limit_max_retries: int = 2
    provider_rate_limit_base_delay_seconds: float = 4.0
    provider_rate_limit_max_delay_seconds: float = 30.0
    provider_request_delay_seconds: float = 0.5


def _float_setting(settings_obj: Any, name: str, default: float) -> float:
    value = getattr(settings_obj, name, default)
    if value is None or value == "":
        value = default
    return float(value)


def load_llm_mapping_config(settings_obj: Any = settings) -> LLMMappingConfig:
    return LLMMappingConfig(
        model_id=str(getattr(settings_obj, "llm_mapping_model_id", "") or "").strip()
        or "Qwen/Qwen3-235B-A22B-Instruct-2507",
        max_candidates=max(1, int(getattr(settings_obj, "llm_mapping_max_candidates", 8) or 8)),
        timeout_seconds=max(1.0, float(getattr(settings_obj, "llm_mapping_timeout_seconds", 60) or 60)),
        high_confidence_threshold=min(
            1.0,
            max(0.0, _float_setting(settings_obj, "llm_mapping_high_confidence_threshold", 0.88)),
        ),
        min_display_confidence=min(
            1.0,
            max(0.0, _float_setting(settings_obj, "llm_mapping_min_display_confidence", 0.50)),
        ),
        min_manual_confidence=min(
            1.0,
            max(0.0, _float_setting(settings_obj, "llm_mapping_min_manual_confidence", 0.0)),
        ),
        max_rows_per_job=max(1, int(getattr(settings_obj, "llm_mapping_max_rows_per_job", 50) or 50)),
        auto_apply_high_confidence=bool(
            getattr(settings_obj, "llm_mapping_auto_apply_high_confidence", False)
        ),
        fewshot_enabled=bool(getattr(settings_obj, "llm_mapping_fewshot_enabled", True)),
        fewshot_max_examples=max(0, int(getattr(settings_obj, "llm_mapping_fewshot_max_examples", 3) or 3)),
        fewshot_case_split_mode=str(
            getattr(settings_obj, "llm_mapping_fewshot_case_split_mode", "training_only")
            or "training_only"
        ).strip().lower(),
        fewshot_guardrails_enabled=bool(getattr(settings_obj, "llm_mapping_fewshot_guardrails_enabled", True)),
        fewshot_fallback_to_base_prompt=bool(getattr(settings_obj, "llm_mapping_fewshot_fallback_to_base_prompt", True)),
        provider_rate_limit_max_retries=min(
            2,
            max(0, int(getattr(settings_obj, "llm_mapping_provider_rate_limit_max_retries", 2) or 2)),
        ),
        provider_rate_limit_base_delay_seconds=max(
            0.0,
            _float_setting(settings_obj, "llm_mapping_provider_rate_limit_base_delay_seconds", 4.0),
        ),
        provider_rate_limit_max_delay_seconds=max(
            1.0,
            _float_setting(settings_obj, "llm_mapping_provider_rate_limit_max_delay_seconds", 30.0),
        ),
        provider_request_delay_seconds=max(
            0.0,
            _float_setting(settings_obj, "llm_mapping_provider_request_delay_seconds", 0.5),
        ),
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _decode_warnings(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return [str(value)]
    if isinstance(decoded, list):
        return [str(item) for item in decoded]
    return [str(decoded)]


def _row_type_for_item(item: ExtractedDataItem) -> str:
    if _clean_text(getattr(item, "extracted_value", "")):
        return "numeric_fact"
    return "text_block"


def _candidate_from_item(item: ExtractedDataItem, page: FinancialStatementPage) -> dict[str, Any]:
    return {
        "row_type": _row_type_for_item(item),
        "label": getattr(item, "extracted_label", None),
        "value": getattr(item, "extracted_value", None),
        "previous_value": getattr(item, "value_previous_year", None),
        "statement_section": getattr(item, "statement_type", None),
        "page_number": getattr(page, "page_number", None),
        "warnings": _decode_warnings(getattr(item, "validation_warnings", None)),
    }


def _hard_precheck_rejection_reason(
    candidate: Mapping[str, Any],
    diagnosis: Mapping[str, Any],
) -> str | None:
    reason = str(diagnosis.get("mapping_rejection_reason") or "")
    if reason in DISQUALIFYING_REJECTION_REASONS:
        return reason
    label = normalize_text(
        _strip_note_references_for_llm(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
    )
    if label in LLM_HARD_AMBIGUOUS_LABELS:
        return "rejected_ambiguous"
    return None


def _sorted_item_rows(job: FilingJob) -> list[tuple[FinancialStatementPage, ExtractedDataItem]]:
    rows: list[tuple[FinancialStatementPage, ExtractedDataItem]] = []
    for page in sorted(list(getattr(job, "pages", []) or []), key=lambda page: getattr(page, "page_number", 0) or 0):
        for item in sorted(list(getattr(page, "extracted_items", []) or []), key=lambda row: str(getattr(row, "id", ""))):
            rows.append((page, item))
    return rows


def _nearby_rows(
    rows: Sequence[tuple[FinancialStatementPage, ExtractedDataItem]],
    index: int,
) -> list[dict[str, Any]]:
    nearby: list[dict[str, Any]] = []
    for offset in (-2, -1, 1, 2):
        neighbor_index = index + offset
        if neighbor_index < 0 or neighbor_index >= len(rows):
            continue
        page, item = rows[neighbor_index]
        nearby.append(
            {
                "relative_position": offset,
                "page_number": getattr(page, "page_number", None),
                "label": _clean_text(getattr(item, "extracted_label", None), 220),
                "value": _clean_text(getattr(item, "extracted_value", None), 120),
                "statement_type": _clean_text(getattr(item, "statement_type", None), 160),
            }
        )
    return nearby


def _row_context(
    *,
    item: ExtractedDataItem,
    page: FinancialStatementPage,
    nearby: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "extracted_data_item_id": getattr(item, "id", None),
        "extracted_label": _clean_text(getattr(item, "extracted_label", None), 500),
        "extracted_value": _clean_text(getattr(item, "extracted_value", None), 500),
        "value_previous_year": _clean_text(getattr(item, "value_previous_year", None), 500),
        "financial_year": getattr(item, "financial_year", None),
        "financial_year_previous": getattr(item, "financial_year_previous", None),
        "statement_type": _clean_text(getattr(item, "statement_type", None), 220),
        "page_number": getattr(page, "page_number", None),
        "nearby_rows": nearby,
    }


def _strip_note_references_for_llm(value: Any) -> str:
    text = _clean_text(value, 1000)
    text = re.sub(r"^\s*(?:note\s*)?\d+[a-z]?\s*[-).:]?\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+\(?\s*(?:note\s*)?\d+[a-z]?\s*\)?\s*$", "", text, flags=re.IGNORECASE)
    return _clean_text(text, 1000)


def _unique_preserve_order(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _llm_statement_template_preferences(candidate: Mapping[str, Any], label: str) -> list[str]:
    section = normalize_text(candidate.get("statement_section"))
    label_norm = normalize_text(label)
    preferred: list[str] = []

    if re.search(
        r"\b(cash\s+flows?|net\s+increase|net\s+decrease|cash\s+and\s+cash\s+equivalents\s+at\s+"
        r"(?:beginning|end)|decrease\s+in\s+(?:payable|receivable)|increase\s+in\s+"
        r"(?:payable|receivable|director))\b",
        f"{section} {label_norm}",
        flags=re.IGNORECASE,
    ):
        preferred.extend(["520000", "510000"])
    if re.search(r"\b(comprehensive\s+(?:income|loss)|other\s+comprehensive)\b", label_norm):
        preferred.extend(["410000", "420000", "310000", "320000"])
    if re.search(r"\b(net\s+loss|net\s+profit|loss\s+after\s+tax|profit\s+after\s+tax|loss\s+before\s+tax)\b", label_norm):
        preferred.extend(["310000", "320000", "410000", "420000"])
    if re.search(
        r"\b(share\s+capital|contributed\s+capital|issued\s+capital|capital\s+deficiency|"
        r"bank\s+overdraft|receivables?|payables?|accruals?|director'?s?\s+account)\b",
        label_norm,
    ):
        preferred.extend(["210000", "210100", "220000", "220100"])

    if "financial position" in section or "balance sheet" in section:
        preferred.extend(["210000", "210100", "220000", "220100"])
    if "profit or loss" in section or "income statement" in section:
        preferred.extend(["310000", "320000"])
    if "comprehensive income" in section:
        preferred.extend(["410000", "420000"])
    if "cash flow" in section:
        preferred.extend(["520000", "510000"])
    if "changes in equity" in section or "retained earnings" in section:
        preferred.extend(["610000", "620000", "210000", "210100", "220000", "220100"])

    preferred.extend(LLM_BROAD_TEMPLATE_CODES)
    return _unique_preserve_order(preferred)


def _llm_candidate_template_code(
    concept: Mapping[str, Any],
    candidate: Mapping[str, Any],
    label: str,
) -> str | None:
    concept_templates = [str(code) for code in concept.get("templates") or []]
    if not concept_templates:
        return None
    for template_code in _llm_statement_template_preferences(candidate, label):
        if template_code in concept_templates:
            return template_code
    return None


def _llm_concept_eligible(row_type: str, concept_id: str, concept_label: str) -> bool:
    if row_type not in {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}:
        return False
    local = _split_template_local_name(concept_id)
    haystack = normalize_text(f"{concept_id} {concept_label}")
    if (
        "abstract" in haystack
        or "text block" in haystack
        or "explanatory" in haystack
        or local.endswith("axis")
        or local.endswith("member")
        or local.endswith("domain")
        or local.endswith("lineitems")
        or local.endswith("table")
    ):
        return False
    return not local.startswith(
        (
            "date",
            "description",
            "disclosure whether",
            "identification",
            "method",
            "name",
            "number",
            "type",
        )
    )


def _strip_total_or_net_prefix(value: Any) -> str:
    return re.sub(r"^(?:total|net)\s+", "", normalize_text(value)).strip()


def _llm_aliases_for_concept(concept_id: str, concept: Mapping[str, Any]) -> set[str]:
    concept_label = _clean_text(concept.get("label"), 500)
    aliases = {
        normalize_text(concept_label),
        _strip_total_or_net_prefix(concept_label),
        _split_template_local_name(concept_id),
        _strip_total_or_net_prefix(_split_template_local_name(concept_id)),
    }
    aliases.update(normalize_text(alias) for alias in concept.get("aliases") or [])
    aliases.update(normalize_text(alias) for alias in LLM_CONCEPT_ALIASES.get(concept_id, set()))
    return {alias for alias in aliases if alias}


def _llm_token_set(value: Any) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if token and token not in LLM_TOKEN_STOPWORDS
    }


def _llm_overlap(left: Any, right: Any) -> float:
    left_tokens = _llm_token_set(left)
    right_tokens = _llm_token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _llm_concept_family(value: Any) -> str:
    text = normalize_text(value)
    if "cash" in text:
        return "cash"
    if "receivable" in text:
        return "receivables"
    if "payable" in text or "director" in text:
        return "payables"
    if "capital" in text or "equity" in text:
        return "equity"
    if "tax" in text:
        return "tax"
    if "expense" in text or "administr" in text:
        return "expenses"
    if "loss" in text or "profit" in text:
        return "profit_loss"
    if "asset" in text:
        return "assets"
    if "liabil" in text:
        return "liabilities"
    return "other"


def _fewshot_tokens(value: Any) -> set[str]:
    return {
        token
        for token in normalize_text(strip_note_references(value)).split()
        if token and token not in LLM_TOKEN_STOPWORDS
    }


def _fewshot_token_overlap(left: Any, right: Any) -> float:
    left_tokens = _fewshot_tokens(left)
    right_tokens = _fewshot_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _fewshot_synonym_overlap(left: Any, right: Any) -> float:
    left_text = normalize_text(left)
    right_text = normalize_text(right)
    matches = 0
    for group in LLM_FEWSHOT_SYNONYM_GROUPS:
        if any(term in left_text for term in group) and any(term in right_text for term in group):
            matches += 1
    return min(1.0, matches / 2) if matches else 0.0


def _is_generic_fewshot_label(value: Any) -> bool:
    label = re.sub(r"^(?:total|net)\s+", "", normalize_text(strip_note_references(value))).strip()
    return label in GENERIC_FEWSHOT_LABELS or label.startswith("total ")


def _fewshot_rationale(row: Mapping[str, Any]) -> str:
    evidence = row.get("evidence") or row.get("gold_alignment_evidence") or {}
    parts = []
    if evidence.get("value_match"):
        parts.append("value matched local reference fact")
    if evidence.get("period_match"):
        parts.append("period evidence aligned")
    if evidence.get("unit_evidence"):
        parts.append("unit/context evidence aligned")
    if evidence.get("label_similarity") is not None:
        parts.append(f"label similarity {evidence.get('label_similarity')}")
    return "; ".join(parts[:3]) or "strong local gold alignment"


def _fewshot_training_cases(case_ids: Sequence[str]) -> set[str]:
    canonical = {f"case_{index:03d}" for index in range(1, DEFAULT_FEWSHOT_TRAINING_CASE_COUNT + 1)}
    present = {str(case_id) for case_id in case_ids if case_id}
    if present & canonical:
        return canonical
    ordered = sorted({str(case_id) for case_id in case_ids if case_id})
    return set(ordered[:DEFAULT_FEWSHOT_TRAINING_CASE_COUNT])


def load_production_fewshot_example_store(
    alignment_report_path: str | Path = DEFAULT_FEWSHOT_ALIGNMENT_REPORT,
    *,
    case_split_mode: str = "training_only",
) -> list[dict[str, Any]]:
    """Load compact #17A strong-gold examples for production prompts.

    This intentionally excludes auditor XML, parsed facts, candidate fact details,
    ambiguous alignments, unaligned rows, target labels, values, and evaluation
    labels from the payload sent to the external model.
    """

    report = json.loads(Path(alignment_report_path).read_text(encoding="utf-8"))
    alignments = list(report.get("alignments") or [])
    training_cases = _fewshot_training_cases([row.get("source_case_id") for row in alignments])
    use_training_only = str(case_split_mode or "training_only").strip().lower() == "training_only"
    examples = []
    for row in alignments:
        if row.get("alignment_status") != "strong":
            continue
        if use_training_only and row.get("source_case_id") not in training_cases:
            continue
        concept = row.get("correct_template_field_id") or row.get("correct_concept_qname")
        if not concept:
            continue
        examples.append(
            {
                "source_case_id": row.get("source_case_id"),
                "example_id": row.get("extracted_row_id"),
                "extracted_label": _clean_text(row.get("extracted_label"), 240),
                "statement_type": _clean_text(row.get("statement_type"), 160),
                "correct_concept_qname": _clean_text(row.get("correct_concept_qname"), 220),
                "correct_template_field_id": _clean_text(concept, 220),
                "concept_family": _llm_concept_family(f"{concept} {row.get('extracted_label')}"),
                "rationale": _clean_text(_fewshot_rationale(row), 260),
            }
        )
    return examples


def retrieve_production_fewshot_examples(
    *,
    row_context: Mapping[str, Any],
    example_store: Sequence[Mapping[str, Any]],
    limit: int = 3,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    target_label = row_context.get("extracted_label")
    target_statement = normalize_text(row_context.get("statement_type"))
    target_family = _llm_concept_family(f"{target_label} {row_context.get('statement_type')}")
    scored = []
    for example in example_store:
        label = example.get("extracted_label")
        statement = normalize_text(example.get("statement_type"))
        label_score = max(
            _fewshot_token_overlap(target_label, label),
            SequenceMatcher(None, normalize_text(target_label), normalize_text(label)).ratio(),
        )
        synonym_score = _fewshot_synonym_overlap(target_label, label)
        statement_score = 1.0 if target_statement and statement and target_statement == statement else _fewshot_token_overlap(target_statement, statement)
        family_score = 1.0 if target_family == example.get("concept_family") else 0.0
        score = (0.48 * label_score) + (0.22 * synonym_score) + (0.18 * statement_score) + (0.12 * family_score)
        if score < MIN_FEWSHOT_RETRIEVAL_SCORE:
            continue
        if _is_generic_fewshot_label(label) and label_score < 0.72:
            continue
        if family_score == 0.0 and statement_score < 0.35 and label_score < 0.65:
            continue
        scored.append(
            {
                "source_case_id": example.get("source_case_id"),
                "example_id": example.get("example_id"),
                "extracted_label": example.get("extracted_label"),
                "statement_type": example.get("statement_type"),
                "correct_concept_qname": example.get("correct_concept_qname"),
                "correct_template_field_id": example.get("correct_template_field_id"),
                "rationale": example.get("rationale"),
                "retrieval_score": round(score, 4),
            }
        )
    scored.sort(key=lambda row: (-float(row["retrieval_score"]), str(row["correct_template_field_id"]), str(row["extracted_label"])))
    return scored[:limit]


def _fewshot_broad_substitution_warnings(
    target_label_norm: str,
    candidate_concepts: Sequence[Mapping[str, Any]],
    *,
    family: str,
) -> list[str]:
    warnings = []
    lacks_trade = "trade" not in target_label_norm
    lacks_current = "current" not in target_label_norm
    lacks_noncurrent = "noncurrent" not in target_label_norm and "non current" not in target_label_norm
    lacks_nontrade = "nontrade" not in target_label_norm and "non trade" not in target_label_norm
    for candidate in candidate_concepts:
        candidate_id = str(candidate.get("template_field_id") or "")
        candidate_text = normalize_text(f"{candidate_id} {candidate.get('label')}")
        if family == "receivables" and "receivable" not in candidate_text:
            continue
        if family == "payables" and "payable" not in candidate_text:
            continue
        reasons = []
        if lacks_trade and "trade" in candidate_text:
            reasons.append("target label lacks trade evidence")
        if lacks_current and "current" in candidate_text:
            reasons.append("target label lacks current/noncurrent classification wording")
        if lacks_noncurrent and "noncurrent" in candidate_text:
            reasons.append("target label lacks noncurrent classification wording")
        if lacks_nontrade and "nontrade" in candidate_text:
            reasons.append("target label lacks nontrade wording")
        if "total" in candidate_text and "total" not in target_label_norm:
            reasons.append("candidate is a broader total/summary concept")
        if reasons:
            warnings.append(f"{candidate_id}: broad-substitution risk ({'; '.join(reasons)}).")
    return warnings[:5]


def build_production_fewshot_guardrail_context(
    *,
    row_context: Mapping[str, Any],
    candidate_concepts: Sequence[Mapping[str, Any]],
    fewshot_examples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    target_label = row_context.get("extracted_label")
    target_label_norm = normalize_text(strip_note_references(target_label))
    candidate_ids = {str(row.get("template_field_id") or "") for row in candidate_concepts}
    warnings = []
    absent_similar_example_concepts = []
    for example in fewshot_examples:
        concept = str(example.get("correct_template_field_id") or "")
        if not concept or concept in candidate_ids:
            continue
        if float(example.get("retrieval_score") or 0.0) >= HIGH_SIMILARITY_FEWSHOT_SCORE:
            absent_similar_example_concepts.append(
                {
                    "example_label": example.get("extracted_label"),
                    "example_concept": concept,
                    "retrieval_score": example.get("retrieval_score"),
                }
            )
    if absent_similar_example_concepts:
        warnings.append(
            "A close training example maps to a concept that is absent from candidate_concepts; do not select a broader substitute only by analogy."
        )
    if "other receivable" in target_label_norm or "other receivables" in target_label_norm:
        warnings.extend(_fewshot_broad_substitution_warnings(target_label_norm, candidate_concepts, family="receivables"))
    if "other payable" in target_label_norm or "other payables" in target_label_norm:
        warnings.extend(_fewshot_broad_substitution_warnings(target_label_norm, candidate_concepts, family="payables"))
    return {
        "target_label_family": _llm_concept_family(f"{target_label} {row_context.get('statement_type')}"),
        "selection_guardrails": [
            "Return null if candidate concepts are close but not an exact semantic fit for the target label.",
            "Do not overgeneralize from few-shot examples; they are guidance, not answer keys for the target row.",
            "Prefer null when statement type and concept family do not align.",
            "High confidence requires strong label meaning and statement-context evidence, not value pattern alone.",
            "Avoid broad summary concepts when the row label is a more specific receivable/payable/accrual/nontrade item.",
        ],
        "candidate_warnings": warnings,
        "absent_similar_example_concepts": absent_similar_example_concepts,
    }


def _llm_score_broad_concept(
    *,
    label: str,
    row_type: str,
    template_code: str,
    concept_id: str,
    concept: Mapping[str, Any],
) -> dict[str, Any] | None:
    concept_label = _clean_text(concept.get("label"), 500)
    if not _llm_concept_eligible(row_type, concept_id, concept_label):
        return None

    label_norm = normalize_text(_strip_note_references_for_llm(label))
    label_base = _strip_total_or_net_prefix(label_norm)
    aliases = _llm_aliases_for_concept(concept_id, concept)
    exact_alias = bool(label_norm in aliases or label_base in aliases)
    phrase_containment = any(
        alias
        and label_norm
        and len(alias) >= 8
        and (label_norm in alias or alias in label_norm)
        for alias in aliases
    )
    overlap = max((_llm_overlap(label_norm, alias) for alias in aliases), default=0.0)
    similarity = max((SequenceMatcher(None, label_norm, alias).ratio() for alias in aliases), default=0.0)

    if exact_alias:
        score = 0.94
        method = "exact_alias_match"
    elif phrase_containment and overlap >= 0.45:
        score = 0.78 + (0.12 * overlap)
        method = "phrase_containment_match"
    else:
        score = (0.42 * similarity) + (0.46 * overlap)
        method = "token_overlap_match"

    preferred_codes = _llm_statement_template_preferences({"statement_section": ""}, label_norm)
    if template_code in preferred_codes[:4]:
        score += 0.03
    if concept.get("required"):
        score += 0.01

    score = round(max(0.0, min(1.0, score)), 4)
    if score < 0.34:
        return None
    return {
        "template_field_id": concept_id,
        "label": concept_label,
        "template_code": template_code,
        "score": score,
        "method": method,
        "required": bool(concept.get("required", False)),
        "position": concept.get("position"),
        "namespace": concept.get("namespace"),
    }


def _broad_candidate_rows_for_llm(
    candidate: Mapping[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    row_type = str(candidate.get("row_type") or "")
    label = _strip_note_references_for_llm(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
    if not label:
        return []

    service = get_xbrl_template_service()
    rows: list[dict[str, Any]] = []
    for concept_id, concept in service.all_concepts.items():
        template_code = _llm_candidate_template_code(concept, candidate, label)
        if not template_code:
            continue
        score = _llm_score_broad_concept(
            label=label,
            row_type=row_type,
            template_code=template_code,
            concept_id=str(concept_id),
            concept=concept,
        )
        if score is None:
            continue
        score["statement_type"] = _clean_text(service.get_template_description(template_code), 220)
        rows.append(score)

    rows.sort(key=lambda row: (-float(row["score"]), str(row["template_field_id"]), str(row["template_code"])))
    return rows[:limit]


def _merge_candidate_rows(
    primary: Sequence[Mapping[str, Any]],
    additional: Sequence[Mapping[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    best_by_id: dict[str, dict[str, Any]] = {}
    for row in list(primary) + list(additional):
        template_field_id = str(row.get("template_field_id") or "").strip()
        if not template_field_id:
            continue
        normalized = dict(row)
        current = best_by_id.get(template_field_id)
        if current is None or float(normalized.get("score") or 0.0) > float(current.get("score") or 0.0):
            best_by_id[template_field_id] = normalized
    rows = list(best_by_id.values())
    rows.sort(key=lambda row: (-float(row.get("score") or 0.0), str(row.get("template_field_id") or "")))
    return rows[:limit]


def _candidate_rows_for_llm(
    candidate: Mapping[str, Any],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    rows = _merge_candidate_rows(
        azure_di_candidate_template_matches(candidate, limit=limit),
        _broad_candidate_rows_for_llm(candidate, limit=limit),
        limit=limit,
    )
    safe_rows = []
    for row in rows:
        template_field_id = str(row.get("template_field_id") or "").strip()
        if not template_field_id:
            continue
        safe_rows.append(
            {
                "template_field_id": template_field_id,
                "label": _clean_text(row.get("label"), 500),
                "statement_type": _clean_text(row.get("statement_type"), 220),
                "template_code": _clean_text(row.get("template_code"), 20),
                "deterministic_score": row.get("score"),
                "deterministic_method": row.get("method"),
                "required": bool(row.get("required", False)),
                "position": row.get("position"),
                "namespace": row.get("namespace"),
            }
        )
    return safe_rows


def _safe_prompt_row_context(row_context: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "extracted_data_item_id",
        "extracted_label",
        "extracted_value",
        "value_previous_year",
        "financial_year",
        "financial_year_previous",
        "statement_type",
        "page_number",
        "nearby_rows",
    )
    return {key: row_context.get(key) for key in allowed if key in row_context}


def _safe_prompt_fewshot_examples(examples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    allowed = (
        "source_case_id",
        "example_id",
        "extracted_label",
        "statement_type",
        "correct_concept_qname",
        "correct_template_field_id",
        "rationale",
        "retrieval_score",
    )
    return [
        {key: example.get(key) for key in allowed if key in example}
        for example in examples
    ]


def build_mapping_prompt(
    row_context: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    fewshot_examples: Sequence[Mapping[str, Any]] | None = None,
    guardrails_enabled: bool = True,
) -> str:
    examples = _safe_prompt_fewshot_examples(list(fewshot_examples or []))
    safe_row = _safe_prompt_row_context(row_context)
    payload = {
        "row": safe_row,
        "candidate_concepts": list(candidates),
        "required_output_schema": {
            "selected_template_field_id": "string or null",
            "confidence": 0.0,
            "reason": "string",
            "ranked_candidates": [
                {
                    "template_field_id": "string",
                    "confidence": 0.0,
                    "reason": "string",
                }
            ],
            "requires_human_confirmation": True,
            "rejection_reason": "string or null",
        },
    }
    if examples:
        payload["few_shot_examples"] = examples
    if guardrails_enabled:
        payload["guardrail_context"] = build_production_fewshot_guardrail_context(
            row_context=safe_row,
            candidate_concepts=candidates,
            fewshot_examples=examples,
        )
    return (
        "You are mapping one extracted financial statement row to one of the "
        "provided XBRL/MPERS template concepts.\n\n"
        "Rules:\n"
        "- Choose only from candidate_concepts.template_field_id.\n"
        "- Use few_shot_examples only as mapping-pattern guidance from other training cases.\n"
        "- Never copy a few-shot answer unless the target row and provided candidate evidence support it.\n"
        "- Do not select a broader summary concept when a close specific concept appears to be absent from candidate_concepts.\n"
        "- A candidate that matches only value pattern, generic family, or broad receivable/payable wording is not enough.\n"
        "- Reduce confidence or return null when label meaning and concept specificity do not align.\n"
        "- If none is safe, return selected_template_field_id as null.\n"
        "- Do not invent qnames, template fields, values, facts, periods, units, or statement sections.\n"
        "- Do not map person/company names or note numbers as financial facts.\n"
        "- Do not force ambiguous rows; prefer null if uncertain.\n"
        "- Preserve statement context and explain uncertainty.\n"
        "- Return strict JSON only, with no markdown fences or commentary.\n\n"
        "Input:\n"
        f"{json.dumps(payload, ensure_ascii=True, sort_keys=True)}"
    )


def _extract_embedded_json(text: str) -> str | None:
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


def _mapping_has_llm_schema(value: Mapping[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "selected_template_field_id",
            "confidence",
            "ranked_candidates",
            "requires_human_confirmation",
            "rejection_reason",
        )
    )


def _first_choice_value(choice: Any, key: str) -> Any:
    if isinstance(choice, Mapping):
        return choice.get(key)
    return getattr(choice, key, None)


def _choice_message_content(choice: Any) -> Any:
    message = _first_choice_value(choice, "message")
    if isinstance(message, Mapping):
        return message.get("content")
    return getattr(message, "content", None)


def _response_choices(raw_response: Any) -> Sequence[Any]:
    if isinstance(raw_response, Mapping):
        choices = raw_response.get("choices")
    else:
        choices = getattr(raw_response, "choices", None)
    if isinstance(choices, (list, tuple)):
        return choices
    return []


def _parse_json_text(raw_text: str, *, default_shape: str) -> tuple[dict[str, Any] | None, str | None, str]:
    if not raw_text:
        return None, "parser_no_content", "invalid_json"

    fence = re.search(r"```(?:json)?\s*(.*?)```", raw_text, re.IGNORECASE | re.DOTALL)
    candidates = [fence.group(1).strip()] if fence else []
    candidates.append(raw_text)
    embedded = _extract_embedded_json(raw_text)
    if embedded and embedded not in candidates:
        candidates.append(embedded)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed, None, "markdown_json" if fence else default_shape
    return None, "invalid_json", "invalid_json"


def parse_llm_json_response(raw_response: Any) -> tuple[dict[str, Any] | None, str | None, str, str, str]:
    raw_text = json.dumps(raw_response, ensure_ascii=True, default=str) if isinstance(raw_response, Mapping) else ""
    if isinstance(raw_response, Mapping):
        if _mapping_has_llm_schema(raw_response):
            return dict(raw_response), None, raw_text, raw_text, "direct_json"

        choices = _response_choices(raw_response)
        if choices:
            first_choice = choices[0]
            content = _choice_message_content(first_choice)
            if content is not None:
                content_text = str(content).strip()
                parsed, parse_error, shape = _parse_json_text(
                    content_text,
                    default_shape="chat_completion_message_content",
                )
                return parsed, parse_error, raw_text, content_text, shape

            choice_text = _first_choice_value(first_choice, "text")
            if choice_text is not None:
                content_text = str(choice_text).strip()
                parsed, parse_error, shape = _parse_json_text(
                    content_text,
                    default_shape="chat_completion_text",
                )
                return parsed, parse_error, raw_text, content_text, shape

            return None, "parser_no_content", raw_text, "", "invalid_json"

        output_text = raw_response.get("output_text")
        if output_text is not None:
            content_text = str(output_text).strip()
            parsed, parse_error, shape = _parse_json_text(content_text, default_shape="direct_json")
            return parsed, parse_error, raw_text, content_text, shape

        parsed, parse_error, shape = _parse_json_text(raw_text, default_shape="direct_json")
        return parsed, parse_error, raw_text, raw_text, shape

    output_text = getattr(raw_response, "output_text", None)
    if output_text is None:
        choices = _response_choices(raw_response)
        if choices:
            output_text = _choice_message_content(choices[0])
            default_shape = "chat_completion_message_content"
            if output_text is None:
                output_text = _first_choice_value(choices[0], "text")
                default_shape = "chat_completion_text"
            if output_text is None:
                raw_text = str(raw_response or "").strip()
                return None, "parser_no_content", raw_text, "", "invalid_json"
        else:
            default_shape = "direct_json"
    else:
        default_shape = "direct_json"

    raw_text = str(output_text if output_text is not None else raw_response or "").strip()
    if not raw_text:
        return None, "parser_no_content", "", "", "invalid_json"

    parsed, parse_error, shape = _parse_json_text(raw_text, default_shape=default_shape)
    return parsed, parse_error, raw_text, raw_text, shape


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, confidence))


def _reason_is_vague(reason: Any) -> bool:
    normalized = normalize_text(reason)
    if len(normalized) < 12:
        return True
    return normalized in {"match", "matches", "best match", "good match", "same meaning"}


def _candidate_by_id(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(candidate.get("template_field_id") or ""): candidate for candidate in candidates}


def _confidence_category(
    confidence: float,
    *,
    high_confidence_threshold: float,
    min_display_confidence: float,
) -> str:
    if confidence >= high_confidence_threshold:
        return "high"
    if confidence >= min_display_confidence:
        return "medium"
    return "low"


def _confidence_warning_level(
    confidence: float,
    *,
    min_display_confidence: float,
) -> str | None:
    if confidence < min_display_confidence:
        return "low_confidence"
    return None


def validate_llm_mapping_output(
    parsed: Mapping[str, Any] | None,
    *,
    candidates: Sequence[Mapping[str, Any]],
    high_confidence_threshold: float,
    min_display_confidence: float,
    min_manual_confidence: float,
    parse_error: str | None = None,
) -> dict[str, Any]:
    valid_candidates = _candidate_by_id(candidates)
    valid_ids = set(valid_candidates)
    base = {
        "selected_template_field_id": None,
        "confidence": 0.0,
        "reason": "",
        "ranked_candidates": [],
        "requires_human_confirmation": True,
        "rejection_reason": None,
        "status": "rejected",
        "invalid_response": False,
        "hallucinated_concept": False,
        "warning_level": None,
        "confidence_category": "low",
    }

    if parse_error or parsed is None:
        return {
            **base,
            "rejection_reason": parse_error or "invalid_llm_response",
            "invalid_response": True,
        }

    selected = parsed.get("selected_template_field_id")
    selected_id = str(selected).strip() if selected is not None else ""
    confidence = _coerce_confidence(parsed.get("confidence"))
    reason = _clean_text(parsed.get("reason"), 1000)

    ranked_rows = parsed.get("ranked_candidates") or []
    if not isinstance(ranked_rows, list):
        return {
            **base,
            "confidence": confidence,
            "reason": reason,
            "rejection_reason": "invalid_ranked_candidates",
            "invalid_response": True,
        }

    ranked_candidates = []
    for row in ranked_rows[: len(candidates)]:
        if not isinstance(row, Mapping):
            return {
                **base,
                "confidence": confidence,
                "reason": reason,
                "rejection_reason": "invalid_ranked_candidates",
                "invalid_response": True,
            }
        row_id = str(row.get("template_field_id") or "").strip()
        if row_id not in valid_ids:
            return {
                **base,
                "confidence": confidence,
                "reason": reason,
                "rejection_reason": "selected_candidate_not_in_candidates",
                "hallucinated_concept": True,
            }
        ranked_candidates.append(
            {
                "template_field_id": row_id,
                "confidence": _coerce_confidence(row.get("confidence")),
                "reason": _clean_text(row.get("reason"), 600),
            }
        )

    if selected_id and selected_id not in valid_ids:
        return {
            **base,
            "selected_template_field_id": selected_id,
            "confidence": confidence,
            "reason": reason,
            "ranked_candidates": ranked_candidates,
            "rejection_reason": "selected_candidate_not_in_candidates",
            "hallucinated_concept": True,
        }

    if not selected_id:
        model_rejection = _clean_text(parsed.get("rejection_reason"), 300)
        return {
            **base,
            "confidence": confidence,
            "reason": reason,
            "ranked_candidates": ranked_candidates,
            "rejection_reason": "no_safe_mapping_returned_by_model" if model_rejection else "missing_selected_template_field_id",
            "model_rejection_reason": model_rejection or None,
        }

    if confidence < min_manual_confidence:
        return {
            **base,
            "selected_template_field_id": selected_id,
            "confidence": confidence,
            "reason": reason,
            "ranked_candidates": ranked_candidates,
            "rejection_reason": "below_manual_confidence",
        }

    selected_candidate = valid_candidates[selected_id]
    confidence_category = _confidence_category(
        confidence,
        high_confidence_threshold=high_confidence_threshold,
        min_display_confidence=min_display_confidence,
    )
    return {
        **base,
        "selected_template_field_id": selected_id,
        "selected_candidate": dict(selected_candidate),
        "confidence": confidence,
        "reason": reason,
        "ranked_candidates": ranked_candidates,
        "rejection_reason": None,
        "requires_human_confirmation": True,
        "status": "suggested",
        "warning_level": _confidence_warning_level(
            confidence,
            min_display_confidence=min_display_confidence,
        ),
        "confidence_category": confidence_category,
    }


class HuggingFaceQwenMappingClient:
    """Small live Qwen chat client using the existing provider-neutral token."""

    def __init__(
        self,
        *,
        token: str | None = None,
        client_factory: Any | None = None,
        sleeper: Any | None = None,
    ) -> None:
        self._token_override = token
        self._client_factory = client_factory
        self._sleeper = sleeper or asyncio.sleep

    def _client(self, *, config: LLMMappingConfig, token: str) -> Any:
        if self._client_factory is not None:
            return self._client_factory(config=config, token=token)

        from huggingface_hub import AsyncInferenceClient

        return AsyncInferenceClient(model=config.model_id, token=token)

    async def complete(self, prompt: str, *, config: LLMMappingConfig) -> Any:
        token = (
            self._token_override
            if self._token_override is not None
            else (settings.model_api_token or settings.hugging_face_token or "")
        ).strip()
        if token in PLACEHOLDER_TOKENS:
            raise RuntimeError("MODEL_API_TOKEN is not configured for live LLM mapping.")

        client = self._client(config=config, token=token)
        max_retries = min(2, max(0, int(config.provider_rate_limit_max_retries)))
        attempts_allowed = max_retries + 1
        last_rate_limit: BaseException | None = None

        for attempt_index in range(1, attempts_allowed + 1):
            try:
                return await asyncio.wait_for(
                    client.chat_completion(
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=900,
                        temperature=0.0,
                    ),
                    timeout=config.timeout_seconds,
                )
            except Exception as exc:
                if not is_rate_limit_error(exc):
                    raise
                last_rate_limit = exc
                retry_after = _retry_after_seconds(exc)
                if attempt_index >= attempts_allowed:
                    raise LLMMappingRateLimitError(
                        retry_after_seconds=retry_after,
                        attempt_count=attempt_index,
                    ) from exc

                delay_seconds = _bounded_rate_limit_delay(
                    retry_after_seconds=retry_after,
                    attempt_index=attempt_index,
                    base_delay_seconds=config.provider_rate_limit_base_delay_seconds,
                    max_delay_seconds=config.provider_rate_limit_max_delay_seconds,
                )
                logger.warning(
                    "LLM mapping provider rate limited; retrying model=%s attempt=%s/%s delay_seconds=%.1f",
                    config.model_id,
                    attempt_index,
                    attempts_allowed,
                    delay_seconds,
                )
                await self._sleeper(delay_seconds)

        raise LLMMappingRateLimitError(attempt_count=attempts_allowed) from last_rate_limit


class MockQwenMappingClient:
    """Deterministic local client for report generation and tests."""

    async def complete(self, prompt: str, *, config: LLMMappingConfig) -> dict[str, Any]:
        parsed_input = _extract_prompt_input(prompt)
        row = parsed_input.get("row") or {}
        candidates = parsed_input.get("candidate_concepts") or []
        label = normalize_text(row.get("extracted_label"))
        if not candidates:
            return {
                "selected_template_field_id": None,
                "confidence": 0.0,
                "reason": "No local candidate concepts were provided.",
                "ranked_candidates": [],
                "requires_human_confirmation": True,
                "rejection_reason": "rejected_no_template_candidate",
            }

        best = None
        best_score = 0.0
        for candidate in candidates:
            candidate_label = normalize_text(candidate.get("label"))
            local_name = _split_template_local_name(candidate.get("template_field_id"))
            candidate_text = normalize_text(
                f"{candidate.get('template_field_id')} {candidate.get('label')} {candidate.get('statement_type')}"
            )
            overlap = max(
                _token_overlap(label, candidate_text),
                _token_overlap(label, candidate_label),
                _token_overlap(label, local_name),
            )
            deterministic = float(candidate.get("deterministic_score") or 0.0)
            score = min(0.96, max(overlap, deterministic) + 0.04)
            if candidate_label and (candidate_label in label or label in candidate_label):
                score = max(score, 0.91)
            if local_name and local_name in label:
                score = max(score, 0.9)
            if score > best_score:
                best = candidate
                best_score = score

        if best is None or best_score < config.min_manual_confidence:
            return {
                "selected_template_field_id": None,
                "confidence": round(best_score, 4),
                "reason": "No provided candidate is safe enough for the extracted row.",
                "ranked_candidates": _mock_ranked_candidates(candidates, label),
                "requires_human_confirmation": True,
                "rejection_reason": "below_manual_confidence",
            }

        return {
            "selected_template_field_id": best["template_field_id"],
            "confidence": round(best_score, 4),
            "reason": "The extracted label and statement context align with this provided candidate concept.",
            "ranked_candidates": _mock_ranked_candidates(candidates, label),
            "requires_human_confirmation": True,
            "rejection_reason": None,
        }


async def run_llm_mapping_advisory_prompt(
    prompt: str,
    candidates: Sequence[Mapping[str, Any]],
    *,
    llm_client: Any | None = None,
    config: LLMMappingConfig | None = None,
) -> dict[str, Any]:
    """Run one candidate-constrained mapper prompt without persistence or apply."""

    effective_config = config or load_llm_mapping_config()
    client = llm_client or HuggingFaceQwenMappingClient()
    raw_response = await client.complete(prompt, config=effective_config)
    parsed, parse_error, raw_text, parsed_content, normalized_shape = parse_llm_json_response(
        raw_response
    )
    validated = validate_llm_mapping_output(
        parsed,
        candidates=candidates,
        high_confidence_threshold=effective_config.high_confidence_threshold,
        min_display_confidence=effective_config.min_display_confidence,
        min_manual_confidence=effective_config.min_manual_confidence,
        parse_error=parse_error,
    )
    validated.update(
        {
            "model_id": effective_config.model_id,
            "raw_response_preview": raw_text[:RAW_RESPONSE_PREVIEW_CHARS],
            "parsed_content_preview": parsed_content[:RAW_RESPONSE_PREVIEW_CHARS],
            "normalized_response_shape": normalized_shape,
        }
    )
    return {
        "validated_mapping": validated,
        "parsed_output": dict(parsed or {}),
    }


def _extract_prompt_input(prompt: str) -> dict[str, Any]:
    marker = "Input:\n"
    payload = prompt.split(marker, 1)[1] if marker in prompt else prompt
    try:
        parsed = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _token_overlap(left: Any, right: Any) -> float:
    left_tokens = set(normalize_text(left).split())
    right_tokens = set(normalize_text(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _split_template_local_name(template_field_id: Any) -> str:
    local = str(template_field_id or "").split(":")[-1]
    local = re.sub(r"([a-z])([A-Z])", r"\1 \2", local)
    local = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", local)
    return normalize_text(local)


def _mock_ranked_candidates(candidates: Sequence[Mapping[str, Any]], label: str) -> list[dict[str, Any]]:
    rows = []
    for candidate in candidates:
        candidate_label = normalize_text(candidate.get("label"))
        local_name = _split_template_local_name(candidate.get("template_field_id"))
        overlap = max(
            _token_overlap(label, f"{candidate.get('template_field_id')} {candidate.get('label')}"),
            _token_overlap(label, candidate_label),
            _token_overlap(label, local_name),
        )
        confidence = min(0.96, max(float(candidate.get("deterministic_score") or 0.0), overlap) + 0.04)
        if candidate_label and (candidate_label in label or label in candidate_label):
            confidence = max(confidence, 0.91)
        if local_name and local_name in label:
            confidence = max(confidence, 0.9)
        rows.append(
            {
                "template_field_id": candidate.get("template_field_id"),
                "confidence": round(confidence, 4),
                "reason": "Candidate provided by local deterministic template retrieval.",
            }
        )
    rows.sort(key=lambda row: (-float(row["confidence"]), str(row["template_field_id"])))
    return rows


async def load_filing_job_for_llm_mapping(db: AsyncSession, job_id: int) -> FilingJob | None:
    result = await db.execute(
        select(FilingJob)
        .where(FilingJob.id == job_id)
        .options(
            selectinload(FilingJob.pages)
            .selectinload(FinancialStatementPage.extracted_items)
            .selectinload(ExtractedDataItem.llm_mapping_suggestions),
            selectinload(FilingJob.llm_mapping_suggestions),
        )
    )
    return result.scalars().unique().one_or_none()


def build_llm_mapping_row_inputs(
    job: FilingJob,
    *,
    include_mapped: bool = False,
    max_rows: int = 50,
    max_candidates: int = 8,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = _sorted_item_rows(job)
    before_mapped_count = sum(1 for _page, item in rows if getattr(item, "template_field_id", None))
    entries: list[dict[str, Any]] = []

    for index, (page, item) in enumerate(rows):
        already_mapped = bool(getattr(item, "template_field_id", None))
        if already_mapped and not include_mapped:
            continue
        if len(entries) >= max_rows:
            break

        candidate = _candidate_from_item(item, page)
        diagnosis = diagnose_azure_di_candidate_mapping(candidate)
        rejection_reason = _hard_precheck_rejection_reason(candidate, diagnosis)
        disqualified = rejection_reason is not None
        candidate_rows = [] if disqualified else _candidate_rows_for_llm(candidate, limit=max_candidates)
        if not candidate_rows and not disqualified:
            rejection_reason = "rejected_no_template_candidate"

        entries.append(
            {
                "item": item,
                "page": page,
                "candidate": candidate,
                "row_context": _row_context(item=item, page=page, nearby=_nearby_rows(rows, index)),
                "already_mapped": already_mapped,
                "deterministic_diagnosis": diagnosis,
                "precheck_rejection_reason": rejection_reason if rejection_reason in DISQUALIFYING_REJECTION_REASONS or not candidate_rows else None,
                "candidate_concepts": candidate_rows,
            }
        )

    return entries, {
        "total_rows": len(rows),
        "already_mapped_rows": before_mapped_count,
    }


def _existing_suggestion_item_ids(job: FilingJob) -> set[str]:
    ids: set[str] = set()
    job_id = getattr(job, "id", None)
    for suggestion in list(getattr(job, "llm_mapping_suggestions", []) or []):
        if getattr(suggestion, "job_id", job_id) == job_id:
            item_id = getattr(suggestion, "extracted_data_item_id", None)
            if item_id:
                ids.add(str(item_id))

    for _page, item in _sorted_item_rows(job):
        for suggestion in list(getattr(item, "llm_mapping_suggestions", []) or []):
            if getattr(suggestion, "job_id", job_id) == job_id:
                item_id = getattr(suggestion, "extracted_data_item_id", getattr(item, "id", None))
                if item_id:
                    ids.add(str(item_id))
    return ids


def _should_pace_llm_client(llm_client: Any | None) -> bool:
    return isinstance(llm_client, HuggingFaceQwenMappingClient)


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


async def _flush_and_commit_persisted_suggestion(db: AsyncSession) -> None:
    flush = getattr(db, "flush", None)
    if flush is not None:
        await _maybe_await(flush())

    commit = getattr(db, "commit", None)
    if commit is not None:
        await _maybe_await(commit())


async def run_llm_mapping_for_job(
    db: AsyncSession,
    job_id: int,
    *,
    llm_client: Any | None = None,
    include_mapped: bool = False,
    apply_high_confidence: bool = False,
    persist_suggestions: bool = True,
    config: LLMMappingConfig | None = None,
) -> dict[str, Any]:
    job = await load_filing_job_for_llm_mapping(db, job_id)
    if job is None:
        raise ValueError(f"Filing job not found: {job_id}")
    return await run_llm_mapping_for_loaded_job(
        db,
        job,
        llm_client=llm_client,
        include_mapped=include_mapped,
        apply_high_confidence=apply_high_confidence,
        persist_suggestions=persist_suggestions,
        config=config,
    )


async def run_llm_mapping_for_loaded_job(
    db: AsyncSession | None,
    job: FilingJob,
    *,
    llm_client: Any | None = None,
    include_mapped: bool = False,
    apply_high_confidence: bool = False,
    persist_suggestions: bool = True,
    config: LLMMappingConfig | None = None,
) -> dict[str, Any]:
    config = config or load_llm_mapping_config()
    entries, base_counts = build_llm_mapping_row_inputs(
        job,
        include_mapped=include_mapped,
        max_rows=config.max_rows_per_job,
        max_candidates=config.max_candidates,
    )
    llm_called = llm_client is not None
    before_mapped_count = base_counts["already_mapped_rows"]
    results = []
    suggestions_generated = 0
    display_suggestions_generated = 0
    high_confidence_suggestions = 0
    rejected_rows = 0
    rejected_precheck_rows = 0
    rejected_low_confidence_rows = 0
    rejected_no_candidate_rows = 0
    invalid_llm_responses = 0
    hallucinated_concept_rejections = 0
    rows_sent_to_llm = 0
    provider_requests_started = 0
    applied_suggestions = 0
    rows_with_candidates = 0
    existing_suggestion_rows = 0
    persisted_suggestion_records = 0
    fewshot_example_store: list[dict[str, Any]] = []
    fewshot_loader_error: str | None = None
    existing_suggestion_item_ids = (
        _existing_suggestion_item_ids(job)
        if persist_suggestions and not include_mapped
        else set()
    )

    if llm_client is not None and config.fewshot_enabled and config.fewshot_max_examples > 0:
        try:
            fewshot_example_store = load_production_fewshot_example_store(
                case_split_mode=config.fewshot_case_split_mode,
            )
        except Exception as exc:
            fewshot_loader_error = _clean_text(str(exc), 500)
            logger.warning("Few-shot mapping example loading failed; falling back to base prompt: %s", exc)
            if not config.fewshot_fallback_to_base_prompt:
                raise

    for entry in entries:
        if entry["already_mapped"] and not include_mapped:
            continue

        row_result = _base_row_result(entry)
        item_id = str(getattr(entry["item"], "id", ""))
        if item_id and item_id in existing_suggestion_item_ids:
            row_result["suggestion"] = None
            row_result["skip_reason"] = "existing_ai_mapping_suggestion"
            existing_suggestion_rows += 1
            results.append(row_result)
            continue

        precheck_reason = entry.get("precheck_rejection_reason")
        candidates = entry.get("candidate_concepts") or []
        if candidates:
            rows_with_candidates += 1

        if precheck_reason:
            row_result["suggestion"] = _rejected_suggestion(precheck_reason)
            rejected_rows += 1
            rejected_precheck_rows += 1
            if precheck_reason == "rejected_no_template_candidate":
                rejected_no_candidate_rows += 1
        elif not candidates:
            row_result["suggestion"] = _rejected_suggestion("rejected_no_template_candidate")
            rejected_rows += 1
            rejected_no_candidate_rows += 1
        elif llm_client is None:
            row_result["suggestion"] = None
        else:
            rows_sent_to_llm += 1
            fewshot_examples = (
                retrieve_production_fewshot_examples(
                    row_context=entry["row_context"],
                    example_store=fewshot_example_store,
                    limit=config.fewshot_max_examples,
                )
                if fewshot_example_store
                else []
            )
            prompt_mode = "fewshot_guarded" if fewshot_examples else "base"
            prompt = build_mapping_prompt(
                entry["row_context"],
                candidates,
                fewshot_examples=fewshot_examples,
                guardrails_enabled=config.fewshot_guardrails_enabled,
            )
            row_result["prompt_mode"] = prompt_mode
            row_result["fewshot_examples_count"] = len(fewshot_examples)
            row_result["fewshot_example_ids"] = [
                example.get("example_id") or example.get("source_case_id")
                for example in fewshot_examples
            ]
            row_result["fewshot_source_case_ids"] = [
                example.get("source_case_id")
                for example in fewshot_examples
                if example.get("source_case_id")
            ]
            if fewshot_loader_error:
                row_result["fewshot_loader_error"] = fewshot_loader_error
            try:
                if (
                    provider_requests_started > 0
                    and _should_pace_llm_client(llm_client)
                    and config.provider_request_delay_seconds > 0
                ):
                    await asyncio.sleep(config.provider_request_delay_seconds)
                provider_requests_started += 1
                raw_response = await llm_client.complete(prompt, config=config)
                parsed, parse_error, raw_text, parsed_content, normalized_shape = parse_llm_json_response(raw_response)
            except Exception as exc:
                if is_rate_limit_error(exc):
                    rate_limit_exc = (
                        exc
                        if isinstance(exc, LLMMappingRateLimitError)
                        else LLMMappingRateLimitError()
                    )
                    rate_limit_exc.with_run_progress(
                        rows_sent_to_llm=rows_sent_to_llm,
                        processed_rows=len(results),
                        saved_suggestions=persisted_suggestion_records,
                        pending_rows=max(0, len(entries) - len(results)),
                        failed_row_id=item_id or None,
                    )
                    logger.warning(
                        "LLM mapping stopped by provider rate limit for job=%s row=%s processed_rows=%s saved_suggestions=%s pending_rows=%s",
                        getattr(job, "id", None),
                        item_id or None,
                        len(results),
                        persisted_suggestion_records,
                        rate_limit_exc.pending_rows,
                    )
                    raise rate_limit_exc from exc
                parsed, parse_error, raw_text, parsed_content, normalized_shape = (
                    None,
                    f"llm_call_failed: {exc}",
                    "",
                    "",
                    "invalid_json",
                )

            suggestion = validate_llm_mapping_output(
                parsed,
                candidates=candidates,
                high_confidence_threshold=config.high_confidence_threshold,
                min_display_confidence=config.min_display_confidence,
                min_manual_confidence=config.min_manual_confidence,
                parse_error=parse_error,
            )
            suggestion["raw_response_preview"] = raw_text[:RAW_RESPONSE_PREVIEW_CHARS]
            suggestion["parsed_content_preview"] = parsed_content[:RAW_RESPONSE_PREVIEW_CHARS]
            suggestion["normalized_response_shape"] = normalized_shape
            suggestion["prompt_mode"] = prompt_mode
            suggestion["fewshot_examples_count"] = len(fewshot_examples)
            suggestion["fewshot_example_ids"] = row_result["fewshot_example_ids"]
            suggestion["fewshot_source_case_ids"] = row_result["fewshot_source_case_ids"]
            suggestion["candidate_count"] = len(candidates)
            suggestion["model_id"] = config.model_id
            if suggestion["invalid_response"]:
                invalid_llm_responses += 1
            if suggestion["hallucinated_concept"]:
                hallucinated_concept_rejections += 1

            if suggestion["status"] == "suggested":
                suggestions_generated += 1
                display_suggestions_generated += 1
                if suggestion["confidence"] >= config.high_confidence_threshold:
                    high_confidence_suggestions += 1
            else:
                rejected_rows += 1
                if suggestion.get("rejection_reason") in {"rejected_low_confidence", "below_display_confidence", "below_manual_confidence"}:
                    rejected_low_confidence_rows += 1

            if _should_apply_suggestion(
                suggestion,
                entry,
                apply_high_confidence=apply_high_confidence,
                threshold=config.high_confidence_threshold,
            ):
                _apply_suggestion_to_item(entry["item"], suggestion)
                suggestion["status"] = "accepted"
                suggestion["requires_human_confirmation"] = False
                applied_suggestions += 1

            row_result["suggestion"] = suggestion

        if persist_suggestions and db is not None and row_result.get("suggestion") is not None:
            record = _make_suggestion_record(
                job_id=getattr(job, "id"),
                item_id=getattr(entry["item"], "id"),
                suggestion=row_result["suggestion"],
                config=config,
                diagnostic=row_result,
            )
            db.add(record)
            await _flush_and_commit_persisted_suggestion(db)
            persisted_suggestion_records += 1
            existing_suggestion_item_ids.add(str(getattr(entry["item"], "id")))
            row_result["suggestion_id"] = record.id

        results.append(row_result)

    if db is not None and persist_suggestions:
        flush = getattr(db, "flush", None)
        if flush is not None:
            maybe_awaitable = flush()
            if asyncio.iscoroutine(maybe_awaitable):
                await maybe_awaitable

    after_mapped_count = before_mapped_count + applied_suggestions
    return {
        "run_metadata": {
            "feature": "16E",
            "generated_at": _utc_now_iso(),
            "model_id": config.model_id,
            "llm_called": llm_called,
            "candidate_constrained": True,
            "confirmed_tag_id_set": False,
            "min_display_confidence": config.min_display_confidence,
            "min_manual_confidence": config.min_manual_confidence,
            "high_confidence_threshold": config.high_confidence_threshold,
            "auto_apply_high_confidence": bool(apply_high_confidence),
            "persist_suggestions": bool(persist_suggestions),
            "fewshot_enabled": config.fewshot_enabled,
            "fewshot_guardrails_enabled": config.fewshot_guardrails_enabled,
            "fewshot_max_examples": config.fewshot_max_examples,
            "fewshot_case_split_mode": config.fewshot_case_split_mode,
            "fewshot_examples_loaded": len(fewshot_example_store),
            "fewshot_loader_error": fewshot_loader_error,
        },
        "job_id": getattr(job, "id", None),
        "company_name": getattr(job, "company_name", None),
        "status": getattr(job, "status", None),
        "summary": {
            "total_rows": base_counts["total_rows"],
            "already_mapped_rows": before_mapped_count,
            "rows_considered": len(entries),
            "rows_sent_to_llm": rows_sent_to_llm,
            "existing_suggestion_rows": existing_suggestion_rows,
            "suggestions_generated": suggestions_generated,
            "persisted_suggestion_records": persisted_suggestion_records,
            "display_suggestions_generated": display_suggestions_generated,
            "high_confidence_suggestions": high_confidence_suggestions,
            "medium_confidence_suggestions": sum(
                1
                for row in results
                if (row.get("suggestion") or {}).get("confidence_category") == "medium"
            ),
            "low_confidence_suggestions": sum(
                1
                for row in results
                if (row.get("suggestion") or {}).get("confidence_category") == "low"
                and (row.get("suggestion") or {}).get("status") == "suggested"
            ),
            "rejected_rows": rejected_rows,
            "rejected_precheck_rows": rejected_precheck_rows,
            "rejected_low_confidence_rows": rejected_low_confidence_rows,
            "rejected_no_candidate_rows": rejected_no_candidate_rows,
            "candidate_coverage_rate": round(rows_with_candidates / len(entries), 4) if entries else 0.0,
            "invalid_llm_responses": invalid_llm_responses,
            "hallucinated_concept_rejections": hallucinated_concept_rejections,
            "rate_limited_rows": 0,
            "pending_rows_after_rate_limit": 0,
            "before_mapped_count": before_mapped_count,
            "after_mapped_count": after_mapped_count,
            "applied_suggestions": applied_suggestions,
            "db_mutated_extracted_data_items": applied_suggestions > 0,
        },
        "rows": results,
    }


def _base_row_result(entry: Mapping[str, Any]) -> dict[str, Any]:
    row_context = dict(entry.get("row_context") or {})
    diagnosis = entry.get("deterministic_diagnosis") or {}
    return {
        "extracted_data_item_id": row_context.get("extracted_data_item_id"),
        "page_number": row_context.get("page_number"),
        "extracted_label": row_context.get("extracted_label"),
        "extracted_value": row_context.get("extracted_value"),
        "value_previous_year": row_context.get("value_previous_year"),
        "statement_type": row_context.get("statement_type"),
        "already_mapped": bool(entry.get("already_mapped")),
        "deterministic_mapping_rejection_reason": diagnosis.get("mapping_rejection_reason"),
        "precheck_rejection_reason": entry.get("precheck_rejection_reason"),
        "candidate_concepts": entry.get("candidate_concepts") or [],
    }


def _rejected_suggestion(reason: str) -> dict[str, Any]:
    return {
        "selected_template_field_id": None,
        "confidence": 0.0,
        "reason": "",
        "ranked_candidates": [],
        "requires_human_confirmation": True,
        "rejection_reason": reason,
        "status": "rejected",
        "invalid_response": False,
        "hallucinated_concept": False,
        "warning_level": None,
        "confidence_category": "low",
    }


def _should_apply_suggestion(
    suggestion: Mapping[str, Any],
    entry: Mapping[str, Any],
    *,
    apply_high_confidence: bool,
    threshold: float,
) -> bool:
    if not apply_high_confidence:
        return False
    if suggestion.get("status") != "suggested":
        return False
    if float(suggestion.get("confidence") or 0.0) < threshold:
        return False
    if entry.get("precheck_rejection_reason"):
        return False
    item = entry.get("item")
    return bool(item is not None and not getattr(item, "template_field_id", None))


def _apply_suggestion_to_item(item: ExtractedDataItem, suggestion: Mapping[str, Any]) -> None:
    selected_id = str(suggestion.get("selected_template_field_id") or "").strip()
    selected_candidate = dict(suggestion.get("selected_candidate") or {})
    if not selected_id:
        return

    item.template_field_id = selected_id
    item.statement_type = selected_candidate.get("statement_type") or getattr(item, "statement_type", None)
    item.template_position = selected_candidate.get("position")
    item.is_required_field = bool(selected_candidate.get("required", False))
    item.is_reviewed = True
    item.confirmed_tag_id = None


def _make_suggestion_record(
    *,
    job_id: int,
    item_id: str,
    suggestion: Mapping[str, Any],
    config: LLMMappingConfig,
    diagnostic: Mapping[str, Any],
) -> LLMMappingSuggestion:
    status_value = str(suggestion.get("status") or "rejected")
    if status_value not in VALID_SUGGESTION_STATUSES:
        status_value = "rejected"
    return LLMMappingSuggestion(
        id=str(uuid.uuid4()),
        job_id=int(job_id),
        extracted_data_item_id=str(item_id),
        suggested_template_field_id=suggestion.get("selected_template_field_id"),
        confidence=float(suggestion.get("confidence") or 0.0),
        reason=_clean_text(suggestion.get("reason") or suggestion.get("rejection_reason"), 5000),
        ranked_candidates_json=json.dumps(suggestion.get("ranked_candidates") or [], ensure_ascii=True),
        status=status_value,
        model_id=config.model_id,
        raw_response_preview=_clean_text(suggestion.get("raw_response_preview"), RAW_RESPONSE_PREVIEW_CHARS),
        diagnostic_json=json.dumps(_diagnostic_preview(diagnostic), ensure_ascii=True, default=str),
    )


def _diagnostic_preview(diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    suggestion = diagnostic.get("suggestion") or {}
    return {
        "extracted_label": diagnostic.get("extracted_label"),
        "page_number": diagnostic.get("page_number"),
        "statement_type": diagnostic.get("statement_type"),
        "precheck_rejection_reason": diagnostic.get("precheck_rejection_reason"),
        "prompt_mode": diagnostic.get("prompt_mode") or suggestion.get("prompt_mode"),
        "fewshot_examples_count": diagnostic.get("fewshot_examples_count") or suggestion.get("fewshot_examples_count") or 0,
        "fewshot_example_ids": diagnostic.get("fewshot_example_ids") or suggestion.get("fewshot_example_ids") or [],
        "fewshot_source_case_ids": diagnostic.get("fewshot_source_case_ids") or suggestion.get("fewshot_source_case_ids") or [],
        "confidence_category": suggestion.get("confidence_category"),
        "warning_level": suggestion.get("warning_level"),
        "rejection_reason": suggestion.get("rejection_reason"),
        "candidate_count": len(diagnostic.get("candidate_concepts") or []),
        "selected_template_field_id": suggestion.get("selected_template_field_id"),
        "model_id": suggestion.get("model_id"),
        "suggestion": suggestion,
    }


def suggestion_template_metadata(template_field_id: str) -> dict[str, Any] | None:
    service = get_xbrl_template_service()
    concept = service.get_concept_info(template_field_id)
    if not concept:
        return None
    template_code = (concept.get("templates") or [None])[0]
    return {
        "template_field_id": template_field_id,
        "label": concept.get("label"),
        "statement_type": service.get_template_description(template_code) if template_code else None,
        "template_code": template_code,
        "position": concept.get("position"),
        "required": bool(concept.get("required", False)),
    }
