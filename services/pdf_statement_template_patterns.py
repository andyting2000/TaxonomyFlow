"""Statement-specific template patterns for Feature #18E-B.

The patterns in this module are intentionally offline and advisory-only. They
expand deterministic candidate coverage for replay reports, but they do not make
any mapping safe to auto-apply.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from services.pdf_xbrl_deterministic_alignment import clean_text, concept_label, normalize_label


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


PATTERN_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "pattern_id": "18E-B-is-cost-of-sales",
        "statement_family": "income_statement",
        "section_blocks": ["cost_of_sales"],
        "label_any": ["cost of sales", "purchases"],
        "target_qname": "ifrs-smes:CostOfSales",
        "reason": "income_statement_cost_of_sales_template",
    },
    {
        "pattern_id": "18E-B-is-gross-profit",
        "statement_family": "income_statement",
        "label_any": ["gross profit", "gross loss"],
        "target_qname": "ifrs-smes:GrossProfit",
        "reason": "income_statement_gross_profit_template",
    },
    {
        "pattern_id": "18E-B-is-audit-fees",
        "statement_family": "income_statement",
        "label_any": ["audit fee", "audit fees", "auditors remuneration", "auditor s remuneration", "auditors' remuneration"],
        "target_qname": "ssmt-mpers:AuditorsRemuneration",
        "reason": "income_statement_audit_fee_template",
    },
    {
        "pattern_id": "18E-B-is-directors-fees",
        "statement_family": "income_statement",
        "label_any": ["director s fee", "directors fee", "directors fees"],
        "target_qname": "ssmt-mpers:DirectorsFees",
        "reason": "income_statement_directors_fee_template",
    },
    {
        "pattern_id": "18E-B-is-directors-remuneration",
        "statement_family": "income_statement",
        "label_any": ["directors remuneration", "director s remuneration", "directors salaries", "director s salaries", "directors salary"],
        "target_qname": "ssmt-mpers:DirectorsRemuneration",
        "reason": "income_statement_directors_remuneration_template",
    },
    {
        "pattern_id": "18E-B-is-wages-and-salaries",
        "statement_family": "income_statement",
        "label_any": ["staff costs", "salaries", "wages", "epf contribution", "socso contribution", "eis contribution"],
        "target_qname": "ifrs-smes:WagesAndSalaries",
        "reason": "income_statement_staff_cost_template",
    },
    {
        "pattern_id": "18E-B-fp-share-capital",
        "statement_family": "financial_position",
        "section_blocks": ["equity"],
        "label_any": ["share capital"],
        "target_qname": "ifrs-smes:IssuedCapital",
        "reason": "financial_position_share_capital_template",
    },
    {
        "pattern_id": "18E-B-fp-retained-earnings",
        "statement_family": "financial_position",
        "section_blocks": ["equity"],
        "label_any": ["accumulated losses", "retained profits", "retained earnings"],
        "target_qname": "ifrs-smes:RetainedEarnings",
        "reason": "financial_position_retained_earnings_template",
    },
    {
        "pattern_id": "18E-B-fp-current-accruals",
        "statement_family": "financial_position",
        "section_blocks": ["current_liabilities"],
        "label_any": ["accruals"],
        "target_qname": "ssmt-mpers:CurrentNontradeAccruals",
        "reason": "financial_position_current_accruals_template",
    },
    {
        "pattern_id": "18E-B-fp-current-tax-liability",
        "statement_family": "financial_position",
        "section_blocks": ["current_liabilities"],
        "label_any": ["provision for taxation", "taxation"],
        "target_qname": "ifrs-smes:CurrentTaxLiabilitiesCurrent",
        "reason": "financial_position_current_tax_liability_template",
    },
    {
        "pattern_id": "18E-B-fp-related-party-payable",
        "statement_family": "financial_position",
        "section_blocks": ["current_liabilities", "non_current_liabilities"],
        "label_any": ["amount due to director", "amount due to directors", "due to related parties"],
        "target_qname": "ssmt-mpers:OtherCurrentPayablesDueToRelatedParties",
        "reason": "financial_position_related_party_payable_template",
    },
    {
        "pattern_id": "18E-B-fp-related-party-receivable",
        "statement_family": "financial_position",
        "section_blocks": ["current_assets"],
        "label_any": ["amount due from director", "amount due from directors", "due from related parties"],
        "target_qname": "ssmt-mpers:OtherCurrentReceivablesDueFromRelatedParties",
        "reason": "financial_position_related_party_receivable_template",
    },
    {
        "pattern_id": "18E-B-fp-other-current-deposits",
        "statement_family": "financial_position",
        "section_blocks": ["current_assets"],
        "label_any": ["deposits", "other deposits"],
        "target_qname": "ssmt-mpers:OtherCurrentNontradeDeposits",
        "reason": "financial_position_deposits_template",
    },
    {
        "pattern_id": "18E-B-cf-operating-total",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_operating"],
        "label_any": ["net cash from operating activities", "net cash from to operating activities", "cash from operating activities"],
        "target_qname": "ifrs-smes:CashFlowsFromUsedInOperatingActivities",
        "reason": "cash_flow_operating_total_template",
    },
    {
        "pattern_id": "18E-B-cf-investing-total",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_investing"],
        "label_any": ["cash flows from investing activities", "net cash to investing activities", "net cash from investing activities"],
        "target_qname": "ifrs-smes:CashFlowsFromUsedInInvestingActivities",
        "reason": "cash_flow_investing_total_template",
    },
    {
        "pattern_id": "18E-B-cf-financing-total",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_financing"],
        "label_any": ["cash flows from financing activities", "net cash from financing activities", "net cash used in financing activities"],
        "target_qname": "ifrs-smes:CashFlowsFromUsedInFinancingActivities",
        "reason": "cash_flow_financing_total_template",
    },
    {
        "pattern_id": "18E-B-cf-cash-net-change",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_reconciliation"],
        "label_any": ["net increase in cash", "net decrease in cash", "net decrease increase in cash", "net increase decrease in cash"],
        "target_qname": "ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents",
        "reason": "cash_flow_cash_change_template",
    },
    {
        "pattern_id": "18E-B-cf-cash-equivalents",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_reconciliation"],
        "label_any": [
            "cash and cash equivalents at beginning",
            "cash and cash equivalents at the beginning",
            "cash and cash equivalents at end",
            "cash and cash equivalents at the end",
            "cash and cash equivalent at beginning",
            "cash and cash equivalent at the end",
            "bank balances",
        ],
        "target_qname": "ifrs-smes:CashAndCashEquivalents",
        "reason": "cash_flow_cash_equivalents_reconciliation_template",
    },
    {
        "pattern_id": "18E-B-cf-depreciation-adjustment",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_investing", "cash_flow_operating", "cash_flow_other"],
        "label_any": ["depreciation", "depreciation of property plant and equipment", "depreciation of property, plant and equipment"],
        "target_qname": "ssmt-mpers:AdjustmentsForDepreciationExpense",
        "reason": "cash_flow_depreciation_adjustment_template",
    },
    {
        "pattern_id": "18E-B-cf-receivables-adjustment",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_operating"],
        "label_any": ["trade and other receivables", "trade receivables", "other receivables", "amount due from directors"],
        "label_any_required": ["increase", "decrease"],
        "target_qname": "ifrs-smes:AdjustmentsForDecreaseIncreaseInTradeAccountReceivable",
        "reason": "cash_flow_receivables_working_capital_template",
    },
    {
        "pattern_id": "18E-B-cf-payables-adjustment",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_operating"],
        "label_any": ["trade and other payables", "other payables", "payables and accruals", "amount due to director", "amount due to directors"],
        "label_any_required": ["increase", "decrease"],
        "target_qname": "ifrs-smes:AdjustmentsForIncreaseDecreaseInTradeAndOtherPayables",
        "reason": "cash_flow_payables_working_capital_template",
    },
    {
        "pattern_id": "18E-B-cf-income-tax-paid",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_operating"],
        "label_any": ["taxation paid", "income tax paid", "tax paid"],
        "target_qname": "ifrs-smes:IncomeTaxesPaidRefundClassifiedAsOperatingActivities",
        "reason": "cash_flow_income_tax_paid_template",
    },
    {
        "pattern_id": "18E-B-cf-borrowing-repayment",
        "statement_family": "cash_flow",
        "section_blocks": ["cash_flow_financing"],
        "label_any": ["repayment of term loan", "repayment of borrowings", "term loan repayment"],
        "target_qname": "ifrs-smes:RepaymentsOfBorrowingsClassifiedAsFinancingActivities",
        "reason": "cash_flow_borrowing_repayment_template",
    },
    {
        "pattern_id": "18E-B-note-tax-expense",
        "statement_family": None,
        "section_blocks": ["notes_tax"],
        "label_any": ["tax expense", "income tax expense", "charges for the year", "provision based on these financial statements"],
        "note_title_any": ["tax", "taxation"],
        "target_qname": "ifrs-smes:IncomeTaxExpenseContinuingOperations",
        "reason": "note_linked_tax_expense_template",
    },
    {
        "pattern_id": "18E-B-note-audit-fees",
        "statement_family": None,
        "section_blocks": ["notes_detail", "administrative_expenses"],
        "label_any": ["audit fee", "auditors remuneration", "auditor s remuneration"],
        "target_qname": "ssmt-mpers:AuditorsRemuneration",
        "reason": "note_linked_audit_fee_template",
    },
    {
        "pattern_id": "18E-B-note-directors-remuneration",
        "statement_family": None,
        "section_blocks": ["notes_detail", "administrative_expenses"],
        "label_any": ["directors remuneration", "director s remuneration", "directors fees", "directors fee"],
        "target_qname": "ssmt-mpers:DirectorsRemuneration",
        "reason": "note_linked_directors_remuneration_template",
    },
    {
        "pattern_id": "18E-B-note-accruals",
        "statement_family": None,
        "section_blocks": ["notes_payables", "notes_detail"],
        "label_any": ["accruals"],
        "note_title_any": ["payable", "accrual"],
        "target_qname": "ssmt-mpers:CurrentNontradeAccruals",
        "reason": "note_linked_accruals_template",
    },
    {
        "pattern_id": "18E-B-note-ppe-depreciation",
        "statement_family": None,
        "section_blocks": ["notes_ppe", "notes_detail"],
        "label_any": ["depreciation"],
        "note_title_any": ["property plant", "property, plant"],
        "target_qname": "ifrs-smes:DepreciationPropertyPlantAndEquipment",
        "reason": "note_linked_ppe_depreciation_template",
    },
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _unique(values: Sequence[Any]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if value not in (None, "")))


def _context_confidence(context: Mapping[str, Any]) -> float:
    try:
        return float(context.get("context_confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _context_label_text(context: Mapping[str, Any]) -> str:
    return normalize_label(
        " ".join(
            str(value or "")
            for value in (
                context.get("original_label"),
                context.get("normalized_label"),
                context.get("section_block"),
            )
        )
    )


def _note_text(note_link: Mapping[str, Any] | None) -> str:
    if not note_link:
        return ""
    return normalize_label(
        " ".join(
            str(value or "")
            for value in (
                note_link.get("note_number"),
                note_link.get("note_title"),
                note_link.get("note_section_label"),
            )
        )
    )


def _contains_any(text: str, phrases: Sequence[str]) -> bool:
    return any(normalize_label(phrase) in text for phrase in phrases if normalize_label(phrase))


def _pattern_matches_context(
    pattern: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    note_link: Mapping[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    family = pattern.get("statement_family")
    if family and str(context.get("statement_family") or "") != str(family):
        return False, []
    if family:
        reasons.append(f"statement_family:{family}")

    blocks = _as_list(pattern.get("section_blocks"))
    if blocks and str(context.get("section_block") or "") not in blocks:
        return False, []
    if blocks:
        reasons.append(f"section_block:{context.get('section_block')}")

    roles = _as_list(pattern.get("row_roles"))
    if roles and str(context.get("row_role") or "") not in roles:
        return False, []
    if roles:
        reasons.append(f"row_role:{context.get('row_role')}")

    text = _context_label_text(context)
    any_required = _as_list(pattern.get("label_any_required"))
    if any_required and not _contains_any(text, any_required):
        return False, []
    label_any = _as_list(pattern.get("label_any"))
    if label_any and not _contains_any(text, label_any):
        return False, []
    label_all = _as_list(pattern.get("label_all"))
    if label_all and not all(normalize_label(phrase) in text for phrase in label_all):
        return False, []
    label_none = _as_list(pattern.get("label_none"))
    if label_none and _contains_any(text, label_none):
        return False, []
    if label_any or label_all:
        reasons.append("label_pattern_match")

    note_any = _as_list(pattern.get("note_title_any"))
    if note_any:
        note = _note_text(note_link)
        if not note or not _contains_any(note, note_any):
            return False, []
        reasons.append("note_title_pattern_match")

    return True, reasons


def _support_for_pattern(pattern: Mapping[str, Any], contexts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    matched = []
    for context in contexts:
        ok, _reasons = _pattern_matches_context(pattern, context)
        if ok:
            matched.append(context)
    labels = Counter(str(item.get("normalized_label") or normalize_label(item.get("original_label"))) for item in matched)
    samples = sorted({str(item.get("sample_id") or "") for item in matched if item.get("sample_id")})
    return {
        "observation_count": len(matched),
        "sample_support_count": len(samples),
        "sample_ids": samples,
        "top_observed_labels": [
            {"normalized_label": label, "count": count}
            for label, count in labels.most_common(10)
            if label
        ],
    }


def extract_statement_template_patterns(row_contexts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return deterministic statement template patterns with observed support."""
    patterns: list[dict[str, Any]] = []
    for raw in PATTERN_DEFINITIONS:
        pattern = dict(raw)
        pattern["target_concept_label"] = concept_label(pattern.get("target_qname"))
        pattern["candidate_source"] = "statement_template_pattern"
        pattern["confidence_bucket"] = "review_required"
        pattern["safe_for_auto_apply"] = False
        pattern["requires_human_review"] = True
        pattern["blocking_reasons"] = ["statement_template_candidate_requires_review"]
        pattern["support"] = _support_for_pattern(pattern, row_contexts)
        patterns.append(pattern)
    return patterns


def template_pattern_index(patterns: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(item.get("pattern_id") or ""): item for item in patterns if item.get("pattern_id")}


def match_statement_template_candidate(
    context: Mapping[str, Any] | None,
    patterns: Sequence[Mapping[str, Any]],
    *,
    note_link: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the first deterministic review-only template candidate for a row context."""
    if not context:
        return None
    for pattern in patterns:
        matched, reasons = _pattern_matches_context(pattern, context, note_link=note_link)
        if not matched:
            continue
        confidence = min(0.72, max(0.42, _context_confidence(context)))
        blocking = ["statement_template_candidate_requires_review"]
        if _context_confidence(context) < 0.75:
            blocking.append("low_context_confidence_requires_review")
        if not context.get("is_main_statement"):
            blocking.append("non_main_statement_context_requires_review")
        if context.get("is_notes_context"):
            blocking.append("notes_context_requires_review")
        if note_link:
            blocking.append("note_linked_candidate_requires_review")
        return {
            "matched_template_pattern_id": pattern.get("pattern_id"),
            "matched_rule_id": pattern.get("pattern_id"),
            "target_qname": pattern.get("target_qname"),
            "target_concept_label": pattern.get("target_concept_label") or concept_label(pattern.get("target_qname")),
            "confidence_score": round(min(confidence, 0.65), 4),
            "confidence_bucket": "review_required",
            "candidate_source": "note_link_template_pattern" if note_link else "statement_template_pattern",
            "match_reasons": _unique([pattern.get("reason"), *reasons, "statement_template_rulebook_match"]),
            "blocking_reasons": _unique(blocking),
            "template_pattern": {
                "pattern_id": pattern.get("pattern_id"),
                "statement_family": pattern.get("statement_family"),
                "section_blocks": pattern.get("section_blocks"),
                "target_qname": pattern.get("target_qname"),
                "reason": pattern.get("reason"),
            },
        }
    return None


def summarize_statement_template_patterns(patterns: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    supported = [item for item in patterns if int(((item.get("support") or {}).get("observation_count") or 0)) > 0]
    by_family = Counter(str(item.get("statement_family") or "any") for item in patterns)
    supported_by_family = Counter(str(item.get("statement_family") or "any") for item in supported)
    observations = sum(int((item.get("support") or {}).get("observation_count") or 0) for item in patterns)
    return {
        "feature": "18E-B",
        "total_template_patterns": len(patterns),
        "supported_template_patterns": len(supported),
        "unsupported_template_patterns": len(patterns) - len(supported),
        "template_observation_support_total": observations,
        "pattern_family_counts": dict(sorted(by_family.items())),
        "supported_pattern_family_counts": dict(sorted(supported_by_family.items())),
        "safe_for_auto_apply_count": 0,
        "requires_human_review_count": len(patterns),
        "safety": SAFETY,
    }


def build_statement_template_report(row_contexts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    patterns = extract_statement_template_patterns(row_contexts)
    return {
        "run_metadata": {
            "feature": "18E-B",
            "generated_at": _utc_now(),
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": summarize_statement_template_patterns(patterns),
        "statement_template_patterns": patterns,
    }


def render_statement_template_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Statement Template Patterns - Feature #18E-B",
        "",
        f"- Total patterns: {summary.get('total_template_patterns', 0)}",
        f"- Supported patterns: {summary.get('supported_template_patterns', 0)}",
        f"- Unsupported patterns: {summary.get('unsupported_template_patterns', 0)}",
        f"- Safe for auto-apply: {summary.get('safe_for_auto_apply_count', 0)}",
        "",
        "| Pattern | QName | Observations | Samples |",
        "| --- | --- | ---: | ---: |",
    ]
    for pattern in report.get("statement_template_patterns") or []:
        support = pattern.get("support") or {}
        lines.append(
            f"| {clean_text(pattern.get('pattern_id'))} | {pattern.get('target_qname')} | "
            f"{support.get('observation_count', 0)} | {support.get('sample_support_count', 0)} |"
        )
    lines.append("")
    return "\n".join(lines)
