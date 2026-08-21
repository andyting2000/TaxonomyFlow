"""Read-only mapping suggestions for Azure DI normalized handoff candidates."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping


DEFAULT_HANDOFF_REPORT = Path("reports/azure_di_normalized_mapping_handoff_13y.json")
DEFAULT_REFERENCE_REPORT = Path("reports/reference_xbrl_report_20260511T082343Z.json")
DEFAULT_TEMPLATE_FILE = Path("mpers_templates.json")
DEFAULT_OUTPUT_DIR = Path("reports")
NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
ALLOWED_GATE_STATUSES = {"auto_mappable_candidate", "suggest_mapping_only"}
GENERIC_LABELS = {
    "other",
    "total",
    "subtotal",
    "current",
    "previous",
    "prior",
    "owners of the company",
    "no par value",
}
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
}

SECTION_FAMILY_PATTERNS = [
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
    ("financial_position", re.compile(r"financial\s+position|assets|liabilit|equity", re.IGNORECASE)),
    ("comprehensive_income", re.compile(r"comprehensive\s+income|profit|loss|tax|expense|income", re.IGNORECASE)),
    ("cash_flows", re.compile(r"cash\s+flows?|cash\s+and\s+cash\s+equivalents|overdraft", re.IGNORECASE)),
    ("changes_in_equity", re.compile(r"changes\s+in\s+equity|share\s+capital|retained|accumulated", re.IGNORECASE)),
    ("corporate_information", re.compile(r"corporate\s+information|principal\s+place|registered\s+office", re.IGNORECASE)),
    ("accounting_policies", re.compile(r"accounting\s+polic|basis\s+of\s+preparation", re.IGNORECASE)),
    ("notes", re.compile(r"notes?\s+to\s+the\s+financial\s+statements|receivable|payable|director", re.IGNORECASE)),
]

ALIAS_GROUPS = {
    "cash": {"cash", "cash equivalents", "cash and bank balances", "bank balances", "bank overdraft"},
    "receivables": {"receivable", "receivables", "other receivable", "trade receivables"},
    "payables": {"payable", "payables", "other payable", "trade payables"},
    "share_capital": {"share capital", "contributed share capital", "ordinary shares"},
    "accumulated_losses": {"accumulated loss", "accumulated losses", "retained earnings"},
    "tax": {"tax", "tax expense", "income tax"},
    "loss": {"loss", "loss before tax", "loss after tax", "total comprehensive loss"},
    "directors_report": {"directors report", "director's report"},
    "statement_by_directors": {"statement by directors"},
    "statutory_declaration": {"statutory declaration"},
    "accounting_policies": {"accounting policies", "basis of preparation"},
    "corporate_information": {"corporate information", "registered office", "principal place of business"},
}


@dataclass(frozen=True)
class MappingOutputPaths:
    candidates_json: Path
    candidates_md: Path
    confidence_json: Path
    confidence_md: Path
    gap_json: Path
    gap_md: Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def no_side_effect_metadata() -> dict[str, Any]:
    return {
        "feature": "13Z",
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


def output_paths_from_prefix(output_prefix: str | Path | None = None) -> MappingOutputPaths:
    if output_prefix is None:
        root = DEFAULT_OUTPUT_DIR
        return MappingOutputPaths(
            candidates_json=root / "azure_di_mapping_candidates_13z.json",
            candidates_md=root / "azure_di_mapping_candidates_13z.md",
            confidence_json=root / "azure_di_mapping_confidence_13z.json",
            confidence_md=root / "azure_di_mapping_confidence_13z.md",
            gap_json=root / "azure_di_mapping_gap_analysis_13z.json",
            gap_md=root / "azure_di_mapping_gap_analysis_13z.md",
        )
    prefix = Path(output_prefix)
    return MappingOutputPaths(
        candidates_json=Path(f"{prefix}_mapping_candidates_13z.json"),
        candidates_md=Path(f"{prefix}_mapping_candidates_13z.md"),
        confidence_json=Path(f"{prefix}_mapping_confidence_13z.json"),
        confidence_md=Path(f"{prefix}_mapping_confidence_13z.md"),
        gap_json=Path(f"{prefix}_mapping_gap_analysis_13z.json"),
        gap_md=Path(f"{prefix}_mapping_gap_analysis_13z.md"),
    )


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text(value: Any) -> str:
    text = clean_text(value).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))


def token_set(value: Any) -> set[str]:
    return {token for token in normalize_text(value).split() if len(token) >= 3 and token not in STOPWORDS}


def token_overlap(left: Any, right: Any) -> float:
    left_tokens = token_set(left)
    right_tokens = token_set(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def label_similarity(left: Any, right: Any) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def statement_family(value: Any) -> str | None:
    text = clean_text(value)
    for family, pattern in SECTION_FAMILY_PATTERNS:
        if pattern.search(text):
            return family
    return None


def is_generic_label(value: Any) -> bool:
    label = normalize_text(value)
    if not label:
        return True
    if label in GENERIC_LABELS:
        return True
    tokens = token_set(label)
    return len(tokens) <= 1 and label not in {"cash", "tax"}


def is_heading_like(value: Any) -> bool:
    text = clean_text(value)
    if not text:
        return False
    if len(text.split()) <= 8 and (text.isupper() or text.istitle()):
        return True
    return bool(re.search(r"\b(statement|directors'? report|notes to|assets|liabilities|equity)\b", text, re.IGNORECASE))


def _local_name(qname: str) -> str:
    return str(qname or "").split(":")[-1]


def _concept_type(concept_id: str, label: str) -> tuple[str, bool | str, bool | str]:
    local = _local_name(concept_id)
    local_norm = local.lower()
    label_norm = normalize_text(label)
    if "text block" in label_norm or local_norm.endswith("explanatory") or "explanatory" in label_norm:
        return "text_block", False, True
    if re.search(r"(axis|member|abstract|table|lineitems|domain)$", local_norm):
        return "structural", False, False
    if re.match(r"^(date|name|type|identification|description|method|disclosurewhether|numberof)", local_norm):
        return "string_or_metadata", False, False
    if label_norm.startswith(("date ", "name ", "type ", "description ", "method ", "number ")):
        return "string_or_metadata", False, False
    if "disclosure " in label_norm and "text block" not in label_norm:
        return "string_or_metadata", False, False
    return "numeric", True, False


def _concept_aliases(label: str, concept_id: str) -> list[str]:
    aliases = {normalize_text(label), normalize_text(_local_name(concept_id))}
    local_words = re.sub(r"([a-z])([A-Z])", r"\1 \2", _local_name(concept_id))
    aliases.add(normalize_text(local_words))
    for values in ALIAS_GROUPS.values():
        if token_set(label) & token_set(" ".join(values)) or token_set(local_words) & token_set(" ".join(values)):
            aliases.update(normalize_text(value) for value in values)
    return sorted(alias for alias in aliases if alias)


def _concept_from_template(code: str, description: str, concept: Mapping[str, Any]) -> dict[str, Any]:
    concept_id = str(concept.get("id") or concept.get("qname") or "")
    label = clean_text(concept.get("label") or concept_id)
    concept_type, is_numeric, is_text_block = _concept_type(concept_id, label)
    return {
        "concept_qname": concept_id,
        "concept_label": label,
        "concept_type": concept.get("type") or concept_type,
        "statement_family": statement_family(f"{description} {label} {concept_id}") or "unknown",
        "is_numeric_concept": is_numeric,
        "is_text_block_concept": is_text_block,
        "template_code": code,
        "template_description": description,
        "source": "mpers_templates.json",
        "aliases": _concept_aliases(label, concept_id) + [normalize_text(item) for item in concept.get("aliases") or []],
    }


def load_local_concept_metadata(
    *,
    template_path: str | Path = DEFAULT_TEMPLATE_FILE,
    reference_report_path: str | Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    limitations: list[str] = []
    concepts: dict[str, dict[str, Any]] = {}
    template = Path(template_path)
    if template.exists():
        data = json.loads(template.read_text(encoding="utf-8"))
        for code, template_data in (data.get("templates") or {}).items():
            description = clean_text(template_data.get("description") or code)
            for concept in template_data.get("concepts") or []:
                record = _concept_from_template(str(code), description, concept)
                if record["concept_qname"]:
                    concepts.setdefault(record["concept_qname"], record)
    else:
        limitations.append(f"Local template metadata file not found: {template}")

    if reference_report_path:
        ref_path = Path(reference_report_path)
        if ref_path.exists():
            reference = json.loads(ref_path.read_text(encoding="utf-8"))
            for case in reference.get("case_reports") or []:
                for fact in case.get("facts") or []:
                    qname = str(fact.get("qname") or fact.get("concept") or "")
                    if not qname or qname in concepts:
                        continue
                    label = clean_text(fact.get("label") or fact.get("local_name") or _local_name(qname))
                    concept_type, is_numeric, is_text_block = _concept_type(qname, label)
                    concepts[qname] = {
                        "concept_qname": qname,
                        "concept_label": label,
                        "concept_type": concept_type,
                        "statement_family": statement_family(label) or "unknown",
                        "is_numeric_concept": bool(fact.get("is_numeric")) if fact.get("is_numeric") is not None else is_numeric,
                        "is_text_block_concept": bool(fact.get("is_text_block")) if fact.get("is_text_block") is not None else is_text_block,
                        "template_code": None,
                        "template_description": None,
                        "source": "reference_report_concept_inventory",
                        "aliases": _concept_aliases(label, qname),
                    }
            limitations.append(
                "Reference report was used only as an offline concept inventory fallback, not as a direct answer key."
            )
    if not concepts:
        limitations.append("No local concept metadata was available; all candidates will be no_safe_suggestion.")
    return list(concepts.values()), limitations


def _alias_match(candidate_label: str, concept: Mapping[str, Any]) -> bool:
    label_norm = normalize_text(candidate_label)
    aliases = [normalize_text(item) for item in concept.get("aliases") or []]
    return any(alias and (alias == label_norm or alias in label_norm or label_norm in alias) for alias in aliases)


def _alias_evidence(candidate_label: str, concept: Mapping[str, Any]) -> dict[str, Any]:
    label_norm = normalize_text(candidate_label)
    if not label_norm:
        return {
            "alias_match": False,
            "exact_alias_match": False,
            "alias_source_strength": 0.0,
            "matched_alias": None,
            "matched_alias_source": None,
            "matched_alias_group": None,
        }
    best: dict[str, Any] | None = None
    records = list(concept.get("alias_records") or [])
    if not records:
        records = [
            {"alias": alias, "normalized_alias": normalize_text(alias), "source": "legacy_alias", "strength": 0.6}
            for alias in concept.get("aliases") or []
        ]
    for record in records:
        alias_norm = normalize_text(record.get("normalized_alias") or record.get("alias"))
        if not alias_norm:
            continue
        exact = alias_norm == label_norm
        contained = alias_norm in label_norm or label_norm in alias_norm
        if not exact and not contained:
            continue
        strength = float(record.get("strength") or 0.6)
        candidate = {
            "alias_match": True,
            "exact_alias_match": exact,
            "alias_source_strength": strength,
            "matched_alias": record.get("alias") or alias_norm,
            "matched_alias_source": record.get("source"),
            "matched_alias_group": record.get("group"),
        }
        if best is None or (candidate["exact_alias_match"], candidate["alias_source_strength"]) > (
            best["exact_alias_match"],
            best["alias_source_strength"],
        ):
            best = candidate
    return best or {
        "alias_match": False,
        "exact_alias_match": False,
        "alias_source_strength": 0.0,
        "matched_alias": None,
        "matched_alias_source": None,
        "matched_alias_group": None,
    }


def _candidate_statement_family(item: Mapping[str, Any]) -> str | None:
    query = _query_text(item)
    family = statement_family(query)
    if family and family != "notes":
        return family
    section_family = statement_family(item.get("statement_section"))
    return family or section_family


def _phrase_containment(left: Any, right: Any) -> bool:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    return bool(left_norm and right_norm and (left_norm in right_norm or right_norm in left_norm))


def _row_type_compatible(row_type: str, concept: Mapping[str, Any]) -> bool:
    if row_type in NUMERIC_ROW_TYPES:
        return concept.get("is_numeric_concept") is True and concept.get("is_text_block_concept") is not True
    if row_type == "text_block":
        return concept.get("is_text_block_concept") is True or str(concept.get("concept_type")) in {"text_block", "string_or_metadata"}
    return False


def _concept_type_match(row_type: str, concept: Mapping[str, Any]) -> bool:
    if row_type in NUMERIC_ROW_TYPES:
        return concept.get("is_numeric_concept") is True
    if row_type == "text_block":
        return concept.get("is_text_block_concept") is True
    return False


def _query_text(item: Mapping[str, Any]) -> str:
    parts = [
        clean_text(item.get("label")),
        clean_text(item.get("text") or item.get("text_preview") or item.get("source_snippet"))[:500],
        clean_text(item.get("statement_section")),
    ]
    return " ".join(part for part in parts if part)


def _score_concept(item: Mapping[str, Any], concept: Mapping[str, Any]) -> dict[str, Any] | None:
    row_type = str(item.get("row_type") or "")
    label = clean_text(item.get("label") or item.get("text") or item.get("source_snippet"))
    section = clean_text(item.get("statement_section"))
    query = _query_text(item)
    concept_label = clean_text(concept.get("concept_label"))

    if row_type in NUMERIC_ROW_TYPES and concept.get("is_text_block_concept") is True:
        return None
    if row_type == "text_block" and concept.get("is_numeric_concept") is True:
        return None

    exact = bool(normalize_text(label) and normalize_text(label) == normalize_text(concept_label)) or (
        bool(compact_text(label)) and compact_text(label) == compact_text(concept_label)
    )
    similarity = label_similarity(label, concept_label)
    overlap = max(token_overlap(label, concept_label), token_overlap(query, concept_label))
    label_alias = _alias_evidence(label, concept)
    query_alias = _alias_evidence(query, concept)
    alias_info = label_alias if label_alias["alias_source_strength"] >= query_alias["alias_source_strength"] else query_alias
    alias = bool(alias_info["alias_match"])
    phrase_containment = _phrase_containment(label, concept_label)
    candidate_family = _candidate_statement_family(item)
    concept_family = str(concept.get("statement_family") or "unknown")
    section_match = bool(candidate_family and concept_family == candidate_family)
    section_mismatch = bool(candidate_family and concept_family not in {candidate_family, "unknown", "notes"})
    row_match = _row_type_compatible(row_type, concept)
    type_match = _concept_type_match(row_type, concept)
    penalties: list[dict[str, Any]] = []

    score = 0.0
    if exact:
        score += 0.45
    score += 0.20 * similarity
    score += 0.25 * overlap
    if alias:
        score += 0.16 + (0.14 * float(alias_info.get("alias_source_strength") or 0.0))
    if alias_info.get("exact_alias_match"):
        score += 0.16
    if phrase_containment:
        score += 0.08
    if section_match:
        score += 0.14
    if row_match:
        score += 0.10
    if type_match:
        score += 0.12
    if row_type == "subtotal_or_total" and re.search(r"\b(total|loss|profit|assets|liabilities|equity)\b", concept_label, re.IGNORECASE):
        score += 0.05

    if is_generic_label(label):
        penalties.append({"code": "generic_label", "points": 0.22})
    if not section:
        penalties.append({"code": "missing_section", "points": 0.12})
    if is_heading_like(label) and row_type in NUMERIC_ROW_TYPES and not re.search(r"\b(total|loss|profit|tax)\b", label, re.IGNORECASE):
        penalties.append({"code": "heading_like_label", "points": 0.12})
    if section_mismatch:
        penalties.append({"code": "section_family_mismatch", "points": 0.18})
    if not row_match:
        penalties.append({"code": "row_type_concept_type_mismatch", "points": 0.35})
    for penalty in penalties:
        score -= float(penalty["points"])
    score = round(max(0.0, min(1.0, score)), 4)
    if score < 0.24:
        return None
    return {
        "concept_qname": concept.get("concept_qname"),
        "concept_label": concept_label,
        "concept_type": concept.get("concept_type"),
        "statement_family": concept.get("statement_family"),
        "is_numeric_concept": concept.get("is_numeric_concept", "unknown"),
        "is_text_block_concept": concept.get("is_text_block_concept", "unknown"),
        "score": score,
        "confidence_tier": "low",
        "evidence": {
            "exact_match": exact,
            "label_similarity": round(similarity, 4),
            "token_overlap": round(overlap, 4),
            "alias_match": alias,
            "exact_alias_match": bool(alias_info.get("exact_alias_match")),
            "alias_source_strength": round(float(alias_info.get("alias_source_strength") or 0.0), 4),
            "matched_alias": alias_info.get("matched_alias"),
            "matched_alias_source": alias_info.get("matched_alias_source"),
            "matched_alias_group": alias_info.get("matched_alias_group"),
            "phrase_containment": phrase_containment,
            "section_match": section_match,
            "section_family_mismatch": section_mismatch,
            "row_type_match": row_match,
            "concept_type_match": type_match,
            "penalties": penalties,
        },
        "warnings": [],
        "mapping_decision_status": "suggested_only",
        "source": "deterministic_local_metadata",
    }


def _close_second_best(top: Mapping[str, Any] | None, second: Mapping[str, Any] | None) -> bool:
    if not top or not second:
        return False
    return float(top.get("score") or 0) >= 0.55 and float(top.get("score") or 0) - float(second.get("score") or 0) < 0.07


def _status_and_tiers(item: Mapping[str, Any], suggestions: list[dict[str, Any]]) -> tuple[str, list[str]]:
    blockers: list[str] = []
    gate = str(item.get("gate_status") or "")
    if gate not in ALLOWED_GATE_STATUSES or not item.get("mapping_allowed", True):
        blockers.append("blocked_by_handoff_gate")
        return "blocked_by_gate", blockers
    if not suggestions:
        blockers.append("no_local_metadata_match_above_threshold")
        return "no_safe_suggestion", blockers

    top = suggestions[0]
    second = suggestions[1] if len(suggestions) > 1 else None
    evidence = top.get("evidence") or {}
    score = float(top.get("score") or 0)
    if _close_second_best(top, second):
        blockers.append("multiple_close_concept_matches")
        return "ambiguous_multiple_suggestions", blockers
    if evidence.get("section_family_mismatch"):
        blockers.append("section_family_mismatch")
        if score < 0.72:
            return "no_safe_suggestion", blockers
    if not evidence.get("row_type_match") or not evidence.get("concept_type_match"):
        blockers.append("row_type_or_concept_type_mismatch")
        return "no_safe_suggestion", blockers
    if is_generic_label(item.get("label")):
        blockers.append("generic_or_weak_label")
        return ("low_confidence_suggestion" if score >= 0.5 else "no_safe_suggestion"), blockers
    if not clean_text(item.get("statement_section")):
        blockers.append("missing_statement_section")
        return ("medium_confidence_suggestion" if score >= 0.7 else "low_confidence_suggestion"), blockers
    if item.get("requires_confirmation") or gate == "suggest_mapping_only":
        blockers.append("requires_confirmation")
        return ("medium_confidence_suggestion" if score >= 0.55 else "low_confidence_suggestion"), blockers
    if score >= 0.78:
        return "high_confidence_suggestion", blockers
    if score >= 0.55:
        return "medium_confidence_suggestion", blockers
    if score >= 0.35:
        return "low_confidence_suggestion", blockers
    blockers.append("top_score_below_safe_threshold")
    return "no_safe_suggestion", blockers


def _tier_for_status(status: str) -> str | None:
    if status.startswith("high_"):
        return "high"
    if status.startswith("medium_"):
        return "medium"
    if status.startswith("low_"):
        return "low"
    return None


def _build_mapping_record(item: Mapping[str, Any], concepts: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [
        scored
        for concept in concepts
        for scored in [_score_concept(item, concept)]
        if scored is not None
    ]
    scored.sort(key=lambda row: (-float(row.get("score") or 0), str(row.get("concept_qname") or "")))
    suggestions = scored[:5]
    status, blockers = _status_and_tiers(item, suggestions)
    tier = _tier_for_status(status)
    for suggestion in suggestions:
        suggestion["confidence_tier"] = tier or ("medium" if status == "ambiguous_multiple_suggestions" else "low")
        if status == "ambiguous_multiple_suggestions":
            suggestion["warnings"].append("multiple_close_concept_matches")
        if str(item.get("row_type")) == "subtotal_or_total":
            suggestion["warnings"].append("subtotal_or_total_requires_policy_confirmation")
    if status in {"no_safe_suggestion", "blocked_by_gate"}:
        suggestions = [] if status == "no_safe_suggestion" else suggestions

    top = suggestions[0] if suggestions else None
    return {
        "mapping_input_id": item.get("mapping_input_id"),
        "source_candidate_id": item.get("source_candidate_id"),
        "case_id": item.get("case_id"),
        "page_number": item.get("page_number"),
        "row_type": item.get("row_type"),
        "label": item.get("label"),
        "value": item.get("value"),
        "previous_value": item.get("previous_value"),
        "text_preview": clean_text(item.get("text") or item.get("source_snippet"))[:300],
        "statement_section": item.get("statement_section"),
        "gate_status": item.get("gate_status"),
        "requires_confirmation": bool(item.get("requires_confirmation")),
        "readiness_level": item.get("readiness_level"),
        "warning_flags": list(item.get("warning_flags") or []),
        "suggestions": suggestions,
        "top_suggestion": top,
        "suggestion_count": len(suggestions),
        "mapping_status": status,
        "blockers": blockers,
        "audit_trail": {
            "source": "13Z_deterministic_report_based_mapping_suggestion",
            "mapping_input_id": item.get("mapping_input_id"),
            "source_candidate_id": item.get("source_candidate_id"),
            "source_handoff_audit_trail": item.get("audit_trail") or {},
            "mapping_decision_status": "suggested_only",
            "final_mapping_approved": False,
        },
    }


def generate_mapping_candidate_reports(
    *,
    handoff_report: Mapping[str, Any],
    concept_metadata: list[dict[str, Any]] | None = None,
    concept_metadata_limitations: list[str] | None = None,
    input_paths: Mapping[str, Any] | None = None,
    run_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    concepts = concept_metadata or []
    records = [_build_mapping_record(item, concepts) for item in handoff_report.get("handoff_items") or []]
    candidates = build_candidates_report(
        handoff_report=handoff_report,
        mapping_records=records,
        concept_count=len(concepts),
        concept_metadata_limitations=concept_metadata_limitations or [],
        input_paths=input_paths or {},
        run_id=run_id,
    )
    confidence = build_confidence_report(candidates)
    gap = build_gap_analysis_report(candidates, concept_metadata_limitations=concept_metadata_limitations or [])
    return candidates, confidence, gap


def _count_by(records: Iterable[Mapping[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get(key) or "unknown") for record in records).items()))


def build_candidates_report(
    *,
    handoff_report: Mapping[str, Any],
    mapping_records: list[dict[str, Any]],
    concept_count: int,
    concept_metadata_limitations: list[str],
    input_paths: Mapping[str, Any],
    run_id: str | None,
) -> dict[str, Any]:
    status_counts = Counter(record["mapping_status"] for record in mapping_records)
    confidence_counts = Counter(_tier_for_status(record["mapping_status"]) or "none" for record in mapping_records)
    blocker_counts = Counter(blocker for record in mapping_records for blocker in record.get("blockers") or [])
    top_records = [record for record in mapping_records if record.get("top_suggestion")][:15]
    traceable = sum(1 for record in mapping_records if record.get("mapping_input_id") and record.get("source_candidate_id"))
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "run_id": run_id,
            "report_type": "azure_di_mapping_candidates",
            "script": "scripts/generate_azure_di_mapping_candidates_13z.py",
        },
        "input_reports": dict(input_paths),
        "source_feature_chain": ["13X", "13Y", "13Z"],
        "concept_metadata": {
            "source": "local mpers_templates.json plus optional reference concept inventory",
            "concept_count": concept_count,
            "limitations": concept_metadata_limitations,
        },
        "total_handoff_candidates": int(handoff_report.get("total_handoff_candidates") or len(mapping_records)),
        "mapping_record_count": len(mapping_records),
        "status_counts": dict(status_counts),
        "confidence_tier_counts": dict(confidence_counts),
        "per_case_mapping_summary": _count_by(mapping_records, "case_id"),
        "per_row_type_mapping_summary": _count_by(mapping_records, "row_type"),
        "high_confidence_count": status_counts.get("high_confidence_suggestion", 0),
        "medium_confidence_count": status_counts.get("medium_confidence_suggestion", 0),
        "low_confidence_count": status_counts.get("low_confidence_suggestion", 0),
        "ambiguous_multiple_suggestions_count": status_counts.get("ambiguous_multiple_suggestions", 0),
        "no_safe_suggestion_count": status_counts.get("no_safe_suggestion", 0),
        "blocked_by_gate_count": status_counts.get("blocked_by_gate", 0),
        "top_suggestions": [
            {
                "mapping_input_id": record.get("mapping_input_id"),
                "label": record.get("label"),
                "row_type": record.get("row_type"),
                "mapping_status": record.get("mapping_status"),
                "top_suggestion": record.get("top_suggestion"),
            }
            for record in top_records
        ],
        "top_blockers": [{"blocker": key, "count": value} for key, value in blocker_counts.most_common(15)],
        "traceability_summary": {
            "mapping_records": len(mapping_records),
            "records_with_mapping_input_id_and_source_candidate_id": traceable,
            "coverage_ratio": 1.0 if not mapping_records else round(traceable / len(mapping_records), 4),
        },
        "mapping_records": mapping_records,
        "limitations": [
            "Deterministic local metadata suggestions only; no final mapping is approved.",
            "No semantic matcher, embeddings, LLM, Azure DI, Hugging Face, OpenAI, DB mutation, XBRL generation, or Arelle validation is used.",
            "Reference report, when provided, is used only as offline concept inventory/gap context and not as a direct answer key.",
        ],
    }


def build_confidence_report(candidates_report: Mapping[str, Any]) -> dict[str, Any]:
    records = list(candidates_report.get("mapping_records") or [])
    by_gate: dict[str, Counter[str]] = defaultdict(Counter)
    by_row_type: dict[str, Counter[str]] = defaultdict(Counter)
    section_counts = Counter()
    for record in records:
        status = str(record.get("mapping_status"))
        by_gate[str(record.get("gate_status") or "unknown")][status] += 1
        by_row_type[str(record.get("row_type") or "unknown")][status] += 1
        top = record.get("top_suggestion") or {}
        evidence = top.get("evidence") or {}
        if top:
            section_counts["section_match" if evidence.get("section_match") else "section_not_matched"] += 1
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "report_type": "azure_di_mapping_confidence",
            "script": "scripts/generate_azure_di_mapping_candidates_13z.py",
        },
        "input_reports": candidates_report.get("input_reports") or {},
        "confidence_tier_counts": candidates_report.get("confidence_tier_counts") or {},
        "status_counts": candidates_report.get("status_counts") or {},
        "auto_mappable_vs_suggest_only_distribution": {key: dict(value) for key, value in sorted(by_gate.items())},
        "requires_confirmation_count": sum(1 for record in records if record.get("requires_confirmation")),
        "ambiguous_multiple_suggestion_count": candidates_report.get("ambiguous_multiple_suggestions_count", 0),
        "no_safe_suggestion_count": candidates_report.get("no_safe_suggestion_count", 0),
        "text_block_mapping_summary": dict(by_row_type.get("text_block", Counter())),
        "numeric_mapping_summary": {
            row_type: dict(by_row_type.get(row_type, Counter()))
            for row_type in sorted(NUMERIC_ROW_TYPES)
        },
        "section_compatibility_summary": dict(section_counts),
        "top_high_confidence_suggestions": [
            record for record in records if record.get("mapping_status") == "high_confidence_suggestion"
        ][:15],
        "top_ambiguous_labels": [
            {
                "mapping_input_id": record.get("mapping_input_id"),
                "label": record.get("label"),
                "suggestions": record.get("suggestions"),
            }
            for record in records
            if record.get("mapping_status") == "ambiguous_multiple_suggestions"
        ][:15],
        "top_no_safe_labels": [
            {
                "mapping_input_id": record.get("mapping_input_id"),
                "label": record.get("label"),
                "row_type": record.get("row_type"),
                "blockers": record.get("blockers"),
            }
            for record in records
            if record.get("mapping_status") == "no_safe_suggestion"
        ][:20],
        "limitations": candidates_report.get("limitations") or [],
    }


def build_gap_analysis_report(
    candidates_report: Mapping[str, Any],
    *,
    concept_metadata_limitations: list[str],
) -> dict[str, Any]:
    records = list(candidates_report.get("mapping_records") or [])
    no_safe = [record for record in records if record.get("mapping_status") == "no_safe_suggestion"]
    weak_statuses = {"low_confidence_suggestion", "no_safe_suggestion", "ambiguous_multiple_suggestions"}
    weak_by_row = Counter(str(record.get("row_type") or "unknown") for record in records if record.get("mapping_status") in weak_statuses)
    weak_by_section = Counter(str(record.get("statement_section") or "missing") for record in records if record.get("mapping_status") in weak_statuses)
    text_gap_count = sum(1 for record in no_safe if record.get("row_type") == "text_block")
    numeric_gap_count = sum(1 for record in no_safe if record.get("row_type") in NUMERIC_ROW_TYPES)
    return {
        "run_metadata": {
            **no_side_effect_metadata(),
            "report_type": "azure_di_mapping_gap_analysis",
            "script": "scripts/generate_azure_di_mapping_candidates_13z.py",
        },
        "input_reports": candidates_report.get("input_reports") or {},
        "labels_with_no_safe_suggestion": [
            {
                "mapping_input_id": record.get("mapping_input_id"),
                "label": record.get("label"),
                "row_type": record.get("row_type"),
                "statement_section": record.get("statement_section"),
                "blockers": record.get("blockers"),
            }
            for record in no_safe
        ],
        "row_types_with_weak_mapping_coverage": dict(weak_by_row),
        "sections_with_weakest_mapping_coverage": [{"section": key, "count": value} for key, value in weak_by_section.most_common(15)],
        "concept_metadata_limitations": concept_metadata_limitations,
        "text_block_concept_gaps": {
            "no_safe_text_block_count": text_gap_count,
            "limitation": "Narrative mapping depends on local text-block concept labels; no LLM or semantic matcher was used.",
        },
        "numeric_concept_gaps": {
            "no_safe_numeric_count": numeric_gap_count,
            "limitation": "Numeric mapping does not infer dimensions, periods, aggregation, or sign policy.",
        },
        "recommended_next_feature": _recommend_next_feature(candidates_report),
        "limitations": candidates_report.get("limitations") or [],
    }


def _recommend_next_feature(candidates_report: Mapping[str, Any]) -> str:
    total = int(candidates_report.get("mapping_record_count") or 0)
    no_safe = int(candidates_report.get("no_safe_suggestion_count") or 0)
    ambiguous = int(candidates_report.get("ambiguous_multiple_suggestions_count") or 0)
    high_medium = int(candidates_report.get("high_confidence_count") or 0) + int(candidates_report.get("medium_confidence_count") or 0)
    if total and high_medium >= total * 0.6 and no_safe <= total * 0.25:
        return "Feature #14A - Azure DI mapping quality evaluation against reference XML, no DB mutation."
    if no_safe + ambiguous > total * 0.4:
        return "Feature #14A - Concept metadata enrichment if no-safe/ambiguous rate is high."
    return "Feature #14A - Text-block concept matching refinement if narrative mapping is weak."


def render_candidates_markdown(report: Mapping[str, Any]) -> str:
    feature = (report.get("run_metadata") or {}).get("feature") or "13Z"
    lines = [
        f"# Azure DI Mapping Candidates - Feature #{feature}",
        "",
        "## Summary",
        "",
        f"- Handoff candidates: {report.get('total_handoff_candidates', 0)}",
        f"- Mapping records: {report.get('mapping_record_count', 0)}",
        f"- High confidence: {report.get('high_confidence_count', 0)}",
        f"- Medium confidence: {report.get('medium_confidence_count', 0)}",
        f"- Low confidence: {report.get('low_confidence_count', 0)}",
        f"- Ambiguous: {report.get('ambiguous_multiple_suggestions_count', 0)}",
        f"- No safe suggestion: {report.get('no_safe_suggestion_count', 0)}",
        f"- Database mutated: {report.get('run_metadata', {}).get('database_mutated')}",
        f"- Semantic matcher called: {report.get('run_metadata', {}).get('semantic_matcher_called')}",
        "",
        "## Status Counts",
        "",
    ]
    lines.extend(f"- {key}: {value}" for key, value in (report.get("status_counts") or {}).items())
    lines.extend(["", "## Top Suggestions", ""])
    top = report.get("top_suggestions") or []
    if top:
        for row in top[:15]:
            suggestion = row.get("top_suggestion") or {}
            lines.append(
                f"- `{row.get('mapping_input_id')}` {row.get('label')}: {suggestion.get('concept_qname')} "
                f"({suggestion.get('score')}) [{row.get('mapping_status')}]"
            )
    else:
        lines.append("- None")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def render_confidence_markdown(report: Mapping[str, Any]) -> str:
    feature = (report.get("run_metadata") or {}).get("feature") or "13Z"
    lines = [
        f"# Azure DI Mapping Confidence - Feature #{feature}",
        "",
        "## Summary",
        "",
        f"- Confidence tiers: {report.get('confidence_tier_counts', {})}",
        f"- Status counts: {report.get('status_counts', {})}",
        f"- Requires confirmation: {report.get('requires_confirmation_count', 0)}",
        f"- Ambiguous multiple suggestions: {report.get('ambiguous_multiple_suggestion_count', 0)}",
        f"- No safe suggestion: {report.get('no_safe_suggestion_count', 0)}",
        "",
        "## Gate Distribution",
        "",
    ]
    for gate, counts in (report.get("auto_mappable_vs_suggest_only_distribution") or {}).items():
        lines.append(f"- {gate}: {counts}")
    lines.extend(["", "## Top No-Safe Labels", ""])
    no_safe = report.get("top_no_safe_labels") or []
    lines.extend(f"- `{row.get('mapping_input_id')}` {row.get('label')} ({row.get('row_type')})" for row in no_safe) if no_safe else lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def render_gap_analysis_markdown(report: Mapping[str, Any]) -> str:
    feature = (report.get("run_metadata") or {}).get("feature") or "13Z"
    lines = [
        f"# Azure DI Mapping Gap Analysis - Feature #{feature}",
        "",
        "## Summary",
        "",
        f"- No-safe labels: {len(report.get('labels_with_no_safe_suggestion', []))}",
        f"- Weak row-type coverage: {report.get('row_types_with_weak_mapping_coverage', {})}",
        f"- Recommended next feature: {report.get('recommended_next_feature')}",
        "",
        "## No-Safe Labels",
        "",
    ]
    rows = report.get("labels_with_no_safe_suggestion") or []
    lines.extend(f"- `{row.get('mapping_input_id')}` {row.get('label')} ({row.get('row_type')})" for row in rows[:30]) if rows else lines.append("- None")
    lines.extend(["", "## Concept Metadata Limitations", ""])
    limits = report.get("concept_metadata_limitations") or []
    lines.extend(f"- {item}" for item in limits) if limits else lines.append("- None")
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run_mapping_candidate_generation(
    *,
    handoff_report_path: str | Path = DEFAULT_HANDOFF_REPORT,
    reference_report_path: str | Path | None = None,
    run_id: str | None = None,
    output_prefix: str | Path | None = None,
    concept_metadata: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    handoff_path = Path(handoff_report_path)
    handoff_report = json.loads(handoff_path.read_text(encoding="utf-8"))
    paths = output_paths_from_prefix(output_prefix)
    if concept_metadata is None:
        concepts, limitations = load_local_concept_metadata(reference_report_path=reference_report_path)
    else:
        concepts, limitations = concept_metadata, []
    input_paths = {
        "handoff_report": str(handoff_path),
        "reference_report": str(reference_report_path) if reference_report_path else None,
    }
    candidates, confidence, gap = generate_mapping_candidate_reports(
        handoff_report=handoff_report,
        concept_metadata=concepts,
        concept_metadata_limitations=limitations,
        input_paths=input_paths,
        run_id=run_id,
    )
    for report, path in [
        (candidates, paths.candidates_json),
        (confidence, paths.confidence_json),
        (gap, paths.gap_json),
    ]:
        metadata = dict(report.get("run_metadata") or {})
        metadata["output_path"] = str(path)
        report["run_metadata"] = metadata
    _write_json(paths.candidates_json, candidates)
    _write_text(paths.candidates_md, render_candidates_markdown(candidates))
    _write_json(paths.confidence_json, confidence)
    _write_text(paths.confidence_md, render_confidence_markdown(confidence))
    _write_json(paths.gap_json, gap)
    _write_text(paths.gap_md, render_gap_analysis_markdown(gap))
    return {
        "paths": paths,
        "candidates_report": candidates,
        "confidence_report": confidence,
        "gap_report": gap,
    }
