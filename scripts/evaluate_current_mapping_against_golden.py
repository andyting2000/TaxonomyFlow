"""Evaluate current deterministic and optional live-Qwen mapping against #17A gold."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.current_mapping_baseline import (  # noqa: E402
    DEFAULT_ALIGNMENT_REPORT,
    DEFAULT_OUTPUT_DIR,
    write_current_mapping_baseline_reports,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate report-only current deterministic and optional live-Qwen baselines against #17A strong gold rows."
    )
    parser.add_argument("--golden-dir", type=Path, default=PROJECT_ROOT / "benchmark_mbrs_pairs")
    parser.add_argument("--alignment-report", type=Path, default=DEFAULT_ALIGNMENT_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--no-live-llm",
        action="store_true",
        help="Run local deterministic scoring and record live Qwen scoring as blocked without any external request.",
    )
    mode.add_argument(
        "--use-live-llm",
        action="store_true",
        help="Send extracted row context plus local candidate concepts only to the configured Qwen provider. Never sends XML or gold answers.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = parse_args()
    result = await write_current_mapping_baseline_reports(
        golden_dir=args.golden_dir,
        output_dir=args.output_dir,
        alignment_report_path=args.alignment_report,
        use_live_llm=args.use_live_llm,
    )
    accuracy = result["accuracy"]
    deterministic = accuracy["deterministic_mapping"]
    qwen = accuracy["qwen_mapping"]
    print(f"Predictions report: {result['paths']['predictions_json']}")
    print(f"Accuracy report: {result['paths']['accuracy_json']}")
    print(f"Error analysis report: {result['paths']['errors_json']}")
    print(f"Strict scoring rows: {accuracy['strict_scoring_rows']}")
    print(f"Ambiguous diagnostic rows: {accuracy['ambiguous_diagnostic_rows']}")
    print(f"Deterministic coverage: {deterministic['coverage']}")
    print(f"Deterministic accuracy: {deterministic['accuracy']}")
    print(f"Qwen status: {qwen['status']}")
    print(f"Qwen measurable: {qwen['measurable']}")
    print(f"External LLM called: {accuracy['run_metadata']['external_llm_called']}")
    print("Auditor XML sent externally: False")
    print("Gold answers sent externally: False")
    return 0


def main() -> int:
    return asyncio.run(_main())


if __name__ == "__main__":
    raise SystemExit(main())

