"""Build read-only #13T manual-review policy, gate, and queue reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.extraction_v2_manual_review_policy import (  # noqa: E402
    build_manual_review_policy_reports,
    render_gate_markdown,
    render_policy_markdown,
    render_queue_markdown,
)


REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_CLEANED = REPORTS_DIR / "extraction_v2_cleaned_candidates_13s.json"
DEFAULT_DUPLICATE = REPORTS_DIR / "extraction_v2_duplicate_conflict_13s.json"
DEFAULT_READINESS = REPORTS_DIR / "extraction_v2_mapping_readiness_after_13s.json"
DEFAULT_QUALITY = REPORTS_DIR / "extraction_v2_candidate_quality_13r.json"
DEFAULT_REFERENCE = REPORTS_DIR / "reference_xbrl_report_20260511T082343Z.json"
DEFAULT_POLICY_JSON = REPORTS_DIR / "extraction_v2_manual_review_policy_13t.json"
DEFAULT_GATE_JSON = REPORTS_DIR / "extraction_v2_mapping_candidate_gate_13t.json"
DEFAULT_QUEUE_JSON = REPORTS_DIR / "extraction_v2_manual_review_queue_13t.json"


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build read-only manual-review policy and mapping gate reports for cleaned Extraction v2 candidates."
    )
    parser.add_argument("--cleaned-candidates", type=Path, default=DEFAULT_CLEANED)
    parser.add_argument("--duplicate-report", type=Path, default=DEFAULT_DUPLICATE)
    parser.add_argument("--readiness-report", type=Path, default=DEFAULT_READINESS)
    parser.add_argument("--quality-report", type=Path, default=DEFAULT_QUALITY)
    parser.add_argument("--reference-report", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--policy-json", type=Path, default=DEFAULT_POLICY_JSON)
    parser.add_argument("--policy-md", type=Path)
    parser.add_argument("--gate-json", type=Path, default=DEFAULT_GATE_JSON)
    parser.add_argument("--gate-md", type=Path)
    parser.add_argument("--queue-json", type=Path, default=DEFAULT_QUEUE_JSON)
    parser.add_argument("--queue-md", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    policy_json = args.policy_json
    gate_json = args.gate_json
    queue_json = args.queue_json
    policy_md = args.policy_md or policy_json.with_suffix(".md")
    gate_md = args.gate_md or gate_json.with_suffix(".md")
    queue_md = args.queue_md or queue_json.with_suffix(".md")
    for path in (policy_json, gate_json, queue_json, policy_md, gate_md, queue_md):
        path.parent.mkdir(parents=True, exist_ok=True)

    policy_report, gate_report, queue_report = build_manual_review_policy_reports(
        cleaned_report=load_json(args.cleaned_candidates),
        duplicate_report=load_json(args.duplicate_report),
        readiness_report=load_json(args.readiness_report),
        quality_report=load_json(args.quality_report),
        reference_report=load_json(args.reference_report),
        input_paths={
            "cleaned_candidates": str(args.cleaned_candidates),
            "duplicate_report": str(args.duplicate_report),
            "readiness_report": str(args.readiness_report),
            "quality_report": str(args.quality_report) if args.quality_report.exists() else None,
            "reference_report": str(args.reference_report) if args.reference_report.exists() else None,
        },
        output_paths={
            "policy": str(policy_json),
            "gate": str(gate_json),
            "queue": str(queue_json),
        },
    )

    policy_json.write_text(json.dumps(policy_report, indent=2, default=str), encoding="utf-8")
    policy_md.write_text(render_policy_markdown(policy_report), encoding="utf-8")
    gate_json.write_text(json.dumps(gate_report, indent=2, default=str), encoding="utf-8")
    gate_md.write_text(render_gate_markdown(gate_report), encoding="utf-8")
    queue_json.write_text(json.dumps(queue_report, indent=2, default=str), encoding="utf-8")
    queue_md.write_text(render_queue_markdown(queue_report), encoding="utf-8")

    counts = gate_report["aggregate_gate_counts"]
    summary = gate_report["mapping_candidate_input_summary"]
    print(f"Manual-review policy report: {policy_json}")
    print(f"Mapping candidate gate report: {gate_json}")
    print(f"Manual-review queue report: {queue_json}")
    print(f"Auto mappable candidates: {counts.get('auto_mappable_candidate', 0)}")
    print(f"Suggest-only candidates: {counts.get('suggest_mapping_only', 0)}")
    print(f"Manual review required: {counts.get('manual_review_required', 0)}")
    print(f"Blocked/context candidates: {summary.get('blocked_from_13u_count', 0)}")
    print(f"Queue items: {queue_report.get('queue_item_count', 0)}")
    print(f"Recommended next feature: {policy_report.get('recommended_next_feature')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
