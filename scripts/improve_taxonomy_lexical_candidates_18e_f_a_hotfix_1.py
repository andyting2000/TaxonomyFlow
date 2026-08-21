"""Improve taxonomy lexical candidates with local metadata for #18E-F-A-hotfix-1."""

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
    render_evaluation_markdown,
    render_ranking_markdown,
    render_uncovered_markdown,
    safe_rate,
    summarize_candidate_rows,
    utc_now,
    write_json,
)
from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.taxonomy_concept_metadata import build_metadata_report, render_metadata_markdown
from services.tightened_mapper_evaluation import load_local_evaluation_evidence, sanitize_report_value


FEATURE = "18E-F-A-hotfix-1"
GOOD_TOP_N_STATUSES = {"correct_qname_top1", "correct_qname_top3", "correct_qname_top5"}
ORIGINAL_18E_F_A_HIGH_RISK_COUNT = 1006


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


def _delta(before: int | float | None, after: int | float | None) -> int | float | None:
    if before is None or after is None:
        return None
    return round(after - before, 4) if isinstance(before, float) or isinstance(after, float) else after - before


def _risk_count(summary: Mapping[str, Any]) -> int:
    risk = summary.get("risk_distribution") or summary.get("candidate_risk_distribution") or {}
    return int(risk.get("high") or 0) + int(risk.get("critical") or 0)


def _candidate_total(summary: Mapping[str, Any]) -> int:
    risk = summary.get("risk_distribution") or summary.get("candidate_risk_distribution") or {}
    return sum(int(value) for value in risk.values())


def _source_count(summary: Mapping[str, Any], source: str) -> int:
    return int((summary.get("candidate_source_counts") or {}).get(source) or 0)


def _evaluation_index(report: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {_row_key(row): row for row in report.get("records") or []}


def _override_feature(report: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(report)
    metadata = dict(output.get("run_metadata") or {})
    metadata["feature"] = FEATURE
    output["run_metadata"] = metadata
    return output


def _recommendation(
    *,
    enhanced_summary: Mapping[str, Any],
    baseline_eval_summary: Mapping[str, Any],
    enhanced_eval_summary: Mapping[str, Any],
    metadata_summary: Mapping[str, Any],
) -> dict[str, Any]:
    coverage = float(enhanced_summary.get("candidate_coverage_rate") or 0.0)
    top1_before = baseline_eval_summary.get("top1_precision_if_evaluable")
    top1_after = enhanced_eval_summary.get("top1_precision_if_evaluable")
    top3_before = baseline_eval_summary.get("top3_recall_if_evaluable")
    top3_after = enhanced_eval_summary.get("top3_recall_if_evaluable")
    top5_before = baseline_eval_summary.get("top5_recall_if_evaluable")
    top5_after = enhanced_eval_summary.get("top5_recall_if_evaluable")
    high_after = _risk_count(enhanced_summary)
    total_after = _candidate_total(enhanced_summary)
    noisy_after = total_after > 0 and (high_after / total_after) > 0.5
    top1_preserved = top1_before is not None and top1_after is not None and float(top1_after) >= float(top1_before)
    topn_improved = (
        top3_before is not None
        and top3_after is not None
        and top5_before is not None
        and top5_after is not None
        and (float(top3_after) > float(top3_before) or float(top5_after) > float(top5_before))
    )
    alias_coverage = float(metadata_summary.get("alias_coverage_rate") or 0.0)

    if coverage >= 0.6 and top1_preserved and topn_improved and high_after < ORIGINAL_18E_F_A_HIGH_RISK_COUNT and not noisy_after:
        feature = "Feature #18F-B - Hybrid candidate-ranking hardening and threshold calibration"
        reason = "Metadata-enhanced lexical generation recovered coverage while preserving top-1 precision and keeping high-risk candidates below the original #18E-F-A baseline."
    elif alias_coverage < 0.25:
        feature = "Feature #18E-F-A-hotfix-1B - Expand local taxonomy metadata coverage from safe fixtures"
        reason = "Concept metadata alias coverage remains too low for lexical recovery to be reliable."
    elif noisy_after:
        feature = "Feature #18E-F-A-hotfix-3 - Disable noisy lexical families and require source corroboration"
        reason = "The enhanced candidate list is still dominated by high/critical risk candidates."
    elif coverage < 0.6:
        feature = "Feature #18E-F-A-2 - Add non-lexical local candidate sources for uncovered rows"
        reason = "Coverage remains below 60% after conservative metadata enrichment."
    else:
        feature = "Feature #18F-B - Hybrid candidate-ranking hardening and threshold calibration"
        reason = "Coverage and risk are usable enough for threshold calibration, though not all preferred targets were met."

    return {
        "recommended_next_feature": feature,
        "reason": reason,
        "basis": {
            "candidate_coverage_rate": coverage,
            "top1_precision_before": top1_before,
            "top1_precision_after": top1_after,
            "top3_recall_before": top3_before,
            "top3_recall_after": top3_after,
            "top5_recall_before": top5_before,
            "top5_recall_after": top5_after,
            "top1_preserved": top1_preserved,
            "topn_improved": topn_improved,
            "high_or_critical_candidate_count_after": high_after,
            "candidate_total_after": total_after,
            "candidate_list_too_noisy_after": noisy_after,
            "metadata_alias_coverage_rate": alias_coverage,
        },
    }


def _filter_analysis(
    baseline_rows: Sequence[Mapping[str, Any]],
    enhanced_rows: Sequence[Mapping[str, Any]],
    baseline_eval: Mapping[str, Any],
    enhanced_eval: Mapping[str, Any],
) -> dict[str, Any]:
    base_by_key = {_row_key(row): row for row in baseline_rows}
    enhanced_by_key = {_row_key(row): row for row in enhanced_rows}
    base_eval = _evaluation_index(baseline_eval)
    enhanced_eval_index = _evaluation_index(enhanced_eval)
    filtered_reason_counts: Counter[str] = Counter()
    still_uncovered_labels: Counter[str] = Counter()
    newly_covered_labels: Counter[str] = Counter()
    recovered_rows = []
    recovered_true_positive_rows = []
    new_false_positive_or_wrong_candidate_rows = []
    rows_losing_all_candidates = []

    for key, enhanced in enhanced_by_key.items():
        baseline = base_by_key.get(key) or {}
        label = str(enhanced.get("normalized_label") or canonical_label(enhanced.get("pdf_label")))
        for candidate in enhanced.get("filtered_candidates") or []:
            for reason in candidate.get("filter_reasons") or []:
                filtered_reason_counts[str(reason)] += 1
        before_count = int(baseline.get("candidate_count") or 0)
        after_count = int(enhanced.get("candidate_count") or 0)
        after_status = str((enhanced_eval_index.get(key) or {}).get("evaluation_status") or "")
        before_status = str((base_eval.get(key) or {}).get("evaluation_status") or "")
        if before_count == 0 and after_count > 0:
            newly_covered_labels[label] += 1
            row = {
                "sample_id": enhanced.get("sample_id"),
                "row_id": enhanced.get("row_id"),
                "normalized_label": label,
                "baseline_candidate_count": before_count,
                "enhanced_candidate_count": after_count,
                "before_status": before_status,
                "after_status": after_status,
                "top_candidate": (enhanced.get("candidates") or [{}])[0],
            }
            recovered_rows.append(row)
            if after_status in GOOD_TOP_N_STATUSES:
                recovered_true_positive_rows.append(row)
            elif after_status == "correct_qname_not_in_candidates":
                new_false_positive_or_wrong_candidate_rows.append(row)
        if before_count > 0 and after_count == 0:
            rows_losing_all_candidates.append(
                {
                    "sample_id": enhanced.get("sample_id"),
                    "row_id": enhanced.get("row_id"),
                    "normalized_label": label,
                    "baseline_candidate_count": before_count,
                    "filtered_candidate_count": enhanced.get("filtered_candidate_count"),
                    "filtered_candidates": enhanced.get("filtered_candidates"),
                }
            )
        if after_count == 0:
            still_uncovered_labels[label] += 1

    return sanitize_report_value(
        {
            "run_metadata": {"feature": FEATURE, "generated_at": utc_now(), "offline_only": True, **SAFETY},
            "summary": {
                "recovered_row_count": len(recovered_rows),
                "recovered_true_positive_count": len(recovered_true_positive_rows),
                "new_false_positive_or_wrong_candidate_count": len(new_false_positive_or_wrong_candidate_rows),
                "rows_losing_all_candidates": len(rows_losing_all_candidates),
                "filtered_reason_counts": dict(sorted(filtered_reason_counts.items())),
                "newly_covered_labels": [
                    {"normalized_label": label, "count": count}
                    for label, count in newly_covered_labels.most_common(40)
                ],
                "top_still_uncovered_labels": [
                    {"normalized_label": label, "count": count}
                    for label, count in still_uncovered_labels.most_common(40)
                ],
                "safe_for_auto_apply_count": 0,
                "safety": dict(SAFETY),
            },
            "recovered_rows": recovered_rows[:250],
            "recovered_true_positive_rows": recovered_true_positive_rows[:120],
            "new_false_positive_or_wrong_candidate_rows": new_false_positive_or_wrong_candidate_rows[:120],
            "rows_losing_all_candidates": rows_losing_all_candidates[:120],
        }
    )


def _summary_report(
    *,
    generated_at: str,
    baseline_rows: Sequence[Mapping[str, Any]],
    enhanced_reports: Mapping[str, Mapping[str, Any]],
    baseline_eval: Mapping[str, Any],
    metadata_report: Mapping[str, Any],
    filter_analysis: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_summary = summarize_candidate_rows(baseline_rows)
    enhanced_summary = enhanced_reports["summary"]["summary"]
    enhanced_eval = enhanced_reports["evaluation"]["summary"]
    baseline_eval_summary = baseline_eval["summary"]
    recommendation = _recommendation(
        enhanced_summary=enhanced_summary,
        baseline_eval_summary=baseline_eval_summary,
        enhanced_eval_summary=enhanced_eval,
        metadata_summary=metadata_report.get("summary") or {},
    )
    return sanitize_report_value(
        {
            "run_metadata": {"feature": FEATURE, "generated_at": generated_at, "offline_only": True, **SAFETY},
            "summary": {
                "baseline": baseline_summary,
                "metadata_enhanced": enhanced_summary,
                "coverage_delta": _delta(baseline_summary.get("candidate_coverage_rate"), enhanced_summary.get("candidate_coverage_rate")),
                "rows_with_at_least_1_candidate_delta": _delta(baseline_summary.get("rows_with_at_least_1_candidate"), enhanced_summary.get("rows_with_at_least_1_candidate")),
                "rows_with_at_least_3_candidates_delta": _delta(baseline_summary.get("rows_with_at_least_3_candidates"), enhanced_summary.get("rows_with_at_least_3_candidates")),
                "no_candidate_rows_delta": _delta(baseline_summary.get("no_candidate_rows"), enhanced_summary.get("no_candidate_rows")),
                "candidate_total_delta": _delta(_candidate_total(baseline_summary), _candidate_total(enhanced_summary)),
                "high_risk_delta": _delta(_risk_count(baseline_summary), _risk_count(enhanced_summary)),
                "high_risk_vs_original_18e_f_a_baseline": {
                    "original_18e_f_a_high_or_critical_candidate_count": ORIGINAL_18E_F_A_HIGH_RISK_COUNT,
                    "metadata_enhanced_high_or_critical_candidate_count": _risk_count(enhanced_summary),
                    "materially_below_original_baseline": _risk_count(enhanced_summary) < ORIGINAL_18E_F_A_HIGH_RISK_COUNT,
                },
                "taxonomy_lexical_candidates_before": _source_count(baseline_summary, "taxonomy_lexical"),
                "taxonomy_lexical_candidates_after": _source_count(enhanced_summary, "taxonomy_lexical"),
                "taxonomy_lexical_delta": _delta(_source_count(baseline_summary, "taxonomy_lexical"), _source_count(enhanced_summary, "taxonomy_lexical")),
                "top1_precision_before": baseline_eval_summary.get("top1_precision_if_evaluable"),
                "top1_precision_after": enhanced_eval.get("top1_precision_if_evaluable"),
                "top3_recall_before": baseline_eval_summary.get("top3_recall_if_evaluable"),
                "top3_recall_after": enhanced_eval.get("top3_recall_if_evaluable"),
                "top5_recall_before": baseline_eval_summary.get("top5_recall_if_evaluable"),
                "top5_recall_after": enhanced_eval.get("top5_recall_if_evaluable"),
                "metadata_summary": metadata_report.get("summary") or {},
                "filter_summary": filter_analysis.get("summary") or {},
                "safe_for_auto_apply_count": enhanced_summary.get("safe_for_auto_apply_count"),
                "safety": dict(SAFETY),
            },
            "recommendation": recommendation,
        }
    )


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    baseline = summary.get("baseline") or {}
    enhanced = summary.get("metadata_enhanced") or {}
    rec = report.get("recommendation") or {}
    lines = [
        "# Hybrid Candidate Ranking Metadata Summary #18E-F-A-hotfix-1",
        "",
        "All candidates remain review-only evidence. No candidate is safe for auto-apply.",
        "",
        f"- Rows with >=1 candidate: `{baseline.get('rows_with_at_least_1_candidate')}` -> `{enhanced.get('rows_with_at_least_1_candidate')}`",
        f"- Rows with >=3 candidates: `{baseline.get('rows_with_at_least_3_candidates')}` -> `{enhanced.get('rows_with_at_least_3_candidates')}`",
        f"- No-candidate rows: `{baseline.get('no_candidate_rows')}` -> `{enhanced.get('no_candidate_rows')}`",
        f"- Candidate coverage: `{baseline.get('candidate_coverage_rate')}` -> `{enhanced.get('candidate_coverage_rate')}`",
        f"- Candidate total delta: `{summary.get('candidate_total_delta')}`",
        f"- High-risk delta: `{summary.get('high_risk_delta')}`",
        f"- Taxonomy lexical candidates: `{summary.get('taxonomy_lexical_candidates_before')}` -> `{summary.get('taxonomy_lexical_candidates_after')}`",
        f"- Top-1 precision: `{summary.get('top1_precision_before')}` -> `{summary.get('top1_precision_after')}`",
        f"- Top-3 recall: `{summary.get('top3_recall_before')}` -> `{summary.get('top3_recall_after')}`",
        f"- Top-5 recall: `{summary.get('top5_recall_before')}` -> `{summary.get('top5_recall_after')}`",
        f"- Recovered rows: `{(summary.get('filter_summary') or {}).get('recovered_row_count')}`",
        f"- Recovered true positives: `{(summary.get('filter_summary') or {}).get('recovered_true_positive_count')}`",
        f"- New wrong-candidate rows: `{(summary.get('filter_summary') or {}).get('new_false_positive_or_wrong_candidate_count')}`",
        f"- Recommended next feature: `{rec.get('recommended_next_feature')}`",
        f"- Recommendation reason: {rec.get('reason')}",
    ]
    return "\n".join(lines) + "\n"


def render_filter_analysis_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Hybrid Candidate Ranking Metadata Filter Analysis #18E-F-A-hotfix-1",
        "",
        f"- Recovered rows: `{summary.get('recovered_row_count')}`",
        f"- Recovered true positives: `{summary.get('recovered_true_positive_count')}`",
        f"- New wrong-candidate rows: `{summary.get('new_false_positive_or_wrong_candidate_count')}`",
        f"- Rows losing all candidates: `{summary.get('rows_losing_all_candidates')}`",
        f"- Filtered reason counts: `{summary.get('filtered_reason_counts')}`",
        "",
        "| Newly covered label | Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("newly_covered_labels") or []:
        lines.append(f"| {item.get('normalized_label')} | {item.get('count')} |")
    lines.extend(["", "| Still uncovered label | Count |", "| --- | ---: |"])
    for item in summary.get("top_still_uncovered_labels") or []:
        lines.append(f"| {item.get('normalized_label')} | {item.get('count')} |")
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
    enhanced_reports = build_reports(
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
    enhanced_ranking = _override_feature(enhanced_reports["ranking"])
    enhanced_evaluation = _override_feature(enhanced_reports["evaluation"])
    enhanced_uncovered = {"run_metadata": enhanced_ranking["run_metadata"], **build_uncovered_report(enhanced_ranking.get("ranked_rows") or [])}
    metadata_report = build_metadata_report(concepts, metadata_diagnostics, feature=FEATURE)
    filter_analysis = _filter_analysis(
        baseline_rows,
        enhanced_ranking.get("ranked_rows") or [],
        baseline_eval,
        enhanced_evaluation,
    )
    summary_report = _summary_report(
        generated_at=generated_at,
        baseline_rows=baseline_rows,
        enhanced_reports={**enhanced_reports, "ranking": enhanced_ranking, "evaluation": enhanced_evaluation},
        baseline_eval=baseline_eval,
        metadata_report=metadata_report,
        filter_analysis=filter_analysis,
    )
    enhanced_ranking["comparison_summary"] = summary_report["summary"]
    enhanced_ranking["recommendation"] = summary_report["recommendation"]
    enhanced_evaluation["run_metadata"]["feature"] = FEATURE
    enhanced_uncovered["run_metadata"]["feature"] = FEATURE

    write_json(output_dir / "taxonomy_concept_metadata_18e_f_a_hotfix_1.json", metadata_report)
    write_json(output_dir / "hybrid_candidate_ranking_metadata_enhanced_18e_f_a_hotfix_1.json", enhanced_ranking)
    write_json(output_dir / "hybrid_candidate_ranking_metadata_summary_18e_f_a_hotfix_1.json", summary_report)
    write_json(output_dir / "hybrid_candidate_ranking_metadata_evaluation_18e_f_a_hotfix_1.json", enhanced_evaluation)
    write_json(output_dir / "hybrid_candidate_ranking_metadata_filter_analysis_18e_f_a_hotfix_1.json", filter_analysis)
    write_json(output_dir / "hybrid_candidate_ranking_metadata_uncovered_18e_f_a_hotfix_1.json", enhanced_uncovered)

    (output_dir / "taxonomy_concept_metadata_18e_f_a_hotfix_1.md").write_text(render_metadata_markdown(metadata_report), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_metadata_enhanced_18e_f_a_hotfix_1.md").write_text(render_ranking_markdown(enhanced_ranking), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_metadata_summary_18e_f_a_hotfix_1.md").write_text(render_summary_markdown(summary_report), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_metadata_evaluation_18e_f_a_hotfix_1.md").write_text(render_evaluation_markdown(enhanced_evaluation), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_metadata_filter_analysis_18e_f_a_hotfix_1.md").write_text(render_filter_analysis_markdown(filter_analysis), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_metadata_uncovered_18e_f_a_hotfix_1.md").write_text(render_uncovered_markdown(enhanced_uncovered), encoding="utf-8")

    summary = summary_report["summary"]
    print(
        {
            "baseline_coverage": summary["baseline"].get("candidate_coverage_rate"),
            "metadata_enhanced_coverage": summary["metadata_enhanced"].get("candidate_coverage_rate"),
            "baseline_high_risk": _risk_count(summary["baseline"]),
            "metadata_enhanced_high_risk": _risk_count(summary["metadata_enhanced"]),
            "taxonomy_lexical_before": summary.get("taxonomy_lexical_candidates_before"),
            "taxonomy_lexical_after": summary.get("taxonomy_lexical_candidates_after"),
            "top1_before": summary.get("top1_precision_before"),
            "top1_after": summary.get("top1_precision_after"),
            "top3_before": summary.get("top3_recall_before"),
            "top3_after": summary.get("top3_recall_after"),
            "top5_before": summary.get("top5_recall_before"),
            "top5_after": summary.get("top5_recall_after"),
            "recovered_rows": (summary.get("filter_summary") or {}).get("recovered_row_count"),
            "new_wrong_candidate_rows": (summary.get("filter_summary") or {}).get("new_false_positive_or_wrong_candidate_count"),
            "recommended_next_feature": summary_report["recommendation"].get("recommended_next_feature"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
