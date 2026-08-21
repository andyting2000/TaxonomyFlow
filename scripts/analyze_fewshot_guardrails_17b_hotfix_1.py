"""Generate local few-shot guardrail analysis reports for #17B-hotfix-1."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.fewshot_qwen_mapping import (  # noqa: E402
    OUTPUT_STEM_ACCURACY,
    OUTPUT_STEM_COMPARISON,
    OUTPUT_STEM_PREDICTIONS,
    write_guardrail_hotfix_reports,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze existing #17B few-shot Qwen errors and generate local guardrail hotfix reports."
    )
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument(
        "--predictions-report",
        type=Path,
        default=PROJECT_ROOT / "reports" / f"{OUTPUT_STEM_PREDICTIONS}.json",
    )
    parser.add_argument(
        "--accuracy-report",
        type=Path,
        default=PROJECT_ROOT / "reports" / f"{OUTPUT_STEM_ACCURACY}.json",
    )
    parser.add_argument(
        "--comparison-report",
        type=Path,
        default=PROJECT_ROOT / "reports" / f"{OUTPUT_STEM_COMPARISON}.json",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_guardrail_hotfix_reports(
        output_dir=args.output_dir,
        predictions_report_path=args.predictions_report,
        accuracy_report_path=args.accuracy_report,
        comparison_report_path=args.comparison_report,
    )
    summary = result["analysis"]["summary"]
    projected = result["comparison"]["projected_after_guardrails"]
    print(f"Guardrail analysis report: {result['paths']['analysis_json']}")
    print(f"Guardrail comparison report: {result['paths']['comparison_json']}")
    print(f"Wrong concept rows: {summary['wrong_concept_rows']}")
    print(f"Candidate-missing wrong rows: {summary['candidate_missing_wrong_rows']}")
    print(f"Broad-substitution wrong rows: {summary['broad_substitution_wrong_rows']}")
    print(f"Projected wrong concepts: {projected.get('wrong_concept')}")
    print(f"Projected coverage: {projected.get('coverage')}")
    print(f"External LLM called: {result['analysis']['run_metadata']['external_llm_called']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
