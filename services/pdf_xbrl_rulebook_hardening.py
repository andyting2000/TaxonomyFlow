"""Expanded PDF-XBRL rulebook hardening for Feature #18D-B."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.pdf_xbrl_deterministic_alignment import canonical_label, normalize_label
from services.pdf_xbrl_rulebook_context_upgrade import leave_one_out_expansion_replay
from services.pdf_xbrl_rulebook_replay import (
    FALSE_POSITIVE_STATUSES,
    GOOD_STATUSES,
    NOT_EVALUABLE_STATUSES,
    SAFETY,
    _aggregate_summaries,
    _company_by_sample,
    _outlier_sample_ids,
    _sample_ids_from_alignment_report,
    load_sample_replay_data,
    replay_sample,
)


PRODUCTION_PRECISION_THRESHOLD = 0.95
ADVISORY_PRECISION_THRESHOLD = 0.90
MIN_SAFE_CANDIDATES_FOR_OFFLINE_INTEGRATION = 5

GENERIC_LABELS = {"amount", "balance", "current", "less", "net", "other", "subtotal", "total"}
QNAME_CONFLICTS = {"label_statement_maps_to_multiple_qnames", "conflicting_qnames"}
STATEMENT_CONFLICTS = {"statement_family_conflict", "statement_family_mismatch"}
GENERIC_CONFLICTS = {"generic_label_requires_review", "generic_label_without_statement_context"}

NO_AUTO_APPLY_BOUNDARIES = [
    "Rulebook output must not set confirmed_tag_id.",
    "Rulebook output must not auto-accept or auto-apply a mapping.",
    "Rulebook output must be persisted only as mapping suggestion evidence.",
    "Human review remains final for accepted mappings.",
    "Supervisor or LLM review can focus on exceptions, conflicts, and unmapped rows.",
]


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


def _rule_key(rule: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        canonical_label(rule.get("normalized_label_pattern")),
        str(rule.get("target_qname") or ""),
        str(rule.get("statement_family") or ""),
    )


def _prediction_key(prediction: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        canonical_label(prediction.get("normalized_label") or prediction.get("pdf_label")),
        str(prediction.get("predicted_qname") or ""),
        str(prediction.get("pdf_statement_family") or ""),
    )


def _active_rules(expanded_rulebook: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(rule) for rule in expanded_rulebook.get("rules") or [] if rule.get("rule_status") == "active"]


def _active_prediction(prediction: Mapping[str, Any]) -> bool:
    return bool(prediction.get("predicted_qname")) and prediction.get("rule_confidence_tier") in {"strong", "usable"}


def _all_replay_predictions(replay: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [prediction for fold in replay.get("folds") or [] for prediction in fold.get("predictions") or []]


def _top_labels(predictions: Sequence[Mapping[str, Any]], *, limit: int = 30) -> list[dict[str, Any]]:
    counter = Counter(str(item.get("normalized_label") or normalize_label(item.get("pdf_label"))) for item in predictions)
    return [{"normalized_label": label, "count": count} for label, count in counter.most_common(limit) if label]


def _performance_from_predictions(
    predictions: Sequence[Mapping[str, Any]],
    *,
    total_observations: int,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for prediction in predictions:
        if _active_prediction(prediction):
            grouped[_prediction_key(prediction)].append(prediction)

    output: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, items in grouped.items():
        good = sum(1 for item in items if item.get("evaluation_status") in GOOD_STATUSES)
        false = sum(1 for item in items if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES)
        not_evaluable = sum(1 for item in items if item.get("evaluation_status") in NOT_EVALUABLE_STATUSES)
        output[key] = {
            "predictions": len(items),
            "qname_value_matches": good,
            "false_positive_count": false,
            "not_evaluable_count": not_evaluable,
            "precision_on_evaluable": _safe_rate(good, good + false),
            "coverage_rate": _safe_rate(len(items), total_observations),
            "matched_rule_ids": sorted({str(item.get("matched_rule_id")) for item in items if item.get("matched_rule_id")}),
            "matched_labels": _top_labels(items, limit=10),
        }
    return output


def _fallback_performance(rule: Mapping[str, Any], *, total_observations: int) -> dict[str, Any]:
    replay_after = rule.get("replay_after") or {}
    predictions = int(replay_after.get("predictions") or 0)
    good = int(replay_after.get("qname_value_matches") or 0)
    false = int(replay_after.get("false_positive_count") or 0)
    precision = replay_after.get("precision_on_evaluable")
    if precision is None:
        precision = _safe_rate(good, good + false)
    return {
        "predictions": predictions,
        "qname_value_matches": good,
        "false_positive_count": false,
        "not_evaluable_count": 0,
        "precision_on_evaluable": precision,
        "coverage_rate": _safe_rate(predictions, total_observations),
        "matched_rule_ids": [rule.get("rule_id")] if rule.get("rule_id") and predictions else [],
        "matched_labels": [],
    }


def _zero_only_evidence(rule: Mapping[str, Any]) -> bool:
    evidence = rule.get("evidence_summary") or {}
    return int(evidence.get("zero_value_count") or 0) > 0 and int(evidence.get("nonzero_value_count") or 0) == 0


def _generic_label(rule: Mapping[str, Any]) -> bool:
    normalized = normalize_label(rule.get("normalized_label_pattern"))
    tokens = normalized.split()
    conflicts = set(rule.get("conflict_reasons") or [])
    return normalized in GENERIC_LABELS or len(tokens) <= 1 or bool(conflicts & GENERIC_CONFLICTS)


def _has_required_context(rule: Mapping[str, Any]) -> bool:
    return bool(rule.get("required_context_conditions"))


def _strong_concept_evidence(rule: Mapping[str, Any]) -> bool:
    evidence = rule.get("evidence_summary") or {}
    return (
        int(rule.get("high_confidence_count") or 0) > 0
        and bool(evidence.get("label_support"))
        and float(rule.get("score_max") or 0) >= 95
    )


def _stable_support(rule: Mapping[str, Any]) -> bool:
    return int(rule.get("sample_support_count") or 0) >= 2 or _strong_concept_evidence(rule)


def _rule_risk_flags(rule: Mapping[str, Any]) -> dict[str, Any]:
    conflicts = set(rule.get("conflict_reasons") or [])
    return {
        "zero_only_evidence": _zero_only_evidence(rule),
        "qname_conflict": bool(conflicts & QNAME_CONFLICTS),
        "statement_family_conflict": bool(conflicts & STATEMENT_CONFLICTS),
        "generic_label": _generic_label(rule),
        "generic_without_context": _generic_label(rule) and not _has_required_context(rule),
        "context_conditions_required": _has_required_context(rule),
        "stable_support": _stable_support(rule),
        "strong_concept_evidence": _strong_concept_evidence(rule),
        "conflict_reasons": sorted(conflicts),
    }


def classify_rule_readiness(
    rule: Mapping[str, Any],
    performance: Mapping[str, Any] | None = None,
    *,
    total_observations: int = 0,
    outlier_performance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Conservatively classify one active expanded rule for future advisory use."""
    perf = dict(performance or _fallback_performance(rule, total_observations=total_observations))
    flags = _rule_risk_flags(rule)
    predictions = int(perf.get("predictions") or 0)
    false_positive_count = int(perf.get("false_positive_count") or 0)
    precision = perf.get("precision_on_evaluable")
    outlier_false_positive_count = int((outlier_performance or {}).get("false_positive_count") or 0)
    reasons: list[str] = []

    if flags["zero_only_evidence"]:
        return {
            "readiness": "exclude",
            "reasons": ["zero-only evidence is not safe for deterministic mapping"],
            "risk_flags": flags,
            "performance": perf,
        }
    if outlier_false_positive_count:
        return {
            "readiness": "downgrade_to_review_required",
            "reasons": ["outlier replay produced a false positive"],
            "risk_flags": flags,
            "performance": perf,
        }
    if false_positive_count >= 2:
        return {
            "readiness": "exclude",
            "reasons": ["repeated false positives across replay"],
            "risk_flags": flags,
            "performance": perf,
        }
    if false_positive_count and (precision is None or float(precision) < ADVISORY_PRECISION_THRESHOLD):
        return {
            "readiness": "downgrade_to_review_required",
            "reasons": ["active rule has false positive evidence below advisory precision threshold"],
            "risk_flags": flags,
            "performance": perf,
        }
    if precision is not None and float(precision) < ADVISORY_PRECISION_THRESHOLD:
        return {
            "readiness": "review_only",
            "reasons": ["precision below advisory threshold"],
            "risk_flags": flags,
            "performance": perf,
        }
    if flags["generic_without_context"]:
        return {
            "readiness": "review_only",
            "reasons": ["generic label lacks required context conditions"],
            "risk_flags": flags,
            "performance": perf,
        }
    if flags["qname_conflict"] or flags["statement_family_conflict"]:
        reasons.append("conflict history prevents production-candidate classification")
        if precision is not None and float(precision) < ADVISORY_PRECISION_THRESHOLD:
            return {
                "readiness": "review_only",
                "reasons": reasons,
                "risk_flags": flags,
                "performance": perf,
            }
        return {
            "readiness": "advisory_candidate",
            "reasons": reasons + ["rule can rank suggestions but should not be final deterministic output"],
            "risk_flags": flags,
            "performance": perf,
        }

    production_precision_ok = precision is not None and float(precision) >= PRODUCTION_PRECISION_THRESHOLD
    no_false_positive_with_replay = predictions > 0 and false_positive_count == 0
    if (production_precision_ok or no_false_positive_with_replay) and flags["stable_support"]:
        return {
            "readiness": "production_candidate",
            "reasons": ["high precision or no false positives with stable support"],
            "risk_flags": flags,
            "performance": perf,
        }

    if precision is not None and float(precision) >= ADVISORY_PRECISION_THRESHOLD:
        reasons.append("precision is advisory-safe but support or conflict history is limited")
    elif predictions == 0:
        reasons.append("active rule has limited leave-one-out replay evidence")
    else:
        reasons.append("rule is useful as ranking evidence only")
    return {
        "readiness": "advisory_candidate",
        "reasons": reasons,
        "risk_flags": flags,
        "performance": perf,
    }


def _error_type(prediction: Mapping[str, Any]) -> str:
    label = normalize_label(prediction.get("pdf_label"))
    family = str(prediction.get("pdf_statement_family") or "")
    status = str(prediction.get("evaluation_status") or "")
    reason = str(prediction.get("error_reason") or "").lower()
    if "cash" in label and family == "cash_flow":
        return "cash-flow vs balance-sheet confusion"
    if any(token in label.split() for token in ("total", "subtotal")) or label.startswith("net "):
        return "subtotal/component confusion"
    if any(token in label for token in ("other", "add", "miscellaneous")):
        return "generic label conflict"
    if "period mismatch" in reason or "period confusion" in reason:
        return "period confusion"
    if status == "value_exists_but_different_qname":
        return "value matched wrong concept"
    if status == "predicted_qname_not_found_in_xbrl":
        return "wrong qname"
    if status == "qname_exists_but_value_mismatch":
        return "wrong qname"
    return "other"


def _recommended_fix(error_type: str) -> str:
    fixes = {
        "wrong qname": "add context condition",
        "value matched wrong concept": "leave for human review",
        "period confusion": "add context condition",
        "statement family mismatch": "add context condition",
        "generic label conflict": "downgrade rule",
        "subtotal/component confusion": "require section block",
        "note-section confusion": "require section block",
        "cash-flow vs balance-sheet confusion": "add context condition",
        "other": "leave for human review",
    }
    return fixes.get(error_type, "leave for human review")


def analyze_false_positive(
    prediction: Mapping[str, Any],
    *,
    rule_lookup: Mapping[tuple[str, str, str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    key = _prediction_key(prediction)
    rule = (rule_lookup or {}).get(key) or {}
    error_type = _error_type(prediction)
    rule_status = "active" if prediction.get("rule_confidence_tier") in {"strong", "usable"} else "review_required"
    return {
        "sample_id": prediction.get("sample_id"),
        "pdf_label": prediction.get("pdf_label"),
        "normalized_label": canonical_label(prediction.get("normalized_label") or prediction.get("pdf_label")),
        "pdf_value": prediction.get("pdf_value"),
        "pdf_statement_family": prediction.get("pdf_statement_family"),
        "predicted_qname": prediction.get("predicted_qname"),
        "expected_or_local_supported_qname": prediction.get("matched_xbrl_qname"),
        "matched_rule_id": prediction.get("matched_rule_id"),
        "matched_final_rule_id": rule.get("rule_id"),
        "rule_status": rule_status,
        "rule_confidence_tier": prediction.get("rule_confidence_tier"),
        "evaluation_status": prediction.get("evaluation_status"),
        "error_type": error_type,
        "recommended_fix": _recommended_fix(error_type),
    }


def _false_positive_report(
    *,
    active_false_positives: Sequence[Mapping[str, Any]],
    all_false_positives: Sequence[Mapping[str, Any]],
    rule_lookup: Mapping[tuple[str, str, str], Mapping[str, Any]],
    run_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    analyzed = [analyze_false_positive(item, rule_lookup=rule_lookup) for item in active_false_positives]
    type_counts = Counter(item["error_type"] for item in analyzed)
    fix_counts = Counter(item["recommended_fix"] for item in analyzed)
    return {
        "run_metadata": run_metadata,
        "summary": {
            "active_false_positive_count": len(active_false_positives),
            "all_rule_false_positive_count": len(all_false_positives),
            "error_type_counts": dict(sorted(type_counts.items())),
            "recommended_fix_counts": dict(sorted(fix_counts.items())),
            "raw_xml_included": False,
            "safety": SAFETY,
        },
        "false_positives": analyzed,
    }


def _missed_label_opportunities(predictions: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    missed = [item for item in predictions if item.get("replay_confidence") == "no_rule_match"]
    opportunities = []
    for item in _top_labels(missed, limit=30):
        label = item["normalized_label"]
        if any(token in label for token in ("tax", "revenue", "receivable", "payable")):
            direction = "needs stronger section/block context before promotion"
        elif any(token in label for token in ("cash", "bank", "overdraft")):
            direction = "separate cash-flow and balance-sheet cash contexts"
        else:
            direction = "candidate for later coverage analysis, not automatic promotion"
        opportunities.append({**item, "remediation_direction": direction})
    return opportunities


def _outlier_ids(dataset_dir: str | Path, alignment_report: Mapping[str, Any] | None, requested: Sequence[str] | None) -> list[str]:
    if requested:
        return [str(item) for item in requested]
    if alignment_report:
        found = _outlier_sample_ids(alignment_report)
        if found:
            return found
    default_case = Path(dataset_dir) / "case_006"
    return ["case_006"] if default_case.exists() else []


def build_outlier_replay_report(
    *,
    dataset_dir: str | Path,
    expanded_rulebook: Mapping[str, Any],
    alignment_report: Mapping[str, Any] | None = None,
    sample_data_by_id: Mapping[str, Mapping[str, Any]] | None = None,
    outlier_sample_ids: Sequence[str] | None = None,
    run_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    active_rules = _active_rules(expanded_rulebook)
    samples = []
    for sample_id in _outlier_ids(dataset_dir, alignment_report, outlier_sample_ids):
        data = (
            sample_data_by_id[sample_id]
            if sample_data_by_id and sample_id in sample_data_by_id
            else load_sample_replay_data(dataset_dir=dataset_dir, sample_id=sample_id)
        )
        replay = replay_sample(sample_id=sample_id, row_values=data.get("row_values") or [], facts=data.get("facts") or [], rules=active_rules)
        predictions = [item for item in replay["predictions"] if item.get("predicted_qname")]
        false_positives = [item for item in predictions if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES]
        samples.append(
            {
                "sample_id": sample_id,
                "company_name": data.get("company_name"),
                "pdf_observations": len(data.get("row_values") or []),
                "xbrl_numeric_facts": len(data.get("facts") or []),
                "summary": replay["summary"],
                "matched_labels": replay["summary"].get("labels_covered_by_rules") or [],
                "missed_labels": replay["summary"].get("top_missed_labels") or [],
                "false_positives": [analyze_false_positive(item) for item in false_positives],
            }
        )
    aggregate = _aggregate_summaries([sample["summary"] for sample in samples]) if samples else {"sample_count": 0}
    aggregate["sample_count"] = len(samples)
    false_positive_count = int(aggregate.get("false_positive_count") or 0)
    aggregate["rules_remain_safe_on_outlier"] = false_positive_count == 0
    aggregate["should_remain_excluded_from_rulebook_training"] = True
    aggregate["training_exclusion_reason"] = "outlier remains separate diagnostic evidence and is not mixed into main metrics"
    return {
        "run_metadata": dict(run_metadata or {}),
        "summary": {
            **aggregate,
            "outlier_metrics_mixed_into_main_precision": False,
            "safety": SAFETY,
        },
        "samples": samples,
    }


def _outlier_performance_by_key(outlier_report: Mapping[str, Any], *, total_observations: int) -> dict[tuple[str, str, str], dict[str, Any]]:
    predictions = [
        prediction
        for sample in outlier_report.get("samples") or []
        for prediction in ((sample.get("summary") or {}).get("predictions") or [])
    ]
    return _performance_from_predictions(predictions, total_observations=total_observations)


def _replay_expanded_rulebook(
    *,
    dataset_dir: str | Path,
    alignment_report: Mapping[str, Any],
    source_replay_report: Mapping[str, Any],
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

    return leave_one_out_expansion_replay(
        alignments=alignment_report.get("alignments") or [],
        sample_ids=sample_ids,
        sample_loader=load_sample,
        replay_report=source_replay_report,
        expand=True,
    )


def _replay_consistency(saved: Mapping[str, Any], rerun: Mapping[str, Any]) -> dict[str, Any]:
    saved_aggregate = ((saved.get("expanded_leave_one_out") or {}).get("aggregate") or (saved.get("summary") or {}).get("expanded_leave_one_out") or {})
    rerun_aggregate = rerun.get("aggregate") or {}
    fields = [
        "pdf_observations",
        "active_rule_predictions",
        "active_rule_qname_value_matches",
        "active_rule_false_positive_count",
        "active_rule_precision_on_evaluable",
    ]
    comparisons = {
        field: {"saved": saved_aggregate.get(field), "rerun": rerun_aggregate.get(field), "matches": saved_aggregate.get(field) == rerun_aggregate.get(field)}
        for field in fields
    }
    return {"fields": comparisons, "matches_saved_report": all(item["matches"] for item in comparisons.values())}


def build_integration_plan(
    *,
    readiness_summary: Mapping[str, Any],
    replay_summary: Mapping[str, Any],
    outlier_summary: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    production = int(readiness_summary.get("production_candidate_count") or 0)
    advisory = int(readiness_summary.get("advisory_candidate_count") or 0)
    downgraded = int(readiness_summary.get("downgrade_to_review_required_count") or 0)
    safe_candidates = production + advisory
    outlier_safe = bool(outlier_summary.get("rules_remain_safe_on_outlier", True))
    active_precision = replay_summary.get("active_rule_precision_on_evaluable")
    active_coverage = replay_summary.get("active_rule_coverage_rate") or 0
    start_18d_c = (
        safe_candidates >= MIN_SAFE_CANDIDATES_FOR_OFFLINE_INTEGRATION
        and outlier_safe
        and active_precision is not None
        and float(active_precision) >= ADVISORY_PRECISION_THRESHOLD
    )
    if start_18d_c:
        recommended_next = "Feature #18D-C - Deterministic rulebook mapper service, offline/mock only"
        action = "start_offline_mock_integration"
    elif downgraded >= safe_candidates:
        recommended_next = "Feature #18D-A-hotfix-1 - tighten/repair context upgrades"
        action = "repair_context_upgrades"
    else:
        recommended_next = "Feature #18E-A - Extract section/block context from Azure DI layout to expand coverage"
        action = "expand_section_block_context"

    return {
        "run_metadata": {
            "feature": "18D-B",
            "generated_at": generated_at or _utc_now(),
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": {
            "recommended_action": action,
            "recommended_next_feature": recommended_next,
            "feature_18d_c_offline_mapper_service_justified": start_18d_c,
            "production_integration_now_justified": False,
            "auto_apply_approved": False,
            "confirmed_tag_id_automation_approved": False,
            "safe_candidate_count": safe_candidates,
            "active_rule_precision_on_evaluable": active_precision,
            "active_rule_coverage_rate": active_coverage,
            "coverage_remains_low": active_coverage < 0.10,
            "safety": SAFETY,
        },
        "design": {
            "deterministic_first_position": "Rulebook runs before the LLM mapper as a deterministic candidate generator.",
            "production_candidate_behavior": "Production candidates may produce deterministic suggestions but still cannot auto-apply.",
            "advisory_candidate_behavior": "Advisory rules can boost or rank candidates and require human or Supervisor review.",
            "review_only_behavior": "Review-only rules should not be auto-selected and can only provide ranking evidence.",
            "llm_supervisor_focus": "LLM and Supervisor review should focus on exceptions, conflicts, and unmapped rows.",
            "persistence_boundary": "Persist rulebook output as mapping suggestion evidence, not as final mapping state.",
            "no_auto_apply_boundaries": NO_AUTO_APPLY_BOUNDARIES,
        },
        "future_phases": [
            {
                "feature": "Feature #18D-C",
                "scope": "deterministic rulebook mapper service, offline/mock only",
                "auto_apply_allowed": False,
            },
            {
                "feature": "Feature #18D-D",
                "scope": "backend API/reporting integration as advisory suggestions only",
                "auto_apply_allowed": False,
            },
            {
                "feature": "Feature #18D-E",
                "scope": "UI display of deterministic rulebook suggestions",
                "auto_apply_allowed": False,
            },
            {
                "feature": "Feature #18D-F",
                "scope": "production rulebook feature flag and monitoring",
                "auto_apply_allowed": False,
            },
            {
                "feature": "Later explicit approval only",
                "scope": "no auto-apply unless a later feature explicitly approves it",
                "auto_apply_allowed": False,
            },
        ],
    }


def build_hardening_reports(
    *,
    dataset_dir: str | Path,
    expanded_rulebook: Mapping[str, Any],
    expansion_replay: Mapping[str, Any],
    alignment_report: Mapping[str, Any] | None = None,
    source_replay_report: Mapping[str, Any] | None = None,
    sample_data_by_id: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    generated_at = _utc_now()
    run_metadata = {
        "feature": "18D-B",
        "generated_at": generated_at,
        "read_only": True,
        "offline_only": True,
        "dataset_dir": str(dataset_dir),
        **SAFETY,
    }
    active_rules = _active_rules(expanded_rulebook)
    replay = {"folds": [], "aggregate": ((expansion_replay.get("expanded_leave_one_out") or {}).get("aggregate") or {})}
    replay_consistency = {"matches_saved_report": None, "fields": {}}
    if alignment_report and source_replay_report:
        replay = _replay_expanded_rulebook(
            dataset_dir=dataset_dir,
            alignment_report=alignment_report,
            source_replay_report=source_replay_report,
            sample_data_by_id=sample_data_by_id,
        )
        replay_consistency = _replay_consistency(expansion_replay, replay)

    replay_summary = replay.get("aggregate") or {}
    total_observations = int(replay_summary.get("pdf_observations") or 0)
    predictions = _all_replay_predictions(replay)
    active_predictions = [item for item in predictions if _active_prediction(item)]
    all_false_positives = [item for item in predictions if item.get("predicted_qname") and item.get("evaluation_status") in FALSE_POSITIVE_STATUSES]
    active_false_positives = [item for item in active_predictions if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES]
    performance_by_key = _performance_from_predictions(active_predictions, total_observations=total_observations)
    rule_lookup = {_rule_key(rule): rule for rule in expanded_rulebook.get("rules") or []}

    outlier_report = build_outlier_replay_report(
        dataset_dir=dataset_dir,
        expanded_rulebook=expanded_rulebook,
        alignment_report=alignment_report,
        sample_data_by_id=sample_data_by_id,
        run_metadata=run_metadata,
    )

    readiness_records = []
    counts: Counter[str] = Counter()
    for rule in active_rules:
        key = _rule_key(rule)
        performance = performance_by_key.get(key) or _fallback_performance(rule, total_observations=total_observations)
        classification = classify_rule_readiness(rule, performance, total_observations=total_observations)
        readiness = classification["readiness"]
        counts[readiness] += 1
        readiness_records.append(
            {
                "rule_id": rule.get("rule_id"),
                "normalized_label_pattern": rule.get("normalized_label_pattern"),
                "target_qname": rule.get("target_qname"),
                "statement_family": rule.get("statement_family"),
                "confidence_tier": rule.get("confidence_tier"),
                "upgrade_status": rule.get("upgrade_status"),
                "sample_support_count": rule.get("sample_support_count"),
                "observation_count": rule.get("observation_count"),
                "readiness": readiness,
                "classification_reasons": classification["reasons"],
                "risk_flags": classification["risk_flags"],
                "performance": classification["performance"],
                "required_context_conditions": rule.get("required_context_conditions") or {},
                "blocking_conditions": rule.get("blocking_conditions") or {},
            }
        )

    readiness_records.sort(key=lambda item: (str(item["readiness"]), str(item["normalized_label_pattern"]), str(item["target_qname"])))
    readiness_summary = {
        "active_rule_count": len(active_rules),
        "production_candidate_count": counts["production_candidate"],
        "advisory_candidate_count": counts["advisory_candidate"],
        "review_only_count": counts["review_only"],
        "downgrade_to_review_required_count": counts["downgrade_to_review_required"],
        "exclude_count": counts["exclude"],
        "expanded_replay": replay_summary,
        "replay_consistency": replay_consistency,
        "false_positive_root_cause_count": len(active_false_positives),
        "missed_label_opportunities": _missed_label_opportunities(predictions),
        "no_auto_apply_boundaries": NO_AUTO_APPLY_BOUNDARIES,
        "safety": SAFETY,
    }

    false_positive_report = _false_positive_report(
        active_false_positives=active_false_positives,
        all_false_positives=all_false_positives,
        rule_lookup=rule_lookup,
        run_metadata=run_metadata,
    )
    integration_plan = build_integration_plan(
        readiness_summary=readiness_summary,
        replay_summary=replay_summary,
        outlier_summary=outlier_report.get("summary") or {},
        generated_at=generated_at,
    )
    readiness_summary["recommendation"] = integration_plan["summary"]
    hardening_report = {
        "run_metadata": run_metadata,
        "summary": readiness_summary,
        "rule_readiness": readiness_records,
        "false_positive_root_causes": false_positive_report["false_positives"],
        "outlier_summary": outlier_report.get("summary"),
    }
    return {
        "hardening": hardening_report,
        "false_positive_analysis": false_positive_report,
        "outlier_replay": outlier_report,
        "integration_plan": integration_plan,
    }


def render_hardening_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    recommendation = summary.get("recommendation") or {}
    lines = [
        "# PDF-XBRL Rulebook Hardening - Feature #18D-B",
        "",
        "## Readiness",
        "",
        f"- Active rules: {summary.get('active_rule_count', 0)}",
        f"- Production candidates: {summary.get('production_candidate_count', 0)}",
        f"- Advisory candidates: {summary.get('advisory_candidate_count', 0)}",
        f"- Review-only: {summary.get('review_only_count', 0)}",
        f"- Downgraded to review-required: {summary.get('downgrade_to_review_required_count', 0)}",
        f"- Excluded: {summary.get('exclude_count', 0)}",
        "",
        "## Replay",
        "",
        f"- Active precision: {(summary.get('expanded_replay') or {}).get('active_rule_precision_on_evaluable')}",
        f"- Active coverage: {(summary.get('expanded_replay') or {}).get('active_rule_coverage_rate')}",
        f"- Active false positives: {(summary.get('expanded_replay') or {}).get('active_rule_false_positive_count')}",
        "",
        "## Recommendation",
        "",
        f"- Next: {recommendation.get('recommended_next_feature')}",
        f"- #18D-C justified: {recommendation.get('feature_18d_c_offline_mapper_service_justified')}",
        f"- Auto-apply approved: {recommendation.get('auto_apply_approved')}",
        "",
        "| Rule | QName | Readiness | Precision | Coverage |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for item in report.get("rule_readiness") or []:
        performance = item.get("performance") or {}
        lines.append(
            f"| {item.get('normalized_label_pattern')} | {item.get('target_qname')} | {item.get('readiness')} | "
            f"{performance.get('precision_on_evaluable')} | {performance.get('coverage_rate')} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_false_positive_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF-XBRL Rulebook False-Positive Analysis - Feature #18D-B",
        "",
        f"- Active false positives: {summary.get('active_false_positive_count', 0)}",
        f"- All rule false positives: {summary.get('all_rule_false_positive_count', 0)}",
        f"- Raw XML included: {summary.get('raw_xml_included')}",
        "",
        "| Sample | Label | Predicted qname | Error type | Fix |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in report.get("false_positives") or []:
        lines.append(
            f"| {item.get('sample_id')} | {item.get('pdf_label')} | {item.get('predicted_qname')} | "
            f"{item.get('error_type')} | {item.get('recommended_fix')} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_outlier_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# PDF-XBRL Rulebook Outlier Replay - Feature #18D-B",
        "",
        f"- Outlier samples: {summary.get('sample_count', 0)}",
        f"- Observations: {summary.get('pdf_observations', 0)}",
        f"- Predictions: {summary.get('replay_predictions', 0)}",
        f"- Coverage: {summary.get('coverage_rate')}",
        f"- False positives: {summary.get('false_positive_count', 0)}",
        f"- Rules remain safe on outlier: {summary.get('rules_remain_safe_on_outlier')}",
        f"- Remains excluded from training: {summary.get('should_remain_excluded_from_rulebook_training')}",
        "",
    ]
    for sample in report.get("samples") or []:
        lines.extend(
            [
                f"## {sample.get('sample_id')}",
                "",
                f"- Observations: {sample.get('pdf_observations', 0)}",
                f"- Predictions: {(sample.get('summary') or {}).get('replay_predictions', 0)}",
                f"- False positives: {(sample.get('summary') or {}).get('false_positive_count', 0)}",
                "",
            ]
        )
    return "\n".join(lines)


def render_integration_plan_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    design = report.get("design") or {}
    lines = [
        "# Deterministic-First Integration Plan - Feature #18D-B",
        "",
        f"- Recommended next feature: {summary.get('recommended_next_feature')}",
        f"- #18D-C justified: {summary.get('feature_18d_c_offline_mapper_service_justified')}",
        f"- Production integration now justified: {summary.get('production_integration_now_justified')}",
        f"- Auto-apply approved: {summary.get('auto_apply_approved')}",
        f"- confirmed_tag_id automation approved: {summary.get('confirmed_tag_id_automation_approved')}",
        "",
        "## Boundaries",
        "",
    ]
    for item in design.get("no_auto_apply_boundaries") or []:
        lines.append(f"- {item}")
    lines.extend(["", "## Future Phases", "", "| Feature | Scope | Auto-apply |", "| --- | --- | ---: |"])
    for phase in report.get("future_phases") or []:
        lines.append(f"| {phase.get('feature')} | {phase.get('scope')} | {phase.get('auto_apply_allowed')} |")
    lines.append("")
    return "\n".join(lines)


def write_hardening_reports(
    *,
    dataset_dir: str | Path,
    expanded_rulebook_path: str | Path,
    expansion_replay_path: str | Path,
    output_dir: str | Path,
    alignment_report_path: str | Path | None = "reports/pdf_xbrl_alignment_18a.json",
    source_replay_report_path: str | Path | None = "reports/pdf_xbrl_rulebook_replay_18c.json",
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    alignment_report = _read_json(alignment_report_path) if alignment_report_path and Path(alignment_report_path).exists() else {}
    source_replay_report = _read_json(source_replay_report_path) if source_replay_report_path and Path(source_replay_report_path).exists() else {}
    reports = build_hardening_reports(
        dataset_dir=dataset_dir,
        expanded_rulebook=_read_json(expanded_rulebook_path),
        expansion_replay=_read_json(expansion_replay_path),
        alignment_report=alignment_report,
        source_replay_report=source_replay_report,
    )
    paths = {
        "hardening_json": output / "pdf_xbrl_rulebook_hardening_18d_b.json",
        "hardening_md": output / "pdf_xbrl_rulebook_hardening_18d_b.md",
        "false_positive_json": output / "pdf_xbrl_rulebook_false_positive_analysis_18d_b.json",
        "false_positive_md": output / "pdf_xbrl_rulebook_false_positive_analysis_18d_b.md",
        "outlier_json": output / "pdf_xbrl_rulebook_outlier_replay_18d_b.json",
        "outlier_md": output / "pdf_xbrl_rulebook_outlier_replay_18d_b.md",
        "integration_plan_json": output / "pdf_xbrl_rulebook_integration_plan_18d_b.json",
        "integration_plan_md": output / "pdf_xbrl_rulebook_integration_plan_18d_b.md",
    }
    _write_json(paths["hardening_json"], reports["hardening"])
    _write_json(paths["false_positive_json"], reports["false_positive_analysis"])
    _write_json(paths["outlier_json"], reports["outlier_replay"])
    _write_json(paths["integration_plan_json"], reports["integration_plan"])
    paths["hardening_md"].write_text(render_hardening_markdown(reports["hardening"]), encoding="utf-8")
    paths["false_positive_md"].write_text(render_false_positive_markdown(reports["false_positive_analysis"]), encoding="utf-8")
    paths["outlier_md"].write_text(render_outlier_markdown(reports["outlier_replay"]), encoding="utf-8")
    paths["integration_plan_md"].write_text(render_integration_plan_markdown(reports["integration_plan"]), encoding="utf-8")
    return {"paths": paths, **reports}
