"""Tighten hybrid candidate ranking filters for Feature #18E-F-A-hotfix-2."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.hybrid_candidate_ranking_mapper import (
    SAFETY,
    build_concept_catalog,
    build_reports,
    build_uncovered_report,
    evaluate_candidate_rows,
    load_cached_qwen_candidates,
    mapper_records_from_report,
    read_json,
    render_ranking_markdown,
    render_risk_markdown,
    render_uncovered_markdown,
    safe_rate,
    summarize_candidate_rows,
    utc_now,
    write_json,
)
from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.tightened_mapper_evaluation import load_local_evaluation_evidence, sanitize_report_value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--baseline-report", required=True)
    parser.add_argument("--mapper-report", required=True)
    parser.add_argument("--evaluation-report", required=True)
    parser.add_argument("--taxonomy-metadata")
    parser.add_argument("--qwen-report-dir")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--allow-missing-taxonomy", action="store_true")
    parser.add_argument("--allow-missing-qwen", action="store_true")
    return parser.parse_args()


def _row_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("sample_id") or ""), str(row.get("row_id") or row.get("pdf_row_id") or "")


def _risk_count(summary: Mapping[str, Any]) -> int:
    risk = summary.get("risk_distribution") or summary.get("candidate_risk_distribution") or {}
    return int(risk.get("high") or 0) + int(risk.get("critical") or 0)


def _candidate_total(summary: Mapping[str, Any]) -> int:
    risk = summary.get("risk_distribution") or summary.get("candidate_risk_distribution") or {}
    return sum(int(value) for value in risk.values())


def _source_count(summary: Mapping[str, Any], source: str) -> int:
    return int((summary.get("candidate_source_counts") or {}).get(source) or 0)


def _delta(before: int | float | None, after: int | float | None) -> int | float | None:
    if before is None or after is None:
        return None
    return round(after - before, 4) if isinstance(before, float) or isinstance(after, float) else after - before


def _recommendation(
    baseline_summary: Mapping[str, Any],
    tightened_summary: Mapping[str, Any],
    baseline_eval: Mapping[str, Any],
    tightened_eval: Mapping[str, Any],
) -> dict[str, Any]:
    coverage = float(tightened_summary.get("candidate_coverage_rate") or 0.0)
    high_before = _risk_count(baseline_summary)
    high_after = _risk_count(tightened_summary)
    high_drop_rate = safe_rate(high_before - high_after, high_before) or 0.0
    total_after = _candidate_total(tightened_summary)
    noisy_after = total_after > 0 and (high_after / total_after) > 0.5
    top5_before = baseline_eval.get("top5_recall_if_evaluable")
    top5_after = tightened_eval.get("top5_recall_if_evaluable")
    top5_improved = top5_before is not None and top5_after is not None and float(top5_after) > float(top5_before)

    if coverage >= 0.6 and high_drop_rate >= 0.3 and not noisy_after:
        feature = "Feature #18F-B - Hybrid candidate-ranking hardening and threshold calibration"
        reason = "Candidate coverage remains useful and high-risk candidates dropped materially."
    elif coverage < 0.6:
        feature = "Feature #18E-F-A-hotfix-1 - Improve taxonomy lexical candidate generation / concept metadata coverage"
        reason = "Tightening pushed candidate coverage below 60%, so metadata/lexical coverage needs repair."
    elif noisy_after:
        feature = "Feature #18E-F-A-hotfix-3 - Disable noisy lexical families and require source corroboration"
        reason = "The candidate list remains too noisy after tightening."
    elif top5_improved:
        feature = "Feature #18F-C - Design backend advisory integration for ranked candidates, no auto-apply"
        reason = "Top-5 recall improved and risk is manageable."
    else:
        feature = "Feature #18F-B - Hybrid candidate-ranking hardening and threshold calibration"
        reason = "Candidate coverage remains useful and risk is improved enough for calibration."
    return {
        "recommended_next_feature": feature,
        "reason": reason,
        "basis": {
            "candidate_coverage_rate": coverage,
            "high_risk_before": high_before,
            "high_risk_after": high_after,
            "high_risk_drop_rate": high_drop_rate,
            "candidate_total_after": total_after,
            "candidate_list_too_noisy_after": noisy_after,
            "top5_recall_before": top5_before,
            "top5_recall_after": top5_after,
        },
    }


def _evaluation_index(report: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {_row_key(row): row for row in report.get("records") or []}


def _filter_analysis(
    baseline_rows: Sequence[Mapping[str, Any]],
    tightened_rows: Sequence[Mapping[str, Any]],
    baseline_eval: Mapping[str, Any],
    tightened_eval: Mapping[str, Any],
) -> dict[str, Any]:
    base_by_key = {_row_key(row): row for row in baseline_rows}
    tight_by_key = {_row_key(row): row for row in tightened_rows}
    base_eval = _evaluation_index(baseline_eval)
    tight_eval = _evaluation_index(tightened_eval)
    reason_counts: Counter[str] = Counter()
    affected_labels: Counter[str] = Counter()
    filtered_source_counts: Counter[str] = Counter()
    rows_losing_all = []
    rows_improved = []
    rows_candidate_count_reduced = []
    filtered_candidate_count = 0

    for key, tightened in tight_by_key.items():
        baseline = base_by_key.get(key) or {}
        filtered = tightened.get("filtered_candidates") or []
        filtered_candidate_count += len(filtered)
        if filtered:
            affected_labels[str(tightened.get("normalized_label") or canonical_label(tightened.get("pdf_label")))] += len(filtered)
        for candidate in filtered:
            for reason in candidate.get("filter_reasons") or []:
                reason_counts[str(reason)] += 1
            for source in candidate.get("candidate_sources_combined") or []:
                filtered_source_counts[str(source)] += 1
        if int(baseline.get("candidate_count") or 0) > 0 and int(tightened.get("candidate_count") or 0) == 0:
            rows_losing_all.append(
                {
                    "sample_id": tightened.get("sample_id"),
                    "row_id": tightened.get("row_id"),
                    "normalized_label": tightened.get("normalized_label"),
                    "baseline_candidate_count": baseline.get("candidate_count"),
                    "filtered_candidate_count": tightened.get("filtered_candidate_count"),
                    "filtered_candidates": filtered,
                }
            )
        if int(tightened.get("candidate_count") or 0) < int(baseline.get("candidate_count") or 0):
            rows_candidate_count_reduced.append(
                {
                    "sample_id": tightened.get("sample_id"),
                    "row_id": tightened.get("row_id"),
                    "normalized_label": tightened.get("normalized_label"),
                    "baseline_candidate_count": baseline.get("candidate_count"),
                    "tightened_candidate_count": tightened.get("candidate_count"),
                    "filtered_candidate_count": tightened.get("filtered_candidate_count"),
                }
            )
        before_status = str((base_eval.get(key) or {}).get("evaluation_status") or "")
        after_status = str((tight_eval.get(key) or {}).get("evaluation_status") or "")
        if before_status not in {"correct_qname_top1", "correct_qname_top3", "correct_qname_top5"} and after_status in {"correct_qname_top1", "correct_qname_top3", "correct_qname_top5"}:
            rows_improved.append(
                {
                    "sample_id": tightened.get("sample_id"),
                    "row_id": tightened.get("row_id"),
                    "normalized_label": tightened.get("normalized_label"),
                    "before_status": before_status,
                    "after_status": after_status,
                    "top_candidate": (tightened.get("candidates") or [{}])[0],
                }
            )

    return sanitize_report_value(
        {
            "summary": {
                "filtered_candidate_count": filtered_candidate_count,
                "filtered_reason_count": sum(reason_counts.values()) if reason_counts else 0,
                "filter_reason_counts": dict(sorted(reason_counts.items())),
                "filtered_source_counts": dict(sorted(filtered_source_counts.items())),
                "rows_losing_all_candidates": len(rows_losing_all),
                "rows_with_candidate_count_reduced": len(rows_candidate_count_reduced),
                "rows_improved_by_filtering": len(rows_improved),
                "labels_most_affected": [
                    {"normalized_label": label, "filtered_candidate_count": count}
                    for label, count in affected_labels.most_common(40)
                ],
                "safe_for_auto_apply_count": 0,
                "safety": dict(SAFETY),
            },
            "rows_losing_all_candidates": rows_losing_all[:250],
            "rows_with_candidate_count_reduced": rows_candidate_count_reduced[:250],
            "rows_improved_by_filtering": rows_improved[:120],
        }
    )


def _summary_report(
    *,
    generated_at: str,
    baseline_rows: Sequence[Mapping[str, Any]],
    tightened_reports: Mapping[str, Mapping[str, Any]],
    baseline_eval: Mapping[str, Any],
    filter_analysis: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_summary = summarize_candidate_rows(baseline_rows)
    tightened_summary = tightened_reports["summary"]["summary"]
    tightened_eval = tightened_reports["evaluation"]["summary"]
    baseline_eval_summary = baseline_eval["summary"]
    recommendation = _recommendation(baseline_summary, tightened_summary, baseline_eval_summary, tightened_eval)
    return sanitize_report_value(
        {
            "run_metadata": {"feature": "18E-F-A-hotfix-2", "generated_at": generated_at, "offline_only": True, **SAFETY},
            "summary": {
                "baseline": baseline_summary,
                "tightened": tightened_summary,
                "coverage_delta": _delta(baseline_summary.get("candidate_coverage_rate"), tightened_summary.get("candidate_coverage_rate")),
                "rows_with_at_least_1_candidate_delta": _delta(baseline_summary.get("rows_with_at_least_1_candidate"), tightened_summary.get("rows_with_at_least_1_candidate")),
                "rows_with_at_least_3_candidates_delta": _delta(baseline_summary.get("rows_with_at_least_3_candidates"), tightened_summary.get("rows_with_at_least_3_candidates")),
                "no_candidate_rows_delta": _delta(baseline_summary.get("no_candidate_rows"), tightened_summary.get("no_candidate_rows")),
                "candidate_total_delta": _delta(_candidate_total(baseline_summary), _candidate_total(tightened_summary)),
                "high_risk_delta": _delta(_risk_count(baseline_summary), _risk_count(tightened_summary)),
                "high_risk_drop_rate": safe_rate(_risk_count(baseline_summary) - _risk_count(tightened_summary), _risk_count(baseline_summary)),
                "taxonomy_lexical_candidates_before": _source_count(baseline_summary, "taxonomy_lexical"),
                "taxonomy_lexical_candidates_after": _source_count(tightened_summary, "taxonomy_lexical"),
                "taxonomy_lexical_delta": _delta(_source_count(baseline_summary, "taxonomy_lexical"), _source_count(tightened_summary, "taxonomy_lexical")),
                "top1_precision_before": baseline_eval_summary.get("top1_precision_if_evaluable"),
                "top1_precision_after": tightened_eval.get("top1_precision_if_evaluable"),
                "top3_recall_before": baseline_eval_summary.get("top3_recall_if_evaluable"),
                "top3_recall_after": tightened_eval.get("top3_recall_if_evaluable"),
                "top5_recall_before": baseline_eval_summary.get("top5_recall_if_evaluable"),
                "top5_recall_after": tightened_eval.get("top5_recall_if_evaluable"),
                "candidate_coverage_remains_useful": float(tightened_summary.get("candidate_coverage_rate") or 0.0) >= 0.6,
                "eighty_percent_target_realistic_now": float(tightened_summary.get("candidate_coverage_rate") or 0.0) >= 0.75 and (_risk_count(tightened_summary) / max(_candidate_total(tightened_summary), 1)) <= 0.35,
                "filter_summary": filter_analysis.get("summary") or {},
                "safe_for_auto_apply_count": tightened_summary.get("safe_for_auto_apply_count"),
                "safety": dict(SAFETY),
            },
            "recommendation": recommendation,
        }
    )


def render_tightening_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    baseline = summary.get("baseline") or {}
    tightened = summary.get("tightened") or {}
    rec = report.get("recommendation") or {}
    lines = [
        "# Hybrid Candidate Ranking Tightening Summary #18E-F-A-hotfix-2",
        "",
        "All candidates remain review-only evidence. No candidate is safe for auto-apply.",
        "",
        f"- Rows with >=1 candidate: `{baseline.get('rows_with_at_least_1_candidate')}` -> `{tightened.get('rows_with_at_least_1_candidate')}`",
        f"- Rows with >=3 candidates: `{baseline.get('rows_with_at_least_3_candidates')}` -> `{tightened.get('rows_with_at_least_3_candidates')}`",
        f"- No-candidate rows: `{baseline.get('no_candidate_rows')}` -> `{tightened.get('no_candidate_rows')}`",
        f"- Candidate coverage: `{baseline.get('candidate_coverage_rate')}` -> `{tightened.get('candidate_coverage_rate')}`",
        f"- Candidate total delta: `{summary.get('candidate_total_delta')}`",
        f"- High-risk delta: `{summary.get('high_risk_delta')}`",
        f"- High-risk drop rate: `{summary.get('high_risk_drop_rate')}`",
        f"- Taxonomy lexical candidates: `{summary.get('taxonomy_lexical_candidates_before')}` -> `{summary.get('taxonomy_lexical_candidates_after')}`",
        f"- Top-1 precision: `{summary.get('top1_precision_before')}` -> `{summary.get('top1_precision_after')}`",
        f"- Top-3 recall: `{summary.get('top3_recall_before')}` -> `{summary.get('top3_recall_after')}`",
        f"- Top-5 recall: `{summary.get('top5_recall_before')}` -> `{summary.get('top5_recall_after')}`",
        f"- Recommended next feature: `{rec.get('recommended_next_feature')}`",
        f"- Recommendation reason: {rec.get('reason')}",
    ]
    return "\n".join(lines) + "\n"


def render_filter_analysis_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Hybrid Candidate Ranking Filter Analysis #18E-F-A-hotfix-2",
        "",
        f"- Filtered candidate reasons: `{summary.get('filter_reason_counts')}`",
        f"- Filtered source counts: `{summary.get('filtered_source_counts')}`",
        f"- Rows losing all candidates: `{summary.get('rows_losing_all_candidates')}`",
        f"- Rows with candidate count reduced: `{summary.get('rows_with_candidate_count_reduced')}`",
        f"- Rows improved by filtering: `{summary.get('rows_improved_by_filtering')}`",
        "",
        "| Label | Filtered Candidate Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("labels_most_affected") or []:
        lines.append(f"| {item.get('normalized_label')} | {item.get('filtered_candidate_count')} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = utc_now()

    baseline_report = read_json(args.baseline_report)
    baseline_rows = list(baseline_report.get("ranked_rows") or [])
    mapper_report = read_json(args.mapper_report)
    evaluation_report = read_json(args.evaluation_report)
    records = mapper_records_from_report(mapper_report)
    concepts, metadata_diagnostics = build_concept_catalog(
        records,
        taxonomy_metadata_path=args.taxonomy_metadata,
        allow_missing_taxonomy=args.allow_missing_taxonomy,
    )
    qwen_index, qwen_diagnostics = load_cached_qwen_candidates(
        args.qwen_report_dir,
        allow_missing=args.allow_missing_qwen,
    )
    evidence = load_local_evaluation_evidence(dataset_dir=args.dataset_dir, records=records)

    baseline_eval = evaluate_candidate_rows(
        baseline_rows,
        row_values=evidence.get("row_values") or [],
        facts_by_sample=evidence.get("facts_by_sample") or {},
    )
    tightened_reports = build_reports(
        records=records,
        concepts=concepts,
        evaluation_report=evaluation_report,
        qwen_index=qwen_index,
        row_values=evidence.get("row_values") or [],
        facts_by_sample=evidence.get("facts_by_sample") or {},
        top_n=args.top_n,
        metadata_diagnostics=metadata_diagnostics,
        qwen_diagnostics=qwen_diagnostics,
        filter_mode="tightened",
    )
    filter_analysis = _filter_analysis(
        baseline_rows,
        tightened_reports["ranking"].get("ranked_rows") or [],
        baseline_eval,
        tightened_reports["evaluation"],
    )
    summary_report = _summary_report(
        generated_at=generated_at,
        baseline_rows=baseline_rows,
        tightened_reports=tightened_reports,
        baseline_eval=baseline_eval,
        filter_analysis=filter_analysis,
    )

    tightened = tightened_reports["ranking"]
    tightened["run_metadata"]["feature"] = "18E-F-A-hotfix-2"
    tightened["comparison_summary"] = summary_report["summary"]
    tightened["recommendation"] = summary_report["recommendation"]
    risk_after = tightened_reports["risk_analysis"]
    risk_after["run_metadata"]["feature"] = "18E-F-A-hotfix-2"
    uncovered_after = build_uncovered_report(tightened.get("ranked_rows") or [])
    uncovered_after = {"run_metadata": tightened["run_metadata"], **uncovered_after}

    write_json(output_dir / "hybrid_candidate_ranking_tightened_18e_f_a_hotfix_2.json", tightened)
    write_json(output_dir / "hybrid_candidate_ranking_tightening_summary_18e_f_a_hotfix_2.json", summary_report)
    write_json(output_dir / "hybrid_candidate_ranking_filter_analysis_18e_f_a_hotfix_2.json", filter_analysis)
    write_json(output_dir / "hybrid_candidate_ranking_risk_after_tightening_18e_f_a_hotfix_2.json", risk_after)
    write_json(output_dir / "hybrid_candidate_ranking_uncovered_after_tightening_18e_f_a_hotfix_2.json", uncovered_after)

    (output_dir / "hybrid_candidate_ranking_tightened_18e_f_a_hotfix_2.md").write_text(render_ranking_markdown(tightened), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_tightening_summary_18e_f_a_hotfix_2.md").write_text(render_tightening_summary_markdown(summary_report), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_filter_analysis_18e_f_a_hotfix_2.md").write_text(render_filter_analysis_markdown(filter_analysis), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_risk_after_tightening_18e_f_a_hotfix_2.md").write_text(render_risk_markdown(risk_after), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_uncovered_after_tightening_18e_f_a_hotfix_2.md").write_text(render_uncovered_markdown(uncovered_after), encoding="utf-8")

    summary = summary_report["summary"]
    print(
        {
            "baseline_coverage": summary["baseline"].get("candidate_coverage_rate"),
            "tightened_coverage": summary["tightened"].get("candidate_coverage_rate"),
            "baseline_high_risk": _risk_count(summary["baseline"]),
            "tightened_high_risk": _risk_count(summary["tightened"]),
            "taxonomy_lexical_before": summary.get("taxonomy_lexical_candidates_before"),
            "taxonomy_lexical_after": summary.get("taxonomy_lexical_candidates_after"),
            "top1_before": summary.get("top1_precision_before"),
            "top1_after": summary.get("top1_precision_after"),
            "top3_before": summary.get("top3_recall_before"),
            "top3_after": summary.get("top3_recall_after"),
            "top5_before": summary.get("top5_recall_before"),
            "top5_after": summary.get("top5_recall_after"),
            "recommended_next_feature": summary_report["recommendation"].get("recommended_next_feature"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
