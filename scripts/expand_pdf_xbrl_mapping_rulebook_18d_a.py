"""Run Feature #18D-A context-aware PDF-XBRL rulebook expansion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pdf_xbrl_rulebook_context_upgrade import write_expansion_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expand the offline PDF-XBRL mapping rulebook with context-aware deterministic upgrades.",
    )
    parser.add_argument("--dataset-dir", default="benchmark_mbrs_pairs", help="Local benchmark PDF/XML pair directory.")
    parser.add_argument("--alignment-report", default="reports/pdf_xbrl_alignment_18a.json", help="Feature #18A alignment report.")
    parser.add_argument("--rulebook-report", default="reports/pdf_xbrl_mapping_rulebook_18b.json", help="Feature #18B rulebook report.")
    parser.add_argument("--replay-report", default="reports/pdf_xbrl_rulebook_replay_18c.json", help="Feature #18C replay report.")
    parser.add_argument("--output-dir", default="reports", help="Directory for #18D-A reports.")
    parser.add_argument("--holdout-sample", default=None, help="Optional single holdout sample id for debugging.")
    parser.add_argument("--debug-label", default=None, help="Optional normalized label substring filter.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_expansion_reports(
        dataset_dir=args.dataset_dir,
        alignment_report_path=args.alignment_report,
        rulebook_report_path=args.rulebook_report,
        replay_report_path=args.replay_report,
        output_dir=args.output_dir,
        holdout_sample=args.holdout_sample,
        debug_label=args.debug_label,
    )
    summary = result["summary"]["summary"]
    before = summary["original_leave_one_out"]
    after = summary["expanded_leave_one_out"]
    recommendation = summary["recommendation"]
    print("Feature #18D-A PDF-XBRL rulebook expansion reports written:")
    for name, path in result["paths"].items():
        print(f"- {name}: {path}")
    print("")
    print("Rule counts:")
    print(f"- original_active_rules: {summary['original_active_rules']}")
    print(f"- expanded_active_rules: {summary['expanded_active_rules']}")
    print(f"- upgraded_strong_rules: {summary['upgraded_strong_rules']}")
    print(f"- upgraded_usable_rules: {summary['upgraded_usable_rules']}")
    print(f"- still_review_required_rules: {summary['still_review_required_rules']}")
    print(f"- still_excluded_rules: {summary['still_excluded_rules']}")
    print("")
    print("Leave-one-out active replay:")
    print(f"- before_coverage: {before.get('active_rule_coverage_rate')}")
    print(f"- after_coverage: {after.get('active_rule_coverage_rate')}")
    print(f"- before_precision: {before.get('active_rule_precision_on_evaluable')}")
    print(f"- after_precision: {after.get('active_rule_precision_on_evaluable')}")
    print(f"- before_false_positives: {before.get('active_rule_false_positive_count')}")
    print(f"- after_false_positives: {after.get('active_rule_false_positive_count')}")
    print("")
    print(f"Recommendation: {recommendation['recommended_next_feature']}")
    print("Safety:")
    for key, value in summary["safety"].items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
