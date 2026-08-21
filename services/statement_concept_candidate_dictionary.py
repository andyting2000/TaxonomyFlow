"""Statement-specific concept candidate dictionary for Feature #18E-B-2.

The dictionary produces candidate evidence only. It does not create final
confirmed mappings and nothing here is safe for auto-apply.
"""

from __future__ import annotations

from collections import Counter
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

CONFIDENCE_RANK = {
    "dictionary_strong": 0,
    "dictionary_usable": 1,
    "dictionary_review_required": 2,
}

UNKNOWN_SECTION_BLOCKS = {None, "", "unknown", "blank", "unclassified"}
LOW_CONTEXT_CONFIDENCE_THRESHOLD = 0.7

EXACT_CASH_FLOW_TOTAL_LABELS = {
    "cash flows from operating activities",
    "net cash from operating activities",
    "net cash used in operating activities",
    "cash from operating activities",
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
}

STABLE_COMPREHENSIVE_EQUITY_LABELS = {
    "total comprehensive income",
    "total comprehensive loss",
    "comprehensive loss for the period",
}


def _entry(
    entry_id: str,
    *,
    statement_family: str | None,
    section_blocks: Sequence[str],
    labels: Sequence[str],
    preferred_qname: str,
    concept_family: str,
    confidence_tier: str = "dictionary_review_required",
    row_roles: Sequence[str] = (),
    candidate_qnames: Sequence[str] = (),
    required_context_conditions: Mapping[str, Any] | None = None,
    blocking_conditions: Sequence[str] = (),
    evidence_source: str = "manual_seed",
    notes: str = "",
) -> dict[str, Any]:
    aliases = sorted({canonical_label(item) for item in labels if canonical_label(item)})
    return {
        "dictionary_entry_id": entry_id,
        "statement_family": statement_family,
        "section_blocks": list(section_blocks),
        "row_roles": list(row_roles),
        "normalized_label_pattern": aliases[0] if aliases else "",
        "aliases": aliases,
        "candidate_qnames": list(candidate_qnames or [preferred_qname]),
        "preferred_qname": preferred_qname,
        "preferred_concept_label": concept_label(preferred_qname),
        "concept_family": concept_family,
        "required_context_conditions": dict(required_context_conditions or {}),
        "blocking_conditions": list(blocking_conditions),
        "confidence_tier": confidence_tier,
        "evidence_source": evidence_source,
        "notes": notes,
    }


DICTIONARY_ENTRIES: tuple[dict[str, Any], ...] = (
    _entry(
        "18E-B2-is-revenue",
        statement_family="income_statement",
        section_blocks=("revenue",),
        labels=("revenue", "turnover", "sales"),
        preferred_qname="ifrs-smes:Revenue",
        concept_family="revenue",
        confidence_tier="dictionary_strong",
        required_context_conditions={"is_main_statement": True},
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-is-cost-of-sales",
        statement_family="income_statement",
        section_blocks=("cost_of_sales",),
        labels=("cost of sales", "purchases"),
        preferred_qname="ifrs-smes:CostOfSales",
        concept_family="cost_of_sales",
        confidence_tier="dictionary_strong",
        required_context_conditions={"is_main_statement": True},
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-is-gross-profit",
        statement_family="income_statement",
        section_blocks=("profit_loss", "income_statement_other"),
        labels=("gross profit", "gross loss"),
        preferred_qname="ifrs-smes:GrossProfit",
        concept_family="gross_profit",
        confidence_tier="dictionary_strong",
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-is-other-income",
        statement_family="income_statement",
        section_blocks=("other_income", "income_statement_other"),
        labels=("other income", "rental income", "rental received", "interest income"),
        preferred_qname="ifrs-smes:OtherIncome",
        concept_family="other_income",
        confidence_tier="dictionary_usable",
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-is-administrative-expenses",
        statement_family="income_statement",
        section_blocks=("administrative_expenses",),
        labels=("administrative expenses", "administration expenses", "operating expenses", "other operating expenses", "other operating costs"),
        preferred_qname="ifrs-smes:AdministrativeExpense",
        concept_family="operating_expense",
        confidence_tier="dictionary_usable",
        candidate_qnames=("ifrs-smes:AdministrativeExpense", "ifrs-smes:OtherExpenseByFunction"),
        evidence_source="local_report",
        notes="Operating/admin expense labels vary by filer; review is required.",
    ),
    _entry(
        "18E-B2-is-finance-costs",
        statement_family="income_statement",
        section_blocks=("finance_costs", "administrative_expenses"),
        labels=("finance costs", "term loan interests", "interest expense", "bank overdraft interest"),
        preferred_qname="ifrs-smes:FinanceCosts",
        concept_family="finance_cost",
        confidence_tier="dictionary_usable",
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-is-profit-loss-before-tax",
        statement_family="income_statement",
        section_blocks=("profit_loss_before_tax", "profit_loss"),
        labels=("profit before tax", "loss before tax", "profit before taxation", "loss before taxation", "operating profit loss before tax"),
        preferred_qname="ifrs-smes:ProfitLossBeforeTax",
        concept_family="profit_loss_before_tax",
        confidence_tier="dictionary_strong",
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-is-tax-expense",
        statement_family="income_statement",
        section_blocks=("tax_expense", "profit_loss"),
        labels=("tax expense", "taxation", "income tax expense", "less taxation"),
        preferred_qname="ifrs-smes:IncomeTaxExpenseContinuingOperations",
        concept_family="tax_expense",
        confidence_tier="dictionary_usable",
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-note-tax-expense",
        statement_family=None,
        section_blocks=("notes_tax",),
        labels=("tax expense", "provision for taxation", "taxation", "charges for the year"),
        preferred_qname="ifrs-smes:IncomeTaxExpenseContinuingOperations",
        concept_family="tax_expense",
        confidence_tier="dictionary_review_required",
        required_context_conditions={"is_notes_context": True},
        blocking_conditions=("notes_context_requires_review",),
        evidence_source="local_report",
    ),
    _entry(
        "18E-B2-is-profit-loss-year",
        statement_family="income_statement",
        section_blocks=("profit_loss",),
        labels=("profit for the financial year", "loss for the financial year", "profit for the year", "loss for the year", "profit after tax", "loss after tax"),
        preferred_qname="ifrs-smes:ProfitLoss",
        concept_family="profit_loss",
        confidence_tier="dictionary_usable",
        row_roles=("total", "subtotal"),
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-is-comprehensive-income",
        statement_family="income_statement",
        section_blocks=("profit_loss",),
        labels=("total comprehensive income", "total comprehensive loss", "comprehensive income for the year", "comprehensive loss for the year"),
        preferred_qname="ifrs-smes:ComprehensiveIncome",
        concept_family="comprehensive_income",
        confidence_tier="dictionary_usable",
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-sfp-receivables",
        statement_family="financial_position",
        section_blocks=("current_assets",),
        labels=("trade and other receivables", "trade receivables", "other receivables"),
        preferred_qname="ifrs-smes:TradeAndOtherCurrentReceivables",
        concept_family="receivables",
        confidence_tier="dictionary_usable",
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-sfp-related-party-receivable",
        statement_family="financial_position",
        section_blocks=("current_assets",),
        labels=("amount due from director", "amount due from directors", "amount due from related parties", "due from related parties"),
        preferred_qname="ssmt-mpers:OtherCurrentReceivablesDueFromRelatedParties",
        concept_family="related_party_receivable",
        confidence_tier="dictionary_usable",
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-sfp-payables",
        statement_family="financial_position",
        section_blocks=("current_liabilities",),
        labels=("trade and other payables", "trade payables", "other payables", "payables and accruals"),
        preferred_qname="ifrs-smes:TradeAndOtherCurrentPayables",
        concept_family="payables",
        confidence_tier="dictionary_usable",
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-sfp-related-party-payable",
        statement_family="financial_position",
        section_blocks=("current_liabilities", "non_current_liabilities"),
        labels=("amount due to director", "amount due to directors", "amount due to related parties", "due to related parties"),
        preferred_qname="ssmt-mpers:OtherCurrentPayablesDueToRelatedParties",
        concept_family="related_party_payable",
        confidence_tier="dictionary_usable",
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-sfp-tax-recoverable",
        statement_family="financial_position",
        section_blocks=("current_assets",),
        labels=("tax recoverable", "tax refundable", "income tax recoverable"),
        preferred_qname="ifrs-smes:CurrentTaxAssetsCurrent",
        concept_family="tax_asset",
        confidence_tier="dictionary_review_required",
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-sfp-tax-payable",
        statement_family="financial_position",
        section_blocks=("current_liabilities",),
        labels=("tax payable", "provision for taxation", "income tax payable", "taxation"),
        preferred_qname="ifrs-smes:CurrentTaxLiabilitiesCurrent",
        concept_family="tax_liability",
        confidence_tier="dictionary_usable",
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-sfp-accruals",
        statement_family="financial_position",
        section_blocks=("current_liabilities",),
        labels=("accruals", "accrued expenses"),
        preferred_qname="ssmt-mpers:CurrentNontradeAccruals",
        concept_family="accruals",
        confidence_tier="dictionary_strong",
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-sfp-borrowings",
        statement_family="financial_position",
        section_blocks=("current_liabilities", "non_current_liabilities"),
        labels=("borrowings", "term loan", "term loans", "bank overdraft"),
        preferred_qname="ifrs-smes:Borrowings",
        concept_family="borrowings",
        confidence_tier="dictionary_review_required",
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-sfp-share-capital",
        statement_family="financial_position",
        section_blocks=("equity",),
        labels=("share capital", "issued capital", "contributed share capital"),
        preferred_qname="ifrs-smes:IssuedCapital",
        concept_family="equity",
        confidence_tier="dictionary_strong",
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-sfp-retained-earnings",
        statement_family="financial_position",
        section_blocks=("equity",),
        labels=("retained earnings", "retained profits", "accumulated losses", "accumulated loss"),
        preferred_qname="ifrs-smes:RetainedEarnings",
        concept_family="equity",
        confidence_tier="dictionary_strong",
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-sfp-total-equity",
        statement_family="financial_position",
        section_blocks=("equity",),
        labels=("total equity", "total shareholders equity", "shareholders equity"),
        preferred_qname="ifrs-smes:Equity",
        concept_family="equity_total",
        confidence_tier="dictionary_usable",
        row_roles=("total", "subtotal"),
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-sfp-total-assets",
        statement_family="financial_position",
        section_blocks=("assets", "financial_position_other"),
        labels=("total assets",),
        preferred_qname="ifrs-smes:Assets",
        concept_family="asset_total",
        confidence_tier="dictionary_usable",
        row_roles=("total", "subtotal"),
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-sfp-current-assets",
        statement_family="financial_position",
        section_blocks=("current_assets",),
        labels=("total current assets", "current assets"),
        preferred_qname="ifrs-smes:CurrentAssets",
        concept_family="asset_total",
        confidence_tier="dictionary_usable",
        row_roles=("total", "subtotal"),
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-sfp-current-liabilities",
        statement_family="financial_position",
        section_blocks=("current_liabilities",),
        labels=("total current liabilities", "current liabilities"),
        preferred_qname="ifrs-smes:CurrentLiabilities",
        concept_family="liability_total",
        confidence_tier="dictionary_usable",
        row_roles=("total", "subtotal"),
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-sfp-noncurrent-assets",
        statement_family="financial_position",
        section_blocks=("non_current_assets",),
        labels=("total non-current assets", "total non current assets", "non-current assets", "non current assets"),
        preferred_qname="ifrs-smes:NoncurrentAssets",
        concept_family="asset_total",
        confidence_tier="dictionary_usable",
        row_roles=("total", "subtotal"),
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-sfp-noncurrent-liabilities",
        statement_family="financial_position",
        section_blocks=("non_current_liabilities",),
        labels=("total non-current liabilities", "total non current liabilities", "non-current liabilities", "non current liabilities"),
        preferred_qname="ifrs-smes:NoncurrentLiabilities",
        concept_family="liability_total",
        confidence_tier="dictionary_usable",
        row_roles=("total", "subtotal"),
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-sfp-equity-liabilities",
        statement_family="financial_position",
        section_blocks=("equity_and_liabilities", "liabilities", "financial_position_other"),
        labels=("total equity and liabilities", "equity and liabilities", "capital deficiency and liabilities"),
        preferred_qname="ifrs-smes:EquityAndLiabilities",
        concept_family="equity_liabilities_total",
        confidence_tier="dictionary_usable",
        row_roles=("total", "subtotal"),
        evidence_source="rulebook",
    ),
    _entry(
        "18E-B2-cf-operating",
        statement_family="cash_flow",
        section_blocks=("cash_flow_operating",),
        labels=("cash flows from operating activities", "net cash from operating activities", "net cash used in operating activities", "cash from operating activities"),
        preferred_qname="ifrs-smes:CashFlowsFromUsedInOperatingActivities",
        concept_family="cash_flow_operating",
        confidence_tier="dictionary_usable",
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-cf-operations",
        statement_family="cash_flow",
        section_blocks=("cash_flow_operating",),
        labels=("net cash generated from operations", "net cash used in operations", "cash generated from operations", "cash used in operations"),
        preferred_qname="ssmt-mpers:CashFlowsFromUsedInOperations",
        concept_family="cash_flow_operations",
        confidence_tier="dictionary_review_required",
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-cf-investing",
        statement_family="cash_flow",
        section_blocks=("cash_flow_investing",),
        labels=("cash flows from investing activities", "net cash used in investing activities", "net cash from investing activities"),
        preferred_qname="ifrs-smes:CashFlowsFromUsedInInvestingActivities",
        concept_family="cash_flow_investing",
        confidence_tier="dictionary_usable",
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-cf-financing",
        statement_family="cash_flow",
        section_blocks=("cash_flow_financing",),
        labels=("cash flows from financing activities", "net cash from financing activities", "net cash used in financing activities"),
        preferred_qname="ifrs-smes:CashFlowsFromUsedInFinancingActivities",
        concept_family="cash_flow_financing",
        confidence_tier="dictionary_usable",
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-cf-ppe-purchase",
        statement_family="cash_flow",
        section_blocks=("cash_flow_investing",),
        labels=("purchase of property plant and equipment", "purchase of property, plant and equipment", "acquisition of property plant and equipment"),
        preferred_qname="ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        concept_family="cash_flow_investing",
        confidence_tier="dictionary_usable",
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-cf-borrowing-repayment",
        statement_family="cash_flow",
        section_blocks=("cash_flow_financing",),
        labels=("repayment of borrowings", "repayment of term loan", "term loan repayment"),
        preferred_qname="ifrs-smes:RepaymentsOfBorrowingsClassifiedAsFinancingActivities",
        concept_family="cash_flow_financing",
        confidence_tier="dictionary_usable",
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-cf-borrowing-drawdown",
        statement_family="cash_flow",
        section_blocks=("cash_flow_financing",),
        labels=("drawdown of borrowings", "drawdown of term loan", "proceeds from borrowings", "proceeds from term loan"),
        preferred_qname="ifrs-smes:ProceedsFromBorrowingsClassifiedAsFinancingActivities",
        concept_family="cash_flow_financing",
        confidence_tier="dictionary_usable",
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-cf-cash-begin-end",
        statement_family="cash_flow",
        section_blocks=("cash_flow_reconciliation",),
        labels=("cash and cash equivalents at beginning of year", "cash and cash equivalents at end of year", "cash and cash equivalents at beginning", "cash and cash equivalents at end", "bank balances"),
        preferred_qname="ifrs-smes:CashAndCashEquivalents",
        concept_family="cash_equivalents",
        confidence_tier="dictionary_usable",
        blocking_conditions=("cash_flow_cash_equivalents_requires_review",),
        evidence_source="observed_template",
    ),
    _entry(
        "18E-B2-equity-share-capital",
        statement_family="changes_in_equity",
        section_blocks=("changes_in_equity",),
        labels=("share capital", "issued capital"),
        preferred_qname="ifrs-smes:IssuedCapital",
        concept_family="equity",
        confidence_tier="dictionary_usable",
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-equity-retained-earnings",
        statement_family="changes_in_equity",
        section_blocks=("changes_in_equity",),
        labels=("retained earnings", "retained profits", "accumulated losses", "accumulated loss"),
        preferred_qname="ifrs-smes:RetainedEarnings",
        concept_family="equity",
        confidence_tier="dictionary_usable",
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-equity-profit-loss",
        statement_family="changes_in_equity",
        section_blocks=("changes_in_equity",),
        labels=("profit for the year", "loss for the year", "profit for the financial year", "loss for the financial year"),
        preferred_qname="ifrs-smes:ProfitLoss",
        concept_family="profit_loss",
        confidence_tier="dictionary_review_required",
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-equity-comprehensive-income",
        statement_family="changes_in_equity",
        section_blocks=("changes_in_equity",),
        labels=("total comprehensive income", "total comprehensive loss", "comprehensive profit for the year", "comprehensive loss for the period"),
        preferred_qname="ifrs-smes:ComprehensiveIncome",
        concept_family="comprehensive_income",
        confidence_tier="dictionary_review_required",
        evidence_source="taxonomy_label",
    ),
    _entry(
        "18E-B2-equity-total",
        statement_family="changes_in_equity",
        section_blocks=("changes_in_equity",),
        labels=("balance at beginning of year", "balance at end of year", "total equity"),
        preferred_qname="ifrs-smes:Equity",
        concept_family="equity_total",
        confidence_tier="dictionary_review_required",
        evidence_source="taxonomy_label",
    ),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def statement_concept_candidate_entries() -> list[dict[str, Any]]:
    return [dict(entry) for entry in DICTIONARY_ENTRIES]


def _context_value(context: Mapping[str, Any], key: str) -> Any:
    if key in context:
        return context.get(key)
    row_context = context.get("row_context")
    if isinstance(row_context, Mapping):
        return row_context.get(key)
    return None


def _context_label(context: Mapping[str, Any]) -> str:
    return canonical_label(
        context.get("normalized_label")
        or context.get("original_label")
        or context.get("pdf_label")
        or context.get("label")
    )


def _raw_context_label(context: Mapping[str, Any]) -> str:
    return normalize_label(
        context.get("original_label")
        or context.get("pdf_label")
        or context.get("normalized_label")
        or context.get("label")
    )


def _condition_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set, frozenset)):
        return actual in expected
    return actual == expected


def _safe_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _label_match_score(label: str, raw_label: str, aliases: Sequence[str]) -> tuple[float, str | None]:
    best = 0.0
    matched = None
    for alias in aliases:
        alias_norm = canonical_label(alias)
        if not alias_norm:
            continue
        if label == alias_norm or raw_label == alias_norm:
            return 1.0, alias_norm
        if alias_norm in raw_label or alias_norm in label:
            score = min(0.95, max(0.72, len(alias_norm) / max(len(raw_label), len(alias_norm))))
            if score > best:
                best = score
                matched = alias_norm
    return best, matched


def entry_matches_context(entry: Mapping[str, Any], context: Mapping[str, Any]) -> tuple[bool, list[str], float]:
    family = _context_value(context, "statement_family")
    section = _context_value(context, "section_block")
    row_role = _context_value(context, "row_role")
    required_family = entry.get("statement_family")
    if required_family and family != required_family:
        return False, [], 0.0
    section_blocks = set(entry.get("section_blocks") or [])
    if section_blocks and section not in section_blocks:
        return False, [], 0.0
    row_roles = set(entry.get("row_roles") or [])
    if row_roles and row_role not in row_roles:
        return False, [], 0.0
    for key, expected in (entry.get("required_context_conditions") or {}).items():
        if not _condition_matches(_context_value(context, key), expected):
            return False, [], 0.0

    label = _context_label(context)
    raw_label = _raw_context_label(context)
    label_score, matched_alias = _label_match_score(label, raw_label, entry.get("aliases") or [])
    if label_score <= 0:
        return False, [], 0.0

    reasons = [
        f"dictionary_entry:{entry.get('dictionary_entry_id')}",
        f"statement_family:{family or 'unknown'}",
        f"section_block:{section or 'unknown'}",
        f"matched_alias:{matched_alias}",
    ]
    if row_role:
        reasons.append(f"row_role:{row_role}")
    return True, reasons, label_score


def _hotfix_blocking_reasons(
    entry: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    label_score: float,
) -> list[str]:
    entry_id = str(entry.get("dictionary_entry_id") or "")
    label = _context_label(context)
    family = _context_value(context, "statement_family")
    section = _context_value(context, "section_block")
    row_role = _context_value(context, "row_role")
    context_confidence = _safe_float(_context_value(context, "context_confidence"))
    reasons: list[str] = []

    if context_confidence is not None and context_confidence < LOW_CONTEXT_CONFIDENCE_THRESHOLD:
        reasons.append("low_context_confidence_blocks_dictionary_candidate")
    if section in UNKNOWN_SECTION_BLOCKS:
        reasons.append("missing_section_context_blocks_dictionary_candidate")
    if label_score < 1.0:
        reasons.append("non_exact_dictionary_alias_blocked")

    is_note_context = (
        bool(_context_value(context, "is_notes_context"))
        or family == "notes"
        or row_role == "note_detail"
        or str(section or "").startswith("notes_")
    )
    if is_note_context:
        reasons.append("note_detail_main_statement_concept_blocked")
        if entry_id == "18E-B2-note-tax-expense":
            reasons.append("missing_note_link_confirmation")

    if entry_id == "18E-B2-is-administrative-expenses" and label not in STABLE_ADMIN_EXPENSE_TOTAL_LABELS:
        reasons.append("administrative_expense_component_dictionary_blocked")
    if entry_id == "18E-B2-sfp-borrowings":
        reasons.append("borrowings_specificity_requires_note_or_current_noncurrent_boundary")
    if entry_id == "18E-B2-cf-operating" and label not in EXACT_CASH_FLOW_TOTAL_LABELS:
        reasons.append("cash_flow_header_or_component_blocked")
    if entry_id == "18E-B2-cf-ppe-purchase" and not (
        label.startswith("purchase of property plant and equipment")
        or label.startswith("purchase of property plant")
        or label.startswith("acquisition of property plant")
    ):
        reasons.append("cash_flow_ppe_purchase_requires_purchase_or_acquisition_label")
    if entry_id == "18E-B2-equity-comprehensive-income" and label not in STABLE_COMPREHENSIVE_EQUITY_LABELS:
        reasons.append("unstable_comprehensive_income_equity_alias_blocked")
    if entry_id == "18E-B2-sfp-total-assets" and "discussion" in label:
        reasons.append("extraction_artifact_discussion_label_blocked")

    if entry_id == "18E-B2-is-tax-expense" and family != "income_statement":
        reasons.append("tax_expense_requires_profit_and_loss_context")
    if entry_id == "18E-B2-sfp-tax-payable" and section != "current_liabilities":
        reasons.append("tax_payable_requires_current_liabilities_context")
    if entry_id == "18E-B2-sfp-receivables" and section != "current_assets":
        reasons.append("receivables_require_current_assets_context")
    if entry_id == "18E-B2-sfp-payables" and section != "current_liabilities":
        reasons.append("payables_require_current_liabilities_context")
    if entry_id == "18E-B2-sfp-accruals" and section != "current_liabilities":
        reasons.append("accruals_require_current_liabilities_context")

    return sorted(dict.fromkeys(reasons))


def match_statement_concept_candidate(
    context: Mapping[str, Any] | None,
    entries: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not context:
        return None
    matches = []
    for index, entry in enumerate(entries or DICTIONARY_ENTRIES):
        matched, reasons, label_score = entry_matches_context(entry, context)
        if not matched:
            continue
        tier = str(entry.get("confidence_tier") or "dictionary_review_required")
        score = round(min(0.68, max(0.48, 0.46 + (label_score * 0.18))), 4)
        matches.append((CONFIDENCE_RANK.get(tier, 9), -label_score, index, entry, reasons, score))
    if not matches:
        return None
    _, _, _, entry, reasons, score = sorted(matches)[0]
    blocking = ["dictionary_candidate_requires_review", *(entry.get("blocking_conditions") or [])]
    if _context_value(context, "is_notes_context"):
        blocking.append("notes_context_requires_review")
    hotfix_blocking = _hotfix_blocking_reasons(entry, context, label_score=-sorted(matches)[0][1])
    candidate_blocked = bool(hotfix_blocking)
    blocking.extend(hotfix_blocking)
    return {
        "matched_rule_id": f"18E-B2-dictionary-{entry['dictionary_entry_id']}",
        "dictionary_entry_id": entry.get("dictionary_entry_id"),
        "target_qname": entry.get("preferred_qname"),
        "target_concept_label": concept_label(entry.get("preferred_qname")),
        "candidate_qnames": list(entry.get("candidate_qnames") or []),
        "concept_family": entry.get("concept_family"),
        "confidence_score": score,
        "confidence_bucket": "no_match" if candidate_blocked else "review_required",
        "confidence_tier": entry.get("confidence_tier"),
        "candidate_blocked": candidate_blocked,
        "match_reasons": reasons,
        "blocking_reasons": sorted(dict.fromkeys(blocking)),
        "dictionary_entry": dict(entry),
    }


def build_statement_concept_candidate_dictionary_report(
    *,
    contexts: Sequence[Mapping[str, Any]] = (),
    entries: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    dictionary = [dict(entry) for entry in (entries or DICTIONARY_ENTRIES)]
    matched = []
    for context in contexts:
        candidate = match_statement_concept_candidate(context, dictionary)
        if not candidate:
            continue
        matched.append(
            {
                "sample_id": context.get("sample_id"),
                "row_id": context.get("row_id"),
                "normalized_label": context.get("normalized_label"),
                "statement_family": context.get("statement_family"),
                "section_block": context.get("section_block"),
                "dictionary_entry_id": candidate.get("dictionary_entry_id"),
                "target_qname": candidate.get("target_qname"),
                "candidate_blocked": candidate.get("candidate_blocked"),
                "blocking_reasons": candidate.get("blocking_reasons") or [],
                "match_reasons": candidate.get("match_reasons"),
            }
        )
    entry_families = Counter(str(entry.get("statement_family") or "any") for entry in dictionary)
    usage = Counter(str(item.get("dictionary_entry_id")) for item in matched)
    return {
        "run_metadata": {
            "feature": "18E-B-2",
            "generated_at": utc_now(),
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": {
            "dictionary_entry_count": len(dictionary),
            "entry_count_by_statement_family": dict(sorted(entry_families.items())),
            "context_rows_considered": len(contexts),
            "context_rows_with_dictionary_candidate": len(matched),
            "context_rows_with_blocked_dictionary_candidate": sum(1 for item in matched if item.get("candidate_blocked")),
            "top_dictionary_usage": [
                {"dictionary_entry_id": key, "count": count}
                for key, count in usage.most_common(30)
            ],
            "safe_for_auto_apply": False,
            "requires_human_review": True,
        },
        "dictionary_entries": dictionary,
        "context_candidate_matches": matched,
    }


def render_statement_concept_candidate_dictionary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Statement Concept Candidate Dictionary - Feature #18E-B-2",
        "",
        f"- Dictionary entries: {summary.get('dictionary_entry_count', 0)}",
        f"- Context rows considered: {summary.get('context_rows_considered', 0)}",
        f"- Context rows with dictionary candidates: {summary.get('context_rows_with_dictionary_candidate', 0)}",
        f"- Safe for auto-apply: {summary.get('safe_for_auto_apply')}",
        "",
        "## Entries by Statement Family",
        "",
        "| Statement family | Count |",
        "| --- | ---: |",
    ]
    for family, count in (summary.get("entry_count_by_statement_family") or {}).items():
        lines.append(f"| {family} | {count} |")
    lines.extend(["", "## Top Usage", "", "| Entry | Count |", "| --- | ---: |"])
    for item in summary.get("top_dictionary_usage") or []:
        lines.append(f"| {item.get('dictionary_entry_id')} | {item.get('count')} |")
    lines.append("")
    return "\n".join(lines)
