"""Offline PDF-XBRL rulebook replay and holdout evaluation for Feature #18C."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from services.golden_mbrs_dataset import discover_golden_cases, load_normalized_extraction_rows
from services.pdf_xbrl_deterministic_alignment import (
    PdfRowValue,
    canonical_label,
    concept_label,
    expected_period_type_for_statement,
    fact_period_type,
    fact_period_year,
    is_alignable_xbrl_fact,
    normalize_label,
    normalize_numeric_value,
    pdf_row_values,
)
from services.pdf_xbrl_mapping_rulebook import build_rulebook_entries
from services.reference_xbrl_parser import parse_reference_xbrl


GOOD_STATUSES = {"exact_qname_value_period_match", "qname_value_match_period_uncertain"}
FALSE_POSITIVE_STATUSES = {
    "qname_exists_but_value_mismatch",
    "value_exists_but_different_qname",
    "predicted_qname_not_found_in_xbrl",
}
NOT_EVALUABLE_STATUSES = {"ambiguous_xbrl_support", "no_xbrl_support", "not_evaluable"}
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


def _unique(values: Sequence[Any]) -> list[str]:
    return sorted({str(value) for value in values if value not in (None, "")})


def _sample_ids_from_alignment_report(alignment_report: Mapping[str, Any]) -> list[str]:
    discovery = alignment_report.get("discovery") or {}
    samples = discovery.get("included_samples") or []
    if samples:
        return [str(sample.get("sample_id")) for sample in samples if sample.get("sample_id")]
    return sorted({str(item.get("sample_id")) for item in alignment_report.get("alignments") or [] if item.get("sample_id")})


def _company_by_sample(alignment_report: Mapping[str, Any]) -> dict[str, str]:
    output = {}
    for sample in (alignment_report.get("discovery") or {}).get("samples") or []:
        if sample.get("sample_id"):
            output[str(sample["sample_id"])] = str(sample.get("company_name") or sample["sample_id"])
    for item in alignment_report.get("alignments") or []:
        if item.get("sample_id") and item.get("company_name"):
            output.setdefault(str(item["sample_id"]), str(item["company_name"]))
    return output


def _sample_current_year(facts: Sequence[Mapping[str, Any]]) -> int | None:
    years = [fact_period_year(fact) for fact in facts if fact_period_year(fact) is not None]
    return max(years) if years else None


def _case_index(dataset_dir: str | Path) -> dict[str, Mapping[str, Any]]:
    return {str(case.get("case_id")): case for case in discover_golden_cases(dataset_dir)}


def load_sample_replay_data(
    *,
    dataset_dir: str | Path,
    sample_id: str,
    company_name: str | None = None,
) -> dict[str, Any]:
    """Load local cached row-value observations and local XBRL facts for one sample."""
    cases = _case_index(dataset_dir)
    if sample_id not in cases:
        raise KeyError(f"Unknown sample_id: {sample_id}")
    case = cases[sample_id]
    rows, row_sources = load_normalized_extraction_rows(case)
    reference = parse_reference_xbrl(sample_id, case["reference_path"], "xml")
    facts = reference.get("facts") or []
    numeric_facts = [fact for fact in facts if is_alignable_xbrl_fact(fact)]
    current_year = _sample_current_year(numeric_facts)
    display_name = company_name or str((case.get("metadata") or {}).get("source_case_id") or sample_id)
    row_values = [
        row_value
        for index, row in enumerate(rows, start=1)
        for row_value in pdf_row_values(
            sample_id=sample_id,
            company_name=display_name,
            row=row,
            fallback_index=index,
            default_current_year=current_year,
        )
    ]
    return {
        "sample_id": sample_id,
        "company_name": display_name,
        "row_values": row_values,
        "facts": numeric_facts,
        "pdf_rows_found": len(rows),
        "pdf_row_values": len(row_values),
        "xbrl_numeric_facts": len(numeric_facts),
        "row_sources": row_sources,
    }


def _rule_aliases(rule: Mapping[str, Any]) -> set[str]:
    aliases = {str(rule.get("normalized_label_pattern") or "")}
    aliases.update(str(alias) for alias in rule.get("aliases") or [] if alias)
    aliases.update(canonical_label(alias) for alias in list(aliases))
    aliases.update(normalize_label(alias) for alias in list(aliases))
    return {alias for alias in aliases if alias}


def _label_matches_rule(row: PdfRowValue, rule: Mapping[str, Any]) -> bool:
    aliases = _rule_aliases(rule)
    row_norm = normalize_label(row.pdf_label)
    row_canon = canonical_label(row.pdf_label)
    return row_norm in aliases or row_canon in aliases


def _family_compatible(row: PdfRowValue, rule: Mapping[str, Any]) -> bool:
    rule_family = rule.get("statement_family")
    return not rule_family or not row.pdf_statement_family or str(rule_family) == str(row.pdf_statement_family)


def _period_compatible(row: PdfRowValue, rule: Mapping[str, Any]) -> bool:
    hint = rule.get("period_type_hint")
    expected = expected_period_type_for_statement(row.pdf_statement_family)
    return not hint or not expected or str(hint) == str(expected)


def _as_text_set(value: Any) -> set[str]:
    if value in (None, ""):
        return set()
    if isinstance(value, str):
        return {normalize_label(value)}
    if isinstance(value, (list, tuple, set, frozenset)):
        return {normalize_label(item) for item in value if normalize_label(item)}
    return {normalize_label(value)}


def _total_semantics(label: Any) -> bool:
    normalized = normalize_label(label)
    tokens = set(normalized.split())
    return bool({"total", "subtotal"} & tokens) or normalized.startswith("net ")


def _value_is_zero(row: PdfRowValue) -> bool:
    return row.numeric_value is not None and row.numeric_value == 0


def _text_contains_any(text: str, values: set[str]) -> bool:
    return not values or any(value in text for value in values)


def _text_contains_all(text: str, values: set[str]) -> bool:
    return all(value in text for value in values)


def _context_conditions_match(row: PdfRowValue, rule: Mapping[str, Any]) -> bool:
    required = rule.get("required_context_conditions") or {}
    blocking = rule.get("blocking_conditions") or {}
    if not required and not blocking:
        return True

    label = normalize_label(row.pdf_label)
    canonical = canonical_label(row.pdf_label)
    statement_type = normalize_label(row.pdf_statement_type)
    family = row.pdf_statement_family
    expected_period = expected_period_type_for_statement(family)

    family_in = {str(item) for item in required.get("statement_family_in") or []}
    if required.get("statement_family"):
        family_in.add(str(required["statement_family"]))
    if family_in and str(family) not in family_in:
        return False

    if required.get("period_type") and expected_period and str(required["period_type"]) != expected_period:
        return False

    row_types = {str(item) for item in required.get("row_type_in") or []}
    if row_types and str(row.row_type) not in row_types:
        return False

    value_roles = {str(item) for item in required.get("value_role_in") or []}
    if value_roles and str(row.value_role) not in value_roles:
        return False

    exact_labels = _as_text_set(required.get("label_exact_any"))
    if exact_labels and label not in exact_labels and canonical not in exact_labels:
        return False

    if not _text_contains_any(label, _as_text_set(required.get("label_contains_any"))):
        return False
    if not _text_contains_all(label, _as_text_set(required.get("label_contains_all"))):
        return False
    if not _text_contains_any(statement_type, _as_text_set(required.get("statement_type_contains_any"))):
        return False
    if not _text_contains_all(statement_type, _as_text_set(required.get("statement_type_contains_all"))):
        return False

    if required.get("requires_total_semantics") and not _total_semantics(row.pdf_label):
        return False
    if required.get("requires_nonzero_value") and _value_is_zero(row):
        return False

    blocked_labels = _as_text_set(blocking.get("label_contains_any"))
    if blocked_labels and _text_contains_any(label, blocked_labels):
        return False
    blocked_statement_types = _as_text_set(blocking.get("statement_type_contains_any"))
    if blocked_statement_types and _text_contains_any(statement_type, blocked_statement_types):
        return False
    blocked_families = {str(item) for item in blocking.get("statement_family_in") or []}
    if blocked_families and str(family) in blocked_families:
        return False
    if blocking.get("zero_value") and _value_is_zero(row):
        return False

    return True


def _rule_rank(rule: Mapping[str, Any]) -> tuple[int, int, int, str]:
    status = str(rule.get("rule_status") or "")
    tier = str(rule.get("confidence_tier") or "")
    status_rank = {"active": 0, "review_required": 1}.get(status, 2)
    tier_rank = {"strong": 0, "usable": 1, "weak": 2}.get(tier, 3)
    return (
        status_rank,
        tier_rank,
        -int(rule.get("observation_count") or 0),
        str(rule.get("rule_id") or ""),
    )


def _prediction_base(row: PdfRowValue) -> dict[str, Any]:
    return {
        "sample_id": row.sample_id,
        "company_name": row.company_name,
        "pdf_row_id": row.pdf_row_id,
        "pdf_label": row.pdf_label,
        "normalized_label": canonical_label(row.pdf_label),
        "pdf_value": row.pdf_value,
        "pdf_period": {"value_role": row.value_role, "expected_year": row.expected_year},
        "pdf_statement_family": row.pdf_statement_family,
        "pdf_statement_type": row.pdf_statement_type,
        "matched_rule_id": None,
        "rule_confidence_tier": None,
        "predicted_qname": None,
        "predicted_concept_label": None,
        "replay_confidence": "no_rule_match",
        "replay_reason": "no matching active or review-required rule",
        "evaluation_status": "not_evaluable",
        "xbrl_support_status": "not_evaluable",
        "matched_xbrl_fact_id": None,
        "matched_xbrl_value": None,
        "matched_xbrl_context": None,
        "error_reason": None,
        "competing_rules": [],
    }


def replay_row_value(row: PdfRowValue, rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    base = _prediction_base(row)
    usable_rules = [rule for rule in rules if rule.get("rule_status") in {"active", "review_required"}]
    label_matches = [rule for rule in usable_rules if _label_matches_rule(row, rule)]
    if not label_matches:
        return base

    family_matches = [rule for rule in label_matches if _family_compatible(row, rule)]
    if not family_matches:
        base["replay_reason"] = "label matched rule but statement family did not match"
        base["competing_rules"] = [_rule_competitor(rule) for rule in sorted(label_matches, key=_rule_rank)[:5]]
        return base

    period_matches = [rule for rule in family_matches if _period_compatible(row, rule)]
    if not period_matches:
        base["replay_reason"] = "label and statement family matched but period type hint did not match"
        base["competing_rules"] = [_rule_competitor(rule) for rule in sorted(family_matches, key=_rule_rank)[:5]]
        return base

    context_matches = [rule for rule in period_matches if _context_conditions_match(row, rule)]
    if not context_matches:
        base["replay_reason"] = "label, statement family, and period matched but context conditions did not match"
        base["competing_rules"] = [_rule_competitor(rule) for rule in sorted(period_matches, key=_rule_rank)[:5]]
        return base

    qnames = {str(rule.get("target_qname")) for rule in context_matches if rule.get("target_qname")}
    if len(qnames) > 1:
        base["replay_confidence"] = "conflicting_rule_match"
        base["replay_reason"] = "multiple rules matched the row label and statement family"
        base["error_reason"] = "conflicting_rule_match"
        base["competing_rules"] = [_rule_competitor(rule) for rule in sorted(context_matches, key=_rule_rank)[:8]]
        return base

    rule = sorted(context_matches, key=_rule_rank)[0]
    tier = str(rule.get("confidence_tier") or "weak")
    status = str(rule.get("rule_status") or "")
    if status == "review_required":
        confidence = "review_required_rule_match"
    elif tier == "strong":
        confidence = "strong_rule_match"
    elif tier == "usable":
        confidence = "usable_rule_match"
    else:
        confidence = "review_required_rule_match"
    base.update(
        {
            "matched_rule_id": rule.get("rule_id"),
            "rule_confidence_tier": tier,
            "predicted_qname": rule.get("target_qname"),
            "predicted_concept_label": rule.get("target_concept_label"),
            "replay_confidence": confidence,
            "replay_reason": "matched normalized label or alias with compatible statement family",
            "competing_rules": [_rule_competitor(item) for item in sorted(period_matches, key=_rule_rank)[1:6]],
        }
    )
    return base


def _rule_competitor(rule: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": rule.get("rule_id"),
        "target_qname": rule.get("target_qname"),
        "confidence_tier": rule.get("confidence_tier"),
        "rule_status": rule.get("rule_status"),
        "statement_family": rule.get("statement_family"),
    }


def _period_matches(row: PdfRowValue, fact: Mapping[str, Any]) -> bool:
    fact_year = fact_period_year(fact)
    if row.expected_year and fact_year and row.expected_year != fact_year:
        return False
    expected_type = expected_period_type_for_statement(row.pdf_statement_family)
    actual_type = fact_period_type(fact)
    if expected_type and actual_type != "unknown" and expected_type != actual_type:
        return False
    return True


def _fact_ref(fact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "matched_xbrl_fact_id": fact.get("fact_id"),
        "matched_xbrl_value": fact.get("normalized_value") or normalize_numeric_value(fact.get("value")),
        "matched_xbrl_context": fact.get("context_ref"),
    }


def evaluate_prediction(prediction: Mapping[str, Any], row: PdfRowValue, facts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result = dict(prediction)
    qname = result.get("predicted_qname")
    if not qname:
        result.update({"evaluation_status": "not_evaluable", "xbrl_support_status": "no_prediction"})
        return result
    if not facts:
        result.update({"evaluation_status": "no_xbrl_support", "xbrl_support_status": "no_xbrl_facts", "error_reason": "no_xbrl_support"})
        return result

    value = normalize_numeric_value(row.pdf_value)
    qname_facts = [fact for fact in facts if str(fact.get("qname")) == str(qname)]
    value_facts = [fact for fact in facts if (fact.get("normalized_value") or normalize_numeric_value(fact.get("value"))) == value]
    qname_value_facts = [fact for fact in qname_facts if (fact.get("normalized_value") or normalize_numeric_value(fact.get("value"))) == value]
    qname_value_period_facts = [fact for fact in qname_value_facts if _period_matches(row, fact)]

    if len(qname_value_period_facts) == 1:
        result.update({"evaluation_status": "exact_qname_value_period_match", "xbrl_support_status": "supported", **_fact_ref(qname_value_period_facts[0])})
        return result
    if len(qname_value_period_facts) > 1:
        result.update(
            {
                "evaluation_status": "ambiguous_xbrl_support",
                "xbrl_support_status": "ambiguous",
                "error_reason": "multiple matching facts for predicted qname/value/period",
                "competing_xbrl_facts": [_fact_ref(fact) for fact in qname_value_period_facts[:8]],
            }
        )
        return result
    if qname_value_facts:
        result.update({"evaluation_status": "qname_value_match_period_uncertain", "xbrl_support_status": "period_uncertain", **_fact_ref(qname_value_facts[0])})
        return result
    different_qname_value_facts = [fact for fact in value_facts if str(fact.get("qname")) != str(qname) and _period_matches(row, fact)]
    if different_qname_value_facts:
        result.update(
            {
                "evaluation_status": "value_exists_but_different_qname",
                "xbrl_support_status": "unsupported",
                "error_reason": "same value/period exists under a different qname",
                **_fact_ref(different_qname_value_facts[0]),
                "matched_xbrl_qname": different_qname_value_facts[0].get("qname"),
            }
        )
        return result
    if qname_facts:
        result.update(
            {
                "evaluation_status": "qname_exists_but_value_mismatch",
                "xbrl_support_status": "unsupported",
                "error_reason": "predicted qname exists but no matching value/period fact was found",
            }
        )
        return result
    result.update(
        {
            "evaluation_status": "predicted_qname_not_found_in_xbrl",
            "xbrl_support_status": "unsupported",
            "error_reason": "predicted qname not present in local XBRL facts",
        }
    )
    return result


def replay_sample(
    *,
    sample_id: str,
    row_values: Sequence[PdfRowValue],
    facts: Sequence[Mapping[str, Any]],
    rules: Sequence[Mapping[str, Any]],
    debug_label: str | None = None,
) -> dict[str, Any]:
    wanted = normalize_label(debug_label) if debug_label else None
    predictions = []
    for row in row_values:
        if wanted and wanted not in normalize_label(row.pdf_label):
            continue
        prediction = replay_row_value(row, rules)
        predictions.append(evaluate_prediction(prediction, row, facts))
    return {
        "sample_id": sample_id,
        "predictions": predictions,
        "summary": summarize_predictions(predictions, rules=rules),
    }


def _prediction_count(predictions: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for item in predictions if item.get("predicted_qname"))


def _false_positive_count(predictions: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for item in predictions if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES)


def _not_evaluable_count(predictions: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for item in predictions if item.get("predicted_qname") and item.get("evaluation_status") in NOT_EVALUABLE_STATUSES)


def _qname_value_match_count(predictions: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for item in predictions if item.get("evaluation_status") in GOOD_STATUSES)


def _precision(predictions: Sequence[Mapping[str, Any]]) -> float | None:
    good = _qname_value_match_count(predictions)
    false = _false_positive_count(predictions)
    return _safe_rate(good, good + false)


def summarize_predictions(predictions: Sequence[Mapping[str, Any]], *, rules: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    prediction_count = _prediction_count(predictions)
    exact = sum(1 for item in predictions if item.get("evaluation_status") == "exact_qname_value_period_match")
    qname_value = _qname_value_match_count(predictions)
    false_positive = _false_positive_count(predictions)
    not_evaluable = _not_evaluable_count(predictions)
    by_confidence = Counter(str(item.get("replay_confidence") or "unknown") for item in predictions)
    status_counts = Counter(str(item.get("evaluation_status") or "unknown") for item in predictions)
    active_rules = [rule for rule in rules if rule.get("rule_status") == "active"]
    used_rule_ids = {item.get("matched_rule_id") for item in predictions if item.get("matched_rule_id")}
    strong_predictions = [item for item in predictions if item.get("rule_confidence_tier") == "strong" and item.get("predicted_qname")]
    usable_predictions = [item for item in predictions if item.get("rule_confidence_tier") == "usable" and item.get("predicted_qname")]
    active_predictions = strong_predictions + usable_predictions
    review_predictions = [item for item in predictions if item.get("replay_confidence") == "review_required_rule_match"]
    return {
        "pdf_observations": len(predictions),
        "replay_predictions": prediction_count,
        "coverage_rate": _safe_rate(prediction_count, len(predictions)),
        "active_rule_predictions": len(active_predictions),
        "active_rule_coverage_rate": _safe_rate(len(active_predictions), len(predictions)),
        "active_rule_qname_value_matches": _qname_value_match_count(active_predictions),
        "active_rule_false_positive_count": _false_positive_count(active_predictions),
        "active_rule_precision_on_evaluable": _precision(active_predictions),
        "exact_qname_value_period_matches": exact,
        "qname_value_matches": qname_value,
        "false_positive_count": false_positive,
        "not_evaluable_count": not_evaluable,
        "precision_on_evaluable": _precision(predictions),
        "strong_rule_predictions": len(strong_predictions),
        "strong_rule_qname_value_matches": _qname_value_match_count(strong_predictions),
        "strong_rule_false_positive_count": _false_positive_count(strong_predictions),
        "strong_rule_precision": _precision(strong_predictions),
        "usable_rule_predictions": len(usable_predictions),
        "usable_rule_qname_value_matches": _qname_value_match_count(usable_predictions),
        "usable_rule_false_positive_count": _false_positive_count(usable_predictions),
        "usable_rule_precision": _precision(usable_predictions),
        "review_required_rule_predictions": len(review_predictions),
        "review_required_rule_qname_value_matches": _qname_value_match_count(review_predictions),
        "review_required_rule_false_positive_count": _false_positive_count(review_predictions),
        "review_required_rule_precision": _precision(review_predictions),
        "no_rule_match_count": by_confidence.get("no_rule_match", 0),
        "conflicting_rule_match_count": by_confidence.get("conflicting_rule_match", 0),
        "evaluation_status_counts": dict(sorted(status_counts.items())),
        "replay_confidence_counts": dict(sorted(by_confidence.items())),
        "active_rules_used": len(used_rule_ids & {rule.get("rule_id") for rule in active_rules}),
        "unused_active_rules": sorted(str(rule.get("rule_id")) for rule in active_rules if rule.get("rule_id") not in used_rule_ids),
        "labels_covered_by_rules": _top_labels([item for item in predictions if item.get("predicted_qname")]),
        "labels_not_covered_by_rules": _top_labels([item for item in predictions if item.get("replay_confidence") == "no_rule_match"]),
        "top_false_positives": _top_errors(predictions, FALSE_POSITIVE_STATUSES),
        "top_missed_labels": _top_labels([item for item in predictions if item.get("replay_confidence") == "no_rule_match"])[:20],
    }


def _top_labels(predictions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    counter = Counter(str(item.get("normalized_label") or normalize_label(item.get("pdf_label"))) for item in predictions)
    return [{"normalized_label": label, "count": count} for label, count in counter.most_common(30) if label]


def _top_errors(predictions: Sequence[Mapping[str, Any]], statuses: set[str]) -> list[dict[str, Any]]:
    rows = [item for item in predictions if item.get("evaluation_status") in statuses]
    rows.sort(key=lambda item: (str(item.get("evaluation_status")), str(item.get("normalized_label")), str(item.get("sample_id"))))
    return [
        {
            "sample_id": item.get("sample_id"),
            "pdf_label": item.get("pdf_label"),
            "pdf_value": item.get("pdf_value"),
            "predicted_qname": item.get("predicted_qname"),
            "matched_xbrl_qname": item.get("matched_xbrl_qname"),
            "evaluation_status": item.get("evaluation_status"),
            "error_reason": item.get("error_reason"),
        }
        for item in rows[:30]
    ]


def _aggregate_summaries(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    total_observations = sum(int(item.get("pdf_observations") or 0) for item in summaries)
    predictions = sum(int(item.get("replay_predictions") or 0) for item in summaries)
    active_predictions = sum(int(item.get("active_rule_predictions") or 0) for item in summaries)
    active_qname_value = sum(int(item.get("active_rule_qname_value_matches") or 0) for item in summaries)
    active_false_positive = sum(int(item.get("active_rule_false_positive_count") or 0) for item in summaries)
    exact = sum(int(item.get("exact_qname_value_period_matches") or 0) for item in summaries)
    qname_value = sum(int(item.get("qname_value_matches") or 0) for item in summaries)
    false_positive = sum(int(item.get("false_positive_count") or 0) for item in summaries)
    not_evaluable = sum(int(item.get("not_evaluable_count") or 0) for item in summaries)
    no_rule = sum(int(item.get("no_rule_match_count") or 0) for item in summaries)
    strong_predictions = sum(int(item.get("strong_rule_predictions") or 0) for item in summaries)
    strong_qname_value = sum(int(item.get("strong_rule_qname_value_matches") or 0) for item in summaries)
    strong_false_positive = sum(int(item.get("strong_rule_false_positive_count") or 0) for item in summaries)
    usable_predictions = sum(int(item.get("usable_rule_predictions") or 0) for item in summaries)
    usable_qname_value = sum(int(item.get("usable_rule_qname_value_matches") or 0) for item in summaries)
    usable_false_positive = sum(int(item.get("usable_rule_false_positive_count") or 0) for item in summaries)
    review_predictions = sum(int(item.get("review_required_rule_predictions") or 0) for item in summaries)
    review_qname_value = sum(int(item.get("review_required_rule_qname_value_matches") or 0) for item in summaries)
    review_false_positive = sum(int(item.get("review_required_rule_false_positive_count") or 0) for item in summaries)
    status_counts: Counter[str] = Counter()
    replay_counts: Counter[str] = Counter()
    for item in summaries:
        status_counts.update(item.get("evaluation_status_counts") or {})
        replay_counts.update(item.get("replay_confidence_counts") or {})
    return {
        "pdf_observations": total_observations,
        "replay_predictions": predictions,
        "coverage_rate": _safe_rate(predictions, total_observations),
        "active_rule_predictions": active_predictions,
        "active_rule_coverage_rate": _safe_rate(active_predictions, total_observations),
        "active_rule_qname_value_matches": active_qname_value,
        "active_rule_false_positive_count": active_false_positive,
        "active_rule_precision_on_evaluable": _safe_rate(active_qname_value, active_qname_value + active_false_positive),
        "exact_qname_value_period_matches": exact,
        "qname_value_matches": qname_value,
        "false_positive_count": false_positive,
        "not_evaluable_count": not_evaluable,
        "precision_on_evaluable": _safe_rate(qname_value, qname_value + false_positive),
        "strong_rule_predictions": strong_predictions,
        "strong_rule_qname_value_matches": strong_qname_value,
        "strong_rule_false_positive_count": strong_false_positive,
        "strong_rule_precision": _safe_rate(strong_qname_value, strong_qname_value + strong_false_positive),
        "usable_rule_predictions": usable_predictions,
        "usable_rule_qname_value_matches": usable_qname_value,
        "usable_rule_false_positive_count": usable_false_positive,
        "usable_rule_precision": _safe_rate(usable_qname_value, usable_qname_value + usable_false_positive),
        "review_required_rule_predictions": review_predictions,
        "review_required_rule_qname_value_matches": review_qname_value,
        "review_required_rule_false_positive_count": review_false_positive,
        "review_required_rule_precision": _safe_rate(review_qname_value, review_qname_value + review_false_positive),
        "no_rule_match_count": no_rule,
        "evaluation_status_counts": dict(sorted(status_counts.items())),
        "replay_confidence_counts": dict(sorted(replay_counts.items())),
    }


SampleLoader = Callable[[str], Mapping[str, Any]]


def leave_one_out_replay(
    *,
    alignments: Sequence[Mapping[str, Any]],
    sample_ids: Sequence[str],
    sample_loader: SampleLoader,
    holdout_sample: str | None = None,
    debug_label: str | None = None,
) -> dict[str, Any]:
    folds = []
    selected_samples = [sample for sample in sample_ids if not holdout_sample or sample == holdout_sample]
    for sample_id in selected_samples:
        train_sample_ids = [sample for sample in sample_ids if sample != sample_id]
        train_alignments = [item for item in alignments if str(item.get("sample_id")) in set(train_sample_ids)]
        rules = build_rulebook_entries(train_alignments)
        data = sample_loader(sample_id)
        replay = replay_sample(
            sample_id=sample_id,
            row_values=data.get("row_values") or [],
            facts=data.get("facts") or [],
            rules=rules,
            debug_label=debug_label,
        )
        active_rules = [rule for rule in rules if rule.get("rule_status") == "active"]
        fold = {
            "holdout_sample": sample_id,
            "train_sample_ids": train_sample_ids,
            "train_sample_count": len(train_sample_ids),
            "active_rules_built": len(active_rules),
            "strong_rules_built": sum(1 for rule in active_rules if rule.get("confidence_tier") == "strong"),
            "usable_rules_built": sum(1 for rule in active_rules if rule.get("confidence_tier") == "usable"),
            "review_required_rules_built": sum(1 for rule in rules if rule.get("rule_status") == "review_required"),
            "pdf_observations_in_holdout": len(data.get("row_values") or []),
            **replay["summary"],
            "predictions": replay["predictions"],
        }
        folds.append(fold)
    aggregate = _aggregate_summaries(folds)
    aggregate["fold_count"] = len(folds)
    aggregate["holdout_samples"] = [fold["holdout_sample"] for fold in folds]
    return {"folds": folds, "aggregate": aggregate}


def in_sample_replay(
    *,
    sample_ids: Sequence[str],
    rules: Sequence[Mapping[str, Any]],
    sample_loader: SampleLoader,
    debug_label: str | None = None,
) -> dict[str, Any]:
    samples = []
    for sample_id in sample_ids:
        data = sample_loader(sample_id)
        replay = replay_sample(
            sample_id=sample_id,
            row_values=data.get("row_values") or [],
            facts=data.get("facts") or [],
            rules=rules,
            debug_label=debug_label,
        )
        samples.append({"sample_id": sample_id, **replay})
    aggregate = _aggregate_summaries([sample["summary"] for sample in samples])
    aggregate["sample_count"] = len(samples)
    active_rule_ids = {rule.get("rule_id") for rule in rules if rule.get("rule_status") == "active"}
    used_rule_ids = {
        prediction.get("matched_rule_id")
        for sample in samples
        for prediction in sample.get("predictions") or []
        if prediction.get("matched_rule_id")
    }
    aggregate["active_rules_used"] = len(active_rule_ids & used_rule_ids)
    aggregate["unused_active_rules"] = sorted(str(rule_id) for rule_id in active_rule_ids - used_rule_ids if rule_id)
    return {"samples": samples, "aggregate": aggregate}


def _outlier_sample_ids(alignment_report: Mapping[str, Any]) -> list[str]:
    samples = (alignment_report.get("discovery") or {}).get("excluded_samples") or []
    return [
        str(sample.get("sample_id"))
        for sample in samples
        if sample.get("sample_id") and "outlier" in str(sample.get("reason") or "").lower()
    ]


def _per_rule_performance(predictions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in predictions:
        if item.get("matched_rule_id"):
            grouped[str(item["matched_rule_id"])].append(item)
    output = []
    for rule_id, items in grouped.items():
        output.append(
            {
                "rule_id": rule_id,
                "target_qname": items[0].get("predicted_qname"),
                "confidence_tier": items[0].get("rule_confidence_tier"),
                "predictions": len(items),
                "exact_qname_value_period_matches": sum(1 for item in items if item.get("evaluation_status") == "exact_qname_value_period_match"),
                "qname_value_matches": _qname_value_match_count(items),
                "false_positive_count": _false_positive_count(items),
                "not_evaluable_count": _not_evaluable_count(items),
                "precision_on_evaluable": _precision(items),
                "matched_labels": _top_labels(items)[:10],
            }
        )
    return sorted(output, key=lambda item: (-int(item["predictions"]), str(item["rule_id"])))


def _recommend_next(holdout: Mapping[str, Any]) -> dict[str, Any]:
    active_precision = holdout.get("active_rule_precision_on_evaluable")
    active_coverage = holdout.get("active_rule_coverage_rate") or 0
    active_predictions = int(holdout.get("active_rule_predictions") or 0)
    overall_precision = holdout.get("precision_on_evaluable")
    overall_coverage = holdout.get("coverage_rate") or 0
    precision = active_precision if active_predictions else overall_precision
    coverage = active_coverage if active_predictions else overall_coverage
    false_positive = int(holdout.get("active_rule_false_positive_count") or holdout.get("false_positive_count") or 0)
    if active_predictions and (precision is not None and precision < 0.85):
        feature = "Feature #18B-hotfix-1 - tighten rulebook inclusion criteria."
        action = "tighten_rulebook"
    elif active_predictions and precision is not None and precision >= 0.85 and coverage >= 0.2:
        feature = "Feature #18D - Integrate rulebook into production mapper as deterministic-first advisory layer."
        action = "integrate_deterministic_first_layer"
    else:
        feature = "Feature #18D-A - Expand deterministic rulebook using review-required patterns / better context."
        action = "expand_rulebook_first"
    return {
        "recommended_action": action,
        "recommended_next_feature": feature,
        "basis": {
            "holdout_coverage_rate": coverage,
            "holdout_precision_on_evaluable": precision,
            "holdout_active_rule_coverage_rate": active_coverage,
            "holdout_active_rule_precision_on_evaluable": active_precision,
            "holdout_overall_coverage_rate": overall_coverage,
            "holdout_overall_precision_on_evaluable": overall_precision,
            "holdout_replay_predictions": int(holdout.get("replay_predictions") or 0),
            "holdout_active_rule_predictions": active_predictions,
            "holdout_false_positive_count": false_positive,
        },
    }


def build_replay_reports(
    *,
    dataset_dir: str | Path,
    alignment_report: Mapping[str, Any],
    rulebook_report: Mapping[str, Any],
    include_outlier: bool = True,
    holdout_sample: str | None = None,
    skip_leave_one_out: bool = False,
    debug_label: str | None = None,
    sample_data_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    sample_ids = _sample_ids_from_alignment_report(alignment_report)
    company_names = _company_by_sample(alignment_report)

    cache: dict[str, Mapping[str, Any]] = {}

    def load_sample(sample_id: str) -> Mapping[str, Any]:
        if sample_data_by_id and sample_id in sample_data_by_id:
            return sample_data_by_id[sample_id]
        if sample_id not in cache:
            cache[sample_id] = load_sample_replay_data(
                dataset_dir=dataset_dir,
                sample_id=sample_id,
                company_name=company_names.get(sample_id),
            )
        return cache[sample_id]

    alignments = alignment_report.get("alignments") or []
    final_rules = rulebook_report.get("rules") or []
    holdout = (
        {"folds": [], "aggregate": {"fold_count": 0, "skipped": True}}
        if skip_leave_one_out
        else leave_one_out_replay(
            alignments=alignments,
            sample_ids=sample_ids,
            sample_loader=load_sample,
            holdout_sample=holdout_sample,
            debug_label=debug_label,
        )
    )
    in_sample = in_sample_replay(sample_ids=sample_ids, rules=final_rules, sample_loader=load_sample, debug_label=debug_label)

    outlier_results = []
    if include_outlier:
        for sample_id in _outlier_sample_ids(alignment_report):
            data = (
                sample_data_by_id[sample_id]
                if sample_data_by_id and sample_id in sample_data_by_id
                else load_sample_replay_data(dataset_dir=dataset_dir, sample_id=sample_id)
            )
            replay = replay_sample(sample_id=sample_id, row_values=data["row_values"], facts=data["facts"], rules=final_rules, debug_label=debug_label)
            outlier_results.append(
                {
                    "sample_id": sample_id,
                    "company_name": data.get("company_name"),
                    "pdf_observations": len(data["row_values"]),
                    "xbrl_numeric_facts": len(data["facts"]),
                    "summary": replay["summary"],
                    "predictions": replay["predictions"],
                    "format_mismatch_diagnostics": {
                        "coverage_rate": replay["summary"].get("coverage_rate"),
                        "no_rule_match_count": replay["summary"].get("no_rule_match_count"),
                        "top_missed_labels": replay["summary"].get("top_missed_labels"),
                    },
                }
            )
    outlier_aggregate = _aggregate_summaries([item["summary"] for item in outlier_results]) if outlier_results else {"sample_count": 0}
    outlier_aggregate["sample_count"] = len(outlier_results)

    all_predictions = [
        prediction
        for fold in holdout.get("folds") or []
        for prediction in fold.get("predictions") or []
    ]
    recommendation = _recommend_next(holdout.get("aggregate") or {})
    generated_at = _utc_now()
    run_metadata = {
        "feature": "18C",
        "generated_at": generated_at,
        "read_only": True,
        "offline_only": True,
        "dataset_dir": str(dataset_dir),
        **SAFETY,
    }
    full = {
        "run_metadata": run_metadata,
        "summary": {
            "feature": "18C",
            "generated_at": generated_at,
            "sample_ids": sample_ids,
            "leave_one_out": holdout.get("aggregate"),
            "in_sample": in_sample.get("aggregate"),
            "outlier": outlier_aggregate,
            "per_rule_performance": _per_rule_performance(
                [
                    prediction
                    for sample in in_sample.get("samples") or []
                    for prediction in sample.get("predictions") or []
                ]
            ),
            "strong_vs_usable": _strong_vs_usable(all_predictions),
            "recommendation": recommendation,
            "safety": SAFETY,
        },
        "leave_one_out": holdout,
        "in_sample": in_sample,
        "outlier": {"samples": outlier_results, "aggregate": outlier_aggregate},
    }
    errors = {
        "run_metadata": run_metadata,
        "summary": {
            "holdout_false_positive_count": (holdout.get("aggregate") or {}).get("false_positive_count", 0),
            "holdout_not_evaluable_count": (holdout.get("aggregate") or {}).get("not_evaluable_count", 0),
        },
        "false_positives": _top_errors(all_predictions, FALSE_POSITIVE_STATUSES),
        "not_evaluable": _top_errors(all_predictions, NOT_EVALUABLE_STATUSES),
        "missed_labels": _top_labels([item for item in all_predictions if item.get("replay_confidence") == "no_rule_match"])[:50],
    }
    return {
        "full": full,
        "holdout_summary": {
            "run_metadata": run_metadata,
            "summary": {
                "leave_one_out": holdout.get("aggregate"),
                "folds": [
                    {key: value for key, value in fold.items() if key != "predictions"}
                    for fold in holdout.get("folds") or []
                ],
                "recommendation": recommendation,
                "safety": SAFETY,
            },
        },
        "errors": errors,
        "outlier": {
            "run_metadata": run_metadata,
            "summary": outlier_aggregate,
            "samples": outlier_results,
        },
    }


def _strong_vs_usable(predictions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    strong = [item for item in predictions if item.get("rule_confidence_tier") == "strong" and item.get("predicted_qname")]
    usable = [item for item in predictions if item.get("rule_confidence_tier") == "usable" and item.get("predicted_qname")]
    review = [item for item in predictions if item.get("replay_confidence") == "review_required_rule_match"]
    return {
        "strong": {
            "predictions": len(strong),
            "qname_value_matches": _qname_value_match_count(strong),
            "false_positive_count": _false_positive_count(strong),
            "precision_on_evaluable": _precision(strong),
        },
        "usable": {
            "predictions": len(usable),
            "qname_value_matches": _qname_value_match_count(usable),
            "false_positive_count": _false_positive_count(usable),
            "precision_on_evaluable": _precision(usable),
        },
        "review_required": {
            "predictions": len(review),
            "qname_value_matches": _qname_value_match_count(review),
            "false_positive_count": _false_positive_count(review),
            "precision_on_evaluable": _precision(review),
        },
    }


def render_replay_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    holdout = summary.get("leave_one_out") or {}
    in_sample = summary.get("in_sample") or {}
    recommendation = summary.get("recommendation") or {}
    lines = [
        "# PDF-XBRL Rulebook Replay - Feature #18C",
        "",
        "## Leave-One-Out",
        "",
        f"- Coverage: {holdout.get('coverage_rate')}",
        f"- Precision on evaluable predictions: {holdout.get('precision_on_evaluable')}",
        f"- Exact qname/value/period matches: {holdout.get('exact_qname_value_period_matches', 0)}",
        f"- False positives: {holdout.get('false_positive_count', 0)}",
        f"- Not evaluable: {holdout.get('not_evaluable_count', 0)}",
        "",
        "## In-Sample",
        "",
        f"- Coverage: {in_sample.get('coverage_rate')}",
        f"- Precision on evaluable predictions: {in_sample.get('precision_on_evaluable')}",
        f"- Exact qname/value/period matches: {in_sample.get('exact_qname_value_period_matches', 0)}",
        "",
        "## Recommendation",
        "",
        f"- Action: {recommendation.get('recommended_action')}",
        f"- Next: {recommendation.get('recommended_next_feature')}",
        "",
    ]
    return "\n".join(lines)


def render_holdout_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    holdout = summary.get("leave_one_out") or {}
    lines = [
        "# PDF-XBRL Rulebook Holdout Summary - Feature #18C",
        "",
        f"- Folds: {holdout.get('fold_count', 0)}",
        f"- Observations: {holdout.get('pdf_observations', 0)}",
        f"- Predictions: {holdout.get('replay_predictions', 0)}",
        f"- Coverage: {holdout.get('coverage_rate')}",
        f"- Precision: {holdout.get('precision_on_evaluable')}",
        "",
        "| Holdout | Active rules | Predictions | Coverage | Precision | False positives |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fold in summary.get("folds") or []:
        lines.append(
            f"| {fold.get('holdout_sample')} | {fold.get('active_rules_built')} | {fold.get('replay_predictions')} | "
            f"{fold.get('coverage_rate')} | {fold.get('precision_on_evaluable')} | {fold.get('false_positive_count')} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_errors_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# PDF-XBRL Rulebook Replay Errors - Feature #18C",
        "",
        f"- False positives: {(report.get('summary') or {}).get('holdout_false_positive_count', 0)}",
        f"- Not evaluable: {(report.get('summary') or {}).get('holdout_not_evaluable_count', 0)}",
        "",
        "## Top False Positives",
        "",
        "| Sample | Label | Predicted qname | Status |",
        "| --- | --- | --- | --- |",
    ]
    for item in report.get("false_positives") or []:
        lines.append(f"| {item.get('sample_id')} | {item.get('pdf_label')} | {item.get('predicted_qname')} | {item.get('evaluation_status')} |")
    lines.append("")
    return "\n".join(lines)


def render_outlier_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF-XBRL Rulebook Outlier Replay - Feature #18C",
        "",
        f"- Outlier sample count: {summary.get('sample_count', 0)}",
        f"- Coverage: {summary.get('coverage_rate')}",
        f"- Precision: {summary.get('precision_on_evaluable')}",
        "",
    ]
    for sample in report.get("samples") or []:
        sample_summary = sample.get("summary") or {}
        lines.extend(
            [
                f"## {sample.get('sample_id')}",
                "",
                f"- Observations: {sample_summary.get('pdf_observations', 0)}",
                f"- Predictions: {sample_summary.get('replay_predictions', 0)}",
                f"- Coverage: {sample_summary.get('coverage_rate')}",
                f"- Precision: {sample_summary.get('precision_on_evaluable')}",
                "",
            ]
        )
    return "\n".join(lines)


def write_replay_reports(
    *,
    dataset_dir: str | Path,
    alignment_report_path: str | Path,
    rulebook_report_path: str | Path,
    output_dir: str | Path,
    include_outlier: bool = True,
    holdout_sample: str | None = None,
    skip_leave_one_out: bool = False,
    debug_label: str | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = build_replay_reports(
        dataset_dir=dataset_dir,
        alignment_report=_read_json(alignment_report_path),
        rulebook_report=_read_json(rulebook_report_path),
        include_outlier=include_outlier,
        holdout_sample=holdout_sample,
        skip_leave_one_out=skip_leave_one_out,
        debug_label=debug_label,
    )
    paths = {
        "replay_json": output / "pdf_xbrl_rulebook_replay_18c.json",
        "replay_md": output / "pdf_xbrl_rulebook_replay_18c.md",
        "holdout_json": output / "pdf_xbrl_rulebook_holdout_summary_18c.json",
        "holdout_md": output / "pdf_xbrl_rulebook_holdout_summary_18c.md",
        "errors_json": output / "pdf_xbrl_rulebook_replay_errors_18c.json",
        "errors_md": output / "pdf_xbrl_rulebook_replay_errors_18c.md",
        "outlier_json": output / "pdf_xbrl_rulebook_replay_outlier_18c.json",
        "outlier_md": output / "pdf_xbrl_rulebook_replay_outlier_18c.md",
    }
    _write_json(paths["replay_json"], reports["full"])
    _write_json(paths["holdout_json"], reports["holdout_summary"])
    _write_json(paths["errors_json"], reports["errors"])
    _write_json(paths["outlier_json"], reports["outlier"])
    paths["replay_md"].write_text(render_replay_markdown(reports["full"]), encoding="utf-8")
    paths["holdout_md"].write_text(render_holdout_markdown(reports["holdout_summary"]), encoding="utf-8")
    paths["errors_md"].write_text(render_errors_markdown(reports["errors"]), encoding="utf-8")
    paths["outlier_md"].write_text(render_outlier_markdown(reports["outlier"]), encoding="utf-8")
    return {"paths": paths, **reports}
