"""Context-aware PDF-XBRL rulebook expansion for Feature #18D-A."""

from __future__ import annotations

import copy
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.pdf_xbrl_deterministic_alignment import canonical_label, normalize_label
from services.pdf_xbrl_mapping_rulebook import build_rulebook_entries
from services.pdf_xbrl_rulebook_replay import (
    FALSE_POSITIVE_STATUSES,
    GOOD_STATUSES,
    SAFETY,
    _aggregate_summaries,
    _company_by_sample,
    _outlier_sample_ids,
    _sample_ids_from_alignment_report,
    in_sample_replay,
    load_sample_replay_data,
    replay_sample,
)


STRONG_PRECISION_THRESHOLD = 0.90
USABLE_PRECISION_THRESHOLD = 0.80
MATERIAL_COVERAGE_DELTA = 0.01

FATAL_CONFLICTS = {
    "period_type_mismatch",
    "sign_mismatch_absolute_value_only",
    "statement_family_mismatch",
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


def _normalize_set(values: Any) -> set[str]:
    return {normalize_label(value) for value in _as_list(values) if normalize_label(value)}


def _local_qname(qname: Any) -> str:
    return str(qname or "").split(":")[-1].lower()


def _rule_key(entry: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        canonical_label(entry.get("normalized_label_pattern")),
        str(entry.get("target_qname") or ""),
        str(entry.get("statement_family") or ""),
    )


UPGRADE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "revenue_income_statement",
        "labels": {"revenue"},
        "target_qnames": {"ifrs-smes:Revenue"},
        "statement_family": "income_statement",
        "period_type": "duration",
        "min_sample_support": 2,
        "required_context_conditions": {
            "statement_family": "income_statement",
            "period_type": "duration",
            "label_exact_any": ["revenue", "sales", "turnover"],
            "label_contains_any": ["revenue", "sales", "turnover"],
        },
        "blocking_conditions": {
            "label_contains_any": [
                "cost of sales",
                "finance",
                "interest",
                "other income",
                "deferred",
            ],
            "statement_type_contains_any": ["notes"],
        },
        "allowed_conflicts": set(),
    },
    {
        "name": "other_income_income_statement",
        "labels": {"other income", "add other income"},
        "target_qnames": {"ifrs-smes:OtherIncome", "ssmt-mpers:OtherMiscellaneousIncome"},
        "statement_family": "income_statement",
        "period_type": "duration",
        "min_sample_support": 2,
        "required_context_conditions": {
            "statement_family": "income_statement",
            "period_type": "duration",
            "label_contains_all": ["other", "income"],
        },
        "blocking_conditions": {
            "label_contains_any": ["revenue", "sales", "turnover", "finance", "interest", "dividend"],
            "statement_type_contains_any": ["notes"],
        },
        "allowed_conflicts": {
            "ambiguous_observations_present",
            "multiple_candidates_close_in_score",
            "target_qname_maps_from_many_label_patterns",
        },
    },
    {
        "name": "tax_expense_income_statement",
        "labels": {"tax expense"},
        "target_qnames": {"ifrs-smes:IncomeTaxExpenseContinuingOperations"},
        "statement_family": "income_statement",
        "period_type": "duration",
        "min_sample_support": 2,
        "required_context_conditions": {
            "statement_family": "income_statement",
            "period_type": "duration",
            "label_contains_any": ["tax expense", "income tax", "taxation"],
        },
        "blocking_conditions": {
            "label_contains_any": ["payable", "deferred", "asset", "liability", "provision", "profit before", "profit after"],
            "statement_type_contains_any": ["financial position", "cash flows", "notes"],
        },
        "allowed_conflicts": set(),
    },
    {
        "name": "trade_receivables_current_assets",
        "labels": {"trade and other receivables"},
        "target_qnames": {
            "ifrs-smes:TradeAndOtherCurrentReceivables",
            "ssmt-mpers:CurrentTradeReceivables",
            "ssmt-mpers:OtherCurrentReceivables",
            "ssmt-mpers:OtherCurrentNontradeReceivables",
            "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
        },
        "statement_family": "financial_position",
        "period_type": "instant",
        "min_sample_support": 2,
        "required_context_conditions": {
            "statement_family": "financial_position",
            "period_type": "instant",
            "label_contains_any": ["receivable", "receivables"],
            "statement_type_contains_any": ["financial position", "current assets", "assets"],
        },
        "blocking_conditions": {
            "label_contains_any": ["payable", "payables", "increase", "decrease"],
            "statement_type_contains_any": ["cash flows", "notes"],
        },
        "allowed_conflicts": set(),
    },
    {
        "name": "bank_balances_financial_position",
        "labels": {"bank balances", "cash and cash equivalents"},
        "target_qnames": {"ssmt:CashAndBankBalances", "ifrs-smes:CashAndCashEquivalents", "ifrs-smes:Cash"},
        "statement_family": "financial_position",
        "period_type": "instant",
        "min_sample_support": 3,
        "allow_ambiguous_only": True,
        "min_ambiguous_score": 88,
        "default_tier_without_replay": "usable",
        "required_context_conditions": {
            "statement_family": "financial_position",
            "period_type": "instant",
            "label_contains_any": ["bank balances", "cash and cash equivalents", "cash"],
            "statement_type_contains_any": ["financial position"],
        },
        "blocking_conditions": {
            "label_contains_any": ["increase", "decrease", "beginning", "end of", "net"],
            "statement_type_contains_any": ["cash flows", "notes"],
        },
        "allowed_conflicts": {
            "ambiguous_observations_present",
            "multiple_candidates_close_in_score",
            "statement_family_conflict",
        },
    },
    {
        "name": "ppe_financial_position",
        "labels": {"property plant and equipment"},
        "target_qnames": {"ifrs-smes:PropertyPlantAndEquipment"},
        "statement_family": "financial_position",
        "period_type": "instant",
        "min_sample_support": 1,
        "default_tier_without_replay": "strong",
        "required_context_conditions": {
            "statement_family": "financial_position",
            "period_type": "instant",
            "label_exact_any": ["property plant and equipment", "ppe"],
            "label_contains_all": ["property", "equipment"],
            "statement_type_contains_any": ["financial position", "non current assets", "assets"],
        },
        "blocking_conditions": {
            "label_contains_any": ["depreciation", "addition", "disposal", "movement", "increase", "decrease"],
            "statement_type_contains_any": ["cash flows", "notes"],
        },
        "allowed_conflicts": {
            "label_statement_maps_to_multiple_qnames",
        },
    },
    {
        "name": "total_current_assets",
        "labels": {"total current assets"},
        "target_qnames": {"ifrs-smes:CurrentAssets"},
        "statement_family": "financial_position",
        "period_type": "instant",
        "min_sample_support": 2,
        "required_context_conditions": {
            "statement_family": "financial_position",
            "period_type": "instant",
            "label_contains_all": ["current", "assets"],
            "requires_total_semantics": True,
            "statement_type_contains_any": ["financial position", "current assets", "assets"],
        },
        "blocking_conditions": {
            "label_contains_any": ["liabilities", "equity"],
            "statement_type_contains_any": ["notes", "cash flows"],
        },
        "allowed_conflicts": {"subtotal_total_semantics_mismatch"},
    },
    {
        "name": "total_operating_expenses_income_statement",
        "labels": {"total operating expenses"},
        "target_qnames": {"ifrs-smes:OtherExpenseByFunction"},
        "statement_family": "income_statement",
        "period_type": "duration",
        "min_sample_support": 2,
        "required_context_conditions": {
            "statement_family": "income_statement",
            "period_type": "duration",
            "label_contains_all": ["operating", "expenses"],
            "requires_total_semantics": True,
            "statement_type_contains_any": ["comprehensive income", "profit or loss", "income statement"],
        },
        "blocking_conditions": {
            "label_contains_any": ["finance costs", "tax"],
            "statement_type_contains_any": ["notes", "cash flows", "financial position"],
        },
        "allowed_conflicts": {
            "ambiguous_observations_present",
            "current_comparative_period_confusion",
            "generic_pdf_label_with_duplicate_value",
            "major_alignment_conflict",
            "multiple_candidates_close_in_score",
            "period_year_mismatch",
            "same_value_repeated_across_many_facts",
            "statement_family_conflict",
            "subtotal_total_semantics_mismatch",
            "target_qname_maps_from_many_label_patterns",
        },
    },
)


def _spec_for_entry(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    pattern = canonical_label(entry.get("normalized_label_pattern"))
    aliases = {canonical_label(alias) for alias in entry.get("aliases") or []}
    aliases.add(pattern)
    for spec in UPGRADE_SPECS:
        if aliases & set(spec["labels"]):
            return spec
    return None


def _replay_stats_from_report(replay_report: Mapping[str, Any] | None) -> dict[tuple[str, str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    if not replay_report:
        return {}
    for fold in ((replay_report.get("leave_one_out") or {}).get("folds") or []):
        for prediction in fold.get("predictions") or []:
            if not prediction.get("predicted_qname"):
                continue
            key = (
                canonical_label(prediction.get("normalized_label") or prediction.get("pdf_label")),
                str(prediction.get("predicted_qname") or ""),
                str(prediction.get("pdf_statement_family") or ""),
            )
            grouped[key].append(prediction)

    stats = {}
    for key, predictions in grouped.items():
        good = sum(1 for item in predictions if item.get("evaluation_status") in GOOD_STATUSES)
        false = sum(1 for item in predictions if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES)
        stats[key] = {
            "predictions": len(predictions),
            "qname_value_matches": good,
            "false_positive_count": false,
            "precision_on_evaluable": _safe_rate(good, good + false),
        }
    return stats


def _prediction_stats(predictions: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for prediction in predictions:
        if not prediction.get("predicted_qname"):
            continue
        key = (
            canonical_label(prediction.get("normalized_label") or prediction.get("pdf_label")),
            str(prediction.get("predicted_qname") or ""),
            str(prediction.get("pdf_statement_family") or ""),
        )
        grouped[key].append(prediction)
    output = {}
    for key, items in grouped.items():
        good = sum(1 for item in items if item.get("evaluation_status") in GOOD_STATUSES)
        false = sum(1 for item in items if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES)
        output[key] = {
            "predictions": len(items),
            "qname_value_matches": good,
            "false_positive_count": false,
            "precision_on_evaluable": _safe_rate(good, good + false),
        }
    return output


def _zero_only(entry: Mapping[str, Any]) -> bool:
    evidence = entry.get("evidence_summary") or {}
    return int(evidence.get("zero_value_count") or 0) > 0 and int(evidence.get("nonzero_value_count") or 0) == 0


def _support_ok(entry: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    sample_support = int(entry.get("sample_support_count") or 0)
    high = int(entry.get("high_confidence_count") or 0)
    medium = int(entry.get("medium_confidence_count") or 0)
    ambiguous = int(entry.get("ambiguous_observation_count") or 0)
    score_max = float(entry.get("score_max") or 0)
    score_avg = float(entry.get("score_avg") or 0)
    evidence = entry.get("evidence_summary") or {}
    repeated_safe = (high + medium) > 0 and sample_support >= int(spec.get("min_sample_support") or 2)
    strong_single = high > 0 and score_max >= 95 and bool(evidence.get("label_support"))
    ambiguous_contextual = (
        bool(spec.get("allow_ambiguous_only"))
        and ambiguous > 0
        and sample_support >= int(spec.get("min_sample_support") or 2)
        and score_avg >= float(spec.get("min_ambiguous_score") or 90)
    )
    return repeated_safe or strong_single or ambiguous_contextual


def _concept_family_ok(entry: Mapping[str, Any], spec: Mapping[str, Any]) -> bool:
    qname = _local_qname(entry.get("target_qname"))
    family = str(spec.get("name") or "")
    if "receivables" in family and "payable" in qname:
        return False
    if "tax_expense" in family and any(token in qname for token in ("payable", "asset", "liability", "deferred")):
        return False
    if "ppe" in family and "depreciation" in qname:
        return False
    if "revenue" in family and any(token in qname for token in ("costofsales", "expense")):
        return False
    return True


def _decision_base(entry: Mapping[str, Any], spec: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        "rule_id": entry.get("rule_id"),
        "normalized_label_pattern": entry.get("normalized_label_pattern"),
        "target_qname": entry.get("target_qname"),
        "statement_family": entry.get("statement_family"),
        "original_status": entry.get("rule_status"),
        "original_confidence_tier": entry.get("confidence_tier"),
        "upgrade_spec": (spec or {}).get("name"),
        "upgraded_status": None,
        "upgrade_reason": None,
        "required_context_conditions": {},
        "blocking_conditions": {},
        "evidence_samples": entry.get("sample_ids") or [],
        "replay_precision_before": None,
        "replay_precision_after": None,
        "blocking_reasons": [],
    }


def evaluate_context_upgrade(
    entry: Mapping[str, Any],
    *,
    prior_replay_stats: Mapping[tuple[str, str, str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate one #18B rulebook entry for conservative #18D-A promotion."""
    spec = _spec_for_entry(entry)
    decision = _decision_base(entry, spec)
    key = _rule_key(entry)
    prior_stats = dict((prior_replay_stats or {}).get(key) or {})
    if prior_stats:
        decision["replay_precision_before"] = prior_stats.get("precision_on_evaluable")

    status = str(entry.get("rule_status") or "")
    if status == "active":
        decision["upgraded_status"] = "original_active"
        decision["upgrade_reason"] = "already active in #18B rulebook"
        return decision
    if not spec:
        decision["upgraded_status"] = "still_excluded" if status == "excluded" else "still_review_required"
        decision["blocking_reasons"] = ["no_context_upgrade_spec"]
        return decision

    blocking = []
    target_qname = str(entry.get("target_qname") or "")
    if target_qname not in set(spec.get("target_qnames") or set()):
        blocking.append("target_qname_not_allowed_for_context_spec")
    if entry.get("statement_family") != spec.get("statement_family"):
        blocking.append("statement_family_not_allowed_for_context_spec")
    if spec.get("period_type") and entry.get("period_type_hint") != spec.get("period_type"):
        blocking.append("period_type_not_allowed_for_context_spec")
    if _zero_only(entry):
        blocking.append("zero_only_evidence")
    if not _concept_family_ok(entry, spec):
        blocking.append("concept_family_incompatible_with_context_spec")
    if not _support_ok(entry, spec):
        blocking.append("insufficient_repeated_or_strong_context_evidence")

    conflicts = set(entry.get("conflict_reasons") or [])
    allowed_conflicts = set(spec.get("allowed_conflicts") or set())
    disallowed_conflicts = conflicts - allowed_conflicts
    if disallowed_conflicts & FATAL_CONFLICTS:
        blocking.append("fatal_conflict_not_resolved_by_context")
    unresolved = sorted(disallowed_conflicts - {"ambiguous_observations_present", "multiple_candidates_close_in_score"})
    if unresolved:
        blocking.append("unresolved_conflicts:" + ",".join(unresolved[:6]))

    precision = prior_stats.get("precision_on_evaluable")
    if precision is not None and float(precision) < USABLE_PRECISION_THRESHOLD:
        blocking.append("prior_replay_precision_below_usable_threshold")

    if blocking:
        decision["upgraded_status"] = "still_excluded" if status == "excluded" else "still_review_required"
        decision["blocking_reasons"] = sorted(dict.fromkeys(blocking))
        return decision

    if precision is not None:
        tier = "strong" if float(precision) >= STRONG_PRECISION_THRESHOLD else "usable"
    else:
        tier = str(spec.get("default_tier_without_replay") or "usable")
    decision["upgraded_status"] = f"upgraded_{tier}"
    decision["upgrade_reason"] = (
        "context-specific promotion passed statement, period, support, conflict, zero-value, "
        "concept-family, and prior replay checks"
    )
    decision["required_context_conditions"] = copy.deepcopy(spec.get("required_context_conditions") or {})
    decision["blocking_conditions"] = copy.deepcopy(spec.get("blocking_conditions") or {})
    return decision


def expand_rulebook_entries(
    entries: Sequence[Mapping[str, Any]],
    *,
    replay_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    prior_stats = _replay_stats_from_report(replay_report)
    expanded_rules: list[dict[str, Any]] = []
    decisions = []
    for entry in entries:
        rule = copy.deepcopy(dict(entry))
        decision = evaluate_context_upgrade(rule, prior_replay_stats=prior_stats)
        decisions.append(decision)
        if decision["upgraded_status"] in {"upgraded_strong", "upgraded_usable"}:
            tier = "strong" if decision["upgraded_status"] == "upgraded_strong" else "usable"
            rule.update(
                {
                    "original_status": decision["original_status"],
                    "original_confidence_tier": decision["original_confidence_tier"],
                    "rule_status": "active",
                    "confidence_tier": tier,
                    "upgrade_status": decision["upgraded_status"],
                    "upgrade_reason": decision["upgrade_reason"],
                    "required_context_conditions": decision["required_context_conditions"],
                    "blocking_conditions": decision["blocking_conditions"],
                    "replay_precision_before": decision["replay_precision_before"],
                    "replay_precision_after": decision["replay_precision_after"],
                    "notes": [
                        *(rule.get("notes") or []),
                        "Promoted by #18D-A context-aware offline expansion; not production-integrated.",
                    ],
                }
            )
        else:
            rule.setdefault("upgrade_status", decision["upgraded_status"])
            if decision.get("blocking_reasons"):
                rule["context_upgrade_blocking_reasons"] = decision["blocking_reasons"]
        expanded_rules.append(rule)
    return {"rules": expanded_rules, "decisions": decisions}


def _update_after_stats(
    *,
    rules: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    predictions: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    after_stats = _prediction_stats(predictions)
    updated_rules = []
    for rule in rules:
        item = copy.deepcopy(dict(rule))
        if item.get("upgrade_status") in {"upgraded_strong", "upgraded_usable"}:
            item["replay_precision_after"] = (after_stats.get(_rule_key(item)) or {}).get("precision_on_evaluable")
            item["replay_after"] = after_stats.get(_rule_key(item))
        updated_rules.append(item)
    updated_decisions = []
    for decision in decisions:
        item = copy.deepcopy(dict(decision))
        if item.get("upgraded_status") in {"upgraded_strong", "upgraded_usable"}:
            item["replay_precision_after"] = (after_stats.get(_rule_key(item)) or {}).get("precision_on_evaluable")
            item["replay_after"] = after_stats.get(_rule_key(item))
        updated_decisions.append(item)
    return updated_rules, updated_decisions


def _count_rules(rules: Sequence[Mapping[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for rule in rules:
        status = rule.get("rule_status")
        tier = rule.get("confidence_tier")
        upgrade = rule.get("upgrade_status")
        if status == "active":
            counter["active"] += 1
            if tier == "strong":
                counter["active_strong"] += 1
            elif tier == "usable":
                counter["active_usable"] += 1
        elif status == "review_required":
            counter["review_required"] += 1
        elif status == "excluded":
            counter["excluded"] += 1
        if upgrade == "upgraded_strong":
            counter["upgraded_strong"] += 1
        elif upgrade == "upgraded_usable":
            counter["upgraded_usable"] += 1
    return counter


def _top_upgraded_labels(rules: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    upgraded = [rule for rule in rules if rule.get("upgrade_status") in {"upgraded_strong", "upgraded_usable"}]
    upgraded.sort(
        key=lambda item: (
            str(item.get("upgrade_status")),
            -int(((item.get("replay_after") or {}).get("predictions") or 0)),
            str(item.get("normalized_label_pattern")),
        )
    )
    return [
        {
            "normalized_label_pattern": rule.get("normalized_label_pattern"),
            "target_qname": rule.get("target_qname"),
            "upgraded_status": rule.get("upgrade_status"),
            "required_context_conditions": rule.get("required_context_conditions"),
            "blocking_conditions": rule.get("blocking_conditions"),
            "replay_precision_before": rule.get("replay_precision_before"),
            "replay_precision_after": rule.get("replay_precision_after"),
            "replay_after": rule.get("replay_after"),
        }
        for rule in upgraded
    ]


def _top_rejections(decisions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rejected = [
        decision
        for decision in decisions
        if decision.get("upgrade_spec") and decision.get("upgraded_status") in {"still_excluded", "still_review_required"}
    ]
    rejected.sort(
        key=lambda item: (
            str(item.get("normalized_label_pattern")),
            str(item.get("target_qname")),
        )
    )
    return [
        {
            "normalized_label_pattern": item.get("normalized_label_pattern"),
            "target_qname": item.get("target_qname"),
            "statement_family": item.get("statement_family"),
            "original_status": item.get("original_status"),
            "upgraded_status": item.get("upgraded_status"),
            "upgrade_spec": item.get("upgrade_spec"),
            "blocking_reasons": item.get("blocking_reasons"),
            "replay_precision_before": item.get("replay_precision_before"),
        }
        for item in rejected
    ]


def leave_one_out_expansion_replay(
    *,
    alignments: Sequence[Mapping[str, Any]],
    sample_ids: Sequence[str],
    sample_loader: Any,
    replay_report: Mapping[str, Any] | None = None,
    expand: bool = True,
    holdout_sample: str | None = None,
    debug_label: str | None = None,
) -> dict[str, Any]:
    folds = []
    selected_samples = [sample for sample in sample_ids if not holdout_sample or sample == holdout_sample]
    for sample_id in selected_samples:
        train_sample_ids = [sample for sample in sample_ids if sample != sample_id]
        train_alignments = [item for item in alignments if str(item.get("sample_id")) in set(train_sample_ids)]
        rules = build_rulebook_entries(train_alignments)
        decisions = []
        if expand:
            expanded = expand_rulebook_entries(rules, replay_report=replay_report)
            rules = expanded["rules"]
            decisions = expanded["decisions"]
        data = sample_loader(sample_id)
        replay = replay_sample(
            sample_id=sample_id,
            row_values=data.get("row_values") or [],
            facts=data.get("facts") or [],
            rules=rules,
            debug_label=debug_label,
        )
        counts = _count_rules(rules)
        fold = {
            "holdout_sample": sample_id,
            "train_sample_ids": train_sample_ids,
            "train_sample_count": len(train_sample_ids),
            "active_rules_built": counts["active"],
            "strong_rules_built": counts["active_strong"],
            "usable_rules_built": counts["active_usable"],
            "upgraded_strong_rules_built": counts["upgraded_strong"],
            "upgraded_usable_rules_built": counts["upgraded_usable"],
            "review_required_rules_built": counts["review_required"],
            "pdf_observations_in_holdout": len(data.get("row_values") or []),
            "upgrade_decisions": decisions,
            **replay["summary"],
            "predictions": replay["predictions"],
        }
        folds.append(fold)
    aggregate = _aggregate_summaries(folds)
    aggregate["fold_count"] = len(folds)
    aggregate["holdout_samples"] = [fold["holdout_sample"] for fold in folds]
    aggregate["upgraded_strong_rules_built_avg"] = _safe_rate(
        sum(int(fold.get("upgraded_strong_rules_built") or 0) for fold in folds),
        len(folds),
    )
    aggregate["upgraded_usable_rules_built_avg"] = _safe_rate(
        sum(int(fold.get("upgraded_usable_rules_built") or 0) for fold in folds),
        len(folds),
    )
    return {"folds": folds, "aggregate": aggregate}


def _metric_delta(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    fields = [
        "active_rule_coverage_rate",
        "active_rule_precision_on_evaluable",
        "active_rule_predictions",
        "active_rule_false_positive_count",
        "coverage_rate",
        "precision_on_evaluable",
        "false_positive_count",
    ]
    output = {}
    for field in fields:
        before_value = before.get(field)
        after_value = after.get(field)
        output[field] = {"before": before_value, "after": after_value}
        if isinstance(before_value, (int, float)) and isinstance(after_value, (int, float)):
            output[field]["delta"] = round(after_value - before_value, 4)
    return output


def _recommendation(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    before_coverage = before.get("active_rule_coverage_rate") or 0
    after_coverage = after.get("active_rule_coverage_rate") or 0
    precision = after.get("active_rule_precision_on_evaluable")
    coverage_delta = after_coverage - before_coverage
    if precision is not None and precision < STRONG_PRECISION_THRESHOLD:
        next_feature = "Feature #18D-A-hotfix-1 - tighten upgrade criteria."
        action = "tighten_upgrade_criteria"
        integration_plan = False
    elif precision is not None and coverage_delta >= MATERIAL_COVERAGE_DELTA:
        next_feature = (
            "Feature #18D-B - Replay expanded rulebook on holdout/outlier and "
            "prepare deterministic-first mapper integration plan"
        )
        action = "prepare_integration_plan_after_expanded_replay"
        integration_plan = True
    else:
        next_feature = "Feature #18D-A-2 - extract section/block context from Azure DI layout for broader rule coverage"
        action = "improve_section_context"
        integration_plan = False
    return {
        "recommended_action": action,
        "recommended_next_feature": next_feature,
        "production_integration_now_justified": False,
        "deterministic_first_integration_plan_justified": integration_plan,
        "basis": {
            "expanded_active_rule_precision": precision,
            "expanded_active_rule_coverage": after_coverage,
            "active_rule_coverage_delta": round(coverage_delta, 4),
            "active_rule_false_positive_count": after.get("active_rule_false_positive_count"),
        },
    }


def _all_predictions(replay: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        prediction
        for fold in replay.get("folds") or []
        for prediction in fold.get("predictions") or []
    ]


def build_expansion_reports(
    *,
    dataset_dir: str | Path,
    alignment_report: Mapping[str, Any],
    rulebook_report: Mapping[str, Any],
    replay_report: Mapping[str, Any] | None = None,
    holdout_sample: str | None = None,
    debug_label: str | None = None,
    sample_data_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    sample_ids = _sample_ids_from_alignment_report(alignment_report)
    company_names = _company_by_sample(alignment_report)
    alignments = alignment_report.get("alignments") or []
    original_rules = rulebook_report.get("rules") or []
    expanded = expand_rulebook_entries(original_rules, replay_report=replay_report)
    expanded_rules = expanded["rules"]
    decisions = expanded["decisions"]

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

    original_replay = leave_one_out_expansion_replay(
        alignments=alignments,
        sample_ids=sample_ids,
        sample_loader=load_sample,
        replay_report=replay_report,
        expand=False,
        holdout_sample=holdout_sample,
        debug_label=debug_label,
    )
    expanded_replay = leave_one_out_expansion_replay(
        alignments=alignments,
        sample_ids=sample_ids,
        sample_loader=load_sample,
        replay_report=replay_report,
        expand=True,
        holdout_sample=holdout_sample,
        debug_label=debug_label,
    )
    expanded_rules, decisions = _update_after_stats(
        rules=expanded_rules,
        decisions=decisions,
        predictions=_all_predictions(expanded_replay),
    )
    in_sample = in_sample_replay(
        sample_ids=sample_ids,
        rules=expanded_rules,
        sample_loader=load_sample,
        debug_label=debug_label,
    )

    original_counts = _count_rules(original_rules)
    expanded_counts = _count_rules(expanded_rules)
    before = original_replay["aggregate"]
    after = expanded_replay["aggregate"]
    generated_at = _utc_now()
    run_metadata = {
        "feature": "18D-A",
        "generated_at": generated_at,
        "read_only": True,
        "offline_only": True,
        "dataset_dir": str(dataset_dir),
        "outlier_samples_excluded_from_main_metrics": _outlier_sample_ids(alignment_report),
        **SAFETY,
    }
    summary = {
        "feature": "18D-A",
        "generated_at": generated_at,
        "original_active_rules": original_counts["active"],
        "original_active_strong_rules": original_counts["active_strong"],
        "original_active_usable_rules": original_counts["active_usable"],
        "expanded_active_rules": expanded_counts["active"],
        "expanded_active_strong_rules": expanded_counts["active_strong"],
        "expanded_active_usable_rules": expanded_counts["active_usable"],
        "upgraded_strong_rules": expanded_counts["upgraded_strong"],
        "upgraded_usable_rules": expanded_counts["upgraded_usable"],
        "still_review_required_rules": expanded_counts["review_required"],
        "still_excluded_rules": expanded_counts["excluded"],
        "before_after_leave_one_out": _metric_delta(before, after),
        "original_leave_one_out": before,
        "expanded_leave_one_out": after,
        "expanded_in_sample": in_sample.get("aggregate"),
        "top_upgraded_labels": _top_upgraded_labels(expanded_rules),
        "top_rejected_labels": _top_rejections(decisions)[:20],
        "recommendation": _recommendation(before, after),
        "safety": SAFETY,
    }
    expanded_report = {
        "run_metadata": run_metadata,
        "summary": summary,
        "rules": expanded_rules,
        "upgrade_decisions": decisions,
    }
    summary_report = {
        "run_metadata": run_metadata,
        "summary": summary,
    }
    replay_report_out = {
        "run_metadata": run_metadata,
        "summary": {
            "original_leave_one_out": before,
            "expanded_leave_one_out": after,
            "comparison": summary["before_after_leave_one_out"],
            "recommendation": summary["recommendation"],
            "safety": SAFETY,
        },
        "original_leave_one_out": {
            "folds": [{key: value for key, value in fold.items() if key != "predictions"} for fold in original_replay["folds"]],
            "aggregate": before,
        },
        "expanded_leave_one_out": {
            "folds": [{key: value for key, value in fold.items() if key != "predictions"} for fold in expanded_replay["folds"]],
            "aggregate": after,
        },
    }
    rejections_report = {
        "run_metadata": run_metadata,
        "summary": {
            "rejected_context_candidate_count": len(_top_rejections(decisions)),
            "top_rejected_labels": _top_rejections(decisions)[:30],
            "safety": SAFETY,
        },
        "rejections": _top_rejections(decisions),
    }
    return {
        "expanded": expanded_report,
        "summary": summary_report,
        "replay": replay_report_out,
        "rejections": rejections_report,
    }


def render_expanded_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF-XBRL Expanded Rulebook - Feature #18D-A",
        "",
        f"- Original active rules: {summary.get('original_active_rules')}",
        f"- Expanded active rules: {summary.get('expanded_active_rules')}",
        f"- Upgraded strong rules: {summary.get('upgraded_strong_rules')}",
        f"- Upgraded usable rules: {summary.get('upgraded_usable_rules')}",
        "",
        "## Top Upgraded Labels",
        "",
        "| Label | Target qname | Status | After precision |",
        "| --- | --- | --- | ---: |",
    ]
    for item in summary.get("top_upgraded_labels") or []:
        lines.append(
            f"| {item.get('normalized_label_pattern')} | {item.get('target_qname')} | "
            f"{item.get('upgraded_status')} | {item.get('replay_precision_after')} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    before = summary.get("original_leave_one_out") or {}
    after = summary.get("expanded_leave_one_out") or {}
    recommendation = summary.get("recommendation") or {}
    lines = [
        "# PDF-XBRL Rulebook Expansion Summary - Feature #18D-A",
        "",
        "## Rule Counts",
        "",
        f"- Original active rules: {summary.get('original_active_rules')}",
        f"- Expanded active rules: {summary.get('expanded_active_rules')}",
        f"- Upgraded strong rules: {summary.get('upgraded_strong_rules')}",
        f"- Upgraded usable rules: {summary.get('upgraded_usable_rules')}",
        f"- Still review-required rules: {summary.get('still_review_required_rules')}",
        f"- Still excluded rules: {summary.get('still_excluded_rules')}",
        "",
        "## Active Leave-One-Out Replay",
        "",
        f"- Before coverage: {before.get('active_rule_coverage_rate')}",
        f"- After coverage: {after.get('active_rule_coverage_rate')}",
        f"- Before precision: {before.get('active_rule_precision_on_evaluable')}",
        f"- After precision: {after.get('active_rule_precision_on_evaluable')}",
        f"- Before false positives: {before.get('active_rule_false_positive_count')}",
        f"- After false positives: {after.get('active_rule_false_positive_count')}",
        "",
        "## Recommendation",
        "",
        f"- Production integration now justified: {recommendation.get('production_integration_now_justified')}",
        f"- Integration plan justified: {recommendation.get('deterministic_first_integration_plan_justified')}",
        f"- Next: {recommendation.get('recommended_next_feature')}",
        "",
    ]
    return "\n".join(lines)


def render_replay_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    before = summary.get("original_leave_one_out") or {}
    after = summary.get("expanded_leave_one_out") or {}
    lines = [
        "# PDF-XBRL Rulebook Expansion Replay - Feature #18D-A",
        "",
        "| Metric | Before | After |",
        "| --- | ---: | ---: |",
        f"| Active coverage | {before.get('active_rule_coverage_rate')} | {after.get('active_rule_coverage_rate')} |",
        f"| Active precision | {before.get('active_rule_precision_on_evaluable')} | {after.get('active_rule_precision_on_evaluable')} |",
        f"| Active predictions | {before.get('active_rule_predictions')} | {after.get('active_rule_predictions')} |",
        f"| Active false positives | {before.get('active_rule_false_positive_count')} | {after.get('active_rule_false_positive_count')} |",
        "",
    ]
    return "\n".join(lines)


def render_rejections_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# PDF-XBRL Rulebook Expansion Rejections - Feature #18D-A",
        "",
        f"- Rejected context candidates: {(report.get('summary') or {}).get('rejected_context_candidate_count')}",
        "",
        "| Label | Target qname | Status | Reasons |",
        "| --- | --- | --- | --- |",
    ]
    for item in report.get("rejections") or []:
        lines.append(
            f"| {item.get('normalized_label_pattern')} | {item.get('target_qname')} | "
            f"{item.get('upgraded_status')} | {', '.join(item.get('blocking_reasons') or [])} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_expansion_reports(
    *,
    dataset_dir: str | Path,
    alignment_report_path: str | Path,
    rulebook_report_path: str | Path,
    replay_report_path: str | Path,
    output_dir: str | Path,
    holdout_sample: str | None = None,
    debug_label: str | None = None,
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    reports = build_expansion_reports(
        dataset_dir=dataset_dir,
        alignment_report=_read_json(alignment_report_path),
        rulebook_report=_read_json(rulebook_report_path),
        replay_report=_read_json(replay_report_path),
        holdout_sample=holdout_sample,
        debug_label=debug_label,
    )
    paths = {
        "expanded_json": output / "pdf_xbrl_rulebook_expanded_18d_a.json",
        "expanded_md": output / "pdf_xbrl_rulebook_expanded_18d_a.md",
        "summary_json": output / "pdf_xbrl_rulebook_expansion_summary_18d_a.json",
        "summary_md": output / "pdf_xbrl_rulebook_expansion_summary_18d_a.md",
        "replay_json": output / "pdf_xbrl_rulebook_expansion_replay_18d_a.json",
        "replay_md": output / "pdf_xbrl_rulebook_expansion_replay_18d_a.md",
        "rejections_json": output / "pdf_xbrl_rulebook_expansion_rejections_18d_a.json",
        "rejections_md": output / "pdf_xbrl_rulebook_expansion_rejections_18d_a.md",
    }
    _write_json(paths["expanded_json"], reports["expanded"])
    _write_json(paths["summary_json"], reports["summary"])
    _write_json(paths["replay_json"], reports["replay"])
    _write_json(paths["rejections_json"], reports["rejections"])
    paths["expanded_md"].write_text(render_expanded_markdown(reports["expanded"]), encoding="utf-8")
    paths["summary_md"].write_text(render_summary_markdown(reports["summary"]), encoding="utf-8")
    paths["replay_md"].write_text(render_replay_markdown(reports["replay"]), encoding="utf-8")
    paths["rejections_md"].write_text(render_rejections_markdown(reports["rejections"]), encoding="utf-8")
    return {"paths": paths, **reports}
