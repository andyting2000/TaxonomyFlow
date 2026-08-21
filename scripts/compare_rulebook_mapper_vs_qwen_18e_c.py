"""Generate Feature #18E-C offline deterministic-vs-Qwen mapper comparison reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.mapper_comparison_analysis import (  # noqa: E402
    build_reports,
    load_deterministic_report,
    load_qwen_report,
    write_reports,
)


DEFAULT_DETERMINISTIC_REPORT = ROOT / "reports" / "rulebook_mapper_template_optimized_18e_b.json"
DEFAULT_OUTPUT_DIR = ROOT / "reports"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--deterministic-report",
        default=str(DEFAULT_DETERMINISTIC_REPORT),
        help="Path to the #18E-B deterministic mapper report.",
    )
    parser.add_argument(
        "--qwen-report",
        default=None,
        help="Optional explicit cached Qwen/LLM report path. If omitted, reports directory is searched.",
    )
    parser.add_argument(
        "--qwen-report-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory searched for cached Qwen/LLM reports when --qwen-report is omitted.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for #18E-C JSON/Markdown reports.",
    )
    parser.add_argument(
        "--allow-missing-qwen-report",
        action="store_true",
        help="Produce missing-input reports instead of failing when no cached Qwen report is found.",
    )
    parser.add_argument(
        "--debug-label",
        default=None,
        help="Optional label substring for printing matching comparison rows after reports are written.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    deterministic = load_deterministic_report(args.deterministic_report)
    qwen = load_qwen_report(
        qwen_report=args.qwen_report,
        report_dir=args.qwen_report_dir,
        allow_missing=args.allow_missing_qwen_report,
    )
    reports = build_reports(deterministic, qwen)
    paths = write_reports(reports, output_dir=args.output_dir)
    summary = reports["summary"]["summary"]

    print(
        json.dumps(
            {
                "feature": "18E-C",
                "deterministic_report": deterministic.get("source_file"),
                "qwen_report": qwen.get("source_file"),
                "qwen_status": qwen.get("status"),
                "total_observations": summary.get("total_observations"),
                "deterministic_coverage_rate": summary.get("deterministic_coverage_rate"),
                "qwen_coverage_rate": summary.get("qwen_coverage_rate"),
                "combined_coverage_rate": summary.get("combined_coverage_rate"),
                "both_agree_same_qname": summary.get("both_agree_same_qname"),
                "both_suggest_conflict": summary.get("both_suggest_conflict"),
                "high_risk_conflict_count": summary.get("high_risk_conflict_count"),
                "recommended_next_feature": reports["summary"]["recommendation"]["recommended_next_feature"],
                "paths": paths,
            },
            indent=2,
        )
    )

    if args.debug_label:
        needle = args.debug_label.lower()
        matches = [
            record
            for record in reports["comparison"].get("comparison_records", [])
            if needle in str(record.get("pdf_label") or "").lower()
        ][:20]
        print(json.dumps({"debug_label": args.debug_label, "matches": matches}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

