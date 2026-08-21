"""Normalize Azure DI Extraction v2 candidate reports before mapping."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.extraction_v2_azure_di_normalizer import (  # noqa: E402
    DEFAULT_INPUT_REPORT,
    run_azure_di_normalization,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize a read-only Azure DI Extraction v2 report and optionally run report-only gates."
    )
    parser.add_argument("--azure-di-report", type=Path, default=PROJECT_ROOT / DEFAULT_INPUT_REPORT)
    parser.add_argument("--run-id", default="azure_di_normalized_13y")
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--skip-gates", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_azure_di_normalization(
        azure_di_report_path=args.azure_di_report,
        run_id=args.run_id,
        output_prefix=args.output_prefix,
        skip_gates=args.skip_gates,
        verbose=args.verbose,
    )
    paths = result["paths"]
    normalized = result["normalized_report"]
    summary = result["summary_report"]
    metrics = normalized.get("aggregate_metrics") or {}
    effects = summary.get("normalization_effects") or {}
    print(f"Azure DI normalized extraction report: {paths.extraction_json}")
    print(f"Azure DI normalization summary report: {paths.summary_json}")
    if not args.skip_gates:
        print(f"Azure DI normalized candidate quality report: {paths.quality_json}")
        print(f"Azure DI normalized duplicate/conflict report: {paths.duplicate_json}")
        print(f"Azure DI normalized manual-review queue report: {paths.manual_review_queue_json}")
        print(f"Azure DI normalized mapping handoff report: {paths.mapping_handoff_json}")
    print(f"Normalized candidates: {metrics.get('total_candidates', 0)}")
    print(f"Headings after normalization: {metrics.get('heading_count', 0)}")
    print(f"Text blocks after normalization: {metrics.get('text_block_count', 0)}")
    print(f"Index/TOC rows suppressed: {effects.get('index_toc_rows_suppressed', 0)}")
    print(f"Suppressed candidates: {effects.get('suppressed_candidates', 0)}")
    if args.verbose:
        assessment = summary.get("assessment") or {}
        print(f"Recommended next feature: {assessment.get('recommended_next_feature')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
