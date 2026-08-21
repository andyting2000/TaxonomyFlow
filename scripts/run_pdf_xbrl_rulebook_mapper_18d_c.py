"""Run Feature #18D-C offline advisory PDF-XBRL rulebook mapper."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pdf_xbrl_rulebook_mapper import write_mapper_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay the hardened PDF-XBRL rulebook against cached Azure DI rows as advisory-only evidence.",
    )
    parser.add_argument("--dataset-dir", default="benchmark_mbrs_pairs", help="Local benchmark PDF/XML pair directory.")
    parser.add_argument("--hardened-rulebook", default="reports/pdf_xbrl_rulebook_hardening_18d_b.json", help="Feature #18D-B hardened rulebook/readiness report.")
    parser.add_argument("--output-dir", default="reports", help="Directory for #18D-C reports.")
    parser.add_argument("--include-sample", action="append", default=[], help="Sample id to include; repeat for multiple samples.")
    parser.add_argument("--exclude-sample", action="append", default=[], help="Sample id to exclude; repeat for multiple samples.")
    parser.add_argument("--include-outlier", action="store_true", help="Include outlier samples such as Shield Plus.")
    parser.add_argument("--debug-label", help="Only map rows whose normalized label contains this text.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_mapper_reports(
        dataset_dir=args.dataset_dir,
        hardened_rulebook_path=args.hardened_rulebook,
        output_dir=args.output_dir,
        include_samples=args.include_sample,
        exclude_samples=args.exclude_sample,
        include_outlier=args.include_outlier,
        debug_label=args.debug_label,
    )
    summary = result["summary"]["summary"]
    recommendation = summary["recommendation"]
    print("Feature #18D-C PDF-XBRL rulebook mapper reports written:")
    for name, path in result["paths"].items():
        print(f"- {name}: {path}")
    print("")
    print("Mapper summary:")
    print(f"- total_pdf_row_value_observations: {summary['total_pdf_row_value_observations']}")
    print(f"- advisory_suggestions_count: {summary['advisory_suggestions_count']}")
    print(f"- review_required_suggestions_count: {summary['review_required_suggestions_count']}")
    print(f"- conflicts_count: {summary['conflicts_count']}")
    print(f"- no_match_count: {summary['no_match_count']}")
    print(f"- safe_for_auto_apply_count: {summary['safe_for_auto_apply_count']}")
    print("")
    print(f"Recommendation: {recommendation['recommended_next_feature']}")
    print("Safety:")
    for key, value in summary["safety"].items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
