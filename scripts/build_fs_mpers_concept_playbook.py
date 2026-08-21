"""Build local FS-MPERS concept-card playbook reports for #17D-pre."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.fs_mpers_concept_playbook import (
    build_sample_retrieval_report,
    load_concept_playbook,
    validate_concept_playbook_reports,
    write_concept_playbook_reports,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build local FS-MPERS concept-card RAG reports from the #17A golden mapping dataset."
    )
    parser.add_argument(
        "--golden-dir",
        default="benchmark_mbrs_pairs",
        help="Local golden PDF/XML pair directory. Used for report metadata; auditor XML is not read by this script.",
    )
    parser.add_argument(
        "--alignment-report",
        default="reports/golden_mbrs_mapping_alignment_17a.json",
        help="Local #17A mapping alignment report containing strong gold examples.",
    )
    parser.add_argument(
        "--reports-dir",
        default="reports",
        help="Directory where #17D-pre reports will be written.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate generated #17D-pre report files and payload leakage guards.",
    )
    parser.add_argument(
        "--sample-retrieval",
        action="store_true",
        help="Print sample retrieval results after building reports.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = write_concept_playbook_reports(
        golden_dir=args.golden_dir,
        alignment_report_path=args.alignment_report,
        reports_dir=args.reports_dir,
    )
    print("fs_mpers_concept_playbook_built", json.dumps({key: str(path) for key, path in paths.items()}, sort_keys=True))

    if args.validate:
        validation = validate_concept_playbook_reports(args.reports_dir)
        print("fs_mpers_concept_playbook_validation", json.dumps(validation, sort_keys=True))
        if not validation.get("valid"):
            return 1

    if args.sample_retrieval:
        playbook = load_concept_playbook(Path(args.reports_dir) / "fs_mpers_concept_playbook_17d_pre.json")
        report = build_sample_retrieval_report(playbook)
        summary = {
            sample["sample_label"]: sample["top_concept_qnames"][:3]
            for sample in report.get("samples") or []
        }
        print("fs_mpers_sample_retrieval", json.dumps(summary, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
