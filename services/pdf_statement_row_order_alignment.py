"""Statement row-order alignment evidence for Feature #18E-B-2."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from services.pdf_xbrl_deterministic_alignment import canonical_label, concept_label, normalize_label


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
    "safe_for_auto_apply": False,
}

GENERIC_LABELS = {"amount", "balance", "current", "less", "net", "other", "subtotal", "total"}
LOW_ROW_ORDER_CONFIDENCE_THRESHOLD = 0.7

EXACT_CASH_FLOW_TOTAL_LABELS = {
    "cash flows from operating activities",
    "net cash from operating activities",
    "net cash used in operating activities",
    "cash from operating activities",
    "cash used in operating activities",
    "cash flows from investing activities",
    "net cash from investing activities",
    "net cash used in investing activities",
    "cash flows from financing activities",
    "net cash from financing activities",
    "net cash used in financing activities",
}

STABLE_ADMIN_EXPENSE_TOTAL_LABELS = {
    "administrative expenses",
    "administration expenses",
    "total administrative expenses",
    "total operating expenses",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _context_value(context: Mapping[str, Any], key: str) -> Any:
    if key in context:
        return context.get(key)
    row_context = context.get("row_context")
    if isinstance(row_context, Mapping):
        return row_context.get(key)
    return None


def _row_id_base(row_id: Any) -> str:
    text = str(row_id or "")
    return re.sub(r":(?:current|prior|previous|comparative)$", "", text)


def _row_id(context: Mapping[str, Any]) -> str:
    return str(context.get("row_id") or context.get("pdf_row_id") or "")


def _source_row_id(context: Mapping[str, Any]) -> str:
    return str(context.get("source_row_id") or _row_id_base(_row_id(context)))


def _label(context: Mapping[str, Any]) -> str:
    return canonical_label(context.get("normalized_label") or context.get("original_label") or context.get("pdf_label"))


def _raw_label(context: Mapping[str, Any]) -> str:
    return normalize_label(context.get("original_label") or context.get("pdf_label") or context.get("normalized_label"))


def _contains(value: str, *phrases: str) -> bool:
    return any(normalize_label(phrase) in value for phrase in phrases)


def _neighbor_label(row: Mapping[str, Any] | None) -> str | None:
    if not row:
        return None
    return row.get("normalized_label") or row.get("original_label") or row.get("pdf_label")


def _base_contexts(row_contexts: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    by_base: dict[tuple[str, str], dict[str, Any]] = {}
    row_ids: dict[str, list[str]] = defaultdict(list)
    for context in row_contexts:
        sample_id = str(context.get("sample_id") or "")
        base_id = _source_row_id(context)
        if not sample_id or not base_id:
            continue
        key = (sample_id, base_id)
        row_ids[f"{sample_id}|{base_id}"].append(_row_id(context))
        current = by_base.get(key)
        if current is None or str(_row_id(context)).endswith(":current"):
            by_base[key] = dict(context)
    return list(by_base.values()), row_ids


def _qname_for_label_and_neighbors(
    *,
    family: str | None,
    section: str | None,
    row_role: str | None,
    label: str,
    raw_label: str,
    previous_label: str,
    next_label: str,
) -> tuple[str | None, str | None, str, float, list[str]]:
    reasons = []
    text = f"{label} {raw_label}"
    neighbors = f"{previous_label} {next_label}"
    if previous_label:
        reasons.append(f"previous_label:{previous_label}")
    if next_label:
        reasons.append(f"next_label:{next_label}")

    if family == "income_statement":
        if _contains(text, "tax expense", "taxation", "income tax") and _contains(previous_label, "before tax", "before taxation"):
            return (
                "ifrs-smes:IncomeTaxExpenseContinuingOperations",
                "tax_expense",
                "after_profit_loss_before_tax",
                0.86,
                reasons + ["tax_after_profit_loss_before_tax"],
            )
        if _contains(text, "profit for the financial year", "loss for the financial year", "profit for the year", "loss for the year") and _contains(neighbors, "tax"):
            return "ifrs-smes:ProfitLoss", "profit_loss", "final_profit_loss_after_tax", 0.84, reasons + ["profit_loss_after_tax_line"]
        if _contains(text, "comprehensive income", "comprehensive loss"):
            return "ifrs-smes:ComprehensiveIncome", "comprehensive_income", "final_comprehensive_income_line", 0.82, reasons
        if _contains(text, "profit loss from operating activities", "loss from operating activities", "operating profit"):
            return "ssmt-mpers:ProfitLossFromOperatingActivities", "operating_profit_loss", "operating_result_subtotal", 0.72, reasons
        if section == "administrative_expenses" and _contains(text, "operating expenses", "other operating expenses", "other operating costs", "bank charges", "secretarial fee", "accounting fee", "payroll fee", "insurance", "rental of office"):
            return "ifrs-smes:AdministrativeExpense", "operating_expense", "administrative_expense_component", 0.68, reasons

    if family == "financial_position":
        if section == "current_assets" and _contains(text, "receivable", "deposits"):
            return "ifrs-smes:TradeAndOtherCurrentReceivables", "receivables", "current_asset_component", 0.72, reasons
        if section == "current_liabilities" and _contains(text, "payable", "accrual"):
            qname = "ssmt-mpers:CurrentNontradeAccruals" if "accrual" in text else "ifrs-smes:TradeAndOtherCurrentPayables"
            return qname, "payables", "current_liability_component", 0.72, reasons
        if section == "current_liabilities" and _contains(text, "tax", "taxation"):
            return "ifrs-smes:CurrentTaxLiabilitiesCurrent", "tax_liability", "current_tax_liability", 0.72, reasons
        if section == "equity" and _contains(text, "share capital"):
            return "ifrs-smes:IssuedCapital", "equity", "equity_component", 0.78, reasons
        if section == "equity" and _contains(text, "retained", "accumulated loss"):
            return "ifrs-smes:RetainedEarnings", "equity", "equity_component", 0.78, reasons
        if row_role in {"total", "subtotal"} and _contains(text, "total equity and liabilities", "equity and liabilities"):
            return "ifrs-smes:EquityAndLiabilities", "equity_liabilities_total", "sfp_final_total", 0.78, reasons

    if family == "cash_flow":
        if _contains(text, "cash and cash equivalents at beginning", "cash and cash equivalents at end", "bank balances"):
            return "ifrs-smes:CashAndCashEquivalents", "cash_equivalents", "cash_reconciliation_position", 0.78, reasons + ["cash_flow_reconciliation_not_balance_sheet_cash"]
        if section == "cash_flow_operating" and _contains(text, "operating activities", "cash from operating", "cash used in operating"):
            return "ifrs-smes:CashFlowsFromUsedInOperatingActivities", "cash_flow_operating", "cash_flow_operating_total", 0.78, reasons
        if section == "cash_flow_investing" and _contains(text, "investing activities"):
            return "ifrs-smes:CashFlowsFromUsedInInvestingActivities", "cash_flow_investing", "cash_flow_investing_total", 0.78, reasons
        if section == "cash_flow_financing" and _contains(text, "financing activities"):
            return "ifrs-smes:CashFlowsFromUsedInFinancingActivities", "cash_flow_financing", "cash_flow_financing_total", 0.78, reasons
        if section == "cash_flow_investing" and _contains(text, "property plant and equipment"):
            return "ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "cash_flow_investing", "ppe_purchase_investing", 0.72, reasons
        if section == "cash_flow_financing" and _contains(text, "repayment", "term loan", "borrowings"):
            return "ifrs-smes:RepaymentsOfBorrowingsClassifiedAsFinancingActivities", "cash_flow_financing", "borrowing_repayment_financing", 0.7, reasons

    if family == "changes_in_equity":
        if _contains(text, "share capital"):
            return "ifrs-smes:IssuedCapital", "equity", "equity_column_or_row", 0.7, reasons
        if _contains(text, "retained", "accumulated loss"):
            return "ifrs-smes:RetainedEarnings", "equity", "equity_column_or_row", 0.7, reasons
        if _contains(text, "profit", "loss") and _contains(text, "year"):
            return "ifrs-smes:ProfitLoss", "profit_loss", "equity_profit_loss_movement", 0.66, reasons
        if _contains(text, "comprehensive income", "comprehensive loss", "comprehensive profit"):
            return "ifrs-smes:ComprehensiveIncome", "comprehensive_income", "equity_comprehensive_income_movement", 0.66, reasons
        if _contains(text, "balance at beginning", "balance at end", "at beginning and end"):
            return "ifrs-smes:Equity", "equity_total", "equity_balance_line", 0.58, reasons + ["generic_equity_balance_requires_review"]

    return None, None, "unclassified", 0.0, reasons


def build_statement_row_order_alignments(row_contexts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    base_rows, row_ids_by_base = _base_contexts(row_contexts)
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in base_rows:
        grouped[
            (
                str(row.get("sample_id") or ""),
                str(row.get("statement_family") or "unknown"),
                str(row.get("statement_title") or ""),
            )
        ].append(row)

    alignments: list[dict[str, Any]] = []
    for (_sample, _family, _title), rows in grouped.items():
        ordered = sorted(rows, key=lambda item: (_safe_int(item.get("row_order")) or 0, _source_row_id(item)))
        for index, row in enumerate(ordered):
            previous = ordered[index - 1] if index else None
            next_row = ordered[index + 1] if index + 1 < len(ordered) else None
            family = row.get("statement_family")
            section = row.get("section_block")
            row_role = row.get("row_role")
            previous_label = normalize_label(_neighbor_label(previous))
            next_label = normalize_label(_neighbor_label(next_row))
            qname, concept_family, position, confidence, reasons = _qname_for_label_and_neighbors(
                family=family,
                section=section,
                row_role=row_role,
                label=_label(row),
                raw_label=_raw_label(row),
                previous_label=previous_label,
                next_label=next_label,
            )
            sample_id = str(row.get("sample_id") or "")
            base_id = _source_row_id(row)
            row_ids = sorted(dict.fromkeys(row_ids_by_base.get(f"{sample_id}|{base_id}") or [_row_id(row)]))
            for row_id in row_ids:
                alignments.append(
                    {
                        "alignment_id": f"18E-B2-row-order-{sample_id}-{row_id}".replace(":", "-"),
                        "sample_id": sample_id,
                        "row_id": row_id,
                        "source_row_id": base_id,
                        "statement_family": family,
                        "section_block": section,
                        "row_order": row.get("row_order"),
                        "previous_label": _neighbor_label(previous),
                        "next_label": _neighbor_label(next_row),
                        "canonical_position": position,
                        "expected_role": row_role,
                        "expected_concept_family": concept_family,
                        "expected_qname": qname,
                        "expected_concept_label": concept_label(qname) if qname else None,
                        "row_order_confidence": confidence,
                        "row_order_reasons": reasons,
                        "safe_for_auto_apply": False,
                        "requires_human_review": True,
                    }
                )
    return sorted(alignments, key=lambda item: (str(item.get("sample_id")), str(item.get("row_id"))))


def row_order_alignment_index(alignments: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in alignments}


def row_order_candidate_for_context(
    context: Mapping[str, Any] | None,
    alignment: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not context or not alignment or not alignment.get("expected_qname"):
        return None
    label = canonical_label(context.get("normalized_label") or context.get("original_label") or context.get("pdf_label"))
    row_role = _context_value(context, "row_role")
    family = _context_value(context, "statement_family")
    section = _context_value(context, "section_block")
    confidence = float(alignment.get("row_order_confidence") or 0.0)
    expected_qname = str(alignment.get("expected_qname") or "")
    previous_label = normalize_label(alignment.get("previous_label"))
    next_label = normalize_label(alignment.get("next_label"))
    blocking_reasons: list[str] = ["row_order_candidate_requires_review"]
    if confidence < LOW_ROW_ORDER_CONFIDENCE_THRESHOLD:
        blocking_reasons.append("row_order_confidence_below_hotfix_threshold")
    if (
        bool(_context_value(context, "is_notes_context"))
        or family == "notes"
        or row_role == "note_detail"
        or str(section or "").startswith("notes_")
    ):
        blocking_reasons.append("note_detail_row_order_blocked")
    if label in GENERIC_LABELS and (not previous_label or not next_label):
        blocking_reasons.append("generic_label_without_previous_next_anchors")
    if not previous_label and not next_label and alignment.get("canonical_position") not in {"cash_reconciliation_position"}:
        blocking_reasons.append("missing_previous_next_row_order_anchors")
    if expected_qname == "ifrs-smes:AdministrativeExpense" and (
        row_role not in {"total", "subtotal"} or label not in STABLE_ADMIN_EXPENSE_TOTAL_LABELS
    ):
        blocking_reasons.append("administrative_expense_component_row_order_blocked")
    if expected_qname == "ssmt-mpers:ProfitLossFromOperatingActivities" and row_role not in {"total", "subtotal"}:
        blocking_reasons.append("operating_result_row_order_requires_total_or_subtotal")
    if expected_qname in {
        "ifrs-smes:CashFlowsFromUsedInOperatingActivities",
        "ifrs-smes:CashFlowsFromUsedInInvestingActivities",
        "ifrs-smes:CashFlowsFromUsedInFinancingActivities",
    } and label not in EXACT_CASH_FLOW_TOTAL_LABELS:
        blocking_reasons.append("cash_flow_total_requires_exact_total_label")
    if expected_qname == "ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities" and not (
        label.startswith("purchase of property plant and equipment")
        or label.startswith("purchase of property plant")
        or label.startswith("acquisition of property plant")
    ):
        blocking_reasons.append("cash_flow_ppe_purchase_requires_purchase_or_acquisition_label")
    if expected_qname == "ifrs-smes:ComprehensiveIncome" and label == "comprehensive profit for the year":
        blocking_reasons.append("unstable_comprehensive_profit_year_row_order_blocked")

    blocking_reasons = sorted(dict.fromkeys(blocking_reasons))
    hard_blocks = [reason for reason in blocking_reasons if reason != "row_order_candidate_requires_review"]
    return {
        "matched_rule_id": f"18E-B2-row-order-{alignment.get('alignment_id')}",
        "row_order_alignment_id": alignment.get("alignment_id"),
        "target_qname": alignment.get("expected_qname"),
        "target_concept_label": alignment.get("expected_concept_label"),
        "concept_family": alignment.get("expected_concept_family"),
        "confidence_score": round(min(0.62, max(0.42, confidence)), 4),
        "confidence_bucket": "no_match" if hard_blocks else "review_required",
        "candidate_blocked": bool(hard_blocks),
        "match_reasons": ["row_order_alignment_candidate", *(alignment.get("row_order_reasons") or [])],
        "blocking_reasons": blocking_reasons,
        "row_order_alignment": dict(alignment),
    }


def build_statement_row_order_alignment_report(row_contexts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    alignments = build_statement_row_order_alignments(row_contexts)
    with_qname = [item for item in alignments if item.get("expected_qname")]
    usage = Counter(str(item.get("expected_qname")) for item in with_qname)
    by_family = Counter(str(item.get("statement_family") or "unknown") for item in alignments)
    return {
        "run_metadata": {
            "feature": "18E-B-2",
            "generated_at": utc_now(),
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": {
            "row_contexts_considered": len(row_contexts),
            "row_order_alignments": len(alignments),
            "alignments_with_expected_qname": len(with_qname),
            "alignment_count_by_statement_family": dict(sorted(by_family.items())),
            "top_expected_qnames": [
                {"expected_qname": key, "count": count}
                for key, count in usage.most_common(30)
            ],
            "safe_for_auto_apply": False,
            "requires_human_review": True,
        },
        "row_order_alignments": alignments,
    }


def render_statement_row_order_alignment_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Statement Row-Order Alignment - Feature #18E-B-2",
        "",
        f"- Row contexts considered: {summary.get('row_contexts_considered', 0)}",
        f"- Row-order alignments: {summary.get('row_order_alignments', 0)}",
        f"- Alignments with expected QName: {summary.get('alignments_with_expected_qname', 0)}",
        f"- Safe for auto-apply: {summary.get('safe_for_auto_apply')}",
        "",
        "## Top Expected QNames",
        "",
        "| QName | Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("top_expected_qnames") or []:
        lines.append(f"| {item.get('expected_qname')} | {item.get('count')} |")
    lines.append("")
    return "\n".join(lines)
