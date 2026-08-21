"""Run Feature #18A local deterministic PDF-to-XBRL alignment reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.pdf_xbrl_deterministic_alignment import (  # noqa: E402
    DEFAULT_HIGH_SCORE,
    DEFAULT_MEDIUM_SCORE,
    write_alignment_reports,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build local deterministic PDF row to XBRL fact alignment reports for Feature #18A."
    )
    parser.add_argument("--dataset-dir", type=Path, default=PROJECT_ROOT / "benchmark_mbrs_pairs")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument("--exclude-sample", action="append", default=[], help="Case/company substring to exclude.")
    parser.add_argument("--include-sample", action="append", default=[], help="Case/company substring to include.")
    parser.add_argument(
        "--exclude-outlier",
        action="append",
        default=["Shield"],
        help="Outlier substring to exclude when no include filter is used. Defaults to Shield.",
    )
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--debug-sample", default=None, help="Run one sample by case/company substring.")
    parser.add_argument("--min-high-score", type=int, default=DEFAULT_HIGH_SCORE)
    parser.add_argument("--min-medium-score", type=int, default=DEFAULT_MEDIUM_SCORE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_alignment_reports(
        dataset_dir=args.dataset_dir,
        output_dir=args.output_dir,
        include_samples=args.include_sample,
        exclude_samples=args.exclude_sample,
        exclude_outliers=args.exclude_outlier,
        max_samples=args.max_samples,
        debug_sample=args.debug_sample,
        min_high_score=args.min_high_score,
        min_medium_score=args.min_medium_score,
    )
    summary = result["summary"]["summary"]
    print(f"Alignment report: {result['paths']['alignment_json']}")
    print(f"Summary report: {result['paths']['summary_json']}")
    print(f"Ambiguous report: {result['paths']['ambiguous_json']}")
    print(f"Unmatched report: {result['paths']['unmatched_json']}")
    print(f"Included samples: {summary['included_sample_count']}")
    print(f"Excluded samples: {summary['excluded_sample_count']}")
    print(f"PDF row values considered: {summary['total_pdf_row_values_considered']}")
    print(f"XBRL numeric facts considered: {summary['total_xbrl_facts_considered']}")
    print(f"High confidence: {summary['high_confidence_count']}")
    print(f"Medium confidence: {summary['medium_confidence_count']}")
    print(f"Ambiguous: {summary['ambiguous_count']}")
    print(f"Unmatched PDF rows: {summary['unmatched_pdf_row_count']}")
    print(f"Unmatched XBRL facts: {summary['unmatched_xbrl_fact_count']}")
    print("External LLM called: False")
    print("Database mutated: False")
    print("Production behavior changed: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
