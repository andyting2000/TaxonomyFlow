"""Generate #17D-B hotfix-5 Supervisor calibration diagnostics.

This is local evaluation/reporting only. It consumes existing reports and does
not call any external LLM, mutate the DB, change production jobs, generate
XBRL, or run Arelle.
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

from scripts import analyze_supervisor_evaluation_17d_b_hotfix_4 as h4  # noqa: E402


DEFAULT_REVIEW_REPORT = h4.DEFAULT_REVIEW_REPORT
DEFAULT_PREDICTIONS_REPORT = h4.DEFAULT_PREDICTIONS_REPORT
DEFAULT_PLAYBOOK_REPORT = h4.DEFAULT_PLAYBOOK_REPORT

HARD_RELAXATION_ISSUES = {
    "candidate_not_supported",
    "statement_family_mismatch",
    "ambiguous_label",
    "person_or_company_name",
    "note_number",
    "missing_concept_card",
    "no_supporting_evidence",
    "invalid_supervisor_response",
    "unrepaired_invalid_supervisor_response",
}
BROAD_CATEGORY_TERMS = {
    "assets",
    "liabilities",
    "equity",
    "income",
    "expenses",
    "receivables",
    "payables",
}


def _has_total_terms(record: Mapping[str, Any]) -> bool:
    row = record.get("row") or {}
    label = h4._normalize(row.get("label") or row.get("extracted_label"))
    row_type = h4._normalize(row.get("row_type"))
    return any(term in label.split() for term in {"total", "subtotal"}) or "subtotal" in row_type or "total" in row_type


def _candidate_labels(record: Mapping[str, Any], prediction_index: Mapping[str, Mapping[str, Any]]) -> list[str]:
    prediction = prediction_index.get(h4._row_key(record.get("row") or {})) or {}
    mapper = prediction.get("fewshot_qwen_prediction") or prediction.get("qwen_prediction") or {}
    labels = []
    for candidate in mapper.get("candidate_concepts") or []:
        if isinstance(candidate, Mapping) and candidate.get("label"):
            labels.append(str(candidate.get("label")))
    return labels


def _selected_candidate_label(record: Mapping[str, Any], prediction_index: Mapping[str, Mapping[str, Any]]) -> str:
    candidate = h4._candidate_for(record, prediction_index)
    return str(candidate.get("label") or "").strip()


def _label_specificity_loss(record: Mapping[str, Any], prediction_index: Mapping[str, Mapping[str, Any]]) -> bool:
    label_tokens = h4._tokens(h4._label(record))
    candidate_tokens = h4._tokens(_selected_candidate_label(record, prediction_index))
    if not label_tokens or not candidate_tokens:
        return False
    if _has_total_terms(record):
        return False
    material = {token for token in label_tokens if token not in BROAD_CATEGORY_TERMS}
    return bool(material and len(material - candidate_tokens) >= 1 and len(candidate_tokens) <= len(label_tokens))


def _specific_candidate_exists(record: Mapping[str, Any], prediction_index: Mapping[str, Mapping[str, Any]]) -> bool:
    label = h4._label(record)
    selected = h4._selected_id(record)
    prediction = prediction_index.get(h4._row_key(record.get("row") or {})) or {}
    mapper = prediction.get("fewshot_qwen_prediction") or prediction.get("qwen_prediction") or {}
    for candidate in mapper.get("candidate_concepts") or []:
        if not isinstance(candidate, Mapping):
            continue
        ids = {str(candidate.get("template_field_id") or ""), str(candidate.get("concept_qname") or "")}
        if selected and selected in ids:
            continue
        candidate_label = str(candidate.get("label") or "")
        if h4._similarity(label, candidate_label) >= 0.92 and len(h4._tokens(candidate_label)) >= len(h4._tokens(label)):
            return True
    return False


def _do_not_confuse_warns(card: Mapping[str, Any] | None, record: Mapping[str, Any]) -> bool:
    if not card:
        return False
    label = h4._label(record)
    for item in card.get("do_not_confuse_with") or []:
        examples = " ".join(str(value) for value in (item or {}).get("example_labels") or [])
        reason = str((item or {}).get("reason") or "")
        if h4._similarity(label, examples) >= 0.75 or "broad" in reason.lower():
            return True
    notes = " ".join(str(value) for value in card.get("guardrail_notes") or [])
    return "do not choose" in notes.lower() and "label" in notes.lower()


def classify_broad_substitute_calibrated(
    record: Mapping[str, Any],
    *,
    prediction_index: Mapping[str, Mapping[str, Any]],
    card_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    before = h4.classify_broad_substitute(record, prediction_index=prediction_index, card_index=card_index)
    selected = h4._selected_id(record)
    card = card_index.get(selected)
    candidate = h4._candidate_for(record, prediction_index)
    alias = h4._alias_evidence(record, card, candidate)
    statement_match = h4._statement_matches(record, card, candidate)
    issues = h4._issue_types(record.get("supervisor_review") or {})
    score = record.get("local_scoring") or {}
    total_line = _has_total_terms(record)
    same_family = bool(h4._concept_family(h4._correct_id(record), card_index.get(h4._correct_id(record))) == h4._concept_family(selected, card))
    candidate_support = bool(candidate) or bool(card)
    specific_loss = _label_specificity_loss(record, prediction_index)
    clearer_specific = _specific_candidate_exists(record, prediction_index)
    confuse_warns = _do_not_confuse_warns(card, record)

    if score.get("mapper_wrong") or "candidate_not_supported" in issues or "statement_family_mismatch" in issues:
        classification = "true_broad_substitute_risk"
    elif total_line and statement_match and same_family and candidate_support and alias["exact_or_near_alias"]:
        selected_label_norm = h4._normalize(_selected_candidate_label(record, prediction_index) or (card or {}).get("canonical_label"))
        if h4._normalize(h4._label(record)) == selected_label_norm:
            classification = "exact_total_concept_match"
        elif h4._similarity(h4._label(record), selected_label_norm) >= 0.88:
            classification = "acceptable_total_or_subtotal_line"
        else:
            classification = "same_family_total_label"
    elif score.get("mapper_correct") and alias["exact_or_near_alias"] and statement_match and h4._strong_concept_card(card):
        classification = "over_triggered_broad_substitute"
    elif (specific_loss or clearer_specific or confuse_warns) and not alias["exact_or_near_alias"]:
        classification = "true_broad_substitute_risk"
    else:
        classification = "cannot_determine"

    return {
        **before,
        "before_classification": before["classification"],
        "calibrated_classification": classification,
        "is_total_or_subtotal_line": total_line,
        "same_concept_family": same_family,
        "candidate_evidence_supports_selected": candidate_support,
        "label_specificity_loss": specific_loss,
        "clearer_specific_candidate_exists": clearer_specific,
        "do_not_confuse_warns": confuse_warns,
    }


def classify_safe_accept_relaxation(
    record: Mapping[str, Any],
    *,
    prediction_index: Mapping[str, Mapping[str, Any]],
    card_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    selected = h4._selected_id(record)
    card = card_index.get(selected)
    candidate = h4._candidate_for(record, prediction_index)
    alias = h4._alias_evidence(record, card, candidate)
    issues = h4._issue_types(record.get("supervisor_review") or {})
    hard_issues = sorted(issues & HARD_RELAXATION_ISSUES)
    blockers = h4._relaxation_blockers(record, prediction_index=prediction_index, card_index=card_index)
    broad = classify_broad_substitute_calibrated(record, prediction_index=prediction_index, card_index=card_index)
    labels: list[str] = []
    if hard_issues or blockers:
        labels.append("not_relaxable_due_to_hard_issue")
    else:
        if alias["exact_or_near_alias"]:
            labels.append("relaxation_candidate_exact_alias")
        if _has_total_terms(record) and broad["calibrated_classification"] in {
            "acceptable_total_or_subtotal_line",
            "same_family_total_label",
            "exact_total_concept_match",
        }:
            labels.append("relaxation_candidate_total_line_same_family")
        if h4._strong_concept_card(card):
            labels.append("relaxation_candidate_strong_concept_card")
        if broad["calibrated_classification"] == "over_triggered_broad_substitute" or (
            issues <= {"broad_substitute"} and broad["calibrated_classification"] != "true_broad_substitute_risk"
        ):
            labels.append("relaxation_candidate_blocked_only_by_overtriggered_broad_substitute")
    return {
        "row": record.get("row") or {},
        "selected_concept_qname": selected or None,
        "correct_concept_qname": h4._correct_id(record) or None,
        "relaxation_labels": sorted(set(labels or ["not_relaxable_due_to_hard_issue"])),
        "hard_issues": hard_issues,
        "relaxation_blockers": blockers,
        "broad_substitute_calibration": broad["calibrated_classification"],
        "alias_evidence": alias,
        "statement_family_matches": h4._statement_matches(record, card, candidate),
        "concept_card_available": bool(card),
        "candidate_evidence_available": bool(candidate),
    }


def _is_numeric_fact_like(record: Mapping[str, Any]) -> bool:
    row = record.get("row") or {}
    row_type = h4._normalize(row.get("row_type"))
    value = str(row.get("value") or row.get("extracted_value") or "").strip()
    if "numeric" in row_type or "subtotal" in row_type or "total" in row_type:
        return True
    return any(char.isdigit() for char in value)


def _plausible_candidate_count(record: Mapping[str, Any], prediction_index: Mapping[str, Mapping[str, Any]]) -> int:
    labels = _candidate_labels(record, prediction_index)
    label = h4._label(record)
    return sum(1 for candidate_label in labels if h4._similarity(label, candidate_label) >= 0.55)


def classify_omission_calibrated(
    record: Mapping[str, Any],
    *,
    prediction_index: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    outcome = h4.classify_mapper_outcome(record)
    review = record.get("supervisor_review") or {}
    decision = str(review.get("review_decision") or "")
    omission = outcome in {"mapper_rejected_but_gold_exists", "mapper_no_prediction_but_gold_exists"}
    plausible_candidates = _plausible_candidate_count(record, prediction_index)
    numeric_fact_like = _is_numeric_fact_like(record)
    if outcome == "mapper_correctly_rejected_non_fact":
        calibrated = "mapper_rejected_non_fact_correctly"
    else:
        calibrated = outcome
    return {
        "row": record.get("row") or {},
        "mapper_selection": record.get("mapper_selection") or {},
        "supervisor_review": review,
        "local_scoring": record.get("local_scoring") or {},
        "mapper_outcome": calibrated,
        "is_mapper_omission": omission,
        "numeric_fact_like": numeric_fact_like,
        "plausible_candidate_count": plausible_candidates,
        "supervisor_agreed_with_omission": bool(omission and decision == "agree"),
        "supervisor_caught_omission": bool(omission and decision in {"disagree", "needs_human_review"}),
        "recommended_supervisor_decision": (
            "needs_human_review_or_request_better_candidate"
            if omission and numeric_fact_like and plausible_candidates
            else "current_decision_acceptable_for_evaluation"
        ),
    }


def _case_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "row": record.get("row") or {},
        "mapper_selection": record.get("mapper_selection") or {},
        "supervisor_review": record.get("supervisor_review") or {},
        "local_scoring": record.get("local_scoring") or {},
    }


def build_calibration_reports(
    *,
    review_report: Mapping[str, Any],
    predictions: Mapping[str, Any],
    playbook: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    records = [record for record in review_report.get("review_records") or [] if isinstance(record, Mapping)]
    prediction_index = h4._prediction_rows(predictions)
    card_index = h4._concept_cards(playbook)
    metadata = {
        "feature": "17D-B-hotfix-5",
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
        "production_integration_recommendation": "defer_17d_c_until_calibrated_guardrails_are_reviewed_and_optionally_live_retested",
    }

    broad_records = [
        record for record in records if "broad_substitute" in h4._issue_types(record.get("supervisor_review") or {})
    ]
    broad_cases = [
        classify_broad_substitute_calibrated(record, prediction_index=prediction_index, card_index=card_index)
        for record in broad_records
    ]
    broad_before = Counter(case["before_classification"] for case in broad_cases)
    broad_after = Counter(case["calibrated_classification"] for case in broad_cases)

    omission_cases = [classify_omission_calibrated(record, prediction_index=prediction_index) for record in records]
    omission_outcomes = Counter(case["mapper_outcome"] for case in omission_cases)
    omissions = [case for case in omission_cases if case["is_mapper_omission"]]
    agreed_omissions = [case for case in omissions if case["supervisor_agreed_with_omission"]]
    caught_omissions = [case for case in omissions if case["supervisor_caught_omission"]]

    blocked_correct = [
        record for record in records if (record.get("local_scoring") or {}).get("correct_mapping_unnecessarily_blocked")
    ]
    relaxation_cases = [
        classify_safe_accept_relaxation(record, prediction_index=prediction_index, card_index=card_index)
        for record in blocked_correct
    ]
    label_counts: Counter[str] = Counter()
    for case in relaxation_cases:
        label_counts.update(case.get("relaxation_labels") or [])
    hard_blocked = [case for case in relaxation_cases if "not_relaxable_due_to_hard_issue" in case.get("relaxation_labels", [])]
    relaxable = [case for case in relaxation_cases if "not_relaxable_due_to_hard_issue" not in case.get("relaxation_labels", [])]

    broad_report = {
        "run_metadata": metadata,
        "metrics": {
            "broad_substitute_total": len(broad_cases),
            "before_classification_counts": dict(sorted(broad_before.items())),
            "calibrated_classification_counts": dict(sorted(broad_after.items())),
            "true_broad_substitute_risk": broad_after["true_broad_substitute_risk"],
            "over_triggered_broad_substitute": broad_after["over_triggered_broad_substitute"],
            "acceptable_total_or_subtotal_line": broad_after["acceptable_total_or_subtotal_line"],
            "same_family_total_label": broad_after["same_family_total_label"],
            "exact_total_concept_match": broad_after["exact_total_concept_match"],
            "cannot_determine": broad_after["cannot_determine"],
        },
        "before_after_classification": broad_cases,
        "over_triggered_broad_substitute_examples": [
            case for case in broad_cases if case["calibrated_classification"] == "over_triggered_broad_substitute"
        ][:10],
        "true_broad_substitute_risk_examples": [
            case for case in broad_cases if case["calibrated_classification"] == "true_broad_substitute_risk"
        ][:10],
        "acceptable_total_or_subtotal_examples": [
            case
            for case in broad_cases
            if case["calibrated_classification"]
            in {"acceptable_total_or_subtotal_line", "same_family_total_label", "exact_total_concept_match"}
        ][:10],
        "recommendation": "Use calibrated broad_substitute categories in the next live limited rerun; do not remove the issue type.",
    }

    omission_report = {
        "run_metadata": metadata,
        "metrics": {
            "total_reviewed": len(records),
            "mapper_omission_count": len(omissions),
            "mapper_outcome_counts": dict(sorted(omission_outcomes.items())),
            "supervisor_agreed_with_omission_count": len(agreed_omissions),
            "supervisor_caught_omission_count": len(caught_omissions),
            "numeric_fact_like_omission_count": sum(1 for case in omissions if case["numeric_fact_like"]),
            "omissions_with_plausible_candidates_count": sum(1 for case in omissions if case["plausible_candidate_count"] > 0),
        },
        "mapper_omission_examples": omissions[:10],
        "supervisor_agreed_with_omission_examples": agreed_omissions[:10],
        "supervisor_caught_omission_examples": caught_omissions[:10],
        "recommendation": "Prompt future live Supervisor runs to treat rejected/no-predicted numeric fact-like rows with plausible candidates as human-review/request-better-candidate cases.",
    }

    relaxation_report = {
        "run_metadata": metadata,
        "metrics": {
            "blocked_correct_mapping_count": len(blocked_correct),
            "relaxable_candidates": len(relaxable),
            "blocked_by_hard_issue": len(hard_blocked),
            "relaxation_label_counts": dict(sorted(label_counts.items())),
        },
        "relaxable_candidates_by_reason": {
            label: [case for case in relaxation_cases if label in case.get("relaxation_labels", [])][:10]
            for label in sorted(label_counts)
            if label != "not_relaxable_due_to_hard_issue"
        },
        "blocked_by_hard_issue_examples": hard_blocked[:10],
        "recommended_deterministic_relaxation_rules": [
            "Never relax safe_to_accept when hard issues exist: candidate_not_supported, statement_family_mismatch, ambiguous_label, person_or_company_name, note_number, missing_concept_card, or no_supporting_evidence.",
            "Consider future safe acceptance only when mapper prediction is locally correct in evaluation, selected concept equals local gold, statement family matches, candidate evidence supports the selected concept, and a strong concept card exists.",
            "Treat total/subtotal rows separately: total-line same-family matches may be relaxable, but specific labels mapped to broad categories remain true broad risk.",
            "Keep all production use suggestion-only until a separate approved integration feature and live retest.",
        ],
        "recommendation": "A bounded live rerun is useful after prompt calibration to measure whether omissions and broad_substitute over-triggering decrease without introducing unsafe safe_accept.",
    }
    return {
        "broad": broad_report,
        "omission": omission_report,
        "safe_accept": relaxation_report,
    }


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(lines)


def _metrics_markdown(title: str, report: Mapping[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    rows = [[key, json.dumps(value, sort_keys=True) if isinstance(value, dict) else value] for key, value in metrics.items()]
    return "\n\n".join([title, _markdown_table(["Metric", "Value"], rows), "## Recommendation", str(report.get("recommendation") or "")]) + "\n"


def write_calibration_reports(
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
    reports = build_calibration_reports(
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
        "broad_json": reports_root / "supervisor_broad_substitute_calibration_17d_b_hotfix_5.json",
        "broad_md": reports_root / "supervisor_broad_substitute_calibration_17d_b_hotfix_5.md",
        "omission_json": reports_root / "supervisor_omission_calibration_17d_b_hotfix_5.json",
        "omission_md": reports_root / "supervisor_omission_calibration_17d_b_hotfix_5.md",
        "safe_accept_json": reports_root / "supervisor_safe_accept_calibration_17d_b_hotfix_5.json",
        "safe_accept_md": reports_root / "supervisor_safe_accept_calibration_17d_b_hotfix_5.md",
    }
    h4._write_json(paths["broad_json"], reports["broad"])
    paths["broad_md"].write_text(_metrics_markdown("# Supervisor Broad Substitute Calibration #17D-B Hotfix 5", reports["broad"]), encoding="utf-8")
    h4._write_json(paths["omission_json"], reports["omission"])
    paths["omission_md"].write_text(_metrics_markdown("# Supervisor Omission Calibration #17D-B Hotfix 5", reports["omission"]), encoding="utf-8")
    h4._write_json(paths["safe_accept_json"], reports["safe_accept"])
    paths["safe_accept_md"].write_text(_metrics_markdown("# Supervisor Safe Accept Calibration #17D-B Hotfix 5", reports["safe_accept"]), encoding="utf-8")
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate local #17D-B hotfix-5 Supervisor calibration reports.")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--review-report", default=str(DEFAULT_REVIEW_REPORT))
    parser.add_argument("--predictions-report", default=str(DEFAULT_PREDICTIONS_REPORT))
    parser.add_argument("--playbook-report", default=str(DEFAULT_PLAYBOOK_REPORT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = write_calibration_reports(
        reports_dir=args.reports_dir,
        review_report_path=args.review_report,
        predictions_report_path=args.predictions_report,
        playbook_report_path=args.playbook_report,
    )
    print("supervisor_17d_b_hotfix_5_reports", json.dumps({key: str(value) for key, value in paths.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
