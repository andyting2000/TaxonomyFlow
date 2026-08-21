"""Local concept metadata enrichment for Azure DI mapping refinement."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_TEMPLATE_FILE = Path("mpers_templates.json")
DEFAULT_REFERENCE_REPORT = Path("reports/reference_xbrl_report_20260511T082343Z.json")
DEFAULT_OUTPUT_DIR = Path("reports")

STOPWORDS = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "that",
    "this",
    "are",
    "was",
    "were",
    "has",
    "have",
    "been",
    "company",
    "financial",
    "statements",
    "statement",
    "notes",
    "note",
    "year",
    "period",
    "total",
}

SECTION_PATTERNS = [
    ("statement_by_directors", re.compile(r"statement\s+by\s+directors|section\s+251", re.IGNORECASE)),
    (
        "directors_report",
        re.compile(
            r"directors?'?\s+report|directors?\s+hereby\s+submit|directors?\s+in\s+office|"
            r"directors?'?\s+shareholdings|directors?'?\s+benefits|indemnity.*insurance|"
            r"other\s+statutory\s+information|this\s+report\s+was\s+approved\s+by\s+the\s+board|"
            r"results\s+of\s+the\s+operations|proper\s+action\s+had\s+been\s+taken|contingent\s+liability",
            re.IGNORECASE,
        ),
    ),
    ("statutory_declaration", re.compile(r"statutory\s+declaration", re.IGNORECASE)),
    ("corporate_information", re.compile(r"corporate\s+information|registered\s+office|principal\s+place", re.IGNORECASE)),
    ("accounting_policies", re.compile(r"accounting\s+polic|basis\s+of\s+preparation|financial\s+instruments", re.IGNORECASE)),
    ("cash_flows", re.compile(r"cash\s+flows?|cash\s+and\s+cash\s+equivalents|working\s+capital", re.IGNORECASE)),
    ("changes_in_equity", re.compile(r"changes\s+in\s+equity|share\s+capital|retained|accumulated", re.IGNORECASE)),
    ("comprehensive_income", re.compile(r"comprehensive\s+income|profit|loss|tax|expense|income", re.IGNORECASE)),
    ("financial_position", re.compile(r"financial\s+position|assets?|liabilit|equity|receivable|payable|overdraft", re.IGNORECASE)),
    ("notes", re.compile(r"notes?\s+to\s+the\s+financial\s+statements|disclosure", re.IGNORECASE)),
]


CURATED_ALIAS_GROUPS: list[dict[str, Any]] = [
    {
        "name": "directors_report",
        "aliases": [
            "Directors' Report",
            "Director's Report",
            "Directors Report",
            "report of the directors",
            "directors hereby submit their report",
            "directors in office",
            "directors benefits",
            "directors interests",
            "directors shareholdings",
            "other statutory information",
            "directors report narrative",
            "report approved by the board of directors",
        ],
        "target_local_names": ["DisclosureOfDirectorsReportExplanatory"],
        "statement_family": "directors_report",
        "concept_family": "directors_report",
        "expected_type": "text_block",
    },
    {
        "name": "statement_by_directors",
        "aliases": [
            "Statement by Directors",
            "statement by directors pursuant to section 251",
            "directors opinion",
            "true and fair view statement",
        ],
        "target_local_names": ["DisclosureOfStatementByDirectorsExplanatory"],
        "statement_family": "statement_by_directors",
        "concept_family": "statement_by_directors",
        "expected_type": "text_block",
    },
    {
        "name": "statutory_declaration",
        "aliases": ["Statutory Declaration", "statutory declaration narrative"],
        "target_local_names": ["DateOfStatutoryDeclaration"],
        "statement_family": "statutory_declaration",
        "concept_family": "statutory_declaration",
        "expected_type": "metadata",
    },
    {
        "name": "corporate_information",
        "aliases": [
            "Corporate Information",
            "private company incorporated and domiciled",
            "registered office",
            "principal place of business",
            "financial statements were authorised for issue",
        ],
        "target_local_names": ["DisclosureOfCorporateInformationExplanatory"],
        "statement_family": "corporate_information",
        "concept_family": "corporate_information",
        "expected_type": "text_block",
    },
    {
        "name": "basis_of_preparation",
        "aliases": [
            "Basis of Preparation",
            "financial statements have been prepared in compliance",
            "prepared using historical cost",
            "basis of preparation of financial statements",
        ],
        "target_local_names": [
            "DisclosureOfBasisOfPreparationOfFinancialStatementsExplanatory",
            "DescriptionOfAccountingPolicyForBasisOfPresentationOfFinancialStatementsExplanatory",
        ],
        "statement_family": "accounting_policies",
        "concept_family": "basis_of_preparation",
        "expected_type": "text_block",
    },
    {
        "name": "financial_instruments_policy",
        "aliases": [
            "financial assets",
            "financial liabilities",
            "exchange financial assets or financial liabilities",
            "subsequent measurement financial assets",
            "transaction costs of an equity transaction",
            "short-term other receivable discounting",
        ],
        "target_local_names": [
            "DisclosureOfFinancialInstrumentsExplanatory",
            "DescriptionOfAccountingPolicyForFinancialInstrumentsExplanatory",
            "DisclosureOfTradeAndOtherReceivablesExplanatory",
        ],
        "statement_family": "accounting_policies",
        "concept_family": "financial_instruments",
        "expected_type": "text_block",
    },
    {
        "name": "principal_activity",
        "aliases": ["Principal Activity", "principal activities", "principally engaged", "business as insurance agent"],
        "target_label_patterns": [r"principal\s+activit", r"nature\s+of\s+operations"],
        "statement_family": "corporate_information",
        "concept_family": "principal_activity",
        "expected_type": "text_block",
    },
    {
        "name": "share_capital",
        "aliases": ["Share Capital", "Contributed Share Capital", "Capital from ordinary shares", "ordinary shares issued"],
        "target_local_names": ["CapitalFromOrdinaryShares", "DisclosureOfClassesOfShareCapitalExplanatory"],
        "statement_family": "financial_position",
        "concept_family": "share_capital",
        "expected_type": "numeric_or_text",
    },
    {
        "name": "retained_earnings",
        "aliases": ["Retained Earnings", "Accumulated loss", "Accumulated losses", "capital deficiency"],
        "target_local_names": ["RetainedEarnings", "IncreaseDecreaseInRetainedEarnings"],
        "statement_family": "financial_position",
        "concept_family": "retained_earnings",
        "expected_type": "numeric",
    },
    {
        "name": "other_receivables",
        "aliases": ["Other receivable", "Other receivables", "Trade receivables", "Decrease in receivable"],
        "target_local_names": [
            "OtherCurrentReceivables",
            "OtherReceivables",
            "TradeAndOtherCurrentReceivables",
            "TradeAndOtherReceivables",
            "AdjustmentsForDecreaseIncreaseInOtherOperatingReceivables",
        ],
        "statement_family": "financial_position",
        "concept_family": "receivables",
        "expected_type": "numeric_or_text",
    },
    {
        "name": "other_payables",
        "aliases": ["Other payable", "Other payables", "Trade payables", "Decrease in payable"],
        "target_local_names": [
            "OtherCurrentPayables",
            "OtherPayables",
            "TradeAndOtherCurrentPayables",
            "TradeAndOtherPayables",
            "AdjustmentsForIncreaseDecreaseInTradeAndOtherPayables",
        ],
        "statement_family": "financial_position",
        "concept_family": "payables",
        "expected_type": "numeric_or_text",
    },
    {
        "name": "director_account",
        "aliases": ["Amount due to director", "Amount owing to directors", "Increase in director's account"],
        "target_label_patterns": [r"amount\s+(due|owing)\s+to\s+directors?", r"director'?s?\s+account"],
        "statement_family": "financial_position",
        "concept_family": "director_account",
        "expected_type": "numeric",
    },
    {
        "name": "bank_overdraft",
        "aliases": ["Bank overdraft", "Bank overdraft - unsecured", "Unsecured bank overdraft"],
        "target_local_names": [
            "CurrentPortionOfNoncurrentUnsecuredBankOverdrafts",
            "UnsecuredBankOverdrafts",
            "BankOverdraftsClassifiedAsCashEquivalents",
        ],
        "statement_family": "financial_position",
        "concept_family": "cash_and_overdraft",
        "expected_type": "numeric_or_text",
    },
    {
        "name": "administrative_expenses",
        "aliases": ["Administrative Expenses", "Administration expenses"],
        "target_local_names": ["AdministrativeExpense"],
        "statement_family": "comprehensive_income",
        "concept_family": "expenses",
        "expected_type": "numeric",
    },
    {
        "name": "tax_expense",
        "aliases": ["Tax Expense", "Income Tax Expense"],
        "target_local_names": ["IncomeTaxExpenseContinuingOperations"],
        "statement_family": "comprehensive_income",
        "concept_family": "tax",
        "expected_type": "numeric",
    },
    {
        "name": "profit_loss_before_tax",
        "aliases": ["Profit Before Tax", "Loss Before Tax", "Profit/loss before tax", "Loss before tax"],
        "target_local_names": ["AggregateProfitLossBeforeTax", "ProfitLossBeforeTax"],
        "statement_family": "comprehensive_income",
        "concept_family": "profit_loss",
        "expected_type": "numeric",
    },
    {
        "name": "profit_loss_after_tax",
        "aliases": ["Profit After Tax", "Loss After Tax", "Profit/loss for the financial year", "Net Profit", "Net Loss"],
        "target_local_names": ["AggregateProfitLoss", "ProfitLoss"],
        "statement_family": "comprehensive_income",
        "concept_family": "profit_loss",
        "expected_type": "numeric",
    },
    {
        "name": "other_comprehensive_income",
        "aliases": ["Other Comprehensive Income", "Other comprehensive income for the year"],
        "target_local_names": ["OtherComprehensiveIncome"],
        "statement_family": "comprehensive_income",
        "concept_family": "other_comprehensive_income",
        "expected_type": "numeric",
    },
    {
        "name": "cash_and_cash_equivalents",
        "aliases": [
            "Cash and bank balances",
            "Cash and cash equivalents",
            "Cash and cash equivalents at end of year",
            "cash equivalents at end of year",
        ],
        "target_local_names": ["CashAndBankBalances", "CashAndCashEquivalents", "DisclosureOfCashAndCashEquivalentsExplanatory"],
        "statement_family": "cash_flows",
        "concept_family": "cash_and_overdraft",
        "expected_type": "numeric_or_text",
    },
]


@dataclass(frozen=True)
class EnrichmentOutputPaths:
    enrichment_json: Path
    enrichment_md: Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text(value: Any) -> str:
    text = clean_text(value).lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def split_camel(value: Any) -> str:
    local = str(value or "").split(":")[-1]
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", local)


def token_set(value: Any) -> set[str]:
    return {token for token in normalize_text(value).split() if len(token) >= 3 and token not in STOPWORDS}


def local_name(qname: Any) -> str:
    return str(qname or "").strip().split(":")[-1]


def infer_statement_family(value: Any) -> str:
    text = clean_text(value)
    for family, pattern in SECTION_PATTERNS:
        if pattern.search(text):
            return family
    return "unknown"


def infer_concept_type(qname: Any, label: Any, source_type: Any = None) -> tuple[str, bool | str, bool | str]:
    local = local_name(qname)
    local_norm = local.lower()
    text = normalize_text(f"{label} {local} {source_type or ''}")
    if "text block" in text or "textblock" in text or local_norm.endswith("explanatory") or "explanatory" in text:
        return "text_block", False, True
    if re.search(r"(axis|member|abstract|table|lineitems|domain)$", local_norm):
        return "structural", False, False
    if re.match(r"^(date|name|type|identification|description|method|disclosurewhether|numberof)", local_norm):
        return "string_or_metadata", False, False
    if text.startswith(("date ", "name ", "type ", "description ", "method ", "number ")):
        return "string_or_metadata", False, False
    if "disclosure " in text and "text block" not in text and "textblock" not in text:
        return "string_or_metadata", False, False
    return "numeric", True, False


def _base_aliases(qname: str, label: str, template_description: str | None = None) -> list[str]:
    aliases = {
        normalize_text(label),
        normalize_text(local_name(qname)),
        normalize_text(split_camel(qname)),
    }
    if template_description:
        aliases.add(normalize_text(template_description))
    return sorted(alias for alias in aliases if alias)


def _alias_record(alias: str, *, source: str, group: str | None = None, strength: float = 0.6) -> dict[str, Any]:
    return {
        "alias": clean_text(alias),
        "normalized_alias": normalize_text(alias),
        "source": source,
        "group": group,
        "strength": round(float(strength), 3),
    }


def _concept_from_template(code: str, template_description: str, concept: Mapping[str, Any]) -> dict[str, Any] | None:
    qname = clean_text(concept.get("id") or concept.get("qname"))
    if not qname:
        return None
    label = clean_text(concept.get("label") or qname)
    concept_type, is_numeric, is_text_block = infer_concept_type(qname, label, concept.get("type"))
    aliases = _base_aliases(qname, label, template_description)
    alias_records = [_alias_record(alias, source="template_label", strength=0.55) for alias in aliases]
    family_text = f"{template_description} {label} {qname}"
    return {
        "concept_qname": qname,
        "concept_label": label,
        "normalized_label": normalize_text(label),
        "aliases": aliases,
        "alias_records": alias_records,
        "token_set": sorted(token_set(f"{label} {split_camel(qname)}")),
        "concept_family": infer_statement_family(family_text),
        "statement_family": infer_statement_family(family_text),
        "concept_type": str(concept.get("type") or concept_type),
        "is_numeric_concept": is_numeric,
        "is_text_block_concept": is_text_block,
        "source_metadata": {
            "source": "mpers_templates.json",
            "template_code": code,
            "template_description": template_description,
            "namespace": concept.get("namespace"),
            "required": bool(concept.get("required", False)),
            "position": concept.get("position"),
            "parent": concept.get("parent"),
        },
        "source": "mpers_templates.json",
        "template_code": code,
        "template_description": template_description,
        "enrichment_warnings": [],
    }


def load_template_concepts(template_path: str | Path = DEFAULT_TEMPLATE_FILE) -> tuple[list[dict[str, Any]], list[str]]:
    path = Path(template_path)
    warnings: list[str] = []
    if not path.exists():
        return [], [f"Local template metadata file not found: {path}"]
    data = json.loads(path.read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    for code, template in (data.get("templates") or {}).items():
        description = clean_text(template.get("description") or code)
        for concept in template.get("concepts") or []:
            record = _concept_from_template(str(code), description, concept)
            if record:
                records.append(record)
    return records, warnings


def load_reference_inventory(reference_report_path: str | Path | None) -> tuple[list[dict[str, Any]], list[str]]:
    if not reference_report_path:
        return [], []
    path = Path(reference_report_path)
    if not path.exists():
        return [], [f"Reference report not found: {path}"]
    data = json.loads(path.read_text(encoding="utf-8"))
    concepts: dict[str, dict[str, Any]] = {}
    for case in data.get("case_reports") or []:
        for fact in case.get("facts") or []:
            qname = clean_text(fact.get("qname") or fact.get("concept") or fact.get("concept_qname"))
            if not qname or qname in concepts:
                continue
            label = clean_text(fact.get("label") or fact.get("local_name") or split_camel(qname))
            concept_type, is_numeric, is_text_block = infer_concept_type(qname, label)
            concepts[qname] = {
                "concept_qname": qname,
                "concept_label": label,
                "normalized_label": normalize_text(label),
                "aliases": _base_aliases(qname, label),
                "alias_records": [_alias_record(alias, source="reference_inventory_label", strength=0.45) for alias in _base_aliases(qname, label)],
                "token_set": sorted(token_set(f"{label} {split_camel(qname)}")),
                "concept_family": infer_statement_family(f"{label} {qname}"),
                "statement_family": infer_statement_family(f"{label} {qname}"),
                "concept_type": concept_type,
                "is_numeric_concept": bool(fact.get("is_numeric")) if fact.get("is_numeric") is not None else is_numeric,
                "is_text_block_concept": bool(fact.get("is_text_block")) if fact.get("is_text_block") is not None else is_text_block,
                "source_metadata": {"source": "reference_report_concept_inventory"},
                "source": "reference_report_concept_inventory",
                "template_code": None,
                "template_description": None,
                "enrichment_warnings": ["reference_inventory_only_not_answer_key"],
            }
    return list(concepts.values()), [
        "Reference report was used only as an offline concept inventory fallback, not as a direct answer key."
    ]


def _group_targets(group: Mapping[str, Any], concepts: Mapping[str, dict[str, Any]]) -> list[str]:
    targets: list[str] = []
    local_targets = {str(item) for item in group.get("target_local_names") or []}
    label_patterns = [re.compile(str(pattern), re.IGNORECASE) for pattern in group.get("target_label_patterns") or []]
    for qname, concept in concepts.items():
        if local_name(qname) in local_targets:
            targets.append(qname)
            continue
        haystack = f"{concept.get('concept_label')} {split_camel(qname)} {qname}"
        if any(pattern.search(haystack) for pattern in label_patterns):
            targets.append(qname)
    return sorted(set(targets))


def apply_curated_aliases(concepts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Counter[str]]:
    by_qname = {str(concept["concept_qname"]): dict(concept) for concept in concepts if concept.get("concept_qname")}
    unresolved: list[dict[str, Any]] = []
    group_counts: Counter[str] = Counter()
    for group in CURATED_ALIAS_GROUPS:
        targets = _group_targets(group, by_qname)
        if not targets:
            unresolved.append(
                {
                    "alias_group": group["name"],
                    "aliases": list(group.get("aliases") or []),
                    "reason": "no_existing_local_concept_qname_matched_group",
                }
            )
            continue
        for qname in targets:
            concept = by_qname[qname]
            concept["concept_family"] = group.get("concept_family") or concept.get("concept_family") or "unknown"
            if group.get("statement_family"):
                concept["statement_family"] = group["statement_family"]
            if group.get("expected_type") == "text_block":
                concept["is_text_block_concept"] = True
                concept["is_numeric_concept"] = False
                concept["concept_type"] = "text_block"
            elif group.get("expected_type") == "numeric":
                concept["is_numeric_concept"] = True
                concept["is_text_block_concept"] = False
                concept.setdefault("concept_type", "numeric")
            existing_aliases = {normalize_text(alias) for alias in concept.get("aliases") or []}
            alias_records = list(concept.get("alias_records") or [])
            for alias in group.get("aliases") or []:
                normalized = normalize_text(alias)
                if not normalized or normalized in existing_aliases:
                    continue
                concept.setdefault("aliases", []).append(normalized)
                alias_records.append(_alias_record(alias, source="curated_14a_alias", group=str(group["name"]), strength=0.95))
                existing_aliases.add(normalized)
                group_counts[str(group["name"])] += 1
            concept["alias_records"] = alias_records
            concept["token_set"] = sorted(token_set(" ".join([concept.get("concept_label", ""), *concept.get("aliases", [])])))
    return list(by_qname.values()), unresolved, group_counts


def merge_concept_sources(primary: Iterable[dict[str, Any]], fallback: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {str(concept["concept_qname"]): dict(concept) for concept in primary if concept.get("concept_qname")}
    for concept in fallback:
        qname = str(concept.get("concept_qname") or "")
        if not qname or qname in merged:
            continue
        merged[qname] = dict(concept)
    return list(merged.values())


def build_enriched_concept_metadata(
    *,
    local_concepts: list[dict[str, Any]] | None = None,
    template_path: str | Path = DEFAULT_TEMPLATE_FILE,
    reference_report_path: str | Path | None = None,
    run_id: str | None = None,
    input_paths: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    warnings: list[str] = []
    if local_concepts is None:
        template_concepts, template_warnings = load_template_concepts(template_path)
        warnings.extend(template_warnings)
    else:
        template_concepts = [normalize_external_concept(concept) for concept in local_concepts]
    reference_concepts, reference_warnings = load_reference_inventory(reference_report_path)
    warnings.extend(reference_warnings)
    merged = merge_concept_sources(template_concepts, reference_concepts)
    enriched, unresolved_aliases, alias_counts = apply_curated_aliases(merged)
    report = build_enrichment_report(
        enriched_concepts=enriched,
        unresolved_aliases=unresolved_aliases,
        alias_counts=alias_counts,
        warnings=warnings,
        input_paths=input_paths or {
            "template_file": str(template_path),
            "reference_report": str(reference_report_path) if reference_report_path else None,
        },
        run_id=run_id,
    )
    return enriched, report


def normalize_external_concept(concept: Mapping[str, Any]) -> dict[str, Any]:
    qname = clean_text(concept.get("concept_qname") or concept.get("id") or concept.get("qname"))
    label = clean_text(concept.get("concept_label") or concept.get("label") or qname)
    concept_type, inferred_numeric, inferred_text = infer_concept_type(qname, label, concept.get("concept_type"))
    is_text_block = bool(concept.get("is_text_block_concept")) or inferred_text is True
    is_numeric = (bool(concept.get("is_numeric_concept")) or inferred_numeric is True) and not is_text_block
    aliases = [normalize_text(alias) for alias in (concept.get("aliases") or [])]
    aliases.extend(_base_aliases(qname, label, clean_text(concept.get("template_description"))))
    aliases = sorted(set(alias for alias in aliases if alias))
    alias_records = list(concept.get("alias_records") or [])
    if not alias_records:
        alias_records = [_alias_record(alias, source="fixture_or_local_metadata", strength=0.55) for alias in aliases]
    family_text = f"{concept.get('template_description') or ''} {label} {qname}"
    return {
        "concept_qname": qname,
        "concept_label": label,
        "normalized_label": normalize_text(label),
        "aliases": aliases,
        "alias_records": alias_records,
        "token_set": sorted(token_set(f"{label} {' '.join(aliases)}")),
        "concept_family": concept.get("concept_family") or infer_statement_family(family_text),
        "statement_family": concept.get("statement_family") or infer_statement_family(family_text),
        "concept_type": concept.get("concept_type") or concept_type,
        "is_numeric_concept": is_numeric,
        "is_text_block_concept": is_text_block,
        "source_metadata": dict(concept.get("source_metadata") or {"source": concept.get("source") or "local_fixture"}),
        "source": concept.get("source") or (concept.get("source_metadata") or {}).get("source") or "local_fixture",
        "template_code": concept.get("template_code"),
        "template_description": concept.get("template_description"),
        "enrichment_warnings": list(concept.get("enrichment_warnings") or []),
    }


def no_side_effect_metadata() -> dict[str, Any]:
    return {
        "feature": "14A",
        "generated_at": utc_now_iso(),
        "read_only": True,
        "database_mutated": False,
        "db_schema_changed": False,
        "migration_created": False,
        "api_routes_implemented": False,
        "frontend_code_modified": False,
        "production_behavior_changed": False,
        "production_extraction_behavior_changed": False,
        "production_mapping_behavior_changed": False,
        "taxonomy_mapping_performed": False,
        "final_mapping_approved": False,
        "semantic_matcher_called": False,
        "production_semantic_matcher_called": False,
        "embeddings_used": False,
        "xbrl_generated": False,
        "arelle_validation_run": False,
        "azure_di_live_call_made": False,
        "live_huggingface_calls_made": False,
        "live_openai_calls_made": False,
        "external_provider_calls": False,
        "reference_xml_sent_to_model": False,
        "reference_xml_sent_to_provider": False,
    }


def build_enrichment_report(
    *,
    enriched_concepts: list[Mapping[str, Any]],
    unresolved_aliases: list[dict[str, Any]],
    alias_counts: Counter[str],
    warnings: list[str],
    input_paths: Mapping[str, Any],
    run_id: str | None,
) -> dict[str, Any]:
    families = Counter(str(concept.get("concept_family") or "unknown") for concept in enriched_concepts)
    source_counts = Counter(str((concept.get("source_metadata") or {}).get("source") or concept.get("source") or "unknown") for concept in enriched_concepts)
    alias_count = sum(len(concept.get("aliases") or []) for concept in enriched_concepts)
    text_count = sum(1 for concept in enriched_concepts if concept.get("is_text_block_concept") is True)
    numeric_count = sum(1 for concept in enriched_concepts if concept.get("is_numeric_concept") is True)
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_concept_metadata_enrichment",
            "script": "scripts/refine_azure_di_mapping_candidates_14a.py",
        },
        "input_reports": dict(input_paths),
        "concept_sources_used": dict(source_counts),
        "concept_count": len(enriched_concepts),
        "alias_count": alias_count,
        "curated_alias_count": sum(alias_counts.values()),
        "curated_aliases_by_group": dict(sorted(alias_counts.items())),
        "unresolved_alias_count": len(unresolved_aliases),
        "unresolved_aliases": unresolved_aliases,
        "numeric_concept_count": numeric_count,
        "text_block_concept_count": text_count,
        "concept_families": dict(sorted(families.items())),
        "metadata_limitations": [
            *warnings,
            "Aliases attach only to qnames discovered in local template metadata or optional reference concept inventory.",
            "No fake concept qnames are created.",
            "Reference report, when provided, is used only as offline concept inventory and not as a direct answer key.",
        ],
    }


def build_refinement_comparison_report(
    *,
    baseline_candidates_report: Mapping[str, Any],
    baseline_confidence_report: Mapping[str, Any],
    refined_candidates_report: Mapping[str, Any],
    enrichment_report: Mapping[str, Any],
    input_paths: Mapping[str, Any],
    run_id: str | None,
) -> dict[str, Any]:
    baseline_records = {record.get("mapping_input_id"): record for record in baseline_candidates_report.get("mapping_records") or []}
    refined_records = {record.get("mapping_input_id"): record for record in refined_candidates_report.get("mapping_records") or []}
    changed: list[dict[str, Any]] = []
    unchanged: list[dict[str, Any]] = []
    worsened: list[dict[str, Any]] = []
    rank = {
        "no_safe_suggestion": 0,
        "blocked_by_gate": 0,
        "low_confidence_suggestion": 1,
        "ambiguous_multiple_suggestions": 1,
        "medium_confidence_suggestion": 2,
        "high_confidence_suggestion": 3,
    }
    for mapping_id, refined in refined_records.items():
        before = baseline_records.get(mapping_id, {})
        row = {
            "mapping_input_id": mapping_id,
            "label": refined.get("label"),
            "row_type": refined.get("row_type"),
            "before_status": before.get("mapping_status"),
            "after_status": refined.get("mapping_status"),
            "before_top_concept": (before.get("top_suggestion") or {}).get("concept_qname"),
            "after_top_concept": (refined.get("top_suggestion") or {}).get("concept_qname"),
            "after_score": (refined.get("top_suggestion") or {}).get("score"),
        }
        if row["before_status"] != row["after_status"] or row["before_top_concept"] != row["after_top_concept"]:
            changed.append(row)
        else:
            unchanged.append(row)
        if rank.get(str(row["after_status"]), 0) < rank.get(str(row["before_status"]), 0):
            worsened.append(row)
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_mapping_refinement_comparison",
            "script": "scripts/refine_azure_di_mapping_candidates_14a.py",
        },
        "input_reports": dict(input_paths),
        "before_13z_status_counts": dict(baseline_candidates_report.get("status_counts") or baseline_confidence_report.get("status_counts") or {}),
        "after_14a_status_counts": dict(refined_candidates_report.get("status_counts") or {}),
        "before_13z_confidence_tier_counts": dict(baseline_candidates_report.get("confidence_tier_counts") or baseline_confidence_report.get("confidence_tier_counts") or {}),
        "after_14a_confidence_tier_counts": dict(refined_candidates_report.get("confidence_tier_counts") or {}),
        "confidence_distribution_change": _status_delta(
            baseline_candidates_report.get("status_counts") or baseline_confidence_report.get("status_counts") or {},
            refined_candidates_report.get("status_counts") or {},
        ),
        "labels_improved_or_changed": changed,
        "labels_unchanged": unchanged[:50],
        "labels_worsened": worsened,
        "diagnostic": diagnose_baseline_weaknesses(
            baseline_candidates_report=baseline_candidates_report,
            baseline_confidence_report=baseline_confidence_report,
            enrichment_report=enrichment_report,
        ),
        "cautionary_notes": [
            "Higher confidence remains a suggested-only signal, not final mapping approval.",
            "No XBRL generation or Arelle validation was performed.",
            "Ambiguous and no-safe records remain review signals, not failures.",
        ],
        "recommended_next_feature": recommend_next_feature(refined_candidates_report),
    }


def _status_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    keys = sorted(set(before) | set(after))
    return {
        key: {"before": int(before.get(key) or 0), "after": int(after.get(key) or 0), "delta": int(after.get(key) or 0) - int(before.get(key) or 0)}
        for key in keys
    }


def diagnose_baseline_weaknesses(
    *,
    baseline_candidates_report: Mapping[str, Any],
    baseline_confidence_report: Mapping[str, Any],
    enrichment_report: Mapping[str, Any],
) -> dict[str, Any]:
    records = list(baseline_candidates_report.get("mapping_records") or [])
    weak = [record for record in records if record.get("mapping_status") in {"low_confidence_suggestion", "no_safe_suggestion", "ambiguous_multiple_suggestions"}]
    low = [record for record in records if record.get("mapping_status") == "low_confidence_suggestion"]
    ambiguous = [record for record in records if record.get("mapping_status") == "ambiguous_multiple_suggestions"]
    no_safe = [record for record in records if record.get("mapping_status") == "no_safe_suggestion"]
    blocker_counts = Counter(blocker for record in records for blocker in record.get("blockers") or [])
    weak_text = [record for record in weak if record.get("row_type") == "text_block"]
    weak_numeric = [record for record in weak if record.get("row_type") in {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}]
    return {
        "why_high_confidence_was_zero": [
            "Baseline aliases were mostly generated from raw taxonomy labels and local names, so common annual-report labels often matched only by weak token overlap.",
            "Text-block candidates often carried broad section labels such as Notes to the Financial Statements, hiding Directors' Report, accounting policy, and note-specific intent.",
            "Several numeric labels had multiple nearby taxonomy concepts and needed curated local aliases plus statement-family hints to separate candidates.",
            "The baseline required a strong score gap before high confidence; close concept scores were surfaced as ambiguous by design.",
        ],
        "baseline_status_counts": dict(baseline_candidates_report.get("status_counts") or baseline_confidence_report.get("status_counts") or {}),
        "baseline_blocker_counts": dict(blocker_counts.most_common()),
        "top_low_confidence_labels": _label_rows(low, limit=20),
        "top_ambiguous_labels": _label_rows(ambiguous, limit=20),
        "top_no_safe_labels": _label_rows(no_safe, limit=20),
        "top_text_block_labels_with_weak_matches": _label_rows(weak_text, limit=20),
        "top_numeric_labels_with_weak_matches": _label_rows(weak_numeric, limit=20),
        "concept_families_missing_or_weak": {
            "unresolved_alias_count": enrichment_report.get("unresolved_alias_count", 0),
            "unresolved_alias_groups": [item.get("alias_group") for item in enrichment_report.get("unresolved_aliases") or []],
            "text_block_concept_count": enrichment_report.get("text_block_concept_count", 0),
            "numeric_concept_count": enrichment_report.get("numeric_concept_count", 0),
        },
    }


def _label_rows(records: Iterable[Mapping[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    rows = []
    for record in records:
        top = record.get("top_suggestion") or {}
        rows.append(
            {
                "mapping_input_id": record.get("mapping_input_id"),
                "label": record.get("label"),
                "row_type": record.get("row_type"),
                "mapping_status": record.get("mapping_status"),
                "top_concept": top.get("concept_qname"),
                "top_score": top.get("score"),
                "blockers": record.get("blockers") or [],
            }
        )
    return rows[:limit]


def recommend_next_feature(candidates_report: Mapping[str, Any]) -> str:
    total = int(candidates_report.get("mapping_record_count") or 0)
    high = int(candidates_report.get("high_confidence_count") or 0)
    medium = int(candidates_report.get("medium_confidence_count") or 0)
    ambiguous = int(candidates_report.get("ambiguous_multiple_suggestions_count") or 0)
    no_safe = int(candidates_report.get("no_safe_suggestion_count") or 0)
    if total and (high + medium) >= total * 0.65 and no_safe <= total * 0.15:
        return "Feature #14B - Azure DI mapping quality evaluation against reference XML, no DB mutation."
    if ambiguous + no_safe >= total * 0.35:
        return "Feature #14B - Concept metadata enrichment v2 if confidence remains weak."
    return "Feature #14B - Manual mapping review workflow if ambiguous mappings remain dominant."


def render_enrichment_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Concept Metadata Enrichment - Feature #14A",
        "",
        "## Summary",
        "",
        f"- Concepts: {report.get('concept_count', 0)}",
        f"- Aliases: {report.get('alias_count', 0)}",
        f"- Curated aliases attached: {report.get('curated_alias_count', 0)}",
        f"- Unresolved alias groups: {report.get('unresolved_alias_count', 0)}",
        f"- Numeric concepts: {report.get('numeric_concept_count', 0)}",
        f"- Text-block concepts: {report.get('text_block_concept_count', 0)}",
        "",
        "## Concept Sources",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in (report.get("concept_sources_used") or {}).items())
    lines.extend(["", "## Curated Alias Groups", ""])
    alias_counts = report.get("curated_aliases_by_group") or {}
    lines.extend(f"- {key}: {value}" for key, value in alias_counts.items()) if alias_counts else lines.append("- None")
    lines.extend(["", "## Metadata Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("metadata_limitations", []))
    lines.append("")
    return "\n".join(lines)


def render_refinement_comparison_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Azure DI Mapping Refinement Comparison - Feature #14A",
        "",
        "## Summary",
        "",
        f"- #13Z status counts: {report.get('before_13z_status_counts', {})}",
        f"- #14A status counts: {report.get('after_14a_status_counts', {})}",
        f"- Changed labels: {len(report.get('labels_improved_or_changed', []))}",
        f"- Worsened labels: {len(report.get('labels_worsened', []))}",
        f"- Recommended next feature: {report.get('recommended_next_feature')}",
        "",
        "## Confidence Distribution Change",
        "",
    ]
    for key, values in (report.get("confidence_distribution_change") or {}).items():
        lines.append(f"- {key}: {values.get('before', 0)} -> {values.get('after', 0)} ({values.get('delta', 0):+d})")
    lines.extend(["", "## Diagnostic", ""])
    for item in (report.get("diagnostic") or {}).get("why_high_confidence_was_zero", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Cautionary Notes", ""])
    lines.extend(f"- {item}" for item in report.get("cautionary_notes", []))
    lines.append("")
    return "\n".join(lines)


def output_paths_from_prefix(output_prefix: str | Path | None = None) -> EnrichmentOutputPaths:
    if output_prefix is None:
        root = DEFAULT_OUTPUT_DIR
        return EnrichmentOutputPaths(
            enrichment_json=root / "azure_di_concept_metadata_enrichment_14a.json",
            enrichment_md=root / "azure_di_concept_metadata_enrichment_14a.md",
        )
    prefix = Path(output_prefix)
    return EnrichmentOutputPaths(
        enrichment_json=Path(f"{prefix}_concept_metadata_enrichment_14a.json"),
        enrichment_md=Path(f"{prefix}_concept_metadata_enrichment_14a.md"),
    )


def group_records_by_status(records: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(record.get("mapping_status") or "unknown") for record in records).most_common())
