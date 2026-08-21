"""Recover low-risk #18E-D overblocked candidates with strict evidence gates."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.pdf_xbrl_rulebook_mapper import (
    apply_overblocked_candidate_recovery,
    overblocked_recovery_key,
)
from services.pdf_xbrl_rulebook_replay import FALSE_POSITIVE_STATUSES, GOOD_STATUSES
from services.tightened_mapper_evaluation import (
    evaluate_mapper_records,
    is_false_positive_status,
    is_good_status,
    load_local_evaluation_evidence,
    metrics_for_records,
    read_json,
    safe_rate,
    sanitize_report_value,
    write_json,
)


SAFETY = {
    "external_llm_called": False,
    "external_provider_called": False,
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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record.get("sample_id") or ""), str(record.get("pdf_row_id") or record.get("row_id") or "")


def _analysis_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("sample_id") or ""),
        str(row.get("pdf_row_id") or row.get("row_id") or ""),
        str(row.get("target_qname") or ""),
        str(row.get("blocked_source") or ""),
    )


def _candidate_key_from_decision(decision: Mapping[str, Any]) -> tuple[str, str, str, str]:
    key = decision.get("candidate_key")
    if isinstance(key, Mapping):
        return (
            str(key.get("sample_id") or ""),
            str(key.get("pdf_row_id") or ""),
            str(key.get("target_qname") or ""),
            str(key.get("blocked_source") or ""),
        )
    return "", "", "", ""


def _blocked_candidate_items(record: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    output = []
    for source, field in (("dictionary", "blocked_dictionary_candidate"), ("row_order", "blocked_row_order_candidate")):
        candidate = record.get(field)
        if isinstance(candidate, Mapping) and candidate.get("target_qname"):
            output.append((source, candidate))
    return output


def allowed_recovery_keys(blocked_analysis: Mapping[str, Any]) -> set[tuple[str, str, str, str]]:
    return {
        _analysis_key(row)
        for row in blocked_analysis.get("blocked_candidates") or []
        if row.get("blocked_candidate_classification") == "overblocked_true_positive"
    }


def _no_match_count(records: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for record in records if not record.get("predicted_qname"))


def _summary_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = metrics_for_records(records)
    metrics["no_match_count"] = _no_match_count(records)
    metrics["false_positives"] = metrics.get("false_positive_count")
    return metrics


def _safe_record(record: Mapping[str, Any]) -> dict[str, Any]:
    context = record.get("row_context") if isinstance(record.get("row_context"), Mapping) else {}
    return sanitize_report_value(
        {
            "sample_id": record.get("sample_id"),
            "company_name": record.get("company_name"),
            "pdf_row_id": record.get("pdf_row_id"),
            "pdf_label": record.get("pdf_label"),
            "normalized_label": record.get("normalized_label") or canonical_label(record.get("pdf_label")),
            "pdf_value": record.get("pdf_value"),
            "pdf_period": record.get("pdf_period"),
            "statement_family": context.get("statement_family"),
            "section_block": context.get("section_block"),
            "row_role": context.get("row_role"),
            "predicted_qname": record.get("predicted_qname"),
            "predicted_concept_label": record.get("predicted_concept_label"),
            "candidate_generation_method": record.get("candidate_generation_method"),
            "confidence_bucket": record.get("confidence_bucket"),
            "evaluation_status": record.get("evaluation_status"),
            "blocking_reasons": record.get("blocking_reasons") or [],
            "blocked_candidate_reasons": record.get("blocked_candidate_reasons") or [],
            "safe_for_auto_apply": False,
            "requires_human_review": record.get("requires_human_review") is not False,
        }
    )


def _decision_report_row(
    *,
    analysis_row: Mapping[str, Any],
    decision: Mapping[str, Any] | None,
    post_record: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source_classification = str(analysis_row.get("blocked_candidate_classification") or "not_evaluable")
    recovered = bool(decision and decision.get("can_recover"))
    if recovered:
        classification = "recovered_low_risk"
    elif source_classification == "correctly_blocked_false_positive":
        classification = "still_blocked_correctly"
    elif source_classification == "ambiguous":
        classification = "still_blocked_ambiguous"
    elif source_classification == "not_evaluable":
        classification = "not_evaluable"
    elif decision and decision.get("classification") == "not_recoverable":
        classification = "not_recoverable"
    else:
        classification = "still_blocked_high_risk"

    evaluation_status = analysis_row.get("evaluation_status") or (post_record or {}).get("evaluation_status")
    return sanitize_report_value(
        {
            "classification": classification,
            "source_blocked_candidate_classification": source_classification,
            "sample_id": analysis_row.get("sample_id"),
            "pdf_row_id": analysis_row.get("pdf_row_id"),
            "pdf_label": analysis_row.get("pdf_label"),
            "normalized_label": analysis_row.get("normalized_label"),
            "target_qname": analysis_row.get("target_qname"),
            "blocked_source": analysis_row.get("blocked_source"),
            "statement_family": analysis_row.get("statement_family"),
            "label_family": analysis_row.get("label_family"),
            "row_role": analysis_row.get("row_role"),
            "evaluation_status": evaluation_status,
            "risk_level": (decision or {}).get("risk_level") or analysis_row.get("risk_level"),
            "recovery_reason": (decision or {}).get("recovery_reason"),
            "evidence_conditions_met": (decision or {}).get("evidence_conditions_met") or [],
            "evidence_conditions_failed": (decision or {}).get("evidence_conditions_failed") or [],
            "previous_blocking_reason": (decision or {}).get("previous_blocking_reason") or analysis_row.get("blocking_reasons") or [],
            "safe_for_auto_apply": False,
            "requires_human_review": True,
        }
    )


def _group_counts(rows: Sequence[Mapping[str, Any]], fields: Sequence[str], *, limit: int = 50) -> list[dict[str, Any]]:
    counter = Counter(tuple(str(row.get(field) or "") for field in fields) for row in rows)
    output = []
    for key, count in counter.most_common(limit):
        item = {field: value for field, value in zip(fields, key)}
        item["count"] = count
        output.append(item)
    return output


def _recommend_next(summary: Mapping[str, Any]) -> dict[str, Any]:
    recovered_false = int(summary.get("recovered_false_positive_count") or 0)
    pre_coverage = summary.get("pre_recovery", {}).get("touched_coverage_rate")
    post_coverage = summary.get("post_recovery", {}).get("touched_coverage_rate")
    pre_precision = summary.get("pre_recovery", {}).get("precision_on_evaluable")
    post_precision = summary.get("post_recovery", {}).get("precision_on_evaluable")
    coverage_improved = post_coverage is not None and pre_coverage is not None and post_coverage > pre_coverage
    precision_improved = post_precision is not None and pre_precision is not None and post_precision > pre_precision

    if recovered_false:
        feature = "Feature #18E-D-hotfix-2 - revert risky recovery families"
        reason = "Recovery introduced false positives and should be reverted or tightened."
    elif coverage_improved or precision_improved:
        feature = "Feature #18E-D-2 - Re-evaluate tightened mapper after recovery and update readiness matrix"
        reason = "Recovery improved measured coverage or precision without recovered false positives."
    else:
        feature = "Feature #18E-B-3 - Add safer company-format template memory and note-detail boundaries"
        reason = "Recovery stayed quality-stable but did not improve measured coverage or precision; coverage remains the dominant gap."
    return {
        "recommended_next_feature": feature,
        "reason": reason,
        "basis": {
            "pre_recovery_touched_coverage_rate": pre_coverage,
            "post_recovery_touched_coverage_rate": post_coverage,
            "pre_recovery_precision_on_evaluable": pre_precision,
            "post_recovery_precision_on_evaluable": post_precision,
            "recovered_false_positive_count": recovered_false,
            "safe_for_auto_apply_count": 0,
        },
        "feature_18e_d_2_re_evaluation_justified": feature.startswith("Feature #18E-D-2"),
    }


def build_recovery_reports(
    records: Sequence[Mapping[str, Any]],
    *,
    blocked_analysis: Mapping[str, Any],
    evaluation_report: Mapping[str, Any] | None = None,
    row_values: Sequence[Any] = (),
    facts_by_sample: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated = generated_at or utc_now()
    allowed = allowed_recovery_keys(blocked_analysis)
    pre_records = [dict(record) for record in records]
    post_records = [apply_overblocked_candidate_recovery(record, allowed_recovery_keys=allowed) for record in pre_records]

    if row_values and facts_by_sample is not None:
        pre_evaluated = evaluate_mapper_records(pre_records, row_values=row_values, facts_by_sample=facts_by_sample)
        post_evaluated = evaluate_mapper_records(post_records, row_values=row_values, facts_by_sample=facts_by_sample)
    else:
        pre_evaluated = pre_records
        post_evaluated = post_records

    post_by_key = {_row_key(record): record for record in post_evaluated}
    pre_by_key = {_row_key(record): record for record in pre_evaluated}
    decisions_by_key: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    for record in post_records:
        for decision in record.get("overblocked_recovery_decisions") or []:
            decisions_by_key[_candidate_key_from_decision(decision)] = decision

    recovery_rows = []
    for analysis_row in blocked_analysis.get("blocked_candidates") or []:
        key = _analysis_key(analysis_row)
        post_record = post_by_key.get((key[0], key[1]))
        decision = decisions_by_key.get(key)
        recovery_rows.append(_decision_report_row(analysis_row=analysis_row, decision=decision, post_record=post_record))

    recovered_rows = [row for row in recovery_rows if row["classification"] == "recovered_low_risk"]
    still_blocked = [row for row in recovery_rows if row["classification"] != "recovered_low_risk"]
    recovered_true = [row for row in recovered_rows if is_good_status(row.get("evaluation_status"))]
    recovered_false = [row for row in recovered_rows if is_false_positive_status(row.get("evaluation_status"))]
    recovered_ambiguous = [row for row in recovered_rows if row.get("evaluation_status") == "ambiguous_xbrl_support"]
    recovered_not_evaluable = [
        row
        for row in recovered_rows
        if row.get("evaluation_status") not in GOOD_STATUSES
        and row.get("evaluation_status") not in FALSE_POSITIVE_STATUSES
        and row.get("evaluation_status") != "ambiguous_xbrl_support"
    ]
    newly_covered = []
    for row in recovered_rows:
        key = (str(row.get("sample_id") or ""), str(row.get("pdf_row_id") or ""))
        if not (pre_by_key.get(key) or {}).get("predicted_qname") and (post_by_key.get(key) or {}).get("predicted_qname"):
            newly_covered.append(row)

    pre_metrics = _summary_metrics(pre_evaluated)
    post_metrics = _summary_metrics(post_evaluated)
    classification_counts = Counter(row["classification"] for row in recovery_rows)
    summary = {
        "feature": "18E-D-hotfix-1",
        "generated_at": generated,
        "pre_recovery": pre_metrics,
        "post_recovery": post_metrics,
        "source_evaluation_summary": sanitize_report_value((evaluation_report or {}).get("summary") or {}),
        "blocked_candidate_opportunities": len(recovery_rows),
        "recovered_candidate_count": len(recovered_rows),
        "newly_covered_by_recovery_count": len(newly_covered),
        "recovered_true_positive_count": len(recovered_true),
        "recovered_false_positive_count": len(recovered_false),
        "recovered_ambiguous_count": len(recovered_ambiguous),
        "recovered_not_evaluable_count": len(recovered_not_evaluable),
        "recovered_precision_on_evaluable": safe_rate(len(recovered_true), len(recovered_true) + len(recovered_false)),
        "classification_counts": dict(sorted(classification_counts.items())),
        "recovered_by_qname": _group_counts(recovered_rows, ["target_qname"], limit=20),
        "still_blocked_by_reason": _group_counts(still_blocked, ["recovery_reason"], limit=30),
        "still_blocked_by_qname": _group_counts(still_blocked, ["target_qname", "classification"], limit=30),
        "safe_enough_for_review_required_only": len(recovered_rows) > 0 and not recovered_false,
        "safe_for_auto_apply_count": 0,
        "explicit_no_auto_apply_boundary": "No #18E-D-hotfix-1 recovered candidate is safe for auto-apply; all recovered evidence remains review-required.",
        "safety": SAFETY,
    }
    summary["recommendation"] = _recommend_next(summary)

    run_metadata = {
        "feature": "18E-D-hotfix-1",
        "generated_at": generated,
        "read_only": True,
        "offline_only": True,
        **SAFETY,
    }
    recovery_report = {
        "run_metadata": run_metadata,
        "summary": summary,
        "recovery_candidates": recovery_rows,
    }
    summary_report = {
        "run_metadata": run_metadata,
        "summary": summary,
    }
    error_report = {
        "run_metadata": run_metadata,
        "summary": {
            "recovered_false_positive_count": len(recovered_false),
            "recovered_ambiguous_count": len(recovered_ambiguous),
            "recovered_not_evaluable_count": len(recovered_not_evaluable),
            "recovered_error_count": len(recovered_false) + len(recovered_ambiguous) + len(recovered_not_evaluable),
            "safety": SAFETY,
        },
        "recovery_errors": [*recovered_false, *recovered_ambiguous, *recovered_not_evaluable],
    }
    still_blocked_report = {
        "run_metadata": run_metadata,
        "summary": {
            "still_blocked_count": len(still_blocked),
            "classification_counts": dict(sorted(Counter(row["classification"] for row in still_blocked).items())),
            "still_blocked_by_reason": summary["still_blocked_by_reason"],
            "still_blocked_by_qname": summary["still_blocked_by_qname"],
            "safety": SAFETY,
        },
        "still_blocked_candidates": still_blocked,
    }
    return {
        "recovery": sanitize_report_value(recovery_report),
        "summary": sanitize_report_value(summary_report),
        "errors": sanitize_report_value(error_report),
        "still_blocked": sanitize_report_value(still_blocked_report),
        "post_records": post_evaluated,
    }


def _render_rows_markdown(title: str, report: Mapping[str, Any], rows_key: str) -> str:
    summary = report.get("summary") or {}
    lines = [f"# {title}", ""]
    for key in (
        "blocked_candidate_opportunities",
        "recovered_candidate_count",
        "newly_covered_by_recovery_count",
        "recovered_true_positive_count",
        "recovered_false_positive_count",
        "recovered_precision_on_evaluable",
        "still_blocked_count",
        "safe_for_auto_apply_count",
    ):
        if key in summary:
            lines.append(f"- {key}: {summary.get(key)}")
    recommendation = summary.get("recommendation") or {}
    if recommendation:
        lines.append(f"- recommended_next_feature: {recommendation.get('recommended_next_feature')}")
        lines.append(f"- recommendation_reason: {recommendation.get('reason')}")
    lines.extend(["", "| Sample | Label | QName | Classification | Status | Reason |", "| --- | --- | --- | --- | --- | --- |"])
    for row in report.get(rows_key) or []:
        lines.append(
            f"| {row.get('sample_id')} | {row.get('pdf_label')} | {row.get('target_qname')} | "
            f"{row.get('classification')} | {row.get('evaluation_status')} | {row.get('recovery_reason')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    pre = summary.get("pre_recovery") or {}
    post = summary.get("post_recovery") or {}
    recommendation = summary.get("recommendation") or {}
    lines = [
        "# Overblocked Recovery Summary - Feature #18E-D-hotfix-1",
        "",
        "| Metric | Before recovery | After recovery |",
        "| --- | ---: | ---: |",
    ]
    for key in ("touched_coverage_rate", "precision_on_evaluable", "false_positive_count", "no_match_count"):
        lines.append(f"| {key} | {pre.get(key)} | {post.get(key)} |")
    lines.extend(
        [
            "",
            f"- Recovered candidates: {summary.get('recovered_candidate_count')}",
            f"- Newly covered rows: {summary.get('newly_covered_by_recovery_count')}",
            f"- Recovered true positives: {summary.get('recovered_true_positive_count')}",
            f"- Recovered false positives: {summary.get('recovered_false_positive_count')}",
            f"- Recovered precision: {summary.get('recovered_precision_on_evaluable')}",
            f"- Safe enough for review-required only: {summary.get('safe_enough_for_review_required_only')}",
            f"- Safe for auto-apply count: {summary.get('safe_for_auto_apply_count')}",
            f"- #18E-D-2 justified: {recommendation.get('feature_18e_d_2_re_evaluation_justified')}",
            f"- Next: {recommendation.get('recommended_next_feature')}",
            f"- Reason: {recommendation.get('reason')}",
            "",
        ]
    )
    return "\n".join(lines)


def write_recovery_reports(reports: Mapping[str, Any], *, output_dir: str | Path) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "recovery_json": output / "overblocked_recovery_18e_d_hotfix_1.json",
        "recovery_md": output / "overblocked_recovery_18e_d_hotfix_1.md",
        "summary_json": output / "overblocked_recovery_summary_18e_d_hotfix_1.json",
        "summary_md": output / "overblocked_recovery_summary_18e_d_hotfix_1.md",
        "errors_json": output / "overblocked_recovery_errors_18e_d_hotfix_1.json",
        "errors_md": output / "overblocked_recovery_errors_18e_d_hotfix_1.md",
        "still_blocked_json": output / "overblocked_recovery_still_blocked_18e_d_hotfix_1.json",
        "still_blocked_md": output / "overblocked_recovery_still_blocked_18e_d_hotfix_1.md",
    }
    write_json(paths["recovery_json"], reports["recovery"])
    paths["recovery_md"].write_text(
        _render_rows_markdown("Overblocked Recovery - Feature #18E-D-hotfix-1", reports["recovery"], "recovery_candidates"),
        encoding="utf-8",
    )
    write_json(paths["summary_json"], reports["summary"])
    paths["summary_md"].write_text(_render_summary_markdown(reports["summary"]), encoding="utf-8")
    write_json(paths["errors_json"], reports["errors"])
    paths["errors_md"].write_text(
        _render_rows_markdown("Overblocked Recovery Errors - Feature #18E-D-hotfix-1", reports["errors"], "recovery_errors"),
        encoding="utf-8",
    )
    write_json(paths["still_blocked_json"], reports["still_blocked"])
    paths["still_blocked_md"].write_text(
        _render_rows_markdown(
            "Overblocked Recovery Still Blocked - Feature #18E-D-hotfix-1",
            reports["still_blocked"],
            "still_blocked_candidates",
        ),
        encoding="utf-8",
    )
    return {key: str(path) for key, path in paths.items()}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recover low-risk #18E-D overblocked candidates offline.")
    parser.add_argument("--dataset-dir", default="benchmark_mbrs_pairs")
    parser.add_argument("--mapper-report", default="reports/rulebook_mapper_dictionary_tightened_18e_b2_hotfix_1.json")
    parser.add_argument("--blocked-analysis", default="reports/tightened_mapper_blocked_candidate_analysis_18e_d.json")
    parser.add_argument("--evaluation-report", default="reports/tightened_mapper_evaluation_18e_d.json")
    parser.add_argument("--output-dir", default="reports")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    mapper_report = read_json(args.mapper_report)
    blocked_analysis = read_json(args.blocked_analysis)
    evaluation_report = read_json(args.evaluation_report)
    records = list(mapper_report.get("suggestions") or [])
    evidence = load_local_evaluation_evidence(dataset_dir=args.dataset_dir, records=records)
    reports = build_recovery_reports(
        records,
        blocked_analysis=blocked_analysis,
        evaluation_report=evaluation_report,
        row_values=evidence["row_values"],
        facts_by_sample=evidence["facts_by_sample"],
    )
    paths = write_recovery_reports(reports, output_dir=args.output_dir)
    summary = reports["summary"]["summary"]
    recommendation = summary.get("recommendation") or {}

    print("Feature #18E-D-hotfix-1 overblocked recovery reports written:")
    for name, path in paths.items():
        print(f"- {name}: {path}")
    print("")
    print("Recovery summary:")
    print(f"- recovered_candidate_count: {summary.get('recovered_candidate_count')}")
    print(f"- newly_covered_by_recovery_count: {summary.get('newly_covered_by_recovery_count')}")
    print(f"- recovered_true_positive_count: {summary.get('recovered_true_positive_count')}")
    print(f"- recovered_false_positive_count: {summary.get('recovered_false_positive_count')}")
    print(f"- recovered_precision_on_evaluable: {summary.get('recovered_precision_on_evaluable')}")
    print(f"- pre_coverage: {(summary.get('pre_recovery') or {}).get('touched_coverage_rate')}")
    print(f"- post_coverage: {(summary.get('post_recovery') or {}).get('touched_coverage_rate')}")
    print(f"- pre_precision: {(summary.get('pre_recovery') or {}).get('precision_on_evaluable')}")
    print(f"- post_precision: {(summary.get('post_recovery') or {}).get('precision_on_evaluable')}")
    print(f"- safe_for_auto_apply_count: {summary.get('safe_for_auto_apply_count')}")
    print(f"- next: {recommendation.get('recommended_next_feature')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
