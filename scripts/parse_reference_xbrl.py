"""Parse benchmark reference XML/XBRL files into read-only reports."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.discover_benchmark_cases import discover_benchmark_cases
from services.reference_xbrl_parser import ReferenceXBRLParseError, parse_reference_xbrl


REPORTS_DIR = PROJECT_ROOT / "reports"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_or_discover_manifest(cases_dir: Path, manifest_path: Path) -> dict:
    if manifest_path.exists():
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = discover_benchmark_cases(cases_dir)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    return manifest


def select_reference_cases(manifest: dict, requested_case: str | None, run_all: bool) -> list[dict]:
    ready = [
        case
        for case in manifest.get("cases", [])
        if case.get("status") == "ready" and case.get("reference_available") and case.get("reference_path")
    ]
    if requested_case:
        return [case for case in ready if case.get("case_id") == requested_case]
    if run_all or not requested_case:
        return ready
    return []


def build_report(case_reports: list[dict], *, cases_dir: str, output_json: Path) -> dict:
    warning_counts = Counter(
        warning
        for case_report in case_reports
        for warning in (case_report.get("parse_warnings") or [])
    )
    facts_by_namespace = Counter()
    for case_report in case_reports:
        facts_by_namespace.update(case_report.get("facts_by_namespace") or {})
    sample_facts = [
        fact
        for case_report in case_reports
        for fact in (case_report.get("sample_facts") or [])
    ][:30]
    return {
        "run_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "script": "scripts/parse_reference_xbrl.py",
            "read_only": True,
            "database_mutated": False,
            "production_behavior_changed": False,
            "ui_upload_required": False,
            "xbrl_generated": False,
            "arelle_validation_run": False,
            "openai_used": False,
            "cases_dir": cases_dir,
            "output_path": str(output_json),
        },
        "aggregate_metrics": {
            "total_cases_parsed": len(case_reports),
            "total_reference_files_parsed": sum(1 for report in case_reports if report.get("status") == "ok"),
            "total_facts": sum(report.get("total_facts", 0) for report in case_reports),
            "numeric_fact_count": sum(report.get("numeric_fact_count", 0) for report in case_reports),
            "text_fact_count": sum(report.get("text_fact_count", 0) for report in case_reports),
            "text_block_count": sum(report.get("text_block_count", 0) for report in case_reports),
            "nil_fact_count": sum(report.get("nil_fact_count", 0) for report in case_reports),
            "contexts_count": sum(report.get("contexts_count", 0) for report in case_reports),
            "units_count": sum(report.get("units_count", 0) for report in case_reports),
            "concepts_count": len(
                {
                    fact.get("qname")
                    for report in case_reports
                    for fact in (report.get("facts") or [])
                    if fact.get("qname")
                }
            ),
            "parse_warning_counts": dict(sorted(warning_counts.items())),
            "facts_by_namespace": dict(sorted(facts_by_namespace.items())),
        },
        "case_reports": case_reports,
        "sample_facts": sample_facts,
        "limitations": [
            "Reference XML/XBRL is parsed only for benchmark comparison.",
            "No generated XBRL, Arelle validation, DB mutation, UI upload, or production mapping is performed.",
        ],
    }


def render_markdown(report: dict) -> str:
    aggregate = report["aggregate_metrics"]
    lines = [
        "# Reference XML/XBRL Parsing Report",
        "",
        "## Executive Summary",
        "",
        f"- Cases parsed: {aggregate['total_cases_parsed']}",
        f"- Reference files parsed: {aggregate['total_reference_files_parsed']}",
        f"- Total facts: {aggregate['total_facts']}",
        f"- Numeric facts: {aggregate['numeric_fact_count']}",
        f"- Text facts: {aggregate['text_fact_count']}",
        f"- Text blocks: {aggregate['text_block_count']}",
        f"- Nil facts: {aggregate['nil_fact_count']}",
        f"- Contexts: {aggregate['contexts_count']}",
        f"- Units: {aggregate['units_count']}",
        f"- Concepts: {aggregate['concepts_count']}",
        f"- UI upload required: {report['run_metadata']['ui_upload_required']}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        "",
        "## Cases",
        "",
        "| Case | Status | Facts | Numeric | Text Facts | Text Blocks | Nil | Contexts | Units | Warnings |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case_report in report["case_reports"]:
        lines.append(
            "| {case_id} | {status} | {facts} | {numeric} | {text} | {blocks} | {nil} | {contexts} | {units} | {warnings} |".format(
                case_id=case_report.get("case_id"),
                status=case_report.get("status"),
                facts=case_report.get("total_facts", 0),
                numeric=case_report.get("numeric_fact_count", 0),
                text=case_report.get("text_fact_count", 0),
                blocks=case_report.get("text_block_count", 0),
                nil=case_report.get("nil_fact_count", 0),
                contexts=case_report.get("contexts_count", 0),
                units=case_report.get("units_count", 0),
                warnings=len(case_report.get("parse_warnings") or []),
            )
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Parse benchmark reference XML/XBRL files.")
    parser.add_argument("--cases-dir", type=Path, default=PROJECT_ROOT / "benchmark_cases")
    parser.add_argument("--manifest", type=Path, default=REPORTS_DIR / "benchmark_cases_manifest.json")
    parser.add_argument("--case")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_or_discover_manifest(args.cases_dir, args.manifest)
    selected_cases = select_reference_cases(manifest, args.case, args.all)

    case_reports = []
    for case in selected_cases:
        try:
            parsed = parse_reference_xbrl(
                case_id=case.get("case_id"),
                reference_path=case.get("reference_path"),
                reference_type=case.get("reference_type"),
            )
            parsed["status"] = "ok"
            case_reports.append(parsed)
        except (OSError, ReferenceXBRLParseError, etree.XMLSyntaxError) as exc:  # type: ignore[name-defined]
            case_reports.append(
                {
                    "case_id": case.get("case_id"),
                    "reference_path": case.get("reference_path"),
                    "reference_type": case.get("reference_type"),
                    "status": "error",
                    "total_facts": 0,
                    "numeric_fact_count": 0,
                    "text_fact_count": 0,
                    "text_block_count": 0,
                    "nil_fact_count": 0,
                    "contexts_count": 0,
                    "units_count": 0,
                    "concepts_count": 0,
                    "facts_by_namespace": {},
                    "facts_by_context": {},
                    "parse_warnings": [str(exc)],
                    "facts": [],
                    "sample_facts": [],
                }
            )

    output_json = args.output_json or REPORTS_DIR / f"reference_xbrl_report_{utc_timestamp()}.json"
    output_md = args.output_md or output_json.with_suffix(".md")
    report = build_report(case_reports, cases_dir=str(args.cases_dir), output_json=output_json)
    output_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")

    print(f"Reference report: {output_json}")
    print(f"Markdown summary: {output_md}")
    print(f"Cases parsed: {report['aggregate_metrics']['total_cases_parsed']}")
    print(f"Total facts: {report['aggregate_metrics']['total_facts']}")
    print(f"Numeric facts: {report['aggregate_metrics']['numeric_fact_count']}")
    print(f"Text blocks: {report['aggregate_metrics']['text_block_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
