"""Generate #17D-B hotfix-6 safe-accept threshold calibration reports.

This is an offline simulation only. It reads existing local reports and does
not call an external LLM, mutate the DB, change production jobs, generate XBRL,
or run Arelle.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import analyze_supervisor_calibration_17d_b_hotfix_5 as h5  # noqa: E402
from scripts import analyze_supervisor_evaluation_17d_b_hotfix_4 as h4  # noqa: E402


DEFAULT_REVIEW_REPORT = h4.DEFAULT_REVIEW_REPORT
DEFAULT_PREDICTIONS_REPORT = h4.DEFAULT_PREDICTIONS_REPORT
DEFAULT_PLAYBOOK_REPORT = h4.DEFAULT_PLAYBOOK_REPORT

HARD_ISSUES = {
    "ambiguous_label",
    "candidate_not_supported",
    "statement_family_mismatch",
    "missing_concept_card",
    "person_or_company_name",
    "note_number",
    "no_supporting_evidence",
    "invalid_supervisor_response",
    "unrepaired_invalid_supervisor_response",
}
CASH_FLOW_TERMS = {
    "cash",
    "equivalents",
    "operating",
    "investing",
    "financing",
    "increase",
    "decrease",
    "net",
}


def _is_cash_flow_same_family(
    record: Mapping[str, Any],
    *,
    prediction_index: Mapping[str, Mapping[str, Any]],
    card_index: Mapping[str, Mapping[str, Any]],
) -> bool:
    if h4._statement_type(record) != "Statement of Cash Flows":
        return False
    selected = h4._selected_id(record)
    card = card_index.get(selected)
    candidate = h4._candidate_for(record, prediction_index)
    family = h4._concept_family(selected, card)
    label_text = h4._normalize(" ".join([h4._label(record), str((candidate or {}).get("label") or ""), str((card or {}).get("canonical_label") or "")]))
    label_tokens = set(label_text.split())
    return bool(
        (family in {"cash", "cash_flow"} or "cash" in selected.lower())
        and (label_tokens & CASH_FLOW_TERMS)
        and h4._statement_matches(record, card, candidate)
    )


def _is_non_fact_like(record: Mapping[str, Any]) -> bool:
    return h4._is_non_fact_rejection(record)


def _guardrail_evidence(
    record: Mapping[str, Any],
    *,
    prediction_index: Mapping[str, Mapping[str, Any]],
    card_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    selected = h4._selected_id(record)
    correct = h4._correct_id(record)
    card = card_index.get(selected)
    candidate = h4._candidate_for(record, prediction_index)
    alias = h4._alias_evidence(record, card, candidate)
    issues = h4._issue_types(record.get("supervisor_review") or {})
    broad = h5.classify_broad_substitute_calibrated(record, prediction_index=prediction_index, card_index=card_index)
    hard_issues = set(issues & HARD_ISSUES)
    if broad["calibrated_classification"] == "true_broad_substitute_risk":
        hard_issues.add("broad_substitute_true_risk")
    outcome = h4.classify_mapper_outcome(record)
    return {
        "mapper_correct": bool((record.get("local_scoring") or {}).get("mapper_correct")),
        "mapper_wrong": bool((record.get("local_scoring") or {}).get("mapper_wrong")),
        "selected_equals_gold": bool(selected and selected == correct),
        "statement_family_matches": h4._statement_matches(record, card, candidate),
        "candidate_evidence_available": bool(candidate),
        "concept_card_available": bool(card),
        "strong_concept_card": h4._strong_concept_card(card),
        "exact_or_near_alias": bool(alias["exact_or_near_alias"]),
        "alias_similarity": alias["best_alias_similarity"],
        "alias_label": alias["best_alias_label"],
        "hard_issues": sorted(hard_issues),
        "non_fact_like": _is_non_fact_like(record),
        "mapper_omission": outcome in {"mapper_rejected_but_gold_exists", "mapper_no_prediction_but_gold_exists"},
        "cash_flow_same_family": _is_cash_flow_same_family(record, prediction_index=prediction_index, card_index=card_index),
        "broad_substitute_calibration": broad["calibrated_classification"],
        "low_mapper_confidence_reason": "mapper_confidence_below_safe_threshold"
        in h4._normalization_reasons(record.get("supervisor_review") or {}),
        "selected_concept_qname": selected or None,
        "correct_concept_qname": correct or None,
    }


def classify_safe_accept_threshold(
    record: Mapping[str, Any],
    *,
    prediction_index: Mapping[str, Mapping[str, Any]],
    card_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    review = record.get("supervisor_review") or {}
    original_safe = bool(review.get("safe_to_accept"))
    evidence = _guardrail_evidence(record, prediction_index=prediction_index, card_index=card_index)
    failed: list[str] = []
    if not evidence["mapper_correct"]:
        failed.append("mapper_prediction_not_locally_correct")
    if evidence["mapper_wrong"]:
        failed.append("mapper_prediction_wrong")
    if not evidence["selected_equals_gold"]:
        failed.append("selected_concept_does_not_equal_local_gold")
    if not evidence["statement_family_matches"]:
        failed.append("statement_family_not_matched")
    if not evidence["candidate_evidence_available"]:
        failed.append("candidate_evidence_missing")
    if not evidence["concept_card_available"]:
        failed.append("concept_card_missing")
    if not evidence["strong_concept_card"]:
        failed.append("concept_card_not_strong")
    if not evidence["exact_or_near_alias"]:
        failed.append("exact_or_near_alias_missing")
    if evidence["hard_issues"]:
        failed.extend(evidence["hard_issues"])
    if evidence["non_fact_like"]:
        failed.append("non_fact_or_discussion_header_row")
    if evidence["mapper_omission"]:
        failed.append("mapper_omission_not_relaxable")

    passed = not failed
    labels: list[str] = []
    primary = "not_relaxable"
    if evidence["hard_issues"]:
        primary = "blocked_by_hard_issue"
    elif evidence["non_fact_like"]:
        primary = "blocked_by_ambiguous_or_non_fact_label"
    elif not evidence["statement_family_matches"] or not evidence["candidate_evidence_available"]:
        primary = "blocked_by_statement_or_candidate_mismatch"
    elif not evidence["concept_card_available"] or not evidence["exact_or_near_alias"]:
        primary = "blocked_by_missing_evidence"
    elif passed:
        if evidence["cash_flow_same_family"]:
            labels.append("relaxable_cash_flow_same_family")
        if evidence["alias_similarity"] >= 0.98:
            labels.append("relaxable_exact_alias_strong_evidence")
        else:
            labels.append("relaxable_near_alias_strong_evidence")
        if evidence["low_mapper_confidence_reason"]:
            labels.append("blocked_by_low_mapper_confidence_only")
        primary = labels[0]

    calibrated_safe = bool(original_safe or (passed and evidence["mapper_correct"]))
    return {
        "row": record.get("row") or {},
        "mapper_selection": record.get("mapper_selection") or {},
        "supervisor_review": review,
        "local_scoring": record.get("local_scoring") or {},
        "original_safe_to_accept": original_safe,
        "calibrated_safe_to_accept": calibrated_safe,
        "classification": primary,
        "relaxation_labels": sorted(set(labels)),
        "calibration_reason": (
            "strict_local_evidence_passed_threshold_simulation"
            if calibrated_safe and not original_safe
            else "original_safe_to_accept_retained"
            if original_safe
            else "guardrails_failed"
        ),
        "calibration_guardrails_passed": [
            key
            for key in [
                "mapper_correct",
                "selected_equals_gold",
                "statement_family_matches",
                "candidate_evidence_available",
                "concept_card_available",
                "strong_concept_card",
                "exact_or_near_alias",
            ]
            if evidence.get(key)
        ],
        "calibration_guardrails_failed": sorted(set(failed)),
        "evidence": evidence,
    }


def build_threshold_reports(
    *,
    review_report: Mapping[str, Any],
    predictions: Mapping[str, Any],
    playbook: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    records = [record for record in review_report.get("review_records") or [] if isinstance(record, Mapping)]
    prediction_index = h4._prediction_rows(predictions)
    card_index = h4._concept_cards(playbook)
    cases = [
        classify_safe_accept_threshold(record, prediction_index=prediction_index, card_index=card_index)
        for record in records
    ]
    metadata = {
        "feature": "17D-B-hotfix-6",
        "generated_at": h4._utc_now(),
        "source_review_feature": (review_report.get("run_metadata") or {}).get("feature"),
        "source_review_mode": (review_report.get("run_metadata") or {}).get("mode"),
        "external_llm_called_by_this_script": False,
        "auditor_xml_sent_externally": False,
        "parsed_xml_facts_sent_externally": False,
        "target_gold_answers_sent_externally": False,
        "evaluation_labels_sent_externally": False,
        "database_mutated": False,
        "production_job_mutated": False,
        "confirmed_tag_id_automated": False,
        "xbrl_generated": False,
        "arelle_run": False,
        "production_integration_ready": False,
        "production_integration_recommendation": "defer_17d_c_until_threshold_simulation_is_reviewed_and_live_retested",
    }

    original_safe = [case for case in cases if case["original_safe_to_accept"]]
    calibrated_safe = [case for case in cases if case["calibrated_safe_to_accept"]]
    additional = [case for case in cases if case["calibrated_safe_to_accept"] and not case["original_safe_to_accept"]]
    blocked_correct_before = [
        case for case in cases if (case.get("local_scoring") or {}).get("correct_mapping_unnecessarily_blocked")
    ]
    blocked_correct_after = [
        case
        for case in cases
        if (case.get("local_scoring") or {}).get("mapper_correct") and not case["calibrated_safe_to_accept"]
    ]
    calibrated_false = [case for case in calibrated_safe if not (case.get("local_scoring") or {}).get("mapper_correct")]
    classification_counts = Counter(case["classification"] for case in cases)
    label_counts: Counter[str] = Counter()
    for case in cases:
        label_counts.update(case.get("relaxation_labels") or [])

    metrics = {
        "total_reviewed": len(cases),
        "original_safe_to_accept_count": len(original_safe),
        "calibrated_safe_to_accept_count": len(calibrated_safe),
        "calibrated_safe_to_accept_accuracy": round(
            sum(1 for case in calibrated_safe if (case.get("local_scoring") or {}).get("mapper_correct")) / len(calibrated_safe),
            4,
        )
        if calibrated_safe
        else None,
        "calibrated_false_safe_accept_count": len(calibrated_false),
        "additional_safe_accept_count": len(additional),
        "additional_safe_accept_correct_count": sum(
            1 for case in additional if (case.get("local_scoring") or {}).get("mapper_correct")
        ),
        "blocked_correct_mapping_count_before": len(blocked_correct_before),
        "blocked_correct_mapping_count_after_simulation": len(blocked_correct_after),
        "blocked_correct_reduction": max(0, len(blocked_correct_before) - len(blocked_correct_after)),
        "hard_issue_blocked_count": classification_counts["blocked_by_hard_issue"],
        "low_confidence_only_relaxed_count": sum(
            1 for case in additional if "blocked_by_low_mapper_confidence_only" in case.get("relaxation_labels", [])
        ),
        "cash_flow_relaxed_count": sum(
            1 for case in additional if "relaxable_cash_flow_same_family" in case.get("relaxation_labels", [])
        ),
        "classification_counts": dict(sorted(classification_counts.items())),
        "relaxation_label_counts": dict(sorted(label_counts.items())),
    }

    threshold_report = {
        "run_metadata": metadata,
        "metrics": metrics,
        "simulated_cases": cases,
        "relaxable_candidates_by_reason": {
            label: [case for case in cases if label in case.get("relaxation_labels", [])][:10]
            for label in sorted(label_counts)
        },
        "hard_issue_blocked_cases": [
            case for case in cases if case["classification"] == "blocked_by_hard_issue"
        ][:10],
        "non_relaxable_cases": [
            case for case in cases if not case["calibrated_safe_to_accept"]
        ][:10],
        "recommendation": "Run a bounded live Supervisor retest before any #17D-C production integration; this report is simulation-only.",
    }

    cash_flow_cases = [case for case in cases if case["evidence"]["cash_flow_same_family"]]
    cash_flow_relaxed = [case for case in cash_flow_cases if case["calibrated_safe_to_accept"] and not case["original_safe_to_accept"]]
    cash_flow_false = [case for case in cash_flow_cases if case["calibrated_safe_to_accept"] and not (case.get("local_scoring") or {}).get("mapper_correct")]
    cash_flow_report = {
        "run_metadata": metadata,
        "metrics": {
            "cash_flow_candidate_count": len(cash_flow_cases),
            "cash_flow_relaxable_count": len(cash_flow_relaxed),
            "cash_flow_relaxed_correct_count": sum(
                1 for case in cash_flow_relaxed if (case.get("local_scoring") or {}).get("mapper_correct")
            ),
            "cash_flow_false_safe_accept_count": len(cash_flow_false),
        },
        "cash_flow_relaxable_cases": cash_flow_relaxed,
        "cash_flow_non_relaxable_cases": [
            case for case in cash_flow_cases if not case["calibrated_safe_to_accept"]
        ],
        "recommendation": "Cash-flow relaxation should remain evaluation-only until a bounded live rerun confirms zero false safe accepts.",
    }
    return {"threshold": threshold_report, "cash_flow": cash_flow_report}


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(lines)


def _metrics_markdown(title: str, report: Mapping[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    rows = [[key, json.dumps(value, sort_keys=True) if isinstance(value, dict) else value] for key, value in metrics.items()]
    return "\n\n".join([title, _markdown_table(["Metric", "Value"], rows), "## Recommendation", str(report.get("recommendation") or "")]) + "\n"


def write_threshold_reports(
    *,
    reports_dir: str | Path = PROJECT_ROOT / "reports",
    review_report_path: str | Path = DEFAULT_REVIEW_REPORT,
    predictions_report_path: str | Path = DEFAULT_PREDICTIONS_REPORT,
    playbook_report_path: str | Path = DEFAULT_PLAYBOOK_REPORT,
) -> dict[str, Path]:
    reports_root = h4._resolve(reports_dir)
    review_path = h4._resolve(review_report_path)
    predictions_path = h4._resolve(predictions_report_path)
    playbook_path = h4._resolve(playbook_report_path)
    reports = build_threshold_reports(
        review_report=h4._read_json(review_path),
        predictions=h4._read_json(predictions_path),
        playbook=h4._read_json(playbook_path),
    )
    source_reports = {
        "review": h4._display(review_path),
        "predictions": h4._display(predictions_path),
        "concept_playbook": h4._display(playbook_path),
    }
    for report in reports.values():
        report["run_metadata"]["source_reports"] = source_reports

    paths = {
        "threshold_json": reports_root / "supervisor_safe_accept_threshold_calibration_17d_b_hotfix_6.json",
        "threshold_md": reports_root / "supervisor_safe_accept_threshold_calibration_17d_b_hotfix_6.md",
        "cash_flow_json": reports_root / "supervisor_cash_flow_relaxation_analysis_17d_b_hotfix_6.json",
        "cash_flow_md": reports_root / "supervisor_cash_flow_relaxation_analysis_17d_b_hotfix_6.md",
    }
    h4._write_json(paths["threshold_json"], reports["threshold"])
    paths["threshold_md"].write_text(
        _metrics_markdown("# Supervisor Safe Accept Threshold Calibration #17D-B Hotfix 6", reports["threshold"]),
        encoding="utf-8",
    )
    h4._write_json(paths["cash_flow_json"], reports["cash_flow"])
    paths["cash_flow_md"].write_text(
        _metrics_markdown("# Supervisor Cash Flow Relaxation Analysis #17D-B Hotfix 6", reports["cash_flow"]),
        encoding="utf-8",
    )
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate local #17D-B hotfix-6 safe-accept threshold reports.")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--review-report", default=str(DEFAULT_REVIEW_REPORT))
    parser.add_argument("--predictions-report", default=str(DEFAULT_PREDICTIONS_REPORT))
    parser.add_argument("--playbook-report", default=str(DEFAULT_PLAYBOOK_REPORT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = write_threshold_reports(
        reports_dir=args.reports_dir,
        review_report_path=args.review_report,
        predictions_report_path=args.predictions_report,
        playbook_report_path=args.playbook_report,
    )
    print("supervisor_17d_b_hotfix_6_reports", json.dumps({key: str(value) for key, value in paths.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
