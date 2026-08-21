"""Calibrate hybrid candidate-ranking profiles for Feature #18F-B."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.hybrid_candidate_calibration import (
    SAFETY,
    apply_ranking_profile_to_rows,
    available_ranking_profiles,
    build_profile_metrics,
    profile_config_to_dict,
    select_recommended_profile,
)
from services.hybrid_candidate_ranking_mapper import (
    evaluate_candidate_rows,
    read_json,
    safe_rate,
    summarize_candidate_rows,
    utc_now,
    write_json,
)
from services.tightened_mapper_evaluation import load_local_evaluation_evidence, sanitize_report_value


FEATURE = "18F-B"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--baseline-report", required=True)
    parser.add_argument("--evaluation-report", required=True)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--top-n", type=int, default=5)
    return parser.parse_args()


def _metadata(args: argparse.Namespace, generated_at: str) -> dict[str, Any]:
    return {
        "feature": FEATURE,
        "generated_at": generated_at,
        "baseline_report": args.baseline_report,
        "evaluation_report": args.evaluation_report,
        "top_n": args.top_n,
        "offline_only": True,
        **SAFETY,
    }


def _profile_table(metrics: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for name in available_ranking_profiles():
        summary = (metrics.get(name) or {}).get("summary") or {}
        rows.append(
            {
                "profile": name,
                "candidate_coverage_rate": summary.get("candidate_coverage_rate"),
                "rows_with_at_least_1_candidate": summary.get("rows_with_at_least_1_candidate"),
                "rows_with_at_least_3_candidates": summary.get("rows_with_at_least_3_candidates"),
                "no_candidate_rows": summary.get("no_candidate_rows"),
                "total_candidate_count": summary.get("total_candidate_count"),
                "average_candidates_per_covered_row": summary.get("average_candidates_per_covered_row"),
                "top1_precision_if_evaluable": summary.get("top1_precision_if_evaluable"),
                "top3_recall_if_evaluable": summary.get("top3_recall_if_evaluable"),
                "top5_recall_if_evaluable": summary.get("top5_recall_if_evaluable"),
                "risk_distribution": summary.get("risk_distribution"),
                "high_or_critical_candidate_ratio": summary.get("high_or_critical_candidate_ratio"),
                "ambiguity_count": summary.get("ambiguity_count"),
                "candidate_quality_score": summary.get("candidate_quality_score"),
                "risk_controlled": summary.get("risk_controlled"),
                "rows_losing_all_candidates": summary.get("rows_losing_all_candidates"),
                "safe_for_auto_apply_count": summary.get("safe_for_auto_apply_count"),
            }
        )
    return rows


def _source_contribution(metrics: Mapping[str, Mapping[str, Any]], profile: str) -> dict[str, Any]:
    profile_metrics = metrics.get(profile) or {}
    summary = profile_metrics.get("summary") or {}
    source_counts = profile_metrics.get("source_contribution") or {}
    total = int(summary.get("total_candidate_count") or 0)
    return {
        source: {
            "candidate_count": count,
            "candidate_share": safe_rate(int(count), total),
            "row_count": (profile_metrics.get("source_row_contribution") or {}).get(source),
        }
        for source, count in sorted(source_counts.items())
    }


def _build_reports(
    *,
    args: argparse.Namespace,
    generated_at: str,
    baseline_rows: list[dict[str, Any]],
    baseline_evaluation: Mapping[str, Any],
    supplied_evaluation_report: Mapping[str, Any],
    profile_metrics: Mapping[str, Mapping[str, Any]],
    recommended: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    metadata = _metadata(args, generated_at)
    baseline_summary = summarize_candidate_rows(baseline_rows)
    profile_table = _profile_table(profile_metrics)
    recommended_profile = str(recommended.get("recommended_profile") or "")
    recommended_metrics = profile_metrics.get(recommended_profile) or {}
    recommended_summary = recommended_metrics.get("summary") or {}

    calibration = sanitize_report_value(
        {
            "run_metadata": metadata,
            "baseline": {
                "summary": baseline_summary,
                "evaluation_summary": baseline_evaluation.get("summary") or {},
                "supplied_evaluation_summary": supplied_evaluation_report.get("summary") or {},
            },
            "profile_comparison": profile_table,
            "profile_metrics": profile_metrics,
            "recommended_profile": recommended,
            "backend_advisory_integration": {
                "justified": recommended.get("backend_advisory_integration_justified"),
                "boundary": "Design only; no auto-apply, no API/UI/DB integration, and no confirmed_tag_id automation.",
            },
            "safety": dict(SAFETY),
        }
    )
    summary = sanitize_report_value(
        {
            "run_metadata": metadata,
            "summary": {
                "profile_comparison": profile_table,
                "recommended_profile": recommended_profile,
                "recommended_reason": recommended.get("reason"),
                "recommended_next_feature": recommended.get("recommended_next_feature"),
                "backend_advisory_integration_justified": recommended.get("backend_advisory_integration_justified"),
                "recommended_metrics": recommended_summary,
                "recommended_source_contribution": _source_contribution(profile_metrics, recommended_profile),
                "explicit_no_auto_apply_boundary": True,
                "safe_for_auto_apply_count": recommended_summary.get("safe_for_auto_apply_count"),
                "requires_human_review_count": recommended_summary.get("requires_human_review_count"),
            },
            "safety": dict(SAFETY),
        }
    )
    profiles = sanitize_report_value(
        {
            "run_metadata": metadata,
            "profiles": {name: profile_config_to_dict(name) for name in available_ranking_profiles()},
            "comparison": profile_table,
            "recommended_profile": recommended_profile,
            "safety": dict(SAFETY),
        }
    )
    risk = sanitize_report_value(
        {
            "run_metadata": metadata,
            "profiles": {
                name: {
                    "risk_distribution": (metrics.get("summary") or {}).get("risk_distribution"),
                    "high_or_critical_candidate_count": (metrics.get("summary") or {}).get("high_or_critical_candidate_count"),
                    "high_or_critical_candidate_ratio": (metrics.get("summary") or {}).get("high_or_critical_candidate_ratio"),
                    "critical_candidate_count": (metrics.get("summary") or {}).get("critical_candidate_count"),
                    "risk_controlled": (metrics.get("summary") or {}).get("risk_controlled"),
                    "high_risk_labels_still_present": metrics.get("high_risk_labels_still_present") or [],
                }
                for name, metrics in profile_metrics.items()
            },
            "recommended_profile": recommended_profile,
            "safety": dict(SAFETY),
        }
    )
    recommended_report = sanitize_report_value(
        {
            "run_metadata": metadata,
            "recommended_profile": recommended,
            "recommended_profile_metrics": recommended_metrics,
            "source_contribution_after_calibration": _source_contribution(profile_metrics, recommended_profile),
            "explicit_no_auto_apply_boundary": {
                "safe_for_auto_apply": False,
                "requires_human_review": True,
                "confirmed_tag_id_automation": False,
                "production_mapper_integration": False,
            },
            "safety": dict(SAFETY),
        }
    )
    uncovered = sanitize_report_value(
        {
            "run_metadata": metadata,
            "profiles": {
                name: {
                    "still_uncovered_labels": metrics.get("still_uncovered_labels") or [],
                    "rows_losing_all_candidates": metrics.get("rows_losing_all_candidates") or [],
                    "labels_most_affected": metrics.get("labels_most_affected") or [],
                }
                for name, metrics in profile_metrics.items()
            },
            "recommended_profile": recommended_profile,
            "recommended_uncovered_labels": (recommended_metrics.get("still_uncovered_labels") or []),
            "safety": dict(SAFETY),
        }
    )
    return {
        "calibration": calibration,
        "summary": summary,
        "profiles": profiles,
        "risk": risk,
        "recommended_profile": recommended_report,
        "uncovered": uncovered,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def render_calibration_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Hybrid Candidate Calibration #18F-B",
        "",
        "Offline profile comparison only. All candidates remain review-required and unsafe for auto-apply.",
        "",
        "| Profile | Coverage | Rows >=1 | Rows >=3 | Candidates | Top-1 | Top-3 | Top-5 | High/Critical Ratio | Quality |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("profile_comparison") or []:
        lines.append(
            "| {profile} | {coverage} | {rows1} | {rows3} | {candidates} | {top1} | {top3} | {top5} | {risk} | {quality} |".format(
                profile=row.get("profile"),
                coverage=_fmt(row.get("candidate_coverage_rate")),
                rows1=_fmt(row.get("rows_with_at_least_1_candidate")),
                rows3=_fmt(row.get("rows_with_at_least_3_candidates")),
                candidates=_fmt(row.get("total_candidate_count")),
                top1=_fmt(row.get("top1_precision_if_evaluable")),
                top3=_fmt(row.get("top3_recall_if_evaluable")),
                top5=_fmt(row.get("top5_recall_if_evaluable")),
                risk=_fmt(row.get("high_or_critical_candidate_ratio")),
                quality=_fmt(row.get("candidate_quality_score")),
            )
        )
    rec = report.get("recommended_profile") or {}
    lines.extend(
        [
            "",
            f"- Recommended profile: `{rec.get('recommended_profile')}`",
            f"- Reason: {rec.get('reason')}",
            f"- Backend advisory integration justified: `{rec.get('backend_advisory_integration_justified')}`",
            "- No-auto-apply boundary: `safe_for_auto_apply=false`, `requires_human_review=true`.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    metrics = summary.get("recommended_metrics") or {}
    lines = [
        "# Hybrid Candidate Calibration Summary #18F-B",
        "",
        f"- Recommended profile: `{summary.get('recommended_profile')}`",
        f"- Recommended next feature: `{summary.get('recommended_next_feature')}`",
        f"- Reason: {summary.get('recommended_reason')}",
        f"- Candidate coverage: `{metrics.get('candidate_coverage_rate')}`",
        f"- Top-1 precision if evaluable: `{metrics.get('top1_precision_if_evaluable')}`",
        f"- Top-3 recall if evaluable: `{metrics.get('top3_recall_if_evaluable')}`",
        f"- Top-5 recall if evaluable: `{metrics.get('top5_recall_if_evaluable')}`",
        f"- Risk distribution: `{metrics.get('risk_distribution')}`",
        f"- Risk controlled: `{metrics.get('risk_controlled')}`",
        f"- Candidate quality score: `{metrics.get('candidate_quality_score')}`",
        f"- safe_for_auto_apply_count: `{metrics.get('safe_for_auto_apply_count')}`",
        f"- requires_human_review_count: `{metrics.get('requires_human_review_count')}`",
    ]
    return "\n".join(lines) + "\n"


def render_profiles_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Hybrid Candidate Calibration Profiles #18F-B",
        "",
        "| Profile | Min Score | Lexical Min | Non-Lexical Min | High | Medium | Low | Max Candidates | Ambiguity |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, profile in (report.get("profiles") or {}).items():
        lines.append(
            f"| {name} | {profile.get('minimum_candidate_score')} | {profile.get('taxonomy_lexical_minimum_score')} | "
            f"{profile.get('non_lexical_candidate_minimum_score')} | {profile.get('candidate_high_threshold')} | "
            f"{profile.get('candidate_medium_threshold')} | {profile.get('candidate_low_threshold')} | "
            f"{profile.get('max_candidates_per_row')} | {profile.get('ambiguity_threshold')} |"
        )
    lines.extend(["", "## Source Weights"])
    for name, profile in (report.get("profiles") or {}).items():
        lines.append(f"- `{name}`: `{profile.get('source_weights')}`")
    return "\n".join(lines) + "\n"


def render_risk_markdown(report: Mapping[str, Any]) -> str:
    lines = ["# Hybrid Candidate Calibration Risk #18F-B", ""]
    for name, profile in (report.get("profiles") or {}).items():
        lines.extend(
            [
                f"## {name}",
                f"- Risk distribution: `{profile.get('risk_distribution')}`",
                f"- High/critical count: `{profile.get('high_or_critical_candidate_count')}`",
                f"- High/critical ratio: `{profile.get('high_or_critical_candidate_ratio')}`",
                f"- Critical count: `{profile.get('critical_candidate_count')}`",
                f"- Risk controlled: `{profile.get('risk_controlled')}`",
                "",
                "| High-risk label still present | Candidate Count |",
                "| --- | ---: |",
            ]
        )
        for item in (profile.get("high_risk_labels_still_present") or [])[:20]:
            lines.append(f"| {item.get('normalized_label')} | {item.get('candidate_count')} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_recommended_markdown(report: Mapping[str, Any]) -> str:
    rec = report.get("recommended_profile") or {}
    metrics = report.get("recommended_profile_metrics") or {}
    summary = metrics.get("summary") or {}
    lines = [
        "# Hybrid Candidate Recommended Profile #18F-B",
        "",
        f"- Recommended profile: `{rec.get('recommended_profile')}`",
        f"- Reason: {rec.get('reason')}",
        f"- Recommended next feature: `{rec.get('recommended_next_feature')}`",
        f"- Backend advisory integration justified: `{rec.get('backend_advisory_integration_justified')}`",
        f"- Coverage: `{summary.get('candidate_coverage_rate')}`",
        f"- Top-1 precision: `{summary.get('top1_precision_if_evaluable')}`",
        f"- Top-3 recall: `{summary.get('top3_recall_if_evaluable')}`",
        f"- Top-5 recall: `{summary.get('top5_recall_if_evaluable')}`",
        f"- Risk distribution: `{summary.get('risk_distribution')}`",
        f"- Source contribution: `{report.get('source_contribution_after_calibration')}`",
        "- Safety: `safe_for_auto_apply=false`, `requires_human_review=true`, no confirmed_tag_id automation.",
    ]
    return "\n".join(lines) + "\n"


def render_uncovered_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Hybrid Candidate Calibration Uncovered Rows #18F-B",
        "",
        f"- Recommended profile: `{report.get('recommended_profile')}`",
        "",
    ]
    for name, profile in (report.get("profiles") or {}).items():
        lines.extend([f"## {name}", "", "| Still-uncovered label | Count |", "| --- | ---: |"])
        for item in (profile.get("still_uncovered_labels") or [])[:40]:
            lines.append(f"| {item.get('normalized_label')} | {item.get('count')} |")
        lines.extend(["", "| Most affected label | Count | Candidate Delta |", "| --- | ---: | ---: |"])
        for item in (profile.get("labels_most_affected") or [])[:20]:
            lines.append(f"| {item.get('normalized_label')} | {item.get('count')} | {item.get('candidate_delta')} |")
        lines.append("")
    return "\n".join(lines) + "\n"


def _markdown_reports(reports: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    return {
        "calibration": render_calibration_markdown(reports["calibration"]),
        "summary": render_summary_markdown(reports["summary"]),
        "profiles": render_profiles_markdown(reports["profiles"]),
        "risk": render_risk_markdown(reports["risk"]),
        "recommended_profile": render_recommended_markdown(reports["recommended_profile"]),
        "uncovered": render_uncovered_markdown(reports["uncovered"]),
    }


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = utc_now()

    baseline_report = read_json(args.baseline_report)
    baseline_rows = list(baseline_report.get("ranked_rows") or [])
    if not baseline_rows:
        raise ValueError(f"Baseline report has no ranked_rows: {args.baseline_report}")
    supplied_evaluation_report = read_json(args.evaluation_report)

    evidence = load_local_evaluation_evidence(dataset_dir=args.dataset_dir, records=baseline_rows)
    baseline_evaluation = evaluate_candidate_rows(
        baseline_rows,
        row_values=evidence.get("row_values") or [],
        facts_by_sample=evidence.get("facts_by_sample") or {},
    )

    profile_metrics: dict[str, dict[str, Any]] = {}
    for profile in available_ranking_profiles():
        profile_rows = apply_ranking_profile_to_rows(baseline_rows, profile, top_n=args.top_n)
        profile_evaluation = evaluate_candidate_rows(
            profile_rows,
            row_values=evidence.get("row_values") or [],
            facts_by_sample=evidence.get("facts_by_sample") or {},
        )
        profile_metrics[profile] = build_profile_metrics(
            profile=profile,
            rows=profile_rows,
            evaluation=profile_evaluation,
            baseline_rows=baseline_rows,
        )

    recommended = select_recommended_profile(profile_metrics)
    reports = _build_reports(
        args=args,
        generated_at=generated_at,
        baseline_rows=baseline_rows,
        baseline_evaluation=baseline_evaluation,
        supplied_evaluation_report=supplied_evaluation_report,
        profile_metrics=profile_metrics,
        recommended=recommended,
    )
    markdown = _markdown_reports(reports)

    paths = {
        "calibration": output_dir / "hybrid_candidate_calibration_18f_b.json",
        "summary": output_dir / "hybrid_candidate_calibration_summary_18f_b.json",
        "profiles": output_dir / "hybrid_candidate_calibration_profiles_18f_b.json",
        "risk": output_dir / "hybrid_candidate_calibration_risk_18f_b.json",
        "recommended_profile": output_dir / "hybrid_candidate_calibration_recommended_profile_18f_b.json",
        "uncovered": output_dir / "hybrid_candidate_calibration_uncovered_18f_b.json",
    }
    for key, path in paths.items():
        write_json(path, reports[key])
        path.with_suffix(".md").write_text(markdown[key], encoding="utf-8")

    print(
        {
            "recommended_profile": recommended.get("recommended_profile"),
            "recommended_next_feature": recommended.get("recommended_next_feature"),
            "backend_advisory_integration_justified": recommended.get("backend_advisory_integration_justified"),
            "profiles": {
                name: {
                    "coverage": metrics["summary"].get("candidate_coverage_rate"),
                    "top1": metrics["summary"].get("top1_precision_if_evaluable"),
                    "top3": metrics["summary"].get("top3_recall_if_evaluable"),
                    "top5": metrics["summary"].get("top5_recall_if_evaluable"),
                    "risk_ratio": metrics["summary"].get("high_or_critical_candidate_ratio"),
                    "quality": metrics["summary"].get("candidate_quality_score"),
                }
                for name, metrics in profile_metrics.items()
            },
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
