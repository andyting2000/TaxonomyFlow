"""Run offline hybrid candidate ranking for Feature #18E-F-A."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.hybrid_candidate_ranking_mapper import (
    build_concept_catalog,
    build_reports,
    load_cached_qwen_candidates,
    mapper_records_from_report,
    markdown_reports,
    read_json,
    write_json,
)
from services.tightened_mapper_evaluation import load_local_evaluation_evidence


REPORT_FILES = {
    "ranking": "hybrid_candidate_ranking_18e_f_a",
    "summary": "hybrid_candidate_ranking_summary_18e_f_a",
    "evaluation": "hybrid_candidate_ranking_evaluation_18e_f_a",
    "uncovered": "hybrid_candidate_ranking_uncovered_18e_f_a",
    "risk_analysis": "hybrid_candidate_ranking_risk_analysis_18e_f_a",
    "design": "hybrid_candidate_ranking_design_18e_f_a",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True)
    parser.add_argument("--mapper-report", required=True)
    parser.add_argument("--evaluation-report", required=True)
    parser.add_argument("--taxonomy-metadata")
    parser.add_argument("--qwen-report-dir")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--debug-label")
    parser.add_argument("--allow-missing-taxonomy", action="store_true")
    parser.add_argument("--allow-missing-qwen", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

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
    reports = build_reports(
        records=records,
        concepts=concepts,
        evaluation_report=evaluation_report,
        qwen_index=qwen_index,
        row_values=evidence.get("row_values") or [],
        facts_by_sample=evidence.get("facts_by_sample") or {},
        top_n=args.top_n,
        debug_label=args.debug_label,
        metadata_diagnostics=metadata_diagnostics,
        qwen_diagnostics=qwen_diagnostics,
    )
    markdown = markdown_reports(reports)

    for key, stem in REPORT_FILES.items():
        write_json(output_dir / f"{stem}.json", reports[key])
        (output_dir / f"{stem}.md").write_text(markdown[key], encoding="utf-8")

    summary = reports["summary"]["summary"]
    evaluation = reports["summary"]["evaluation_summary"]
    print(
        {
            "rows_with_at_least_1_candidate": summary.get("rows_with_at_least_1_candidate"),
            "rows_with_at_least_3_candidates": summary.get("rows_with_at_least_3_candidates"),
            "candidate_coverage_rate": summary.get("candidate_coverage_rate"),
            "no_candidate_rows": summary.get("no_candidate_rows"),
            "top1_precision_if_evaluable": evaluation.get("top1_precision_if_evaluable"),
            "top3_recall_if_evaluable": evaluation.get("top3_recall_if_evaluable"),
            "top5_recall_if_evaluable": evaluation.get("top5_recall_if_evaluable"),
            "recommended_next_feature": reports["summary"]["recommendation"].get("recommended_next_feature"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
