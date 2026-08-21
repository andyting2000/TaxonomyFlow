"""Offline hybrid candidate ranking mapper for Feature #18E-F-A.

The mapper emits ranked candidate evidence only. It does not create final
mappings, does not write production state, and never marks a candidate safe for
auto-apply.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from services.hybrid_candidate_calibration import (
    apply_ranking_profile_to_row,
    available_ranking_profiles,
)
from services.local_candidate_sources import generate_local_candidate_specs
from services.pdf_note_detail_boundaries import boundary_blocks_qname, classify_note_detail_boundary
from services.pdf_xbrl_deterministic_alignment import (
    PdfRowValue,
    canonical_label,
    concept_label,
    expected_period_type_for_statement,
    fact_period_type,
    fact_period_year,
    label_similarity,
    normalize_label,
    normalize_numeric_value,
)
from services.statement_concept_candidate_dictionary import (
    entry_matches_context,
    statement_concept_candidate_entries,
)
from services.taxonomy_concept_metadata import (
    best_label_match,
    enrich_concept_record,
    load_taxonomy_concept_metadata as load_enriched_taxonomy_concept_metadata,
    section_family_match,
    statement_family_compatible,
)
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

GOOD_EVALUATION_STATUSES = {
    "exact_qname_value_period_match",
    "qname_value_match_period_uncertain",
}

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
STATEMENT_FAMILY_TEMPLATE_PREFIXES = {
    "financial_position": ("21", "22"),
    "income_statement": ("31", "32", "41", "42"),
    "cash_flow": ("51", "52"),
    "changes_in_equity": ("61", "62"),
    "notes": ("7",),
}
GENERIC_LABELS = {
    "amount",
    "assets",
    "balance",
    "current",
    "equity",
    "expenses",
    "expense",
    "income",
    "liabilities",
    "liability",
    "non current",
    "other",
    "subtotal",
    "total",
}
DEFAULT_TAXONOMY_METADATA = "mpers_templates.json"
FILTER_MODES = {"baseline", "tightened"}
RANKING_PROFILES = set(available_ranking_profiles())
HIGH_RISK_CONCEPT_FAMILIES = {"tax", "receivables", "payables", "borrowings"}
LOW_RISK_CONCEPT_FAMILIES = {"cash", "cash_flow", "financial_position", "profit_loss"}
LOCAL_CANDIDATE_SOURCE_TYPES = {
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
TIGHTENED_MIN_SCORE = 0.44
TIGHTENED_HIGH_RISK_MIN_SCORE = 0.50
TIGHTENED_LEXICAL_MIN_SIMILARITY = 0.65
TIGHTENED_GENERIC_LEXICAL_MIN_SIMILARITY = 0.97


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path | None) -> Any:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def mapper_records_from_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(record) for record in report.get("suggestions") or report.get("records") or []]


def _row_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record.get("sample_id") or ""), str(record.get("pdf_row_id") or record.get("row_id") or "")


def _unique(values: Iterable[Any]) -> list[str]:
    return sorted({str(value) for value in values if value not in (None, "")})


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _context(record: Mapping[str, Any]) -> dict[str, Any]:
    nested = record.get("row_context") if isinstance(record.get("row_context"), Mapping) else {}
    period = record.get("pdf_period") if isinstance(record.get("pdf_period"), Mapping) else {}
    row_id = str(record.get("pdf_row_id") or record.get("row_id") or nested.get("row_id") or "")
    label = record.get("pdf_label") or record.get("normalized_label") or nested.get("original_label") or nested.get("normalized_label")
    return {
        "sample_id": record.get("sample_id") or nested.get("sample_id"),
        "row_id": row_id,
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
    return canonical_label(record.get("normalized_label") or record.get("pdf_label"))


def _raw_label(record: Mapping[str, Any]) -> str:
    return normalize_label(record.get("pdf_label") or record.get("normalized_label"))


def _is_generic_label(value: Any) -> bool:
    normalized = normalize_label(value)
    return normalized in GENERIC_LABELS or normalized.startswith("total ")


def _has_strong_context(candidate: Mapping[str, Any]) -> bool:
    evidence = candidate.get("evidence") or {}
    return bool(
        evidence.get("statement_family_match")
        and (
            evidence.get("section_context_match")
            or evidence.get("template_match")
            or evidence.get("dictionary_match")
            or evidence.get("format_memory_match")
            or evidence.get("note_link_match")
            or evidence.get("row_order_match")
        )
    )


def _is_standalone_taxonomy_lexical(candidate: Mapping[str, Any]) -> bool:
    sources = set(candidate.get("candidate_sources_combined") or [])
    return sources == {"taxonomy_lexical"} or (candidate.get("candidate_source") == "taxonomy_lexical" and len(sources) <= 1)


def _internal_concept_family(value: Any) -> str | None:
    family = str(value or "")
    mapping = {
        "asset": "financial_position",
        "liability": "financial_position",
        "equity": "financial_position",
        "financial_position": "financial_position",
        "total": "financial_position",
        "income": "profit_loss",
        "expense": "profit_loss",
        "profit_loss": "profit_loss",
        "receivable": "receivables",
        "receivables": "receivables",
        "payable": "payables",
        "payables": "payables",
        "borrowing": "borrowings",
        "borrowings": "borrowings",
        "cash": "cash",
        "cash_flow": "cash_flow",
        "ppe": "financial_position",
        "tax": "tax",
        "notes": "notes",
    }
    return mapping.get(family)


def _candidate_concept_family(candidate: Mapping[str, Any]) -> str:
    metadata_family = _internal_concept_family(candidate.get("concept_family"))
    if metadata_family:
        return metadata_family
    return _concept_family_from_text(candidate.get("qname"), candidate.get("concept_label"))


def _row_family(record: Mapping[str, Any]) -> str:
    return str(_context(record).get("statement_family") or record.get("statement_family") or "")


def _template_family(template_code: Any) -> str | None:
    code = str(template_code or "")
    for family, prefixes in STATEMENT_FAMILY_TEMPLATE_PREFIXES.items():
        if any(code.startswith(prefix) for prefix in prefixes):
            return family
    return None


def _concept_family_from_text(qname: Any, label: Any) -> str:
    text = normalize_label(f"{qname} {label}")
    compact = "".join(ch for ch in f"{qname} {label}".lower() if ch.isalnum())
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
        or "classifiedasoperatingactivities" in compact
        or "classifiedasinvestingactivities" in compact
        or "classifiedasfinancingactivities" in compact
        or "adjustmentsforincreasedecrease" in compact
        or "adjustmentsfordecreaseincrease" in compact
        or "adjustmentsforincometaxexpense" in compact
        or "adjustmentsfornoncashincometaxexpense" in compact
    ):
        return "cash_flow"
    if "tax" in text:
        return "tax"
    if "receivable" in text or "due from" in text:
        return "receivables"
    if "payable" in text or "due to" in text or "accrual" in text:
        return "payables"
    if "borrow" in text or "loan" in text or "overdraft" in text:
        return "borrowings"
    if "cash flow" in text or "cash flows" in text or "financing activities" in text or "investing activities" in text or "operating activities" in text:
        return "cash_flow"
    if "cash and cash equivalent" in text or "cash and bank" in text or "bank balance" in text:
        return "cash"
    if "profit" in text or "loss" in text or "income" in text or "expense" in text or "revenue" in text or "cost of sales" in text:
        return "profit_loss"
    if "asset" in text or "liabilit" in text or "equity" in text or "capital" in text or "earnings" in text:
        return "financial_position"
    return "unknown"


def _concept_statement_family(qname: Any, label: Any, template_families: Sequence[str] = ()) -> str | None:
    families = {str(item) for item in template_families if item}
    if len(families) == 1:
        return next(iter(families))
    text = normalize_label(f"{qname} {label}")
    compact = "".join(ch for ch in f"{qname} {label}".lower() if ch.isalnum())
    if (
        "disclosureof" in compact
        or "descriptionofaccountingpolicy" in compact
        or "explanatory" in compact
        or "textblock" in compact
        or "text block" in text
    ):
        return "notes"
    if (
        "classifiedasoperatingactivities" in compact
        or "classifiedasinvestingactivities" in compact
        or "classifiedasfinancingactivities" in compact
        or "adjustmentsforincreasedecrease" in compact
        or "adjustmentsfordecreaseincrease" in compact
        or "adjustmentsforincometaxexpense" in compact
        or "adjustmentsfornoncashincometaxexpense" in compact
    ):
        return "cash_flow"
    if "cash flow" in text or "cash flows" in text or "financing activities" in text or "investing activities" in text or "operating activities" in text:
        return "cash_flow"
    if "changes in equity" in text:
        return "changes_in_equity"
    if "revenue" in text or "expense" in text or "profit" in text or "loss" in text or "income" in text or "cost of sales" in text:
        return "income_statement"
    if "asset" in text or "liabilit" in text or "equity" in text or "capital" in text or "receivable" in text or "payable" in text:
        return "financial_position"
    if "disclosure" in text or "note" in text or "policy" in text:
        return "notes"
    return None


def _families_compatible(row_family: Any, concept_family: Any, qname: Any = "", label: Any = "") -> bool:
    row = str(row_family or "")
    concept = str(concept_family or "")
    if not row or not concept:
        return True
    if row == concept:
        return True
    text = normalize_label(f"{qname} {label}")
    if row == "cash_flow":
        return concept == "cash_flow" or "cash and cash equivalent" in text
    if row == "changes_in_equity":
        return concept in {"changes_in_equity", "financial_position", "income_statement"}
    if row == "notes":
        return True
    if concept == "notes":
        return row == "notes"
    return False


def _base_evidence() -> dict[str, Any]:
    return {
        "label_similarity": 0.0,
        "statement_family_match": False,
        "section_context_match": False,
        "row_role_match": False,
        "template_match": False,
        "note_link_match": False,
        "format_memory_match": False,
        "dictionary_match": False,
        "row_order_match": False,
        "prior_exact_match_evidence": 0,
        "cached_qwen_match": False,
    }


def load_taxonomy_concept_metadata(
    taxonomy_metadata_path: str | Path | None = None,
    *,
    allow_missing: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load local taxonomy/concept metadata from JSON.

    The default source is mpers_templates.json when present. Missing metadata is
    only allowed when the caller explicitly opts in.
    """
    path = Path(taxonomy_metadata_path or DEFAULT_TAXONOMY_METADATA)
    concept_playbook_path = None if path.name != DEFAULT_TAXONOMY_METADATA else "reports/fs_mpers_concept_playbook_17d_pre.json"
    if not path.exists():
        return load_enriched_taxonomy_concept_metadata(path, allow_missing=allow_missing, concept_playbook_path=concept_playbook_path)

    payload = read_json(path)
    concepts: dict[str, dict[str, Any]] = {}

    if isinstance(payload, Mapping) and isinstance(payload.get("templates"), Mapping):
        return load_enriched_taxonomy_concept_metadata(path, allow_missing=allow_missing, concept_playbook_path=concept_playbook_path)
    elif isinstance(payload, Mapping):
        raw = payload.get("concepts") or payload.get("items") or payload.get("rows") or []
        if isinstance(raw, Mapping):
            raw = raw.values()
        for concept in raw:
            if not isinstance(concept, Mapping):
                continue
            qname = str(concept.get("qname") or concept.get("id") or concept.get("concept_id") or "")
            if not qname:
                continue
            label = concept.get("concept_label") or concept.get("label") or concept_label(qname)
            family = concept.get("statement_family")
            concepts[qname] = {
                "qname": qname,
                "concept_label": label,
                "normalized_label": canonical_label(label),
                "template_codes": list(concept.get("template_codes") or []),
                "statement_families": _unique([family, *(concept.get("statement_families") or [])]),
                "concept_family": concept.get("concept_family") or _concept_family_from_text(qname, label),
                "aliases": list(concept.get("aliases") or []),
                "normalized_labels": list(concept.get("normalized_labels") or []),
                "compatible_statement_families": list(concept.get("compatible_statement_families") or []),
            }
    elif isinstance(payload, list):
        for concept in payload:
            if not isinstance(concept, Mapping):
                continue
            qname = str(concept.get("qname") or concept.get("id") or concept.get("concept_id") or "")
            if not qname:
                continue
            label = concept.get("concept_label") or concept.get("label") or concept_label(qname)
            concepts[qname] = {
                "qname": qname,
                "concept_label": label,
                "normalized_label": canonical_label(label),
                "template_codes": list(concept.get("template_codes") or []),
                "statement_families": _unique(concept.get("statement_families") or []),
                "concept_family": concept.get("concept_family") or _concept_family_from_text(qname, label),
                "aliases": list(concept.get("aliases") or []),
                "normalized_labels": list(concept.get("normalized_labels") or []),
                "compatible_statement_families": list(concept.get("compatible_statement_families") or []),
            }

    for item in concepts.values():
        item.update(enrich_concept_record(item))
        item["template_codes"] = _unique(item.get("template_codes") or [])
        item["statement_families"] = _unique(item.get("statement_families") or [])
        if not item["statement_families"]:
            family = _concept_statement_family(item["qname"], item["concept_label"], ())
            item["statement_families"] = [family] if family else []
    return list(concepts.values()), {"status": "loaded", "path": str(path), "concept_count": len(concepts)}


def _add_concept(catalog: dict[str, dict[str, Any]], qname: Any, label: Any = None, *, source: str, family: Any = None) -> None:
    qname_text = str(qname or "")
    if not qname_text:
        return
    concept_text = label or concept_label(qname_text)
    item = catalog.setdefault(
        qname_text,
        {
            "qname": qname_text,
            "concept_label": concept_text,
            "normalized_label": canonical_label(concept_text),
            "normalized_labels": [canonical_label(concept_text)],
            "aliases": [],
            "statement_families": [],
            "compatible_statement_families": [],
            "template_codes": [],
            "concept_family": _concept_family_from_text(qname_text, concept_text),
            "metadata_sources": [],
        },
    )
    if family:
        item["statement_families"].append(str(family))
    item["metadata_sources"].append(source)


def build_concept_catalog(
    records: Sequence[Mapping[str, Any]],
    *,
    taxonomy_metadata_path: str | Path | None = None,
    allow_missing_taxonomy: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    taxonomy_concepts, diagnostics = load_taxonomy_concept_metadata(
        taxonomy_metadata_path,
        allow_missing=allow_missing_taxonomy,
    )
    catalog = {str(item["qname"]): dict(item, metadata_sources=["taxonomy_metadata"]) for item in taxonomy_concepts}

    for entry in statement_concept_candidate_entries():
        family = entry.get("statement_family")
        for qname in entry.get("candidate_qnames") or [entry.get("preferred_qname")]:
            _add_concept(catalog, qname, concept_label(qname), source="statement_dictionary", family=family)
    for record in records:
        if record.get("predicted_qname"):
            _add_concept(
                catalog,
                record.get("predicted_qname"),
                record.get("predicted_concept_label") or concept_label(record.get("predicted_qname")),
                source="deterministic_mapper",
                family=record.get("statement_family"),
            )
        for key in ("blocked_note_boundary_candidate", "blocked_format_memory_candidate"):
            blocked = record.get(key)
            if isinstance(blocked, Mapping):
                _add_concept(catalog, blocked.get("target_qname"), blocked.get("target_concept_label"), source=key, family=record.get("statement_family"))

    for item in catalog.values():
        item["statement_families"] = _unique(item.get("statement_families") or [])
        item["compatible_statement_families"] = _unique(item.get("compatible_statement_families") or item.get("statement_families") or [])
        item["template_codes"] = _unique(item.get("template_codes") or [])
        item["metadata_sources"] = _unique(item.get("metadata_sources") or [])
        item.update(enrich_concept_record(item))
        if not item.get("concept_family"):
            item["concept_family"] = _concept_family_from_text(item.get("qname"), item.get("concept_label"))
    diagnostics["catalog_count"] = len(catalog)
    return list(catalog.values()), diagnostics


def _extract_qname(value: Mapping[str, Any]) -> str | None:
    for key in ("predicted_qname", "selected_concept_qname", "predicted_concept_qname", "concept_qname", "qname"):
        if value.get(key):
            return str(value[key])
    selected = value.get("selected_candidate")
    if isinstance(selected, Mapping):
        return _extract_qname(selected)
    return None


def _walk_qwen_rows(value: Any, source_file: str) -> Iterable[dict[str, Any]]:
    if isinstance(value, Mapping):
        qname = _extract_qname(value)
        sample_id = value.get("sample_id") or value.get("case_id")
        row_id = value.get("pdf_row_id") or value.get("row_id") or value.get("candidate_id")
        if qname and (sample_id or row_id):
            yield {
                "sample_id": str(sample_id or ""),
                "pdf_row_id": str(row_id or ""),
                "normalized_label": canonical_label(value.get("normalized_label") or value.get("pdf_label") or value.get("label") or value.get("extracted_label")),
                "qname": qname,
                "concept_label": value.get("concept_label") or concept_label(qname),
                "source_file": source_file,
            }
        for item in value.values():
            yield from _walk_qwen_rows(item, source_file)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_qwen_rows(item, source_file)


def load_cached_qwen_candidates(
    qwen_report_dir: str | Path | None,
    *,
    allow_missing: bool = False,
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, Any]]:
    if not qwen_report_dir:
        return {}, {"status": "not_requested", "rows_loaded": 0}
    root = Path(qwen_report_dir)
    if not root.exists():
        if allow_missing:
            return {}, {"status": "missing_allowed", "path": str(root), "rows_loaded": 0}
        raise FileNotFoundError(f"Qwen report directory not found: {root}")
    files = [path for path in root.rglob("*.json") if "qwen" in path.name.lower() or "llm" in path.name.lower()]
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    loaded = 0
    for path in files:
        try:
            payload = read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        for row in _walk_qwen_rows(payload, str(path)):
            index[(row["sample_id"], row["pdf_row_id"])].append(row)
            loaded += 1
    return dict(index), {"status": "loaded", "path": str(root), "files_considered": len(files), "rows_loaded": loaded}


def build_prior_evidence(evaluation_report: Mapping[str, Any] | None) -> dict[tuple[str, str], int]:
    evidence: Counter[tuple[str, str]] = Counter()
    for record in (evaluation_report or {}).get("records") or (evaluation_report or {}).get("suggestions") or []:
        if str(record.get("evaluation_status") or "") not in GOOD_EVALUATION_STATUSES:
            continue
        qname = str(record.get("predicted_qname") or "")
        label = canonical_label(record.get("normalized_label") or record.get("pdf_label"))
        if qname and label:
            evidence[(label, qname)] += 1
    return dict(evidence)


def _source_reliability(source: str, record: Mapping[str, Any] | None = None) -> float:
    if source == "deterministic_current_mapper":
        bucket = str((record or {}).get("confidence_bucket") or "")
        if bucket == "advisory_high":
            return 0.88
        if bucket == "advisory_medium":
            return 0.78
        return 0.68
    if source == "statement_dictionary":
        return 0.58
    if source == "taxonomy_lexical":
        return 0.42
    if source == "cached_qwen":
        return 0.52
    if source == "concept_playbook_lookup":
        return 0.56
    if source in {"statement_role_pack", "section_concept_pack"}:
        return 0.54
    if source in {"cash_flow_movement_pack", "equity_movement_pack", "local_concept_family_pack"}:
        return 0.52
    if source == "note_total_candidate":
        return 0.48
    if source in {"taxonomy_structure_hint", "format_memory_pack"}:
        return 0.5
    return 0.4


def _candidate_score(evidence: Mapping[str, Any], source_reliability: float, risk_penalty: float = 0.0) -> float:
    score = 0.0
    score += float(evidence.get("label_similarity") or 0.0) * 0.34
    score += (0.13 if evidence.get("statement_family_match") else 0.0)
    score += (0.07 if evidence.get("section_context_match") else 0.0)
    score += (0.04 if evidence.get("row_role_match") else 0.0)
    score += source_reliability * 0.24
    score += min(int(evidence.get("prior_exact_match_evidence") or 0), 4) * 0.025
    score += (0.05 if evidence.get("template_match") else 0.0)
    score += (0.05 if evidence.get("format_memory_match") else 0.0)
    score += (0.04 if evidence.get("dictionary_match") else 0.0)
    score += (0.04 if evidence.get("note_link_match") else 0.0)
    return round(max(0.0, min(0.99, score - risk_penalty)), 4)


def _confidence_bucket(score: float, risk_level: str) -> str:
    if risk_level == "critical":
        return "candidate_review_only"
    if score >= 0.78 and risk_level in {"low", "medium"}:
        return "candidate_high"
    if score >= 0.62 and risk_level != "critical":
        return "candidate_medium"
    if score >= 0.45:
        return "candidate_low"
    return "candidate_review_only"


def _risk_level(reasons: Sequence[str]) -> str:
    critical = {
        "blocked_by_note_boundary",
        "predicted_qname_not_found_locally_before",
    }
    high = {
        "note_detail_or_reconciliation_row",
        "tax_payable_expense_ambiguity",
        "receivable_payable_detail_ambiguity",
        "borrowings_or_loan_ambiguity",
        "cash_flow_balance_sheet_ambiguity",
        "generic_or_subtotal_label",
        "low_context_confidence",
    }
    if any(reason in critical for reason in reasons):
        return "critical"
    if any(reason in high for reason in reasons):
        return "high"
    if reasons:
        return "medium"
    return "low"


def _risk_reasons(record: Mapping[str, Any], qname: Any, label: Any, score: float) -> list[str]:
    context = _context(record)
    text = normalize_label(f"{record.get('pdf_label')} {qname} {label}")
    reasons: list[str] = []
    if context.get("row_role") in {"note_detail", "note_movement", "note_reconciliation"} or str(context.get("section_block") or "").startswith("notes_"):
        reasons.append("note_detail_or_reconciliation_row")
    if _is_generic_label(record.get("pdf_label") or record.get("normalized_label")):
        reasons.append("generic_or_subtotal_label")
    if "tax" in text:
        reasons.append("tax_payable_expense_ambiguity")
    if "receivable" in text or "payable" in text or "due from" in text or "due to" in text:
        reasons.append("receivable_payable_detail_ambiguity")
    if "borrow" in text or "loan" in text or "overdraft" in text:
        reasons.append("borrowings_or_loan_ambiguity")
    if context.get("statement_family") == "cash_flow" and ("cash and bank" in text or "cashandbank" in text):
        reasons.append("cash_flow_balance_sheet_ambiguity")
    confidence = _as_float(context.get("context_confidence"))
    if confidence is not None and confidence < 0.7:
        reasons.append("low_context_confidence")
    if score < 0.45:
        reasons.append("weak_evidence_score")
    return _unique(reasons)


def _candidate(
    *,
    record: Mapping[str, Any],
    qname: str,
    concept_text: str,
    source: str,
    source_reliability: float,
    evidence: Mapping[str, Any],
    match_reasons: Sequence[str] = (),
    blocking_reasons: Sequence[str] = (),
    ambiguity_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    risk_reasons = _risk_reasons(record, qname, concept_text, 0.0)
    base_score = _candidate_score(evidence, source_reliability)
    risk_reasons = _risk_reasons(record, qname, concept_text, base_score)
    risk_level = _risk_level(risk_reasons)
    penalty = 0.1 if risk_level == "high" else 0.18 if risk_level == "critical" else 0.04 if risk_level == "medium" else 0.0
    score = _candidate_score(evidence, source_reliability, risk_penalty=penalty)
    return {
        "qname": qname,
        "concept_label": concept_text or concept_label(qname),
        "candidate_source": source,
        "candidate_sources_combined": [source],
        "score": score,
        "confidence_bucket": _confidence_bucket(score, risk_level),
        "risk_level": risk_level,
        "risk_reasons": risk_reasons,
        "evidence": dict(_base_evidence(), **dict(evidence)),
        "match_reasons": list(match_reasons),
        "blocking_reasons": _unique(blocking_reasons),
        "ambiguity_reasons": _unique(ambiguity_reasons),
        "requires_human_review": True,
        "safe_for_auto_apply": False,
    }


def _merge_candidate(existing: dict[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    sources = _unique([*(existing.get("candidate_sources_combined") or []), *(new.get("candidate_sources_combined") or [])])
    evidence = dict(existing.get("evidence") or {})
    for key, value in (new.get("evidence") or {}).items():
        if isinstance(value, bool):
            evidence[key] = bool(evidence.get(key)) or value
        elif isinstance(value, (int, float)):
            evidence[key] = max(float(evidence.get(key) or 0), float(value))
        elif value not in (None, ""):
            evidence[key] = value
    score = min(0.99, max(float(existing.get("score") or 0), float(new.get("score") or 0)) + min(0.08, 0.025 * (len(sources) - 1)))
    risk = max([str(existing.get("risk_level") or "low"), str(new.get("risk_level") or "low")], key=lambda item: RISK_ORDER.get(item, 0))
    merged = dict(existing)
    merged_statement_families = _unique(
        [
            *(existing.get("statement_families") or []),
            *(new.get("statement_families") or []),
        ]
    )
    merged_compatible_statement_families = _unique(
        [
            *(existing.get("compatible_statement_families") or []),
            *(new.get("compatible_statement_families") or []),
        ]
    )
    merged_aliases = _unique([*(existing.get("aliases") or []), *(new.get("aliases") or [])])
    merged_normalized_labels = _unique([*(existing.get("normalized_labels") or []), *(new.get("normalized_labels") or [])])
    merged.update(
        {
            "candidate_sources_combined": sources,
            "score": round(score, 4),
            "risk_level": risk,
            "confidence_bucket": _confidence_bucket(score, risk),
            "evidence": evidence,
            "match_reasons": _unique([*(existing.get("match_reasons") or []), *(new.get("match_reasons") or [])]),
            "blocking_reasons": _unique([*(existing.get("blocking_reasons") or []), *(new.get("blocking_reasons") or [])]),
            "ambiguity_reasons": _unique([*(existing.get("ambiguity_reasons") or []), *(new.get("ambiguity_reasons") or [])]),
            "risk_reasons": _unique([*(existing.get("risk_reasons") or []), *(new.get("risk_reasons") or [])]),
            "requires_human_review": True,
            "safe_for_auto_apply": False,
        }
    )
    if new.get("concept_family") and not merged.get("concept_family"):
        merged["concept_family"] = new.get("concept_family")
    if merged_statement_families:
        merged["statement_families"] = merged_statement_families
    if merged_compatible_statement_families:
        merged["compatible_statement_families"] = merged_compatible_statement_families
    if merged_aliases:
        merged["aliases"] = merged_aliases
    if merged_normalized_labels:
        merged["normalized_labels"] = merged_normalized_labels
    if new.get("metadata_match"):
        existing_match = existing.get("metadata_match") if isinstance(existing.get("metadata_match"), Mapping) else {}
        new_match = new.get("metadata_match") if isinstance(new.get("metadata_match"), Mapping) else {}
        if float(new_match.get("ratio") or 0.0) >= float(existing_match.get("ratio") or 0.0):
            merged["metadata_match"] = dict(new_match)
    return merged


def _add_candidate(pool: dict[str, dict[str, Any]], candidate: Mapping[str, Any]) -> None:
    qname = str(candidate.get("qname") or "")
    if not qname:
        return
    if qname in pool:
        pool[qname] = _merge_candidate(pool[qname], candidate)
    else:
        pool[qname] = dict(candidate)


def _row_looks_like_cash_flow_cash_reconciliation(record: Mapping[str, Any]) -> bool:
    label = normalize_label(record.get("pdf_label") or record.get("normalized_label"))
    section = str(_context(record).get("section_block") or "")
    return (
        ("cash_flow_reconciliation" in section or _row_family(record) == "cash_flow")
        and "cash" in label
        and ("beginning" in label or "end" in label or "equivalent" in label)
    )


def _family_filter_reasons(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    row_family = _row_family(record)
    concept_family_name = _candidate_concept_family(candidate)
    qname = str(candidate.get("qname") or "")
    label = normalize_label(f"{candidate.get('concept_label')} {qname}")
    row_label = normalize_label(record.get("pdf_label") or record.get("normalized_label"))
    reasons: list[str] = []

    if row_family == "income_statement" and concept_family_name in {"financial_position", "receivables", "payables", "borrowings", "cash"}:
        reasons.append("profit_loss_row_blocks_balance_sheet_concept")
    if row_family == "financial_position" and concept_family_name in {"profit_loss", "cash_flow"}:
        reasons.append("financial_position_row_blocks_profit_loss_or_cash_flow_concept")
    if row_family == "cash_flow":
        if concept_family_name == "cash" and not _row_looks_like_cash_flow_cash_reconciliation(record):
            reasons.append("cash_flow_row_blocks_balance_sheet_cash_concept")
        if concept_family_name in {"receivables", "payables", "borrowings"} and "cash flow" not in label:
            reasons.append("cash_flow_row_blocks_balance_sheet_working_capital_concept")
    if row_family == "changes_in_equity" and concept_family_name == "profit_loss":
        allowed = any(term in row_label for term in ("profit", "loss", "comprehensive income", "comprehensive loss"))
        if not allowed:
            reasons.append("changes_in_equity_row_blocks_profit_loss_concept_without_clear_total")
    return reasons


def _note_filter_reasons(record: Mapping[str, Any], candidate: Mapping[str, Any], boundary: Mapping[str, Any] | None) -> list[str]:
    context = _context(record)
    row_family = _row_family(record)
    note_like = (
        row_family == "notes"
        or context.get("row_role") in {"note_detail", "note_movement", "note_reconciliation"}
        or str(context.get("section_block") or "").startswith("notes_")
        or bool((boundary or {}).get("is_note_detail_row"))
        or bool((boundary or {}).get("is_note_movement_row"))
        or bool((boundary or {}).get("is_note_reconciliation_row"))
    )
    if not note_like:
        return []
    if (boundary or {}).get("can_support_main_statement_mapping"):
        return []
    concept_family_name = _candidate_concept_family(candidate)
    if concept_family_name != "notes":
        return ["note_detail_row_blocks_main_statement_candidate_without_boundary_support"]
    return []


def _high_risk_filter_reasons(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    concept_family_name = _candidate_concept_family(candidate)
    row_label = normalize_label(record.get("pdf_label") or record.get("normalized_label"))
    label_high_risk = any(term in row_label for term in ("tax", "receivable", "payable", "borrow", "loan", "overdraft"))
    if concept_family_name not in HIGH_RISK_CONCEPT_FAMILIES and not label_high_risk:
        return []

    sources = set(candidate.get("candidate_sources_combined") or [])
    similarity = float((candidate.get("evidence") or {}).get("label_similarity") or 0.0)
    exact_or_near = similarity >= 0.97
    corroborated = len(sources) >= 2
    if corroborated:
        return []
    if exact_or_near and _has_strong_context(candidate):
        return []
    return ["high_risk_label_family_requires_corrob_or_exact_strong_context"]


def _tightened_filter_reasons(
    record: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    boundary: Mapping[str, Any] | None,
) -> list[str]:
    evidence = candidate.get("evidence") or {}
    similarity = float(evidence.get("label_similarity") or 0.0)
    reasons: list[str] = []
    standalone_lexical = _is_standalone_taxonomy_lexical(candidate)

    if standalone_lexical:
        threshold = TIGHTENED_GENERIC_LEXICAL_MIN_SIMILARITY if _is_generic_label(record.get("pdf_label") or record.get("normalized_label")) else TIGHTENED_LEXICAL_MIN_SIMILARITY
        if similarity < threshold:
            reasons.append("taxonomy_lexical_similarity_below_tightened_threshold")
        if _is_generic_label(record.get("pdf_label") or record.get("normalized_label")) and not (similarity >= 0.99 and _has_strong_context(candidate)):
            reasons.append("taxonomy_lexical_generic_label_without_strong_context")

    reasons.extend(_family_filter_reasons(record, candidate))
    reasons.extend(_note_filter_reasons(record, candidate, boundary))
    reasons.extend(_high_risk_filter_reasons(record, candidate))

    score = float(candidate.get("score") or 0.0)
    if score < TIGHTENED_MIN_SCORE:
        reasons.append("candidate_score_below_tightened_threshold")
    if candidate.get("risk_level") == "high" and score < TIGHTENED_HIGH_RISK_MIN_SCORE:
        reasons.append("high_risk_candidate_score_below_tightened_threshold")
    if "blocked_by_note_boundary" in set(candidate.get("blocking_reasons") or []):
        reasons.append("candidate_has_critical_blocking_reason")
    return _unique(reasons)


def _tighten_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    tightened = dict(candidate)
    sources = set(tightened.get("candidate_sources_combined") or [])
    score = float(tightened.get("score") or 0.0)
    risk = str(tightened.get("risk_level") or "low")
    standalone_lexical = _is_standalone_taxonomy_lexical(tightened)

    if standalone_lexical:
        score = max(0.0, score - 0.08)
        if tightened.get("confidence_bucket") == "candidate_high":
            tightened["confidence_bucket"] = "candidate_low"
    elif len(sources) >= 2:
        score = min(0.99, score + 0.05)
        if risk == "high" and _candidate_concept_family(tightened) not in HIGH_RISK_CONCEPT_FAMILIES:
            risk = "medium"

    if standalone_lexical and score >= 0.62:
        tightened["confidence_bucket"] = "candidate_low"
    else:
        tightened["confidence_bucket"] = _confidence_bucket(score, risk)
    tightened["score"] = round(score, 4)
    tightened["risk_level"] = risk
    tightened["requires_human_review"] = True
    tightened["safe_for_auto_apply"] = False
    return tightened


def _apply_tightened_filters(
    record: Mapping[str, Any],
    ranked: Sequence[Mapping[str, Any]],
    *,
    boundary: Mapping[str, Any] | None,
    top_n: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    filtered: list[dict[str, Any]] = []
    standalone_lexical_kept = 0
    for candidate in ranked:
        reasons = _tightened_filter_reasons(record, candidate, boundary=boundary)
        if reasons:
            filtered.append(
                {
                    "qname": candidate.get("qname"),
                    "concept_label": candidate.get("concept_label"),
                    "candidate_sources_combined": candidate.get("candidate_sources_combined"),
                    "score": candidate.get("score"),
                    "risk_level": candidate.get("risk_level"),
                    "filter_reasons": reasons,
                }
            )
            continue

        tightened = dict(candidate) if candidate.get("already_tightened") else _tighten_candidate(candidate)
        if _is_standalone_taxonomy_lexical(tightened):
            if standalone_lexical_kept >= 2:
                filtered.append(
                    {
                        "qname": candidate.get("qname"),
                        "concept_label": candidate.get("concept_label"),
                        "candidate_sources_combined": candidate.get("candidate_sources_combined"),
                        "score": candidate.get("score"),
                        "risk_level": candidate.get("risk_level"),
                        "filter_reasons": ["taxonomy_lexical_standalone_top_n_pruned"],
                    }
                )
                continue
            standalone_lexical_kept += 1
        kept.append(tightened)

    kept = sorted(kept, key=lambda item: (-float(item.get("score") or 0.0), RISK_ORDER.get(str(item.get("risk_level")), 9), str(item.get("qname"))))
    return kept[:top_n], filtered


def _deterministic_candidate(record: Mapping[str, Any], prior_evidence: Mapping[tuple[str, str], int]) -> dict[str, Any] | None:
    qname = str(record.get("predicted_qname") or "")
    if not qname:
        return None
    source_method = str(record.get("candidate_generation_method") or record.get("raw_candidate_generation_method") or "deterministic_current_mapper")
    label_score = 1.0 if record.get("predicted_concept_label") and canonical_label(record.get("predicted_concept_label")) == _label(record) else label_similarity(_label(record), record.get("predicted_concept_label") or concept_label(qname))["ratio"]
    evidence = _base_evidence()
    evidence.update(
        {
            "label_similarity": label_score,
            "statement_family_match": True,
            "section_context_match": True,
            "row_role_match": True,
            "template_match": source_method == "statement_template",
            "note_link_match": source_method == "note_link_template",
            "format_memory_match": source_method == "company_format_template_memory",
            "dictionary_match": source_method == "dictionary",
            "row_order_match": source_method == "row_order_alignment",
            "prior_exact_match_evidence": prior_evidence.get((_label(record), qname), 0),
        }
    )
    return _candidate(
        record=record,
        qname=qname,
        concept_text=record.get("predicted_concept_label") or concept_label(qname),
        source="deterministic_current_mapper",
        source_reliability=_source_reliability("deterministic_current_mapper", record),
        evidence=evidence,
        match_reasons=[f"deterministic_method:{source_method}", *(record.get("match_reasons") or [])],
        blocking_reasons=record.get("blocking_reasons") or [],
    )


def _dictionary_candidates(record: Mapping[str, Any], prior_evidence: Mapping[tuple[str, str], int]) -> list[dict[str, Any]]:
    context = _context(record)
    output = []
    for entry in statement_concept_candidate_entries():
        matched, reasons, label_score = entry_matches_context(entry, context)
        if not matched:
            continue
        for qname in entry.get("candidate_qnames") or [entry.get("preferred_qname")]:
            if not qname:
                continue
            evidence = _base_evidence()
            evidence.update(
                {
                    "label_similarity": label_score,
                    "statement_family_match": True,
                    "section_context_match": bool(entry.get("section_blocks")),
                    "row_role_match": bool(not entry.get("row_roles") or context.get("row_role") in set(entry.get("row_roles") or [])),
                    "dictionary_match": True,
                    "prior_exact_match_evidence": prior_evidence.get((_label(record), str(qname)), 0),
                }
            )
            output.append(
                _candidate(
                    record=record,
                    qname=str(qname),
                    concept_text=concept_label(qname),
                    source="statement_dictionary",
                    source_reliability=_source_reliability("statement_dictionary"),
                    evidence=evidence,
                    match_reasons=reasons,
                    blocking_reasons=["dictionary_candidate_requires_review", *(entry.get("blocking_conditions") or [])],
                )
            )
    return output


def _lexical_candidates(
    record: Mapping[str, Any],
    concepts: Sequence[Mapping[str, Any]],
    prior_evidence: Mapping[tuple[str, str], int],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    row_context = _context(record)
    row_family = (row_context.get("statement_family") or record.get("statement_family") or "")
    row_label = _label(record)
    generic = _is_generic_label(row_label)
    rows = []
    for concept in concepts:
        qname = str(concept.get("qname") or "")
        if not qname:
            continue
        concept_text = str(concept.get("concept_label") or concept_label(qname))
        local_name = qname.split(":")[-1]
        if local_name.endswith("Abstract") or "abstract" in normalize_label(concept_text):
            continue
        note_detail_context = row_context.get("row_role") in {"note_detail", "note_movement", "note_reconciliation"} or str(row_context.get("section_block") or "").startswith("notes_")
        if str(concept.get("concept_family") or "") == "notes" and (str(row_family or "") != "notes" or note_detail_context):
            continue
        concept_families = list(concept.get("statement_families") or [])
        concept_statement_family = _concept_statement_family(qname, concept_text, concept_families)
        fallback_family_match = _families_compatible(row_family, concept_statement_family, qname, concept_text)
        metadata_family_match = statement_family_compatible(row_family, concept)
        if not (metadata_family_match or fallback_family_match):
            continue
        match = best_label_match(row_label, concept)
        ratio = float(match.get("ratio") or 0.0)
        exact_match = str(match.get("reason") or "").startswith("exact_")
        threshold = 0.86 if generic else 0.58
        if exact_match and match.get("match_source") == "alias":
            threshold = 0.99
        elif match.get("match_source") == "alias":
            threshold = max(threshold, 0.65)
        if ratio < threshold:
            continue
        section_match = section_family_match(row_context.get("section_block"), concept)
        internal_family = _internal_concept_family(concept.get("concept_family"))
        row_internal_family = {
            "income_statement": "profit_loss",
            "financial_position": "financial_position",
            "cash_flow": "cash_flow",
            "changes_in_equity": "financial_position",
            "notes": "notes",
        }.get(str(row_family or ""), str(row_family or ""))
        if not section_match and row_context.get("section_block") and row_internal_family and internal_family == row_internal_family:
            section_match = bool(metadata_family_match or fallback_family_match)
        evidence = _base_evidence()
        family_match = metadata_family_match or fallback_family_match
        evidence.update(
            {
                "label_similarity": ratio,
                "statement_family_match": family_match,
                "section_context_match": section_match,
                "row_role_match": row_context.get("row_role") not in {None, "", "note_detail", "note_movement", "note_reconciliation"},
                "template_match": bool(concept.get("template_codes")),
                "prior_exact_match_evidence": prior_evidence.get((row_label, qname), 0),
            }
        )
        candidate = _candidate(
            record=record,
            qname=qname,
            concept_text=concept_text,
            source="taxonomy_lexical",
            source_reliability=_source_reliability("taxonomy_lexical"),
            evidence=evidence,
            match_reasons=[
                f"lexical_similarity:{round(ratio, 4)}",
                f"metadata_match:{match.get('reason')}",
                f"metadata_label:{match.get('matched_label')}",
                f"concept_family:{concept.get('concept_family') or 'unknown'}",
            ],
        )
        candidate.update(
            {
                "concept_family": concept.get("concept_family"),
                "statement_families": list(concept.get("statement_families") or []),
                "compatible_statement_families": list(concept.get("compatible_statement_families") or concept.get("statement_families") or []),
                "normalized_labels": list(concept.get("normalized_labels") or []),
                "aliases": list(concept.get("aliases") or []),
                "metadata_match": dict(match),
            }
        )
        rows.append(candidate)
    return sorted(rows, key=lambda item: (-float(item["score"]), item["qname"]))[:limit]


def _qwen_candidates(
    record: Mapping[str, Any],
    qwen_index: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]],
    prior_evidence: Mapping[tuple[str, str], int],
) -> list[dict[str, Any]]:
    output = []
    for item in qwen_index.get(_row_key(record), []) or []:
        qname = str(item.get("qname") or "")
        if not qname:
            continue
        concept_text = item.get("concept_label") or concept_label(qname)
        similarity = label_similarity(_label(record), concept_text)
        evidence = _base_evidence()
        evidence.update(
            {
                "label_similarity": float(similarity.get("ratio") or 0.0),
                "statement_family_match": True,
                "cached_qwen_match": True,
                "prior_exact_match_evidence": prior_evidence.get((_label(record), qname), 0),
            }
        )
        output.append(
            _candidate(
                record=record,
                qname=qname,
                concept_text=concept_text,
                source="cached_qwen",
                source_reliability=_source_reliability("cached_qwen"),
                evidence=evidence,
                match_reasons=[f"cached_qwen_report:{item.get('source_file')}"],
            )
        )
    return output


def _existing_ranked_candidates(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    output = []
    for raw in record.get("candidates") or []:
        if not isinstance(raw, Mapping) or not raw.get("qname"):
            continue
        candidate = dict(raw)
        sources = _unique(candidate.get("candidate_sources_combined") or [candidate.get("candidate_source")])
        candidate["candidate_source"] = candidate.get("candidate_source") or (sources[0] if sources else "existing_ranked_candidate")
        candidate["candidate_sources_combined"] = sources or [candidate["candidate_source"]]
        candidate["concept_label"] = candidate.get("concept_label") or concept_label(candidate.get("qname"))
        candidate["score"] = round(float(candidate.get("score") or 0.0), 4)
        candidate["risk_level"] = candidate.get("risk_level") or "medium"
        candidate["confidence_bucket"] = candidate.get("confidence_bucket") or _confidence_bucket(float(candidate["score"]), str(candidate["risk_level"]))
        candidate["evidence"] = dict(_base_evidence(), **dict(candidate.get("evidence") or {}))
        candidate["match_reasons"] = list(candidate.get("match_reasons") or [])
        candidate["blocking_reasons"] = list(candidate.get("blocking_reasons") or [])
        candidate["ambiguity_reasons"] = list(candidate.get("ambiguity_reasons") or [])
        candidate["risk_reasons"] = list(candidate.get("risk_reasons") or [])
        candidate["requires_human_review"] = True
        candidate["safe_for_auto_apply"] = False
        candidate["already_tightened"] = True
        output.append(candidate)
    return output


def _apply_minimum_risk(candidate: dict[str, Any], risk_hint: Any) -> dict[str, Any]:
    hint = str(risk_hint or "")
    if hint not in RISK_ORDER:
        return candidate
    current = str(candidate.get("risk_level") or "low")
    if RISK_ORDER.get(hint, 0) > RISK_ORDER.get(current, 0):
        candidate["risk_level"] = hint
        candidate["confidence_bucket"] = _confidence_bucket(float(candidate.get("score") or 0.0), hint)
        candidate["risk_reasons"] = _unique([*(candidate.get("risk_reasons") or []), "local_structured_candidate_requires_review"])
    return candidate


def _local_candidates(
    record: Mapping[str, Any],
    concepts: Sequence[Mapping[str, Any]],
    prior_evidence: Mapping[tuple[str, str], int],
    *,
    concept_cards: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    output = []
    specs = generate_local_candidate_specs(record, concept_cards=concept_cards, concepts=concepts)
    for spec in specs:
        qname = str(spec.get("qname") or "")
        source = str(spec.get("candidate_source") or spec.get("source_type") or "local_concept_family_pack")
        if not qname or source not in LOCAL_CANDIDATE_SOURCE_TYPES:
            continue
        evidence = _base_evidence()
        evidence.update(spec.get("evidence") or {})
        evidence["prior_exact_match_evidence"] = prior_evidence.get((_label(record), qname), 0)
        candidate = _candidate(
            record=record,
            qname=qname,
            concept_text=str(spec.get("concept_label") or concept_label(qname)),
            source=source,
            source_reliability=_source_reliability(source),
            evidence=evidence,
            match_reasons=spec.get("match_reasons") or [],
            blocking_reasons=spec.get("blocking_reasons") or ["local_candidate_requires_review"],
            ambiguity_reasons=spec.get("ambiguity_reasons") or [],
        )
        candidate.update(
            {
                "source_id": spec.get("source_id"),
                "concept_family": spec.get("concept_family"),
                "statement_families": list(spec.get("statement_families") or []),
                "compatible_statement_families": list(spec.get("compatible_statement_families") or spec.get("statement_families") or []),
                "local_candidate_source_type": source,
            }
        )
        output.append(_apply_minimum_risk(candidate, spec.get("risk_level_hint")))
    return output


def rank_candidates_for_record(
    record: Mapping[str, Any],
    *,
    concepts: Sequence[Mapping[str, Any]],
    prior_evidence: Mapping[tuple[str, str], int] | None = None,
    qwen_index: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]] | None = None,
    local_concept_cards: Sequence[Mapping[str, Any]] = (),
    top_n: int = 5,
    filter_mode: str = "baseline",
    enable_local_sources: bool = False,
    include_existing_candidates: bool = False,
    include_standard_sources: bool = True,
    ranking_profile: str | None = None,
) -> dict[str, Any]:
    if filter_mode not in FILTER_MODES:
        raise ValueError(f"Unknown filter_mode: {filter_mode}")
    if ranking_profile is not None and ranking_profile not in RANKING_PROFILES:
        raise ValueError(f"Unknown ranking_profile: {ranking_profile}")
    prior = prior_evidence or {}
    boundary = record.get("note_boundary") if isinstance(record.get("note_boundary"), Mapping) else classify_note_detail_boundary(_context(record))
    pool: dict[str, dict[str, Any]] = {}
    blocked_candidates = []
    filtered_candidates = []

    candidates: list[dict[str, Any]] = []
    if include_existing_candidates:
        candidates.extend(_existing_ranked_candidates(record))
    if include_standard_sources:
        deterministic = _deterministic_candidate(record, prior)
        if deterministic:
            candidates.append(deterministic)
        candidates.extend(_dictionary_candidates(record, prior))
        candidates.extend(_lexical_candidates(record, concepts, prior, limit=max(top_n * 2, 8)))
        candidates.extend(_qwen_candidates(record, qwen_index or {}, prior))
    if enable_local_sources:
        candidates.extend(_local_candidates(record, concepts, prior, concept_cards=local_concept_cards))

    for candidate in candidates:
        blocked, reasons = boundary_blocks_qname(boundary, candidate.get("qname"))
        if blocked:
            blocked_item = dict(candidate)
            blocked_item["blocking_reasons"] = _unique([*(candidate.get("blocking_reasons") or []), *reasons, "blocked_by_note_boundary"])
            blocked_item["risk_level"] = "critical"
            blocked_candidates.append(blocked_item)
            continue
        _add_candidate(pool, candidate)

    ranked = sorted(pool.values(), key=lambda item: (-float(item.get("score") or 0.0), RISK_ORDER.get(str(item.get("risk_level")), 9), str(item.get("qname"))))
    if filter_mode == "tightened":
        ranked, filtered_candidates = _apply_tightened_filters(record, ranked, boundary=boundary, top_n=top_n)

    if len(ranked) > 1 and (float(ranked[0].get("score") or 0.0) - float(ranked[1].get("score") or 0.0)) <= 0.05:
        for item in ranked[:2]:
            item["ambiguity_reasons"] = _unique([*(item.get("ambiguity_reasons") or []), "multiple_competing_candidates_close_in_score"])
            if RISK_ORDER.get(str(item.get("risk_level")), 0) < RISK_ORDER["medium"]:
                item["risk_level"] = "medium"
                item["confidence_bucket"] = _confidence_bucket(float(item.get("score") or 0.0), "medium")

    ranked = ranked[:top_n]
    for index, item in enumerate(ranked, start=1):
        item["rank"] = index
        item["requires_human_review"] = True
        item["safe_for_auto_apply"] = False

    if ranked:
        deterministic_only = all(item.get("candidate_sources_combined") == ["deterministic_current_mapper"] for item in ranked)
        status = "deterministic_candidate_available" if deterministic_only else "ranked_candidates_available"
    elif blocked_candidates:
        status = "blocked_by_note_boundary"
    elif not record.get("pdf_value"):
        status = "not_evaluable"
    else:
        status = "no_candidate"

    context = _context(record)
    output = {
        "sample_id": record.get("sample_id"),
        "company_name": record.get("company_name"),
        "row_id": record.get("pdf_row_id") or record.get("row_id"),
        "pdf_label": record.get("pdf_label"),
        "normalized_label": record.get("normalized_label") or canonical_label(record.get("pdf_label")),
        "value": record.get("pdf_value"),
        "pdf_period": record.get("pdf_period"),
        "statement_family": context.get("statement_family"),
        "section_block": context.get("section_block"),
        "row_role": context.get("row_role"),
        "is_note_detail_row": bool((boundary or {}).get("is_note_detail_row") or (boundary or {}).get("is_note_movement_row") or (boundary or {}).get("is_note_reconciliation_row")),
        "candidate_coverage_status": status,
        "candidate_count": len(ranked),
        "blocked_candidate_count": len(blocked_candidates),
        "filtered_candidate_count": len(filtered_candidates),
        "blocked_candidates": [
            {
                "qname": item.get("qname"),
                "concept_label": item.get("concept_label"),
                "candidate_sources_combined": item.get("candidate_sources_combined"),
                "blocking_reasons": item.get("blocking_reasons"),
                "risk_level": item.get("risk_level"),
            }
            for item in blocked_candidates[:8]
        ],
        "filtered_candidates": filtered_candidates[:12],
        "note_boundary": boundary,
        "candidates": ranked,
        "requires_human_review": True,
        "safe_for_auto_apply": False,
    }
    if ranking_profile:
        output = apply_ranking_profile_to_row(output, ranking_profile, top_n=top_n)
    return sanitize_report_value(output)


def rank_candidate_rows(
    records: Sequence[Mapping[str, Any]],
    *,
    concepts: Sequence[Mapping[str, Any]],
    evaluation_report: Mapping[str, Any] | None = None,
    qwen_index: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]] | None = None,
    local_concept_cards: Sequence[Mapping[str, Any]] = (),
    top_n: int = 5,
    debug_label: str | None = None,
    filter_mode: str = "baseline",
    enable_local_sources: bool = False,
    include_existing_candidates: bool = False,
    include_standard_sources: bool = True,
    ranking_profile: str | None = None,
) -> list[dict[str, Any]]:
    wanted = normalize_label(debug_label) if debug_label else None
    prior = build_prior_evidence(evaluation_report)
    rows = []
    for record in records:
        if wanted and wanted not in normalize_label(record.get("pdf_label") or record.get("normalized_label")):
            continue
        rows.append(
            rank_candidates_for_record(
                record,
                concepts=concepts,
                prior_evidence=prior,
                qwen_index=qwen_index or {},
                local_concept_cards=local_concept_cards,
                top_n=top_n,
                filter_mode=filter_mode,
                enable_local_sources=enable_local_sources,
                include_existing_candidates=include_existing_candidates,
                include_standard_sources=include_standard_sources,
                ranking_profile=ranking_profile,
            )
        )
    return rows


def summarize_candidate_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    with_candidate = [row for row in rows if row.get("candidate_count", 0) > 0]
    with_three = [row for row in rows if row.get("candidate_count", 0) >= 3]
    high_medium = [
        row
        for row in rows
        if any((candidate.get("confidence_bucket") in {"candidate_high", "candidate_medium"}) for candidate in row.get("candidates") or [])
    ]
    only_low_risk = [
        row
        for row in with_candidate
        if all(candidate.get("risk_level") == "low" for candidate in row.get("candidates") or [])
    ]
    candidate_source_counts: Counter[str] = Counter()
    source_row_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    filtered_reason_counts: Counter[str] = Counter()
    candidate_counts_by_row = Counter(int(row.get("candidate_count") or 0) for row in rows)
    for row in rows:
        row_sources = set()
        for candidate in row.get("candidates") or []:
            risk_counts[str(candidate.get("risk_level") or "unknown")] += 1
            confidence_counts[str(candidate.get("confidence_bucket") or "unknown")] += 1
            for source in candidate.get("candidate_sources_combined") or []:
                candidate_source_counts[str(source)] += 1
                row_sources.add(str(source))
        for source in row_sources:
            source_row_counts[source] += 1
        for filtered in row.get("filtered_candidates") or []:
            for reason in filtered.get("filter_reasons") or []:
                filtered_reason_counts[str(reason)] += 1
    status_counts = Counter(str(row.get("candidate_coverage_status") or "unknown") for row in rows)
    blocked = sum(1 for row in rows if row.get("candidate_coverage_status") == "blocked_by_note_boundary")
    no_candidate = sum(1 for row in rows if int(row.get("candidate_count") or 0) == 0)
    no_candidate_status = sum(1 for row in rows if row.get("candidate_coverage_status") == "no_candidate")
    filtered_candidate_count = sum(int(row.get("filtered_candidate_count") or 0) for row in rows)
    return {
        "total_observations": total,
        "rows_with_at_least_1_candidate": len(with_candidate),
        "rows_with_at_least_3_candidates": len(with_three),
        "rows_with_high_or_medium_candidate": len(high_medium),
        "rows_with_only_low_risk_candidates": len(only_low_risk),
        "rows_blocked_by_note_boundaries": blocked,
        "no_candidate_rows": no_candidate,
        "no_candidate_status_rows": no_candidate_status,
        "candidate_coverage_rate": safe_rate(len(with_candidate), total),
        "three_candidate_coverage_rate": safe_rate(len(with_three), total),
        "high_or_medium_candidate_coverage_rate": safe_rate(len(high_medium), total),
        "candidate_coverage_status_counts": dict(sorted(status_counts.items())),
        "candidate_count_by_row": {str(key): value for key, value in sorted(candidate_counts_by_row.items())},
        "candidate_source_counts": dict(sorted(candidate_source_counts.items())),
        "candidate_source_row_counts": dict(sorted(source_row_counts.items())),
        "risk_distribution": dict(sorted(risk_counts.items())),
        "confidence_bucket_distribution": dict(sorted(confidence_counts.items())),
        "filtered_candidate_count": filtered_candidate_count,
        "filtered_reason_counts": dict(sorted(filtered_reason_counts.items())),
        "safe_for_auto_apply_count": sum(1 for row in rows for candidate in row.get("candidates") or [] if candidate.get("safe_for_auto_apply") is True),
        "requires_human_review_count": sum(1 for row in rows for candidate in row.get("candidates") or [] if candidate.get("requires_human_review") is True),
        "safety": dict(SAFETY),
    }


def _period_matches(row: PdfRowValue, fact: Mapping[str, Any]) -> bool:
    fact_year = fact_period_year(fact)
    if row.expected_year and fact_year and row.expected_year != fact_year:
        return False
    expected_type = expected_period_type_for_statement(row.pdf_statement_family)
    actual_type = fact_period_type(fact)
    return not (expected_type and actual_type != "unknown" and expected_type != actual_type)


def _support_qnames(row: PdfRowValue, facts: Sequence[Mapping[str, Any]]) -> tuple[set[str], set[str]]:
    value = normalize_numeric_value(row.pdf_value)
    same_value = [fact for fact in facts if (fact.get("normalized_value") or normalize_numeric_value(fact.get("value"))) == value]
    exact = {str(fact.get("qname")) for fact in same_value if _period_matches(row, fact) and fact.get("qname")}
    uncertain = {str(fact.get("qname")) for fact in same_value if fact.get("qname")}
    return exact, uncertain


def evaluate_candidate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    row_values: Sequence[PdfRowValue],
    facts_by_sample: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    row_by_id = {(row.sample_id, row.pdf_row_id): row for row in row_values}
    records = []
    unique_support_rows = 0
    candidate_rows_with_support = 0
    top1_hits = 0
    top3_hits = 0
    top5_hits = 0
    correct_risk_counts: Counter[str] = Counter()

    for ranked in rows:
        key = (str(ranked.get("sample_id") or ""), str(ranked.get("row_id") or ""))
        row = row_by_id.get(key)
        qnames = [str(candidate.get("qname")) for candidate in ranked.get("candidates") or [] if candidate.get("qname")]
        item = {
            "sample_id": ranked.get("sample_id"),
            "row_id": ranked.get("row_id"),
            "pdf_label": ranked.get("pdf_label"),
            "normalized_label": ranked.get("normalized_label"),
            "candidate_qnames": qnames,
            "top1_qname": qnames[0] if qnames else None,
            "evaluation_status": "not_evaluable",
            "correct_qname": None,
            "correct_candidate_rank": None,
            "correct_candidate_risk_level": None,
        }
        if row is None:
            item["evaluation_status"] = "not_evaluable"
            item["reason"] = "row_value_not_found"
            records.append(item)
            continue
        facts = facts_by_sample.get(row.sample_id) or []
        exact, uncertain = _support_qnames(row, facts)
        support = exact or uncertain
        if not support:
            item["evaluation_status"] = "not_evaluable"
            item["reason"] = "no_same_value_xbrl_support"
            records.append(item)
            continue
        if len(support) > 1:
            item["evaluation_status"] = "ambiguous_xbrl_support"
            item["candidate_support_qnames"] = sorted(support)[:8]
            records.append(item)
            continue

        unique_support_rows += 1
        correct = next(iter(support))
        item["correct_qname"] = correct
        if qnames:
            candidate_rows_with_support += 1
            if qnames[0] == correct:
                top1_hits += 1
        if correct in qnames[:3]:
            top3_hits += 1
        if correct in qnames[:5]:
            top5_hits += 1
        if correct in qnames:
            rank = qnames.index(correct) + 1
            item["correct_candidate_rank"] = rank
            candidate = (ranked.get("candidates") or [])[rank - 1]
            risk = str(candidate.get("risk_level") or "unknown")
            item["correct_candidate_risk_level"] = risk
            correct_risk_counts[risk] += 1
            if rank == 1:
                item["evaluation_status"] = "correct_qname_top1"
            elif rank <= 3:
                item["evaluation_status"] = "correct_qname_top3"
            elif rank <= 5:
                item["evaluation_status"] = "correct_qname_top5"
            else:
                item["evaluation_status"] = "correct_qname_below_top5"
        else:
            item["evaluation_status"] = "correct_qname_not_in_candidates"
        records.append(item)

    status_counts = Counter(str(item.get("evaluation_status") or "unknown") for item in records)
    summary = {
        "total_rows": len(rows),
        "locally_evaluable_unique_support_rows": unique_support_rows,
        "candidate_rows_with_local_support": candidate_rows_with_support,
        "top1_hits": top1_hits,
        "top3_hits": top3_hits,
        "top5_hits": top5_hits,
        "top1_precision_if_evaluable": safe_rate(top1_hits, candidate_rows_with_support),
        "top3_recall_if_evaluable": safe_rate(top3_hits, unique_support_rows),
        "top5_recall_if_evaluable": safe_rate(top5_hits, unique_support_rows),
        "evaluation_status_counts": dict(sorted(status_counts.items())),
        "correct_candidate_risk_distribution": dict(sorted(correct_risk_counts.items())),
        "safe_for_auto_apply_count": sum(1 for row in rows for candidate in row.get("candidates") or [] if candidate.get("safe_for_auto_apply") is True),
        "requires_human_review_count": sum(1 for row in rows for candidate in row.get("candidates") or [] if candidate.get("requires_human_review") is True),
        "safety": dict(SAFETY),
    }
    return {"summary": summary, "records": sanitize_report_value(records)}


def build_uncovered_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    uncovered = [row for row in rows if not row.get("candidates")]
    top_labels = Counter(str(row.get("normalized_label") or canonical_label(row.get("pdf_label"))) for row in uncovered)
    too_many = [row for row in rows if int(row.get("candidate_count") or 0) >= 5]
    return sanitize_report_value(
        {
            "summary": {
                "uncovered_row_count": len(uncovered),
                "rows_with_top_n_saturated": len(too_many),
                "top_uncovered_labels": [{"normalized_label": label, "count": count} for label, count in top_labels.most_common(40) if label],
                "safe_for_auto_apply_count": 0,
                "safety": dict(SAFETY),
            },
            "uncovered_rows": [
                {
                    "sample_id": row.get("sample_id"),
                    "row_id": row.get("row_id"),
                    "pdf_label": row.get("pdf_label"),
                    "normalized_label": row.get("normalized_label"),
                    "statement_family": row.get("statement_family"),
                    "section_block": row.get("section_block"),
                    "row_role": row.get("row_role"),
                    "candidate_coverage_status": row.get("candidate_coverage_status"),
                    "blocked_candidate_count": row.get("blocked_candidate_count"),
                    "filtered_candidate_count": row.get("filtered_candidate_count"),
                    "filtered_candidates": row.get("filtered_candidates"),
                    "blocked_candidates": row.get("blocked_candidates"),
                }
                for row in uncovered
            ],
            "top_n_saturated_rows": [
                {
                    "sample_id": row.get("sample_id"),
                    "row_id": row.get("row_id"),
                    "pdf_label": row.get("pdf_label"),
                    "normalized_label": row.get("normalized_label"),
                    "candidate_count": row.get("candidate_count"),
                    "top_candidate_qnames": [candidate.get("qname") for candidate in row.get("candidates") or []],
                }
                for row in too_many[:120]
            ],
        }
    )


def build_risk_analysis_report(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    candidate_rows = []
    risk_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    blocked_rows = []
    status_blocked_rows = 0
    for row in rows:
        if row.get("candidate_coverage_status") == "blocked_by_note_boundary":
            status_blocked_rows += 1
        if row.get("blocked_candidates"):
            blocked_rows.append(row)
        for candidate in row.get("candidates") or []:
            risk = str(candidate.get("risk_level") or "unknown")
            risk_counts[risk] += 1
            family_counts[_candidate_concept_family(candidate)] += 1
            if risk in {"high", "critical"}:
                candidate_rows.append(
                    {
                        "sample_id": row.get("sample_id"),
                        "row_id": row.get("row_id"),
                        "pdf_label": row.get("pdf_label"),
                        "normalized_label": row.get("normalized_label"),
                        "statement_family": row.get("statement_family"),
                        "qname": candidate.get("qname"),
                        "concept_label": candidate.get("concept_label"),
                        "rank": candidate.get("rank"),
                        "score": candidate.get("score"),
                        "risk_level": risk,
                        "risk_reasons": candidate.get("risk_reasons"),
                        "ambiguity_reasons": candidate.get("ambiguity_reasons"),
                        "candidate_sources_combined": candidate.get("candidate_sources_combined"),
                    }
                )
    return sanitize_report_value(
        {
            "summary": {
                "candidate_risk_distribution": dict(sorted(risk_counts.items())),
                "high_or_critical_candidate_count": sum(count for risk, count in risk_counts.items() if risk in {"high", "critical"}),
                "high_or_critical_candidate_family_counts": dict(sorted(family_counts.items())),
                "rows_blocked_by_note_boundaries": status_blocked_rows,
                "rows_with_blocked_note_boundary_candidates": len(blocked_rows),
                "safe_for_auto_apply_count": 0,
                "safety": dict(SAFETY),
            },
            "high_risk_candidates": candidate_rows[:250],
            "rows_blocked_by_note_boundaries": [
                {
                    "sample_id": row.get("sample_id"),
                    "row_id": row.get("row_id"),
                    "pdf_label": row.get("pdf_label"),
                    "normalized_label": row.get("normalized_label"),
                    "blocked_candidates": row.get("blocked_candidates"),
                }
                for row in blocked_rows[:250]
            ],
        }
    )


def recommendation(summary: Mapping[str, Any], evaluation: Mapping[str, Any], risk: Mapping[str, Any]) -> dict[str, Any]:
    coverage = float(summary.get("candidate_coverage_rate") or 0.0)
    top5 = float((evaluation.get("summary") or {}).get("top5_recall_if_evaluable") or 0.0)
    risk_summary = risk.get("summary") or {}
    high_critical = int(risk_summary.get("high_or_critical_candidate_count") or 0)
    candidate_total = sum(int(value) for value in (summary.get("risk_distribution") or {}).values())
    noisy = candidate_total > 0 and (high_critical / candidate_total) > 0.55
    if coverage >= 0.8 and top5 >= 0.65 and not noisy:
        feature = "Feature #18F-C - Design backend advisory integration for ranked candidates, no auto-apply"
        reason = "Candidate coverage approaches the 80% target with manageable top-5 support and risk."
    elif coverage >= 0.7 and top5 >= 0.5 and not noisy:
        feature = "Feature #18F-B - Hybrid candidate-ranking hardening and threshold calibration"
        reason = "Candidate coverage is high enough to justify calibration before any integration design."
    elif coverage < 0.6:
        feature = "Feature #18E-F-A-hotfix-1 - Improve taxonomy lexical candidate generation / concept metadata coverage"
        reason = "Candidate coverage remains below 60%, so concept metadata and lexical generation are the limiting factors."
    elif noisy:
        feature = "Feature #18E-F-A-hotfix-2 - Tighten risk scoring and candidate filters"
        reason = "Candidate coverage is usable but high/critical risk candidates dominate the review burden."
    else:
        feature = "Feature #18F-B - Hybrid candidate-ranking hardening and threshold calibration"
        reason = "Candidate ranking is viable but needs threshold calibration before integration planning."
    return {
        "recommended_next_feature": feature,
        "reason": reason,
        "basis": {
            "candidate_coverage_rate": coverage,
            "top5_recall_if_evaluable": top5,
            "high_or_critical_candidate_count": high_critical,
            "candidate_total": candidate_total,
            "candidate_list_too_noisy": noisy,
        },
    }


def build_design_report(generated_at: str, summary: Mapping[str, Any] | None = None, evaluation: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "run_metadata": {"feature": "18E-F-A", "generated_at": generated_at, "offline_only": True, **SAFETY},
        "design": {
            "problem": "Deterministic single-qname mapping stalled around the 40-45% useful coverage range once risky expansions were tightened.",
            "new_target": "Candidate coverage: provide one or more ranked plausible taxonomy candidates for at least 80% of rows, with evidence and risk, without final mapping automation.",
            "candidate_sources": [
                "Current #18E-B-3 deterministic mapper output",
                "Statement-specific dictionary candidates",
                "Local taxonomy concept-label lexical search from mpers_templates.json or optional metadata",
                "Optional cached Qwen suggestions when present locally; no Qwen call is made",
            ],
            "evidence_scoring": [
                "Normalized label similarity",
                "Statement-family compatibility",
                "Section context and row-role agreement",
                "Template, note-link, format-memory, dictionary, and row-order source evidence",
                "Prior local exact-match evidence from existing offline evaluation reports",
                "Source reliability weights from current deterministic evidence quality",
            ],
            "risk_scoring": [
                "Note-detail, movement, and reconciliation boundaries",
                "Generic total/subtotal/component labels",
                "Balance-sheet versus cash-flow ambiguity",
                "Tax expense versus tax payable/deferred tax ambiguity",
                "Receivable/payable detail ambiguity",
                "Borrowings/loans weak-label ambiguity",
                "Low context confidence",
                "Multiple candidates close in score",
            ],
            "top_n_output": {
                "per_row": [
                    "candidate_coverage_status",
                    "ranked candidates",
                    "score",
                    "confidence_bucket",
                    "risk_level",
                    "evidence",
                    "blocking_reasons",
                    "ambiguity_reasons",
                    "requires_human_review=true",
                    "safe_for_auto_apply=false",
                ]
            },
            "human_review_boundary": "Every candidate is review evidence only. Human or future Supervisor review remains final.",
            "no_auto_apply_boundary": "The prototype never writes confirmed_tag_id, never auto-accepts, never auto-rejects, and never marks safe_for_auto_apply true.",
            "future_qwen_supervisor_role": "Qwen and Supervisor may later score or review ranked candidates, but this feature makes no LLM calls and only supports optional cached local suggestions as another candidate source.",
            "production_integration_phases": [
                "Offline ranking and metrics prototype",
                "Threshold/risk calibration",
                "Backend advisory integration design behind feature flag",
                "UI display of ranked advisory candidates",
                "Supervisor/human review workflow, still no auto-apply without separate approval",
            ],
        },
        "current_summary": dict(summary or {}),
        "current_evaluation": dict((evaluation or {}).get("summary") or {}),
        "safety": dict(SAFETY),
    }


def build_reports(
    *,
    records: Sequence[Mapping[str, Any]],
    concepts: Sequence[Mapping[str, Any]],
    evaluation_report: Mapping[str, Any] | None,
    qwen_index: Mapping[tuple[str, str], Sequence[Mapping[str, Any]]] | None,
    local_concept_cards: Sequence[Mapping[str, Any]] = (),
    row_values: Sequence[PdfRowValue],
    facts_by_sample: Mapping[str, Sequence[Mapping[str, Any]]],
    top_n: int = 5,
    debug_label: str | None = None,
    metadata_diagnostics: Mapping[str, Any] | None = None,
    qwen_diagnostics: Mapping[str, Any] | None = None,
    filter_mode: str = "baseline",
    enable_local_sources: bool = False,
    include_existing_candidates: bool = False,
    include_standard_sources: bool = True,
    ranking_profile: str | None = None,
) -> dict[str, dict[str, Any]]:
    generated_at = utc_now()
    rows = rank_candidate_rows(
        records,
        concepts=concepts,
        evaluation_report=evaluation_report,
        qwen_index=qwen_index or {},
        local_concept_cards=local_concept_cards,
        top_n=top_n,
        debug_label=debug_label,
        filter_mode=filter_mode,
        enable_local_sources=enable_local_sources,
        include_existing_candidates=include_existing_candidates,
        include_standard_sources=include_standard_sources,
        ranking_profile=ranking_profile,
    )
    summary = summarize_candidate_rows(rows)
    evaluation = evaluate_candidate_rows(rows, row_values=row_values, facts_by_sample=facts_by_sample)
    uncovered = build_uncovered_report(rows)
    risk = build_risk_analysis_report(rows)
    rec = recommendation(summary, evaluation, risk)
    design = build_design_report(generated_at, summary=summary, evaluation=evaluation)
    ranking = {
        "run_metadata": {
            "feature": "18E-F-A",
            "generated_at": generated_at,
            "top_n": top_n,
            "debug_label": debug_label,
            "filter_mode": filter_mode,
            "ranking_profile": ranking_profile,
            "offline_only": True,
            **SAFETY,
        },
        "summary": summary,
        "metadata_diagnostics": dict(metadata_diagnostics or {}),
        "qwen_diagnostics": dict(qwen_diagnostics or {}),
        "recommendation": rec,
        "ranked_rows": rows,
    }
    summary_report = {
        "run_metadata": ranking["run_metadata"],
        "summary": summary,
        "evaluation_summary": evaluation["summary"],
        "risk_summary": risk["summary"],
        "recommendation": rec,
    }
    evaluation_report_out = {"run_metadata": ranking["run_metadata"], **evaluation}
    risk_report = {"run_metadata": ranking["run_metadata"], **risk}
    uncovered_report = {"run_metadata": ranking["run_metadata"], **uncovered}
    design["recommendation"] = rec
    return {
        "ranking": sanitize_report_value(ranking),
        "summary": sanitize_report_value(summary_report),
        "evaluation": sanitize_report_value(evaluation_report_out),
        "uncovered": sanitize_report_value(uncovered_report),
        "risk_analysis": sanitize_report_value(risk_report),
        "design": sanitize_report_value(design),
    }


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    evaluation = report.get("evaluation_summary") or {}
    risk = report.get("risk_summary") or {}
    rec = report.get("recommendation") or {}
    lines = [
        "# Hybrid Candidate Ranking Summary #18E-F-A",
        "",
        "All candidates are review-only evidence. No candidate is safe for auto-apply.",
        "",
        f"- Total observations: `{summary.get('total_observations')}`",
        f"- Rows with >=1 candidate: `{summary.get('rows_with_at_least_1_candidate')}`",
        f"- Rows with >=3 candidates: `{summary.get('rows_with_at_least_3_candidates')}`",
        f"- No-candidate rows: `{summary.get('no_candidate_rows')}`",
        f"- Candidate coverage rate: `{summary.get('candidate_coverage_rate')}`",
        f"- Top-1 precision if evaluable: `{evaluation.get('top1_precision_if_evaluable')}`",
        f"- Top-3 recall if evaluable: `{evaluation.get('top3_recall_if_evaluable')}`",
        f"- Top-5 recall if evaluable: `{evaluation.get('top5_recall_if_evaluable')}`",
        f"- Risk distribution: `{summary.get('risk_distribution')}`",
        f"- High/critical candidate count: `{risk.get('high_or_critical_candidate_count')}`",
        f"- safe_for_auto_apply_count: `{summary.get('safe_for_auto_apply_count')}`",
        f"- Recommended next feature: `{rec.get('recommended_next_feature')}`",
        f"- Recommendation reason: {rec.get('reason')}",
    ]
    return "\n".join(lines) + "\n"


def render_ranking_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Hybrid Candidate Ranking #18E-F-A",
        "",
        "Offline ranked candidate output. Human review remains required.",
        "",
        f"- Rows with candidates: `{summary.get('rows_with_at_least_1_candidate')}`",
        f"- Candidate coverage rate: `{summary.get('candidate_coverage_rate')}`",
        f"- Source contribution: `{summary.get('candidate_source_counts')}`",
        "",
        "| Row | Label | Candidate Count | Top Candidate | Score | Risk |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for row in (report.get("ranked_rows") or [])[:80]:
        top = (row.get("candidates") or [{}])[0]
        lines.append(
            f"| {row.get('row_id')} | {row.get('normalized_label')} | {row.get('candidate_count')} | "
            f"{top.get('qname') or ''} | {top.get('score') or ''} | {top.get('risk_level') or ''} |"
        )
    return "\n".join(lines) + "\n"


def render_evaluation_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Hybrid Candidate Ranking Evaluation #18E-F-A",
        "",
        f"- Locally evaluable unique-support rows: `{summary.get('locally_evaluable_unique_support_rows')}`",
        f"- Top-1 precision if evaluable: `{summary.get('top1_precision_if_evaluable')}`",
        f"- Top-3 recall if evaluable: `{summary.get('top3_recall_if_evaluable')}`",
        f"- Top-5 recall if evaluable: `{summary.get('top5_recall_if_evaluable')}`",
        f"- Evaluation status counts: `{summary.get('evaluation_status_counts')}`",
    ]
    return "\n".join(lines) + "\n"


def render_uncovered_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Hybrid Candidate Ranking Uncovered Rows #18E-F-A",
        "",
        f"- Uncovered rows: `{summary.get('uncovered_row_count')}`",
        f"- Rows with saturated top-N candidate lists: `{summary.get('rows_with_top_n_saturated')}`",
        "",
        "| Label | Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("top_uncovered_labels") or []:
        lines.append(f"| {item.get('normalized_label')} | {item.get('count')} |")
    return "\n".join(lines) + "\n"


def render_risk_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Hybrid Candidate Ranking Risk Analysis #18E-F-A",
        "",
        f"- Candidate risk distribution: `{summary.get('candidate_risk_distribution')}`",
        f"- High/critical candidate count: `{summary.get('high_or_critical_candidate_count')}`",
        f"- Rows blocked by note boundaries: `{summary.get('rows_blocked_by_note_boundaries')}`",
    ]
    return "\n".join(lines) + "\n"


def render_design_markdown(report: Mapping[str, Any]) -> str:
    design = report.get("design") or {}
    rec = report.get("recommendation") or {}
    lines = [
        "# Hybrid Candidate Ranking Design #18E-F-A",
        "",
        f"## Why deterministic-only stalled",
        design.get("problem") or "",
        "",
        "## New target",
        design.get("new_target") or "",
        "",
        "## Candidate sources",
    ]
    lines.extend(f"- {item}" for item in design.get("candidate_sources") or [])
    lines.extend(["", "## Evidence scoring"])
    lines.extend(f"- {item}" for item in design.get("evidence_scoring") or [])
    lines.extend(["", "## Risk scoring"])
    lines.extend(f"- {item}" for item in design.get("risk_scoring") or [])
    lines.extend(
        [
            "",
            "## Review boundary",
            design.get("human_review_boundary") or "",
            "",
            "## No-auto-apply boundary",
            design.get("no_auto_apply_boundary") or "",
            "",
            "## Future Qwen/Supervisor role",
            design.get("future_qwen_supervisor_role") or "",
            "",
            "## Production phases",
        ]
    )
    lines.extend(f"- {item}" for item in design.get("production_integration_phases") or [])
    lines.extend(["", "## Recommended next feature", f"`{rec.get('recommended_next_feature')}` - {rec.get('reason')}"])
    return "\n".join(lines) + "\n"


def markdown_reports(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    return {
        "ranking": render_ranking_markdown(reports["ranking"]),
        "summary": render_summary_markdown(reports["summary"]),
        "evaluation": render_evaluation_markdown(reports["evaluation"]),
        "uncovered": render_uncovered_markdown(reports["uncovered"]),
        "risk_analysis": render_risk_markdown(reports["risk_analysis"]),
        "design": render_design_markdown(reports["design"]),
    }
