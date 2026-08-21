"""Local non-lexical candidate sources for Feature #18E-F-A-2.

The sources in this module are offline, deterministic, and review-only. They
use row context, statement packs, note boundaries, and local concept-card files;
they do not use paired XBRL facts, evaluation labels, embeddings, or external
providers for candidate generation.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from services.pdf_note_detail_boundaries import classify_note_detail_boundary
from services.pdf_xbrl_deterministic_alignment import canonical_label, concept_label, label_similarity, normalize_label
from services.tightened_mapper_evaluation import sanitize_report_value


SAFETY = {
    "external_llm_called": False,
    "external_provider_called": False,
    "qwen_called": False,
    "supervisor_called": False,
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

DEFAULT_CONCEPT_PLAYBOOK_GLOBS = (
    "reports/fs_mpers_concept_playbook_*.json",
    "reports/fs_mpers_rag_payload_examples_*.json",
    "reports/fs_mpers_rag_retrieval_examples_*.json",
)

SOURCE_TYPES = {
    "statement_role_pack",
    "section_concept_pack",
    "concept_playbook_lookup",
    "taxonomy_structure_hint",
    "note_total_candidate",
    "cash_flow_movement_pack",
    "equity_movement_pack",
    "format_memory_pack",
    "local_concept_family_pack",
}

GENERIC_LABELS = {
    "amount",
    "balance",
    "current",
    "expense",
    "expenses",
    "income",
    "liabilities",
    "liability",
    "other",
    "subtotal",
    "total",
}

NOISY_LABEL_TERMS = {
    "akescheda",
    "br and se",
    "brojrp",
    "discussion",
    "dracione",
    "ho e",
    "hoe",
    "hr table",
    "ronic",
    "unselected",
}

STATEMENT_NAME_MAP = {
    "statement of financial position": "financial_position",
    "statement of comprehensive income": "income_statement",
    "statement of profit or loss": "income_statement",
    "statement of cash flows": "cash_flow",
    "statement of changes in equity": "changes_in_equity",
    "notes": "notes",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _unique(values: Iterable[Any]) -> list[str]:
    return sorted({str(value) for value in values if value not in (None, "")})


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _context(record: Mapping[str, Any]) -> dict[str, Any]:
    nested = record.get("row_context") if isinstance(record.get("row_context"), Mapping) else {}
    period = record.get("pdf_period") if isinstance(record.get("pdf_period"), Mapping) else {}
    label = record.get("pdf_label") or record.get("normalized_label") or nested.get("original_label") or nested.get("normalized_label")
    return {
        "sample_id": record.get("sample_id") or nested.get("sample_id"),
        "row_id": record.get("pdf_row_id") or record.get("row_id") or nested.get("row_id"),
        "original_label": label,
        "pdf_label": label,
        "normalized_label": record.get("normalized_label") or nested.get("normalized_label") or canonical_label(label),
        "statement_family": record.get("statement_family") or record.get("pdf_statement_family") or nested.get("statement_family"),
        "section_block": record.get("section_block") or nested.get("section_block"),
        "row_role": record.get("row_role") or nested.get("row_role"),
        "context_confidence": record.get("context_confidence") or nested.get("context_confidence"),
        "is_main_statement": record.get("is_main_statement") if "is_main_statement" in record else nested.get("is_main_statement"),
        "is_notes_context": record.get("is_notes_context") if "is_notes_context" in record else nested.get("is_notes_context"),
        "value_role": period.get("value_role"),
        "expected_year": period.get("expected_year"),
    }


def _label(record: Mapping[str, Any]) -> str:
    return canonical_label(record.get("normalized_label") or record.get("pdf_label") or (_context(record).get("normalized_label")))


def _label_text(record: Mapping[str, Any]) -> str:
    ctx = _context(record)
    return normalize_label(" ".join(str(value or "") for value in (ctx.get("original_label"), ctx.get("normalized_label"))))


def _contains_any(text: str, phrases: Sequence[str]) -> bool:
    return any(normalize_label(phrase) in text for phrase in phrases if normalize_label(phrase))


def _contains_all(text: str, phrases: Sequence[str]) -> bool:
    return all(normalize_label(phrase) in text for phrase in phrases if normalize_label(phrase))


def _is_noisy_label(text: str) -> bool:
    return any(term in text for term in NOISY_LABEL_TERMS)


def _is_generic_label(text: str) -> bool:
    return text in GENERIC_LABELS or text.startswith("total ")


def _statement_families_from_names(names: Sequence[Any]) -> list[str]:
    families = []
    for name in names:
        normalized = normalize_label(name)
        for pattern, family in STATEMENT_NAME_MAP.items():
            if pattern in normalized:
                families.append(family)
    return _unique(families)


def _pack(
    source_id: str,
    source_type: str,
    *,
    statement_family: str | None,
    section_blocks: Sequence[str],
    labels: Sequence[str],
    qname: str,
    concept_family: str,
    row_roles: Sequence[str] = (),
    required_terms: Sequence[str] = (),
    blocked_terms: Sequence[str] = (),
    score: float = 1.0,
    risk_level_hint: str = "low",
    match_mode: str = "contains",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "source_type": source_type,
        "statement_family": statement_family,
        "section_blocks": list(section_blocks),
        "labels": [canonical_label(item) for item in labels],
        "qname": qname,
        "concept_label": concept_label(qname),
        "concept_family": concept_family,
        "row_roles": list(row_roles),
        "required_terms": [normalize_label(item) for item in required_terms],
        "blocked_terms": [normalize_label(item) for item in blocked_terms],
        "score": score,
        "risk_level_hint": risk_level_hint,
        "match_mode": match_mode,
    }


PACK_DEFINITIONS: tuple[dict[str, Any], ...] = (
    _pack("pl-revenue", "statement_role_pack", statement_family="income_statement", section_blocks=("revenue",), labels=("revenue", "sales", "turnover"), qname="ifrs-smes:Revenue", concept_family="profit_loss"),
    _pack("pl-cost-of-sales", "statement_role_pack", statement_family="income_statement", section_blocks=("cost_of_sales",), labels=("cost of sales", "purchases", "add purchases", "less closing stocks"), qname="ifrs-smes:CostOfSales", concept_family="profit_loss", risk_level_hint="medium"),
    _pack("pl-gross-profit", "statement_role_pack", statement_family="income_statement", section_blocks=("profit_loss", "income_statement_other"), labels=("gross profit", "gross loss"), qname="ifrs-smes:GrossProfit", concept_family="profit_loss"),
    _pack("pl-other-income", "section_concept_pack", statement_family="income_statement", section_blocks=("other_income", "income_statement_other"), labels=("other income", "rental income", "interest income", "gain on disposal"), qname="ifrs-smes:OtherIncome", concept_family="profit_loss", risk_level_hint="medium"),
    _pack("pl-finance-costs", "section_concept_pack", statement_family="income_statement", section_blocks=("finance_costs", "administrative_expenses"), labels=("finance costs", "term loan interests", "interest on term loans", "interests on term loans", "interest expense", "bank overdraft interest"), qname="ifrs-smes:FinanceCosts", concept_family="profit_loss", risk_level_hint="medium"),
    _pack("pl-tax-expense", "statement_role_pack", statement_family="income_statement", section_blocks=("tax_expense", "profit_loss"), labels=("tax expense", "taxation", "income tax expense", "less taxation"), qname="ifrs-smes:IncomeTaxExpenseContinuingOperations", concept_family="tax", risk_level_hint="high"),
    _pack("pl-profit-before-tax", "statement_role_pack", statement_family="income_statement", section_blocks=("profit_loss_before_tax", "profit_loss"), labels=("profit before tax", "profit before taxation", "loss before tax", "loss before taxation", "operating loss before tax"), qname="ifrs-smes:ProfitLossBeforeTax", concept_family="profit_loss"),
    _pack("pl-profit-loss-year", "statement_role_pack", statement_family="income_statement", section_blocks=("profit_loss",), labels=("profit for the year", "loss for the year", "profit for the financial year", "loss for the financial year"), qname="ifrs-smes:ProfitLoss", concept_family="profit_loss", row_roles=("subtotal", "total")),
    _pack("pl-comprehensive-income", "statement_role_pack", statement_family="income_statement", section_blocks=("profit_loss",), labels=("total comprehensive income", "total comprehensive loss", "comprehensive income", "comprehensive loss"), qname="ifrs-smes:ComprehensiveIncome", concept_family="profit_loss", row_roles=("subtotal", "total")),
    _pack("pl-audit-fees", "concept_playbook_lookup", statement_family="income_statement", section_blocks=("administrative_expenses", "income_statement_other"), labels=("audit fee", "audit fees", "auditors remuneration", "auditor s remuneration"), qname="ssmt-mpers:AuditorsRemuneration", concept_family="profit_loss", risk_level_hint="medium"),
    _pack("pl-directors-remuneration", "concept_playbook_lookup", statement_family="income_statement", section_blocks=("administrative_expenses", "income_statement_other"), labels=("directors remuneration", "director s remuneration", "directors fee", "director s fee", "directors fees"), qname="ssmt-mpers:DirectorsRemuneration", concept_family="profit_loss", risk_level_hint="medium"),
    _pack("pl-expense-component", "local_concept_family_pack", statement_family="income_statement", section_blocks=("administrative_expenses", "income_statement_other"), labels=("accounting fee", "advertisement", "bank charges", "commission paid", "computer", "electricity", "insurance", "legal fee", "maintenance", "membership fee", "penalties", "petrol", "printing", "professional fee", "rental", "secretarial fee", "seminar fee", "stationeries", "telephone", "travelling", "upkeep", "water", "web hosting", "website maintenance"), qname="ifrs-smes:OtherExpenseByFunction", concept_family="profit_loss", score=0.78, risk_level_hint="medium"),
    _pack("sfp-current-assets", "section_concept_pack", statement_family="financial_position", section_blocks=("current_assets",), labels=("current assets", "total current assets"), qname="ifrs-smes:CurrentAssets", concept_family="financial_position", row_roles=("subtotal", "total")),
    _pack("sfp-noncurrent-assets", "section_concept_pack", statement_family="financial_position", section_blocks=("non_current_assets",), labels=("non current assets", "non-current assets", "total non current assets", "total non-current assets"), qname="ifrs-smes:NoncurrentAssets", concept_family="financial_position", row_roles=("subtotal", "total")),
    _pack("sfp-ppe", "section_concept_pack", statement_family="financial_position", section_blocks=("non_current_assets",), labels=("property plant and equipment", "property, plant and equipment", "plant and equipment"), qname="ifrs-smes:PropertyPlantAndEquipment", concept_family="financial_position"),
    _pack("sfp-receivables", "section_concept_pack", statement_family="financial_position", section_blocks=("current_assets",), labels=("trade and other receivables", "trade receivables", "other receivables"), qname="ifrs-smes:TradeAndOtherCurrentReceivables", concept_family="receivables", risk_level_hint="high"),
    _pack("sfp-related-receivable", "section_concept_pack", statement_family="financial_position", section_blocks=("current_assets", "financial_position_other"), labels=("amount due from director", "amount due from directors", "due from directors", "amount due from related parties"), qname="ssmt-mpers:OtherCurrentReceivablesDueFromRelatedParties", concept_family="receivables", risk_level_hint="high"),
    _pack("sfp-cash-bank", "section_concept_pack", statement_family="financial_position", section_blocks=("current_assets",), labels=("cash at bank", "bank balances", "cash and bank balances"), qname="ssmt:CashAndBankBalances", concept_family="cash"),
    _pack("sfp-total-assets", "section_concept_pack", statement_family="financial_position", section_blocks=("assets", "financial_position_other"), labels=("total assets",), qname="ifrs-smes:Assets", concept_family="financial_position", row_roles=("subtotal", "total")),
    _pack("sfp-share-capital", "section_concept_pack", statement_family="financial_position", section_blocks=("equity",), labels=("share capital", "issued capital"), qname="ifrs-smes:IssuedCapital", concept_family="financial_position"),
    _pack("sfp-retained-earnings", "section_concept_pack", statement_family="financial_position", section_blocks=("equity",), labels=("retained earnings", "retained profits", "accumulated losses", "accumulated loss"), qname="ifrs-smes:RetainedEarnings", concept_family="financial_position"),
    _pack("sfp-total-equity", "section_concept_pack", statement_family="financial_position", section_blocks=("equity",), labels=("total equity", "shareholders equity", "total shareholders equity"), qname="ifrs-smes:Equity", concept_family="financial_position", row_roles=("subtotal", "total")),
    _pack("sfp-current-liabilities", "section_concept_pack", statement_family="financial_position", section_blocks=("current_liabilities",), labels=("current liabilities", "total current liabilities"), qname="ifrs-smes:CurrentLiabilities", concept_family="financial_position", row_roles=("subtotal", "total")),
    _pack("sfp-noncurrent-liabilities", "section_concept_pack", statement_family="financial_position", section_blocks=("non_current_liabilities",), labels=("non current liabilities", "non-current liabilities", "total non current liabilities", "total non-current liabilities"), qname="ifrs-smes:NoncurrentLiabilities", concept_family="financial_position", row_roles=("subtotal", "total")),
    _pack("sfp-payables", "section_concept_pack", statement_family="financial_position", section_blocks=("current_liabilities",), labels=("trade and other payables", "trade payables", "other payables", "payables and accruals"), qname="ifrs-smes:TradeAndOtherCurrentPayables", concept_family="payables", risk_level_hint="high"),
    _pack("sfp-related-payable", "section_concept_pack", statement_family="financial_position", section_blocks=("current_liabilities", "financial_position_other"), labels=("amount due to director", "amount due to directors", "due to directors", "amount due to related parties"), qname="ssmt-mpers:OtherCurrentPayablesDueToRelatedParties", concept_family="payables", risk_level_hint="high"),
    _pack("sfp-accruals", "section_concept_pack", statement_family="financial_position", section_blocks=("current_liabilities",), labels=("accruals", "accrued expenses"), qname="ssmt-mpers:CurrentNontradeAccruals", concept_family="payables", risk_level_hint="high"),
    _pack("sfp-borrowings", "section_concept_pack", statement_family="financial_position", section_blocks=("current_liabilities", "non_current_liabilities"), labels=("borrowings", "term loan", "term loans", "bank overdraft"), qname="ifrs-smes:Borrowings", concept_family="borrowings", risk_level_hint="high"),
    _pack("sfp-tax-payable", "section_concept_pack", statement_family="financial_position", section_blocks=("current_liabilities",), labels=("tax payable", "taxation", "provision for taxation", "income tax payable"), qname="ifrs-smes:CurrentTaxLiabilitiesCurrent", concept_family="tax", risk_level_hint="high"),
    _pack("sfp-tax-recoverable", "section_concept_pack", statement_family="financial_position", section_blocks=("current_assets",), labels=("tax recoverable", "tax refundable", "income tax recoverable"), qname="ifrs-smes:CurrentTaxAssetsCurrent", concept_family="tax", risk_level_hint="high"),
    _pack("sfp-liabilities", "section_concept_pack", statement_family="financial_position", section_blocks=("liabilities",), labels=("total liabilities", "liabilities"), qname="ifrs-smes:Liabilities", concept_family="financial_position", row_roles=("subtotal", "total")),
    _pack("sfp-equity-liabilities", "section_concept_pack", statement_family="financial_position", section_blocks=("equity_and_liabilities", "financial_position_other"), labels=("total equity and liabilities", "equity and liabilities", "capital deficiency and liabilities"), qname="ifrs-smes:EquityAndLiabilities", concept_family="financial_position", row_roles=("subtotal", "total")),
    _pack("cf-operating-total", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_operating",), labels=("cash flows from operating activities", "net cash from operating activities", "net cash used in operating activities", "cash from operating activities"), qname="ifrs-smes:CashFlowsFromUsedInOperatingActivities", concept_family="cash_flow"),
    _pack("cf-operations", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_operating", "cash_flow_other"), labels=("operating loss before working capital changes", "operating profit before working capital changes", "net cash generated from operations", "net cash used in operations"), qname="ssmt-mpers:CashFlowsFromUsedInOperations", concept_family="cash_flow", risk_level_hint="medium"),
    _pack("cf-investing-total", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_investing",), labels=("cash flows from investing activities", "net cash used in investing activities", "net cash from investing activities"), qname="ifrs-smes:CashFlowsFromUsedInInvestingActivities", concept_family="cash_flow"),
    _pack("cf-financing-total", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_financing",), labels=("cash flows from financing activities", "net cash from financing activities", "net cash used in financing activities"), qname="ifrs-smes:CashFlowsFromUsedInFinancingActivities", concept_family="cash_flow"),
    _pack("cf-depreciation", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_operating", "cash_flow_other"), labels=("depreciation", "depreciation of property plant and equipment"), qname="ssmt-mpers:AdjustmentsForDepreciationExpense", concept_family="cash_flow", risk_level_hint="medium"),
    _pack("cf-receivables-movement", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_operating",), labels=("trade and other receivables", "trade receivables", "other receivables"), required_terms=("increase", "decrease"), qname="ifrs-smes:AdjustmentsForDecreaseIncreaseInTradeAccountReceivable", concept_family="cash_flow", risk_level_hint="medium"),
    _pack("cf-payables-movement", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_operating",), labels=("trade and other payables", "other payables", "payables and accruals"), required_terms=("increase", "decrease"), qname="ifrs-smes:AdjustmentsForIncreaseDecreaseInTradeAndOtherPayables", concept_family="cash_flow", risk_level_hint="medium"),
    _pack("cf-ppe-purchase", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_investing",), labels=("purchase of property plant and equipment", "purchase of property, plant and equipment", "acquisition of property plant and equipment"), qname="ifrs-smes:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", concept_family="cash_flow"),
    _pack("cf-borrowing-proceeds", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_financing",), labels=("proceeds from borrowings", "drawdown of borrowings", "drawdown of term loan"), qname="ifrs-smes:ProceedsFromBorrowingsClassifiedAsFinancingActivities", concept_family="cash_flow", risk_level_hint="medium"),
    _pack("cf-borrowing-repayments", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_financing",), labels=("repayment of borrowings", "repayment of term loan", "term loan repayment"), qname="ifrs-smes:RepaymentsOfBorrowingsClassifiedAsFinancingActivities", concept_family="cash_flow", risk_level_hint="medium"),
    _pack("cf-cash-begin-end", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_reconciliation",), labels=("cash and cash equivalents at beginning", "cash and cash equivalents at end", "cash and cash equivalent at beginning", "cash and cash equivalent at the end"), qname="ifrs-smes:CashAndCashEquivalents", concept_family="cash_flow"),
    _pack("cf-net-change-cash", "cash_flow_movement_pack", statement_family="cash_flow", section_blocks=("cash_flow_reconciliation", "cash_flow_other"), labels=("net increase in cash", "net decrease in cash", "net increase decrease in cash", "net decrease increase in cash"), qname="ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents", concept_family="cash_flow"),
    _pack("equity-share-capital", "equity_movement_pack", statement_family="changes_in_equity", section_blocks=("changes_in_equity",), labels=("share capital", "issued capital"), qname="ifrs-smes:IssuedCapital", concept_family="financial_position"),
    _pack("equity-retained-earnings", "equity_movement_pack", statement_family="changes_in_equity", section_blocks=("changes_in_equity",), labels=("retained earnings", "retained profits", "accumulated losses", "accumulated loss"), qname="ifrs-smes:RetainedEarnings", concept_family="financial_position"),
    _pack("equity-profit-loss", "equity_movement_pack", statement_family="changes_in_equity", section_blocks=("changes_in_equity",), labels=("profit for the year", "loss for the year", "profit for the financial year", "loss for the financial year"), qname="ifrs-smes:ProfitLoss", concept_family="profit_loss", risk_level_hint="medium"),
    _pack("equity-comprehensive-income", "equity_movement_pack", statement_family="changes_in_equity", section_blocks=("changes_in_equity",), labels=("total comprehensive income", "total comprehensive loss"), qname="ifrs-smes:ComprehensiveIncome", concept_family="profit_loss", risk_level_hint="medium"),
    _pack("equity-total", "equity_movement_pack", statement_family="changes_in_equity", section_blocks=("changes_in_equity",), labels=("balance at beginning", "balance at end", "total equity"), qname="ifrs-smes:Equity", concept_family="financial_position", risk_level_hint="medium"),
)

NOTE_TOTAL_PACKS: tuple[dict[str, Any], ...] = tuple(
    {**pack, "source_type": "note_total_candidate", "risk_level_hint": "medium"}
    for pack in PACK_DEFINITIONS
    if pack["source_id"]
    in {
        "sfp-current-assets",
        "sfp-noncurrent-assets",
        "sfp-total-assets",
        "sfp-share-capital",
        "sfp-retained-earnings",
        "sfp-total-equity",
        "sfp-current-liabilities",
        "sfp-noncurrent-liabilities",
        "sfp-liabilities",
        "sfp-equity-liabilities",
    }
)


def discover_concept_playbook_files(root: str | Path = ".") -> list[dict[str, Any]]:
    base = Path(root)
    paths: list[Path] = []
    for pattern in DEFAULT_CONCEPT_PLAYBOOK_GLOBS:
        paths.extend(base.glob(pattern))
    unique_paths = sorted({path for path in paths if path.is_file()})
    return [{"path": str(path), "exists": True, "size_bytes": path.stat().st_size} for path in unique_paths]


def load_concept_playbook_cards(
    paths: Sequence[str | Path] | None = None,
    *,
    root: str | Path = ".",
    allow_missing: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if paths:
        files = [Path(path) for path in paths]
    else:
        files = [Path(item["path"]) for item in discover_concept_playbook_files(root)]
    missing = [str(path) for path in files if not path.exists()]
    if missing and not allow_missing:
        raise FileNotFoundError(f"Concept playbook files not found: {missing}")
    cards: dict[str, dict[str, Any]] = {}
    loaded_files = []
    unsupported_files = []
    for path in files:
        if not path.exists():
            continue
        payload = _read_json(path)
        raw_cards = payload.get("concept_cards") if isinstance(payload, Mapping) else None
        if raw_cards is None and isinstance(payload, Mapping):
            raw_cards = payload.get("cards") or payload.get("examples") or []
        if not isinstance(raw_cards, list):
            unsupported_files.append(str(path))
            continue
        loaded_files.append(str(path))
        for card in raw_cards:
            if not isinstance(card, Mapping):
                continue
            qname = str(card.get("concept_qname") or card.get("template_field_id") or card.get("qname") or "")
            if not qname:
                continue
            label = card.get("canonical_label") or card.get("concept_label") or concept_label(qname)
            aliases = _unique(
                [
                    label,
                    *(card.get("common_extracted_labels") or []),
                    *(card.get("normalized_label_patterns") or []),
                    *(card.get("accounting_synonyms") or []),
                    *(card.get("aliases") or []),
                ]
            )
            families = _statement_families_from_names(
                [
                    *(card.get("statement_families_observed") or []),
                    *(card.get("common_sections") or []),
                ]
            )
            metadata = card.get("template_metadata") if isinstance(card.get("template_metadata"), Mapping) else {}
            existing = cards.setdefault(
                qname,
                {
                    "qname": qname,
                    "concept_label": label,
                    "aliases": [],
                    "statement_families": [],
                    "concept_family": ",".join(str(value) for value in card.get("semantic_families") or []) or None,
                    "source_files": [],
                    "template_codes": [],
                },
            )
            existing["aliases"].extend(aliases)
            existing["statement_families"].extend(families)
            existing["source_files"].append(str(path))
            existing["template_codes"].extend(metadata.get("templates") or [])
    normalized_cards = []
    for card in cards.values():
        normalized_cards.append(
            {
                **card,
                "aliases": _unique(canonical_label(alias) for alias in card.get("aliases") or [] if not _is_generic_label(canonical_label(alias))),
                "statement_families": _unique(card.get("statement_families") or []),
                "source_files": _unique(card.get("source_files") or []),
                "template_codes": _unique(card.get("template_codes") or []),
            }
        )
    diagnostics = {
        "status": "loaded" if normalized_cards else "missing_allowed" if allow_missing else "missing",
        "discovered_files": discover_concept_playbook_files(root),
        "loaded_files": loaded_files,
        "missing_files": missing,
        "unsupported_files": unsupported_files,
        "concept_card_count": len(normalized_cards),
    }
    return normalized_cards, diagnostics


def _entry_matches(record: Mapping[str, Any], entry: Mapping[str, Any], *, note_total: bool = False) -> tuple[bool, float, list[str]]:
    ctx = _context(record)
    row_family = str(ctx.get("statement_family") or "")
    section = str(ctx.get("section_block") or "")
    row_role = str(ctx.get("row_role") or "")
    text = _label_text(record)
    label = _label(record)
    if not label or _is_noisy_label(text):
        return False, 0.0, []
    if entry.get("statement_family") and row_family != entry.get("statement_family") and not note_total:
        return False, 0.0, []
    sections = set(entry.get("section_blocks") or [])
    if sections and section not in sections and not note_total:
        return False, 0.0, []
    roles = set(entry.get("row_roles") or [])
    if roles and row_role not in roles:
        return False, 0.0, []
    if entry.get("required_terms") and not _contains_any(text, entry.get("required_terms") or []):
        return False, 0.0, []
    if entry.get("blocked_terms") and _contains_any(text, entry.get("blocked_terms") or []):
        return False, 0.0, []
    if _is_generic_label(label) and row_role not in {"total", "subtotal"} and not note_total:
        return False, 0.0, []

    aliases = [canonical_label(alias) for alias in entry.get("labels") or []]
    exact = next((alias for alias in aliases if label == alias), None)
    if exact:
        return True, 1.0, [f"local_pack:{entry.get('source_id')}", f"exact_label:{exact}"]
    if _contains_any(text, aliases):
        matched = next(alias for alias in aliases if alias and alias in text)
        base_score = float(entry.get("score") or 0.78)
        return True, max(0.72, min(0.95, base_score)), [f"local_pack:{entry.get('source_id')}", f"contains_label:{matched}"]
    return False, 0.0, []


def _spec_from_entry(record: Mapping[str, Any], entry: Mapping[str, Any], *, score: float, reasons: Sequence[str]) -> dict[str, Any]:
    ctx = _context(record)
    source_type = str(entry.get("source_type") or "local_concept_family_pack")
    evidence = {
        "label_similarity": score,
        "statement_family_match": bool(entry.get("statement_family") == ctx.get("statement_family") or source_type == "note_total_candidate"),
        "section_context_match": bool(ctx.get("section_block") in set(entry.get("section_blocks") or []) or source_type == "note_total_candidate"),
        "row_role_match": bool(ctx.get("row_role") in {"component", "subtotal", "total"} or source_type == "note_total_candidate"),
        "template_match": False,
        "note_link_match": source_type == "note_total_candidate",
        "format_memory_match": source_type == "format_memory_pack",
        "dictionary_match": False,
        "row_order_match": False,
        "local_structured_match": True,
        "local_candidate_source_type": source_type,
    }
    return {
        "qname": entry.get("qname"),
        "concept_label": entry.get("concept_label") or concept_label(entry.get("qname")),
        "candidate_source": source_type,
        "source_type": source_type,
        "source_id": entry.get("source_id"),
        "concept_family": entry.get("concept_family"),
        "statement_families": _unique([entry.get("statement_family")]),
        "compatible_statement_families": _unique([entry.get("statement_family")]),
        "evidence": evidence,
        "match_reasons": _unique([*reasons, "local_non_lexical_source"]),
        "blocking_reasons": ["local_candidate_requires_review"],
        "ambiguity_reasons": [],
        "risk_level_hint": entry.get("risk_level_hint") or "low",
        "requires_human_review": True,
        "safe_for_auto_apply": False,
    }


def _pack_specs(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    boundary = record.get("note_boundary") if isinstance(record.get("note_boundary"), Mapping) else classify_note_detail_boundary(_context(record))
    if boundary.get("is_note_detail_row") or boundary.get("is_note_movement_row") or boundary.get("is_note_reconciliation_row"):
        return []
    note_total = bool(boundary.get("is_note_summary_row") and boundary.get("can_support_main_statement_mapping"))
    entries = NOTE_TOTAL_PACKS if note_total else PACK_DEFINITIONS
    specs = []
    for entry in entries:
        matched, score, reasons = _entry_matches(record, entry, note_total=note_total)
        if not matched:
            continue
        if note_total:
            reasons = [*reasons, "note_summary_boundary_can_support_main_statement"]
        specs.append(_spec_from_entry(record, entry, score=score, reasons=reasons))
    return specs


def _playbook_specs(record: Mapping[str, Any], concept_cards: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not concept_cards:
        return []
    boundary = record.get("note_boundary") if isinstance(record.get("note_boundary"), Mapping) else classify_note_detail_boundary(_context(record))
    if boundary.get("is_note_detail_row") or boundary.get("is_note_movement_row") or boundary.get("is_note_reconciliation_row"):
        return []
    ctx = _context(record)
    row_family = str(ctx.get("statement_family") or "")
    label = _label(record)
    text = _label_text(record)
    if not label or _is_noisy_label(text):
        return []
    specs = []
    for card in concept_cards:
        qname = str(card.get("qname") or "")
        if not qname:
            continue
        families = set(str(value) for value in card.get("statement_families") or [] if value)
        if families and row_family and row_family not in families:
            continue
        best_ratio = 0.0
        best_alias = None
        exact = False
        for alias in card.get("aliases") or []:
            alias_norm = canonical_label(alias)
            if not alias_norm or _is_generic_label(alias_norm):
                continue
            ratio = float(label_similarity(label, alias_norm).get("ratio") or 0.0)
            if label == alias_norm:
                ratio = 1.0
                exact = True
            elif alias_norm in text or label in alias_norm:
                ratio = max(ratio, min(0.94, max(0.72, min(len(alias_norm), len(label)) / max(len(alias_norm), len(label)))))
            if ratio > best_ratio:
                best_ratio = ratio
                best_alias = alias_norm
        if best_ratio < (0.99 if _is_generic_label(label) else 0.72):
            continue
        source_id = f"concept-playbook:{qname}"
        entry = {
            "source_id": source_id,
            "source_type": "concept_playbook_lookup",
            "statement_family": row_family or None,
            "section_blocks": [ctx.get("section_block")] if ctx.get("section_block") else [],
            "qname": qname,
            "concept_label": card.get("concept_label") or concept_label(qname),
            "concept_family": card.get("concept_family") or "unknown",
            "risk_level_hint": "medium" if not exact else "low",
        }
        specs.append(
            _spec_from_entry(
                record,
                entry,
                score=best_ratio,
                reasons=[
                    source_id,
                    f"concept_playbook_alias:{best_alias}",
                    f"concept_playbook_files:{','.join(card.get('source_files') or [])}",
                ],
            )
        )
    return specs


def _taxonomy_structure_specs(record: Mapping[str, Any], concepts: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Use only explicit local structure hints; avoid fuzzy taxonomy search."""
    if not concepts:
        return []
    ctx = _context(record)
    row_family = str(ctx.get("statement_family") or "")
    section = str(ctx.get("section_block") or "")
    row_role = str(ctx.get("row_role") or "")
    label = _label(record)
    if not row_family or not section or row_role not in {"total", "subtotal"}:
        return []
    hints = []
    for concept in concepts:
        qname = str(concept.get("qname") or "")
        if not qname:
            continue
        parent = normalize_label(concept.get("parent") or "")
        families = set(str(value) for value in concept.get("compatible_statement_families") or concept.get("statement_families") or [] if value)
        concept_text = normalize_label(" ".join([concept.get("concept_label") or concept_label(qname), parent, str(concept.get("concept_family") or "")]))
        if families and row_family not in families:
            continue
        if section == "current_assets" and "current assets" in label and "current assets" in concept_text:
            hints.append((qname, concept))
        elif section == "current_liabilities" and "current liabilities" in label and "current liabilities" in concept_text:
            hints.append((qname, concept))
        elif section == "equity" and "total equity" in label and "equity" in concept_text:
            hints.append((qname, concept))
    specs = []
    for qname, concept in hints[:2]:
        entry = {
            "source_id": f"taxonomy-structure:{qname}",
            "source_type": "taxonomy_structure_hint",
            "statement_family": row_family,
            "section_blocks": [section],
            "qname": qname,
            "concept_label": concept.get("concept_label") or concept_label(qname),
            "concept_family": concept.get("concept_family") or "unknown",
            "risk_level_hint": "medium",
        }
        specs.append(_spec_from_entry(record, entry, score=0.82, reasons=[f"taxonomy_structure_hint:{section}"]))
    return specs


def generate_local_candidate_specs(
    record: Mapping[str, Any],
    *,
    concept_cards: Sequence[Mapping[str, Any]] = (),
    concepts: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    if record.get("pdf_value") in (None, "") and record.get("value") in (None, ""):
        return []
    specs = [
        *_pack_specs(record),
        *_playbook_specs(record, concept_cards),
        *_taxonomy_structure_specs(record, concepts),
    ]
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for spec in specs:
        source = str(spec.get("candidate_source") or spec.get("source_type") or "")
        qname = str(spec.get("qname") or "")
        if source not in SOURCE_TYPES or not qname:
            continue
        key = (qname, source)
        existing = by_key.get(key)
        if existing is None or float((spec.get("evidence") or {}).get("label_similarity") or 0.0) > float((existing.get("evidence") or {}).get("label_similarity") or 0.0):
            by_key[key] = dict(spec)
    return list(by_key.values())[:8]


def build_local_candidate_sources_report(
    rows: Sequence[Mapping[str, Any]],
    *,
    concept_cards: Sequence[Mapping[str, Any]] = (),
    concept_card_diagnostics: Mapping[str, Any] | None = None,
    concepts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    source_counts: Counter[str] = Counter()
    source_row_counts: Counter[str] = Counter()
    qname_counts: Counter[str] = Counter()
    label_counts: Counter[str] = Counter()
    rows_with_specs = []
    for row in rows:
        specs = generate_local_candidate_specs(row, concept_cards=concept_cards, concepts=concepts)
        if not specs:
            continue
        row_sources = set()
        for spec in specs:
            source = str(spec.get("candidate_source") or spec.get("source_type") or "unknown")
            source_counts[source] += 1
            qname_counts[str(spec.get("qname") or "")] += 1
            row_sources.add(source)
        for source in row_sources:
            source_row_counts[source] += 1
        label_counts[str(row.get("normalized_label") or canonical_label(row.get("pdf_label")))] += 1
        rows_with_specs.append(
            {
                "sample_id": row.get("sample_id"),
                "row_id": row.get("row_id") or row.get("pdf_row_id"),
                "normalized_label": row.get("normalized_label") or canonical_label(row.get("pdf_label")),
                "statement_family": row.get("statement_family"),
                "section_block": row.get("section_block"),
                "row_role": row.get("row_role"),
                "baseline_candidate_count": row.get("candidate_count"),
                "local_candidate_specs": specs,
            }
        )
    return sanitize_report_value(
        {
            "run_metadata": {"feature": "18E-F-A-2", "generated_at": utc_now(), "offline_only": True, **SAFETY},
            "summary": {
                "rows_considered": len(rows),
                "rows_with_local_candidates": len(rows_with_specs),
                "local_candidate_count": sum(source_counts.values()),
                "source_types_enabled": sorted(SOURCE_TYPES),
                "candidate_source_counts": dict(sorted(source_counts.items())),
                "candidate_source_row_counts": dict(sorted(source_row_counts.items())),
                "top_qnames": [{"qname": key, "count": count} for key, count in qname_counts.most_common(30) if key],
                "top_labels_with_local_candidates": [
                    {"normalized_label": key, "count": count} for key, count in label_counts.most_common(30) if key
                ],
                "concept_cards": dict(concept_card_diagnostics or {}),
                "taxonomy_structure": {
                    "concepts_considered": len(concepts),
                    "presentation_or_calculation_tree_available": any(item.get("parent") or item.get("children") for item in concepts),
                    "minimal_qname_concept_family_hints_used": bool(concepts),
                },
                "safe_for_auto_apply_count": 0,
                "requires_human_review": True,
                "safety": dict(SAFETY),
            },
            "rows_with_local_candidates": rows_with_specs[:300],
        }
    )


def render_local_candidate_sources_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    concept_cards = summary.get("concept_cards") or {}
    lines = [
        "# Local Candidate Sources #18E-F-A-2",
        "",
        "Offline non-lexical candidate sources only. All output is review-required.",
        "",
        f"- Rows considered: `{summary.get('rows_considered')}`",
        f"- Rows with local candidates: `{summary.get('rows_with_local_candidates')}`",
        f"- Local candidate count: `{summary.get('local_candidate_count')}`",
        f"- Source counts: `{summary.get('candidate_source_counts')}`",
        f"- Concept card status: `{concept_cards.get('status')}`",
        f"- Concept cards loaded: `{concept_cards.get('concept_card_count')}`",
        f"- Loaded concept card files: `{concept_cards.get('loaded_files')}`",
        f"- safe_for_auto_apply_count: `{summary.get('safe_for_auto_apply_count')}`",
        "",
        "| Label | Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("top_labels_with_local_candidates") or []:
        lines.append(f"| {item.get('normalized_label')} | {item.get('count')} |")
    return "\n".join(lines) + "\n"
