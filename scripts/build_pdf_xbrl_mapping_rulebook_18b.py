"""Build Feature #18B PDF-XBRL mapping rulebook reports from #18A alignments."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pdf_xbrl_mapping_rulebook import write_rulebook_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build reusable offline PDF-to-XBRL mapping rulebook reports for Feature #18B.",
    )
    parser.add_argument(
        "--alignment-report",
        default="reports/pdf_xbrl_alignment_18a.json",
        help="Feature #18A full alignment JSON report.",
    )
    parser.add_argument(
        "--summary-report",
        default="reports/pdf_xbrl_alignment_summary_18a.json",
        help="Feature #18A summary JSON report.",
    )
    parser.add_argument(
        "--ambiguous-report",
        default="reports/pdf_xbrl_alignment_ambiguous_18a.json",
        help="Feature #18A ambiguous-alignment JSON report.",
    )
    parser.add_argument(
        "--output-dir",
        default="reports",
        help="Directory where #18B JSON and markdown reports will be written.",
    )
    parser.add_argument(
        "--min-strong-support",
        type=int,
        default=2,
        help="Minimum safe observations needed for a repeated strong rule.",
    )
    parser.add_argument(
        "--include-medium",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include medium-confidence #18A alignments as usable evidence.",
    )
    parser.add_argument(
        "--exclude-zero-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exclude rules supported only by zero-value evidence.",
    )
    parser.add_argument(
        "--debug-label",
        default=None,
        help="Optional normalized label substring filter for debugging a candidate pattern.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_rulebook_reports(
        alignment_report_path=args.alignment_report,
        summary_report_path=args.summary_report,
        ambiguous_report_path=args.ambiguous_report,
        output_dir=args.output_dir,
        min_strong_support=args.min_strong_support,
        include_medium=args.include_medium,
        exclude_zero_only=args.exclude_zero_only,
        debug_label=args.debug_label,
    )
    summary = result["summary"]["summary"]
    print("Feature #18B PDF-XBRL mapping rulebook reports written:")
    for name, path in result["paths"].items():
        print(f"- {name}: {path}")
    print("")
    print("Rulebook summary:")
    print(f"- candidate_pattern_count: {summary['candidate_pattern_count']}")
    print(f"- active_strong_rules: {summary['active_strong_rules']}")
    print(f"- active_usable_rules: {summary['active_usable_rules']}")
    print(f"- review_required_rules: {summary['review_required_rules']}")
    print(f"- excluded_rules: {summary['excluded_rules']}")
    print(f"- feature_18c_holdout_replay_justified: {summary['recommendation']['feature_18c_holdout_replay_justified']}")
    print("")
    print("Safety:")
    for key, value in summary["safety"].items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
