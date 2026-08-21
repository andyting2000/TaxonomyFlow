"""Build read-only #13V mapping handoff reports from #13S/#13T/#13U reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.extraction_v2_mapping_handoff import (  # noqa: E402
    build_mapping_handoff_reports,
    render_candidates_markdown,
    render_contract_markdown,
    render_validation_markdown,
)


REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_CLEANED = REPORTS_DIR / "extraction_v2_cleaned_candidates_13s.json"
DEFAULT_GATE = REPORTS_DIR / "extraction_v2_mapping_candidate_gate_13t.json"
DEFAULT_QUEUE = REPORTS_DIR / "extraction_v2_manual_review_queue_13t.json"
DEFAULT_DATA_CONTRACT = REPORTS_DIR / "manual_review_queue_data_contract_13u.json"
DEFAULT_UI_API_PLAN = REPORTS_DIR / "manual_review_queue_ui_api_plan_13u.json"
DEFAULT_CANDIDATES = REPORTS_DIR / "extraction_v2_mapping_handoff_candidates_13v.json"
DEFAULT_VALIDATION = REPORTS_DIR / "extraction_v2_mapping_handoff_validation_13v.json"
DEFAULT_CONTRACT = REPORTS_DIR / "extraction_v2_mapping_handoff_contract_13v.json"


def load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a read-only Extraction v2 mapping handoff contract package."
    )
    parser.add_argument("--cleaned-candidates", type=Path, default=DEFAULT_CLEANED)
    parser.add_argument("--mapping-gate-report", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--manual-review-queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--data-contract", type=Path, default=DEFAULT_DATA_CONTRACT)
    parser.add_argument("--ui-api-plan", type=Path, default=DEFAULT_UI_API_PLAN)
    parser.add_argument("--candidates-json", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--candidates-md", type=Path)
    parser.add_argument("--validation-json", type=Path, default=DEFAULT_VALIDATION)
    parser.add_argument("--validation-md", type=Path)
    parser.add_argument("--contract-json", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--contract-md", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candidates_md = args.candidates_md or args.candidates_json.with_suffix(".md")
    validation_md = args.validation_md or args.validation_json.with_suffix(".md")
    contract_md = args.contract_md or args.contract_json.with_suffix(".md")

    input_paths = {
        "cleaned_candidates": str(args.cleaned_candidates),
        "mapping_gate_report": str(args.mapping_gate_report),
        "manual_review_queue": str(args.manual_review_queue),
        "data_contract": str(args.data_contract),
        "ui_api_plan": str(args.ui_api_plan) if args.ui_api_plan.exists() else None,
    }
    candidates_report, validation_report, contract_report = build_mapping_handoff_reports(
        cleaned_report=load_json(args.cleaned_candidates),
        mapping_gate_report=load_json(args.mapping_gate_report),
        manual_review_queue=load_json(args.manual_review_queue),
        data_contract=load_json(args.data_contract),
        ui_api_plan=load_json(args.ui_api_plan),
        input_paths=input_paths,
    )

    write_json(args.candidates_json, candidates_report)
    candidates_md.parent.mkdir(parents=True, exist_ok=True)
    candidates_md.write_text(render_candidates_markdown(candidates_report), encoding="utf-8")
    write_json(args.validation_json, validation_report)
    validation_md.parent.mkdir(parents=True, exist_ok=True)
    validation_md.write_text(render_validation_markdown(validation_report), encoding="utf-8")
    write_json(args.contract_json, contract_report)
    contract_md.parent.mkdir(parents=True, exist_ok=True)
    contract_md.write_text(render_contract_markdown(contract_report), encoding="utf-8")

    print(f"Mapping handoff candidates report: {args.candidates_json}")
    print(f"Mapping handoff validation report: {args.validation_json}")
    print(f"Mapping handoff contract report: {args.contract_json}")
    print(f"Handoff candidates: {candidates_report.get('total_handoff_candidates', 0)}")
    print(f"Auto mappable: {candidates_report.get('auto_mappable_count', 0)}")
    print(f"Suggest-only: {candidates_report.get('suggest_mapping_only_count', 0)}")
    print(f"Requires confirmation: {candidates_report.get('requires_confirmation_count', 0)}")
    print(f"Excluded: {candidates_report.get('excluded_count', 0)}")
    print(f"Validation passed: {validation_report.get('validation_passed')}")
    return 0 if validation_report.get("validation_passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
