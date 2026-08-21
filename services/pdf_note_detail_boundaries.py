"""Conservative note-detail boundary detection for Feature #18E-B-3."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.pdf_row_context_extraction import load_pdf_row_contexts
from services.pdf_xbrl_deterministic_alignment import clean_text, normalize_label


SAFETY = {
    "external_llm_called": False,
    "external_provider_called": False,
    "azure_di_live_call_made": False,
    "database_mutated": False,
    "production_behavior_changed": False,
    "production_mapper_integrated": False,
    "api_changed": False,
    "ui_changed": False,
    "ai_suggestion_table_written": False,
    "auto_applied": False,
    "auto_accept_recommended": False,
    "auto_reject_recommended": False,
    "confirmed_tag_id_mutated": False,
    "confirmed_tag_id_automation_recommended": False,
    "xbrl_generated": False,
    "arelle_run": False,
}

MAIN_STATEMENT_QNAMES = {
    "ifrs-smes:AdministrativeExpense",
    "ifrs-smes:Assets",
    "ifrs-smes:Borrowings",
    "ifrs-smes:CashAndCashEquivalents",
    "ifrs-smes:ComprehensiveIncome",
    "ifrs-smes:CostOfSales",
    "ifrs-smes:CurrentAssets",
    "ifrs-smes:CurrentLiabilities",
    "ifrs-smes:CurrentTaxAssetsCurrent",
    "ifrs-smes:CurrentTaxLiabilitiesCurrent",
    "ifrs-smes:Equity",
    "ifrs-smes:EquityAndLiabilities",
    "ifrs-smes:FinanceCosts",
    "ifrs-smes:GrossProfit",
    "ifrs-smes:IncomeTaxExpenseContinuingOperations",
    "ifrs-smes:IssuedCapital",
    "ifrs-smes:Liabilities",
    "ifrs-smes:NoncurrentAssets",
    "ifrs-smes:NoncurrentLiabilities",
    "ifrs-smes:OtherExpenseByFunction",
    "ifrs-smes:OtherIncome",
    "ifrs-smes:ProfitLoss",
    "ifrs-smes:ProfitLossBeforeTax",
    "ifrs-smes:PropertyPlantAndEquipment",
    "ifrs-smes:RetainedEarnings",
    "ifrs-smes:Revenue",
    "ifrs-smes:TradeAndOtherCurrentPayables",
    "ifrs-smes:TradeAndOtherCurrentReceivables",
    "ssmt:CashAndBankBalances",
}

PPE_BALANCE_QNAMES = {"ifrs-smes:PropertyPlantAndEquipment"}
TAX_EXPENSE_QNAMES = {"ifrs-smes:IncomeTaxExpenseContinuingOperations"}
RECEIVABLE_PAYABLE_QNAMES = {
    "ifrs-smes:TradeAndOtherCurrentReceivables",
    "ifrs-smes:TradeAndOtherCurrentPayables",
    "ssmt-mpers:OtherCurrentPayablesDueToRelatedParties",
    "ssmt-mpers:OtherCurrentReceivablesDueFromRelatedParties",
}
BORROWING_QNAMES = {"ifrs-smes:Borrowings"}
BALANCE_SHEET_CASH_QNAMES = {"ssmt:CashAndBankBalances"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unique(values: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value not in (None, "")))


def _context(record_or_context: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not record_or_context:
        return {}
    row_context = record_or_context.get("row_context")
    if isinstance(row_context, Mapping):
        return row_context
    return record_or_context


def _label_text(record_or_context: Mapping[str, Any] | None) -> str:
    context = _context(record_or_context)
    values = [
        context.get("original_label"),
        context.get("normalized_label"),
        context.get("nearest_heading"),
        context.get("parent_heading"),
        record_or_context.get("pdf_label") if record_or_context else None,
        record_or_context.get("normalized_label") if record_or_context else None,
    ]
    return normalize_label(" ".join(str(value or "") for value in values))


def _contains_any(text: str, phrases: Sequence[str]) -> bool:
    return any(normalize_label(phrase) in text for phrase in phrases)


def _is_notes_context(context: Mapping[str, Any]) -> bool:
    section = str(context.get("section_block") or "")
    family = str(context.get("statement_family") or "")
    row_role = str(context.get("row_role") or "")
    return bool(
        context.get("is_notes_context")
        or family == "notes"
        or row_role == "note_detail"
        or section.startswith("notes")
    )


def _is_main_statement(context: Mapping[str, Any]) -> bool:
    return bool(context.get("is_main_statement")) and not _is_notes_context(context)


def classify_note_detail_boundary(record_or_context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Classify a row's note boundary using existing row-context evidence."""
    context = _context(record_or_context)
    label = _label_text(record_or_context)
    section = str(context.get("section_block") or "")
    family = str(context.get("statement_family") or "")
    row_role = str(context.get("row_role") or "")
    reasons: list[str] = []

    is_notes = _is_notes_context(context)
    is_main = _is_main_statement(context)
    is_total = bool(context.get("is_total")) or row_role == "total" or label.startswith("total ")

    if is_main:
        boundary_type = "main_statement_row"
        reasons.append("main_statement_context")
    elif is_notes:
        reasons.append("notes_context")
        if section == "notes_ppe" or _contains_any(
            label,
            (
                "cost",
                "accumulated depreciation",
                "depreciation",
                "addition",
                "additions",
                "disposal",
                "carrying amount",
                "written off",
                "at beginning",
                "at end",
                "current year",
                "prior year",
            ),
        ):
            boundary_type = "note_movement_row"
            reasons.append("note_movement_terms")
        elif section == "notes_tax" or _contains_any(
            label,
            (
                "expenses not deductible",
                "effect of",
                "over provision",
                "under provision",
                "unabsorbed losses",
                "current charges",
                "deferred tax",
                "tax reconciliation",
                "provision based",
                "charges for the year",
            ),
        ):
            boundary_type = "note_reconciliation_row"
            reasons.append("tax_reconciliation_terms")
        elif _contains_any(label, ("receivable", "payable", "amount due", "borrow", "term loan", "cash and bank", "cash at bank")):
            boundary_type = "note_summary_row" if is_total else "note_detail_row"
            reasons.append("note_breakdown_terms")
        elif is_total:
            boundary_type = "note_summary_row"
            reasons.append("note_total_or_summary_label")
        else:
            boundary_type = "note_detail_row"
            reasons.append("note_detail_default")
    else:
        boundary_type = "unknown"
        reasons.append("boundary_unknown")

    is_note_detail = boundary_type == "note_detail_row"
    is_note_movement = boundary_type == "note_movement_row"
    is_note_reconciliation = boundary_type == "note_reconciliation_row"
    is_note_summary = boundary_type == "note_summary_row"
    can_map_main = is_main
    can_support_main = is_note_summary and not (is_note_movement or is_note_reconciliation)
    blocking = []
    if not can_map_main:
        blocking.append("not_main_statement_row")
    if is_note_detail:
        blocking.append("note_detail_row_support_only")
    if is_note_movement:
        blocking.append("note_movement_row_support_only")
    if is_note_reconciliation:
        blocking.append("note_reconciliation_row_support_only")
    if is_note_summary:
        blocking.append("note_summary_row_support_only")

    if is_main:
        confidence = 0.9
    elif is_notes:
        confidence = 0.85
    else:
        confidence = 0.55

    return {
        "row_id": context.get("row_id") or (record_or_context or {}).get("pdf_row_id"),
        "sample_id": context.get("sample_id") or (record_or_context or {}).get("sample_id"),
        "note_boundary_type": boundary_type,
        "is_main_statement_row": is_main,
        "is_note_summary_row": is_note_summary,
        "is_note_detail_row": is_note_detail,
        "is_note_movement_row": is_note_movement,
        "is_note_reconciliation_row": is_note_reconciliation,
        "can_map_to_main_statement_concept": can_map_main,
        "can_support_main_statement_mapping": can_support_main,
        "boundary_confidence": confidence,
        "boundary_reasons": _unique(reasons),
        "blocking_reasons": _unique(blocking),
        "statement_family": family,
        "section_block": section,
        "row_role": row_role,
        "normalized_label": context.get("normalized_label") or (record_or_context or {}).get("normalized_label"),
        "original_label": context.get("original_label") or (record_or_context or {}).get("pdf_label"),
    }


def boundary_blocks_qname(boundary: Mapping[str, Any] | None, qname: Any) -> tuple[bool, list[str]]:
    """Return whether a boundary blocks mapping the row to a qname."""
    target = str(qname or "")
    if not boundary or not target:
        return False, []

    boundary_type = str(boundary.get("note_boundary_type") or "unknown")
    reasons: list[str] = []
    if boundary_type in {"note_detail_row", "note_movement_row", "note_reconciliation_row"}:
        if target in MAIN_STATEMENT_QNAMES:
            reasons.append(f"{boundary_type}_blocks_main_statement_concept")
    if boundary_type == "note_summary_row" and not boundary.get("can_support_main_statement_mapping"):
        if target in MAIN_STATEMENT_QNAMES:
            reasons.append("note_summary_row_blocks_main_statement_concept")
    if boundary.get("is_note_movement_row") and target in PPE_BALANCE_QNAMES:
        reasons.append("ppe_movement_note_row_blocks_ppe_balance_concept")
    if boundary.get("is_note_reconciliation_row") and target in TAX_EXPENSE_QNAMES:
        reasons.append("tax_reconciliation_note_row_blocks_profit_loss_tax_expense")
    if boundary_type in {"note_detail_row", "note_summary_row"} and target in RECEIVABLE_PAYABLE_QNAMES:
        reasons.append("receivables_payables_note_breakdown_blocks_main_aggregate")
    if boundary_type in {"note_detail_row", "note_summary_row"} and target in BORROWING_QNAMES:
        reasons.append("borrowing_note_detail_blocks_balance_sheet_borrowings")

    if str(boundary.get("statement_family") or "") == "cash_flow" and target in BALANCE_SHEET_CASH_QNAMES:
        reasons.append("cash_flow_row_blocks_balance_sheet_cash_bank")

    return bool(reasons), _unique(reasons)


def boundary_summary(boundary: Mapping[str, Any] | None) -> dict[str, Any]:
    if not boundary:
        return {}
    keys = (
        "note_boundary_type",
        "is_main_statement_row",
        "is_note_summary_row",
        "is_note_detail_row",
        "is_note_movement_row",
        "is_note_reconciliation_row",
        "can_map_to_main_statement_concept",
        "can_support_main_statement_mapping",
        "boundary_confidence",
        "boundary_reasons",
        "blocking_reasons",
    )
    return {key: boundary.get(key) for key in keys}


def classify_note_detail_boundaries(records_or_contexts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [classify_note_detail_boundary(item) for item in records_or_contexts]


def summarize_note_detail_boundaries(boundaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    type_counts = Counter(str(item.get("note_boundary_type") or "unknown") for item in boundaries)
    blocked_main = sum(1 for item in boundaries if not item.get("can_map_to_main_statement_concept"))
    return {
        "feature": "18E-B-3",
        "total_boundaries": len(boundaries),
        "boundary_type_counts": dict(sorted(type_counts.items())),
        "main_statement_rows": type_counts.get("main_statement_row", 0),
        "note_summary_rows": type_counts.get("note_summary_row", 0),
        "note_detail_rows": type_counts.get("note_detail_row", 0),
        "note_movement_rows": type_counts.get("note_movement_row", 0),
        "note_reconciliation_rows": type_counts.get("note_reconciliation_row", 0),
        "rows_not_safe_for_main_statement_mapping": blocked_main,
        "safe_for_auto_apply_count": 0,
        "requires_human_review_count": len(boundaries),
        "safety": SAFETY,
    }


def build_note_detail_boundary_report(
    *,
    dataset_dir: str | Path | None = None,
    records_or_contexts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    if records_or_contexts:
        samples: list[dict[str, Any]] = []
        boundaries = classify_note_detail_boundaries(records_or_contexts)
    elif dataset_dir is not None:
        loaded = load_pdf_row_contexts(dataset_dir=dataset_dir)
        samples = list(loaded.get("samples") or [])
        boundaries = classify_note_detail_boundaries(loaded.get("contexts") or [])
    else:
        samples = []
        boundaries = []
    return {
        "run_metadata": {
            "feature": "18E-B-3",
            "generated_at": utc_now(),
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": summarize_note_detail_boundaries(boundaries),
        "samples": samples,
        "note_detail_boundaries": boundaries,
    }


def render_note_detail_boundary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF Note Detail Boundaries - Feature #18E-B-3",
        "",
        f"- Total boundaries: {summary.get('total_boundaries', 0)}",
        f"- Main statement rows: {summary.get('main_statement_rows', 0)}",
        f"- Note summary rows: {summary.get('note_summary_rows', 0)}",
        f"- Note detail rows: {summary.get('note_detail_rows', 0)}",
        f"- Note movement rows: {summary.get('note_movement_rows', 0)}",
        f"- Note reconciliation rows: {summary.get('note_reconciliation_rows', 0)}",
        f"- Rows not safe for main-statement mapping: {summary.get('rows_not_safe_for_main_statement_mapping', 0)}",
        f"- Safe for auto-apply: {summary.get('safe_for_auto_apply_count', 0)}",
        "",
        "## Boundary Types",
        "",
        "| Type | Count |",
        "| --- | ---: |",
    ]
    for key, count in (summary.get("boundary_type_counts") or {}).items():
        lines.append(f"| {clean_text(key)} | {count} |")
    lines.append("")
    return "\n".join(lines)
