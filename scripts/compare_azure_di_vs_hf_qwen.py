"""Compare Azure DI spike output against the HF Qwen benchmark and reference report."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.extraction_v2_quality_analyzer import detect_candidate_issues, normalize_terms  # noqa: E402


REPORTS_DIR = PROJECT_ROOT / "reports"
DEFAULT_AZURE = REPORTS_DIR / "azure_di_extraction_v2_report_13w_spike.json"
DEFAULT_HF = REPORTS_DIR / "extraction_v2_report_20260512T144014Z.json"
DEFAULT_REFERENCE = REPORTS_DIR / "reference_xbrl_report_20260511T082343Z.json"
DEFAULT_COMPARISON = REPORTS_DIR / "azure_di_vs_hf_qwen_comparison_13w_spike.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _row_counts(candidates: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(candidate.get("row_type") or "unknown") for candidate in candidates)


def _flatten(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in report.get("case_reports") or []:
        case_id = str(case.get("case_id") or "")
        for candidate in case.get("candidates") or []:
            enriched = dict(candidate)
            enriched.setdefault("case_id", case_id)
            rows.append(enriched)
    return rows


def _case_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(case.get("case_id") or ""): case for case in report.get("case_reports") or []}


def _case_candidates(report: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for case in report.get("case_reports") or []:
        case_id = str(case.get("case_id") or "")
        grouped[case_id] = [dict(candidate, case_id=case_id) for candidate in case.get("candidates") or []]
    return grouped


def _numeric_count(counts: Counter[str]) -> int:
    return counts.get("numeric_fact", 0) + counts.get("comparative_numeric_fact", 0) + counts.get("subtotal_or_total", 0)


def _issue_proxy_counts(candidates: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for candidate in candidates:
        for issue in detect_candidate_issues(candidate):
            counter[str(issue.get("code") or "unknown")] += 1
    return counter


def _reference_terms(reference_report: dict[str, Any], case_id: str) -> set[str]:
    terms: set[str] = set()
    for case in reference_report.get("case_reports") or []:
        if str(case.get("case_id") or "") != case_id:
            continue
        for fact in case.get("facts") or []:
            local = fact.get("local_name") or fact.get("qname") or fact.get("concept_name")
            terms.update(normalize_terms(local))
    return terms


def _candidate_terms(candidates: list[dict[str, Any]]) -> set[str]:
    terms: set[str] = set()
    for candidate in candidates:
        terms.update(normalize_terms(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet")))
    return terms


def _overlap_ratio(candidates: list[dict[str, Any]], reference_report: dict[str, Any], case_id: str) -> float:
    ref_terms = _reference_terms(reference_report, case_id)
    cand_terms = _candidate_terms(candidates)
    if not ref_terms:
        return 0.0
    return round(len(ref_terms & cand_terms) / len(ref_terms), 4)


def _table_counts(case: dict[str, Any]) -> int:
    return int(case.get("azure_di_tables_detected") or case.get("tables_detected") or 0)


def _recommendation(azure_summary: dict[str, Any], hf_summary: dict[str, Any], issue_counts: Counter[str]) -> str:
    azure_numeric = int(azure_summary.get("numeric_candidates") or 0)
    hf_numeric = int(hf_summary.get("numeric_candidates") or 0)
    azure_text = int(azure_summary.get("text_block_candidates") or 0)
    hf_text = int(hf_summary.get("text_block_candidates") or 0)
    missing_cases = len(azure_summary.get("missing_numeric_or_text_cases") or [])
    pollution = (
        issue_counts.get("year_header_row_extracted_as_fact", 0)
        + issue_counts.get("date_or_year_value_as_amount", 0)
        + issue_counts.get("heading_like_numeric_fact", 0)
    )
    if missing_cases:
        return "not recommended yet"
    if azure_numeric >= hf_numeric and azure_text >= hf_text and pollution <= max(10, azure_numeric * 0.1):
        return "primary extraction source"
    if azure_numeric >= hf_numeric * 0.6 and (azure_text or azure_summary.get("tables_detected", 0)):
        return "OCR/layout preprocessor before Qwen cleanup"
    if azure_numeric > 0 or azure_text > 0:
        return "fallback only"
    return "not recommended yet"


def compare_reports(
    *,
    azure_report: dict[str, Any],
    hf_report: dict[str, Any],
    reference_report: dict[str, Any],
    input_paths: dict[str, str] | None = None,
) -> dict[str, Any]:
    azure_candidates = _flatten(azure_report)
    hf_candidates = _flatten(hf_report)
    azure_counts = _row_counts(azure_candidates)
    hf_counts = _row_counts(hf_candidates)
    azure_cases = _case_map(azure_report)
    hf_cases = _case_map(hf_report)
    reference_cases = _case_map(reference_report)
    azure_by_case = _case_candidates(azure_report)
    hf_by_case = _case_candidates(hf_report)
    issue_counts = _issue_proxy_counts(azure_candidates)
    case_ids = sorted(set(reference_cases) | set(azure_cases) | set(hf_cases))

    per_case: list[dict[str, Any]] = []
    missing_numeric_or_text: list[str] = []
    missing_numeric: list[str] = []
    missing_text: list[str] = []
    for case_id in case_ids:
        azure_case_candidates = azure_by_case.get(case_id, [])
        hf_case_candidates = hf_by_case.get(case_id, [])
        az_counts = _row_counts(azure_case_candidates)
        hf_case_counts = _row_counts(hf_case_candidates)
        az_numeric = _numeric_count(az_counts)
        az_text = az_counts.get("text_block", 0)
        if not az_numeric:
            missing_numeric.append(case_id)
        if not az_text:
            missing_text.append(case_id)
        if not az_numeric and not az_text and reference_cases.get(case_id):
            missing_numeric_or_text.append(case_id)
        azure_case = azure_cases.get(case_id, {})
        hf_case = hf_cases.get(case_id, {})
        per_case.append(
            {
                "case_id": case_id,
                "azure_di_candidates": len(azure_case_candidates),
                "hf_qwen_candidates": len(hf_case_candidates),
                "azure_di_numeric_candidates": az_numeric,
                "hf_qwen_numeric_candidates": _numeric_count(hf_case_counts),
                "azure_di_comparative_numeric_candidates": az_counts.get("comparative_numeric_fact", 0),
                "hf_qwen_comparative_numeric_candidates": hf_case_counts.get("comparative_numeric_fact", 0),
                "azure_di_text_block_candidates": az_text,
                "hf_qwen_text_block_candidates": hf_case_counts.get("text_block", 0),
                "azure_di_heading_metadata_unknown": az_counts.get("heading", 0) + az_counts.get("metadata", 0) + az_counts.get("unknown", 0),
                "hf_qwen_heading_metadata_unknown": hf_case_counts.get("heading", 0) + hf_case_counts.get("metadata", 0) + hf_case_counts.get("unknown", 0),
                "azure_di_tables_detected": _table_counts(azure_case),
                "azure_di_runtime_seconds": azure_case.get("azure_di_runtime_seconds"),
                "azure_di_pages_processed": azure_case.get("pages_analyzed"),
                "reference_total_facts": reference_cases.get(case_id, {}).get("total_facts", 0),
                "reference_numeric_facts": reference_cases.get(case_id, {}).get("numeric_fact_count", 0),
                "reference_text_blocks": reference_cases.get(case_id, {}).get("text_block_count", 0),
                "rough_reference_term_overlap_ratio": _overlap_ratio(azure_case_candidates, reference_report, case_id),
                "missing_numeric_signal": not bool(az_numeric),
                "missing_text_block_signal": not bool(az_text),
            }
        )

    azure_summary = {
        "total_candidates": len(azure_candidates),
        "numeric_candidates": _numeric_count(azure_counts),
        "comparative_numeric_candidates": azure_counts.get("comparative_numeric_fact", 0),
        "subtotal_or_total_candidates": azure_counts.get("subtotal_or_total", 0),
        "text_block_candidates": azure_counts.get("text_block", 0),
        "heading_candidates": azure_counts.get("heading", 0),
        "metadata_candidates": azure_counts.get("metadata", 0),
        "unknown_candidates": azure_counts.get("unknown", 0),
        "row_type_counts": dict(sorted(azure_counts.items())),
        "tables_detected": (azure_report.get("aggregate_metrics") or {}).get("azure_di_tables_detected", 0),
        "pages_processed": (azure_report.get("aggregate_metrics") or {}).get("azure_di_pages_processed", 0),
        "total_runtime_seconds": (azure_report.get("aggregate_metrics") or {}).get("total_runtime_seconds"),
        "average_seconds_per_page": (azure_report.get("aggregate_metrics") or {}).get("average_seconds_per_page"),
        "estimated_billable_pages": (azure_report.get("aggregate_metrics") or {}).get("estimated_pages_billable"),
        "missing_numeric_cases": missing_numeric,
        "missing_text_block_cases": missing_text,
        "missing_numeric_or_text_cases": missing_numeric_or_text,
    }
    hf_summary = {
        "total_candidates": len(hf_candidates),
        "numeric_candidates": _numeric_count(hf_counts),
        "comparative_numeric_candidates": hf_counts.get("comparative_numeric_fact", 0),
        "subtotal_or_total_candidates": hf_counts.get("subtotal_or_total", 0),
        "text_block_candidates": hf_counts.get("text_block", 0),
        "heading_candidates": hf_counts.get("heading", 0),
        "metadata_candidates": hf_counts.get("metadata", 0),
        "unknown_candidates": hf_counts.get("unknown", 0),
        "row_type_counts": dict(sorted(hf_counts.items())),
    }
    recommendation = _recommendation(azure_summary, hf_summary, issue_counts)
    return {
        "run_metadata": {
            "generated_at": utc_now_iso(),
            "feature": "13W-AzureDI-spike",
            "script": "scripts/compare_azure_di_vs_hf_qwen.py",
            "report_type": "azure_di_vs_hf_qwen_comparison",
            "read_only": True,
            "database_mutated": False,
            "production_behavior_changed": False,
            "live_model_calls": False,
            "external_provider_calls": False,
            "live_huggingface_calls_made": False,
            "live_openai_calls_made": False,
            "reference_xml_sent_to_provider": False,
            "semantic_matcher_called": False,
            "xbrl_generated": False,
            "arelle_validation_run": False,
        },
        "input_reports": input_paths or {},
        "aggregate_comparison": {
            "azure_di": azure_summary,
            "hf_qwen": hf_summary,
            "reference": {
                "total_facts": (reference_report.get("aggregate_metrics") or {}).get("total_facts", 0),
                "numeric_facts": (reference_report.get("aggregate_metrics") or {}).get("numeric_fact_count", 0),
                "text_blocks": (reference_report.get("aggregate_metrics") or {}).get("text_block_count", 0),
            },
            "azure_di_issue_proxy_counts": dict(issue_counts.most_common()),
            "duplicate_conflict_risk_proxies": {
                "duplicate_label_conflicting_values": issue_counts.get("duplicate_label_conflicting_values", 0),
                "duplicate_label_value_same_case": issue_counts.get("duplicate_label_value_same_case", 0),
                "exact_duplicate_same_page": issue_counts.get("exact_duplicate_same_page", 0),
            },
            "date_year_header_pollution_proxies": {
                "year_header_row_extracted_as_fact": issue_counts.get("year_header_row_extracted_as_fact", 0),
                "date_or_year_value_as_amount": issue_counts.get("date_or_year_value_as_amount", 0),
                "date_only_label": issue_counts.get("date_only_label", 0),
                "year_only_label": issue_counts.get("year_only_label", 0),
            },
            "source_provenance_quality": {
                "azure_items_with_page_number": sum(1 for item in azure_candidates if item.get("page_number")),
                "azure_items_with_source_snippet": sum(1 for item in azure_candidates if item.get("source_snippet")),
                "azure_items_with_table_or_paragraph_provenance": sum(
                    1
                    for item in azure_candidates
                    if "table_index" in (item.get("provenance") or {})
                    or "paragraph_index" in (item.get("provenance") or {})
                ),
            },
            "recommended_role": recommendation,
        },
        "per_case": per_case,
        "recommendation": {
            "recommended_role": recommendation,
            "do_not_overclaim_accuracy": True,
            "rationale": _recommendation_rationale(recommendation),
            "potential_next_features": [
                "Feature #13X - Azure DI candidate quality/readiness pipeline through #13R/#13V gates.",
                "Feature #13X - Azure DI-first extraction pipeline integration plan.",
                "Feature #13X - Hybrid Azure DI + Qwen cleanup architecture.",
                "Feature #13X - Continue mapping candidate generation using the best extraction source.",
                "Feature #13X - Azure DI table/text-block normalization if Azure output has table/index pollution.",
            ],
        },
        "limitations": [
            "This comparison is heuristic and report-based; it does not prove final extraction accuracy.",
            "Reference XML is used only offline and is not sent to Azure DI, Hugging Face, or OpenAI.",
            "No taxonomy mapping, semantic matcher call, generated XBRL, Arelle validation, DB mutation, API, or UI work is performed.",
        ],
    }


def _recommendation_rationale(role: str) -> str:
    mapping = {
        "primary extraction source": "Azure DI produced broad numeric and narrative signal with acceptable pollution proxies in this report.",
        "OCR/layout preprocessor before Qwen cleanup": "Azure DI layout/table extraction appears useful, but cleanup or Qwen-style normalization is still needed before cutover.",
        "fallback only": "Azure DI produced some useful signal but does not yet beat the existing HF Qwen benchmark enough for primary use.",
        "not recommended yet": "Azure DI output is missing core numeric/text signal or has unresolved quality risks in this report.",
    }
    return mapping.get(role, "Recommendation is based on conservative heuristic report comparison.")


def render_markdown(report: dict[str, Any]) -> str:
    aggregate = report.get("aggregate_comparison") or {}
    azure = aggregate.get("azure_di") or {}
    hf = aggregate.get("hf_qwen") or {}
    lines = [
        "# Azure DI vs HF Qwen Comparison - Feature #13W",
        "",
        "## Summary",
        "",
        f"- Azure DI candidates: {azure.get('total_candidates', 0)}",
        f"- HF Qwen candidates: {hf.get('total_candidates', 0)}",
        f"- Azure DI numeric candidates: {azure.get('numeric_candidates', 0)}",
        f"- HF Qwen numeric candidates: {hf.get('numeric_candidates', 0)}",
        f"- Azure DI text blocks: {azure.get('text_block_candidates', 0)}",
        f"- HF Qwen text blocks: {hf.get('text_block_candidates', 0)}",
        f"- Azure DI tables detected: {azure.get('tables_detected', 0)}",
        f"- Azure DI average seconds/page: {azure.get('average_seconds_per_page')}",
        f"- Estimated billable pages: {azure.get('estimated_billable_pages')}",
        f"- Recommended role: {aggregate.get('recommended_role')}",
        f"- Database mutated: {report.get('run_metadata', {}).get('database_mutated')}",
        "",
        "## Per Case",
        "",
        "| Case | Azure Candidates | HF Candidates | Azure Numeric | HF Numeric | Azure Text | HF Text | Azure Tables | Ref Overlap |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report.get("per_case") or []:
        lines.append(
            "| {case_id} | {azure_di_candidates} | {hf_qwen_candidates} | {azure_di_numeric_candidates} | {hf_qwen_numeric_candidates} | {azure_di_text_block_candidates} | {hf_qwen_text_block_candidates} | {azure_di_tables_detected} | {rough_reference_term_overlap_ratio} |".format(
                **row
            )
        )
    lines.extend(["", "## Risk Proxies", ""])
    for key, value in (aggregate.get("date_year_header_pollution_proxies") or {}).items():
        lines.append(f"- {key}: {value}")
    for key, value in (aggregate.get("duplicate_conflict_risk_proxies") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Recommendation", "", f"- {report.get('recommendation', {}).get('recommended_role')}: {report.get('recommendation', {}).get('rationale')}", ""])
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations", []))
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Azure DI report against HF Qwen and reference reports.")
    parser.add_argument("--azure-di-report", type=Path, default=DEFAULT_AZURE)
    parser.add_argument("--hf-report", type=Path, default=DEFAULT_HF)
    parser.add_argument("--reference-report", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_COMPARISON)
    parser.add_argument("--output-md", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_md = args.output_md or args.output_json.with_suffix(".md")
    report = compare_reports(
        azure_report=load_json(args.azure_di_report),
        hf_report=load_json(args.hf_report),
        reference_report=load_json(args.reference_report),
        input_paths={
            "azure_di_report": str(args.azure_di_report),
            "hf_report": str(args.hf_report),
            "reference_report": str(args.reference_report),
        },
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(f"Azure DI vs HF Qwen comparison report: {args.output_json}")
    print(f"Azure DI vs HF Qwen markdown report: {output_md}")
    print(f"Recommended role: {report['recommendation']['recommended_role']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
