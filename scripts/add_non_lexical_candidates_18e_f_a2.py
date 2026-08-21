"""Add local non-lexical candidate sources for #18E-F-A-2."""

from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.hybrid_candidate_ranking_mapper import (
    SAFETY,
    build_concept_catalog,
    build_risk_analysis_report,
    build_uncovered_report,
    evaluate_candidate_rows,
    rank_candidate_rows,
    read_json,
    render_evaluation_markdown,
    render_ranking_markdown,
    render_uncovered_markdown,
    safe_rate,
    summarize_candidate_rows,
    utc_now,
    write_json,
)
from services.local_candidate_sources import (
    build_local_candidate_sources_report,
    load_concept_playbook_cards,
    render_local_candidate_sources_markdown,
)
from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.tightened_mapper_evaluation import load_local_evaluation_evidence, sanitize_report_value


FEATURE = "18E-F-A-2"
GOOD_TOP_N_STATUSES = {"correct_qname_top1", "correct_qname_top3", "correct_qname_top5"}
ORIGINAL_18E_F_A_HIGH_RISK_COUNT = 1006


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--baseline-report", required=True)
    parser.add_argument("--evaluation-report", required=True)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--allow-missing-concept-cards", action="store_true")
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


def _evaluation_index(report: Mapping[str, Any]) -> dict[tuple[str, str], Mapping[str, Any]]:
    return {_row_key(row): row for row in report.get("records") or []}


def _override_feature(report: Mapping[str, Any], generated_at: str) -> dict[str, Any]:
    output = dict(report)
    metadata = dict(output.get("run_metadata") or {})
    metadata["feature"] = FEATURE
    metadata["generated_at"] = generated_at
    output["run_metadata"] = metadata
    return output


def _source_evaluation(rows: Sequence[Mapping[str, Any]], evaluation: Mapping[str, Any]) -> dict[str, Any]:
    eval_index = _evaluation_index(evaluation)
    source_rows: dict[str, set[tuple[str, str]]] = defaultdict(set)
    source_top1_rows: dict[str, set[tuple[str, str]]] = defaultdict(set)
    source_correct_rows: dict[str, set[tuple[str, str]]] = defaultdict(set)
    unique_support = 0
    for row in rows:
        key = _row_key(row)
        eval_item = eval_index.get(key) or {}
        status = str(eval_item.get("evaluation_status") or "")
        rank = eval_item.get("correct_candidate_rank")
        has_unique_support = status in {"correct_qname_top1", "correct_qname_top3", "correct_qname_top5", "correct_qname_below_top5", "correct_qname_not_in_candidates"}
        if has_unique_support:
            unique_support += 1
        for candidate in row.get("candidates") or []:
            sources = [str(source) for source in candidate.get("candidate_sources_combined") or []]
            for source in sources:
                source_rows[source].add(key)
        top = (row.get("candidates") or [{}])[0]
        for source in top.get("candidate_sources_combined") or []:
            source_top1_rows[str(source)].add(key)
            if status == "correct_qname_top1":
                source_correct_rows[str(source)].add(key)
        if isinstance(rank, int) and rank > 1:
            candidates = row.get("candidates") or []
            if rank <= len(candidates):
                correct_candidate = candidates[rank - 1]
                for source in correct_candidate.get("candidate_sources_combined") or []:
                    source_correct_rows[str(source)].add(key)
    records = []
    for source in sorted(source_rows):
        rows_with_source = source_rows[source]
        rows_with_local_support = {
            key
            for key in rows_with_source
            if str((eval_index.get(key) or {}).get("evaluation_status") or "")
            in {"correct_qname_top1", "correct_qname_top3", "correct_qname_top5", "correct_qname_below_top5", "correct_qname_not_in_candidates"}
        }
        top1_hits = {
            key
            for key in source_top1_rows.get(source, set())
            if str((eval_index.get(key) or {}).get("evaluation_status") or "") == "correct_qname_top1"
        }
        records.append(
            {
                "source": source,
                "rows_with_source": len(rows_with_source),
                "candidate_rows_with_local_support": len(rows_with_local_support),
                "top1_hits_when_source_on_top": len(top1_hits),
                "correct_candidate_rows_with_source": len(source_correct_rows.get(source, set())),
                "top1_precision_if_source_on_top": safe_rate(len(top1_hits), len(source_top1_rows.get(source, set()) & rows_with_local_support)),
                "top5_recall_if_source_present": safe_rate(len(source_correct_rows.get(source, set())), unique_support),
            }
        )
    return {"unique_support_rows": unique_support, "sources": records}


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
    newly_covered_labels: Counter[str] = Counter()
    still_uncovered_labels: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    source_row_counts: Counter[str] = Counter()
    recovered_rows = []
    recovered_true_positive_rows = []
    new_wrong_candidate_rows = []
    rows_losing_all_candidates = []
    new_high_risk_rows = []

    for key, enhanced in enhanced_by_key.items():
        baseline = base_by_key.get(key) or {}
        before_count = int(baseline.get("candidate_count") or 0)
        after_count = int(enhanced.get("candidate_count") or 0)
        label = str(enhanced.get("normalized_label") or canonical_label(enhanced.get("pdf_label")))
        before_status = str((base_eval.get(key) or {}).get("evaluation_status") or "")
        after_status = str((enhanced_eval_index.get(key) or {}).get("evaluation_status") or "")
        local_sources = set()
        for candidate in enhanced.get("candidates") or []:
            for source in candidate.get("candidate_sources_combined") or []:
                if source in {
                    "statement_role_pack",
                    "section_concept_pack",
                    "concept_playbook_lookup",
                    "taxonomy_structure_hint",
                    "note_total_candidate",
                    "cash_flow_movement_pack",
                    "equity_movement_pack",
                    "format_memory_pack",
                    "local_concept_family_pack",
                }:
                    source_counts[str(source)] += 1
                    local_sources.add(str(source))
        for source in local_sources:
            source_row_counts[source] += 1

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
                "local_sources": sorted(local_sources),
                "top_candidate": (enhanced.get("candidates") or [{}])[0],
            }
            recovered_rows.append(row)
            if after_status in GOOD_TOP_N_STATUSES:
                recovered_true_positive_rows.append(row)
            elif after_status == "correct_qname_not_in_candidates":
                new_wrong_candidate_rows.append(row)
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
        if before_count == 0 and any(candidate.get("risk_level") in {"high", "critical"} for candidate in enhanced.get("candidates") or []):
            new_high_risk_rows.append({"sample_id": enhanced.get("sample_id"), "row_id": enhanced.get("row_id"), "normalized_label": label})

    return sanitize_report_value(
        {
            "run_metadata": {"feature": FEATURE, "generated_at": utc_now(), "offline_only": True, **SAFETY},
            "summary": {
                "recovered_row_count": len(recovered_rows),
                "recovered_true_positive_count": len(recovered_true_positive_rows),
                "new_wrong_candidate_rows": len(new_wrong_candidate_rows),
                "rows_losing_all_candidates": len(rows_losing_all_candidates),
                "newly_covered_high_or_critical_risk_rows": len(new_high_risk_rows),
                "local_source_candidate_counts": dict(sorted(source_counts.items())),
                "local_source_row_counts": dict(sorted(source_row_counts.items())),
                "newly_covered_labels": [
                    {"normalized_label": label, "count": count} for label, count in newly_covered_labels.most_common(40)
                ],
                "top_still_uncovered_labels": [
                    {"normalized_label": label, "count": count} for label, count in still_uncovered_labels.most_common(40)
                ],
                "safe_for_auto_apply_count": 0,
                "safety": dict(SAFETY),
            },
            "recovered_rows": recovered_rows[:250],
            "recovered_true_positive_rows": recovered_true_positive_rows[:120],
            "new_wrong_candidate_rows": new_wrong_candidate_rows[:120],
            "new_high_risk_rows": new_high_risk_rows[:120],
            "rows_losing_all_candidates": rows_losing_all_candidates[:120],
        }
    )


def _recommendation(
    *,
    enhanced_summary: Mapping[str, Any],
    enhanced_eval_summary: Mapping[str, Any],
    baseline_eval_summary: Mapping[str, Any],
    filter_summary: Mapping[str, Any],
    concept_card_summary: Mapping[str, Any],
) -> dict[str, Any]:
    coverage = float(enhanced_summary.get("candidate_coverage_rate") or 0.0)
    top1 = enhanced_eval_summary.get("top1_precision_if_evaluable")
    top3 = enhanced_eval_summary.get("top3_recall_if_evaluable")
    top5 = enhanced_eval_summary.get("top5_recall_if_evaluable")
    top3_before = baseline_eval_summary.get("top3_recall_if_evaluable")
    top5_before = baseline_eval_summary.get("top5_recall_if_evaluable")
    high_count = _risk_count(enhanced_summary)
    total = _candidate_total(enhanced_summary)
    noisy = bool(total and high_count / total > 0.45)
    new_wrong = int(filter_summary.get("new_wrong_candidate_rows") or 0)
    recovered_true = int(filter_summary.get("recovered_true_positive_count") or 0)
    cards_loaded = int(concept_card_summary.get("concept_card_count") or 0)
    topn_improved = (
        top3_before is not None
        and top5_before is not None
        and top3 is not None
        and top5 is not None
        and (float(top3) >= float(top3_before) or float(top5) >= float(top5_before))
    )

    if coverage >= 0.6 and (top1 is None or float(top1) >= 0.68) and topn_improved and high_count < ORIGINAL_18E_F_A_HIGH_RISK_COUNT and new_wrong <= max(4, recovered_true):
        feature = "Feature #18F-B - Hybrid candidate-ranking hardening and threshold calibration"
        reason = "Coverage is now at or above 60% with preserved top-N quality and controlled review-only risk."
    elif cards_loaded == 0:
        feature = "Feature #18E-F-A-hotfix-1B - Build explicit local concept metadata seed from taxonomy/MBRS concept cards"
        reason = "Concept cards/playbooks are unavailable or insufficient for local structured candidate generation."
    elif noisy or new_wrong > max(4, recovered_true):
        feature = "Feature #18E-F-A-2-hotfix-1 - Tighten local candidate source gates"
        reason = "The non-lexical sources introduced too much review noise relative to recovered true positives."
    elif coverage < 0.6:
        feature = "Feature #18E-F-A-3 - Add statement-specific candidate packs for remaining uncovered rows"
        reason = "Coverage remains below 60% after local non-lexical sources."
    else:
        feature = "Feature #18F-B - Hybrid candidate-ranking hardening and threshold calibration"
        reason = "Coverage and risk are usable enough for calibration, though not every preferred metric improved."

    return {
        "recommended_next_feature": feature,
        "reason": reason,
        "basis": {
            "candidate_coverage_rate": coverage,
            "top1_precision_if_evaluable": top1,
            "top3_recall_if_evaluable": top3,
            "top5_recall_if_evaluable": top5,
            "topn_preserved_or_improved": topn_improved,
            "high_or_critical_candidate_count": high_count,
            "candidate_total": total,
            "candidate_list_too_noisy": noisy,
            "new_wrong_candidate_rows": new_wrong,
            "recovered_true_positive_count": recovered_true,
            "concept_card_count": cards_loaded,
        },
    }


def _summary_report(
    *,
    generated_at: str,
    baseline_rows: Sequence[Mapping[str, Any]],
    enhanced_rows: Sequence[Mapping[str, Any]],
    baseline_eval: Mapping[str, Any],
    enhanced_eval: Mapping[str, Any],
    risk_report: Mapping[str, Any],
    source_report: Mapping[str, Any],
    filter_analysis: Mapping[str, Any],
) -> dict[str, Any]:
    baseline_summary = summarize_candidate_rows(baseline_rows)
    enhanced_summary = summarize_candidate_rows(enhanced_rows)
    baseline_eval_summary = baseline_eval.get("summary") or {}
    enhanced_eval_summary = enhanced_eval.get("summary") or {}
    concept_card_summary = ((source_report.get("summary") or {}).get("concept_cards") or {})
    recommendation = _recommendation(
        enhanced_summary=enhanced_summary,
        enhanced_eval_summary=enhanced_eval_summary,
        baseline_eval_summary=baseline_eval_summary,
        filter_summary=filter_analysis.get("summary") or {},
        concept_card_summary=concept_card_summary,
    )
    return sanitize_report_value(
        {
            "run_metadata": {"feature": FEATURE, "generated_at": generated_at, "offline_only": True, **SAFETY},
            "summary": {
                "baseline": baseline_summary,
                "non_lexical_enhanced": enhanced_summary,
                "coverage_delta": _delta(baseline_summary.get("candidate_coverage_rate"), enhanced_summary.get("candidate_coverage_rate")),
                "rows_with_at_least_1_candidate_delta": _delta(baseline_summary.get("rows_with_at_least_1_candidate"), enhanced_summary.get("rows_with_at_least_1_candidate")),
                "rows_with_at_least_3_candidates_delta": _delta(baseline_summary.get("rows_with_at_least_3_candidates"), enhanced_summary.get("rows_with_at_least_3_candidates")),
                "no_candidate_rows_delta": _delta(baseline_summary.get("no_candidate_rows"), enhanced_summary.get("no_candidate_rows")),
                "candidate_total_delta": _delta(_candidate_total(baseline_summary), _candidate_total(enhanced_summary)),
                "high_risk_delta": _delta(_risk_count(baseline_summary), _risk_count(enhanced_summary)),
                "high_risk_vs_original_18e_f_a_baseline": {
                    "original_18e_f_a_high_or_critical_candidate_count": ORIGINAL_18E_F_A_HIGH_RISK_COUNT,
                    "non_lexical_enhanced_high_or_critical_candidate_count": _risk_count(enhanced_summary),
                    "materially_below_original_baseline": _risk_count(enhanced_summary) < ORIGINAL_18E_F_A_HIGH_RISK_COUNT,
                },
                "top1_precision_before": baseline_eval_summary.get("top1_precision_if_evaluable"),
                "top1_precision_after": enhanced_eval_summary.get("top1_precision_if_evaluable"),
                "top3_recall_before": baseline_eval_summary.get("top3_recall_if_evaluable"),
                "top3_recall_after": enhanced_eval_summary.get("top3_recall_if_evaluable"),
                "top5_recall_before": baseline_eval_summary.get("top5_recall_if_evaluable"),
                "top5_recall_after": enhanced_eval_summary.get("top5_recall_if_evaluable"),
                "risk_summary": risk_report.get("summary") or {},
                "source_summary": source_report.get("summary") or {},
                "filter_summary": filter_analysis.get("summary") or {},
                "source_specific_evaluation": _source_evaluation(enhanced_rows, enhanced_eval),
                "eighty_percent_candidate_coverage_path_realistic": bool(float(enhanced_summary.get("candidate_coverage_rate") or 0.0) >= 0.7),
                "safe_for_auto_apply_count": enhanced_summary.get("safe_for_auto_apply_count"),
                "safety": dict(SAFETY),
            },
            "recommendation": recommendation,
        }
    )


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    baseline = summary.get("baseline") or {}
    enhanced = summary.get("non_lexical_enhanced") or {}
    rec = report.get("recommendation") or {}
    lines = [
        "# Hybrid Candidate Ranking Non-Lexical Summary #18E-F-A-2",
        "",
        "All candidates remain review-only evidence. No candidate is safe for auto-apply.",
        "",
        f"- Rows with >=1 candidate: `{baseline.get('rows_with_at_least_1_candidate')}` -> `{enhanced.get('rows_with_at_least_1_candidate')}`",
        f"- Rows with >=3 candidates: `{baseline.get('rows_with_at_least_3_candidates')}` -> `{enhanced.get('rows_with_at_least_3_candidates')}`",
        f"- No-candidate rows: `{baseline.get('no_candidate_rows')}` -> `{enhanced.get('no_candidate_rows')}`",
        f"- Candidate coverage: `{baseline.get('candidate_coverage_rate')}` -> `{enhanced.get('candidate_coverage_rate')}`",
        f"- Candidate total delta: `{summary.get('candidate_total_delta')}`",
        f"- High-risk delta: `{summary.get('high_risk_delta')}`",
        f"- Top-1 precision: `{summary.get('top1_precision_before')}` -> `{summary.get('top1_precision_after')}`",
        f"- Top-3 recall: `{summary.get('top3_recall_before')}` -> `{summary.get('top3_recall_after')}`",
        f"- Top-5 recall: `{summary.get('top5_recall_before')}` -> `{summary.get('top5_recall_after')}`",
        f"- Recovered rows: `{(summary.get('filter_summary') or {}).get('recovered_row_count')}`",
        f"- Recovered true positives: `{(summary.get('filter_summary') or {}).get('recovered_true_positive_count')}`",
        f"- New wrong-candidate rows: `{(summary.get('filter_summary') or {}).get('new_wrong_candidate_rows')}`",
        f"- 80% path realistic now: `{summary.get('eighty_percent_candidate_coverage_path_realistic')}`",
        f"- Recommended next feature: `{rec.get('recommended_next_feature')}`",
        f"- Recommendation reason: {rec.get('reason')}",
    ]
    return "\n".join(lines) + "\n"


def render_filter_analysis_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Hybrid Candidate Ranking Non-Lexical Filter Analysis #18E-F-A-2",
        "",
        f"- Recovered rows: `{summary.get('recovered_row_count')}`",
        f"- Recovered true positives: `{summary.get('recovered_true_positive_count')}`",
        f"- New wrong-candidate rows: `{summary.get('new_wrong_candidate_rows')}`",
        f"- Rows losing all candidates: `{summary.get('rows_losing_all_candidates')}`",
        f"- Local source candidate counts: `{summary.get('local_source_candidate_counts')}`",
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
    if not baseline_rows:
        raise ValueError(f"Baseline report has no ranked_rows: {args.baseline_report}")

    _ = read_json(args.evaluation_report)
    concepts, metadata_diagnostics = build_concept_catalog([], allow_missing_taxonomy=True)
    concept_cards, concept_card_diagnostics = load_concept_playbook_cards(allow_missing=args.allow_missing_concept_cards)
    concept_card_diagnostics["taxonomy_metadata_status"] = metadata_diagnostics.get("status")

    source_report = build_local_candidate_sources_report(
        baseline_rows,
        concept_cards=concept_cards,
        concept_card_diagnostics=concept_card_diagnostics,
        concepts=concepts,
    )
    enhanced_rows = rank_candidate_rows(
        baseline_rows,
        concepts=concepts,
        evaluation_report=None,
        qwen_index={},
        local_concept_cards=concept_cards,
        top_n=args.top_n,
        filter_mode="tightened",
        enable_local_sources=True,
        include_existing_candidates=True,
        include_standard_sources=False,
    )

    evidence = load_local_evaluation_evidence(dataset_dir=args.dataset_dir, records=baseline_rows)
    baseline_eval = evaluate_candidate_rows(
        baseline_rows,
        row_values=evidence.get("row_values") or [],
        facts_by_sample=evidence.get("facts_by_sample") or {},
    )
    enhanced_eval = evaluate_candidate_rows(
        enhanced_rows,
        row_values=evidence.get("row_values") or [],
        facts_by_sample=evidence.get("facts_by_sample") or {},
    )
    enhanced_summary = summarize_candidate_rows(enhanced_rows)
    risk_report = {"run_metadata": {"feature": FEATURE, "generated_at": generated_at, "offline_only": True, **SAFETY}, **build_risk_analysis_report(enhanced_rows)}
    uncovered_report = {"run_metadata": {"feature": FEATURE, "generated_at": generated_at, "offline_only": True, **SAFETY}, **build_uncovered_report(enhanced_rows)}
    filter_analysis = _filter_analysis(baseline_rows, enhanced_rows, baseline_eval, enhanced_eval)
    summary_report = _summary_report(
        generated_at=generated_at,
        baseline_rows=baseline_rows,
        enhanced_rows=enhanced_rows,
        baseline_eval=baseline_eval,
        enhanced_eval=enhanced_eval,
        risk_report=risk_report,
        source_report=source_report,
        filter_analysis=filter_analysis,
    )
    ranking_report = sanitize_report_value(
        {
            "run_metadata": {
                "feature": FEATURE,
                "generated_at": generated_at,
                "top_n": args.top_n,
                "baseline_report": args.baseline_report,
                "evaluation_report_for_metrics_only": args.evaluation_report,
                "filter_mode": "tightened",
                "offline_only": True,
                **SAFETY,
            },
            "summary": enhanced_summary,
            "metadata_diagnostics": metadata_diagnostics,
            "local_candidate_source_summary": source_report.get("summary") or {},
            "comparison_summary": summary_report.get("summary") or {},
            "recommendation": summary_report.get("recommendation") or {},
            "ranked_rows": enhanced_rows,
        }
    )
    evaluation_report_out = _override_feature({"summary": enhanced_eval["summary"], "records": enhanced_eval["records"]}, generated_at)
    filter_analysis["run_metadata"]["generated_at"] = generated_at

    write_json(output_dir / "local_candidate_sources_18e_f_a2.json", source_report)
    write_json(output_dir / "hybrid_candidate_ranking_non_lexical_18e_f_a2.json", ranking_report)
    write_json(output_dir / "hybrid_candidate_ranking_non_lexical_summary_18e_f_a2.json", summary_report)
    write_json(output_dir / "hybrid_candidate_ranking_non_lexical_evaluation_18e_f_a2.json", evaluation_report_out)
    write_json(output_dir / "hybrid_candidate_ranking_non_lexical_filter_analysis_18e_f_a2.json", filter_analysis)
    write_json(output_dir / "hybrid_candidate_ranking_non_lexical_uncovered_18e_f_a2.json", uncovered_report)

    (output_dir / "local_candidate_sources_18e_f_a2.md").write_text(render_local_candidate_sources_markdown(source_report), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_non_lexical_18e_f_a2.md").write_text(render_ranking_markdown(ranking_report), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_non_lexical_summary_18e_f_a2.md").write_text(render_summary_markdown(summary_report), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_non_lexical_evaluation_18e_f_a2.md").write_text(render_evaluation_markdown(evaluation_report_out), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_non_lexical_filter_analysis_18e_f_a2.md").write_text(render_filter_analysis_markdown(filter_analysis), encoding="utf-8")
    (output_dir / "hybrid_candidate_ranking_non_lexical_uncovered_18e_f_a2.md").write_text(render_uncovered_markdown(uncovered_report), encoding="utf-8")

    summary = summary_report["summary"]
    print(
        {
            "baseline_coverage": summary["baseline"].get("candidate_coverage_rate"),
            "non_lexical_coverage": summary["non_lexical_enhanced"].get("candidate_coverage_rate"),
            "baseline_high_risk": _risk_count(summary["baseline"]),
            "non_lexical_high_risk": _risk_count(summary["non_lexical_enhanced"]),
            "top1_before": summary.get("top1_precision_before"),
            "top1_after": summary.get("top1_precision_after"),
            "top3_before": summary.get("top3_recall_before"),
            "top3_after": summary.get("top3_recall_after"),
            "top5_before": summary.get("top5_recall_before"),
            "top5_after": summary.get("top5_recall_after"),
            "recovered_rows": (summary.get("filter_summary") or {}).get("recovered_row_count"),
            "new_wrong_candidate_rows": (summary.get("filter_summary") or {}).get("new_wrong_candidate_rows"),
            "recommended_next_feature": summary_report["recommendation"].get("recommended_next_feature"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
