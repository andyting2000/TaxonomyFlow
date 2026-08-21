"""Run the read-only Azure Document Intelligence Extraction v2 spike."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.discover_benchmark_cases import discover_benchmark_cases  # noqa: E402
from services.azure_document_intelligence_provider import (  # noqa: E402
    AzureDocumentIntelligenceConfigError,
    AzureDocumentIntelligenceProvider,
)
from services.extraction_v2_azure_di_pipeline import (  # noqa: E402
    build_azure_di_report,
    build_case_report,
    build_cost_runtime_report,
    convert_azure_di_result_to_candidates,
    render_azure_di_report_markdown,
    render_cost_runtime_markdown,
)


REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_JSON = REPORTS_DIR / "azure_di_extraction_v2_report_13w_spike.json"
DEFAULT_COMPARISON_JSON = REPORTS_DIR / "azure_di_vs_hf_qwen_comparison_13w_spike.json"
DEFAULT_COST_JSON = REPORTS_DIR / "azure_di_cost_runtime_estimate_13w_spike.json"


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_or_discover_manifest(cases_dir: Path, manifest_path: Path) -> dict[str, Any]:
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = discover_benchmark_cases(cases_dir)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest


def select_cases(manifest: dict[str, Any], *, requested_case: str | None, run_all: bool, max_cases: int | None) -> list[dict[str, Any]]:
    ready = [case for case in manifest.get("cases", []) if case.get("status") == "ready"]
    if requested_case:
        ready = [case for case in ready if case.get("case_id") == requested_case]
    elif not run_all:
        ready = ready[:1]
    if max_cases is not None:
        ready = ready[: max(max_cases, 0)]
    return ready


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Azure DI prebuilt-layout against benchmark cases.")
    parser.add_argument("--cases-dir", type=Path, default=PROJECT_ROOT / "benchmark_cases")
    parser.add_argument("--manifest-json", type=Path, default=REPORTS_DIR / "benchmark_cases_manifest.json")
    parser.add_argument("--case")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--pages", help="Azure DI pages option, for example 1-3 or 1,3.")
    parser.add_argument("--limit-pages", help="Alias for --pages during spike runs.")
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--run-id", default="azure_di_prebuilt_layout_7cases")
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-md", type=Path)
    parser.add_argument("--cost-json", type=Path, default=DEFAULT_COST_JSON)
    parser.add_argument("--cost-md", type=Path)
    return parser.parse_args()


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    pages = args.pages or args.limit_pages
    output_md = args.output_md or args.output_json.with_suffix(".md")
    cost_md = args.cost_md or args.cost_json.with_suffix(".md")
    manifest = load_or_discover_manifest(args.cases_dir, args.manifest_json)
    selected_cases = select_cases(
        manifest,
        requested_case=args.case,
        run_all=bool(args.all),
        max_cases=args.max_cases,
    )
    if not selected_cases:
        print("No ready benchmark cases selected.", file=sys.stderr)
        return 2

    started = iso_now()
    started_monotonic = time.monotonic()
    provider = AzureDocumentIntelligenceProvider()
    case_reports: list[dict[str, Any]] = []
    try:
        provider.validate_config()
    except AzureDocumentIntelligenceConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    for index, case in enumerate(selected_cases, start=1):
        pdf_path = PROJECT_ROOT / str(case.get("pdf_path") or "")
        if args.progress:
            print(f"[13W-AzureDI] {index}/{len(selected_cases)} {case.get('case_id')} {pdf_path.name}", flush=True)
        azure_result = provider.analyze_pdf_path(pdf_path, pages=pages)
        candidates = convert_azure_di_result_to_candidates(
            azure_result,
            case_id=str(case.get("case_id") or ""),
            source_pdf=str(case.get("pdf_path") or pdf_path),
        )
        case_report = build_case_report(case=case, azure_result=azure_result, candidates=candidates)
        case_reports.append(case_report)
        if args.progress:
            print(
                "[13W-AzureDI] {case_id}: status={status} pages={pages} tables={tables} candidates={candidates}".format(
                    case_id=case_report.get("case_id"),
                    status=case_report.get("status"),
                    pages=case_report.get("pages_analyzed"),
                    tables=case_report.get("azure_di_tables_detected"),
                    candidates=case_report.get("candidate_count"),
                ),
                flush=True,
            )

    report = build_azure_di_report(
        case_reports,
        cases_dir=str(args.cases_dir),
        output_json=str(args.output_json),
        run_id=args.run_id,
        model_id=provider.model_id,
        started_at=started,
        total_runtime_seconds=round(time.monotonic() - started_monotonic, 3),
        pages_option=pages,
    )
    write_json(args.output_json, report)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_azure_di_report_markdown(report), encoding="utf-8")

    cost_report = build_cost_runtime_report(report, output_path=str(args.cost_json))
    write_json(args.cost_json, cost_report)
    cost_md.parent.mkdir(parents=True, exist_ok=True)
    cost_md.write_text(render_cost_runtime_markdown(cost_report), encoding="utf-8")

    aggregate = report["aggregate_metrics"]
    print(f"Azure DI extraction report: {args.output_json}")
    print(f"Azure DI markdown report: {output_md}")
    print(f"Azure DI cost/runtime report: {args.cost_json}")
    print(f"Cases processed: {aggregate.get('total_cases_processed', 0)}")
    print(f"Pages processed: {aggregate.get('azure_di_pages_processed', 0)}")
    print(f"Candidate rows: {aggregate.get('total_candidate_rows', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
