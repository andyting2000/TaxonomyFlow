"""Generate Feature #18E-D tightened mapper precision/conflict-risk reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.tightened_mapper_evaluation import build_tightened_mapper_reports_from_files, write_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the #18E-B-2-hotfix-1 tightened mapper offline.")
    parser.add_argument("--dataset-dir", default="benchmark_mbrs_pairs")
    parser.add_argument("--mapper-report", default="reports/rulebook_mapper_dictionary_tightened_18e_b2_hotfix_1.json")
    parser.add_argument("--blocked-report", default="reports/rulebook_mapper_dictionary_blocked_candidates_18e_b2_hotfix_1.json")
    parser.add_argument("--alignment-report", default="reports/pdf_xbrl_alignment_18a.json")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--debug-label")
    parser.add_argument("--include-not-evaluable", action="store_true")
    parser.add_argument("--strict-period-match", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reports = build_tightened_mapper_reports_from_files(
        dataset_dir=args.dataset_dir,
        mapper_report_path=args.mapper_report,
        blocked_report_path=args.blocked_report,
        alignment_report_path=args.alignment_report,
        debug_label=args.debug_label,
        include_not_evaluable=args.include_not_evaluable,
        strict_period_match=args.strict_period_match,
    )
    paths = write_reports(reports, output_dir=args.output_dir)
    evaluation = reports["evaluation"]["summary"]
    blocked = reports["blocked_candidate_analysis"]["summary"]
    readiness = reports["readiness_matrix"]["summary"]
    recommendation = reports["readiness_matrix"]["recommendation"]

    print("Feature #18E-D tightened mapper evaluation reports written:")
    for name, path in paths.items():
        print(f"- {name}: {path}")
    print("")
    print("Evaluation summary:")
    print(f"- total_observations: {evaluation.get('total_observations')}")
    print(f"- touched_coverage_rate: {evaluation.get('touched_coverage_rate')}")
    print(f"- precision_on_evaluable: {evaluation.get('precision_on_evaluable')}")
    print(f"- exact_matches: {evaluation.get('exact_matches')}")
    print(f"- false_positive_count: {evaluation.get('false_positive_count')}")
    print(f"- ambiguous_count: {evaluation.get('ambiguous_count')}")
    print(f"- not_evaluable_count: {evaluation.get('not_evaluable_count')}")
    print(f"- blocked_candidate_rows: {blocked.get('blocked_candidate_rows')}")
    print(f"- correctly_blocked_false_positive_count: {blocked.get('correctly_blocked_false_positive_count')}")
    print(f"- overblocked_true_positive_count: {blocked.get('overblocked_true_positive_count')}")
    print(f"- readiness_should_be_disabled_count: {readiness.get('should_be_disabled_count')}")
    print(f"- safe_for_auto_apply_count: {evaluation.get('safe_for_auto_apply_count')}")
    print(f"- next: {recommendation.get('recommended_next_feature')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
