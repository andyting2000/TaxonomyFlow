"""Local taxonomy concept metadata enrichment for candidate ranking.

This module is intentionally local-only. It reads repository metadata files,
builds conservative labels and aliases, and never calls external providers.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from services.pdf_xbrl_deterministic_alignment import canonical_label, concept_label, label_similarity, normalize_label
from services.tightened_mapper_evaluation import sanitize_report_value


DEFAULT_TAXONOMY_METADATA = "mpers_templates.json"
DEFAULT_CONCEPT_PLAYBOOK_REPORT = "reports/fs_mpers_concept_playbook_17d_pre.json"
DEFAULT_AZURE_METADATA_REPORT = "reports/azure_di_concept_metadata_enrichment_14d.json"

TEMPLATE_FAMILY_PREFIXES = {
    "financial_position": ("21", "22"),
    "income_statement": ("31", "32", "41"),
    "cash_flow": ("51", "52"),
    "changes_in_equity": ("61", "62"),
    "notes": ("7",),
}

STATEMENT_NAME_MAP = {
    "statement of financial position": "financial_position",
    "amount due to director": "financial_position",
    "statement of comprehensive income": "income_statement",
    "statement of profit or loss": "income_statement",
    "statement of cash flows": "cash_flow",
    "statement of changes in equity": "changes_in_equity",
    "notes to the financial statements": "notes",
    "notes": "notes",
}

GENERIC_ALIASES = {
    "amount",
    "balance",
    "current",
    "non current",
    "other",
    "total",
    "subtotal",
    "assets",
    "asset",
    "liabilities",
    "liability",
    "equity",
    "income",
    "expenses",
    "expense",
}

CURATED_ALIASES_BY_QNAME = {
    "ifrs-smes:Revenue": ("revenue", "sales", "turnover"),
    "ifrs-smes:IncomeTaxExpenseContinuingOperations": ("tax expense", "income tax expense", "taxation", "income tax"),
    "ifrs-smes:CurrentTaxLiabilitiesCurrent": ("tax payable", "taxation payable", "current tax liabilities"),
    "ifrs-smes:CurrentTaxAssetsCurrent": ("tax recoverable", "tax refundable", "current tax assets"),
    "ifrs-smes:TradeAndOtherCurrentReceivables": (
        "trade and other receivables",
        "other receivables",
        "current receivables",
    ),
    "ifrs-smes:TradeAndOtherCurrentPayables": (
        "trade and other payables",
        "other payables",
        "other payables and accruals",
        "current payables",
        "accruals",
    ),
    "ifrs-smes:IssuedCapital": ("share capital", "issued share capital"),
    "ifrs-smes:Assets": ("total assets",),
    "ifrs-smes:CurrentAssets": ("total current assets",),
    "ifrs-smes:CurrentLiabilities": ("total current liabilities",),
    "ifrs-smes:EquityAndLiabilities": ("total equity and liabilities",),
    "ifrs-smes:EquityAttributableToOwnersOfParent": (
        "shareholders equity",
        "total shareholders equity",
    ),
    "ifrs-smes:ComprehensiveIncome": (
        "total comprehensive income",
        "total comprehensive profit loss",
        "comprehensive profit for the year",
        "comprehensive loss for the period",
    ),
    "ssmt-mpers:EmployeeBenefitsExpenseByNature": (
        "employee benefits expense",
        "staff costs",
        "staff expenses",
    ),
    "ssmt:CashAndBankBalances": ("bank balances", "cash at bank", "cash and bank balances", "cash and bank"),
    "ifrs-smes:CashAndCashEquivalents": (
        "cash and cash equivalents",
        "cash and cash equivalents at beginning of year",
        "cash and cash equivalents at the beginning of year",
        "cash and cash equivalents at end of year",
        "cash and cash equivalents at the end of year",
        "cash and cash equivalent at beginning of the year",
        "cash and cash equivalent at the end of the year",
    ),
    "ifrs-smes:TradeAndOtherReceivables": ("trade and other receivables", "trade receivables", "other receivables"),
    "ssmt-mpers:CurrentTradeReceivables": ("trade receivables", "current trade receivables"),
    "ifrs-smes:TradeAndOtherPayables": ("trade and other payables", "trade payables", "other payables"),
    "ssmt-mpers:CurrentNontradePayables": ("other payables", "amount payable", "accruals"),
    "ifrs-smes:PropertyPlantAndEquipment": (
        "property plant and equipment",
        "property, plant and equipment",
        "plant and equipment",
        "ppe",
    ),
    "ifrs-smes:DepreciationPropertyPlantAndEquipment": (
        "depreciation of property plant and equipment",
        "depreciation of property, plant and equipment",
    ),
    "ifrs-smes:OtherIncome": ("other income", "add other income"),
    "ifrs-smes:OtherExpenseByFunction": (
        "other expenses",
        "operating expenses",
        "other operating expenses",
        "other operating costs",
        "bank charges",
        "audit fee",
        "accounting fee",
        "payroll fee",
        "secretarial fee",
        "professional fees",
        "rental of office",
        "insurance",
        "telephone and fax charges",
        "quit rent and assessment",
        "commissioner for oaths",
    ),
    "ssmt-mpers:AuditorsRemuneration": ("audit fee", "auditor's remuneration", "auditors remuneration", "auditor s remuneration"),
    "ssmt-mpers:AuditorsRemunerationForAuditServices": ("audit fee", "auditors remuneration for audit services"),
    "ssmt-mpers:DirectorsRemuneration": ("directors remuneration", "director's remuneration", "director s remuneration"),
    "ssmt-mpers:OtherDirectorsRemuneration": ("directors fee", "director's fee", "director s fee"),
    "ifrs-smes:RetainedEarnings": (
        "retained earnings",
        "retained profits carried forward",
        "accumulated losses brought forward",
        "accumulated losses carried forward",
    ),
    "ifrs-smes:Borrowings": ("borrowings", "loan", "term loan", "term loans"),
    "ifrs-smes:RepaymentsOfBorrowingsClassifiedAsFinancingActivities": ("repayment of term loan", "term loans repayments"),
    "ifrs-smes:ProfitLoss": (
        "profit for the year",
        "loss for the year",
        "profit for the financial year",
        "loss for the financial year",
        "profit loss for the financial year",
    ),
    "ifrs-smes:ProfitLossBeforeTax": (
        "profit before tax",
        "profit before taxation",
        "loss before taxation",
        "operating profit loss before working capital changes",
    ),
    "ifrs-smes:CashFlowsFromUsedInOperatingActivities": (
        "net cash from operating activities",
        "net cash from to operating activities",
        "cash from operating activities",
    ),
    "ifrs-smes:IncreaseDecreaseInCashAndCashEquivalents": (
        "net increase in cash and cash equivalents",
        "net decrease increase in cash and cash equivalents",
        "net increase in cash and cash equivalent",
    ),
}


def _unique(values: Iterable[Any]) -> list[str]:
    return sorted({str(value) for value in values if value not in (None, "")})


def _template_family(template_code: Any) -> str | None:
    code = str(template_code or "")
    for family, prefixes in TEMPLATE_FAMILY_PREFIXES.items():
        if any(code.startswith(prefix) for prefix in prefixes):
            return family
    return None


def _compact(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _source_file(path: str | Path) -> str:
    return str(Path(path))


def is_generic_alias(value: Any) -> bool:
    normalized = normalize_label(value)
    return not normalized or normalized in GENERIC_ALIASES or len(normalized) <= 2


def _safe_alias(value: Any) -> str | None:
    normalized = canonical_label(value)
    if is_generic_alias(normalized):
        return None
    tokens = normalized.split()
    if len(tokens) == 1 and tokens[0] in GENERIC_ALIASES:
        return None
    return normalized


def classify_concept_family(qname: Any, label: Any, aliases: Sequence[Any] = ()) -> str:
    text = normalize_label(" ".join([str(qname or ""), str(label or ""), *[str(alias or "") for alias in aliases]]))
    compact = _compact(" ".join([str(qname or ""), str(label or "")]))
    if (
        "disclosureof" in compact
        or "descriptionofaccountingpolicy" in compact
        or "explanatory" in compact
        or "textblock" in compact
        or "text block" in text
    ):
        return "notes"
    if (
        "cashflowsfromusedin" in compact
        or "cash flow" in text
        or "cash flows" in text
        or "operating activities" in text
        or "investing activities" in text
        or "financing activities" in text
        or "classifiedasoperatingactivities" in compact
        or "classifiedasinvestingactivities" in compact
        or "classifiedasfinancingactivities" in compact
        or "adjustmentsforincreasedecrease" in compact
        or "adjustmentsfordecreaseincrease" in compact
    ):
        return "cash_flow"
    if "tax" in text:
        return "tax"
    if "receivable" in text or "due from" in text:
        return "receivable"
    if "payable" in text or "due to" in text or "accrual" in text:
        return "payable"
    if "borrow" in text or "loan" in text or "overdraft" in text:
        return "borrowing"
    if "property plant" in text or "property plants" in text or "ppe" in text or "plant and equipment" in text:
        return "ppe"
    if "cash and cash equivalent" in text or "cash and bank" in text or "bank balance" in text or text in {"cash", "cash at bank"}:
        return "cash"
    if "share capital" in text or "retained earning" in text or "retained profit" in text or "accumulated loss" in text or "equity" in text:
        return "equity"
    if "revenue" in text or "sales" in text or "turnover" in text or "income" in text or "profit" in text or "gain" in text:
        return "income"
    if "expense" in text or "cost" in text or "depreciation" in text or "amortisation" in text or "amortization" in text or "fee" in text or "charges" in text:
        return "expense"
    if "asset" in text:
        return "asset"
    if "liabilit" in text:
        return "liability"
    if "total" in text or "subtotal" in text:
        return "total"
    return "unknown"


def balance_type_hint(concept_family: str, qname: Any = "", label: Any = "") -> str | None:
    text = normalize_label(f"{qname} {label}")
    if concept_family in {"asset", "receivable", "cash", "ppe"}:
        return "asset"
    if concept_family in {"liability", "payable", "borrowing"}:
        return "liability"
    if concept_family == "tax":
        if "asset" in text or "recoverable" in text or "refund" in text:
            return "asset"
        if "liabilit" in text or "payable" in text:
            return "liability"
    if concept_family == "equity":
        return "equity"
    return None


def compatible_statement_families(
    qname: Any,
    label: Any,
    template_codes: Sequence[Any] = (),
    concept_family: str | None = None,
) -> list[str]:
    families = [_template_family(code) for code in template_codes]
    family = concept_family or classify_concept_family(qname, label)
    text = normalize_label(f"{qname} {label}")
    if family == "notes":
        families.append("notes")
    elif family == "cash_flow":
        families.append("cash_flow")
    elif family in {"income", "expense"}:
        families.append("income_statement")
    elif family == "tax":
        if "liabilit" in text or "payable" in text or "asset" in text or "recoverable" in text:
            families.append("financial_position")
        else:
            families.append("income_statement")
    elif family in {"asset", "liability", "equity", "receivable", "payable", "borrowing", "ppe", "cash", "total"}:
        families.append("financial_position")
        if family == "cash" and ("cash equivalent" in text or "cashandcashequivalent" in _compact(qname)):
            families.append("cash_flow")
    return _unique(families)


def _labels_from_qname(qname: str) -> list[str]:
    local = qname.split(":")[-1]
    chars: list[str] = []
    previous = ""
    for char in local:
        if previous and char.isupper() and (previous.islower() or previous.isdigit()):
            chars.append(" ")
        chars.append(char)
        previous = char
    return [canonical_label("".join(chars))]


def _label_variants(label: Any) -> list[str]:
    normalized = canonical_label(label)
    variants = [normalized]
    for prefix in ("total ", "add ", "less "):
        if normalized.startswith(prefix):
            variants.append(normalized[len(prefix) :])
    cleaned = normalized.replace(" continuing operations", "").replace(" current", "").replace(" non current", "")
    variants.append(cleaned)
    return [alias for alias in (_safe_alias(value) for value in variants) if alias]


def _statement_names_to_families(names: Sequence[Any]) -> list[str]:
    families = []
    for name in names:
        normalized = normalize_label(name)
        for pattern, family in STATEMENT_NAME_MAP.items():
            if pattern in normalized:
                families.append(family)
    return _unique(families)


def enrich_concept_record(record: Mapping[str, Any]) -> dict[str, Any]:
    qname = str(record.get("qname") or record.get("id") or record.get("concept_qname") or "")
    label = str(record.get("concept_label") or record.get("standard_label") or record.get("label") or concept_label(qname))
    template_codes = _unique(record.get("template_codes") or record.get("templates") or [])
    aliases: list[str] = []
    aliases.extend(_label_variants(label))
    aliases.extend(_labels_from_qname(qname))
    aliases.extend(CURATED_ALIASES_BY_QNAME.get(qname, ()))
    aliases.extend(record.get("aliases") or [])
    aliases.extend(record.get("normalized_labels") or [])
    aliases = [alias for alias in (_safe_alias(value) for value in aliases) if alias]
    family = str(record.get("concept_family") or classify_concept_family(qname, label, aliases))
    statement_families = _unique(
        [
            *(record.get("statement_families") or []),
            *(record.get("compatible_statement_families") or []),
            *compatible_statement_families(qname, label, template_codes, family),
        ]
    )
    return {
        **dict(record),
        "qname": qname,
        "namespace": record.get("namespace") or (qname.split(":", 1)[0] if ":" in qname else None),
        "standard_label": label,
        "concept_label": label,
        "normalized_label": canonical_label(label),
        "normalized_labels": _unique([canonical_label(label), *aliases]),
        "aliases": _unique(alias for alias in aliases if alias != canonical_label(label)),
        "concept_family": family,
        "compatible_statement_families": statement_families,
        "statement_families": statement_families,
        "period_type_hint": record.get("period_type_hint"),
        "balance_type_hint": record.get("balance_type_hint") or balance_type_hint(family, qname, label),
        "risk_notes": _unique(record.get("risk_notes") or []),
    }


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_template_concepts(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    payload = _read_json(path)
    raw_templates = payload.get("templates") if isinstance(payload, Mapping) else None
    concepts: dict[str, dict[str, Any]] = {}
    if not isinstance(raw_templates, Mapping):
        return concepts, {"status": "unsupported_template_shape", "path": str(path)}
    for code, template in raw_templates.items():
        if not isinstance(template, Mapping):
            continue
        for concept in template.get("concepts") or []:
            if not isinstance(concept, Mapping):
                continue
            qname = str(concept.get("id") or concept.get("qname") or concept.get("concept_id") or "")
            if not qname:
                continue
            item = concepts.setdefault(
                qname,
                {
                    "qname": qname,
                    "standard_label": concept.get("label") or concept_label(qname),
                    "concept_label": concept.get("label") or concept_label(qname),
                    "namespace": concept.get("namespace"),
                    "template_codes": [],
                    "source_files": [],
                    "metadata_sources": [],
                },
            )
            item["template_codes"].append(str(code))
            item["source_files"].append(str(path))
            item["metadata_sources"].append("mpers_templates")
            for key in ("level", "parent", "required", "position"):
                if key in concept and key not in item:
                    item[key] = concept[key]
    return concepts, {"status": "loaded", "path": str(path), "concept_count": len(concepts)}


def _merge_playbook_aliases(concepts: dict[str, dict[str, Any]], path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    payload = _read_json(path)
    cards = payload.get("concept_cards") if isinstance(payload, Mapping) else []
    merged = 0
    for card in cards or []:
        if not isinstance(card, Mapping):
            continue
        qname = str(card.get("concept_qname") or card.get("template_field_id") or "")
        if not qname:
            continue
        item = concepts.setdefault(
            qname,
            {
                "qname": qname,
                "standard_label": card.get("canonical_label") or concept_label(qname),
                "concept_label": card.get("canonical_label") or concept_label(qname),
                "template_codes": [],
                "source_files": [],
                "metadata_sources": [],
            },
        )
        metadata = card.get("template_metadata") if isinstance(card.get("template_metadata"), Mapping) else {}
        item.setdefault("template_codes", []).extend(metadata.get("templates") or [])
        item.setdefault("aliases", []).extend(card.get("common_extracted_labels") or [])
        item.setdefault("aliases", []).extend(card.get("normalized_label_patterns") or [])
        if qname in CURATED_ALIASES_BY_QNAME:
            item.setdefault("aliases", []).extend(card.get("accounting_synonyms") or [])
        item.setdefault("source_files", []).append(str(path))
        item.setdefault("metadata_sources", []).append("concept_playbook")
        item.setdefault("statement_families", []).extend(_statement_names_to_families(card.get("statement_families_observed") or []))
        item.setdefault("statement_families", []).extend(_statement_names_to_families(card.get("common_sections") or []))
        if card.get("semantic_families"):
            item.setdefault("risk_notes", []).append("semantic_families:" + ",".join(str(v) for v in card.get("semantic_families") or []))
        merged += 1
    return {"status": "loaded", "path": str(path), "concept_cards_considered": len(cards or []), "concept_cards_merged": merged}


def discover_metadata_sources(root: str | Path = ".") -> list[dict[str, Any]]:
    base = Path(root)
    candidates = [
        base / DEFAULT_TAXONOMY_METADATA,
        base / DEFAULT_CONCEPT_PLAYBOOK_REPORT,
        base / DEFAULT_AZURE_METADATA_REPORT,
    ]
    return [{"path": _source_file(path), "exists": path.exists(), "size_bytes": path.stat().st_size if path.exists() else 0} for path in candidates]


def load_taxonomy_concept_metadata(
    taxonomy_metadata_path: str | Path | None = None,
    *,
    allow_missing: bool = False,
    concept_playbook_path: str | Path | None = DEFAULT_CONCEPT_PLAYBOOK_REPORT,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = Path(taxonomy_metadata_path or DEFAULT_TAXONOMY_METADATA)
    if not path.exists():
        if allow_missing:
            return [], {
                "status": "missing_allowed",
                "path": str(path),
                "source_files_found": discover_metadata_sources("."),
                "concept_count": 0,
            }
        raise FileNotFoundError(f"Taxonomy metadata not found: {path}")

    concepts, template_diag = _load_template_concepts(path)
    playbook_diag = _merge_playbook_aliases(concepts, Path(concept_playbook_path)) if concept_playbook_path else {"status": "not_requested"}
    enriched = [enrich_concept_record(item) for item in concepts.values()]
    summary = metadata_summary(enriched)
    diagnostics = {
        "status": "loaded",
        "path": str(path),
        "source_files_found": discover_metadata_sources("."),
        "template_metadata": template_diag,
        "concept_playbook": playbook_diag,
        **summary,
    }
    return enriched, diagnostics


def best_label_match(row_label: Any, concept: Mapping[str, Any]) -> dict[str, Any]:
    row = canonical_label(row_label)
    labels = _unique(
        [
            concept.get("normalized_label"),
            *(concept.get("normalized_labels") or []),
            *(concept.get("aliases") or []),
        ]
    )
    best = {"ratio": 0.0, "matched_label": None, "match_source": None, "reason": "no_labels"}
    for label in labels:
        if is_generic_alias(label):
            continue
        similarity = label_similarity(row, label)
        ratio = float(similarity.get("ratio") or 0.0)
        source = "alias" if label in set(concept.get("aliases") or []) else "label"
        if row == label:
            ratio = 1.0
            reason = f"exact_{source}_match"
        else:
            reason = str(similarity.get("reason") or "similarity")
        if ratio > float(best["ratio"] or 0.0):
            best = {"ratio": ratio, "matched_label": label, "match_source": source, "reason": reason}
    return best


def statement_family_compatible(row_family: Any, concept: Mapping[str, Any]) -> bool:
    row = str(row_family or "")
    if not row:
        return True
    families = set(str(value) for value in concept.get("compatible_statement_families") or concept.get("statement_families") or [] if value)
    if not families:
        return True
    if row in families:
        return True
    if row == "notes":
        return "notes" in families
    return False


def section_family_match(section_block: Any, concept: Mapping[str, Any]) -> bool:
    section = normalize_label(section_block)
    family = str(concept.get("concept_family") or "")
    balance = str(concept.get("balance_type_hint") or "")
    if not section:
        return False
    if section.startswith("notes"):
        return "notes" in set(concept.get("compatible_statement_families") or [])
    if "cash_flow" in section:
        return family == "cash_flow" or (family == "cash" and "reconciliation" in section)
    if "income" in section or "profit_loss" in section or "revenue" in section or "tax_expense" in section or "administrative_expenses" in section:
        return family in {"income", "expense", "tax"}
    if "asset" in section:
        return balance == "asset" or family in {"asset", "receivable", "cash", "ppe"}
    if "liabilit" in section:
        return balance == "liability" or family in {"liability", "payable", "borrowing"}
    if "equity" in section:
        return family == "equity" or balance == "equity"
    if "financial_position" in section:
        return balance in {"asset", "liability", "equity"} or family in {"asset", "liability", "equity", "receivable", "payable", "borrowing", "cash", "ppe", "tax"}
    return False


def metadata_summary(concepts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(concepts)
    label_count = sum(1 for item in concepts if item.get("standard_label") or item.get("concept_label"))
    alias_count = sum(1 for item in concepts if item.get("aliases"))
    family_count = sum(1 for item in concepts if item.get("concept_family") and item.get("concept_family") != "unknown")
    statement_count = sum(1 for item in concepts if item.get("compatible_statement_families") or item.get("statement_families"))
    family_distribution = Counter(str(item.get("concept_family") or "unknown") for item in concepts)
    alias_total = sum(len(item.get("aliases") or []) for item in concepts)
    return {
        "concept_count": total,
        "label_coverage_count": label_count,
        "label_coverage_rate": round(label_count / total, 4) if total else 0.0,
        "alias_coverage_count": alias_count,
        "alias_coverage_rate": round(alias_count / total, 4) if total else 0.0,
        "alias_total": alias_total,
        "concept_family_coverage_count": family_count,
        "concept_family_coverage_rate": round(family_count / total, 4) if total else 0.0,
        "statement_family_coverage_count": statement_count,
        "statement_family_coverage_rate": round(statement_count / total, 4) if total else 0.0,
        "concept_family_distribution": dict(sorted(family_distribution.items())),
    }


def build_metadata_report(concepts: Sequence[Mapping[str, Any]], diagnostics: Mapping[str, Any], *, feature: str = "18E-F-A-hotfix-1") -> dict[str, Any]:
    summary = metadata_summary(concepts)
    return sanitize_report_value(
        {
            "run_metadata": {
                "feature": feature,
                "offline_only": True,
                "external_provider_called": False,
                "qwen_called": False,
                "supervisor_called": False,
                "database_mutated": False,
                "production_behavior_changed": False,
            },
            "summary": {
                **summary,
                "metadata_status": diagnostics.get("status"),
                "source_files_found": diagnostics.get("source_files_found") or [],
                "template_metadata": diagnostics.get("template_metadata") or {},
                "concept_playbook": diagnostics.get("concept_playbook") or {},
            },
            "concepts": [
                {
                    "qname": item.get("qname"),
                    "standard_label": item.get("standard_label") or item.get("concept_label"),
                    "aliases": item.get("aliases"),
                    "concept_family": item.get("concept_family"),
                    "compatible_statement_families": item.get("compatible_statement_families"),
                    "balance_type_hint": item.get("balance_type_hint"),
                    "source_files": item.get("source_files"),
                }
                for item in concepts
            ],
        }
    )


def render_metadata_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Taxonomy Concept Metadata #18E-F-A-hotfix-1",
        "",
        "Local deterministic metadata only. No external provider was called.",
        "",
        f"- Concept count: `{summary.get('concept_count')}`",
        f"- Label coverage: `{summary.get('label_coverage_count')}` / `{summary.get('concept_count')}` (`{summary.get('label_coverage_rate')}`)",
        f"- Alias coverage: `{summary.get('alias_coverage_count')}` / `{summary.get('concept_count')}` (`{summary.get('alias_coverage_rate')}`)",
        f"- Alias total: `{summary.get('alias_total')}`",
        f"- Concept-family coverage: `{summary.get('concept_family_coverage_count')}` / `{summary.get('concept_count')}` (`{summary.get('concept_family_coverage_rate')}`)",
        f"- Statement-family coverage: `{summary.get('statement_family_coverage_count')}` / `{summary.get('concept_count')}` (`{summary.get('statement_family_coverage_rate')}`)",
        f"- Concept-family distribution: `{summary.get('concept_family_distribution')}`",
    ]
    return "\n".join(lines) + "\n"
