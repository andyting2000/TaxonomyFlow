"""Generate read-only Azure DI mapping candidate suggestion reports for #13Z."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.azure_di_mapping_candidate_generator import (  # noqa: E402
    DEFAULT_HANDOFF_REPORT,
    render_candidates_markdown,
    run_mapping_candidate_generation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate deterministic, report-only mapping suggestions from the #13Y Azure DI handoff report."
    )
    parser.add_argument("--handoff-report", type=Path, default=PROJECT_ROOT / DEFAULT_HANDOFF_REPORT)
    parser.add_argument("--reference-report", type=Path)
    parser.add_argument("--run-id", default="azure_di_mapping_candidates_13z")
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = run_mapping_candidate_generation(
        handoff_report_path=args.handoff_report,
        reference_report_path=args.reference_report,
        run_id=args.run_id,
        output_prefix=args.output_prefix,
    )
    paths = result["paths"]
    candidates = result["candidates_report"]
    confidence = result["confidence_report"]
    gap = result["gap_report"]
    print(f"Azure DI mapping candidates report: {paths.candidates_json}")
    print(f"Azure DI mapping confidence report: {paths.confidence_json}")
    print(f"Azure DI mapping gap analysis report: {paths.gap_json}")
    print(f"Mapping records: {candidates.get('mapping_record_count', 0)}")
    print(f"High confidence: {candidates.get('high_confidence_count', 0)}")
    print(f"Medium confidence: {candidates.get('medium_confidence_count', 0)}")
    print(f"Low confidence: {candidates.get('low_confidence_count', 0)}")
    print(f"Ambiguous: {candidates.get('ambiguous_multiple_suggestions_count', 0)}")
    print(f"No safe suggestion: {candidates.get('no_safe_suggestion_count', 0)}")
    print(f"Requires confirmation: {confidence.get('requires_confirmation_count', 0)}")
    print(f"Recommended next feature: {gap.get('recommended_next_feature')}")
    if args.verbose:
        print(render_candidates_markdown(candidates).split("## Limitations", 1)[0].strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
