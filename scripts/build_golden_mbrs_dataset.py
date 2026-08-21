"""Build the offline Golden MBRS PDF/XML mapping dataset reports."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.golden_mbrs_dataset import write_golden_mbrs_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the offline Feature #17A Golden MBRS alignment and evaluation reports.")
    parser.add_argument("--cases-dir", type=Path, default=PROJECT_ROOT / "benchmark_mbrs_pairs")
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "reports")
    parser.add_argument("--normalized-extraction-report", action="append", default=[], help="Additional local normalized Azure DI JSON report.")
    parser.add_argument("--deterministic-mapping-report", action="append", default=[], help="Additional local deterministic mapping JSON report.")
    parser.add_argument("--qwen-mapping-report", action="append", default=[], help="Additional local Qwen mapping JSON report. No live Qwen request is made.")
    parser.add_argument("--no-live-llm", action="store_true", help="Explicitly record offline-only operation. Live LLM calls are not implemented by this harness.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_golden_mbrs_reports(
        cases_dir=args.cases_dir,
        output_dir=args.output_dir,
        normalized_extraction_reports=args.normalized_extraction_report,
        deterministic_mapping_reports=args.deterministic_mapping_report,
        qwen_mapping_reports=args.qwen_mapping_report,
    )
    metrics = result["summary"]["metrics"]
    print(f"Golden MBRS summary: {result['paths']['summary_json']}")
    print(f"Golden MBRS alignment: {result['paths']['alignment_json']}")
    print(f"Golden MBRS baseline: {result['paths']['baseline_json']}")
    print(f"Ready PDF/XML pairs: {metrics['ready_pdf_xml_pairs']}")
    print(f"Cases with normalized Azure DI extraction: {metrics['cases_with_normalized_azure_di_extraction']}")
    print(f"Strong gold examples: {metrics['strong_gold_examples']}")
    print(f"Ambiguous alignments: {metrics['ambiguous_alignments']}")
    print("External LLM called: False")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
