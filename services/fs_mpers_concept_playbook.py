"""Local FS-MPERS concept-card playbook and retrieval helpers for #17D-pre.

This module builds mapping-oriented concept cards from #17A strong gold
alignments. It is intentionally deterministic and local-only: no external LLM,
embedding provider, auditor XML, parsed XML facts, target answers, or
evaluation labels are required for retrieval payload construction.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALIGNMENT_REPORT = PROJECT_ROOT / "reports" / "golden_mbrs_mapping_alignment_17a.json"
DEFAULT_PLAYBOOK_REPORT = PROJECT_ROOT / "reports" / "fs_mpers_concept_playbook_17d_pre.json"
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "mpers_templates.json"
SAMPLE_RETRIEVAL_LABELS = (
    "contributed share capital",
    "bank overdraft",
    "other receivable",
    "other payable",
    "accruals",
    "cash and cash equivalents",
    "tax expense",
    "administrative expenses",
)
LEAKAGE_MARKERS = (
    "auditor_xml",
    "reference_xml",
    "parsed_xml_fact",
    "parsed_xml_facts",
    "target_gold_answer",
    "evaluation_label",
    "correct_concept_qname",
    "correct_template_field_id",
    "candidate_facts",
    "fact_id",
    "context_ref",
    "unit_ref",
)
STOPWORDS = {
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "miscellaneous",
    "net",
    "non",
    "noncurrent",
    "of",
    "on",
    "or",
    "other",
    "the",
    "to",
    "total",
    "year",
}
QUALITY_ORDER = {"weak": 1, "moderate": 2, "strong": 3}
ACCOUNTING_SYNONYM_GROUPS = (
    {
        "capital",
        "share capital",
        "issued capital",
        "ordinary share capital",
        "paid up capital",
        "paid-up capital",
        "contributed capital",
        "contributed share capital",
    },
    {"equity", "shareholders equity", "owners equity", "capital deficiency"},
    {"bank overdraft", "overdraft", "secured overdraft", "unsecured bank overdraft"},
    {"cash", "bank balances", "cash at bank", "cash equivalents", "cash and cash equivalents"},
    {"receivable", "receivables", "other receivable", "trade receivable", "debtor", "amount due from"},
    {"payable", "payables", "other payable", "trade payable", "creditor", "amount due to"},
    {"accrual", "accruals", "accrued expenses", "accrued liabilities", "accrued payables"},
    {"taxation", "income tax", "tax expense", "income tax expense", "tax payable", "deferred tax"},
    {"administrative expenses", "administration expenses", "operating expenses", "other expenses"},
    {"depreciation", "depreciation expense"},
    {"profit", "loss", "profit loss", "net loss", "net profit"},
)
SEMANTIC_FAMILY_KEYWORDS = {
    "share_capital": {
        "share capital",
        "issued capital",
        "ordinary share capital",
        "paid up capital",
        "paid-up capital",
        "contributed capital",
        "contributed share capital",
    },
    "equity": {"equity", "shareholders equity", "owners equity", "capital deficiency"},
    "tax": {"taxation", "income tax", "tax expense", "income tax expense", "tax payable", "deferred tax"},
    "profit_before_tax": {"profit before tax", "loss before tax", "profit loss before tax", "before taxation"},
    "overdraft": {"bank overdraft", "overdraft", "secured overdraft", "unsecured bank overdraft"},
    "cash": {"cash", "bank balance", "bank balances", "cash at bank", "cash equivalent", "cash equivalents"},
    "cash_flow": {"cash flow", "cash flows", "operating activities", "financing activities", "investing activities"},
    "receivable": {"receivable", "receivables", "debtor", "debtors", "amount due from"},
    "payable": {"payable", "payables", "creditor", "creditors", "amount due to"},
    "accrual": {"accrual", "accruals", "accrued expense", "accrued expenses", "accrued liabilities"},
    "administrative_expense": {"administrative expenses", "administration expenses"},
    "expense": {"expense", "expenses", "operating expenses", "other expenses", "employee benefits", "wages", "salaries"},
    "income": {"income", "revenue", "turnover", "sales", "rental income", "other income"},
    "asset": {"asset", "assets", "current assets", "non-current assets", "property plant equipment", "inventory"},
    "liability": {"liability", "liabilities", "current liabilities", "non-current liabilities"},
    "broad_subtotal": {
        "assets",
        "liabilities",
        "current assets",
        "current liabilities",
        "non-current assets",
        "non-current liabilities",
        "equity and liabilities",
        "total assets",
        "total liabilities",
    },
}
SPECIFIC_FAMILIES = {
    "share_capital",
    "tax",
    "overdraft",
    "cash",
    "receivable",
    "payable",
    "accrual",
    "administrative_expense",
    "expense",
    "income",
}
GENERIC_SYNONYM_TOKENS = STOPWORDS | {
    "account",
    "activity",
    "amount",
    "balance",
    "benefit",
    "due",
    "expense",
    "function",
    "income",
    "loss",
    "period",
    "profit",
    "taxation",
}
EXPECTED_FAMILY_FALLBACKS = {
    "share_capital": {"share_capital", "equity"},
    "tax": {"tax"},
    "overdraft": {"overdraft"},
    "cash": {"cash"},
    "receivable": {"receivable"},
    "payable": {"payable"},
    "accrual": {"accrual", "payable"},
    "administrative_expense": {"administrative_expense", "expense"},
    "expense": {"expense", "administrative_expense"},
    "income": {"income"},
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _normalize_label(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _normalize_text(value))).strip()


def _canonical_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _tokens(value: Any) -> set[str]:
    return {
        _canonical_token(token)
        for token in _normalize_label(value).split()
        if token and token not in STOPWORDS
    }


def _token_overlap(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _similarity(left: Any, right: Any) -> float:
    left_text = _normalize_label(left)
    right_text = _normalize_label(right)
    if not left_text or not right_text:
        return 0.0
    return max(SequenceMatcher(None, left_text, right_text).ratio(), _token_overlap(left_text, right_text))


def _local_name(qname: Any) -> str:
    return str(qname or "").split(":")[-1]


def _concept_label(qname: Any) -> str:
    value = _local_name(qname)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    return value.strip()


def _semantic_text(*values: Any) -> str:
    parts = []
    for value in values:
        if value is None:
            continue
        parts.append(_normalize_label(value))
        if ":" in str(value):
            parts.append(_normalize_label(_concept_label(value)))
    return " ".join(part for part in parts if part).strip()


def _phrase_present(text: str, phrase: str) -> bool:
    normalized_phrase = _normalize_label(phrase)
    if not text or not normalized_phrase:
        return False
    padded_text = f" {text} "
    padded_phrase = f" {normalized_phrase} "
    compact_text = text.replace(" ", "")
    compact_phrase = normalized_phrase.replace(" ", "")
    return padded_phrase in padded_text or compact_phrase in compact_text


def _semantic_families_for_text(*values: Any) -> set[str]:
    text = _semantic_text(*values)
    families: set[str] = set()
    for family, phrases in SEMANTIC_FAMILY_KEYWORDS.items():
        if any(_phrase_present(text, phrase) for phrase in phrases):
            families.add(family)

    if "profit_before_tax" in families and not any(
        _phrase_present(text, phrase)
        for phrase in ("tax expense", "income tax", "income tax expense", "tax payable", "deferred tax")
    ):
        families.discard("tax")
    if "share_capital" in families:
        families.add("equity")
    if "receivable" in families:
        families.add("asset")
    if families & {"payable", "accrual", "overdraft"}:
        families.add("liability")
    if "administrative_expense" in families:
        families.add("expense")
    return families


def _card_semantic_families(card: Mapping[str, Any]) -> set[str]:
    existing = set(card.get("semantic_families") or [])
    if existing:
        return existing
    values: list[Any] = [
        card.get("concept_qname"),
        card.get("template_field_id"),
        card.get("canonical_label"),
    ]
    values.extend(card.get("common_extracted_labels") or [])
    values.extend(card.get("normalized_label_patterns") or [])
    return _semantic_families_for_text(*values)


def _candidate_semantic_families(candidate_concepts: Sequence[Mapping[str, Any]]) -> set[str]:
    families: set[str] = set()
    for candidate in candidate_concepts:
        families.update(
            _semantic_families_for_text(
                candidate.get("template_field_id"),
                candidate.get("concept_qname"),
                candidate.get("qname"),
                candidate.get("id"),
                candidate.get("xbrl_tag"),
                candidate.get("label"),
            )
        )
    return families


def _specific_family_overlap(left: set[str], right: set[str]) -> set[str]:
    overlap = left & right
    specific = overlap & SPECIFIC_FAMILIES
    return specific or overlap - {"asset", "liability", "equity", "broad_subtotal"}


def _expected_retrieval_families(row_families: set[str]) -> set[str]:
    for family in (
        "share_capital",
        "tax",
        "overdraft",
        "receivable",
        "payable",
        "accrual",
        "cash",
        "administrative_expense",
    ):
        if family in row_families:
            return set(EXPECTED_FAMILY_FALLBACKS[family])
    expected: set[str] = set()
    for family in ("expense", "income"):
        if family in row_families:
            expected.update(EXPECTED_FAMILY_FALLBACKS[family])
    return expected


def _best_expected_family_match(expected_families: set[str], cards: Sequence[Mapping[str, Any]]) -> bool:
    if not expected_families:
        return False
    return any(expected_families & set(card.get("semantic_families") or []) for card in cards)


def _value_nature(value: Any) -> str:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return "blank_or_text"
    try:
        number = float(text)
    except ValueError:
        return "text"
    if number < 0:
        return "negative"
    if number > 0:
        return "positive"
    return "zero"


def _top(counter: Counter, limit: int) -> list[str]:
    return [str(value) for value, _count in counter.most_common(limit)]


def _resolve_path(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _load_template_metadata(template_path: str | Path = DEFAULT_TEMPLATE_PATH) -> dict[str, dict[str, Any]]:
    path = _resolve_path(template_path)
    if not path.exists():
        return {}
    raw = _read_json(path)
    templates = (raw.get("templates") if isinstance(raw, Mapping) else {}) or {}
    by_concept: dict[str, dict[str, Any]] = {}
    for template_code, template in templates.items():
        description = str((template or {}).get("description") or template_code)
        for concept in (template or {}).get("concepts") or []:
            concept_id = concept.get("id")
            if not concept_id:
                continue
            row = by_concept.setdefault(
                str(concept_id),
                {
                    "template_field_id": str(concept_id),
                    "canonical_label": concept.get("label") or _concept_label(concept_id),
                    "templates": [],
                    "statement_families": [],
                    "namespace": concept.get("namespace"),
                    "level": concept.get("level"),
                    "parent": concept.get("parent"),
                    "required": bool(concept.get("required", False)),
                    "position": concept.get("position"),
                },
            )
            row["templates"].append(str(template_code))
            row["statement_families"].append(description)
    return by_concept


def _synonyms_for_text(*values: Any) -> list[str]:
    normalized = " ".join(_normalize_label(value) for value in values)
    tokens = _tokens(normalized)
    synonyms: set[str] = set()
    for group in ACCOUNTING_SYNONYM_GROUPS:
        normalized_group = {_normalize_label(item) for item in group}
        if "tax expense" in normalized_group:
            tax_specific = any(
                _phrase_present(normalized, phrase)
                for phrase in ("tax expense", "income tax", "income tax expense", "tax payable", "deferred tax")
            )
            if not tax_specific:
                continue
        group_tokens = set().union(*(_tokens(item) for item in normalized_group)) - GENERIC_SYNONYM_TOKENS
        phrase_match = any(_phrase_present(normalized, item) for item in normalized_group)
        if phrase_match or (group_tokens and tokens & group_tokens):
            synonyms.update(group)
    return sorted(synonyms)


def _quality(support_count: int, source_case_count: int, statement_count: int) -> str:
    if support_count >= 5 and source_case_count >= 2 and statement_count >= 1:
        return "strong"
    if support_count >= 2 and source_case_count >= 1:
        return "moderate"
    return "weak"


def _compact_example(example: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "extracted_label": example.get("extracted_label"),
        "statement_type": example.get("statement_type"),
        "mapped_concept_qname": example.get("correct_concept_qname"),
        "mapped_template_field_id": example.get("correct_template_field_id"),
        "source_case_id": example.get("source_case_id"),
        "evidence_reason": example.get("reason"),
    }


def _ambiguous_pairs(ambiguous_alignments: Sequence[Mapping[str, Any]]) -> tuple[Counter, dict[tuple[str, str], set[str]]]:
    pair_counter: Counter = Counter()
    labels_by_pair: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in ambiguous_alignments:
        qnames = [
            str(fact.get("correct_concept_qname"))
            for fact in row.get("candidate_facts") or []
            if isinstance(fact, Mapping) and fact.get("correct_concept_qname")
        ]
        unique_qnames = sorted(set(qnames))
        for index, left in enumerate(unique_qnames):
            for right in unique_qnames[index + 1:]:
                pair = tuple(sorted((left, right)))
                pair_counter[pair] += 1
                if row.get("extracted_label"):
                    labels_by_pair[pair].add(str(row["extracted_label"]))
    return pair_counter, labels_by_pair


def _card_do_not_confuse(
    concept_qname: str,
    *,
    pair_counter: Counter,
    labels_by_pair: Mapping[tuple[str, str], set[str]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    rows = []
    for pair, count in pair_counter.items():
        if concept_qname not in pair:
            continue
        other = pair[1] if pair[0] == concept_qname else pair[0]
        rows.append(
            {
                "concept_qname": other,
                "reason": "appeared_together_in_ambiguous_alignment",
                "ambiguous_count": int(count),
                "example_labels": sorted(labels_by_pair.get(pair, set()))[:3],
            }
        )
    rows.sort(key=lambda row: (-row["ambiguous_count"], row["concept_qname"]))
    return rows[:limit]


def build_concept_playbook_from_golden(
    *,
    golden_dir: str | Path = "benchmark_mbrs_pairs",
    alignment_report_path: str | Path = DEFAULT_ALIGNMENT_REPORT,
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
) -> dict[str, Any]:
    """Build concept cards from #17A strong gold examples only."""

    alignment_path = _resolve_path(alignment_report_path)
    alignment = _read_json(alignment_path)
    gold_examples = [
        dict(row)
        for row in alignment.get("gold_examples") or []
        if isinstance(row, Mapping) and row.get("correct_concept_qname")
    ]
    ambiguous_alignments = [
        dict(row)
        for row in alignment.get("ambiguous_alignments") or []
        if isinstance(row, Mapping)
    ]
    template_metadata = _load_template_metadata(template_path)
    groups: dict[str, dict[str, Any]] = {}
    counters: dict[str, dict[str, Counter]] = {}

    for example in gold_examples:
        concept_qname = str(example.get("correct_concept_qname"))
        template_field_id = str(example.get("correct_template_field_id") or concept_qname)
        metadata = template_metadata.get(template_field_id) or template_metadata.get(concept_qname) or {}
        group = groups.setdefault(
            concept_qname,
            {
                "concept_qname": concept_qname,
                "template_field_id": template_field_id,
                "canonical_label": metadata.get("canonical_label") or _concept_label(template_field_id or concept_qname),
                "template_metadata": {
                    key: metadata.get(key)
                    for key in ("templates", "namespace", "level", "parent", "required", "position")
                    if key in metadata
                },
                "statement_families_observed": [],
                "common_extracted_labels": [],
                "normalized_label_patterns": [],
                "accounting_synonyms": [],
                "semantic_families": [],
                "typical_value_nature": None,
                "common_sections": [],
                "example_mappings": [],
                "do_not_confuse_with": [],
                "guardrail_notes": [],
                "source_case_ids": [],
                "support_count": 0,
                "quality": "weak",
            },
        )
        group["support_count"] += 1
        group["example_mappings"].append(_compact_example(example))
        group["source_case_ids"].append(str(example.get("source_case_id") or ""))
        card_counters = counters.setdefault(
            concept_qname,
            {
                "statements": Counter(),
                "labels": Counter(),
                "patterns": Counter(),
                "value_nature": Counter(),
                "sections": Counter(),
            },
        )
        statement = str(example.get("statement_type") or "Unknown")
        label = str(example.get("extracted_label") or "")
        card_counters["statements"][statement] += 1
        card_counters["sections"][statement] += 1
        card_counters["labels"][label] += 1
        card_counters["patterns"][_normalize_label(label)] += 1
        card_counters["value_nature"][_value_nature(example.get("extracted_value"))] += 1

    pair_counter, labels_by_pair = _ambiguous_pairs(ambiguous_alignments)
    for concept_qname, group in groups.items():
        card_counters = counters[concept_qname]
        group["source_case_ids"] = sorted({case_id for case_id in group["source_case_ids"] if case_id})
        group["statement_families_observed"] = _top(card_counters["statements"], 8)
        group["common_extracted_labels"] = _top(card_counters["labels"], 10)
        group["normalized_label_patterns"] = _top(card_counters["patterns"], 10)
        group["typical_value_nature"] = card_counters["value_nature"].most_common(1)[0][0]
        group["common_sections"] = _top(card_counters["sections"], 8)
        group["accounting_synonyms"] = _synonyms_for_text(
            group["canonical_label"],
            concept_qname,
            " ".join(group["common_extracted_labels"]),
        )
        group["semantic_families"] = sorted(
            _semantic_families_for_text(
                group["canonical_label"],
                concept_qname,
                " ".join(group["common_extracted_labels"]),
            )
        )
        group["do_not_confuse_with"] = _card_do_not_confuse(
            concept_qname,
            pair_counter=pair_counter,
            labels_by_pair=labels_by_pair,
        )
        if group["do_not_confuse_with"]:
            group["guardrail_notes"].append(
                "Do not choose this card solely by value match when labels also fit listed do_not_confuse concepts."
            )
        if group["support_count"] == 1:
            group["guardrail_notes"].append("Weak card: only one strong gold example supports this concept.")
        group["quality"] = _quality(
            int(group["support_count"]),
            len(group["source_case_ids"]),
            len(group["statement_families_observed"]),
        )
        group["example_mappings"] = group["example_mappings"][:5]

    concept_cards = sorted(
        groups.values(),
        key=lambda card: (-int(card["support_count"]), str(card["concept_qname"])),
    )
    top_pairs = []
    for pair, count in pair_counter.most_common(20):
        top_pairs.append(
            {
                "concept_qnames": list(pair),
                "ambiguous_count": int(count),
                "example_labels": sorted(labels_by_pair.get(pair, set()))[:5],
            }
        )

    quality_counts = Counter(card["quality"] for card in concept_cards)
    return {
        "run_metadata": {
            "feature": "17D-pre",
            "generated_at": _utc_now(),
            "golden_dir": str(golden_dir),
            "alignment_report_path": _display_path(alignment_path),
            "local_only": True,
            "external_llm_called": False,
            "auditor_xml_sent_externally": False,
            "parsed_xml_facts_included": False,
            "target_gold_answers_included": False,
            "evaluation_labels_included": False,
            "database_mutated": False,
            "production_job_mutated": False,
            "azure_di_extraction_changed": False,
            "react_ui_changed": False,
            "xbrl_generated": False,
            "arelle_run": False,
        },
        "summary": {
            "strong_gold_examples_used": len(gold_examples),
            "ambiguous_alignments_used_for_diagnostics": len(ambiguous_alignments),
            "concept_cards_built": len(concept_cards),
            "concepts_covered": len(concept_cards),
            "quality_counts": dict(sorted(quality_counts.items())),
            "weak_concept_cards": sum(1 for card in concept_cards if card["quality"] == "weak"),
        },
        "concept_cards": concept_cards,
        "do_not_confuse_pairs": top_pairs,
    }


def load_concept_playbook(path: str | Path = DEFAULT_PLAYBOOK_REPORT) -> dict[str, Any]:
    report_path = _resolve_path(path)
    if report_path.exists():
        return _read_json(report_path)
    return build_concept_playbook_from_golden()


def _candidate_ids(candidate_concepts: Sequence[Mapping[str, Any]]) -> set[str]:
    ids = set()
    for candidate in candidate_concepts:
        for key in ("template_field_id", "concept_qname", "qname", "id", "xbrl_tag"):
            if candidate.get(key):
                ids.add(str(candidate[key]))
    return ids


def _candidate_text(candidate_concepts: Sequence[Mapping[str, Any]]) -> str:
    parts = []
    for candidate in candidate_concepts:
        parts.extend(
            str(candidate.get(key) or "")
            for key in ("template_field_id", "concept_qname", "qname", "label", "statement_type")
        )
    return " ".join(parts)


def _statement_compatible(row_statement: Any, card: Mapping[str, Any]) -> bool:
    row_text = _normalize_label(row_statement)
    if not row_text:
        return False
    return any(
        row_text in _normalize_label(statement) or _normalize_label(statement) in row_text
        for statement in card.get("statement_families_observed") or []
    )


def _synonym_match_score(row_label: Any, card: Mapping[str, Any]) -> float:
    row_tokens = _tokens(row_label)
    if not row_tokens:
        return 0.0
    for synonym in card.get("accounting_synonyms") or []:
        synonym_tokens = _tokens(synonym)
        if synonym_tokens and row_tokens & synonym_tokens:
            return 1.0
    return 0.0


def _card_label_similarity(row_label: Any, card: Mapping[str, Any]) -> float:
    candidates = [card.get("canonical_label"), _concept_label(card.get("concept_qname"))]
    candidates.extend(card.get("common_extracted_labels") or [])
    candidates.extend(card.get("normalized_label_patterns") or [])
    return max((_similarity(row_label, value) for value in candidates if value), default=0.0)


def _card_phrase_match_score(row_label: Any, card: Mapping[str, Any]) -> float:
    row_text = _normalize_label(row_label)
    if not row_text:
        return 0.0
    candidates = [card.get("canonical_label"), _concept_label(card.get("concept_qname"))]
    candidates.extend(card.get("common_extracted_labels") or [])
    candidates.extend(card.get("normalized_label_patterns") or [])
    for candidate in candidates:
        candidate_text = _normalize_label(candidate)
        if candidate_text and candidate_text == row_text:
            return 1.0
    for candidate in candidates:
        candidate_text = _normalize_label(candidate)
        if not candidate_text:
            continue
        if f" {row_text} " in f" {candidate_text} " or f" {candidate_text} " in f" {row_text} ":
            return 0.75
    return 0.0


def _quality_boost(card: Mapping[str, Any]) -> float:
    quality = str(card.get("quality") or "weak")
    return {"strong": 0.3, "moderate": 0.15, "weak": 0.0}.get(quality, 0.0)


def _support_boost(card: Mapping[str, Any]) -> float:
    return min(int(card.get("support_count") or 0), 10) * 0.02


def _retrieval_penalties(
    *,
    row_label: Any,
    row_families: set[str],
    card_families: set[str],
    candidate_families: set[str],
    exact_candidate: bool,
    candidate_family_overlap: set[str],
    card: Mapping[str, Any],
    candidate_ids: set[str],
) -> dict[str, float]:
    penalties: dict[str, float] = {}

    if "share_capital" in row_families and not card_families & {"share_capital", "equity"}:
        penalties["asset_liability_equity_mismatch"] = 4.0
    if "tax" in row_families and "tax" not in card_families:
        penalties["tax_mismatch"] = 5.0
    if "receivable" in row_families and card_families & {"payable", "liability"} and "receivable" not in card_families:
        penalties["asset_liability_equity_mismatch"] = max(
            penalties.get("asset_liability_equity_mismatch", 0.0), 4.0
        )
    if "payable" in row_families and card_families & {"receivable", "asset"} and "payable" not in card_families:
        penalties["asset_liability_equity_mismatch"] = max(
            penalties.get("asset_liability_equity_mismatch", 0.0), 4.0
        )
    if "accrual" in row_families and not card_families & {"accrual", "payable"}:
        penalties["accrual_mismatch"] = 2.5
    if "overdraft" in row_families and "overdraft" not in card_families:
        penalties["cash_bank_mismatch"] = 1.5 if "cash" in card_families else 4.0
    if "cash" in row_families and "cash" not in card_families:
        penalties["cash_bank_mismatch"] = max(penalties.get("cash_bank_mismatch", 0.0), 2.5)
    if "cash" in card_families and not row_families & {"cash", "overdraft"}:
        penalties["cash_bank_mismatch"] = max(penalties.get("cash_bank_mismatch", 0.0), 2.5)
    if "cash_flow" in card_families and "cash_flow" not in row_families and "cash" in row_families:
        penalties["cash_flow_substitute"] = 1.5
    if row_families & {"expense", "administrative_expense", "tax"} and "income" in card_families and "tax" not in card_families:
        penalties["income_expense_mismatch"] = 4.0
    if "income" in row_families and card_families & {"expense", "administrative_expense"}:
        penalties["income_expense_mismatch"] = 3.0
    if "administrative_expense" in row_families and card_families & {"income", "cash_flow"}:
        penalties["income_expense_mismatch"] = max(penalties.get("income_expense_mismatch", 0.0), 5.0)
    if "administrative_expense" in row_families and _phrase_present(
        _semantic_text(card.get("concept_qname"), card.get("canonical_label"), " ".join(card.get("common_extracted_labels") or [])),
        "employee benefits",
    ):
        penalties["over_specific_wrong_expense"] = 3.0
    if (row_families & SPECIFIC_FAMILIES) and "broad_subtotal" in card_families:
        penalties["broad_subtotal_for_specific_label"] = 2.5
    confuse_applies = False
    for note in card.get("do_not_confuse_with") or []:
        if note.get("concept_qname") not in candidate_ids:
            continue
        example_labels = note.get("example_labels") or []
        if not example_labels or max((_similarity(row_label, label) for label in example_labels), default=0.0) >= 0.55:
            confuse_applies = True
            break
    if confuse_applies:
        penalties["do_not_confuse_penalty"] = 1.5
    if candidate_families & SPECIFIC_FAMILIES and not exact_candidate and not candidate_family_overlap:
        penalties["candidate_family_mismatch"] = 1.0
    if card.get("quality") == "weak" and not exact_candidate and not (row_families & card_families):
        penalties["weak_card_without_family_evidence"] = 0.5
    return penalties


def _retrieval_floor_met(
    *,
    exact_candidate: bool,
    phrase_score: float,
    label_similarity: float,
    row_family_overlap: set[str],
    candidate_family_overlap: set[str],
    expected_families: set[str],
    card_families: set[str],
) -> bool:
    if expected_families and not (expected_families & card_families):
        if expected_families == {"overdraft"} and "cash" in card_families and "cash_flow" not in card_families:
            return label_similarity >= 0.3
        return phrase_score >= 0.75 and label_similarity >= 0.7
    if exact_candidate or phrase_score >= 0.75 or row_family_overlap or candidate_family_overlap:
        return True
    if expected_families:
        return bool(expected_families & card_families) and label_similarity >= 0.35
    return label_similarity >= 0.55


def retrieve_concept_cards_for_row(
    row: Mapping[str, Any],
    candidate_concepts: Sequence[Mapping[str, Any]],
    *,
    max_cards: int = 5,
    playbook: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    playbook = playbook or load_concept_playbook()
    row_label = row.get("label") or row.get("extracted_label")
    row_statement = row.get("statement_type")
    candidate_ids = _candidate_ids(candidate_concepts)
    candidate_text = _candidate_text(candidate_concepts)
    row_families = _semantic_families_for_text(row_label)
    expected_families = _expected_retrieval_families(row_families)
    candidate_families = _candidate_semantic_families(candidate_concepts)
    retrieved = []
    for card in playbook.get("concept_cards") or []:
        exact_candidate = (
            card.get("concept_qname") in candidate_ids
            or card.get("template_field_id") in candidate_ids
        )
        card_families = _card_semantic_families(card)
        label_similarity = _card_label_similarity(row_label, card)
        phrase_score = _card_phrase_match_score(row_label, card)
        synonym_score = _synonym_match_score(row_label, card)
        statement_score = 1.0 if _statement_compatible(row_statement, card) else 0.0
        token_family_score = max(
            _token_overlap(candidate_text, card.get("concept_qname")),
            _token_overlap(candidate_text, card.get("canonical_label")),
        )
        row_family_overlap = (
            (expected_families & card_families)
            if expected_families
            else _specific_family_overlap(row_families, card_families)
        )
        candidate_family_overlap = _specific_family_overlap(candidate_families, card_families)
        penalties = _retrieval_penalties(
            row_label=row_label,
            row_families=row_families,
            card_families=card_families,
            candidate_families=candidate_families,
            exact_candidate=exact_candidate,
            candidate_family_overlap=candidate_family_overlap,
            card=card,
            candidate_ids=candidate_ids,
        )
        penalty_total = sum(penalties.values())
        score = (
            (7.0 if exact_candidate else 0.0)
            + (2.5 if candidate_family_overlap else 0.0)
            + (3.0 if row_family_overlap else 0.0)
            + (3.0 * phrase_score)
            + (1.25 * label_similarity)
            + (0.8 * synonym_score)
            + (0.6 * statement_score)
            + (0.3 * token_family_score)
            + _quality_boost(card)
            + _support_boost(card)
            - penalty_total
        )
        if not _retrieval_floor_met(
            exact_candidate=exact_candidate,
            phrase_score=phrase_score,
            label_similarity=label_similarity,
            row_family_overlap=row_family_overlap,
            candidate_family_overlap=candidate_family_overlap,
            expected_families=expected_families,
            card_families=card_families,
        ):
            continue
        if score <= 0:
            continue
        compact = _compact_card(card)
        compact["retrieval_score"] = round(score, 4)
        compact["score_breakdown"] = {
            "candidate_exact_match": exact_candidate,
            "candidate_semantic_families": sorted(candidate_families),
            "candidate_family_overlap": sorted(candidate_family_overlap),
            "row_semantic_families": sorted(row_families),
            "expected_semantic_families": sorted(expected_families),
            "card_semantic_families": sorted(card_families),
            "row_family_overlap": sorted(row_family_overlap),
            "phrase_match_score": round(phrase_score, 4),
            "label_similarity": round(label_similarity, 4),
            "synonym_match": bool(synonym_score),
            "statement_type_compatible": bool(statement_score),
            "concept_family_similarity": round(token_family_score, 4),
            "penalties": {key: round(value, 4) for key, value in sorted(penalties.items())},
            "do_not_confuse_penalty": round(penalties.get("do_not_confuse_penalty", 0.0), 4),
            "quality_boost": round(_quality_boost(card), 4),
            "support_boost": round(_support_boost(card), 4),
        }
        retrieved.append(compact)
    retrieved.sort(
        key=lambda item: (
            -float(item["retrieval_score"]),
            -QUALITY_ORDER.get(str(item.get("quality")), 0),
            -int(item.get("support_count") or 0),
            str(item.get("concept_qname") or ""),
        )
    )
    return retrieved[:max_cards]


def retrieve_fewshot_examples_for_row(
    row: Mapping[str, Any],
    *,
    max_examples: int = 3,
    playbook: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    playbook = playbook or load_concept_playbook()
    row_label = row.get("label") or row.get("extracted_label")
    row_statement = row.get("statement_type")
    source_case_id = str(row.get("source_case_id") or "")
    row_families = _semantic_families_for_text(row_label)
    expected_families = _expected_retrieval_families(row_families)
    scored = []
    for card in playbook.get("concept_cards") or []:
        card_families = _card_semantic_families(card)
        family_overlap = (
            (expected_families & card_families)
            if expected_families
            else _specific_family_overlap(row_families, card_families)
        )
        if expected_families and not family_overlap:
            continue
        if "tax" in row_families and "tax" not in card_families:
            continue
        if "receivable" in row_families and card_families & {"payable", "liability"} and "receivable" not in card_families:
            continue
        if "payable" in row_families and card_families & {"receivable", "asset"} and "payable" not in card_families:
            continue
        for example in card.get("example_mappings") or []:
            if source_case_id and source_case_id == str(example.get("source_case_id") or ""):
                if _normalize_label(example.get("extracted_label")) == _normalize_label(row_label):
                    continue
            label_similarity = _similarity(row_label, example.get("extracted_label"))
            statement_score = 1.0 if _normalize_label(row_statement) == _normalize_label(example.get("statement_type")) else 0.0
            synonym_score = _synonym_match_score(row_label, card)
            if not family_overlap and label_similarity < 0.55:
                continue
            score = (
                (2.0 * label_similarity)
                + statement_score
                + (0.8 if family_overlap else 0.0)
                + (0.4 * synonym_score)
                + _quality_boost(card)
            )
            if score <= 0:
                continue
            scored.append(
                {
                    "retrieval_score": round(score, 4),
                    "extracted_label": example.get("extracted_label"),
                    "statement_type": example.get("statement_type"),
                    "mapped_concept_qname": example.get("mapped_concept_qname"),
                    "mapped_template_field_id": example.get("mapped_template_field_id"),
                    "source_case_id": example.get("source_case_id"),
                    "evidence_reason": example.get("evidence_reason"),
                }
            )
    scored.sort(key=lambda item: (-float(item["retrieval_score"]), str(item["mapped_concept_qname"])))
    return scored[:max_examples]


def _compact_card(card: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "concept_qname": card.get("concept_qname"),
        "template_field_id": card.get("template_field_id"),
        "canonical_label": card.get("canonical_label"),
        "statement_families_observed": list(card.get("statement_families_observed") or [])[:5],
        "common_extracted_labels": list(card.get("common_extracted_labels") or [])[:5],
        "normalized_label_patterns": list(card.get("normalized_label_patterns") or [])[:5],
        "accounting_synonyms": list(card.get("accounting_synonyms") or [])[:8],
        "semantic_families": sorted(_card_semantic_families(card)),
        "typical_value_nature": card.get("typical_value_nature"),
        "common_sections": list(card.get("common_sections") or [])[:5],
        "do_not_confuse_with": list(card.get("do_not_confuse_with") or [])[:3],
        "guardrail_notes": list(card.get("guardrail_notes") or [])[:3],
        "source_case_ids": list(card.get("source_case_ids") or [])[:6],
        "support_count": card.get("support_count"),
        "quality": card.get("quality"),
    }


def _compact_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: candidate.get(key)
        for key in ("template_field_id", "concept_qname", "qname", "label", "statement_type")
        if candidate.get(key) is not None
    }


def build_rag_evidence_payload(
    row: Mapping[str, Any],
    candidate_concepts: Sequence[Mapping[str, Any]],
    *,
    max_cards: int = 5,
    max_examples: int = 3,
    playbook: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    playbook = playbook or load_concept_playbook()
    cards = retrieve_concept_cards_for_row(
        row,
        candidate_concepts,
        max_cards=max_cards,
        playbook=playbook,
    )
    examples = retrieve_fewshot_examples_for_row(
        row,
        max_examples=max_examples,
        playbook=playbook,
    )
    diagnostics = _retrieval_diagnostics(row, cards, playbook)
    guardrail_notes = [
        "Choose only from candidate_concepts; return null if retrieved evidence does not support an exact candidate.",
        "Do not infer a concept from value pattern alone; require label and statement-family evidence.",
    ]
    if diagnostics.get("missing_relevant_concept_card"):
        guardrail_notes.append(
            "Local concept-card evidence is missing for the expected semantic family; prefer null over a broad substitute."
        )
    for card in cards:
        for note in card.get("guardrail_notes") or []:
            if note not in guardrail_notes:
                guardrail_notes.append(note)
        for confused in card.get("do_not_confuse_with") or []:
            text = f"Do not confuse {card.get('concept_qname')} with {confused.get('concept_qname')} for labels like {', '.join(confused.get('example_labels') or [])}."
            if text not in guardrail_notes:
                guardrail_notes.append(text)

    payload = {
        "row": {
            "label": row.get("label") or row.get("extracted_label"),
            "value": row.get("value") or row.get("extracted_value"),
            "statement_type": row.get("statement_type"),
        },
        "candidate_concepts": [_compact_candidate(candidate) for candidate in candidate_concepts],
        "retrieved_concept_cards": cards,
        "retrieved_fewshot_examples": examples,
        "retrieval_diagnostics": diagnostics,
        "guardrail_notes": guardrail_notes[:8],
        "safety": {
            "auditor_source_included": False,
            "reference_fact_details_included": False,
            "target_answer_included": False,
            "scoring_labels_included": False,
            "external_llm_required": False,
        },
    }
    assert_payload_is_leakage_safe(payload)
    return payload


def compress_rag_evidence_for_prompt(payload: Mapping[str, Any]) -> dict[str, Any]:
    compressed = {
        "row": dict(payload.get("row") or {}),
        "candidate_concepts": list(payload.get("candidate_concepts") or []),
        "retrieved_concept_cards": list(payload.get("retrieved_concept_cards") or [])[:3],
        "retrieved_fewshot_examples": list(payload.get("retrieved_fewshot_examples") or [])[:3],
        "retrieval_diagnostics": dict(payload.get("retrieval_diagnostics") or {}),
        "guardrail_notes": list(payload.get("guardrail_notes") or [])[:6],
        "safety": dict(payload.get("safety") or {}),
        "compression": {
            "strategy": "deterministic_top_3_cards_top_3_examples",
            "external_llm_called": False,
        },
    }
    assert_payload_is_leakage_safe(compressed)
    return compressed


def assert_payload_is_leakage_safe(payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True).lower()
    for marker in LEAKAGE_MARKERS:
        if marker.lower() in text:
            raise ValueError(f"RAG evidence payload contains forbidden marker: {marker}")


def _sample_row(label: str) -> dict[str, Any]:
    statement = "Statement of Financial Position"
    if any(token in label for token in ("tax", "administrative", "expense")):
        statement = "Statement of Comprehensive Income"
    if "cash and cash equivalents" in label:
        statement = "Statement of Cash Flows"
    return {"label": label, "value": "1000", "statement_type": statement}


def _retrieval_diagnostics(
    row: Mapping[str, Any],
    cards: Sequence[Mapping[str, Any]],
    playbook: Mapping[str, Any],
) -> dict[str, Any]:
    row_label = row.get("label") or row.get("extracted_label")
    row_families = _semantic_families_for_text(row_label)
    expected_families = _expected_retrieval_families(row_families)
    available_matching_cards = [
        _compact_card(card)
        for card in playbook.get("concept_cards") or []
        if expected_families & _card_semantic_families(card)
    ]
    retrieved_relevant = _best_expected_family_match(expected_families, cards)
    missing_relevant = bool(expected_families) and not retrieved_relevant
    if expected_families and not available_matching_cards:
        missing_reason = "no_matching_concept_card_available_in_local_playbook"
    elif missing_relevant:
        missing_reason = "matching_concept_card_available_but_not_retrieved"
    else:
        missing_reason = None
    return {
        "row_semantic_families": sorted(row_families),
        "expected_semantic_families": sorted(expected_families),
        "matching_concept_card_available": bool(available_matching_cards),
        "retrieved_relevant_concept_card": retrieved_relevant,
        "missing_relevant_concept_card": missing_relevant,
        "missing_reason": missing_reason,
        "available_matching_concept_cards": available_matching_cards[:5],
    }


def _sample_candidates(row: Mapping[str, Any], playbook: Mapping[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    label = row.get("label")
    statement = row.get("statement_type")
    row_families = _semantic_families_for_text(label)
    expected_families = _expected_retrieval_families(row_families)
    scored = []
    for card in playbook.get("concept_cards") or []:
        card_families = _card_semantic_families(card)
        family_overlap = (
            (expected_families & card_families)
            if expected_families
            else _specific_family_overlap(row_families, card_families)
        )
        fallback_cash_for_overdraft = "overdraft" in expected_families and "cash" in card_families and "cash_flow" not in card_families
        if expected_families and not family_overlap and not fallback_cash_for_overdraft:
            continue
        score = _card_label_similarity(label, card) + _synonym_match_score(label, card)
        if family_overlap:
            score += 2.0
        if fallback_cash_for_overdraft:
            score += 0.4
        if _statement_compatible(statement, card):
            score += 0.5
        if "broad_subtotal" in card_families and row_families & SPECIFIC_FAMILIES:
            score -= 1.0
        if "cash_flow" in card_families and "cash_flow" not in row_families:
            score -= 1.0
        if score <= 0:
            continue
        scored.append((score, card))
    scored.sort(key=lambda item: (-item[0], str(item[1].get("concept_qname"))))
    return [
        {
            "template_field_id": card.get("template_field_id"),
            "concept_qname": card.get("concept_qname"),
            "label": card.get("canonical_label"),
            "statement_type": (card.get("statement_families_observed") or [None])[0],
        }
        for _score, card in scored[:limit]
    ]


def build_sample_retrieval_report(playbook: Mapping[str, Any]) -> dict[str, Any]:
    samples = []
    for label in SAMPLE_RETRIEVAL_LABELS:
        row = _sample_row(label)
        candidates = _sample_candidates(row, playbook)
        cards = retrieve_concept_cards_for_row(row, candidates, max_cards=5, playbook=playbook)
        examples = retrieve_fewshot_examples_for_row(row, max_examples=3, playbook=playbook)
        diagnostics = _retrieval_diagnostics(row, cards, playbook)
        samples.append(
            {
                "sample_label": label,
                "row": row,
                "candidate_count": len(candidates),
                "retrieved_card_count": len(cards),
                "top_concept_qnames": [card.get("concept_qname") for card in cards[:5]],
                "row_semantic_families": diagnostics["row_semantic_families"],
                "expected_semantic_families": diagnostics["expected_semantic_families"],
                "matching_concept_card_available": diagnostics["matching_concept_card_available"],
                "missing_relevant_concept_card": diagnostics["missing_relevant_concept_card"],
                "missing_reason": diagnostics["missing_reason"],
                "available_matching_concept_cards": diagnostics["available_matching_concept_cards"],
                "retrieved_concept_cards": cards,
                "retrieved_fewshot_examples": examples,
            }
        )
    return {
        "run_metadata": {
            "feature": "17D-pre",
            "generated_at": _utc_now(),
            "external_llm_called": False,
            "local_only": True,
        },
        "samples": samples,
    }


def build_sample_payload_report(playbook: Mapping[str, Any]) -> dict[str, Any]:
    payloads = []
    for label in SAMPLE_RETRIEVAL_LABELS:
        row = _sample_row(label)
        candidates = _sample_candidates(row, playbook)
        payload = build_rag_evidence_payload(row, candidates, playbook=playbook)
        payloads.append(
            {
                "sample_label": label,
                "payload": payload,
                "compressed_payload": compress_rag_evidence_for_prompt(payload),
            }
        )
    return {
        "run_metadata": {
            "feature": "17D-pre",
            "generated_at": _utc_now(),
            "external_llm_called": False,
            "local_only": True,
        },
        "payloads": payloads,
    }


def build_summary_report(playbook: Mapping[str, Any]) -> dict[str, Any]:
    cards = list(playbook.get("concept_cards") or [])
    return {
        "run_metadata": dict(playbook.get("run_metadata") or {}),
        "summary": dict(playbook.get("summary") or {}),
        "support_count_by_concept": [
            {
                "concept_qname": card.get("concept_qname"),
                "template_field_id": card.get("template_field_id"),
                "canonical_label": card.get("canonical_label"),
                "support_count": card.get("support_count"),
                "quality": card.get("quality"),
                "source_case_ids": card.get("source_case_ids"),
            }
            for card in sorted(cards, key=lambda item: (-int(item.get("support_count") or 0), str(item.get("concept_qname"))))
        ],
        "weak_concept_cards": [
            {
                "concept_qname": card.get("concept_qname"),
                "canonical_label": card.get("canonical_label"),
                "support_count": card.get("support_count"),
                "source_case_ids": card.get("source_case_ids"),
                "common_extracted_labels": card.get("common_extracted_labels"),
            }
            for card in cards
            if card.get("quality") == "weak"
        ],
        "common_extracted_labels": [
            {
                "concept_qname": card.get("concept_qname"),
                "labels": card.get("common_extracted_labels"),
            }
            for card in cards[:20]
        ],
        "top_do_not_confuse_pairs": list(playbook.get("do_not_confuse_pairs") or [])[:20],
    }


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        output.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(output)


def render_playbook_markdown(playbook: Mapping[str, Any]) -> str:
    summary = playbook.get("summary") or {}
    rows = [
        [
            card.get("concept_qname"),
            card.get("support_count"),
            card.get("quality"),
            ", ".join((card.get("common_extracted_labels") or [])[:3]),
        ]
        for card in (playbook.get("concept_cards") or [])[:40]
    ]
    return "\n\n".join(
        [
            "# FS-MPERS Concept Playbook #17D-pre",
            f"- Concept cards built: {summary.get('concept_cards_built')}",
            f"- Strong gold examples used: {summary.get('strong_gold_examples_used')}",
            f"- Ambiguous alignments used for diagnostics: {summary.get('ambiguous_alignments_used_for_diagnostics')}",
            f"- Quality counts: {summary.get('quality_counts')}",
            _markdown_table(["Concept", "Support", "Quality", "Common Labels"], rows),
        ]
    ) + "\n"


def render_summary_markdown(summary_report: Mapping[str, Any]) -> str:
    summary = summary_report.get("summary") or {}
    support_rows = [
        [row.get("concept_qname"), row.get("support_count"), row.get("quality")]
        for row in (summary_report.get("support_count_by_concept") or [])[:40]
    ]
    pair_rows = [
        [", ".join(row.get("concept_qnames") or []), row.get("ambiguous_count"), ", ".join(row.get("example_labels") or [])]
        for row in (summary_report.get("top_do_not_confuse_pairs") or [])[:20]
    ]
    return "\n\n".join(
        [
            "# FS-MPERS Concept Playbook Summary #17D-pre",
            f"- Concept cards built: {summary.get('concept_cards_built')}",
            f"- Weak concept cards: {summary.get('weak_concept_cards')}",
            "## Support Counts",
            _markdown_table(["Concept", "Support", "Quality"], support_rows),
            "## Top Do-Not-Confuse Pairs",
            _markdown_table(["Concept Pair", "Ambiguous Count", "Example Labels"], pair_rows),
        ]
    ) + "\n"


def render_retrieval_markdown(report: Mapping[str, Any]) -> str:
    rows = [
        [
            sample.get("sample_label"),
            sample.get("candidate_count"),
            sample.get("retrieved_card_count"),
            sample.get("missing_relevant_concept_card"),
            sample.get("missing_reason") or "",
            ", ".join(sample.get("top_concept_qnames") or []),
        ]
        for sample in report.get("samples") or []
    ]
    return "\n\n".join(
        [
            "# FS-MPERS RAG Retrieval Examples #17D-pre",
            _markdown_table(["Sample Label", "Candidates", "Cards", "Missing Relevant Card", "Missing Reason", "Top Concepts"], rows),
        ]
    ) + "\n"


def render_payload_markdown(report: Mapping[str, Any]) -> str:
    rows = []
    for sample in report.get("payloads") or []:
        payload = sample.get("payload") or {}
        rows.append(
            [
                sample.get("sample_label"),
                len(payload.get("retrieved_concept_cards") or []),
                len(payload.get("retrieved_fewshot_examples") or []),
                len(payload.get("guardrail_notes") or []),
                (payload.get("safety") or {}).get("external_llm_required") is False,
            ]
        )
    return "\n\n".join(
        [
            "# FS-MPERS RAG Payload Examples #17D-pre",
            _markdown_table(["Sample Label", "Cards", "Examples", "Guardrails", "No External LLM"], rows),
        ]
    ) + "\n"


def write_concept_playbook_reports(
    *,
    golden_dir: str | Path = "benchmark_mbrs_pairs",
    alignment_report_path: str | Path = DEFAULT_ALIGNMENT_REPORT,
    reports_dir: str | Path = PROJECT_ROOT / "reports",
) -> dict[str, Path]:
    reports_root = _resolve_path(reports_dir)
    playbook = build_concept_playbook_from_golden(
        golden_dir=golden_dir,
        alignment_report_path=alignment_report_path,
    )
    summary = build_summary_report(playbook)
    retrieval = build_sample_retrieval_report(playbook)
    payloads = build_sample_payload_report(playbook)
    paths = {
        "playbook_json": reports_root / "fs_mpers_concept_playbook_17d_pre.json",
        "playbook_md": reports_root / "fs_mpers_concept_playbook_17d_pre.md",
        "summary_json": reports_root / "fs_mpers_concept_playbook_summary_17d_pre.json",
        "summary_md": reports_root / "fs_mpers_concept_playbook_summary_17d_pre.md",
        "retrieval_json": reports_root / "fs_mpers_rag_retrieval_examples_17d_pre.json",
        "retrieval_md": reports_root / "fs_mpers_rag_retrieval_examples_17d_pre.md",
        "payload_json": reports_root / "fs_mpers_rag_payload_examples_17d_pre.json",
        "payload_md": reports_root / "fs_mpers_rag_payload_examples_17d_pre.md",
    }
    _write_json(paths["playbook_json"], playbook)
    paths["playbook_md"].write_text(render_playbook_markdown(playbook), encoding="utf-8")
    _write_json(paths["summary_json"], summary)
    paths["summary_md"].write_text(render_summary_markdown(summary), encoding="utf-8")
    _write_json(paths["retrieval_json"], retrieval)
    paths["retrieval_md"].write_text(render_retrieval_markdown(retrieval), encoding="utf-8")
    _write_json(paths["payload_json"], payloads)
    paths["payload_md"].write_text(render_payload_markdown(payloads), encoding="utf-8")
    return paths


def validate_concept_playbook_reports(reports_dir: str | Path = PROJECT_ROOT / "reports") -> dict[str, Any]:
    reports_root = _resolve_path(reports_dir)
    required = [
        "fs_mpers_concept_playbook_17d_pre.json",
        "fs_mpers_concept_playbook_summary_17d_pre.json",
        "fs_mpers_rag_retrieval_examples_17d_pre.json",
        "fs_mpers_rag_payload_examples_17d_pre.json",
    ]
    missing = [name for name in required if not (reports_root / name).exists()]
    payload_report = _read_json(reports_root / "fs_mpers_rag_payload_examples_17d_pre.json") if not missing else {}
    leakage_errors = []
    for sample in payload_report.get("payloads") or []:
        try:
            assert_payload_is_leakage_safe(sample.get("payload") or {})
            assert_payload_is_leakage_safe(sample.get("compressed_payload") or {})
        except ValueError as exc:
            leakage_errors.append(str(exc))
    return {
        "valid": not missing and not leakage_errors,
        "missing": missing,
        "leakage_errors": leakage_errors,
    }
