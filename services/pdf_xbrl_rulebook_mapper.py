"""Offline advisory PDF-XBRL rulebook mapper for Feature #18D-C."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.golden_mbrs_dataset import discover_golden_cases, load_normalized_extraction_rows
from services.pdf_xbrl_deterministic_alignment import (
    PdfRowValue,
    canonical_label,
    concept_label,
    expected_period_type_for_statement,
    normalize_label,
    pdf_row_values,
)
from services.pdf_statement_template_patterns import match_statement_template_candidate
from services.pdf_statement_row_order_alignment import row_order_candidate_for_context
from services.statement_concept_candidate_dictionary import match_statement_concept_candidate
from services.pdf_xbrl_rulebook_replay import _context_conditions_match
from services.company_format_template_memory import match_company_format_memory_candidate
from services.pdf_note_detail_boundaries import (
    boundary_blocks_qname,
    boundary_summary,
    classify_note_detail_boundary,
)


SUGGESTION_SOURCE = "pdf_xbrl_rulebook"
GENERIC_LABELS = {"amount", "balance", "current", "less", "net", "other", "subtotal", "total"}
OVERBLOCKED_RECOVERY_TARGET_QNAMES = {
    "ifrs-smes:ProfitLoss",
    "ifrs-smes:IncomeTaxExpenseContinuingOperations",
    "ifrs-smes:OtherIncome",
}
PROFIT_LOSS_FINAL_LABELS = {
    "profit for the financial year",
    "loss for the financial year",
    "profit for the year",
    "loss for the year",
    "profit loss for the financial year",
    "profit loss for the year",
    "profit after tax",
    "loss after tax",
    "profit after taxation",
    "loss after taxation",
}
OTHER_INCOME_RECOVERY_LABELS = {"other income", "add other income", "add other income fros"}
TAX_EXPENSE_RECOVERY_LABELS = {"tax expense", "income tax expense", "taxation", "less taxation"}
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _as_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _unique(values: Sequence[Any]) -> list[str]:
    return sorted({str(value) for value in values if value not in (None, "")})


def _is_outlier_case(case: Mapping[str, Any]) -> bool:
    metadata = case.get("metadata") or {}
    text = " ".join(
        str(value or "")
        for value in (
            case.get("case_id"),
            metadata.get("source_case_id"),
            metadata.get("azure_di_case_id"),
            metadata.get("source_case_dir"),
        )
    )
    return "shield" in text.lower()


def _sample_display_name(case: Mapping[str, Any]) -> str:
    metadata = case.get("metadata") or {}
    return str(metadata.get("source_case_id") or metadata.get("azure_di_case_id") or case.get("case_id"))


def _row_default_current_year(rows: Sequence[Mapping[str, Any]]) -> int | None:
    years = []
    for row in rows:
        for key in ("current_year", "prior_year"):
            try:
                if row.get(key) not in (None, ""):
                    years.append(int(row[key]))
            except (TypeError, ValueError):
                continue
    return max(years) if years else None


def _case_selected(
    case: Mapping[str, Any],
    *,
    include_samples: Sequence[str],
    exclude_samples: Sequence[str],
    include_outlier: bool,
) -> tuple[bool, str]:
    case_id = str(case.get("case_id") or "")
    includes = {str(item) for item in include_samples if item}
    excludes = {str(item) for item in exclude_samples if item}
    if includes and case_id not in includes:
        return False, "not_in_include_sample_filter"
    if case_id in excludes:
        return False, "excluded_by_exclude_sample_filter"
    if _is_outlier_case(case) and not include_outlier and case_id not in includes:
        return False, "outlier_excluded_by_default"
    return True, "included"


def load_pdf_row_observations(
    *,
    dataset_dir: str | Path,
    include_samples: Sequence[str] = (),
    exclude_samples: Sequence[str] = (),
    include_outlier: bool = False,
) -> dict[str, Any]:
    """Load cached Azure DI normalized rows and expand them into row-value observations."""
    samples = []
    observations: list[PdfRowValue] = []
    for case in discover_golden_cases(dataset_dir):
        selected, reason = _case_selected(
            case,
            include_samples=include_samples,
            exclude_samples=exclude_samples,
            include_outlier=include_outlier,
        )
        if not selected:
            samples.append(
                {
                    "sample_id": case.get("case_id"),
                    "company_name": _sample_display_name(case),
                    "status": "excluded",
                    "reason": reason,
                    "pdf_rows_found": 0,
                    "pdf_row_values": 0,
                    "normalized_extraction_sources": [],
                }
            )
            continue

        rows, sources = load_normalized_extraction_rows(case)
        current_year = _row_default_current_year(rows)
        sample_values = [
            row_value
            for index, row in enumerate(rows, start=1)
            for row_value in pdf_row_values(
                sample_id=str(case.get("case_id")),
                company_name=_sample_display_name(case),
                row=row,
                fallback_index=index,
                default_current_year=current_year,
            )
        ]
        observations.extend(sample_values)
        samples.append(
            {
                "sample_id": case.get("case_id"),
                "company_name": _sample_display_name(case),
                "status": "included",
                "reason": reason,
                "pdf_rows_found": len(rows),
                "pdf_row_values": len(sample_values),
                "normalized_extraction_sources": sources,
            }
        )
    return {"samples": samples, "row_values": observations}


def _output_readiness(readiness: Any) -> str:
    value = str(readiness or "")
    if value == "downgrade_to_review_required":
        return "downgraded"
    if value == "review_only":
        return "review_required"
    if value in {"exclude", "excluded"}:
        return "excluded"
    if value in {"production_candidate", "advisory_candidate"}:
        return value
    return value or "unknown"


def _rule_status_for_readiness(readiness: Any) -> str:
    value = str(readiness or "")
    if value in {"exclude", "excluded"}:
        return "excluded"
    if value in {"downgrade_to_review_required", "review_only"}:
        return "review_required"
    return "active"


def load_hardened_mapper_rules(hardened_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Convert #18D-B readiness records into mapper rule records."""
    rules = []
    for record in hardened_report.get("rule_readiness") or []:
        rule = dict(record)
        readiness = str(rule.get("readiness") or "")
        pattern = canonical_label(rule.get("normalized_label_pattern"))
        aliases = set(_as_list(rule.get("aliases")))
        aliases.add(pattern)
        aliases.add(normalize_label(pattern))
        rule.update(
            {
                "hardened_readiness": readiness,
                "rule_readiness": _output_readiness(readiness),
                "rule_status": _rule_status_for_readiness(readiness),
                "normalized_label_pattern": pattern,
                "aliases": sorted(alias for alias in aliases if alias),
                "target_concept_label": rule.get("target_concept_label") or concept_label(rule.get("target_qname")),
            }
        )
        rules.append(rule)
    return rules


def _rule_aliases(rule: Mapping[str, Any]) -> set[str]:
    aliases = {canonical_label(rule.get("normalized_label_pattern")), normalize_label(rule.get("normalized_label_pattern"))}
    for alias in rule.get("aliases") or []:
        aliases.add(canonical_label(alias))
        aliases.add(normalize_label(alias))
    return {alias for alias in aliases if alias}


def _label_match_kind(row: PdfRowValue, rule: Mapping[str, Any]) -> str | None:
    row_norm = normalize_label(row.pdf_label)
    row_canon = canonical_label(row.pdf_label)
    aliases = _rule_aliases(rule)
    if row_norm in aliases:
        return "exact_alias_match"
    if row_canon in aliases:
        return "canonical_alias_match"
    return None


def _family_compatible(row: PdfRowValue, rule: Mapping[str, Any]) -> bool:
    rule_family = rule.get("statement_family")
    return not rule_family or not row.pdf_statement_family or str(rule_family) == str(row.pdf_statement_family)


def _period_compatible(row: PdfRowValue, rule: Mapping[str, Any]) -> bool:
    hint = rule.get("period_type_hint")
    expected = expected_period_type_for_statement(row.pdf_statement_family)
    return not hint or not expected or str(hint) == str(expected)


def _rule_rank(rule: Mapping[str, Any]) -> tuple[int, int, int, str]:
    readiness_rank = {
        "production_candidate": 0,
        "advisory_candidate": 1,
        "downgrade_to_review_required": 2,
        "review_only": 3,
        "exclude": 4,
        "excluded": 4,
    }.get(str(rule.get("hardened_readiness") or rule.get("readiness") or ""), 5)
    tier_rank = {"strong": 0, "usable": 1, "weak": 2}.get(str(rule.get("confidence_tier") or ""), 3)
    performance = rule.get("performance") or {}
    return (
        readiness_rank,
        tier_rank,
        -int(performance.get("predictions") or rule.get("observation_count") or 0),
        str(rule.get("rule_id") or ""),
    )


def _rule_competitor(rule: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": rule.get("rule_id"),
        "target_qname": rule.get("target_qname"),
        "predicted_concept_label": rule.get("target_concept_label"),
        "hardened_readiness": rule.get("hardened_readiness"),
        "rule_readiness": rule.get("rule_readiness"),
        "confidence_tier": rule.get("confidence_tier"),
        "statement_family": rule.get("statement_family"),
        "risk_flags": rule.get("risk_flags"),
    }


def _row_generic(row: PdfRowValue) -> bool:
    normalized = normalize_label(row.pdf_label)
    tokens = normalized.split()
    return normalized in GENERIC_LABELS or len(tokens) <= 1 or normalized.startswith("total ") or normalized.startswith("other ")


def _section_context_missing(row: PdfRowValue) -> bool:
    return not row.pdf_statement_family or not row.pdf_statement_type


def _rule_has_conflict(rule: Mapping[str, Any]) -> bool:
    flags = rule.get("risk_flags") or {}
    return bool(
        flags.get("qname_conflict")
        or flags.get("statement_family_conflict")
        or flags.get("zero_only_evidence")
        or flags.get("conflict_reasons")
    )


def _dominant_rule(row: PdfRowValue, rules: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    dominant = [
        rule
        for rule in rules
        if rule.get("rule_status") != "excluded"
        and _label_match_kind(row, rule) == "exact_alias_match"
        and rule.get("statement_family")
        and row.pdf_statement_family
        and str(rule.get("statement_family")) == str(row.pdf_statement_family)
        and not _rule_has_conflict(rule)
    ]
    return sorted(dominant, key=_rule_rank)[0] if len(dominant) == 1 else None


def _false_positive_index(hardened_report: Mapping[str, Any]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in hardened_report.get("false_positive_root_causes") or []:
        key = (
            canonical_label(item.get("normalized_label") or item.get("pdf_label")),
            str(item.get("predicted_qname") or ""),
            str(item.get("pdf_statement_family") or ""),
        )
        index[key].append(dict(item))
    return dict(index)


def _false_positive_risks(
    row: PdfRowValue,
    rule: Mapping[str, Any],
    risk_index: Mapping[tuple[str, str, str], Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    keys = [
        (canonical_label(row.pdf_label), str(rule.get("target_qname") or ""), str(row.pdf_statement_family or "")),
        (canonical_label(rule.get("normalized_label_pattern")), str(rule.get("target_qname") or ""), str(rule.get("statement_family") or "")),
    ]
    risks = []
    seen = set()
    for key in keys:
        for item in risk_index.get(key) or []:
            marker = (item.get("sample_id"), item.get("normalized_label"), item.get("predicted_qname"), item.get("error_type"))
            if marker in seen:
                continue
            seen.add(marker)
            risks.append(
                {
                    "sample_id": item.get("sample_id"),
                    "normalized_label": item.get("normalized_label"),
                    "predicted_qname": item.get("predicted_qname"),
                    "error_type": item.get("error_type"),
                    "recommended_fix": item.get("recommended_fix"),
                }
            )
    return risks


def _base_record(row: PdfRowValue) -> dict[str, Any]:
    return {
        "sample_id": row.sample_id,
        "company_name": row.company_name,
        "pdf_row_id": row.pdf_row_id,
        "pdf_label": row.pdf_label,
        "normalized_label": canonical_label(row.pdf_label),
        "pdf_value": row.pdf_value,
        "pdf_statement_family": row.pdf_statement_family,
        "pdf_statement_type": row.pdf_statement_type,
        "pdf_period": {"value_role": row.value_role, "expected_year": row.expected_year},
        "suggestion_source": SUGGESTION_SOURCE,
        "matched_rule_id": None,
        "hardened_readiness": None,
        "rule_readiness": "no_match",
        "predicted_qname": None,
        "predicted_concept_label": None,
        "confidence_score": 0.0,
        "confidence_bucket": "no_match",
        "requires_human_review": True,
        "safe_for_auto_apply": False,
        "match_reasons": [],
        "blocking_reasons": ["no matching hardened rule"],
        "evidence_summary": {},
        "competing_rules": [],
        "false_positive_risk_notes": [],
    }


def _confidence_score(rule: Mapping[str, Any]) -> float:
    performance = rule.get("performance") or {}
    precision = performance.get("precision_on_evaluable")
    if precision is not None:
        try:
            return round(max(0.0, min(float(precision), 1.0)), 4)
        except (TypeError, ValueError):
            pass
    readiness = str(rule.get("hardened_readiness") or "")
    if readiness == "production_candidate":
        return 0.95
    if readiness == "advisory_candidate":
        return 0.9 if rule.get("confidence_tier") == "strong" else 0.82
    if readiness in {"downgrade_to_review_required", "review_only"}:
        return 0.5
    return 0.0


def _advisory_bucket(rule: Mapping[str, Any]) -> str:
    score = _confidence_score(rule)
    if rule.get("confidence_tier") == "strong" or score >= 0.95:
        return "advisory_high"
    return "advisory_medium"


def _evidence_summary(rule: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "classification_reasons": rule.get("classification_reasons") or [],
        "risk_flags": rule.get("risk_flags") or {},
        "performance": rule.get("performance") or {},
        "sample_support_count": rule.get("sample_support_count"),
        "observation_count": rule.get("observation_count"),
        "required_context_conditions": rule.get("required_context_conditions") or {},
        "blocking_conditions": rule.get("blocking_conditions") or {},
    }


def _matched_rules_for_row(row: PdfRowValue, rules: Sequence[Mapping[str, Any]]) -> tuple[list[Mapping[str, Any]], list[str]]:
    label_matches = [rule for rule in rules if _label_match_kind(row, rule)]
    if not label_matches:
        return [], ["no matching hardened rule"]
    family_matches = [rule for rule in label_matches if _family_compatible(row, rule)]
    if not family_matches:
        return label_matches, ["label matched rule but statement family did not match"]
    period_matches = [rule for rule in family_matches if _period_compatible(row, rule)]
    if not period_matches:
        return family_matches, ["label and statement family matched but period type hint did not match"]
    context_matches = [rule for rule in period_matches if _context_conditions_match(row, rule)]
    if not context_matches:
        return period_matches, ["label, statement family, and period matched but context conditions did not match"]
    return context_matches, []


def map_row_value(
    row: PdfRowValue,
    rules: Sequence[Mapping[str, Any]],
    *,
    false_positive_index: Mapping[tuple[str, str, str], Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Map one PDF row-value observation to advisory deterministic evidence."""
    record = _base_record(row)
    matches, blocking = _matched_rules_for_row(row, rules)
    if blocking:
        record["blocking_reasons"] = blocking
        record["competing_rules"] = [_rule_competitor(rule) for rule in sorted(matches, key=_rule_rank)[:8]]
        return record

    candidate_matches = [rule for rule in matches if rule.get("rule_status") != "excluded"]
    if not candidate_matches:
        record["blocking_reasons"] = ["matched excluded rule only"]
        record["competing_rules"] = [_rule_competitor(rule) for rule in sorted(matches, key=_rule_rank)[:8]]
        return record

    selected: Mapping[str, Any] | None
    if len(matches) > 1:
        selected = _dominant_rule(row, matches)
        if selected is None:
            record.update(
                {
                    "confidence_bucket": "conflict",
                    "rule_readiness": "conflict",
                    "blocking_reasons": ["multiple hardened rules matched without one dominant exact contextual rule"],
                    "competing_rules": [_rule_competitor(rule) for rule in sorted(matches, key=_rule_rank)[:8]],
                }
            )
            return record
    else:
        selected = sorted(candidate_matches, key=_rule_rank)[0]

    risks = _false_positive_risks(row, selected, false_positive_index or {})
    readiness = str(selected.get("hardened_readiness") or selected.get("readiness") or "")
    score = _confidence_score(selected)
    blocking_reasons = []
    match_reasons = [
        _label_match_kind(row, selected) or "label_match",
        "statement_family_match" if row.pdf_statement_family and selected.get("statement_family") else "statement_family_unavailable_or_unconstrained",
        "context_conditions_match",
        f"hardened_readiness:{readiness}",
    ]

    if readiness in {"downgrade_to_review_required", "review_only"}:
        blocking_reasons.append("hardened_rule_requires_review")
    if _row_generic(row):
        blocking_reasons.append("generic_label_requires_review")
    if _section_context_missing(row):
        blocking_reasons.append("missing_section_context")
    if risks:
        blocking_reasons.append("known_false_positive_risk")

    if blocking_reasons:
        bucket = "review_required"
    elif readiness in {"production_candidate", "advisory_candidate"}:
        bucket = _advisory_bucket(selected)
    else:
        bucket = "review_required"

    competing = [rule for rule in sorted(matches, key=_rule_rank) if rule.get("rule_id") != selected.get("rule_id")]
    record.update(
        {
            "matched_rule_id": selected.get("rule_id"),
            "hardened_readiness": readiness,
            "rule_readiness": selected.get("rule_readiness") or _output_readiness(readiness),
            "predicted_qname": selected.get("target_qname"),
            "predicted_concept_label": selected.get("target_concept_label"),
            "confidence_score": score,
            "confidence_bucket": bucket,
            "match_reasons": match_reasons,
            "blocking_reasons": blocking_reasons,
            "evidence_summary": _evidence_summary(selected),
            "competing_rules": [_rule_competitor(rule) for rule in competing[:5]],
            "false_positive_risk_notes": risks,
        }
    )
    record["safe_for_auto_apply"] = False
    record["requires_human_review"] = True
    return record


def map_row_values(
    row_values: Sequence[PdfRowValue],
    rules: Sequence[Mapping[str, Any]],
    *,
    false_positive_index: Mapping[tuple[str, str, str], Sequence[Mapping[str, Any]]] | None = None,
    debug_label: str | None = None,
) -> list[dict[str, Any]]:
    wanted = normalize_label(debug_label) if debug_label else None
    return [
        map_row_value(row, rules, false_positive_index=false_positive_index)
        for row in row_values
        if not wanted or wanted in normalize_label(row.pdf_label)
    ]


def _context_summary(context: Mapping[str, Any] | None) -> dict[str, Any]:
    if not context:
        return {}
    keys = (
        "statement_family",
        "statement_title",
        "section_block",
        "subsection_block",
        "parent_heading",
        "nearest_heading",
        "row_role",
        "is_main_statement",
        "is_notes_context",
        "is_cash_flow",
        "context_confidence",
        "context_reasons",
    )
    return {key: context.get(key) for key in keys}


def _context_confidence(context: Mapping[str, Any]) -> float:
    try:
        return float(context.get("context_confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _context_text(context: Mapping[str, Any], key: str) -> str:
    return normalize_label(context.get(key))


def _contains_any(text: str, phrases: Sequence[str]) -> bool:
    return any(normalize_label(phrase) in text for phrase in phrases)


def _context_rule_id(qname: str, label_slug: str) -> str:
    local = qname.split(":")[-1].lower()
    slug = "-".join(normalize_label(label_slug).split())[:44] or local
    return f"18E-A-context-{slug}-{local}"


def _candidate(
    context: Mapping[str, Any],
    *,
    qname: str,
    reason: str,
    advisory_allowed: bool,
    extra_blocking: Sequence[str] = (),
) -> dict[str, Any]:
    confidence = _context_confidence(context)
    blocking = ["context_optimized_candidate_requires_review"]
    blocking.extend(extra_blocking)
    if confidence < 0.75:
        blocking.append("low_context_confidence_requires_review")
    if not context.get("is_main_statement"):
        blocking.append("non_main_statement_context_requires_review")
    if context.get("is_notes_context"):
        blocking.append("notes_context_requires_review")
    if not advisory_allowed:
        blocking.append("context_rule_not_advisory_safe")
    bucket = "review_required"
    score = round(min(0.92, max(0.45, confidence)), 4)
    if bucket == "review_required":
        score = min(score, 0.65)
    return {
        "matched_rule_id": _context_rule_id(qname, str(context.get("normalized_label") or context.get("original_label") or "")),
        "target_qname": qname,
        "target_concept_label": concept_label(qname),
        "confidence_score": score,
        "confidence_bucket": bucket,
        "match_reasons": [reason, "context_optimized_rulebook_match"],
        "blocking_reasons": _unique(blocking),
    }


def _context_candidate_for_row(context: Mapping[str, Any]) -> dict[str, Any] | None:
    original = _context_text(context, "original_label")
    canonical = _context_text(context, "normalized_label")
    family = str(context.get("statement_family") or "")
    block = str(context.get("section_block") or "")
    row_role = str(context.get("row_role") or "")
    is_total = bool(context.get("is_total"))
    is_subtotal = bool(context.get("is_subtotal"))
    is_main = bool(context.get("is_main_statement"))
    is_notes = bool(context.get("is_notes_context"))

    if family == "cash_flow":
        return None

    if family == "income_statement":
        if _contains_any(original, ("before tax", "before taxation")):
            return _candidate(
                context,
                qname="ifrs-smes:ProfitLossBeforeTax",
                reason="profit_loss_before_tax_income_statement_context",
                advisory_allowed=is_main and (is_total or is_subtotal or row_role == "component"),
            )
        if _contains_any(original, ("tax expense", "tax expenses", "less : taxation", "less taxation")) or canonical == "tax expense":
            return _candidate(
                context,
                qname="ifrs-smes:IncomeTaxExpenseContinuingOperations",
                reason="tax_expense_income_statement_context",
                advisory_allowed=is_main and block == "tax_expense",
            )
        if "cost of sales" not in original and (_contains_any(original, ("turnover", "revenue", "sales")) or canonical == "revenue"):
            return _candidate(
                context,
                qname="ifrs-smes:Revenue",
                reason="revenue_income_statement_context",
                advisory_allowed=is_main and block == "revenue",
            )
        if _contains_any(original, ("other income", "rental received")) or canonical == "other income":
            return _candidate(
                context,
                qname="ifrs-smes:OtherIncome",
                reason="other_income_income_statement_context",
                advisory_allowed=is_main and block == "other_income",
            )
        if _contains_any(original, ("administrative expenses", "administration expenses", "admin expenses")):
            return _candidate(
                context,
                qname="ifrs-smes:AdministrativeExpense",
                reason="administrative_expense_income_statement_context",
                advisory_allowed=is_main and block == "administrative_expenses",
            )
        if _contains_any(original, ("finance costs", "term loan interests", "interest expense")):
            return _candidate(
                context,
                qname="ifrs-smes:FinanceCosts",
                reason="finance_cost_income_statement_context",
                advisory_allowed=is_main and block == "finance_costs",
            )
        if _contains_any(original, ("loss for the financial year", "profit for the financial year", "loss for the year", "profit for the year")):
            return _candidate(
                context,
                qname="ifrs-smes:ProfitLoss",
                reason="profit_loss_income_statement_context",
                advisory_allowed=is_main,
            )

    if family in {"financial_position", ""} or is_notes:
        if "depreciation" not in original and "adjustment" not in original and "decrease" not in original and _contains_any(original, ("property plant and equipment", "property, plant and equipment")):
            return _candidate(
                context,
                qname="ifrs-smes:PropertyPlantAndEquipment",
                reason="ppe_non_current_asset_context",
                advisory_allowed=is_main and family == "financial_position" and block == "non_current_assets",
            )
        if _contains_any(original, ("bank balances", "cash at bank", "cash and cash equivalents")):
            return _candidate(
                context,
                qname="ssmt:CashAndBankBalances",
                reason="cash_current_asset_context",
                advisory_allowed=is_main and family == "financial_position" and block == "current_assets",
            )
        if "increase" not in original and "decrease" not in original and _contains_any(original, ("trade receivables", "other receivables", "trade and other receivables")):
            return _candidate(
                context,
                qname="ifrs-smes:TradeAndOtherCurrentReceivables",
                reason="receivables_current_asset_context",
                advisory_allowed=is_main and family == "financial_position" and block == "current_assets",
            )
        if "increase" not in original and "decrease" not in original and _contains_any(original, ("trade payables", "other payables", "payables and accruals", "trade and other payables")):
            return _candidate(
                context,
                qname="ifrs-smes:TradeAndOtherCurrentPayables",
                reason="payables_current_liability_context",
                advisory_allowed=is_main and family == "financial_position" and block == "current_liabilities",
            )
        if _contains_any(original, ("total non-current assets", "total non current assets")):
            return _candidate(
                context,
                qname="ifrs-smes:NoncurrentAssets",
                reason="total_non_current_assets_context",
                advisory_allowed=is_main and is_total and family == "financial_position" and block == "non_current_assets",
                extra_blocking=[] if is_total else ["total_semantics_required"],
            )
        if "total current assets" in original:
            return _candidate(
                context,
                qname="ifrs-smes:CurrentAssets",
                reason="total_current_assets_context",
                advisory_allowed=is_main and is_total and family == "financial_position" and block == "current_assets",
                extra_blocking=[] if is_total else ["total_semantics_required"],
            )
        if _contains_any(original, ("total non-current liabilities", "total non current liabilities")):
            return _candidate(
                context,
                qname="ifrs-smes:NoncurrentLiabilities",
                reason="total_non_current_liabilities_context",
                advisory_allowed=is_main and is_total and family == "financial_position" and block == "non_current_liabilities",
                extra_blocking=[] if is_total else ["total_semantics_required"],
            )
        if "total current liabilities" in original:
            return _candidate(
                context,
                qname="ifrs-smes:CurrentLiabilities",
                reason="total_current_liabilities_context",
                advisory_allowed=is_main and is_total and family == "financial_position" and block == "current_liabilities",
                extra_blocking=[] if is_total else ["total_semantics_required"],
            )
        if "total equity and liabilities" in original:
            return _candidate(
                context,
                qname="ifrs-smes:EquityAndLiabilities",
                reason="total_equity_and_liabilities_context",
                advisory_allowed=is_main and is_total and family == "financial_position" and block == "equity_and_liabilities",
                extra_blocking=[] if is_total else ["total_semantics_required"],
            )
        if _contains_any(original, ("total shareholders equity", "total shareholders' equity", "total equity")):
            return _candidate(
                context,
                qname="ifrs-smes:Equity",
                reason="total_equity_context",
                advisory_allowed=is_main and is_total and family == "financial_position" and block == "equity",
                extra_blocking=[] if is_total else ["total_semantics_required"],
            )
        if original == "total assets":
            return _candidate(
                context,
                qname="ifrs-smes:Assets",
                reason="total_assets_context",
                advisory_allowed=is_main and is_total and family == "financial_position",
                extra_blocking=[] if is_total else ["total_semantics_required"],
            )
        if original == "total liabilities":
            return _candidate(
                context,
                qname="ifrs-smes:Liabilities",
                reason="total_liabilities_context",
                advisory_allowed=is_main and is_total and family == "financial_position",
                extra_blocking=[] if is_total else ["total_semantics_required"],
            )

    return None


def apply_context_optimized_mapping(record: Mapping[str, Any], context: Mapping[str, Any] | None) -> dict[str, Any]:
    """Apply #18E-A offline-only context optimization to an existing mapper record."""
    optimized = dict(record)
    optimized["row_context"] = _context_summary(context)
    optimized["context_optimization_applied"] = False
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True
    if not context:
        return optimized

    if optimized.get("predicted_qname"):
        if optimized.get("confidence_bucket") in {"advisory_high", "advisory_medium"} and _context_confidence(context) < 0.6:
            optimized["confidence_bucket"] = "review_required"
            optimized["blocking_reasons"] = _unique([*(optimized.get("blocking_reasons") or []), "low_context_confidence_requires_review"])
            optimized["confidence_score"] = min(float(optimized.get("confidence_score") or 0.0), 0.65)
            optimized["context_optimization_applied"] = True
        return optimized

    candidate = _context_candidate_for_row(context)
    if not candidate:
        return optimized

    evidence = dict(optimized.get("evidence_summary") or {})
    evidence["context_optimization"] = _context_summary(context)
    optimized.update(
        {
            "matched_rule_id": candidate["matched_rule_id"],
            "hardened_readiness": "context_optimized",
            "rule_readiness": "context_optimized_review" if candidate["confidence_bucket"] == "review_required" else "context_optimized_advisory",
            "predicted_qname": candidate["target_qname"],
            "predicted_concept_label": candidate["target_concept_label"],
            "confidence_score": candidate["confidence_score"],
            "confidence_bucket": candidate["confidence_bucket"],
            "match_reasons": candidate["match_reasons"],
            "blocking_reasons": candidate["blocking_reasons"],
            "evidence_summary": evidence,
            "context_optimization_applied": True,
        }
    )
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True
    return optimized


def map_row_values_with_context(
    row_values: Sequence[PdfRowValue],
    rules: Sequence[Mapping[str, Any]],
    row_contexts: Sequence[Mapping[str, Any]],
    *,
    false_positive_index: Mapping[tuple[str, str, str], Sequence[Mapping[str, Any]]] | None = None,
    debug_label: str | None = None,
) -> list[dict[str, Any]]:
    context_by_row = {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in row_contexts}
    wanted = normalize_label(debug_label) if debug_label else None
    records = []
    for row in row_values:
        if wanted and wanted not in normalize_label(row.pdf_label):
            continue
        base = map_row_value(row, rules, false_positive_index=false_positive_index)
        context = context_by_row.get((row.sample_id, row.pdf_row_id))
        records.append(apply_context_optimized_mapping(base, context))
    return records


def _note_link_summary(note_link: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not note_link:
        return None
    keys = (
        "note_number",
        "note_title",
        "note_page",
        "note_section_label",
        "note_link_confidence",
        "note_link_reasons",
    )
    return {key: note_link.get(key) for key in keys}


def apply_statement_template_mapping(
    record: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    statement_patterns: Sequence[Mapping[str, Any]],
    *,
    note_link: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply #18E-B offline-only statement-template expansion to a mapper record."""
    optimized = dict(record)
    optimized.setdefault("row_context", _context_summary(context))
    optimized["note_link"] = _note_link_summary(note_link)
    optimized["statement_template_optimization_applied"] = False
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True
    if not context:
        return optimized

    candidate = match_statement_template_candidate(context, statement_patterns, note_link=note_link)
    if optimized.get("predicted_qname"):
        if candidate and candidate.get("target_qname") != optimized.get("predicted_qname"):
            optimized["confidence_bucket"] = "review_required"
            optimized["confidence_score"] = min(float(optimized.get("confidence_score") or 0.0), 0.65)
            optimized["blocking_reasons"] = _unique(
                [
                    *(optimized.get("blocking_reasons") or []),
                    "template_candidate_conflicts_with_existing_prediction",
                    "statement_template_candidate_requires_review",
                ]
            )
            optimized["template_conflict_candidate"] = {
                "matched_template_pattern_id": candidate.get("matched_template_pattern_id"),
                "target_qname": candidate.get("target_qname"),
                "target_concept_label": candidate.get("target_concept_label"),
                "match_reasons": candidate.get("match_reasons") or [],
            }
            optimized["statement_template_optimization_applied"] = True
        return optimized
    if not candidate:
        return optimized

    evidence = dict(optimized.get("evidence_summary") or {})
    evidence["statement_template_expansion"] = {
        "row_context": _context_summary(context),
        "note_link": _note_link_summary(note_link),
        "template_pattern": candidate.get("template_pattern"),
    }
    optimized.update(
        {
            "matched_rule_id": candidate["matched_rule_id"],
            "matched_template_pattern_id": candidate["matched_template_pattern_id"],
            "candidate_source": candidate.get("candidate_source"),
            "hardened_readiness": "statement_template_expansion",
            "rule_readiness": "statement_template_review",
            "predicted_qname": candidate["target_qname"],
            "predicted_concept_label": candidate["target_concept_label"],
            "confidence_score": candidate["confidence_score"],
            "confidence_bucket": "review_required",
            "match_reasons": candidate["match_reasons"],
            "blocking_reasons": candidate["blocking_reasons"],
            "evidence_summary": evidence,
            "statement_template_optimization_applied": True,
        }
    )
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True
    return optimized


def map_row_values_with_statement_templates(
    row_values: Sequence[PdfRowValue],
    rules: Sequence[Mapping[str, Any]],
    row_contexts: Sequence[Mapping[str, Any]],
    statement_patterns: Sequence[Mapping[str, Any]],
    note_links: Sequence[Mapping[str, Any]] = (),
    *,
    false_positive_index: Mapping[tuple[str, str, str], Sequence[Mapping[str, Any]]] | None = None,
    debug_label: str | None = None,
) -> list[dict[str, Any]]:
    context_by_row = {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in row_contexts}
    note_by_row = {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in note_links}
    wanted = normalize_label(debug_label) if debug_label else None
    records = []
    for row in row_values:
        if wanted and wanted not in normalize_label(row.pdf_label):
            continue
        base = map_row_value(row, rules, false_positive_index=false_positive_index)
        context = context_by_row.get((row.sample_id, row.pdf_row_id))
        context_record = apply_context_optimized_mapping(base, context)
        records.append(
            apply_statement_template_mapping(
                context_record,
                context,
                statement_patterns,
                note_link=note_by_row.get((row.sample_id, row.pdf_row_id)),
            )
        )
    return records


def _candidate_target(candidate: Mapping[str, Any] | None) -> str | None:
    if not candidate:
        return None
    if candidate.get("candidate_blocked"):
        return None
    value = candidate.get("target_qname")
    return str(value) if value else None


def _candidate_payload(candidate: Mapping[str, Any] | None, *, kind: str) -> dict[str, Any] | None:
    if not candidate:
        return None
    return {
        f"{kind}_id": candidate.get(f"{kind}_entry_id") or candidate.get(f"{kind}_alignment_id"),
        "target_qname": candidate.get("target_qname"),
        "target_concept_label": candidate.get("target_concept_label"),
        "concept_family": candidate.get("concept_family"),
        "confidence_score": candidate.get("confidence_score"),
        "candidate_blocked": bool(candidate.get("candidate_blocked")),
        "match_reasons": candidate.get("match_reasons") or [],
        "blocking_reasons": candidate.get("blocking_reasons") or [],
    }


def _record_row_context(record: Mapping[str, Any]) -> Mapping[str, Any]:
    context = record.get("row_context")
    return context if isinstance(context, Mapping) else {}


def _blocked_recovery_candidates(record: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    candidates: list[tuple[str, Mapping[str, Any]]] = []
    for source, field in (("dictionary", "blocked_dictionary_candidate"), ("row_order", "blocked_row_order_candidate")):
        candidate = record.get(field)
        if isinstance(candidate, Mapping) and candidate.get("target_qname"):
            candidates.append((source, candidate))
    return candidates


def overblocked_recovery_key(
    record: Mapping[str, Any],
    candidate: Mapping[str, Any],
    source: str,
) -> tuple[str, str, str, str]:
    return (
        str(record.get("sample_id") or ""),
        str(record.get("pdf_row_id") or record.get("row_id") or ""),
        str(candidate.get("target_qname") or ""),
        str(source or ""),
    )


def _candidate_identifier(candidate: Mapping[str, Any], source: str) -> Any:
    return candidate.get(f"{source}_id") or candidate.get("dictionary_id") or candidate.get("row_order_id")


def _evidence_condition(condition: bool, passed: list[str], failed: list[str], name: str) -> None:
    (passed if condition else failed).append(name)


def _context_is_main_income_statement(context: Mapping[str, Any]) -> bool:
    return (
        str(context.get("statement_family") or "") == "income_statement"
        and bool(context.get("is_main_statement"))
        and not bool(context.get("is_notes_context"))
        and not bool(context.get("is_cash_flow"))
    )


def _context_confidence_value(context: Mapping[str, Any]) -> float:
    try:
        return float(context.get("context_confidence") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _record_label_text(record: Mapping[str, Any]) -> str:
    return normalize_label(record.get("pdf_label") or record.get("normalized_label") or "")


def _candidate_text(candidate: Mapping[str, Any], context: Mapping[str, Any]) -> str:
    values = [
        *(candidate.get("match_reasons") or []),
        *(candidate.get("blocking_reasons") or []),
        *(context.get("context_reasons") or []),
        context.get("previous_label"),
        context.get("next_label"),
        context.get("nearest_heading"),
        context.get("parent_heading"),
    ]
    return normalize_label(" ".join(str(value or "") for value in values))


def _has_note_link_confirmation(record: Mapping[str, Any]) -> bool:
    note_link = record.get("note_link")
    if not isinstance(note_link, Mapping):
        return False
    try:
        confidence = float(note_link.get("note_link_confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return confidence >= 0.8


def _profit_loss_recovery_conditions(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[bool, list[str], list[str]]:
    context = _record_row_context(record)
    label = _record_label_text(record)
    passed: list[str] = []
    failed: list[str] = []
    row_role = str(context.get("row_role") or "")

    _evidence_condition(_context_is_main_income_statement(context), passed, failed, "main_income_statement_context")
    _evidence_condition(str(context.get("section_block") or "") == "profit_loss", passed, failed, "profit_loss_section")
    _evidence_condition(row_role in {"total", "subtotal"} or bool(context.get("is_total")) or bool(context.get("is_subtotal")), passed, failed, "final_result_row_role")
    _evidence_condition(any(phrase in label for phrase in PROFIT_LOSS_FINAL_LABELS), passed, failed, "final_profit_loss_label")
    _evidence_condition("comprehensive" not in label, passed, failed, "not_comprehensive_income_line")
    _evidence_condition("operating activities" not in label and "cash flow" not in label, passed, failed, "not_cash_flow_operating_profit")
    _evidence_condition("retained" not in label and "accumulated" not in label and "balance" not in label, passed, failed, "not_retained_earnings_movement")
    _evidence_condition(_context_confidence_value(context) >= 0.85, passed, failed, "high_context_confidence")
    _evidence_condition(str(candidate.get("target_qname") or "") == "ifrs-smes:ProfitLoss", passed, failed, "profit_loss_target_qname")
    return not failed, passed, failed


def _tax_expense_recovery_conditions(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[bool, list[str], list[str]]:
    context = _record_row_context(record)
    label = _record_label_text(record)
    text = _candidate_text(candidate, context)
    passed: list[str] = []
    failed: list[str] = []
    forbidden = ("payable", "recoverable", "refundable", "deferred", "asset", "liability")
    before_after_profit_label = ("profit" in label or "loss" in label) and "tax expense" not in label and "income tax expense" not in label
    row_order_mentions_before_tax = "previous label profit before tax" in text or "previous label loss before tax" in text or "before taxation" in text
    row_order_available = "previous label" in text or "next label" in text

    _evidence_condition(_context_is_main_income_statement(context), passed, failed, "main_income_statement_context")
    _evidence_condition(str(context.get("section_block") or "") == "tax_expense", passed, failed, "tax_expense_section")
    _evidence_condition(any(term in label for term in TAX_EXPENSE_RECOVERY_LABELS), passed, failed, "tax_expense_label")
    _evidence_condition(not any(term in label for term in forbidden), passed, failed, "not_balance_sheet_tax_asset_or_liability")
    _evidence_condition(not before_after_profit_label, passed, failed, "not_profit_or_loss_before_after_tax_label")
    _evidence_condition(not bool(context.get("is_notes_context")) and str(context.get("row_role") or "") != "note_detail", passed, failed, "not_note_detail_tax")
    _evidence_condition(not row_order_available or row_order_mentions_before_tax, passed, failed, "row_order_after_profit_before_tax_if_available")
    _evidence_condition(_context_confidence_value(context) >= 0.85, passed, failed, "high_context_confidence")
    _evidence_condition(
        str(candidate.get("target_qname") or "") == "ifrs-smes:IncomeTaxExpenseContinuingOperations",
        passed,
        failed,
        "income_tax_expense_target_qname",
    )
    return not failed, passed, failed


def _other_income_recovery_conditions(record: Mapping[str, Any], candidate: Mapping[str, Any]) -> tuple[bool, list[str], list[str]]:
    context = _record_row_context(record)
    label = _record_label_text(record)
    passed: list[str] = []
    failed: list[str] = []
    forbidden = ("revenue", "turnover", "sales", "finance income", "interest income")
    near_exact = label in OTHER_INCOME_RECOVERY_LABELS or label.startswith("add other income") or label == "other income"

    _evidence_condition(_context_is_main_income_statement(context), passed, failed, "main_income_statement_context")
    _evidence_condition(str(context.get("section_block") or "") == "other_income", passed, failed, "other_income_section")
    _evidence_condition(near_exact, passed, failed, "exact_or_near_exact_other_income_label")
    _evidence_condition(not any(term in label for term in forbidden), passed, failed, "not_revenue_or_finance_income")
    _evidence_condition("note" not in str(context.get("section_block") or "") and not bool(context.get("is_notes_context")), passed, failed, "not_note_detail_breakdown")
    _evidence_condition(not any(term in label for term in ("subtotal", "total", "profit", "loss", "comprehensive")), passed, failed, "not_subtotal_or_profit_loss_component")
    _evidence_condition(_context_confidence_value(context) >= 0.85, passed, failed, "high_context_confidence")
    _evidence_condition(str(candidate.get("target_qname") or "") == "ifrs-smes:OtherIncome", passed, failed, "other_income_target_qname")
    return not failed, passed, failed


def overblocked_recovery_decision(
    record: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    source: str,
    allowed_recovery_keys: set[tuple[str, str, str, str]] | None = None,
) -> dict[str, Any]:
    target_qname = str(candidate.get("target_qname") or "")
    key = overblocked_recovery_key(record, candidate, source)
    previous_reasons = list(candidate.get("blocking_reasons") or record.get("blocked_candidate_reasons") or [])
    base = {
        "candidate_key": {
            "sample_id": key[0],
            "pdf_row_id": key[1],
            "target_qname": key[2],
            "blocked_source": key[3],
        },
        "blocked_source": source,
        "candidate_id": _candidate_identifier(candidate, source),
        "target_qname": target_qname,
        "target_concept_label": candidate.get("target_concept_label"),
        "previous_blocking_reason": previous_reasons,
        "safe_for_auto_apply": False,
        "requires_human_review": True,
    }
    if allowed_recovery_keys is not None and key not in allowed_recovery_keys:
        return {
            **base,
            "classification": "not_recoverable",
            "can_recover": False,
            "risk_level": "medium",
            "recovery_reason": "candidate_not_in_18e_d_overblocked_true_positive_set",
            "evidence_conditions_met": [],
            "evidence_conditions_failed": ["18e_d_overblocked_true_positive_whitelist"],
        }
    if target_qname not in OVERBLOCKED_RECOVERY_TARGET_QNAMES:
        return {
            **base,
            "classification": "not_recoverable",
            "can_recover": False,
            "risk_level": "medium",
            "recovery_reason": "target_family_not_in_low_risk_recovery_scope",
            "evidence_conditions_met": [],
            "evidence_conditions_failed": ["allowed_recovery_target_family"],
        }

    existing_qname = str(record.get("predicted_qname") or "")
    if existing_qname and existing_qname != target_qname:
        return {
            **base,
            "classification": "still_blocked_high_risk",
            "can_recover": False,
            "risk_level": "high",
            "recovery_reason": "blocked_candidate_conflicts_with_existing_prediction",
            "evidence_conditions_met": [],
            "evidence_conditions_failed": ["no_existing_prediction_conflict"],
        }

    if target_qname == "ifrs-smes:ProfitLoss":
        can_recover, passed, failed = _profit_loss_recovery_conditions(record, candidate)
        reason = "profit_loss_final_result_recovery" if can_recover else "profit_loss_recovery_conditions_not_met"
    elif target_qname == "ifrs-smes:IncomeTaxExpenseContinuingOperations":
        can_recover, passed, failed = _tax_expense_recovery_conditions(record, candidate)
        reason = "income_tax_expense_main_statement_recovery" if can_recover else "income_tax_expense_recovery_conditions_not_met"
    else:
        can_recover, passed, failed = _other_income_recovery_conditions(record, candidate)
        reason = "other_income_exact_main_statement_recovery" if can_recover else "other_income_recovery_conditions_not_met"

    return {
        **base,
        "classification": "recovered_low_risk" if can_recover else "still_blocked_high_risk",
        "can_recover": can_recover,
        "risk_level": "low" if can_recover else "high",
        "recovery_reason": reason,
        "evidence_conditions_met": passed,
        "evidence_conditions_failed": failed,
    }


def apply_overblocked_candidate_recovery(
    record: Mapping[str, Any],
    *,
    allowed_recovery_keys: set[tuple[str, str, str, str]] | None = None,
) -> dict[str, Any]:
    """Apply #18E-D-hotfix-1 opt-in low-risk blocked-candidate recovery."""
    optimized = dict(record)
    decisions = [
        overblocked_recovery_decision(
            optimized,
            candidate,
            source=source,
            allowed_recovery_keys=allowed_recovery_keys,
        )
        for source, candidate in _blocked_recovery_candidates(optimized)
    ]
    if not decisions:
        optimized["overblocked_recovery_applied"] = False
        optimized["safe_for_auto_apply"] = False
        optimized["requires_human_review"] = True
        return optimized

    recovered = [decision for decision in decisions if decision.get("can_recover")]
    optimized["overblocked_recovery_decisions"] = decisions
    optimized["overblocked_recovery_applied"] = bool(recovered)
    if not recovered:
        optimized["safe_for_auto_apply"] = False
        optimized["requires_human_review"] = True
        return optimized

    chosen = recovered[0]
    existing_qname = optimized.get("predicted_qname")
    recovery_reasons = _unique([decision.get("recovery_reason") for decision in recovered])
    evidence = dict(optimized.get("evidence_summary") or {})
    evidence["overblocked_recovery"] = {
        "feature": "18E-D-hotfix-1",
        "recovered_candidates": recovered,
        "recovery_scope": "review_required_only",
        "safe_for_auto_apply": False,
    }
    if not existing_qname:
        optimized.update(
            {
                "matched_rule_id": f"18E-D-hotfix-1-{chosen.get('blocked_source')}-{chosen.get('candidate_id')}",
                "candidate_source": "overblocked_recovery",
                "hardened_readiness": "overblocked_recovery",
                "rule_readiness": "overblocked_recovery_review",
                "predicted_qname": chosen.get("target_qname"),
                "predicted_concept_label": chosen.get("target_concept_label"),
                "confidence_score": min(float(optimized.get("confidence_score") or 0.64), 0.64),
                "confidence_bucket": "review_required",
                "candidate_generation_method": "overblocked_recovery",
            }
        )
    optimized["match_reasons"] = _unique([*(optimized.get("match_reasons") or []), *recovery_reasons, "overblocked_low_risk_recovery"])
    optimized["blocking_reasons"] = _unique(
        [*(optimized.get("blocking_reasons") or []), "overblocked_recovery_requires_human_review"]
    )
    optimized["evidence_summary"] = evidence
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True
    return optimized


def _blocked_prediction_payload(record: Mapping[str, Any], *, reasons: Sequence[str]) -> dict[str, Any]:
    return {
        "matched_rule_id": record.get("matched_rule_id"),
        "target_qname": record.get("predicted_qname"),
        "target_concept_label": record.get("predicted_concept_label"),
        "confidence_score": record.get("confidence_score"),
        "confidence_bucket": record.get("confidence_bucket"),
        "candidate_generation_method": record.get("candidate_generation_method")
        or record.get("candidate_source")
        or record.get("suggestion_source"),
        "match_reasons": record.get("match_reasons") or [],
        "blocking_reasons": list(reasons),
    }


def apply_note_detail_boundary(
    record: Mapping[str, Any],
    boundary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply #18E-B-3 note-detail boundary blocks to one mapper record."""
    optimized = dict(record)
    note_boundary = dict(boundary or classify_note_detail_boundary(optimized))
    optimized["note_boundary"] = boundary_summary(note_boundary)
    optimized["note_boundary_optimization_applied"] = False
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True

    qname = optimized.get("predicted_qname")
    blocked, reasons = boundary_blocks_qname(note_boundary, qname)
    if not blocked:
        return optimized

    existing = _blocked_prediction_payload(optimized, reasons=reasons)
    evidence = dict(optimized.get("evidence_summary") or {})
    evidence["note_detail_boundary"] = {
        "feature": "18E-B-3",
        "boundary": boundary_summary(note_boundary),
        "blocked_candidate": existing,
        "safe_for_auto_apply": False,
    }
    optimized.update(
        {
            "matched_rule_id": None,
            "hardened_readiness": None,
            "rule_readiness": "no_match",
            "predicted_qname": None,
            "predicted_concept_label": None,
            "confidence_score": 0.0,
            "confidence_bucket": "no_match",
            "match_reasons": [],
            "blocking_reasons": _unique([*(optimized.get("blocking_reasons") or []), *reasons, "note_boundary_blocks_candidate"]),
            "blocked_note_boundary_candidate": existing,
            "candidate_generation_method": "note_boundary_block",
            "evidence_summary": evidence,
            "note_boundary_optimization_applied": True,
        }
    )
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True
    return optimized


def _format_memory_candidate_payload(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "memory_entry_id": candidate.get("memory_entry_id"),
        "target_qname": candidate.get("target_qname"),
        "target_concept_label": candidate.get("target_concept_label"),
        "confidence_score": candidate.get("confidence_score"),
        "candidate_blocked": bool(candidate.get("candidate_blocked")),
        "match_reasons": candidate.get("match_reasons") or [],
        "blocking_reasons": candidate.get("blocking_reasons") or [],
        "format_memory_entry": candidate.get("format_memory_entry") or {},
    }


def apply_company_format_memory_mapping(
    record: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    memory_entries: Sequence[Mapping[str, Any]],
    *,
    note_boundary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply #18E-B-3 company-format memory as review-only evidence."""
    optimized = dict(record)
    optimized.setdefault("row_context", _context_summary(context))
    if note_boundary is not None:
        optimized["note_boundary"] = boundary_summary(note_boundary)
    optimized["company_format_memory_applied"] = False
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True
    if not context:
        return optimized

    candidate_context = dict(context)
    candidate_context.setdefault("original_label", record.get("pdf_label"))
    candidate_context.setdefault("normalized_label", record.get("normalized_label"))
    candidate_context.setdefault("pdf_label", record.get("pdf_label"))
    candidate = match_company_format_memory_candidate(candidate_context, memory_entries, note_boundary=note_boundary)
    if not candidate:
        return optimized

    existing_qname = optimized.get("predicted_qname")
    if existing_qname:
        if existing_qname == candidate.get("target_qname"):
            optimized["match_reasons"] = _unique(
                [*(optimized.get("match_reasons") or []), "format_memory_agrees_with_existing_prediction"]
            )
            optimized["company_format_memory_applied"] = True
        else:
            optimized["confidence_bucket"] = "review_required"
            optimized["confidence_score"] = min(float(optimized.get("confidence_score") or 0.0), 0.65)
            optimized["format_memory_conflict_candidate"] = _format_memory_candidate_payload(candidate)
            optimized["blocking_reasons"] = _unique(
                [
                    *(optimized.get("blocking_reasons") or []),
                    "format_memory_candidate_conflicts_with_existing_prediction",
                    "format_memory_candidate_requires_review",
                ]
            )
            optimized["company_format_memory_applied"] = True
        optimized["safe_for_auto_apply"] = False
        optimized["requires_human_review"] = True
        return optimized

    if candidate.get("candidate_blocked"):
        optimized["blocked_format_memory_candidate"] = _format_memory_candidate_payload(candidate)
        optimized["blocking_reasons"] = _unique(
            [*(optimized.get("blocking_reasons") or []), *(candidate.get("blocking_reasons") or [])]
        )
        optimized["company_format_memory_applied"] = True
        optimized["safe_for_auto_apply"] = False
        optimized["requires_human_review"] = True
        return optimized

    evidence = dict(optimized.get("evidence_summary") or {})
    evidence["company_format_template_memory"] = {
        "feature": "18E-B-3",
        "candidate": _format_memory_candidate_payload(candidate),
        "safe_for_auto_apply": False,
    }
    optimized.update(
        {
            "matched_rule_id": candidate.get("matched_rule_id"),
            "memory_entry_id": candidate.get("memory_entry_id"),
            "candidate_source": "company_format_template_memory",
            "hardened_readiness": "company_format_template_memory",
            "rule_readiness": "format_memory_review",
            "predicted_qname": candidate.get("target_qname"),
            "predicted_concept_label": candidate.get("target_concept_label"),
            "confidence_score": candidate.get("confidence_score"),
            "confidence_bucket": "review_required",
            "match_reasons": candidate.get("match_reasons") or [],
            "blocking_reasons": _unique(candidate.get("blocking_reasons") or ["format_memory_candidate_requires_review"]),
            "evidence_summary": evidence,
            "candidate_generation_method": "company_format_template_memory",
            "company_format_memory_applied": True,
        }
    )
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True
    return optimized


def apply_dictionary_row_order_mapping(
    record: Mapping[str, Any],
    context: Mapping[str, Any] | None,
    dictionary_entries: Sequence[Mapping[str, Any]],
    *,
    row_order_alignment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply #18E-B-2 offline-only dictionary and row-order candidate evidence."""
    optimized = dict(record)
    optimized.setdefault("row_context", _context_summary(context))
    optimized.setdefault("dictionary_entry_id", None)
    optimized.setdefault("dictionary_match_reasons", [])
    optimized.setdefault("row_order_alignment_id", None)
    optimized.setdefault("row_order_reasons", [])
    optimized.setdefault("candidate_generation_method", optimized.get("candidate_source") or optimized.get("suggestion_source"))
    optimized.setdefault("context_dictionary_agreement", "not_evaluated")
    optimized.setdefault("template_dictionary_agreement", "not_evaluated")
    optimized.setdefault("ambiguity_reasons", [])
    optimized["dictionary_row_order_optimization_applied"] = False
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True
    if not context:
        return optimized

    dictionary_candidate = match_statement_concept_candidate(context, dictionary_entries)
    row_candidate = row_order_candidate_for_context(context, row_order_alignment)
    dictionary_qname = _candidate_target(dictionary_candidate)
    row_qname = _candidate_target(row_candidate)
    existing_qname = optimized.get("predicted_qname")

    if dictionary_candidate:
        optimized["dictionary_entry_id"] = dictionary_candidate.get("dictionary_entry_id")
        optimized["dictionary_match_reasons"] = dictionary_candidate.get("match_reasons") or []
        optimized["dictionary_candidate"] = _candidate_payload(dictionary_candidate, kind="dictionary")
        if dictionary_candidate.get("candidate_blocked"):
            optimized["blocked_dictionary_candidate"] = _candidate_payload(dictionary_candidate, kind="dictionary")
    if row_candidate:
        optimized["row_order_alignment_id"] = row_candidate.get("row_order_alignment_id")
        optimized["row_order_reasons"] = row_candidate.get("match_reasons") or []
        optimized["row_order_candidate"] = _candidate_payload(row_candidate, kind="row_order")
        if row_candidate.get("candidate_blocked"):
            optimized["blocked_row_order_candidate"] = _candidate_payload(row_candidate, kind="row_order")

    blocked_reasons = _unique(
        [
            *(dictionary_candidate.get("blocking_reasons") or [] if dictionary_candidate and dictionary_candidate.get("candidate_blocked") else []),
            *(row_candidate.get("blocking_reasons") or [] if row_candidate and row_candidate.get("candidate_blocked") else []),
        ]
    )
    if blocked_reasons:
        optimized["blocked_candidate_reasons"] = blocked_reasons
        optimized["blocking_reasons"] = _unique([*(optimized.get("blocking_reasons") or []), *blocked_reasons])

    if dictionary_qname and row_qname:
        optimized["context_dictionary_agreement"] = "dictionary_row_order_agree" if dictionary_qname == row_qname else "dictionary_row_order_conflict"
    elif dictionary_qname:
        optimized["context_dictionary_agreement"] = "dictionary_only"
    elif row_qname:
        optimized["context_dictionary_agreement"] = "row_order_only"

    if optimized.get("matched_template_pattern_id") and dictionary_qname:
        optimized["template_dictionary_agreement"] = (
            "template_dictionary_agree"
            if dictionary_qname == existing_qname
            else "template_dictionary_conflict"
        )

    if existing_qname:
        conflicts = []
        if dictionary_qname and dictionary_qname != existing_qname:
            conflicts.append("dictionary_candidate_conflicts_with_existing_prediction")
            optimized["dictionary_conflict_candidate"] = _candidate_payload(dictionary_candidate, kind="dictionary")
        if row_qname and row_qname != existing_qname:
            conflicts.append("row_order_candidate_conflicts_with_existing_prediction")
            optimized["row_order_conflict_candidate"] = _candidate_payload(row_candidate, kind="row_order")
        if conflicts:
            optimized["confidence_bucket"] = "review_required"
            optimized["confidence_score"] = min(float(optimized.get("confidence_score") or 0.0), 0.65)
            optimized["blocking_reasons"] = _unique([*(optimized.get("blocking_reasons") or []), *conflicts, "dictionary_row_order_candidate_requires_review"])
            optimized["ambiguity_reasons"] = _unique([*(optimized.get("ambiguity_reasons") or []), *conflicts])
            optimized["dictionary_row_order_optimization_applied"] = True
        elif dictionary_qname or row_qname:
            optimized["match_reasons"] = _unique(
                [
                    *(optimized.get("match_reasons") or []),
                    *(["dictionary_agrees_with_existing_prediction"] if dictionary_qname == existing_qname else []),
                    *(["row_order_agrees_with_existing_prediction"] if row_qname == existing_qname else []),
                ]
            )
            optimized["dictionary_row_order_optimization_applied"] = True
        optimized["safe_for_auto_apply"] = False
        optimized["requires_human_review"] = True
        return optimized

    chosen = None
    method = None
    ambiguity = []
    if dictionary_qname and row_qname and dictionary_qname == row_qname:
        chosen = dictionary_candidate
        method = "dictionary_row_order_agreement"
    elif dictionary_qname and row_qname and dictionary_qname != row_qname:
        chosen = dictionary_candidate
        method = "dictionary_row_order_conflict"
        ambiguity.append("dictionary_row_order_conflict_requires_review")
    elif dictionary_qname:
        chosen = dictionary_candidate
        method = "statement_concept_dictionary"
    elif row_qname:
        chosen = row_candidate
        method = "row_order_alignment"
        if _context_text(context, "normalized_label") in GENERIC_LABELS:
            ambiguity.append("generic_label_row_order_only")

    if not chosen:
        return optimized

    blocking = _unique([*(chosen.get("blocking_reasons") or []), "dictionary_row_order_candidate_requires_review", *ambiguity])
    match_reasons = _unique([*(chosen.get("match_reasons") or []), method])
    evidence = dict(optimized.get("evidence_summary") or {})
    evidence["dictionary_row_order_expansion"] = {
        "dictionary_candidate": _candidate_payload(dictionary_candidate, kind="dictionary"),
        "row_order_candidate": _candidate_payload(row_candidate, kind="row_order"),
        "candidate_generation_method": method,
        "ambiguity_reasons": ambiguity,
    }
    optimized.update(
        {
            "matched_rule_id": chosen.get("matched_rule_id"),
            "candidate_source": "dictionary_row_order",
            "hardened_readiness": "dictionary_row_order_expansion",
            "rule_readiness": "dictionary_row_order_review",
            "predicted_qname": chosen.get("target_qname"),
            "predicted_concept_label": chosen.get("target_concept_label"),
            "confidence_score": min(float(chosen.get("confidence_score") or 0.0), 0.66),
            "confidence_bucket": "review_required",
            "match_reasons": match_reasons,
            "blocking_reasons": blocking,
            "evidence_summary": evidence,
            "candidate_generation_method": method,
            "ambiguity_reasons": _unique([*(optimized.get("ambiguity_reasons") or []), *ambiguity]),
            "dictionary_row_order_optimization_applied": True,
        }
    )
    optimized["safe_for_auto_apply"] = False
    optimized["requires_human_review"] = True
    return optimized


def map_row_values_with_dictionary_row_order(
    row_values: Sequence[PdfRowValue],
    rules: Sequence[Mapping[str, Any]],
    row_contexts: Sequence[Mapping[str, Any]],
    statement_patterns: Sequence[Mapping[str, Any]],
    dictionary_entries: Sequence[Mapping[str, Any]],
    row_order_alignments: Sequence[Mapping[str, Any]],
    note_links: Sequence[Mapping[str, Any]] = (),
    *,
    false_positive_index: Mapping[tuple[str, str, str], Sequence[Mapping[str, Any]]] | None = None,
    debug_label: str | None = None,
) -> list[dict[str, Any]]:
    context_by_row = {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in row_contexts}
    note_by_row = {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in note_links}
    alignment_by_row = {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in row_order_alignments}
    wanted = normalize_label(debug_label) if debug_label else None
    records = []
    for row in row_values:
        if wanted and wanted not in normalize_label(row.pdf_label):
            continue
        key = (row.sample_id, row.pdf_row_id)
        context = context_by_row.get(key)
        base = map_row_value(row, rules, false_positive_index=false_positive_index)
        context_record = apply_context_optimized_mapping(base, context)
        template_record = apply_statement_template_mapping(
            context_record,
            context,
            statement_patterns,
            note_link=note_by_row.get(key),
        )
        records.append(
            apply_dictionary_row_order_mapping(
                template_record,
                context,
                dictionary_entries,
                row_order_alignment=alignment_by_row.get(key),
            )
        )
    return records


def map_row_values_with_format_memory(
    row_values: Sequence[PdfRowValue],
    rules: Sequence[Mapping[str, Any]],
    row_contexts: Sequence[Mapping[str, Any]],
    statement_patterns: Sequence[Mapping[str, Any]],
    dictionary_entries: Sequence[Mapping[str, Any]],
    row_order_alignments: Sequence[Mapping[str, Any]],
    memory_entries: Sequence[Mapping[str, Any]],
    note_links: Sequence[Mapping[str, Any]] = (),
    note_boundaries: Sequence[Mapping[str, Any]] = (),
    *,
    false_positive_index: Mapping[tuple[str, str, str], Sequence[Mapping[str, Any]]] | None = None,
    allowed_recovery_keys: set[tuple[str, str, str, str]] | None = None,
    debug_label: str | None = None,
) -> list[dict[str, Any]]:
    """Apply the #18E-B-3 offline candidate priority order."""
    context_by_row = {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in row_contexts}
    note_by_row = {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in note_links}
    alignment_by_row = {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in row_order_alignments}
    boundary_by_row = {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in note_boundaries}
    wanted = normalize_label(debug_label) if debug_label else None
    records = []
    for row in row_values:
        if wanted and wanted not in normalize_label(row.pdf_label):
            continue
        key = (row.sample_id, row.pdf_row_id)
        context = context_by_row.get(key)
        boundary = boundary_by_row.get(key) or classify_note_detail_boundary(context or _base_record(row))
        base = map_row_value(row, rules, false_positive_index=false_positive_index)
        context_record = apply_context_optimized_mapping(base, context)
        template_record = apply_statement_template_mapping(
            context_record,
            context,
            statement_patterns,
            note_link=note_by_row.get(key),
        )
        recovered_record = apply_overblocked_candidate_recovery(
            template_record,
            allowed_recovery_keys=allowed_recovery_keys,
        )
        boundary_record = apply_note_detail_boundary(recovered_record, boundary)
        memory_record = apply_company_format_memory_mapping(
            boundary_record,
            context,
            memory_entries,
            note_boundary=boundary,
        )
        boundary_memory_record = apply_note_detail_boundary(memory_record, boundary)
        dictionary_record = apply_dictionary_row_order_mapping(
            boundary_memory_record,
            context,
            dictionary_entries,
            row_order_alignment=alignment_by_row.get(key),
        )
        records.append(apply_note_detail_boundary(dictionary_record, boundary))
    return records


def _count_bucket(records: Sequence[Mapping[str, Any]], bucket: str) -> int:
    return sum(1 for item in records if item.get("confidence_bucket") == bucket)


def _advisory_suggestions(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in records if item.get("confidence_bucket") in {"advisory_high", "advisory_medium"}]


def _review_required_suggestions(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in records if item.get("confidence_bucket") == "review_required" and item.get("predicted_qname")]


def _conflicts(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in records if item.get("confidence_bucket") == "conflict"]


def _no_matches(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in records if item.get("confidence_bucket") == "no_match"]


def _top_records(records: Sequence[Mapping[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    ordered = sorted(
        records,
        key=lambda item: (-float(item.get("confidence_score") or 0), str(item.get("sample_id")), str(item.get("pdf_row_id"))),
    )
    return [
        {
            "sample_id": item.get("sample_id"),
            "pdf_row_id": item.get("pdf_row_id"),
            "pdf_label": item.get("pdf_label"),
            "pdf_value": item.get("pdf_value"),
            "confidence_bucket": item.get("confidence_bucket"),
            "matched_rule_id": item.get("matched_rule_id"),
            "rule_readiness": item.get("rule_readiness"),
            "predicted_qname": item.get("predicted_qname"),
            "confidence_score": item.get("confidence_score"),
            "blocking_reasons": item.get("blocking_reasons"),
        }
        for item in ordered[:limit]
    ]


def _top_no_match_labels(records: Sequence[Mapping[str, Any]], *, limit: int = 30) -> list[dict[str, Any]]:
    counter = Counter(str(item.get("normalized_label") or normalize_label(item.get("pdf_label"))) for item in records)
    return [{"normalized_label": label, "count": count} for label, count in counter.most_common(limit) if label]


def _per_sample_summary(records: Sequence[Mapping[str, Any]], samples: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    by_sample: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in records:
        by_sample[str(item.get("sample_id"))].append(item)
    output = []
    for sample in samples:
        sample_id = str(sample.get("sample_id"))
        items = by_sample.get(sample_id, [])
        output.append(
            {
                "sample_id": sample.get("sample_id"),
                "company_name": sample.get("company_name"),
                "status": sample.get("status"),
                "reason": sample.get("reason"),
                "pdf_rows_found": sample.get("pdf_rows_found", 0),
                "pdf_row_value_observations": len(items),
                "advisory_suggestions": len(_advisory_suggestions(items)),
                "review_required_suggestions": len(_review_required_suggestions(items)),
                "conflicts": len(_conflicts(items)),
                "no_match": len(_no_matches(items)),
            }
        )
    return output


def _per_rule_usage(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in records:
        if item.get("matched_rule_id"):
            grouped[str(item["matched_rule_id"])].append(item)
    output = []
    for rule_id, items in grouped.items():
        output.append(
            {
                "rule_id": rule_id,
                "predicted_qname": items[0].get("predicted_qname"),
                "rule_readiness": items[0].get("rule_readiness"),
                "total_suggestions": len(items),
                "advisory_suggestions": len(_advisory_suggestions(items)),
                "review_required_suggestions": len(_review_required_suggestions(items)),
                "matched_labels": _top_no_match_labels(items, limit=10),
            }
        )
    return sorted(output, key=lambda item: (-int(item["total_suggestions"]), str(item["rule_id"])))


def _recommend_next(summary: Mapping[str, Any]) -> dict[str, Any]:
    advisory = int(summary.get("advisory_suggestions_count") or 0)
    review = int(summary.get("review_required_suggestions_count") or 0)
    conflicts = int(summary.get("conflicts_count") or 0)
    safe_auto_apply = int(summary.get("safe_for_auto_apply_count") or 0)
    justified = advisory > 0 and safe_auto_apply == 0
    return {
        "feature_18d_d_backend_api_advisory_integration_justified": justified,
        "recommended_next_feature": (
            "Feature #18D-D - Backend/API integration of deterministic rulebook suggestions as advisory-only evidence, behind feature flag, no auto-apply."
            if justified
            else "Keep #18D-C offline and improve rule coverage/context before backend/API advisory integration."
        ),
        "basis": {
            "advisory_suggestions_count": advisory,
            "review_required_suggestions_count": review,
            "conflicts_count": conflicts,
            "safe_for_auto_apply_count": safe_auto_apply,
            "no_suggestion_safe_for_auto_apply": safe_auto_apply == 0,
        },
    }


def summarize_mapper_records(
    records: Sequence[Mapping[str, Any]],
    *,
    samples: Sequence[Mapping[str, Any]],
    rules: Sequence[Mapping[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    advisory = _advisory_suggestions(records)
    review = _review_required_suggestions(records)
    conflicts = _conflicts(records)
    no_match = _no_matches(records)
    bucket_counts = Counter(str(item.get("confidence_bucket") or "unknown") for item in records)
    readiness_counts = Counter(str(item.get("rule_readiness") or "unknown") for item in records)
    summary = {
        "feature": "18D-C",
        "generated_at": generated_at,
        "total_pdf_row_value_observations": len(records),
        "hardened_rules_loaded": len(rules),
        "advisory_suggestions_count": len(advisory),
        "review_required_suggestions_count": len(review),
        "conflicts_count": len(conflicts),
        "no_match_count": len(no_match),
        "safe_for_auto_apply_count": sum(1 for item in records if item.get("safe_for_auto_apply")),
        "requires_human_review_count": sum(1 for item in records if item.get("requires_human_review")),
        "no_suggestion_safe_for_auto_apply": all(not item.get("safe_for_auto_apply") for item in records),
        "confidence_bucket_counts": dict(sorted(bucket_counts.items())),
        "rule_readiness_counts": dict(sorted(readiness_counts.items())),
        "per_sample_summary": _per_sample_summary(records, samples),
        "per_rule_usage": _per_rule_usage(records),
        "top_advisory_suggestions": _top_records(advisory, limit=20),
        "top_review_required_suggestions": _top_records(review, limit=20),
        "top_conflicts": _top_records(conflicts, limit=20),
        "top_no_match_labels": _top_no_match_labels(no_match, limit=30),
        "explicit_auto_apply_statement": "No #18D-C suggestion is safe for auto-apply; human review remains required.",
        "safety": SAFETY,
    }
    summary["recommendation"] = _recommend_next(summary)
    return summary


def build_mapper_reports(
    *,
    dataset_dir: str | Path,
    hardened_rulebook: Mapping[str, Any],
    include_samples: Sequence[str] = (),
    exclude_samples: Sequence[str] = (),
    include_outlier: bool = False,
    debug_label: str | None = None,
    sample_data_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    generated_at = _utc_now()
    rules = load_hardened_mapper_rules(hardened_rulebook)
    risk_index = _false_positive_index(hardened_rulebook)
    if sample_data_by_id is None:
        loaded = load_pdf_row_observations(
            dataset_dir=dataset_dir,
            include_samples=include_samples,
            exclude_samples=exclude_samples,
            include_outlier=include_outlier,
        )
        samples = loaded["samples"]
        row_values = loaded["row_values"]
    else:
        samples = []
        row_values = []
        for sample_id, data in sorted(sample_data_by_id.items()):
            values = list(data.get("row_values") or [])
            samples.append(
                {
                    "sample_id": sample_id,
                    "company_name": data.get("company_name") or sample_id,
                    "status": "included",
                    "reason": "test_sample_data",
                    "pdf_rows_found": data.get("pdf_rows_found", len(values)),
                    "pdf_row_values": len(values),
                    "normalized_extraction_sources": [],
                }
            )
            row_values.extend(values)

    records = map_row_values(row_values, rules, false_positive_index=risk_index, debug_label=debug_label)
    summary = summarize_mapper_records(records, samples=samples, rules=rules, generated_at=generated_at)
    run_metadata = {
        "feature": "18D-C",
        "generated_at": generated_at,
        "read_only": True,
        "offline_only": True,
        "dataset_dir": str(dataset_dir),
        "include_samples": list(include_samples),
        "exclude_samples": list(exclude_samples),
        "include_outlier": include_outlier,
        "debug_label": debug_label,
        **SAFETY,
    }
    suggestions_report = {
        "run_metadata": run_metadata,
        "summary": summary,
        "suggestions": records,
    }
    summary_report = {
        "run_metadata": run_metadata,
        "summary": summary,
    }
    conflicts = _conflicts(records)
    conflicts_report = {
        "run_metadata": run_metadata,
        "summary": {
            "conflicts_count": len(conflicts),
            "top_conflicts": summary["top_conflicts"],
            "safety": SAFETY,
        },
        "conflicts": conflicts,
    }
    no_match = _no_matches(records)
    no_match_report = {
        "run_metadata": run_metadata,
        "summary": {
            "no_match_count": len(no_match),
            "top_no_match_labels": summary["top_no_match_labels"],
            "safety": SAFETY,
        },
        "no_match": no_match,
    }
    return {
        "suggestions": suggestions_report,
        "summary": summary_report,
        "conflicts": conflicts_report,
        "no_match": no_match_report,
    }


def render_suggestions_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF-XBRL Rulebook Mapper Suggestions - Feature #18D-C",
        "",
        f"- Total PDF row-value observations: {summary.get('total_pdf_row_value_observations', 0)}",
        f"- Advisory suggestions: {summary.get('advisory_suggestions_count', 0)}",
        f"- Review-required suggestions: {summary.get('review_required_suggestions_count', 0)}",
        f"- Conflicts: {summary.get('conflicts_count', 0)}",
        f"- No-match: {summary.get('no_match_count', 0)}",
        f"- Safe for auto-apply: {summary.get('safe_for_auto_apply_count', 0)}",
        "",
        "## Top Advisory Suggestions",
        "",
        "| Sample | Label | Value | QName | Bucket | Rule |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for item in summary.get("top_advisory_suggestions") or []:
        lines.append(
            f"| {item.get('sample_id')} | {item.get('pdf_label')} | {item.get('pdf_value')} | "
            f"{item.get('predicted_qname')} | {item.get('confidence_bucket')} | {item.get('matched_rule_id')} |"
        )
    lines.extend(["", "## Auto-Apply Boundary", "", f"- {summary.get('explicit_auto_apply_statement')}", ""])
    return "\n".join(lines)


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    recommendation = summary.get("recommendation") or {}
    lines = [
        "# PDF-XBRL Rulebook Mapper Summary - Feature #18D-C",
        "",
        "## Metrics",
        "",
    ]
    for key in (
        "total_pdf_row_value_observations",
        "hardened_rules_loaded",
        "advisory_suggestions_count",
        "review_required_suggestions_count",
        "conflicts_count",
        "no_match_count",
        "safe_for_auto_apply_count",
    ):
        lines.append(f"- {key}: {summary.get(key, 0)}")
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"- #18D-D justified: {recommendation.get('feature_18d_d_backend_api_advisory_integration_justified')}",
            f"- Next: {recommendation.get('recommended_next_feature')}",
            "",
            "## Per Sample",
            "",
            "| Sample | Observations | Advisory | Review-required | Conflicts | No-match |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in summary.get("per_sample_summary") or []:
        if item.get("status") != "included":
            continue
        lines.append(
            f"| {item.get('sample_id')} | {item.get('pdf_row_value_observations')} | "
            f"{item.get('advisory_suggestions')} | {item.get('review_required_suggestions')} | "
            f"{item.get('conflicts')} | {item.get('no_match')} |"
        )
    lines.extend(["", "## Safety", ""])
    for key, value in (summary.get("safety") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def render_conflicts_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF-XBRL Rulebook Mapper Conflicts - Feature #18D-C",
        "",
        f"- Conflicts: {summary.get('conflicts_count', 0)}",
        "",
        "| Sample | Label | Value | Reason |",
        "| --- | --- | ---: | --- |",
    ]
    for item in summary.get("top_conflicts") or []:
        lines.append(
            f"| {item.get('sample_id')} | {item.get('pdf_label')} | {item.get('pdf_value')} | "
            f"{', '.join(item.get('blocking_reasons') or [])} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_no_match_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF-XBRL Rulebook Mapper No-Match Rows - Feature #18D-C",
        "",
        f"- No-match rows: {summary.get('no_match_count', 0)}",
        "",
        "| Normalized label | Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("top_no_match_labels") or []:
        lines.append(f"| {item.get('normalized_label')} | {item.get('count')} |")
    lines.append("")
    return "\n".join(lines)


def write_mapper_reports(
    *,
    dataset_dir: str | Path,
    hardened_rulebook_path: str | Path,
    output_dir: str | Path,
    include_samples: Sequence[str] = (),
    exclude_samples: Sequence[str] = (),
    include_outlier: bool = False,
    debug_label: str | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = build_mapper_reports(
        dataset_dir=dataset_dir,
        hardened_rulebook=_read_json(hardened_rulebook_path),
        include_samples=include_samples,
        exclude_samples=exclude_samples,
        include_outlier=include_outlier,
        debug_label=debug_label,
    )
    paths = {
        "suggestions_json": output / "pdf_xbrl_rulebook_mapper_suggestions_18d_c.json",
        "suggestions_md": output / "pdf_xbrl_rulebook_mapper_suggestions_18d_c.md",
        "summary_json": output / "pdf_xbrl_rulebook_mapper_summary_18d_c.json",
        "summary_md": output / "pdf_xbrl_rulebook_mapper_summary_18d_c.md",
        "conflicts_json": output / "pdf_xbrl_rulebook_mapper_conflicts_18d_c.json",
        "conflicts_md": output / "pdf_xbrl_rulebook_mapper_conflicts_18d_c.md",
        "no_match_json": output / "pdf_xbrl_rulebook_mapper_no_match_18d_c.json",
        "no_match_md": output / "pdf_xbrl_rulebook_mapper_no_match_18d_c.md",
    }
    _write_json(paths["suggestions_json"], reports["suggestions"])
    _write_json(paths["summary_json"], reports["summary"])
    _write_json(paths["conflicts_json"], reports["conflicts"])
    _write_json(paths["no_match_json"], reports["no_match"])
    paths["suggestions_md"].write_text(render_suggestions_markdown(reports["suggestions"]), encoding="utf-8")
    paths["summary_md"].write_text(render_summary_markdown(reports["summary"]), encoding="utf-8")
    paths["conflicts_md"].write_text(render_conflicts_markdown(reports["conflicts"]), encoding="utf-8")
    paths["no_match_md"].write_text(render_no_match_markdown(reports["no_match"]), encoding="utf-8")
    return {"paths": paths, **reports}
