"""Local deterministic PDF row to XBRL fact alignment for Feature #18A."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from services.golden_mbrs_dataset import discover_golden_cases, load_normalized_extraction_rows
from services.reference_xbrl_parser import parse_reference_xbrl


NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
DEFAULT_HIGH_SCORE = 80
DEFAULT_MEDIUM_SCORE = 65
AMBIGUITY_SCORE_GAP = 8
TOP_CANDIDATE_LIMIT = 5

GENERIC_LABELS = {
    "amount",
    "current",
    "non current",
    "other",
    "total",
    "subtotal",
    "balance",
    "net",
    "less",
}

STATEMENT_FAMILY_NAMES = {
    "financial_position": "Statement of Financial Position",
    "income_statement": "Statement of Profit or Loss and Other Comprehensive Income",
    "cash_flow": "Statement of Cash Flows",
    "changes_in_equity": "Statement of Changes in Equity",
    "notes": "Notes",
}

ALIAS_GROUPS = (
    (
        "cash and cash equivalents at end of period",
        "cash and cash equivalents at end of year",
        "cash and cash equivalents at end of the year",
        "cash and cash equivalents end of year",
        "cash and cash equivalents at end",
        "cash and cash equivalents at the end of financial year",
        "cash cash equivalents end period",
    ),
    ("revenue", "turnover", "sales"),
    ("profit before tax", "profit before taxation", "profit before income tax"),
    ("tax expense", "income tax expense", "taxation", "income tax"),
    ("trade and other receivables", "receivables", "other receivables", "trade receivables"),
    ("trade and other payables", "payables", "other payables", "trade payables"),
    ("accruals", "accrued expenses", "accrued liabilities"),
    ("property plant and equipment", "ppe", "property plants and equipment"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    if text.strip() in {"-", "--"}:
        return Decimal("0")
    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        text = text[1:-1]
    text = re.sub(r"^(?:rm|myr|usd|\$)\s*", "", text.strip(), flags=re.IGNORECASE)
    text = text.replace(",", "").replace(" ", "")
    text = re.sub(r"[^0-9.+-]", "", text)
    if text in {"", "-", "+", ".", "-.", "+."}:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    return -number if negative_parentheses and number > 0 else number


def normalize_numeric_value(value: Any) -> str | None:
    """Normalize common financial-statement numeric text to a stable string."""
    number = _decimal(value)
    if number is None:
        return None
    normalized = format(number, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _normalize_note_references(text: str) -> str:
    text = re.sub(r"\(\s*notes?\s*\d+[a-z]?(?:\.\d+)?\s*\)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\bnotes?\s*\d+[a-z]?(?:\.\d+)?\b", " ", text, flags=re.IGNORECASE)
    return text


def normalize_label(value: Any) -> str:
    """Normalize labels without using embeddings or external services."""
    text = clean_text(value).lower()
    text = _normalize_note_references(text)
    text = text.replace("&", " and ")
    text = re.sub(r"\bp\s*[\.\-]?\s*p\s*[\.\-]?\s*e\b", " ppe ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _alias_map() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for group in ALIAS_GROUPS:
        canonical = normalize_label(group[0])
        for alias in group:
            aliases[normalize_label(alias)] = canonical
    return aliases


ALIASES = _alias_map()


def canonical_label(value: Any) -> str:
    normalized = normalize_label(value)
    if normalized in ALIASES:
        return ALIASES[normalized]
    for alias, canonical in sorted(ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if alias and alias in normalized:
            return canonical
    return normalized


def _tokens(value: Any) -> set[str]:
    return {token for token in normalize_label(value).split() if token}


def _token_overlap(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def label_similarity(left: Any, right: Any) -> dict[str, Any]:
    left_norm = normalize_label(left)
    right_norm = normalize_label(right)
    if not left_norm or not right_norm:
        return {"ratio": 0.0, "reason": "missing_label", "alias_match": False}
    if left_norm == right_norm:
        return {"ratio": 1.0, "reason": "exact_normalized_label", "alias_match": False}
    left_canonical = canonical_label(left_norm)
    right_canonical = canonical_label(right_norm)
    if left_canonical and left_canonical == right_canonical:
        return {"ratio": 0.96, "reason": "alias_match", "alias_match": True}
    if left_norm in right_norm or right_norm in left_norm:
        containment = min(len(left_norm), len(right_norm)) / max(len(left_norm), len(right_norm))
        return {"ratio": max(0.82, containment), "reason": "label_containment", "alias_match": False}
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    overlap = _token_overlap(left_norm, right_norm)
    return {
        "ratio": round(max(sequence, overlap), 4),
        "reason": "token_or_sequence_similarity",
        "alias_match": False,
    }


def local_name(qname: Any) -> str:
    return str(qname or "").split(":")[-1]


def concept_label(qname: Any) -> str:
    value = local_name(qname)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    value = value.replace("_", " ").replace("-", " ")
    return clean_text(value)


def statement_family(value: Any) -> str | None:
    normalized = normalize_label(value)
    if not normalized:
        return None
    if "financial position" in normalized or "balance sheet" in normalized:
        return "financial_position"
    if "cash flow" in normalized or "cash flows" in normalized:
        return "cash_flow"
    if "changes in equity" in normalized:
        return "changes_in_equity"
    if "comprehensive income" in normalized or "profit or loss" in normalized or "income statement" in normalized:
        return "income_statement"
    if normalized.startswith("notes") or "notes to the financial statements" in normalized:
        return "notes"
    return None


def infer_fact_statement_family(fact: Mapping[str, Any]) -> str | None:
    label = normalize_label(concept_label(fact.get("qname") or fact.get("local_name")))
    if not label:
        return None
    if "cash flow" in label or "cash flows" in label:
        return "cash_flow"
    if "cash and cash equivalents" in label and any(token in label for token in ("end", "beginning", "period", "year")):
        return "cash_flow"
    if any(token in label for token in ("revenue", "turnover", "sales", "income", "expense", "tax", "profit", "loss", "cost of sales")):
        return "income_statement"
    if any(
        token in label
        for token in (
            "asset",
            "liabilit",
            "equity",
            "receivable",
            "payable",
            "inventory",
            "inventories",
            "capital",
            "retained",
            "accumulated",
            "property plant",
            "cash",
            "bank",
            "accrual",
        )
    ):
        return "financial_position"
    if any(token in label for token in ("disclosure", "policy", "text block", "note")):
        return "notes"
    return None


def _year_from_date(value: Any) -> int | None:
    match = re.match(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def fact_period_year(fact: Mapping[str, Any]) -> int | None:
    return _year_from_date(fact.get("instant") or fact.get("period_end") or fact.get("period_start"))


def fact_period_type(fact: Mapping[str, Any]) -> str:
    if fact.get("instant"):
        return "instant"
    if fact.get("period_start") or fact.get("period_end"):
        return "duration"
    period = fact.get("period") or {}
    if isinstance(period, Mapping):
        return str(period.get("type") or "unknown")
    return "unknown"


def expected_period_type_for_statement(family: str | None) -> str | None:
    if family in {"financial_position", "changes_in_equity"}:
        return "instant"
    if family in {"income_statement", "cash_flow"}:
        return "duration"
    return None


def _cash_flow_balance_label(value: Any) -> bool:
    canonical = canonical_label(value)
    return "cash and cash equivalents at end" in canonical or "cash and cash equivalents at beginning" in canonical


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _is_generic_label(value: Any) -> bool:
    normalized = normalize_label(value)
    tokens = normalized.split()
    return normalized in GENERIC_LABELS or len(tokens) <= 1 or normalized.startswith("total ")


def _row_base_id(row: Mapping[str, Any], fallback_index: int) -> str:
    for key in ("original_candidate_id", "source_candidate_id", "candidate_id", "mapping_input_id", "row_id"):
        if row.get(key):
            return str(row[key])
    return f"row-{fallback_index}"


def _row_order(row: Mapping[str, Any], fallback_index: int) -> int:
    provenance = row.get("provenance") or {}
    for key in ("row_index", "_original_case_index", "_original_global_index"):
        value = provenance.get(key) if key in provenance else row.get(key)
        parsed = _safe_int(value)
        if parsed is not None:
            return parsed
    return fallback_index


@dataclass(frozen=True)
class PdfRowValue:
    sample_id: str
    company_name: str
    pdf_row_id: str
    source_pdf_row_id: str
    pdf_label: str
    pdf_value: str | None
    numeric_value: Decimal | None
    value_role: str
    expected_year: int | None
    pdf_statement_type: str | None
    pdf_statement_family: str | None
    pdf_page: int | None
    pdf_row_order: int
    row_type: str | None


def _sample_current_year(facts: Sequence[Mapping[str, Any]]) -> int | None:
    years = [fact_period_year(fact) for fact in facts if fact_period_year(fact) is not None]
    return max(years) if years else None


def pdf_row_values(
    *,
    sample_id: str,
    company_name: str,
    row: Mapping[str, Any],
    fallback_index: int,
    default_current_year: int | None,
) -> list[PdfRowValue]:
    if str(row.get("row_type") or "") not in NUMERIC_ROW_TYPES:
        return []
    label = clean_text(row.get("label") or row.get("extracted_label"))
    statement_type = clean_text(row.get("statement_type") or row.get("statement_section")) or None
    family = statement_family(statement_type)
    base_id = _row_base_id(row, fallback_index)
    page = _safe_int(row.get("page_number") or row.get("pdf_page"))
    order = _row_order(row, fallback_index)
    current_year = _safe_int(row.get("current_year")) or default_current_year
    prior_year = _safe_int(row.get("prior_year")) or (current_year - 1 if current_year else None)
    values = [
        ("current", row.get("value") if row.get("value") is not None else row.get("extracted_value"), current_year),
        ("prior", row.get("previous_value") if row.get("previous_value") is not None else row.get("value_previous_year"), prior_year),
    ]
    output: list[PdfRowValue] = []
    for role, raw_value, expected_year in values:
        numeric = _decimal(raw_value)
        if numeric is None:
            continue
        suffix = role if role == "prior" or any(_decimal(item[1]) is not None for item in values if item[0] == "prior") else "current"
        output.append(
            PdfRowValue(
                sample_id=sample_id,
                company_name=company_name,
                pdf_row_id=f"{base_id}:{suffix}",
                source_pdf_row_id=base_id,
                pdf_label=label,
                pdf_value=normalize_numeric_value(raw_value),
                numeric_value=numeric,
                value_role=role,
                expected_year=expected_year,
                pdf_statement_type=statement_type,
                pdf_statement_family=family,
                pdf_page=page,
                pdf_row_order=order,
                row_type=str(row.get("row_type") or ""),
            )
        )
    return output


def _value_match(row_value: Decimal | None, fact_value: Any) -> dict[str, Any] | None:
    fact_decimal = _decimal(fact_value)
    if row_value is None or fact_decimal is None:
        return None
    if row_value == fact_decimal:
        return {"kind": "exact", "points": 40, "sign_mismatch": False}
    if row_value.copy_abs() == fact_decimal.copy_abs():
        return {"kind": "absolute_sign_match", "points": 25, "sign_mismatch": True}
    tolerance = Decimal("0.5")
    if abs(row_value - fact_decimal) <= tolerance:
        return {"kind": "rounded_tolerance", "points": 36, "sign_mismatch": False}
    if abs(row_value.copy_abs() - fact_decimal.copy_abs()) <= tolerance:
        return {"kind": "rounded_absolute_sign_match", "points": 22, "sign_mismatch": True}
    return None


def _unit_match(fact: Mapping[str, Any]) -> bool:
    unit = str(fact.get("unit_ref") or "").lower()
    return bool(unit) and any(token in unit for token in ("myr", "rm", "iso4217"))


def is_alignable_xbrl_fact(fact: Mapping[str, Any]) -> bool:
    return bool(fact.get("is_numeric")) and not bool(fact.get("is_nil")) and _unit_match(fact)


def _total_semantics(label: Any) -> bool:
    normalized = normalize_label(label)
    return any(token in normalized.split() for token in ("total", "subtotal")) or normalized.startswith("net ")


def _candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "xbrl_fact_id": candidate.get("xbrl_fact_id"),
        "xbrl_qname": candidate.get("xbrl_qname"),
        "xbrl_label": candidate.get("xbrl_label"),
        "xbrl_value": candidate.get("xbrl_value"),
        "xbrl_context_id": candidate.get("xbrl_context_id"),
        "xbrl_period": candidate.get("xbrl_period"),
        "xbrl_unit": candidate.get("xbrl_unit"),
        "score": candidate.get("score"),
        "score_breakdown": candidate.get("score_breakdown"),
        "match_reasons": candidate.get("match_reasons"),
        "conflict_reasons": candidate.get("conflict_reasons"),
    }


def score_candidate(row: PdfRowValue, fact: Mapping[str, Any]) -> dict[str, Any] | None:
    if not is_alignable_xbrl_fact(fact):
        return None
    value = _value_match(row.numeric_value, fact.get("normalized_value") or fact.get("value"))
    if value is None:
        return None

    fact_label = concept_label(fact.get("qname") or fact.get("local_name"))
    similarity = label_similarity(row.pdf_label, fact_label)
    fact_family = infer_fact_statement_family(fact)
    fact_year = fact_period_year(fact)
    period_type = fact_period_type(fact)
    expected_period_type = expected_period_type_for_statement(row.pdf_statement_family)
    if row.pdf_statement_family == "cash_flow" and _cash_flow_balance_label(row.pdf_label):
        expected_period_type = "instant"
    unit_ok = _unit_match(fact)
    alias_match = bool(similarity.get("alias_match"))

    score = int(value["points"])
    breakdown: dict[str, Any] = {"value_match": value["points"]}
    reasons = [f"value_{value['kind']}"]
    conflicts: list[str] = []
    penalties: dict[str, int] = {}

    label_points = round(float(similarity["ratio"]) * 25)
    score += label_points
    breakdown["label_similarity"] = label_points
    reasons.append(str(similarity["reason"]))

    if row.pdf_statement_family and fact_family:
        if row.pdf_statement_family == fact_family:
            score += 15
            breakdown["statement_family_match"] = 15
            reasons.append("statement_family_match")
        else:
            penalties["statement_family_mismatch"] = -15
            conflicts.append("statement_family_mismatch")
    elif row.pdf_statement_family:
        breakdown["statement_family_match"] = 0

    if row.expected_year and fact_year:
        if row.expected_year == fact_year:
            score += 10
            breakdown["period_match"] = 10
            reasons.append("period_year_match")
        else:
            penalties["period_year_mismatch"] = -10
            conflicts.append("period_year_mismatch")
    elif row.expected_year:
        breakdown["period_match"] = 0

    if expected_period_type and period_type != "unknown":
        if expected_period_type == period_type:
            reasons.append("period_type_match")
        else:
            penalties["period_type_mismatch"] = -8
            conflicts.append("period_type_mismatch")

    if alias_match:
        score += 5
        breakdown["concept_alias_match"] = 5
        reasons.append("concept_alias_match")
    else:
        breakdown["concept_alias_match"] = 0

    if unit_ok:
        score += 5
        breakdown["unit_match"] = 5
        reasons.append("unit_match")
    else:
        breakdown["unit_match"] = 0
        conflicts.append("missing_or_non_currency_unit")

    row_total = _total_semantics(row.pdf_label)
    fact_total = _total_semantics(fact_label)
    if row_total == fact_total and row_total:
        score += 3
        breakdown["subtotal_total_semantics"] = 3
        reasons.append("subtotal_total_semantics_match")
    elif row_total != fact_total:
        penalties["subtotal_total_semantics_mismatch"] = -5
        conflicts.append("subtotal_total_semantics_mismatch")

    if value["sign_mismatch"]:
        penalties["sign_mismatch"] = -20
        conflicts.append("sign_mismatch_absolute_value_only")

    penalty_total = sum(penalties.values())
    score += penalty_total
    breakdown["penalties"] = penalties
    score = max(0, min(100, score))

    return {
        "xbrl_fact_id": fact.get("fact_id"),
        "xbrl_qname": fact.get("qname"),
        "xbrl_label": fact_label,
        "xbrl_value": fact.get("normalized_value") or normalize_numeric_value(fact.get("value")),
        "xbrl_context_id": fact.get("context_ref"),
        "xbrl_period": fact.get("period"),
        "xbrl_period_year": fact_year,
        "xbrl_period_type": period_type,
        "xbrl_unit": fact.get("unit_ref"),
        "score": score,
        "score_breakdown": breakdown,
        "match_reasons": reasons,
        "conflict_reasons": conflicts,
        "label_similarity_ratio": similarity["ratio"],
        "fact_statement_family": fact_family,
    }


def _classify_alignment(
    *,
    row: PdfRowValue,
    candidates: list[dict[str, Any]],
    min_high_score: int,
    min_medium_score: int,
) -> tuple[str, list[str]]:
    if row.numeric_value is None:
        return "unmatched", ["missing_pdf_numeric_value"]
    if not candidates:
        return "unmatched", ["no_xbrl_value_match"]

    top = candidates[0]
    runner_up = candidates[1] if len(candidates) > 1 else None
    conflicts = set(top.get("conflict_reasons") or [])
    major_conflicts = {
        "sign_mismatch_absolute_value_only",
        "statement_family_mismatch",
        "period_type_mismatch",
    }
    ambiguous_reasons: list[str] = []
    if runner_up and int(top["score"]) - int(runner_up["score"]) <= AMBIGUITY_SCORE_GAP:
        ambiguous_reasons.append("multiple_candidates_close_in_score")
    if len(candidates) > 1 and _is_generic_label(row.pdf_label):
        ambiguous_reasons.append("generic_pdf_label_with_duplicate_value")
    if len(candidates) >= 3 and float(top.get("label_similarity_ratio") or 0) < 0.75:
        ambiguous_reasons.append("same_value_repeated_across_many_facts")
    if "period_year_mismatch" in conflicts and row.expected_year:
        ambiguous_reasons.append("current_comparative_period_confusion")
    if ambiguous_reasons:
        return "ambiguous", ambiguous_reasons
    if int(top["score"]) >= min_high_score and not (conflicts & major_conflicts):
        return "high", []
    if int(top["score"]) >= min_medium_score and "sign_mismatch_absolute_value_only" not in conflicts:
        return "medium", []
    return "low", list(conflicts or ["weak_alignment_evidence"])


def align_pdf_row_value(
    row: PdfRowValue,
    facts: Sequence[Mapping[str, Any]],
    *,
    min_high_score: int = DEFAULT_HIGH_SCORE,
    min_medium_score: int = DEFAULT_MEDIUM_SCORE,
) -> dict[str, Any]:
    candidates = [candidate for fact in facts if (candidate := score_candidate(row, fact)) is not None]
    candidates.sort(key=lambda item: (-int(item["score"]), str(item.get("xbrl_qname")), str(item.get("xbrl_fact_id"))))
    bucket, extra_conflicts = _classify_alignment(
        row=row,
        candidates=candidates,
        min_high_score=min_high_score,
        min_medium_score=min_medium_score,
    )
    top = candidates[0] if candidates else {}
    conflict_reasons = list(dict.fromkeys([*(top.get("conflict_reasons") or []), *extra_conflicts]))
    return {
        "sample_id": row.sample_id,
        "company_name": row.company_name,
        "pdf_row_id": row.pdf_row_id,
        "source_pdf_row_id": row.source_pdf_row_id,
        "pdf_label": row.pdf_label,
        "pdf_value": row.pdf_value,
        "pdf_value_role": row.value_role,
        "pdf_expected_year": row.expected_year,
        "pdf_statement_type": row.pdf_statement_type,
        "pdf_statement_family": row.pdf_statement_family,
        "pdf_page": row.pdf_page,
        "pdf_row_order": row.pdf_row_order,
        "row_type": row.row_type,
        "xbrl_fact_id": top.get("xbrl_fact_id"),
        "xbrl_qname": top.get("xbrl_qname"),
        "xbrl_label": top.get("xbrl_label"),
        "xbrl_value": top.get("xbrl_value"),
        "xbrl_context_id": top.get("xbrl_context_id"),
        "xbrl_period": top.get("xbrl_period"),
        "xbrl_unit": top.get("xbrl_unit"),
        "score": top.get("score", 0),
        "score_breakdown": top.get("score_breakdown", {}),
        "confidence_bucket": bucket,
        "match_reasons": top.get("match_reasons", []),
        "conflict_reasons": conflict_reasons,
        "competing_candidates": [_candidate_summary(candidate) for candidate in candidates[1:TOP_CANDIDATE_LIMIT]],
        "candidate_count": len(candidates),
    }


def _apply_global_ambiguity(alignments: list[dict[str, Any]]) -> None:
    by_fact: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for alignment in alignments:
        if alignment.get("confidence_bucket") in {"high", "medium"} and alignment.get("xbrl_fact_id"):
            by_fact[(str(alignment.get("sample_id")), str(alignment.get("xbrl_fact_id")))].append(alignment)
    for items in by_fact.values():
        if len(items) <= 1:
            continue
        for item in items:
            item["confidence_bucket"] = "ambiguous"
            item.setdefault("conflict_reasons", [])
            if "one_xbrl_fact_matches_multiple_pdf_rows" not in item["conflict_reasons"]:
                item["conflict_reasons"].append("one_xbrl_fact_matches_multiple_pdf_rows")


def align_sample(
    *,
    sample_id: str,
    company_name: str,
    rows: Sequence[Mapping[str, Any]],
    facts: Sequence[Mapping[str, Any]],
    min_high_score: int = DEFAULT_HIGH_SCORE,
    min_medium_score: int = DEFAULT_MEDIUM_SCORE,
) -> tuple[list[dict[str, Any]], list[PdfRowValue]]:
    numeric_facts = [fact for fact in facts if is_alignable_xbrl_fact(fact)]
    current_year = _sample_current_year(numeric_facts)
    row_values = [
        row_value
        for index, row in enumerate(rows, start=1)
        for row_value in pdf_row_values(
            sample_id=sample_id,
            company_name=company_name,
            row=row,
            fallback_index=index,
            default_current_year=current_year,
        )
    ]
    alignments = [
        align_pdf_row_value(
            row_value,
            numeric_facts,
            min_high_score=min_high_score,
            min_medium_score=min_medium_score,
        )
        for row_value in row_values
    ]
    _apply_global_ambiguity(alignments)
    return alignments, row_values


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def _readable_sample_name(case: Mapping[str, Any]) -> str:
    metadata = case.get("metadata") or {}
    return str(
        metadata.get("azure_di_case_id")
        or metadata.get("source_case_id")
        or Path(str(metadata.get("source_case_dir") or "")).name
        or case.get("case_id")
    )


def _matches_sample(value: str, patterns: Sequence[str]) -> bool:
    haystack = normalize_label(value)
    return any(normalize_label(pattern) and normalize_label(pattern) in haystack for pattern in patterns)


def _case_search_text(case: Mapping[str, Any]) -> str:
    metadata = case.get("metadata") or {}
    parts = [
        case.get("case_id"),
        metadata.get("source_case_id"),
        metadata.get("azure_di_case_id"),
        metadata.get("source_case_dir"),
        case.get("pdf_path"),
    ]
    return " ".join(str(part or "") for part in parts)


def discover_alignment_inputs(
    *,
    dataset_dir: str | Path,
    include_samples: Sequence[str] = (),
    exclude_samples: Sequence[str] = (),
    exclude_outliers: Sequence[str] = ("Shield",),
    max_samples: int | None = None,
) -> dict[str, Any]:
    cases = discover_golden_cases(dataset_dir)
    sample_records: list[dict[str, Any]] = []
    included_count = 0
    include_filter_active = bool(include_samples)
    for case in cases:
        case_id = str(case.get("case_id"))
        metadata = case.get("metadata") or {}
        search_text = _case_search_text(case)
        rows, row_sources = ([], [])
        facts_count = 0
        numeric_facts_count = 0
        reason = None
        status = "included"
        if case.get("status") != "ready":
            status = "excluded"
            reason = "incomplete_pdf_xml_pair"
        elif include_filter_active and not _matches_sample(search_text, include_samples):
            status = "excluded"
            reason = "not_in_include_filter"
        elif _matches_sample(search_text, exclude_samples):
            status = "excluded"
            reason = "excluded_by_cli_sample_filter"
        elif not include_filter_active and _matches_sample(search_text, exclude_outliers):
            status = "excluded"
            reason = "outlier_excluded_by_default"
        if case.get("status") == "ready":
            try:
                reference = parse_reference_xbrl(case_id, case["reference_path"], "xml")
                facts = reference.get("facts") or []
                facts_count = len(facts)
                numeric_facts_count = sum(1 for fact in facts if is_alignable_xbrl_fact(fact))
                rows, row_sources = load_normalized_extraction_rows(case)
                if status == "included" and not rows:
                    status = "excluded"
                    reason = "missing_cached_azure_di_normalized_rows"
            except Exception as exc:  # report discovery failures without hiding other samples
                if status == "included":
                    status = "excluded"
                    reason = f"load_error:{exc.__class__.__name__}"
                else:
                    reason = f"{reason}; count_load_error:{exc.__class__.__name__}" if reason else f"count_load_error:{exc.__class__.__name__}"
        if status == "included":
            if max_samples is not None and included_count >= max_samples:
                status = "excluded"
                reason = "max_samples_limit"
            else:
                included_count += 1
        sample_records.append(
            {
                "sample_id": case_id,
                "company_name": _readable_sample_name(case),
                "status": status,
                "reason": reason,
                "pdf_path": _display_path(Path(case["pdf_path"])),
                "reference_path": _display_path(Path(case["reference_path"])),
                "metadata": metadata,
                "pdf_rows_found": len(rows),
                "pdf_rows_considered": sum(1 for row in rows if str(row.get("row_type") or "") in NUMERIC_ROW_TYPES),
                "xbrl_facts_found": facts_count,
                "xbrl_numeric_facts_considered": numeric_facts_count,
                "normalized_extraction_sources": row_sources,
            }
        )
    return {
        "total_samples_found": len(cases),
        "included_samples": [sample for sample in sample_records if sample["status"] == "included"],
        "excluded_samples": [sample for sample in sample_records if sample["status"] == "excluded"],
        "samples": sample_records,
    }


def _fact_key(sample_id: str, fact: Mapping[str, Any]) -> tuple[str, str]:
    return sample_id, str(fact.get("fact_id") or "")


def _fact_summary(sample_id: str, company_name: str, fact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "company_name": company_name,
        "xbrl_fact_id": fact.get("fact_id"),
        "xbrl_qname": fact.get("qname"),
        "xbrl_label": concept_label(fact.get("qname") or fact.get("local_name")),
        "xbrl_value": fact.get("normalized_value") or normalize_numeric_value(fact.get("value")),
        "xbrl_context_id": fact.get("context_ref"),
        "xbrl_period": fact.get("period"),
        "xbrl_unit": fact.get("unit_ref"),
    }


def _counts_by_bucket(alignments: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counter = Counter(str(alignment.get("confidence_bucket") or "unknown") for alignment in alignments)
    return {bucket: counter.get(bucket, 0) for bucket in ["high", "medium", "low", "ambiguous", "unmatched"]}


def _per_sample_summary(alignments: Sequence[Mapping[str, Any]], samples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_sample: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for alignment in alignments:
        by_sample[str(alignment.get("sample_id"))].append(alignment)
    output = []
    for sample in samples:
        sample_alignments = by_sample.get(str(sample["sample_id"]), [])
        output.append(
            {
                "sample_id": sample["sample_id"],
                "company_name": sample["company_name"],
                "pdf_rows_found": sample["pdf_rows_found"],
                "pdf_rows_considered": sample["pdf_rows_considered"],
                "pdf_row_values_considered": len(sample_alignments),
                "xbrl_facts_found": sample["xbrl_facts_found"],
                "xbrl_numeric_facts_considered": sample["xbrl_numeric_facts_considered"],
                **_counts_by_bucket(sample_alignments),
            }
        )
    return output


def _per_statement_summary(alignments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_statement: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for alignment in alignments:
        key = str(alignment.get("pdf_statement_type") or "Unknown")
        by_statement[key].append(alignment)
    return [
        {"statement_type": statement, "total": len(items), **_counts_by_bucket(items)}
        for statement, items in sorted(by_statement.items())
    ]


def _repeated_patterns(alignments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for alignment in alignments:
        if alignment.get("confidence_bucket") not in {"high", "medium"} or not alignment.get("xbrl_qname"):
            continue
        grouped[(canonical_label(alignment.get("pdf_label")), str(alignment.get("xbrl_qname")))].append(alignment)
    patterns = []
    for (label, qname), items in grouped.items():
        samples = sorted({str(item.get("sample_id")) for item in items})
        patterns.append(
            {
                "normalized_pdf_label": label,
                "xbrl_qname": qname,
                "count": len(items),
                "sample_count": len(samples),
                "samples": samples,
                "best_score": max(int(item.get("score") or 0) for item in items),
            }
        )
    return sorted(patterns, key=lambda item: (-item["sample_count"], -item["count"], item["xbrl_qname"]))[:30]


def _ambiguous_duplicate_cases(alignments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    ambiguous = [item for item in alignments if item.get("confidence_bucket") == "ambiguous"]
    ambiguous.sort(key=lambda item: (-int(item.get("candidate_count") or 0), -int(item.get("score") or 0)))
    return [
        {
            "sample_id": item.get("sample_id"),
            "pdf_row_id": item.get("pdf_row_id"),
            "pdf_label": item.get("pdf_label"),
            "pdf_value": item.get("pdf_value"),
            "score": item.get("score"),
            "candidate_count": item.get("candidate_count"),
            "conflict_reasons": item.get("conflict_reasons"),
            "top_candidate": {
                "xbrl_fact_id": item.get("xbrl_fact_id"),
                "xbrl_qname": item.get("xbrl_qname"),
                "xbrl_label": item.get("xbrl_label"),
            },
            "competing_candidates": item.get("competing_candidates"),
        }
        for item in ambiguous[:30]
    ]


def _recommend_next(summary: Mapping[str, Any]) -> dict[str, Any]:
    high = int(summary.get("high_confidence_count") or 0)
    medium = int(summary.get("medium_confidence_count") or 0)
    repeated = len(summary.get("repeated_mapping_patterns") or [])
    justified = high >= 20 and repeated >= 5
    return {
        "feature_18b_rulebook_generation_justified": justified,
        "recommended_next_feature": (
            "Feature #18B - Build reusable mapping rulebook from high-confidence PDF-XBRL alignments."
            if justified
            else "Review #18A ambiguities before starting #18B rulebook generation."
        ),
        "basis": {
            "high_confidence_count": high,
            "medium_confidence_count": medium,
            "repeated_pattern_count": repeated,
        },
    }


def build_alignment_reports(
    *,
    dataset_dir: str | Path,
    include_samples: Sequence[str] = (),
    exclude_samples: Sequence[str] = (),
    exclude_outliers: Sequence[str] = ("Shield",),
    max_samples: int | None = None,
    debug_sample: str | None = None,
    min_high_score: int = DEFAULT_HIGH_SCORE,
    min_medium_score: int = DEFAULT_MEDIUM_SCORE,
) -> dict[str, Any]:
    discovery = discover_alignment_inputs(
        dataset_dir=dataset_dir,
        include_samples=include_samples or ([debug_sample] if debug_sample else ()),
        exclude_samples=exclude_samples,
        exclude_outliers=exclude_outliers,
        max_samples=max_samples,
    )
    all_alignments: list[dict[str, Any]] = []
    all_numeric_facts: list[tuple[str, str, Mapping[str, Any]]] = []
    for sample in discovery["included_samples"]:
        case_dir = Path(dataset_dir) / str(sample["sample_id"])
        case = {
            "case_id": sample["sample_id"],
            "case_dir": case_dir,
            "metadata": sample.get("metadata") or {},
        }
        rows, _sources = load_normalized_extraction_rows(case)
        reference = parse_reference_xbrl(sample["sample_id"], case_dir / "reference.xml", "xml")
        facts = reference.get("facts") or []
        numeric_facts = [fact for fact in facts if is_alignable_xbrl_fact(fact)]
        all_numeric_facts.extend((sample["sample_id"], sample["company_name"], fact) for fact in numeric_facts)
        sample_alignments, _row_values = align_sample(
            sample_id=sample["sample_id"],
            company_name=sample["company_name"],
            rows=rows,
            facts=facts,
            min_high_score=min_high_score,
            min_medium_score=min_medium_score,
        )
        all_alignments.extend(sample_alignments)

    matched_fact_keys = {
        (str(item.get("sample_id")), str(item.get("xbrl_fact_id")))
        for item in all_alignments
        if item.get("confidence_bucket") in {"high", "medium"} and item.get("xbrl_fact_id")
    }
    unmatched_facts = [
        _fact_summary(sample_id, company_name, fact)
        for sample_id, company_name, fact in all_numeric_facts
        if _fact_key(sample_id, fact) not in matched_fact_keys
    ]
    ambiguous_alignments = [item for item in all_alignments if item.get("confidence_bucket") == "ambiguous"]
    unmatched_pdf_rows = [item for item in all_alignments if item.get("confidence_bucket") == "unmatched"]
    buckets = _counts_by_bucket(all_alignments)
    repeated = _repeated_patterns(all_alignments)
    concept_qnames = {fact.get("qname") for _sample_id, _company_name, fact in all_numeric_facts if fact.get("qname")}
    matched_concepts = {
        item.get("xbrl_qname")
        for item in all_alignments
        if item.get("confidence_bucket") in {"high", "medium"} and item.get("xbrl_qname")
    }
    summary = {
        "feature": "18A",
        "generated_at": _utc_now(),
        "dataset_dir": str(dataset_dir),
        "min_high_score": min_high_score,
        "min_medium_score": min_medium_score,
        "total_samples_found": discovery["total_samples_found"],
        "included_sample_count": len(discovery["included_samples"]),
        "excluded_sample_count": len(discovery["excluded_samples"]),
        "total_pdf_rows_found": sum(int(sample.get("pdf_rows_found") or 0) for sample in discovery["included_samples"]),
        "total_pdf_rows_considered": sum(int(sample.get("pdf_rows_considered") or 0) for sample in discovery["included_samples"]),
        "total_pdf_row_values_considered": len(all_alignments),
        "total_xbrl_facts_found": sum(int(sample.get("xbrl_facts_found") or 0) for sample in discovery["included_samples"]),
        "total_xbrl_facts_considered": len(all_numeric_facts),
        "high_confidence_count": buckets["high"],
        "medium_confidence_count": buckets["medium"],
        "low_confidence_count": buckets["low"],
        "ambiguous_count": buckets["ambiguous"],
        "unmatched_pdf_row_count": buckets["unmatched"],
        "unmatched_xbrl_fact_count": len(unmatched_facts),
        "per_sample_summary": _per_sample_summary(all_alignments, discovery["included_samples"]),
        "per_statement_summary": _per_statement_summary(all_alignments),
        "concept_coverage_summary": {
            "matched_high_or_medium_concepts": len(matched_concepts),
            "numeric_xbrl_concepts_considered": len(concept_qnames),
            "ratio": round(len(matched_concepts) / len(concept_qnames), 4) if concept_qnames else 0.0,
        },
        "repeated_mapping_patterns": repeated,
        "top_30_high_confidence_alignments": [
            item
            for item in sorted(
                (alignment for alignment in all_alignments if alignment.get("confidence_bucket") == "high"),
                key=lambda value: (-int(value.get("score") or 0), str(value.get("sample_id")), str(value.get("pdf_row_id"))),
            )[:30]
        ],
        "top_ambiguous_duplicate_value_cases": _ambiguous_duplicate_cases(all_alignments),
        "safety": {
            "external_llm_called": False,
            "external_provider_called": False,
            "azure_di_live_call_made": False,
            "database_mutated": False,
            "production_behavior_changed": False,
            "api_changed": False,
            "ui_changed": False,
            "xbrl_generated": False,
            "arelle_run": False,
        },
    }
    summary["recommendation"] = _recommend_next(summary)

    run_metadata = {
        "feature": "18A",
        "generated_at": summary["generated_at"],
        "read_only": True,
        "offline_only": True,
        **summary["safety"],
    }
    alignment_report = {
        "run_metadata": run_metadata,
        "discovery": discovery,
        "summary": summary,
        "alignments": all_alignments,
    }
    summary_report = {
        "run_metadata": run_metadata,
        "discovery": discovery,
        "summary": summary,
    }
    ambiguous_report = {
        "run_metadata": run_metadata,
        "summary": {
            "ambiguous_count": len(ambiguous_alignments),
            "top_ambiguous_duplicate_value_cases": summary["top_ambiguous_duplicate_value_cases"],
        },
        "ambiguous_alignments": ambiguous_alignments,
    }
    unmatched_report = {
        "run_metadata": run_metadata,
        "summary": {
            "unmatched_pdf_row_count": len(unmatched_pdf_rows),
            "unmatched_xbrl_fact_count": len(unmatched_facts),
        },
        "unmatched_pdf_rows": unmatched_pdf_rows,
        "unmatched_xbrl_facts": unmatched_facts,
    }
    return {
        "alignment": alignment_report,
        "summary": summary_report,
        "ambiguous": ambiguous_report,
        "unmatched": unmatched_report,
    }


def _sample_table(samples: Sequence[Mapping[str, Any]]) -> list[str]:
    lines = [
        "| Sample | Company | Status | Reason | PDF rows | PDF rows considered | XBRL facts | XBRL facts considered |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for sample in samples:
        lines.append(
            f"| {sample.get('sample_id')} | {sample.get('company_name')} | {sample.get('status')} | "
            f"{sample.get('reason') or ''} | {sample.get('pdf_rows_found', 0)} | "
            f"{sample.get('pdf_rows_considered', 0)} | {sample.get('xbrl_facts_found', 0)} | "
            f"{sample.get('xbrl_numeric_facts_considered', 0)} |"
        )
    return lines


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    discovery = report.get("discovery") or {}
    recommendation = summary.get("recommendation") or {}
    lines = [
        "# PDF-XBRL Deterministic Alignment Summary - Feature #18A",
        "",
        "## Metrics",
        "",
    ]
    for key in (
        "total_samples_found",
        "included_sample_count",
        "excluded_sample_count",
        "total_pdf_rows_considered",
        "total_pdf_row_values_considered",
        "total_xbrl_facts_considered",
        "high_confidence_count",
        "medium_confidence_count",
        "ambiguous_count",
        "unmatched_pdf_row_count",
        "unmatched_xbrl_fact_count",
    ):
        lines.append(f"- {key}: {summary.get(key, 0)}")
    lines.extend(
        [
            "",
            "## Included Samples",
            "",
            *_sample_table(discovery.get("included_samples") or []),
            "",
            "## Excluded Samples",
            "",
            *_sample_table(discovery.get("excluded_samples") or []),
            "",
            "## Top Repeated Mapping Patterns",
            "",
            "| Label | XBRL QName | Count | Samples |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for pattern in summary.get("repeated_mapping_patterns") or []:
        lines.append(
            f"| {pattern.get('normalized_pdf_label')} | {pattern.get('xbrl_qname')} | "
            f"{pattern.get('count')} | {pattern.get('sample_count')} |"
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- #18B justified: {recommendation.get('feature_18b_rulebook_generation_justified')}",
            f"- Next: {recommendation.get('recommended_next_feature')}",
            "",
            "## Safety",
            "",
        ]
    )
    for key, value in (summary.get("safety") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def render_alignment_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF-XBRL Deterministic Alignments - Feature #18A",
        "",
        f"- High-confidence alignments: {summary.get('high_confidence_count', 0)}",
        f"- Medium-confidence alignments: {summary.get('medium_confidence_count', 0)}",
        f"- Ambiguous alignments: {summary.get('ambiguous_count', 0)}",
        "",
        "## Top 30 High-Confidence Alignments",
        "",
        "| Sample | PDF label | PDF value | XBRL qname | Score |",
        "| --- | --- | ---: | --- | ---: |",
    ]
    for item in summary.get("top_30_high_confidence_alignments") or []:
        lines.append(
            f"| {item.get('sample_id')} | {item.get('pdf_label')} | {item.get('pdf_value')} | "
            f"{item.get('xbrl_qname')} | {item.get('score')} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_ambiguous_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF-XBRL Ambiguous Alignments - Feature #18A",
        "",
        f"- Ambiguous alignments: {summary.get('ambiguous_count', 0)}",
        "",
        "## Top Duplicate/Close Cases",
        "",
        "| Sample | PDF label | PDF value | Candidate count | Reasons |",
        "| --- | --- | ---: | ---: | --- |",
    ]
    for item in summary.get("top_ambiguous_duplicate_value_cases") or []:
        lines.append(
            f"| {item.get('sample_id')} | {item.get('pdf_label')} | {item.get('pdf_value')} | "
            f"{item.get('candidate_count')} | {', '.join(item.get('conflict_reasons') or [])} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_unmatched_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    rows = report.get("unmatched_pdf_rows") or []
    facts = report.get("unmatched_xbrl_facts") or []
    lines = [
        "# PDF-XBRL Unmatched Cases - Feature #18A",
        "",
        f"- Unmatched PDF rows: {summary.get('unmatched_pdf_row_count', 0)}",
        f"- Unmatched XBRL facts: {summary.get('unmatched_xbrl_fact_count', 0)}",
        "",
        "## Sample Unmatched PDF Rows",
        "",
        "| Sample | PDF label | Value | Reasons |",
        "| --- | --- | ---: | --- |",
    ]
    for item in rows[:30]:
        lines.append(
            f"| {item.get('sample_id')} | {item.get('pdf_label')} | {item.get('pdf_value')} | "
            f"{', '.join(item.get('conflict_reasons') or [])} |"
        )
    lines.extend(
        [
            "",
            "## Sample Unmatched XBRL Facts",
            "",
            "| Sample | XBRL qname | Value | Context |",
            "| --- | --- | ---: | --- |",
        ]
    )
    for item in facts[:30]:
        lines.append(
            f"| {item.get('sample_id')} | {item.get('xbrl_qname')} | {item.get('xbrl_value')} | "
            f"{item.get('xbrl_context_id')} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_alignment_reports(
    *,
    dataset_dir: str | Path,
    output_dir: str | Path,
    include_samples: Sequence[str] = (),
    exclude_samples: Sequence[str] = (),
    exclude_outliers: Sequence[str] = ("Shield",),
    max_samples: int | None = None,
    debug_sample: str | None = None,
    min_high_score: int = DEFAULT_HIGH_SCORE,
    min_medium_score: int = DEFAULT_MEDIUM_SCORE,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = build_alignment_reports(
        dataset_dir=dataset_dir,
        include_samples=include_samples,
        exclude_samples=exclude_samples,
        exclude_outliers=exclude_outliers,
        max_samples=max_samples,
        debug_sample=debug_sample,
        min_high_score=min_high_score,
        min_medium_score=min_medium_score,
    )
    paths = {
        "alignment_json": output / "pdf_xbrl_alignment_18a.json",
        "alignment_md": output / "pdf_xbrl_alignment_18a.md",
        "summary_json": output / "pdf_xbrl_alignment_summary_18a.json",
        "summary_md": output / "pdf_xbrl_alignment_summary_18a.md",
        "ambiguous_json": output / "pdf_xbrl_alignment_ambiguous_18a.json",
        "ambiguous_md": output / "pdf_xbrl_alignment_ambiguous_18a.md",
        "unmatched_json": output / "pdf_xbrl_alignment_unmatched_18a.json",
        "unmatched_md": output / "pdf_xbrl_alignment_unmatched_18a.md",
    }
    writers = (
        (paths["alignment_json"], reports["alignment"]),
        (paths["summary_json"], reports["summary"]),
        (paths["ambiguous_json"], reports["ambiguous"]),
        (paths["unmatched_json"], reports["unmatched"]),
    )
    for path, payload in writers:
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    paths["alignment_md"].write_text(render_alignment_markdown(reports["alignment"]), encoding="utf-8")
    paths["summary_md"].write_text(render_summary_markdown(reports["summary"]), encoding="utf-8")
    paths["ambiguous_md"].write_text(render_ambiguous_markdown(reports["ambiguous"]), encoding="utf-8")
    paths["unmatched_md"].write_text(render_unmatched_markdown(reports["unmatched"]), encoding="utf-8")
    return {"paths": paths, **reports}
