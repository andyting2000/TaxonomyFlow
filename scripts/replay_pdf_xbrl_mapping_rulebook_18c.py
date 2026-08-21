"""Run Feature #18C offline PDF-XBRL rulebook replay evaluation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pdf_xbrl_rulebook_replay import write_replay_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay the Feature #18B PDF-XBRL rulebook against local holdout samples.",
    )
    parser.add_argument("--dataset-dir", default="benchmark_mbrs_pairs", help="Local benchmark PDF/XML pair directory.")
    parser.add_argument("--alignment-report", default="reports/pdf_xbrl_alignment_18a.json", help="Feature #18A alignment JSON report.")
    parser.add_argument("--rulebook-report", default="reports/pdf_xbrl_mapping_rulebook_18b.json", help="Feature #18B rulebook JSON report.")
    parser.add_argument("--output-dir", default="reports", help="Directory for #18C reports.")
    parser.add_argument("--exclude-outlier", action="store_true", help="Skip separate Shield Plus/outlier replay.")
    parser.add_argument("--include-outlier", action="store_true", help="Force separate Shield Plus/outlier replay.")
    parser.add_argument("--holdout-sample", default=None, help="Optional single holdout sample id for leave-one-out debugging.")
    parser.add_argument("--skip-leave-one-out", action="store_true", help="Skip primary leave-one-out evaluation.")
    parser.add_argument("--debug-label", default=None, help="Optional normalized label substring filter.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    include_outlier = True
    if args.exclude_outlier:
        include_outlier = False
    if args.include_outlier:
        include_outlier = True
    result = write_replay_reports(
        dataset_dir=args.dataset_dir,
        alignment_report_path=args.alignment_report,
        rulebook_report_path=args.rulebook_report,
        output_dir=args.output_dir,
        include_outlier=include_outlier,
        holdout_sample=args.holdout_sample,
        skip_leave_one_out=args.skip_leave_one_out,
        debug_label=args.debug_label,
    )
    summary = result["full"]["summary"]
    holdout = summary["leave_one_out"]
    in_sample = summary["in_sample"]
    outlier = summary["outlier"]
    print("Feature #18C PDF-XBRL rulebook replay reports written:")
    for name, path in result["paths"].items():
        print(f"- {name}: {path}")
    print("")
    print("Leave-one-out:")
    print(f"- coverage_rate: {holdout.get('coverage_rate')}")
    print(f"- precision_on_evaluable: {holdout.get('precision_on_evaluable')}")
    print(f"- exact_qname_value_period_matches: {holdout.get('exact_qname_value_period_matches')}")
    print(f"- false_positive_count: {holdout.get('false_positive_count')}")
    print(f"- not_evaluable_count: {holdout.get('not_evaluable_count')}")
    print("")
    print("In-sample:")
    print(f"- coverage_rate: {in_sample.get('coverage_rate')}")
    print(f"- precision_on_evaluable: {in_sample.get('precision_on_evaluable')}")
    print(f"- exact_qname_value_period_matches: {in_sample.get('exact_qname_value_period_matches')}")
    print("")
    print("Outlier:")
    print(f"- sample_count: {outlier.get('sample_count')}")
    print(f"- coverage_rate: {outlier.get('coverage_rate')}")
    print(f"- precision_on_evaluable: {outlier.get('precision_on_evaluable')}")
    print("")
    print(f"Recommendation: {summary['recommendation']['recommended_next_feature']}")
    print("Safety:")
    for key, value in summary["safety"].items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
