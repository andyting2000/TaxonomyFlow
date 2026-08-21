"""Evaluate retrieval-based few-shot Qwen mapping against #17A holdout gold."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.fewshot_qwen_mapping import (  # noqa: E402
    DEFAULT_ALIGNMENT_REPORT,
    DEFAULT_BASELINE_ACCURACY_REPORT,
    DEFAULT_BASELINE_PREDICTIONS_REPORT,
    write_fewshot_qwen_reports,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate report-only retrieval-based few-shot Qwen mapping evaluation against #17A holdout rows."
    )
    parser.add_argument("--golden-dir", type=Path, default=PROJECT_ROOT / "benchmark_mbrs_pairs")
    parser.add_argument("--alignment-report", type=Path, default=DEFAULT_ALIGNMENT_REPORT)
    parser.add_argument("--baseline-accuracy-report", type=Path, default=DEFAULT_BASELINE_ACCURACY_REPORT)
    parser.add_argument("--baseline-predictions-report", type=Path, default=DEFAULT_BASELINE_PREDICTIONS_REPORT)
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument("--train-case-count", type=int, default=4)
    parser.add_argument("--holdout-case", action="append", default=[], help="Explicit holdout case id. May be repeated.")
    parser.add_argument("--examples-per-row", type=int, default=5)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--no-live-llm", action="store_true", help="Generate local prompt inputs and reports without external Qwen calls.")
    mode.add_argument(
        "--use-live-llm",
        action="store_true",
        help="Send holdout row context, training-case few-shot examples, and local candidate concepts only to Qwen.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    result = await write_fewshot_qwen_reports(
        golden_dir=args.golden_dir,
        output_dir=args.output_dir,
        alignment_report_path=args.alignment_report,
        baseline_accuracy_report_path=args.baseline_accuracy_report,
        baseline_predictions_report_path=args.baseline_predictions_report,
        use_live_llm=args.use_live_llm,
        train_case_count=args.train_case_count,
        holdout_cases=args.holdout_case or None,
        examples_per_row=args.examples_per_row,
    )
    score = result["accuracy"]["fewshot_qwen_mapping"]
    comparison = result["comparison"]
    print(f"Few-shot predictions report: {result['paths']['predictions_json']}")
    print(f"Few-shot accuracy report: {result['paths']['accuracy_json']}")
    print(f"Few-shot error analysis report: {result['paths']['errors_json']}")
    print(f"Few-shot comparison report: {result['paths']['comparison_json']}")
    print(f"Holdout rows: {result['accuracy']['strict_scoring_rows']}")
    print(f"Few-shot Qwen status: {score['status']}")
    print(f"Few-shot Qwen coverage: {score['coverage']}")
    print(f"Few-shot Qwen strict accuracy: {score['accuracy']}")
    print(f"Few-shot Qwen accuracy when predicted: {score['accuracy_when_predicted']}")
    print(f"Delta vs same-holdout baseline: {comparison['delta_vs_same_holdout_baseline']}")
    print(f"External LLM called: {result['accuracy']['run_metadata']['external_llm_called']}")
    print("Auditor XML sent externally: False")
    print("Target gold answers sent externally: False")
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())

