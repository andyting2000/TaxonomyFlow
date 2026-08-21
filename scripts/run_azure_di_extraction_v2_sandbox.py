"""Run the Azure DI-first Extraction v2 sandbox path."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.extraction_v2_azure_di_sandbox import (  # noqa: E402
    APPROVAL_MESSAGE,
    AzureDISandboxApprovalError,
    AzureDISandboxInputError,
    build_dry_run_plan,
    run_azure_di_sandbox,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a read-only Azure DI-first Extraction v2 sandbox.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", type=Path, help="Path to a single PDF.")
    source.add_argument("--case-dir", type=Path, help="Benchmark case directory containing one PDF.")
    parser.add_argument("--run-id", default="azure_di_sandbox_13x")
    parser.add_argument("--output-prefix", type=Path, default=PROJECT_ROOT / "reports" / "azure_di_sandbox")
    parser.add_argument("--approve-azure-document-intelligence-upload", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-quality-gates", action="store_true")
    parser.add_argument("--pages", help="Optional Azure DI pages range, for example 1-3 or 1,3.")
    parser.add_argument("--max-pages", type=int, help="Convenience alias that becomes pages 1-N when --pages is absent.")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def _print_plan(plan: dict) -> None:
    print("Azure DI sandbox dry-run plan")
    print(f"PDF: {plan['input']['pdf_path']}")
    print(f"Case ID: {plan['input']['case_id']}")
    print(f"Pages: {plan['input']['pages']}")
    print(f"Skip quality gates: {plan['input']['skip_quality_gates']}")
    print(f"Would call Azure Document Intelligence: {plan['would_call_azure_document_intelligence']}")
    print(f"Approval required for live run: {plan['approval_required_for_live_run']}")
    if plan.get("would_write_reports"):
        print("Report paths:")
        for _name, path in plan["would_write_reports"].items():
            print(f"- {path}")


def main() -> int:
    args = parse_args()
    try:
        if args.dry_run:
            plan = build_dry_run_plan(
                pdf=args.pdf,
                case_dir=args.case_dir,
                run_id=args.run_id,
                output_prefix=args.output_prefix,
                skip_quality_gates=args.skip_quality_gates,
                pages=args.pages,
                max_pages=args.max_pages,
            )
            _print_plan(plan)
            if args.verbose:
                print(json.dumps(plan, indent=2, default=str))
            return 0
        result = run_azure_di_sandbox(
            pdf=args.pdf,
            case_dir=args.case_dir,
            run_id=args.run_id,
            output_prefix=args.output_prefix,
            approve_azure_document_intelligence_upload=args.approve_azure_document_intelligence_upload,
            dry_run=False,
            skip_quality_gates=args.skip_quality_gates,
            pages=args.pages,
            max_pages=args.max_pages,
            progress=print if args.progress else None,
        )
    except AzureDISandboxApprovalError:
        print(APPROVAL_MESSAGE, file=sys.stderr)
        return 2
    except AzureDISandboxInputError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    paths = result["paths"]
    extraction = result["extraction_report"]
    summary = result["summary_report"]
    metrics = extraction["aggregate_metrics"]
    print(f"Azure DI sandbox extraction report: {paths.extraction_json}")
    print(f"Azure DI sandbox summary report: {paths.summary_json}")
    if not args.skip_quality_gates:
        print(f"Azure DI sandbox candidate quality report: {paths.quality_json}")
        print(f"Azure DI sandbox duplicate/conflict report: {paths.duplicate_json}")
        print(f"Azure DI sandbox manual-review queue report: {paths.manual_review_queue_json}")
        print(f"Azure DI sandbox mapping handoff report: {paths.mapping_handoff_json}")
    print(f"Candidates: {metrics.get('total_candidates', 0)}")
    print(f"Pages processed: {metrics.get('pages_processed', 0)}")
    print(f"Tables detected: {metrics.get('tables_detected', 0)}")
    print(f"Ready for mapping-candidate generation: {summary['summary'].get('ready_for_mapping_candidate_generation')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
