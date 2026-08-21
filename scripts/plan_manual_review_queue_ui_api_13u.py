"""Generate Feature #13U manual-review queue UI/API planning reports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.extraction_v2_manual_review_planner import (  # noqa: E402
    build_manual_review_queue_plan_reports,
    render_data_contract_markdown,
    render_implementation_sequence_markdown,
    render_ui_api_plan_markdown,
)


DEFAULT_POLICY_PATH = Path("reports/extraction_v2_manual_review_policy_13t.json")
DEFAULT_GATE_PATH = Path("reports/extraction_v2_mapping_candidate_gate_13t.json")
DEFAULT_QUEUE_PATH = Path("reports/extraction_v2_manual_review_queue_13t.json")

DEFAULT_UI_API_JSON = Path("reports/manual_review_queue_ui_api_plan_13u.json")
DEFAULT_DATA_CONTRACT_JSON = Path("reports/manual_review_queue_data_contract_13u.json")
DEFAULT_SEQUENCE_JSON = Path("reports/manual_review_queue_implementation_sequence_13u.json")


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Expected object JSON at {path}")
    return data


def write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan manual-review queue UI/API workflow for Extraction v2 mapping cutover."
    )
    parser.add_argument("--manual-review-policy", type=Path, default=DEFAULT_POLICY_PATH)
    parser.add_argument("--mapping-gate-report", type=Path, default=DEFAULT_GATE_PATH)
    parser.add_argument("--manual-review-queue", type=Path, default=DEFAULT_QUEUE_PATH)
    parser.add_argument("--ui-api-plan-json", type=Path, default=DEFAULT_UI_API_JSON)
    parser.add_argument("--data-contract-json", type=Path, default=DEFAULT_DATA_CONTRACT_JSON)
    parser.add_argument("--implementation-sequence-json", type=Path, default=DEFAULT_SEQUENCE_JSON)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manual_review_policy = load_json(args.manual_review_policy)
    mapping_gate_report = load_json(args.mapping_gate_report)
    manual_review_queue = load_json(args.manual_review_queue)

    input_paths = {
        "manual_review_policy": str(args.manual_review_policy),
        "mapping_gate_report": str(args.mapping_gate_report),
        "manual_review_queue": str(args.manual_review_queue),
    }
    ui_api_plan, data_contract, implementation_sequence = build_manual_review_queue_plan_reports(
        manual_review_policy,
        mapping_gate_report,
        manual_review_queue,
        input_paths=input_paths,
    )

    write_json(args.ui_api_plan_json, ui_api_plan)
    write_json(args.data_contract_json, data_contract)
    write_json(args.implementation_sequence_json, implementation_sequence)

    ui_api_md = args.ui_api_plan_json.with_suffix(".md")
    data_contract_md = args.data_contract_json.with_suffix(".md")
    sequence_md = args.implementation_sequence_json.with_suffix(".md")
    write_text(ui_api_md, render_ui_api_plan_markdown(ui_api_plan))
    write_text(data_contract_md, render_data_contract_markdown(data_contract))
    write_text(sequence_md, render_implementation_sequence_markdown(implementation_sequence))

    summary = ui_api_plan.get("queue_summary", {})
    print("[13U] Manual-review UI/API planning reports written")
    print(f"[13U] UI/API plan: {args.ui_api_plan_json}")
    print(f"[13U] Data contract: {args.data_contract_json}")
    print(f"[13U] Implementation sequence: {args.implementation_sequence_json}")
    print(
        "[13U] Queue summary: "
        f"auto={summary.get('auto_mappable_candidate', 0)}, "
        f"suggest={summary.get('suggest_mapping_only', 0)}, "
        f"manual_review={summary.get('manual_review_required', 0)}, "
        f"blocked={summary.get('blocked_from_mapping', 0)}, "
        f"queue_items={summary.get('manual_review_queue_items', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
