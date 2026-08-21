"""Generate read-only Extraction v2 candidate quality and mapping readiness reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.extraction_v2_quality_analyzer import (  # noqa: E402
    analyze_candidate_quality_reports,
    render_candidate_quality_markdown,
    render_mapping_readiness_markdown,
)


REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_QUALITY_JSON = REPORTS_DIR / "extraction_v2_candidate_quality_13r.json"
DEFAULT_READINESS_JSON = REPORTS_DIR / "extraction_v2_mapping_readiness_13r.json"
DEFAULT_CLOSEOUT = REPORTS_DIR / "huggingface_qwen_benchmark_closeout_13q.json"


def load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze completed Extraction v2 benchmark candidates for quality and mapping readiness."
    )
    parser.add_argument("--v2-report", type=Path, required=True)
    parser.add_argument("--comparison-report", type=Path, required=True)
    parser.add_argument("--reference-report", type=Path, required=True)
    parser.add_argument("--closeout-report", type=Path, default=DEFAULT_CLOSEOUT)
    parser.add_argument("--quality-json", type=Path, default=DEFAULT_QUALITY_JSON)
    parser.add_argument("--quality-md", type=Path)
    parser.add_argument("--readiness-json", type=Path, default=DEFAULT_READINESS_JSON)
    parser.add_argument("--readiness-md", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    v2_report = load_json(args.v2_report)
    comparison_report = load_json(args.comparison_report)
    reference_report = load_json(args.reference_report)
    closeout_report = load_json(args.closeout_report) if args.closeout_report and args.closeout_report.exists() else None

    quality_json = args.quality_json
    readiness_json = args.readiness_json
    quality_md = args.quality_md or quality_json.with_suffix(".md")
    readiness_md = args.readiness_md or readiness_json.with_suffix(".md")
    for path in (quality_json, readiness_json, quality_md, readiness_md):
        path.parent.mkdir(parents=True, exist_ok=True)

    quality_report, readiness_report = analyze_candidate_quality_reports(
        v2_report=v2_report or {},
        comparison_report=comparison_report or {},
        reference_report=reference_report or {},
        closeout_report=closeout_report,
        input_paths={
            "v2_report": str(args.v2_report),
            "comparison_report": str(args.comparison_report),
            "reference_report": str(args.reference_report),
            "closeout_report": str(args.closeout_report) if args.closeout_report and args.closeout_report.exists() else None,
        },
    )
    quality_report["run_metadata"]["output_path"] = str(quality_json)
    readiness_report["run_metadata"]["output_path"] = str(readiness_json)

    quality_json.write_text(json.dumps(quality_report, indent=2, default=str), encoding="utf-8")
    quality_md.write_text(render_candidate_quality_markdown(quality_report), encoding="utf-8")
    readiness_json.write_text(json.dumps(readiness_report, indent=2, default=str), encoding="utf-8")
    readiness_md.write_text(render_mapping_readiness_markdown(readiness_report), encoding="utf-8")

    aggregate = quality_report["aggregate_candidate_counts"]
    readiness = readiness_report["aggregate_readiness_counts"]
    print(f"Candidate quality report: {quality_json}")
    print(f"Candidate quality markdown: {quality_md}")
    print(f"Mapping readiness report: {readiness_json}")
    print(f"Mapping readiness markdown: {readiness_md}")
    print(f"Candidates analyzed: {aggregate.get('total_candidates', 0)}")
    print(f"Readiness distribution: {readiness}")
    print(f"Recommended next feature: {readiness_report.get('recommended_next_feature')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
