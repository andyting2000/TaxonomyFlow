"""Conservative production mapping bridge for Azure DI extracted rows."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Mapping

from services.azure_di_concept_metadata_enricher_v2 import CURATED_ALIAS_GROUPS_V2
from services.xbrl_template_service import (
    automatic_mapping_guardrail_reason,
    get_xbrl_template_service,
)
from services.template_group_registry import template_group_statement_family_map

logger = logging.getLogger(__name__)

NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
PERSISTABLE_ROW_TYPES = NUMERIC_ROW_TYPES | {"text_block"}
HIGH_CONFIDENCE_THRESHOLD = 0.86
AMBIGUOUS_SCORE_DELTA = 0.08

GENERIC_LABELS = {
    "current",
    "non current",
    "noncurrent",
    "other",
    "previous",
    "prior",
    "subtotal",
    "total",
    "year",
}

ALLOWED_SINGLE_TOKEN_LABELS = {
    "assets",
    "cash",
    "equity",
    "accrual",
    "accruals",
    "deposit",
    "deposits",
    "inventories",
    "inventory",
    "liabilities",
    "payables",
    "receivables",
    "revenue",
    "tax",
}

STOPWORDS = {
    "and",
    "at",
    "for",
    "from",
    "in",
    "of",
    "the",
    "to",
    "total",
}

COMPANY_NAME_TERMS = {
    "berhad",
    "bhd",
    "bhd.",
    "corp",
    "corporation",
    "limited",
    "ltd",
    "ltd.",
    "plc",
    "pte",
    "sdn",
    "sdn.",
}

FINANCIAL_LABEL_TERMS = {
    "accrual",
    "accruals",
    "administration",
    "administrative",
    "asset",
    "assets",
    "bank",
    "borrowings",
    "capital",
    "cash",
    "cost",
    "deposit",
    "deposits",
    "director",
    "expense",
    "expenses",
    "income",
    "liabilities",
    "liability",
    "loss",
    "overdraft",
    "payable",
    "payables",
    "profit",
    "receivable",
    "receivables",
    "revenue",
    "tax",
}

LABEL_STATEMENT_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(
            r"\b(net\s+increase|net\s+decrease|cash\s+and\s+cash\s+equivalents\s+at\s+"
            r"(?:beginning|end)|cash\s+flows?)\b",
            re.IGNORECASE,
        ),
        "510000",
        "cash_flow_label_evidence",
    ),
    (
        re.compile(
            r"\b(revenue|administrati(?:on|ve)\s+expenses?|loss\s+before\s+tax|"
            r"profit\s+before\s+tax|tax\s+expense|cost\s+of\s+sales|gross\s+profit|"
            r"finance\s+costs?|other\s+income)\b",
            re.IGNORECASE,
        ),
        "310000",
        "profit_or_loss_label_evidence",
    ),
    (
        re.compile(r"\b(other\s+comprehensive\s+income|total\s+comprehensive\s+(?:income|loss))\b", re.IGNORECASE),
        "410000",
        "comprehensive_income_label_evidence",
    ),
    (
        re.compile(r"\b(accumulated\s+loss(?:es)?|retained\s+earnings|share\s+capital|issued\s+capital)\b", re.IGNORECASE),
        "610000",
        "equity_label_evidence",
    ),
    (
        re.compile(
            r"\b(current\s+liabilities|other\s+receivables?|amount\s+due\s+to\s+director|"
            r"amount\s+due\s+from\s+director|bank\s+overdrafts?|other\s+payables?|"
            r"accruals?|deposits?|cash\s+and\s+bank\s+balances)\b",
            re.IGNORECASE,
        ),
        "210000",
        "financial_position_label_evidence",
    ),
]

FAMILY_TEMPLATE_CODES = {
    "financial_position": ("210000", "210100", "220000", "220100"),
    "profit_or_loss": ("310000", "320000"),
    "comprehensive_income": ("410000", "420000"),
    "cash_flows": ("510000", "520000"),
    "changes_in_equity": ("610000", "620000"),
}

DETERMINISTIC_CONCEPT_ALIASES = {
    "ifrs-smes:Revenue": {
        "revenue",
        "sales",
    },
    "ifrs-smes:AdministrativeExpense": {
        "administration expenses",
        "administrative expenses",
        "admin expenses",
    },
    "ifrs-smes:ProfitLossBeforeTax": {
        "loss before tax",
        "profit before tax",
        "profit loss before tax",
    },
    "ifrs-smes:IncomeTaxExpenseContinuingOperations": {
        "tax expense",
        "taxation",
    },
    "ifrs-smes:RetainedEarnings": {
        "accumulated loss",
        "accumulated losses",
        "retained earnings",
    },
    "ifrs-smes:IssuedCapital": {
        "contributed share capital",
        "share capital",
        "issued capital",
    },
    "ifrs-smes:TradeAndOtherCurrentReceivables": {
        "other receivable",
        "other receivables",
    },
    "ifrs-smes:TradeAndOtherCurrentPayables": {
        "amount due to director",
        "amount due to directors",
        "other payable",
        "other payables",
    },
    "ssmt-mpers:CurrentNontradeAccruals": {
        "accrual",
        "accruals",
    },
    "ssmt-mpers:OtherCurrentNontradeDeposits": {
        "deposit",
        "deposits",
    },
    "ssmt-mpers:UnsecuredBankOverdrafts": {
        "bank overdraft unsecured",
        "unsecured bank overdraft",
        "unsecured bank overdrafts",
    },
    "ssmt-mpers:CurrentPortionOfNoncurrentUnsecuredBankOverdrafts": {
        "bank overdraft unsecured",
        "unsecured bank overdraft",
        "unsecured bank overdrafts",
    },
    "ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents": {
        "net increase in cash and cash equivalents",
        "net decrease in cash and cash equivalents",
        "net increase decrease in cash and cash equivalents",
    },
    "ifrs-smes:CashAndCashEquivalents": {
        "cash and cash equivalents at beginning of year",
        "cash and cash equivalents at beginning of period",
        "cash and cash equivalents at end of year",
        "cash and cash equivalents at end of period",
    },
}

DIRECT_LABEL_CONCEPT_MATCHES = {
    "revenue": "ifrs-smes:Revenue",
    "administration expenses": "ifrs-smes:AdministrativeExpense",
    "administrative expenses": "ifrs-smes:AdministrativeExpense",
    "loss before tax": "ifrs-smes:ProfitLossBeforeTax",
    "profit before tax": "ifrs-smes:ProfitLossBeforeTax",
    "tax expense": "ifrs-smes:IncomeTaxExpenseContinuingOperations",
    "accumulated loss": "ifrs-smes:RetainedEarnings",
    "accumulated losses": "ifrs-smes:RetainedEarnings",
    "contributed share capital": "ifrs-smes:IssuedCapital",
    "share capital": "ifrs-smes:IssuedCapital",
    "net increase in cash and cash equivalents": "ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents",
    "net decrease in cash and cash equivalents": "ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents",
    "cash and cash equivalents at beginning of year": "ifrs-smes:CashAndCashEquivalents",
    "cash and cash equivalents at beginning of period": "ifrs-smes:CashAndCashEquivalents",
    "cash and cash equivalents at end of year": "ifrs-smes:CashAndCashEquivalents",
    "cash and cash equivalents at end of period": "ifrs-smes:CashAndCashEquivalents",
}

STATEMENT_SECTION_TO_TEMPLATE_CODE = {
    "auditors report": "130000",
    "corporate information": "710000",
    "directors report": "120000",
    "notes to financial statements": "730000",
    "notes to the financial statements": "730000",
    "significant accounting policies": "720000",
    "statement by directors": "120100",
    "statement of changes in equity": "610000",
    "statement of comprehensive income": "410000",
    "statement of financial position": "210000",
    "statement of profit or loss": "310000",
    "statutory declaration": "020000",
}

TEMPLATE_CODE_FAMILY = template_group_statement_family_map()


@dataclass(frozen=True)
class AzureDITemplateMapping:
    template_field_id: str | None = None
    statement_type: str | None = None
    template_position: int | None = None
    is_required_field: bool = False
    is_reviewed: bool = False
    confidence: str | None = None
    score: float = 0.0
    method: str | None = None
    warning: str | None = None
    reason: str | None = None


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text(value: Any) -> str:
    text = clean_text(value).lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def strip_note_references(value: Any) -> str:
    text = clean_text(value)
    text = re.sub(r"^\s*(?:note\s*)?\d+[a-z]?\s*[-).:]?\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:note\s*)?\d+[a-z]?\s*$", "", text, flags=re.IGNORECASE)
    return clean_text(text)


def normalized_candidate_label(value: Any) -> str:
    return strip_note_references(value)


def _token_set(value: Any) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if token and token not in STOPWORDS
    }


def _local_name(qname: Any) -> str:
    return str(qname or "").strip().split(":")[-1]


def _split_local_name(qname: Any) -> str:
    local = _local_name(qname)
    local = re.sub(r"([a-z])([A-Z])", r"\1 \2", local)
    local = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", local)
    return clean_text(local)


def _strip_total_prefix(value: Any) -> str:
    text = normalize_text(value)
    return re.sub(r"^(?:total|net)\s+", "", text).strip()


def _looks_like_note_number_only(candidate: Mapping[str, Any]) -> bool:
    value = clean_text(candidate.get("value") or candidate.get("extracted_value"))
    previous = clean_text(candidate.get("previous_value") or candidate.get("value_previous_year"))
    if previous:
        return False
    if not re.fullmatch(r"\d{1,2}[a-z]?", value, flags=re.IGNORECASE):
        return False
    warnings = " ".join(str(item) for item in candidate.get("warnings") or [])
    provenance = candidate.get("provenance") or {}
    if "note_column" in warnings:
        return True
    cells = provenance.get("cells") or []
    if any(normalize_text((cell or {}).get("content")) in {"note", "notes"} for cell in cells):
        return True
    return bool(value and not re.search(r"[,().-]", value))


def _is_ambiguous_summary_label(label: Any) -> bool:
    normalized = normalize_text(strip_note_references(label))
    return normalized in {
        "trade and other receivables",
        "trade and other current receivables",
        "trade and other payables",
        "trade and other current payables",
    }


def _looks_like_person_or_company_name(label: Any) -> bool:
    raw = clean_text(label)
    normalized = normalize_text(raw)
    if not normalized:
        return False
    tokens = normalized.split()
    if any(token in FINANCIAL_LABEL_TERMS for token in tokens):
        return False
    if any(token in COMPANY_NAME_TERMS for token in tokens):
        return True
    if re.search(r"\b(?:mr|mrs|ms|miss|dr|dato|datuk|tan\s+sri|tuan|puan)\b", normalized):
        return True
    words = [word for word in re.split(r"\s+", raw) if word]
    titlecase_words = [word for word in words if re.fullmatch(r"[A-Z][a-zA-Z'.-]+", word)]
    return 2 <= len(words) <= 5 and len(titlecase_words) == len(words)


def _is_generic_label(label: Any) -> bool:
    clean_label = strip_note_references(label)
    normalized = normalize_text(clean_label)
    base = _strip_total_prefix(clean_label)
    if not normalized or normalized in GENERIC_LABELS:
        return True
    if base in ALLOWED_SINGLE_TOKEN_LABELS:
        return False
    tokens = _token_set(normalized)
    return len(tokens) <= 1 and normalized not in ALLOWED_SINGLE_TOKEN_LABELS


def _statement_template_code(statement_section: Any) -> str | None:
    section = normalize_text(statement_section)
    if not section:
        return None
    if section in STATEMENT_SECTION_TO_TEMPLATE_CODE:
        return STATEMENT_SECTION_TO_TEMPLATE_CODE[section]
    if "financial position" in section or "balance sheet" in section:
        return "210000"
    if "profit or loss" in section or "income statement" in section:
        return "310000"
    if "comprehensive income" in section:
        return "410000"
    if "changes in equity" in section:
        return "610000"
    if "cash flow" in section:
        if "direct" in section:
            return "510000"
        if "indirect" in section:
            return "520000"
        return None
    if "accounting polic" in section or "basis of preparation" in section:
        return "720000"
    if "notes" in section:
        return "730000"
    return None


def _statement_family_for_code(template_code: str | None) -> str | None:
    return TEMPLATE_CODE_FAMILY.get(str(template_code or ""))


def classify_azure_di_statement(candidate: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    """Classify the statement section from heading context plus strong label evidence."""

    raw_label = candidate.get("label") or candidate.get("text") or candidate.get("source_snippet")
    label = strip_note_references(raw_label)
    existing_code = _statement_template_code(candidate.get("statement_section"))
    existing_family = _statement_family_for_code(existing_code)
    existing_section = clean_text(candidate.get("statement_section"))

    for pattern, template_code, evidence in LABEL_STATEMENT_RULES:
        if not pattern.search(label):
            continue
        label_family = _statement_family_for_code(template_code)
        if existing_family in {"notes", "accounting_policies", "directors_report", "auditors_report"}:
            return existing_section, existing_code, "preserved_non_statement_section"
        if existing_family and existing_family != label_family:
            statement_type = get_xbrl_template_service().get_template_description(template_code)
            return statement_type, template_code, evidence
        if not existing_code:
            statement_type = get_xbrl_template_service().get_template_description(template_code)
            return statement_type, template_code, evidence
        return existing_section, existing_code, "statement_heading_context"

    if existing_code:
        return existing_section, existing_code, "statement_heading_context"
    return existing_section or None, None, "statement_section_not_mapped"


def _candidate_template_codes(candidate: Mapping[str, Any]) -> tuple[tuple[str, ...], str | None, str | None]:
    _statement, template_code, evidence = classify_azure_di_statement(candidate)
    family = _statement_family_for_code(template_code)
    if family in FAMILY_TEMPLATE_CODES:
        return FAMILY_TEMPLATE_CODES[family], template_code, evidence
    if template_code:
        return (template_code,), template_code, evidence
    return (), None, evidence


def _concept_is_structural(concept_id: str, label: str) -> bool:
    haystack = normalize_text(f"{concept_id} {label}")
    local = normalize_text(_local_name(concept_id))
    return (
        "abstract" in haystack
        or local.endswith("axis")
        or local.endswith("member")
        or local.endswith("domain")
        or local.endswith("lineitems")
        or local.endswith("table")
    )


def _concept_is_text(concept_id: str, label: str) -> bool:
    haystack = normalize_text(f"{concept_id} {label}")
    return "text block" in haystack or "explanatory" in haystack


def _concept_is_metadata(concept_id: str, label: str) -> bool:
    local = normalize_text(_local_name(concept_id))
    label_norm = normalize_text(label)
    return local.startswith(
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
    ) or label_norm.startswith(
        ("date ", "description ", "disclosure whether ", "method ", "name ", "number ", "type ")
    )


def _row_type_compatible(row_type: str, concept_id: str, label: str) -> bool:
    if _concept_is_structural(concept_id, label):
        return False
    if row_type in NUMERIC_ROW_TYPES:
        return not _concept_is_text(concept_id, label) and not _concept_is_metadata(concept_id, label)
    if row_type == "text_block":
        return _concept_is_text(concept_id, label) or _concept_is_metadata(concept_id, label)
    return False


def _curated_aliases_for_concept(
    *,
    concept_id: str,
    concept_label: str,
    template_code: str,
    row_type: str,
) -> set[str]:
    aliases: set[str] = set()
    local = _local_name(concept_id)
    concept_label_norm = normalize_text(concept_label)
    template_family = TEMPLATE_CODE_FAMILY.get(template_code)
    expected_type = "text_block" if row_type == "text_block" else "numeric"

    for group in CURATED_ALIAS_GROUPS_V2:
        group_type = str(group.get("expected_type") or "")
        if group_type and group_type != expected_type:
            continue
        group_family = str(group.get("statement_family") or "")
        if (
            group_family
            and template_family
            and group_family != template_family
            and local not in set(group.get("target_local_names") or [])
        ):
            continue
        target_names = {str(item) for item in group.get("target_local_names") or []}
        target_patterns = [normalize_text(item) for item in group.get("target_label_patterns") or []]
        target_matches = local in target_names or any(
            pattern and pattern in concept_label_norm for pattern in target_patterns
        )
        if not target_matches:
            continue
        aliases.update(normalize_text(item) for item in group.get("aliases") or [])

    return {alias for alias in aliases if alias}


def _concept_aliases(concept: Mapping[str, Any], *, template_code: str, row_type: str) -> set[str]:
    concept_id = str(concept.get("id") or "")
    concept_label = clean_text(concept.get("label") or concept_id)
    aliases = {
        normalize_text(concept_label),
        normalize_text(_split_local_name(concept_id)),
        _strip_total_prefix(concept_label),
        _strip_total_prefix(_split_local_name(concept_id)),
    }
    aliases.update(normalize_text(item) for item in concept.get("aliases") or [])
    aliases.update(normalize_text(item) for item in DETERMINISTIC_CONCEPT_ALIASES.get(concept_id, set()))
    aliases.update(
        _curated_aliases_for_concept(
            concept_id=concept_id,
            concept_label=concept_label,
            template_code=template_code,
            row_type=row_type,
        )
    )
    return {alias for alias in aliases if alias}


def _token_overlap(left: Any, right: Any) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _score_concept(
    *,
    label: str,
    row_type: str,
    template_code: str,
    concept: Mapping[str, Any],
) -> dict[str, Any] | None:
    concept_id = str(concept.get("id") or "")
    concept_label = clean_text(concept.get("label") or concept_id)
    if not concept_id or not _row_type_compatible(row_type, concept_id, concept_label):
        return None

    clean_label = strip_note_references(label)
    label_norm = normalize_text(clean_label)
    label_base = _strip_total_prefix(clean_label)
    concept_label_norm = normalize_text(concept_label)
    concept_base = _strip_total_prefix(concept_label)
    local_norm = normalize_text(_split_local_name(concept_id))
    local_base = _strip_total_prefix(local_norm)
    aliases = _concept_aliases(concept, template_code=template_code, row_type=row_type)

    exact_label = bool(label_norm and (label_norm == concept_label_norm or label_base == concept_label_norm))
    exact_local = bool(label_norm and (label_norm == local_norm or label_base == local_base))
    exact_alias = bool(label_norm and (label_norm in aliases or label_base in aliases))
    phrase_containment = bool(
        label_norm
        and concept_label_norm
        and not _is_generic_label(clean_label)
        and (label_norm in concept_label_norm or concept_label_norm in label_norm)
    )
    similarity = SequenceMatcher(None, label_norm, concept_label_norm).ratio()
    overlap = max(_token_overlap(label, concept_label), _token_overlap(label, local_norm))

    if exact_label or exact_local or exact_alias:
        score = 0.94
    elif phrase_containment and overlap >= 0.6:
        score = 0.82 + (0.10 * overlap)
    else:
        score = (0.52 * similarity) + (0.36 * overlap)
        if any(alias and (alias in label_norm or label_norm in alias) for alias in aliases):
            score += 0.08

    if concept.get("required"):
        score += 0.02
    if row_type == "subtotal_or_total" and re.search(r"\b(total|assets|liabilities|equity|profit|loss)\b", concept_label, re.I):
        score += 0.03
    if _is_generic_label(clean_label) and not (exact_label or exact_local or exact_alias):
        score -= 0.25

    score = round(max(0.0, min(1.0, score)), 4)
    if score < 0.5:
        return None

    if exact_alias:
        method = "exact_alias_match"
    elif exact_label or exact_local:
        method = "normalized_label_match"
    elif phrase_containment:
        method = "phrase_containment_match"
    else:
        method = "statement_family_match"

    return {
        "concept": concept,
        "concept_id": concept_id,
        "concept_label": concept_label,
        "score": score,
        "exact_label": exact_label,
        "exact_local": exact_local,
        "exact_alias": exact_alias,
        "phrase_containment": phrase_containment,
        "token_overlap": round(overlap, 4),
        "similarity": round(similarity, 4),
        "method": method,
        "template_code": template_code,
    }


def _mapping_warning(mapping: AzureDITemplateMapping, *, template_code: str) -> str | None:
    if not mapping.template_field_id:
        return None
    return "azure_di_template_mapping=" + json.dumps(
        {
            "template_field_id": mapping.template_field_id,
            "statement_type": mapping.statement_type,
            "template_code": template_code,
            "confidence": mapping.confidence,
            "score": mapping.score,
            "method": mapping.method,
        },
        ensure_ascii=True,
        sort_keys=True,
    )


def _unique_scored_candidates(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_concept: dict[str, dict[str, Any]] = {}
    for score in scored:
        concept_id = str(score["concept_id"])
        current = best_by_concept.get(concept_id)
        if current is None or float(score["score"]) > float(current["score"]):
            best_by_concept[concept_id] = score
    rows = list(best_by_concept.values())
    rows.sort(key=lambda item: (-float(item["score"]), str(item["concept_id"]), str(item.get("template_code") or "")))
    return rows


def _top_candidate_matches(candidate: Mapping[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    row_type = str(candidate.get("row_type") or "")
    label = normalized_candidate_label(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
    template_codes, _classified_code, _evidence = _candidate_template_codes(candidate)
    if row_type not in PERSISTABLE_ROW_TYPES or not label or not template_codes:
        return []

    service = get_xbrl_template_service()
    scored: list[dict[str, Any]] = []
    for template_code in template_codes:
        template = service.get_template(template_code)
        if not template:
            continue
        for concept in template.get("concepts") or []:
            score = _score_concept(
                label=label,
                row_type=row_type,
                template_code=template_code,
                concept=concept,
            )
            if score is not None:
                scored.append(score)

    matches = []
    for score in _unique_scored_candidates(scored)[:limit]:
        matches.append(
            {
                "template_field_id": score["concept_id"],
                "label": score["concept_label"],
                "template_code": score.get("template_code"),
                "statement_type": service.get_template_description(str(score.get("template_code") or "")),
                "score": score["score"],
                "method": score["method"],
                "required": bool((score.get("concept") or {}).get("required", False)),
                "position": (score.get("concept") or {}).get("position"),
                "namespace": (score.get("concept") or {}).get("namespace"),
            }
        )
    return matches


def azure_di_candidate_template_matches(
    candidate: Mapping[str, Any],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return deterministic local template candidates for an Azure DI row."""

    return _top_candidate_matches(candidate, limit=limit)


def diagnose_azure_di_candidate_mapping(candidate: Mapping[str, Any]) -> dict[str, Any]:
    mapping = map_azure_di_candidate_to_template_field(candidate)
    statement_type, template_code, evidence = classify_azure_di_statement(candidate)
    return {
        "label": clean_text(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet")),
        "normalized_label": normalize_text(normalized_candidate_label(candidate.get("label"))),
        "value": clean_text(candidate.get("value") or candidate.get("extracted_value")),
        "page_number": candidate.get("page_number"),
        "input_statement_section": clean_text(candidate.get("statement_section")),
        "classified_statement_type": statement_type,
        "classified_template_code": template_code,
        "statement_classification_evidence": evidence,
        "mapped": bool(mapping.template_field_id),
        "template_field_id": mapping.template_field_id,
        "mapping_method": mapping.method,
        "mapping_score": mapping.score,
        "mapping_rejection_reason": mapping.reason,
        "top_candidate_matches": _top_candidate_matches(candidate),
    }


def map_azure_di_candidate_to_template_field(candidate: Mapping[str, Any]) -> AzureDITemplateMapping:
    """Return a high-confidence template-field mapping for an Azure DI candidate.

    The bridge is deliberately conservative: it maps only when the candidate has a
    recognized statement section, a local template concept match, and no close
    competing concept in the same template.
    """

    row_type = str(candidate.get("row_type") or "")
    if row_type not in PERSISTABLE_ROW_TYPES:
        return AzureDITemplateMapping(reason="row_type_not_persistable")

    label = normalized_candidate_label(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet"))
    if not label or _is_generic_label(label):
        return AzureDITemplateMapping(reason="rejected_generic_label")
    if _is_ambiguous_summary_label(label):
        return AzureDITemplateMapping(reason="rejected_ambiguous")
    if _looks_like_note_number_only(candidate):
        return AzureDITemplateMapping(reason="rejected_note_number_only")
    if _looks_like_person_or_company_name(label):
        return AzureDITemplateMapping(reason="rejected_person_or_company_name")

    template_codes, classified_template_code, classification_evidence = _candidate_template_codes(candidate)
    if not template_codes:
        return AzureDITemplateMapping(reason="rejected_no_template_candidate")

    service = get_xbrl_template_service()
    scored: list[dict[str, Any]] = []
    for template_code in template_codes:
        template = service.get_template(template_code)
        if not template:
            continue
        scored.extend(
            score
            for concept in template.get("concepts") or []
            for score in [
                _score_concept(
                    label=label,
                    row_type=row_type,
                    template_code=template_code,
                    concept=concept,
                )
            ]
            if score is not None
        )
    scored = _unique_scored_candidates(scored)
    if not scored:
        return AzureDITemplateMapping(reason="rejected_no_template_candidate")

    direct_concept_id = DIRECT_LABEL_CONCEPT_MATCHES.get(normalize_text(label))
    direct_match_applied = False
    if direct_concept_id:
        direct_scores = [score for score in scored if score["concept_id"] == direct_concept_id]
        if direct_scores:
            scored = direct_scores + [
                score for score in scored if score["concept_id"] != direct_concept_id
            ]
            direct_match_applied = True

    top = scored[0]
    second = None if direct_match_applied else (scored[1] if len(scored) > 1 else None)
    top_score = float(top["score"])
    if top_score < HIGH_CONFIDENCE_THRESHOLD:
        return AzureDITemplateMapping(reason="rejected_low_confidence", score=top_score)
    if second and top_score - float(second["score"]) < AMBIGUOUS_SCORE_DELTA:
        return AzureDITemplateMapping(reason="rejected_ambiguous", score=top_score)

    concept_id = str(top["concept_id"])
    guardrail_reason = automatic_mapping_guardrail_reason(concept_id, label)
    if guardrail_reason:
        return AzureDITemplateMapping(reason=guardrail_reason, score=top_score)

    concept = top["concept"]
    template_code = str(top.get("template_code") or classified_template_code or template_codes[0])
    statement_type = service.get_template_description(template_code) or clean_text(candidate.get("statement_section"))
    mapping = AzureDITemplateMapping(
        template_field_id=concept_id,
        statement_type=statement_type,
        template_position=concept.get("position"),
        is_required_field=bool(concept.get("required", False)),
        is_reviewed=True,
        confidence="high",
        score=top_score,
        method=str(top.get("method") or classification_evidence or "statement_family_match"),
    )
    return AzureDITemplateMapping(
        **{
            **mapping.__dict__,
            "warning": _mapping_warning(mapping, template_code=template_code),
        }
    )
