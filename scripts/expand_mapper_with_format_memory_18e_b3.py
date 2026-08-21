"""Expand the offline mapper with format memory and note boundaries for #18E-B-3."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.company_format_template_memory import (
    build_company_format_template_memory_report,
    render_company_format_template_memory_markdown,
)
from services.pdf_note_detail_boundaries import (
    build_note_detail_boundary_report,
    classify_note_detail_boundaries,
    render_note_detail_boundary_markdown,
)
from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.pdf_xbrl_rulebook_mapper import (
    apply_company_format_memory_mapping,
    apply_note_detail_boundary,
    apply_overblocked_candidate_recovery,
)
from services.tightened_mapper_evaluation import (
    evaluate_mapper_records,
    is_false_positive_status,
    is_good_status,
    load_local_evaluation_evidence,
    metrics_for_records,
    read_json,
    sanitize_report_value,
    safe_rate,
    utc_now,
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


def _row_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record.get("sample_id") or ""), str(record.get("pdf_row_id") or record.get("row_id") or "")


def _read_records(mapper_report: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(record) for record in mapper_report.get("suggestions") or mapper_report.get("records") or []]


def _analysis_key(row: Mapping[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("sample_id") or ""),
        str(row.get("pdf_row_id") or row.get("row_id") or ""),
        str(row.get("target_qname") or ""),
        str(row.get("blocked_source") or ""),
    )


def allowed_recovery_keys(blocked_analysis: Mapping[str, Any]) -> set[tuple[str, str, str, str]]:
    return {
        _analysis_key(row)
        for row in blocked_analysis.get("blocked_candidates") or []
        if row.get("blocked_candidate_classification") == "overblocked_true_positive"
    }


def _no_match_records(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [record for record in records if not record.get("predicted_qname")]


def _summary_metrics(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = metrics_for_records(records)
    metrics["no_match_count"] = len(_no_match_records(records))
    metrics["false_positives"] = metrics.get("false_positive_count")
    return metrics


def _top_labels(records: Sequence[Mapping[str, Any]], *, limit: int = 30) -> list[dict[str, Any]]:
    counter = Counter(str(record.get("normalized_label") or canonical_label(record.get("pdf_label"))) for record in records)
    return [{"normalized_label": label, "count": count} for label, count in counter.most_common(limit) if label]


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
            "match_reasons": record.get("match_reasons") or [],
            "blocking_reasons": record.get("blocking_reasons") or [],
            "note_boundary": record.get("note_boundary") or {},
            "blocked_note_boundary_candidate": record.get("blocked_note_boundary_candidate"),
            "blocked_format_memory_candidate": record.get("blocked_format_memory_candidate"),
            "safe_for_auto_apply": False,
            "requires_human_review": record.get("requires_human_review") is not False,
        }
    )


def _boundary_index(boundaries: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {(str(item.get("sample_id") or ""), str(item.get("row_id") or "")): item for item in boundaries}


def apply_format_memory_optimization(
    records: Sequence[Mapping[str, Any]],
    *,
    memory_entries: Sequence[Mapping[str, Any]],
    note_boundaries: Sequence[Mapping[str, Any]],
    blocked_analysis: Mapping[str, Any],
) -> list[dict[str, Any]]:
    boundaries = _boundary_index(note_boundaries)
    allowed = allowed_recovery_keys(blocked_analysis)
    optimized = []
    for record in records:
        key = _row_key(record)
        context = record.get("row_context") if isinstance(record.get("row_context"), Mapping) else {}
        boundary = boundaries.get(key)
        recovered = apply_overblocked_candidate_recovery(record, allowed_recovery_keys=allowed)
        boundary_record = apply_note_detail_boundary(recovered, boundary)
        memory_record = apply_company_format_memory_mapping(
            boundary_record,
            context,
            memory_entries,
            note_boundary=boundary,
        )
        optimized.append(apply_note_detail_boundary(memory_record, boundary))
    return optimized


def _new_candidate_rows(
    baseline: Sequence[Mapping[str, Any]],
    optimized: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    base_by_key = {_row_key(record): record for record in baseline}
    rows = []
    for record in optimized:
        previous = base_by_key.get(_row_key(record), {})
        if not previous.get("predicted_qname") and record.get("predicted_qname"):
            rows.append(record)
    return rows


def _removed_candidate_rows(
    baseline: Sequence[Mapping[str, Any]],
    optimized: Sequence[Mapping[str, Any]],
) -> list[tuple[Mapping[str, Any], Mapping[str, Any]]]:
    opt_by_key = {_row_key(record): record for record in optimized}
    rows = []
    for record in baseline:
        optimized_record = opt_by_key.get(_row_key(record), {})
        if record.get("predicted_qname") and not optimized_record.get("predicted_qname"):
            rows.append((record, optimized_record))
    return rows


def _recommend_next(summary: Mapping[str, Any]) -> dict[str, Any]:
    baseline = summary.get("baseline") or {}
    optimized = summary.get("optimized") or {}
    baseline_precision = baseline.get("precision_on_evaluable")
    optimized_precision = optimized.get("precision_on_evaluable")
    optimized_coverage = optimized.get("touched_coverage_rate")
    false_increase = int(summary.get("optimized_false_positive_count_delta") or 0)

    if false_increase > 0:
        feature = "Feature #18E-B-3-hotfix-1 - tighten format memory and note boundaries"
        reason = "False positives increased after format-memory or note-boundary changes."
    elif (
        optimized_coverage is not None
        and optimized_coverage > 0.5
        and baseline_precision is not None
        and optimized_precision is not None
        and optimized_precision >= baseline_precision
    ):
        feature = "Feature #18E-D-2 - Re-evaluate mapper after format memory and update readiness matrix"
        reason = "Coverage improved above 50% without a precision drop."
    elif optimized_coverage is not None and optimized_coverage <= 0.47:
        feature = "Feature #18E-F-A - Redesign mapper target from deterministic-only to candidate-ranking hybrid with Qwen fallback"
        reason = "Coverage still stalls around the 45% baseline despite conservative format memory."
    elif int(summary.get("false_positives_prevented_by_note_boundaries") or 0) > int(summary.get("correct_candidates_lost_due_to_note_boundaries") or 0):
        feature = "Feature #18E-B-4 - Add safe note-total aggregation candidates"
        reason = "Note boundaries improved quality enough to justify a separate safe note-total aggregation slice."
    else:
        feature = "Feature #18E-F-A - Redesign mapper target from deterministic-only to candidate-ranking hybrid with Qwen fallback"
        reason = "Coverage did not improve enough for another deterministic-only readiness pass."
    return {
        "recommended_next_feature": feature,
        "reason": reason,
        "basis": {
            "baseline_touched_coverage_rate": baseline.get("touched_coverage_rate"),
            "optimized_touched_coverage_rate": optimized.get("touched_coverage_rate"),
            "baseline_precision_on_evaluable": baseline_precision,
            "optimized_precision_on_evaluable": optimized_precision,
            "optimized_false_positive_count_delta": false_increase,
            "safe_for_auto_apply_count": optimized.get("safe_for_auto_apply_count"),
        },
        "feature_18e_d_2_re_evaluation_justified": feature.startswith("Feature #18E-D-2"),
    }


def _comparison_report(
    *,
    generated_at: str,
    baseline_records: Sequence[Mapping[str, Any]],
    optimized_records: Sequence[Mapping[str, Any]],
    memory_report: Mapping[str, Any],
    boundary_report: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_metrics = _summary_metrics(baseline_records)
    optimized_metrics = _summary_metrics(optimized_records)
    new_candidates = _new_candidate_rows(baseline_records, optimized_records)
    removed_candidates = _removed_candidate_rows(baseline_records, optimized_records)
    blocked_by_boundary = [record for record in optimized_records if record.get("blocked_note_boundary_candidate")]
    blocked_format_memory = [record for record in optimized_records if record.get("blocked_format_memory_candidate")]

    new_good = [record for record in new_candidates if is_good_status(record.get("evaluation_status"))]
    new_false = [record for record in new_candidates if is_false_positive_status(record.get("evaluation_status"))]
    false_prevented = [before for before, _after in removed_candidates if is_false_positive_status(before.get("evaluation_status"))]
    correct_lost = [before for before, _after in removed_candidates if is_good_status(before.get("evaluation_status"))]

    summary = {
        "feature": "18E-B-3",
        "generated_at": generated_at,
        "baseline": baseline_metrics,
        "optimized": optimized_metrics,
        "coverage_delta": (
            round(float(optimized_metrics.get("touched_coverage_rate") or 0) - float(baseline_metrics.get("touched_coverage_rate") or 0), 4)
            if optimized_metrics.get("touched_coverage_rate") is not None and baseline_metrics.get("touched_coverage_rate") is not None
            else None
        ),
        "precision_delta": (
            round(float(optimized_metrics.get("precision_on_evaluable") or 0) - float(baseline_metrics.get("precision_on_evaluable") or 0), 4)
            if optimized_metrics.get("precision_on_evaluable") is not None and baseline_metrics.get("precision_on_evaluable") is not None
            else None
        ),
        "optimized_false_positive_count_delta": int(optimized_metrics.get("false_positive_count") or 0)
        - int(baseline_metrics.get("false_positive_count") or 0),
        "new_candidates_count": len(new_candidates),
        "new_true_positive_count": len(new_good),
        "new_false_positive_count": len(new_false),
        "new_candidate_precision_on_evaluable": safe_rate(len(new_good), len(new_good) + len(new_false)),
        "no_match_before": baseline_metrics.get("no_match_count"),
        "no_match_after": optimized_metrics.get("no_match_count"),
        "format_memory_entry_count": (memory_report.get("summary") or {}).get("memory_entry_count"),
        "note_boundary_counts": (boundary_report.get("summary") or {}).get("boundary_type_counts"),
        "candidates_blocked_by_note_boundaries": len(blocked_by_boundary),
        "format_memory_candidates_blocked_by_note_boundaries": len(blocked_format_memory),
        "false_positives_prevented_by_note_boundaries": len(false_prevented),
        "correct_candidates_lost_due_to_note_boundaries": len(correct_lost),
        "top_newly_covered_labels": _top_labels(new_good),
        "top_still_missed_labels": _top_labels(_no_match_records(optimized_records)),
        "eighty_percent_path": {
            "target_coverage_rate": 0.8,
            "optimized_touched_coverage_rate": optimized_metrics.get("touched_coverage_rate"),
            "additional_candidates_needed_for_80_percent": max(
                0,
                int(round((int(optimized_metrics.get("total_observations") or 0) * 0.8)))
                - int(optimized_metrics.get("candidate_count") or 0),
            ),
            "realistic_with_current_deterministic_memory": bool((optimized_metrics.get("touched_coverage_rate") or 0) >= 0.6),
        },
        "safe_for_auto_apply_count": optimized_metrics.get("safe_for_auto_apply_count"),
        "safety": SAFETY,
    }
    summary["recommendation"] = _recommend_next(summary)
    return {
        "run_metadata": {
            "feature": "18E-B-3",
            "generated_at": generated_at,
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": summary,
        "new_candidates": [_safe_record(record) for record in new_candidates],
        "boundary_blocked_candidates": [_safe_record(record) for record in blocked_by_boundary],
        "false_positives_prevented_by_note_boundaries": [_safe_record(record) for record in false_prevented],
        "correct_candidates_lost_due_to_note_boundaries": [_safe_record(record) for record in correct_lost],
    }


def _optimized_report(generated_at: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "run_metadata": {
            "feature": "18E-B-3",
            "generated_at": generated_at,
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": _summary_metrics(records),
        "suggestions": [_safe_record(record) for record in records],
    }


def _errors_report(generated_at: str, comparison: Mapping[str, Any], optimized_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    false_records = [record for record in optimized_records if is_false_positive_status(record.get("evaluation_status"))]
    ambiguous = [record for record in optimized_records if record.get("evaluation_status") == "ambiguous_xbrl_support"]
    not_eval = [
        record
        for record in optimized_records
        if record.get("predicted_qname") and str(record.get("evaluation_status") or "") == "not_evaluable"
    ]
    return {
        "run_metadata": {
            "feature": "18E-B-3",
            "generated_at": generated_at,
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": {
            "optimized_false_positive_count": len(false_records),
            "optimized_ambiguous_count": len(ambiguous),
            "optimized_not_evaluable_prediction_count": len(not_eval),
            "new_false_positive_count": (comparison.get("summary") or {}).get("new_false_positive_count"),
            "correct_candidates_lost_due_to_note_boundaries": (comparison.get("summary") or {}).get("correct_candidates_lost_due_to_note_boundaries"),
            "safe_for_auto_apply_count": 0,
        },
        "false_positives": [_safe_record(record) for record in false_records],
        "ambiguous": [_safe_record(record) for record in ambiguous],
        "not_evaluable_predictions": [_safe_record(record) for record in not_eval],
    }


def _no_match_report(generated_at: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    no_match = _no_match_records(records)
    return {
        "run_metadata": {
            "feature": "18E-B-3",
            "generated_at": generated_at,
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": {
            "no_match_count": len(no_match),
            "top_no_match_labels": _top_labels(no_match),
            "safe_for_auto_apply_count": 0,
        },
        "no_match": [_safe_record(record) for record in no_match],
    }


def _blocked_report(generated_at: str, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    blocked = [
        record
        for record in records
        if record.get("blocked_note_boundary_candidate")
        or record.get("blocked_format_memory_candidate")
        or record.get("blocked_dictionary_candidate")
        or record.get("blocked_row_order_candidate")
    ]
    return {
        "run_metadata": {
            "feature": "18E-B-3",
            "generated_at": generated_at,
            "read_only": True,
            "offline_only": True,
            **SAFETY,
        },
        "summary": {
            "blocked_candidate_rows": len(blocked),
            "note_boundary_blocked_rows": sum(1 for record in blocked if record.get("blocked_note_boundary_candidate")),
            "format_memory_blocked_rows": sum(1 for record in blocked if record.get("blocked_format_memory_candidate")),
            "blocked_reason_counts": [
                {"blocking_reason": reason, "count": count}
                for reason, count in Counter(reason for record in blocked for reason in record.get("blocking_reasons") or []).most_common(30)
            ],
            "safe_for_auto_apply_count": 0,
        },
        "blocked_candidates": [_safe_record(record) for record in blocked],
    }


def render_comparison_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    baseline = summary.get("baseline") or {}
    optimized = summary.get("optimized") or {}
    recommendation = summary.get("recommendation") or {}
    lines = [
        "# Rulebook Mapper Format Memory Comparison - Feature #18E-B-3",
        "",
        f"- Baseline coverage: {baseline.get('touched_coverage_rate')}",
        f"- Optimized coverage: {optimized.get('touched_coverage_rate')}",
        f"- Baseline precision: {baseline.get('precision_on_evaluable')}",
        f"- Optimized precision: {optimized.get('precision_on_evaluable')}",
        f"- New candidates: {summary.get('new_candidates_count')}",
        f"- New true positives: {summary.get('new_true_positive_count')}",
        f"- New false positives: {summary.get('new_false_positive_count')}",
        f"- No-match before: {summary.get('no_match_before')}",
        f"- No-match after: {summary.get('no_match_after')}",
        f"- Boundary-blocked candidates: {summary.get('candidates_blocked_by_note_boundaries')}",
        f"- False positives prevented by note boundaries: {summary.get('false_positives_prevented_by_note_boundaries')}",
        f"- Correct candidates lost due to note boundaries: {summary.get('correct_candidates_lost_due_to_note_boundaries')}",
        f"- #18E-D-2 justified: {recommendation.get('feature_18e_d_2_re_evaluation_justified')}",
        f"- Recommended next feature: {recommendation.get('recommended_next_feature')}",
        "",
        "## Top Newly Covered Labels",
        "",
    ]
    for item in summary.get("top_newly_covered_labels") or []:
        lines.append(f"- {item.get('normalized_label')}: {item.get('count')}")
    lines.extend(["", "## Top Still Missed Labels", ""])
    for item in summary.get("top_still_missed_labels") or []:
        lines.append(f"- {item.get('normalized_label')}: {item.get('count')}")
    lines.append("")
    return "\n".join(lines)


def render_simple_markdown(title: str, report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [f"# {title}", ""]
    for key, value in summary.items():
        if isinstance(value, (dict, list)):
            continue
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def build_reports(
    *,
    dataset_dir: str | Path,
    mapper_report_path: str | Path,
    evaluation_report_path: str | Path | None = None,
    blocked_analysis_path: str | Path | None = None,
) -> dict[str, Any]:
    generated = utc_now()
    mapper_report = read_json(mapper_report_path)
    _evaluation_report = read_json(evaluation_report_path) if evaluation_report_path else {}
    blocked_analysis = read_json(blocked_analysis_path) if blocked_analysis_path and Path(blocked_analysis_path).exists() else {}
    baseline_records = _read_records(mapper_report)
    evidence = load_local_evaluation_evidence(dataset_dir=dataset_dir, records=baseline_records)
    baseline_evaluated = evaluate_mapper_records(
        baseline_records,
        row_values=evidence["row_values"],
        facts_by_sample=evidence["facts_by_sample"],
    )

    boundary_report = build_note_detail_boundary_report(records_or_contexts=baseline_records)
    note_boundaries = list(boundary_report.get("note_detail_boundaries") or classify_note_detail_boundaries(baseline_records))
    memory_report = build_company_format_template_memory_report(baseline_evaluated)
    memory_entries = list(memory_report.get("format_memory_entries") or [])
    optimized_records = apply_format_memory_optimization(
        baseline_records,
        memory_entries=memory_entries,
        note_boundaries=note_boundaries,
        blocked_analysis=blocked_analysis,
    )
    optimized_evaluated = evaluate_mapper_records(
        optimized_records,
        row_values=evidence["row_values"],
        facts_by_sample=evidence["facts_by_sample"],
    )
    comparison = _comparison_report(
        generated_at=generated,
        baseline_records=baseline_evaluated,
        optimized_records=optimized_evaluated,
        memory_report=memory_report,
        boundary_report=boundary_report,
    )
    return {
        "company_format_template_memory": memory_report,
        "pdf_note_detail_boundaries": boundary_report,
        "optimized": _optimized_report(generated, optimized_evaluated),
        "comparison": comparison,
        "errors": _errors_report(generated, comparison, optimized_evaluated),
        "no_match": _no_match_report(generated, optimized_evaluated),
        "blocked": _blocked_report(generated, optimized_evaluated),
    }


def write_reports(reports: Mapping[str, Mapping[str, Any]], *, output_dir: str | Path) -> dict[str, Path]:
    output = Path(output_dir)
    paths = {
        "company_format_template_memory_json": output / "company_format_template_memory_18e_b3.json",
        "company_format_template_memory_md": output / "company_format_template_memory_18e_b3.md",
        "pdf_note_detail_boundaries_json": output / "pdf_note_detail_boundaries_18e_b3.json",
        "pdf_note_detail_boundaries_md": output / "pdf_note_detail_boundaries_18e_b3.md",
        "optimized_json": output / "rulebook_mapper_format_memory_optimized_18e_b3.json",
        "optimized_md": output / "rulebook_mapper_format_memory_optimized_18e_b3.md",
        "comparison_json": output / "rulebook_mapper_format_memory_comparison_18e_b3.json",
        "comparison_md": output / "rulebook_mapper_format_memory_comparison_18e_b3.md",
        "errors_json": output / "rulebook_mapper_format_memory_errors_18e_b3.json",
        "errors_md": output / "rulebook_mapper_format_memory_errors_18e_b3.md",
        "no_match_json": output / "rulebook_mapper_format_memory_no_match_18e_b3.json",
        "no_match_md": output / "rulebook_mapper_format_memory_no_match_18e_b3.md",
        "blocked_json": output / "rulebook_mapper_format_memory_blocked_18e_b3.json",
        "blocked_md": output / "rulebook_mapper_format_memory_blocked_18e_b3.md",
    }
    write_json(paths["company_format_template_memory_json"], reports["company_format_template_memory"])
    paths["company_format_template_memory_md"].write_text(
        render_company_format_template_memory_markdown(reports["company_format_template_memory"]),
        encoding="utf-8",
    )
    write_json(paths["pdf_note_detail_boundaries_json"], reports["pdf_note_detail_boundaries"])
    paths["pdf_note_detail_boundaries_md"].write_text(
        render_note_detail_boundary_markdown(reports["pdf_note_detail_boundaries"]),
        encoding="utf-8",
    )
    write_json(paths["optimized_json"], reports["optimized"])
    paths["optimized_md"].write_text(render_simple_markdown("Rulebook Mapper Format Memory Optimized - Feature #18E-B-3", reports["optimized"]), encoding="utf-8")
    write_json(paths["comparison_json"], reports["comparison"])
    paths["comparison_md"].write_text(render_comparison_markdown(reports["comparison"]), encoding="utf-8")
    write_json(paths["errors_json"], reports["errors"])
    paths["errors_md"].write_text(render_simple_markdown("Rulebook Mapper Format Memory Errors - Feature #18E-B-3", reports["errors"]), encoding="utf-8")
    write_json(paths["no_match_json"], reports["no_match"])
    paths["no_match_md"].write_text(render_simple_markdown("Rulebook Mapper Format Memory No-Match - Feature #18E-B-3", reports["no_match"]), encoding="utf-8")
    write_json(paths["blocked_json"], reports["blocked"])
    paths["blocked_md"].write_text(render_simple_markdown("Rulebook Mapper Format Memory Blocked - Feature #18E-B-3", reports["blocked"]), encoding="utf-8")
    return paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expand the tightened mapper with format memory and note boundaries.")
    parser.add_argument("--dataset-dir", default="benchmark_mbrs_pairs")
    parser.add_argument("--mapper-report", default="reports/rulebook_mapper_dictionary_tightened_18e_b2_hotfix_1.json")
    parser.add_argument("--evaluation-report", default="reports/tightened_mapper_evaluation_18e_d.json")
    parser.add_argument("--blocked-analysis", default="reports/tightened_mapper_blocked_candidate_analysis_18e_d.json")
    parser.add_argument("--output-dir", default="reports")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reports = build_reports(
        dataset_dir=args.dataset_dir,
        mapper_report_path=args.mapper_report,
        evaluation_report_path=args.evaluation_report,
        blocked_analysis_path=args.blocked_analysis,
    )
    paths = write_reports(reports, output_dir=args.output_dir)
    comparison = reports["comparison"]["summary"]
    recommendation = comparison["recommendation"]

    print("Feature #18E-B-3 format-memory reports written:")
    for name, path in paths.items():
        print(f"- {name}: {path}")
    print("")
    print("Comparison summary:")
    print(f"- baseline_coverage: {comparison['baseline'].get('touched_coverage_rate')}")
    print(f"- optimized_coverage: {comparison['optimized'].get('touched_coverage_rate')}")
    print(f"- baseline_precision: {comparison['baseline'].get('precision_on_evaluable')}")
    print(f"- optimized_precision: {comparison['optimized'].get('precision_on_evaluable')}")
    print(f"- new_candidates_count: {comparison.get('new_candidates_count')}")
    print(f"- new_true_positive_count: {comparison.get('new_true_positive_count')}")
    print(f"- new_false_positive_count: {comparison.get('new_false_positive_count')}")
    print(f"- no_match_before: {comparison.get('no_match_before')}")
    print(f"- no_match_after: {comparison.get('no_match_after')}")
    print(f"- candidates_blocked_by_note_boundaries: {comparison.get('candidates_blocked_by_note_boundaries')}")
    print(f"- safe_for_auto_apply_count: {comparison['optimized'].get('safe_for_auto_apply_count')}")
    print(f"- #18E-D-2 justified: {recommendation.get('feature_18e_d_2_re_evaluation_justified')}")
    print(f"- next: {recommendation.get('recommended_next_feature')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
