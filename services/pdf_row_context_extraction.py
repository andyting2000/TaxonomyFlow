"""Cached PDF row context extraction for Feature #18E-A."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.golden_mbrs_dataset import discover_golden_cases, load_normalized_extraction_rows
from services.pdf_xbrl_deterministic_alignment import (
    canonical_label,
    clean_text,
    normalize_label,
    pdf_row_values,
    statement_family,
)


NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
MAIN_STATEMENT_TITLES = {
    "financial_position": "Statement of Financial Position",
    "income_statement": "Statement of Comprehensive Income",
    "cash_flow": "Statement of Cash Flows",
    "changes_in_equity": "Statement of Changes in Equity",
}
MAIN_STATEMENT_FAMILIES = set(MAIN_STATEMENT_TITLES)
SAFETY = {
    "external_llm_called": False,
    "external_provider_called": False,
    "azure_di_live_call_made": False,
    "database_mutated": False,
    "production_behavior_changed": False,
    "api_changed": False,
    "ui_changed": False,
    "xbrl_generated": False,
    "arelle_run": False,
    "auto_applied": False,
    "confirmed_tag_id_mutated": False,
}


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_outlier_case(case: Mapping[str, Any]) -> bool:
    metadata = case.get("metadata") or {}
    text = " ".join(
        str(value or "")
        for value in (
            case.get("case_id"),
            metadata.get("source_case_id"),
            metadata.get("azure_di_case_id"),
            metadata.get("source_case_dir"),
        )
    )
    return "shield" in text.lower()


def _case_selected(
    case: Mapping[str, Any],
    *,
    include_samples: Sequence[str],
    exclude_samples: Sequence[str],
    include_outlier: bool,
) -> tuple[bool, str]:
    case_id = str(case.get("case_id") or "")
    includes = {str(item) for item in include_samples if item}
    excludes = {str(item) for item in exclude_samples if item}
    if includes and case_id not in includes:
        return False, "not_in_include_sample_filter"
    if case_id in excludes:
        return False, "excluded_by_exclude_sample_filter"
    if _is_outlier_case(case) and not include_outlier and case_id not in includes:
        return False, "outlier_excluded_by_default"
    return True, "included"


def _sample_display_name(case: Mapping[str, Any]) -> str:
    metadata = case.get("metadata") or {}
    return str(metadata.get("source_case_id") or metadata.get("azure_di_case_id") or case.get("case_id"))


def _row_default_current_year(rows: Sequence[Mapping[str, Any]]) -> int | None:
    years = []
    for row in rows:
        for key in ("current_year", "prior_year"):
            parsed = _safe_int(row.get(key))
            if parsed is not None:
                years.append(parsed)
    return max(years) if years else None


def _row_order(row: Mapping[str, Any], fallback_index: int) -> int:
    provenance = row.get("provenance") or {}
    for key in ("row_index", "_original_case_index", "_original_global_index"):
        parsed = _safe_int(provenance.get(key) if key in provenance else row.get(key))
        if parsed is not None:
            return parsed
    return fallback_index


def _column_indexes(row: Mapping[str, Any]) -> list[int]:
    cells = (row.get("provenance") or {}).get("cells") or []
    indexes: list[int] = []
    for cell in cells:
        if not isinstance(cell, Mapping):
            continue
        content = str(cell.get("content") or "")
        if not any(char.isdigit() for char in content) and content.strip() not in {"-", "--"}:
            continue
        parsed = _safe_int(cell.get("column_index"))
        if parsed is not None and parsed > 0:
            indexes.append(parsed)
    return sorted(dict.fromkeys(indexes))


def _column_index(row: Mapping[str, Any], value_role: str) -> int | None:
    indexes = _column_indexes(row)
    if not indexes:
        return None
    has_prior = row.get("previous_value") is not None or row.get("value_previous_year") is not None
    if value_role == "prior" and has_prior:
        return indexes[-1]
    if has_prior and len(indexes) >= 2:
        return indexes[-2]
    return indexes[-1]


def _statement_title(family: str | None, statement_text: str) -> str | None:
    if family in MAIN_STATEMENT_TITLES:
        return MAIN_STATEMENT_TITLES[family]
    return clean_text(statement_text) or None


def _is_main_statement(family: str | None, statement_text: str) -> bool:
    normalized = normalize_label(statement_text)
    if family == "financial_position":
        return "statement of financial position" in normalized or "balance sheet" in normalized
    if family == "income_statement":
        return (
            "statement of comprehensive income" in normalized
            or "profit or loss" in normalized
            or "income statement" in normalized
        )
    if family == "cash_flow":
        return "statement of cash flow" in normalized or "statement of cash flows" in normalized
    if family == "changes_in_equity":
        return "statement of changes in equity" in normalized
    return False


def _is_notes_context(family: str | None, statement_text: str) -> bool:
    normalized = normalize_label(statement_text)
    if family == "notes" or "notes to the financial statements" in normalized:
        return True
    if family in MAIN_STATEMENT_FAMILIES:
        return False
    note_hints = (
        "amount due",
        "property plant",
        "taxation",
        "tax expense",
        "receivable",
        "payable",
        "director",
        "deposits",
    )
    return any(hint in normalized for hint in note_hints)


def _contains(label: str, *phrases: str) -> bool:
    return any(normalize_label(phrase) in label for phrase in phrases)


def classify_section_block(label: Any, statement_text: Any, family: str | None, *, is_main_statement: bool) -> str:
    normalized = normalize_label(label)
    statement = normalize_label(statement_text)
    if not normalized:
        return "unknown"
    if not is_main_statement and _is_notes_context(family, statement):
        if "tax" in statement or "tax" in normalized:
            return "notes_tax"
        if "receivable" in statement or "receivable" in normalized:
            return "notes_receivables"
        if "payable" in statement or "payable" in normalized or "amount due" in statement:
            return "notes_payables"
        if "property plant" in statement or "property plant" in normalized:
            return "notes_ppe"
        return "notes_detail"

    if family == "financial_position":
        if "equity and liabilities" in normalized:
            return "equity_and_liabilities"
        if "total assets" in normalized:
            return "assets"
        if _contains(normalized, "non-current assets", "non current assets", "property plant and equipment", "investments"):
            return "non_current_assets"
        if _contains(normalized, "current assets", "trade receivables", "other receivables", "receivables", "bank balances", "cash at bank", "cash and cash equivalents", "deposits"):
            return "current_assets"
        if _contains(normalized, "total equity", "share capital", "retained", "accumulated losses", "shareholders equity"):
            return "equity"
        if _contains(normalized, "non-current liabilities", "non current liabilities", "term loan", "deferred liabilities"):
            return "non_current_liabilities"
        if _contains(normalized, "current liabilities", "payables", "accruals", "amount due to", "taxation", "provision for taxation"):
            return "current_liabilities"
        if "liabilities" in normalized:
            return "liabilities"
        return "financial_position_other"

    if family == "income_statement":
        if _contains(normalized, "before taxation", "before tax"):
            return "profit_loss_before_tax"
        if "tax" in normalized or "taxation" in normalized:
            return "tax_expense"
        if _contains(normalized, "turnover", "sales", "revenue") and "cost of sales" not in normalized:
            return "revenue"
        if "cost of sales" in normalized:
            return "cost_of_sales"
        if "other income" in normalized or "rental received" in normalized:
            return "other_income"
        if _contains(normalized, "finance costs", "term loan interest", "interest expense", "bank overdraft interest"):
            return "finance_costs"
        if _contains(normalized, "admin", "administration", "operating costs", "operating expenses", "staff costs", "audit fee", "secretarial fee", "bank charges", "professional fees"):
            return "administrative_expenses"
        if _contains(normalized, "gross profit", "operating activities", "loss for the year", "profit for the year", "financial year", "comprehensive"):
            return "profit_loss"
        return "income_statement_other"

    if family == "cash_flow":
        if "operating activities" in normalized:
            return "cash_flow_operating"
        if "investing activities" in normalized or "property plant" in normalized:
            return "cash_flow_investing"
        if "financing activities" in normalized:
            return "cash_flow_financing"
        if "cash and cash equivalents" in normalized or "bank balances" in normalized:
            return "cash_flow_reconciliation"
        return "cash_flow_other"

    if family == "changes_in_equity":
        return "changes_in_equity"

    if "notes" in statement:
        return "notes_detail"
    return "unknown"


def classify_row_role(
    label: Any,
    row_type: Any,
    family: str | None,
    *,
    is_main_statement: bool,
    is_notes_context: bool = False,
) -> str:
    normalized = normalize_label(label)
    row_type_text = str(row_type or "")
    if row_type_text in {"heading", "metadata"}:
        return "heading"
    if not is_main_statement and is_notes_context:
        return "note_detail"
    if row_type_text == "subtotal_or_total" or normalized.startswith("total "):
        return "total"
    if normalized.startswith("net ") or _contains(normalized, "gross profit", "before tax", "before taxation"):
        return "subtotal"
    if "cash flows from" in normalized and "activities" in normalized:
        return "heading"
    if not normalized:
        return "unknown"
    return "component"


def _confidence(
    *,
    family: str | None,
    section_block: str,
    row_role: str,
    is_main_statement: bool,
    is_notes_context: bool,
    page: int | None,
    row_order: int | None,
) -> tuple[float, list[str]]:
    score = 0.35
    reasons: list[str] = []
    if family:
        score += 0.2
        reasons.append(f"statement_family:{family}")
    if is_main_statement:
        score += 0.25
        reasons.append("main_statement_context")
    if section_block != "unknown":
        score += 0.1
        reasons.append(f"section_block:{section_block}")
    if row_role in {"component", "subtotal", "total"}:
        score += 0.05
        reasons.append(f"row_role:{row_role}")
    if page is not None or row_order is not None:
        score += 0.05
        reasons.append("row_position_available")
    if is_notes_context:
        score = min(score, 0.55)
        reasons.append("notes_or_non_main_context_caps_confidence")
    if not is_main_statement and family not in {"cash_flow", "changes_in_equity"}:
        score = min(score, 0.55)
        reasons.append("not_main_statement_caps_confidence")
    if not family:
        score = min(score, 0.5)
        reasons.append("statement_family_missing_caps_confidence")
    if section_block == "unknown":
        score = min(score, 0.7)
        reasons.append("section_block_unknown_caps_confidence")
    return round(score, 4), reasons


def extract_row_contexts_for_case(
    *,
    sample_id: str,
    company_name: str,
    rows: Sequence[Mapping[str, Any]],
    default_current_year: int | None = None,
) -> list[dict[str, Any]]:
    """Return one enriched context record for each numeric PDF row-value observation."""
    current_year = default_current_year or _row_default_current_year(rows)
    contexts: list[dict[str, Any]] = []
    for fallback_index, row in enumerate(rows, start=1):
        if str(row.get("row_type") or "") not in NUMERIC_ROW_TYPES:
            continue
        statement_text = clean_text(row.get("statement_type") or row.get("statement_section")) or ""
        family = statement_family(statement_text)
        is_main = _is_main_statement(family, statement_text)
        is_notes = _is_notes_context(family, statement_text)
        section_block = classify_section_block(row.get("label") or row.get("extracted_label"), statement_text, family, is_main_statement=is_main)
        row_role = classify_row_role(
            row.get("label") or row.get("extracted_label"),
            row.get("row_type"),
            family,
            is_main_statement=is_main,
            is_notes_context=is_notes,
        )
        page = _safe_int(row.get("page_number") or row.get("pdf_page"))
        order = _row_order(row, fallback_index)
        confidence, reasons = _confidence(
            family=family,
            section_block=section_block,
            row_role=row_role,
            is_main_statement=is_main,
            is_notes_context=is_notes,
            page=page,
            row_order=order,
        )
        for row_value in pdf_row_values(
            sample_id=sample_id,
            company_name=company_name,
            row=row,
            fallback_index=fallback_index,
            default_current_year=current_year,
        ):
            contexts.append(
                {
                    "sample_id": sample_id,
                    "company_name": company_name,
                    "row_id": row_value.pdf_row_id,
                    "source_row_id": row_value.source_pdf_row_id,
                    "original_label": row_value.pdf_label,
                    "normalized_label": canonical_label(row_value.pdf_label),
                    "value": row_value.pdf_value,
                    "page": page,
                    "row_order": order,
                    "column_index": _column_index(row, row_value.value_role),
                    "period": {"value_role": row_value.value_role, "expected_year": row_value.expected_year},
                    "statement_family": family,
                    "statement_title": _statement_title(family, statement_text),
                    "section_block": section_block,
                    "subsection_block": section_block,
                    "parent_heading": clean_text(statement_text) or None,
                    "nearest_heading": clean_text(statement_text) or None,
                    "row_role": row_role,
                    "is_main_statement": is_main,
                    "is_notes_context": is_notes,
                    "is_total": row_role == "total",
                    "is_subtotal": row_role == "subtotal",
                    "is_component": row_role == "component",
                    "is_current_asset": section_block == "current_assets",
                    "is_noncurrent_asset": section_block == "non_current_assets",
                    "is_current_liability": section_block == "current_liabilities",
                    "is_noncurrent_liability": section_block == "non_current_liabilities",
                    "is_equity": section_block == "equity",
                    "is_cash_flow": family == "cash_flow",
                    "context_confidence": confidence,
                    "context_reasons": reasons,
                }
            )
    return contexts


def load_pdf_row_contexts(
    *,
    dataset_dir: str | Path,
    include_samples: Sequence[str] = (),
    exclude_samples: Sequence[str] = (),
    include_outlier: bool = False,
) -> dict[str, Any]:
    samples: list[dict[str, Any]] = []
    contexts: list[dict[str, Any]] = []
    for case in discover_golden_cases(dataset_dir):
        sample_id = str(case.get("case_id") or "")
        selected, reason = _case_selected(
            case,
            include_samples=include_samples,
            exclude_samples=exclude_samples,
            include_outlier=include_outlier,
        )
        if not selected:
            samples.append({"sample_id": sample_id, "status": "skipped", "reason": reason, "row_contexts": 0})
            continue
        rows, sources = load_normalized_extraction_rows(case)
        company_name = _sample_display_name(case)
        sample_contexts = extract_row_contexts_for_case(sample_id=sample_id, company_name=company_name, rows=rows)
        samples.append(
            {
                "sample_id": sample_id,
                "company_name": company_name,
                "status": "included",
                "reason": reason,
                "pdf_rows_found": len(rows),
                "row_contexts": len(sample_contexts),
                "normalized_extraction_sources": sources,
            }
        )
        contexts.extend(sample_contexts)
    return {"samples": samples, "contexts": contexts}


def row_context_index(contexts: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in contexts}


def summarize_row_contexts(contexts: Sequence[Mapping[str, Any]], samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    families = Counter(str(item.get("statement_family") or "unknown") for item in contexts)
    blocks = Counter(str(item.get("section_block") or "unknown") for item in contexts)
    roles = Counter(str(item.get("row_role") or "unknown") for item in contexts)
    high = sum(1 for item in contexts if float(item.get("context_confidence") or 0) >= 0.75)
    low = sum(1 for item in contexts if float(item.get("context_confidence") or 0) < 0.6)
    return {
        "feature": "18E-A",
        "total_row_contexts": len(contexts),
        "included_samples": sum(1 for item in samples if item.get("status") == "included"),
        "high_confidence_contexts": high,
        "low_confidence_contexts": low,
        "statement_family_counts": dict(sorted(families.items())),
        "section_block_counts": dict(sorted(blocks.items())),
        "row_role_counts": dict(sorted(roles.items())),
        "per_sample_summary": samples,
        "safety": SAFETY,
    }


def build_row_context_report(
    *,
    dataset_dir: str | Path,
    include_samples: Sequence[str] = (),
    exclude_samples: Sequence[str] = (),
    include_outlier: bool = False,
) -> dict[str, Any]:
    loaded = load_pdf_row_contexts(
        dataset_dir=dataset_dir,
        include_samples=include_samples,
        exclude_samples=exclude_samples,
        include_outlier=include_outlier,
    )
    return {
        "run_metadata": {
            "feature": "18E-A",
            "dataset_dir": str(dataset_dir),
            "include_samples": list(include_samples),
            "exclude_samples": list(exclude_samples),
            "include_outlier": include_outlier,
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": summarize_row_contexts(loaded["contexts"], loaded["samples"]),
        "row_contexts": loaded["contexts"],
    }


def render_row_context_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF Row Context Extraction - Feature #18E-A",
        "",
        f"- Total row contexts: {summary.get('total_row_contexts', 0)}",
        f"- High-confidence contexts: {summary.get('high_confidence_contexts', 0)}",
        f"- Low-confidence contexts: {summary.get('low_confidence_contexts', 0)}",
        "",
        "## Statement Families",
        "",
    ]
    for family, count in (summary.get("statement_family_counts") or {}).items():
        lines.append(f"- {family}: {count}")
    lines.extend(["", "## Section Blocks", ""])
    for block, count in (summary.get("section_block_counts") or {}).items():
        lines.append(f"- {block}: {count}")
    lines.append("")
    return "\n".join(lines)
