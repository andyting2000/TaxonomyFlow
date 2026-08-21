"""Build report-only manual mapping review workflow artifacts for #14B."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.azure_di_manual_mapping_review import (  # noqa: E402
    DEFAULT_CONFIDENCE_REPORT,
    DEFAULT_GAP_REPORT,
    DEFAULT_MAPPING_REPORT,
    render_summary_markdown,
    run_manual_mapping_review,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only manual mapping review queue from #14A Azure DI mapping reports."
    )
    parser.add_argument("--mapping-report", type=Path, default=PROJECT_ROOT / DEFAULT_MAPPING_REPORT)
    parser.add_argument("--confidence-report", type=Path, default=PROJECT_ROOT / DEFAULT_CONFIDENCE_REPORT)
    parser.add_argument("--gap-report", type=Path, default=PROJECT_ROOT / DEFAULT_GAP_REPORT)
    parser.add_argument("--run-id", default="azure_di_manual_mapping_review_14b")
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_manual_mapping_review(
        mapping_report_path=args.mapping_report,
        confidence_report_path=args.confidence_report,
        gap_report_path=args.gap_report,
        run_id=args.run_id,
        output_prefix=args.output_prefix,
    )
    paths = result["paths"]
    queue = result["queue_report"]
    summary = result["summary_report"]
    print(f"Azure DI manual mapping review queue: {paths.queue_json}")
    print(f"Azure DI mapping review policy: {paths.policy_json}")
    print(f"Azure DI mapping review handoff contract: {paths.contract_json}")
    print(f"Azure DI mapping review summary: {paths.summary_json}")
    print(f"Review queue items: {queue.get('review_queue_count', 0)}")
    print(f"Workflow status distribution: {queue.get('workflow_status_distribution', {})}")
    print(f"Priority distribution: {queue.get('priority_distribution', {})}")
    print(f"Recommended next feature: {summary.get('recommended_next_feature')}")
    if args.verbose:
        print(render_summary_markdown(summary).split("## Top Ambiguous Labels", 1)[0].strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

