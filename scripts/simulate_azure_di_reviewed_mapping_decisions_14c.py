"""Simulate reviewed Azure DI mapping decisions without approving mappings."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.azure_di_reviewed_mapping_simulator import (  # noqa: E402
    DEFAULT_HANDOFF_CONTRACT,
    DEFAULT_REVIEW_POLICY,
    DEFAULT_REVIEW_QUEUE,
    SimulationPolicy,
    render_eligibility_markdown,
    run_reviewed_mapping_simulation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build #14C simulated reviewed mapping decisions from #14B review queue reports."
    )
    parser.add_argument("--review-queue", type=Path, default=PROJECT_ROOT / DEFAULT_REVIEW_QUEUE)
    parser.add_argument("--review-policy", type=Path, default=PROJECT_ROOT / DEFAULT_REVIEW_POLICY)
    parser.add_argument("--handoff-contract", type=Path, default=PROJECT_ROOT / DEFAULT_HANDOFF_CONTRACT)
    parser.add_argument("--run-id", default="azure_di_reviewed_mapping_simulation_14c")
    parser.add_argument("--output-prefix", type=Path)
    parser.add_argument("--approve-ready-only", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--simulate-confirm-medium", action="store_true")
    parser.add_argument("--simulate-choose-top-ambiguous", action="store_true")
    parser.add_argument("--strict", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    policy = SimulationPolicy(
        approve_ready_only=bool(args.approve_ready_only),
        simulate_confirm_medium=bool(args.simulate_confirm_medium),
        simulate_choose_top_ambiguous=bool(args.simulate_choose_top_ambiguous),
        strict=bool(args.strict),
    )
    result = run_reviewed_mapping_simulation(
        review_queue_path=args.review_queue,
        review_policy_path=args.review_policy,
        handoff_contract_path=args.handoff_contract,
        run_id=args.run_id,
        output_prefix=args.output_prefix,
        simulation_policy=policy,
    )
    paths = result["paths"]
    decisions = result["decisions_report"]
    handoff = result["handoff_report"]
    eligibility = result["eligibility_report"]
    print(f"Azure DI simulated reviewed mapping decisions: {paths.decisions_json}")
    print(f"Azure DI simulated reviewed mapping handoff: {paths.handoff_json}")
    print(f"Azure DI XBRL eligibility summary: {paths.eligibility_json}")
    print(f"Azure DI review simulation policy: {paths.policy_json}")
    print(f"Simulated decisions: {decisions.get('simulated_decision_count', 0)}")
    print(f"Simulated approved: {decisions.get('simulated_approved_count', 0)}")
    print(f"XBRL eligible simulated handoff items: {handoff.get('xbrl_eligible_count', 0)}")
    print(f"Decision type counts: {decisions.get('decision_type_counts', {})}")
    print(f"Recommended next feature: {eligibility.get('recommended_next_feature')}")
    if args.verbose:
        print(render_eligibility_markdown(eligibility).split("## Top XBRL Blockers", 1)[0].strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

