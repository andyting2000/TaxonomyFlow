"""Run Feature #18D-B expanded PDF-XBRL rulebook hardening."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pdf_xbrl_rulebook_hardening import write_hardening_reports


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Harden the expanded offline PDF-XBRL mapping rulebook and produce a deterministic-first integration plan.",
    )
    parser.add_argument("--dataset-dir", default="benchmark_mbrs_pairs", help="Local benchmark PDF/XML pair directory.")
    parser.add_argument("--expanded-rulebook", default="reports/pdf_xbrl_rulebook_expanded_18d_a.json", help="Feature #18D-A expanded rulebook report.")
    parser.add_argument("--expansion-replay", default="reports/pdf_xbrl_rulebook_expansion_replay_18d_a.json", help="Feature #18D-A expansion replay report.")
    parser.add_argument("--alignment-report", default="reports/pdf_xbrl_alignment_18a.json", help="Feature #18A alignment report for replay reconstruction.")
    parser.add_argument("--source-replay-report", default="reports/pdf_xbrl_rulebook_replay_18c.json", help="Feature #18C replay report used by #18D-A context upgrades.")
    parser.add_argument("--output-dir", default="reports", help="Directory for #18D-B reports.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = write_hardening_reports(
        dataset_dir=args.dataset_dir,
        expanded_rulebook_path=args.expanded_rulebook,
        expansion_replay_path=args.expansion_replay,
        alignment_report_path=args.alignment_report,
        source_replay_report_path=args.source_replay_report,
        output_dir=args.output_dir,
    )
    summary = result["hardening"]["summary"]
    recommendation = summary["recommendation"]
    outlier = result["outlier_replay"]["summary"]
    print("Feature #18D-B PDF-XBRL rulebook hardening reports written:")
    for name, path in result["paths"].items():
        print(f"- {name}: {path}")
    print("")
    print("Rule readiness:")
    print(f"- production_candidate: {summary['production_candidate_count']}")
    print(f"- advisory_candidate: {summary['advisory_candidate_count']}")
    print(f"- review_only: {summary['review_only_count']}")
    print(f"- downgrade_to_review_required: {summary['downgrade_to_review_required_count']}")
    print(f"- exclude: {summary['exclude_count']}")
    print("")
    print("False positives:")
    print(f"- active_false_positive_count: {summary['false_positive_root_cause_count']}")
    print("")
    print("Shield Plus outlier:")
    print(f"- observations: {outlier.get('pdf_observations', 0)}")
    print(f"- predictions: {outlier.get('replay_predictions', 0)}")
    print(f"- false_positives: {outlier.get('false_positive_count', 0)}")
    print("")
    print(f"Recommendation: {recommendation['recommended_next_feature']}")
    print("Safety:")
    for key, value in summary["safety"].items():
        print(f"- {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
