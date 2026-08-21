"""Resolve Extraction v2 duplicate/conflict candidates in read-only benchmark reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.extraction_v2_duplicate_resolver import (  # noqa: E402
    render_cleaned_candidates_markdown,
    render_duplicate_conflict_markdown,
    render_readiness_after_13s_markdown,
    resolve_extraction_v2_duplicates,
)


REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_COMPARISON = REPORTS_DIR / "v2_reference_comparison_20260512T145407Z.json"
DEFAULT_REFERENCE = REPORTS_DIR / "reference_xbrl_report_20260511T082343Z.json"
DEFAULT_DUPLICATE_JSON = REPORTS_DIR / "extraction_v2_duplicate_conflict_13s.json"
DEFAULT_CLEANED_JSON = REPORTS_DIR / "extraction_v2_cleaned_candidates_13s.json"
DEFAULT_READINESS_JSON = REPORTS_DIR / "extraction_v2_mapping_readiness_after_13s.json"


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only duplicate/conflict control for Extraction v2 benchmark candidates.")
    parser.add_argument("--v2-report", type=Path, required=True)
    parser.add_argument("--quality-report", type=Path, required=True)
    parser.add_argument("--readiness-report", type=Path, required=True)
    parser.add_argument("--comparison-report", type=Path, default=DEFAULT_COMPARISON)
    parser.add_argument("--reference-report", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--duplicate-json", type=Path, default=DEFAULT_DUPLICATE_JSON)
    parser.add_argument("--duplicate-md", type=Path)
    parser.add_argument("--cleaned-json", type=Path, default=DEFAULT_CLEANED_JSON)
    parser.add_argument("--cleaned-md", type=Path)
    parser.add_argument("--readiness-json", type=Path, default=DEFAULT_READINESS_JSON)
    parser.add_argument("--readiness-md", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    duplicate_json = args.duplicate_json
    cleaned_json = args.cleaned_json
    readiness_json = args.readiness_json
    duplicate_md = args.duplicate_md or duplicate_json.with_suffix(".md")
    cleaned_md = args.cleaned_md or cleaned_json.with_suffix(".md")
    readiness_md = args.readiness_md or readiness_json.with_suffix(".md")
    for path in (duplicate_json, cleaned_json, readiness_json, duplicate_md, cleaned_md, readiness_md):
        path.parent.mkdir(parents=True, exist_ok=True)

    duplicate_report, cleaned_report, readiness_after = resolve_extraction_v2_duplicates(
        v2_report=load_json(args.v2_report),
        quality_report=load_json(args.quality_report),
        readiness_report=load_json(args.readiness_report),
        comparison_report=load_json(args.comparison_report),
        reference_report=load_json(args.reference_report),
        input_paths={
            "v2_report": str(args.v2_report),
            "quality_report": str(args.quality_report),
            "readiness_report": str(args.readiness_report),
            "comparison_report": str(args.comparison_report) if args.comparison_report.exists() else None,
            "reference_report": str(args.reference_report) if args.reference_report.exists() else None,
        },
        output_paths={
            "duplicate": str(duplicate_json),
            "cleaned": str(cleaned_json),
            "readiness_after": str(readiness_json),
        },
    )

    duplicate_json.write_text(json.dumps(duplicate_report, indent=2, default=str), encoding="utf-8")
    duplicate_md.write_text(render_duplicate_conflict_markdown(duplicate_report), encoding="utf-8")
    cleaned_json.write_text(json.dumps(cleaned_report, indent=2, default=str), encoding="utf-8")
    cleaned_md.write_text(render_cleaned_candidates_markdown(cleaned_report), encoding="utf-8")
    readiness_json.write_text(json.dumps(readiness_after, indent=2, default=str), encoding="utf-8")
    readiness_md.write_text(render_readiness_after_13s_markdown(readiness_after), encoding="utf-8")

    aggregate = duplicate_report["aggregate"]
    print(f"Duplicate/conflict report: {duplicate_json}")
    print(f"Cleaned candidate report: {cleaned_json}")
    print(f"Post-13S readiness report: {readiness_json}")
    print(f"Candidates analyzed: {aggregate.get('total_candidates_analyzed', 0)}")
    print(f"Suppressed exact duplicates: {aggregate.get('safe_suppression_count', 0)}")
    print(f"Downgraded candidates: {aggregate.get('downgrade_count', 0)}")
    print(f"Converted comparative candidates: {aggregate.get('converted_row_type_count', 0)}")
    print(f"Conflict review candidates: {aggregate.get('conflict_review_count', 0)}")
    print(f"Recommended next feature: {readiness_after.get('recommended_next_feature')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
