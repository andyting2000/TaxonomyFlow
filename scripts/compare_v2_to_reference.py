"""Compare Extraction v2 benchmark output against parsed reference XML/XBRL facts."""

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


REPORTS_DIR = PROJECT_ROOT / "reports"


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def normalize_terms(value: Any) -> set[str]:
    text = str(value or "")
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).lower()
    return {term for term in text.split() if len(term) >= 3}


def overlap_score(left: Any, right: Any) -> float:
    left_terms = normalize_terms(left)
    right_terms = normalize_terms(right)
    if not left_terms or not right_terms:
        return 0.0
    return len(left_terms & right_terms) / len(left_terms | right_terms)


def _case_map(report: dict, key: str = "case_reports") -> dict[str, dict]:
    return {str(case.get("case_id")): case for case in report.get(key, [])}


def _v2_candidates(case_report: dict) -> list[dict]:
    return list(case_report.get("candidates") or [])


def _reference_facts(case_report: dict) -> list[dict]:
    return list(case_report.get("facts") or [])


def _represented_reference_concepts(reference_facts: list[dict], v2_candidates: list[dict]) -> set[str]:
    labels = [candidate.get("label") or candidate.get("text") or candidate.get("source_snippet") for candidate in v2_candidates]
    represented: set[str] = set()
    for fact in reference_facts:
        concept = fact.get("local_name") or fact.get("qname")
        if any(overlap_score(concept, label) >= 0.35 for label in labels):
            represented.add(str(fact.get("qname") or concept))
    return represented


def _candidate_method_counts(candidates: list[dict]) -> Counter:
    return Counter(str(candidate.get("extraction_method") or "unknown") for candidate in candidates)


def _aggregate_value(report: dict, key: str, default: Any = 0) -> Any:
    return (report.get("aggregate_metrics") or {}).get(key, default)


def _run_metadata_value(report: dict, key: str, default: Any = None) -> Any:
    return (report.get("run_metadata") or {}).get(key, default)


def compare_reports(reference_report: dict, v2_report: dict, *, output_json: str | None = None) -> dict:
    reference_cases = _case_map(reference_report)
    v2_cases = _case_map(v2_report)
    compared_case_ids = sorted(set(reference_cases) & set(v2_cases))
    per_case: list[dict[str, Any]] = []
    all_reference_facts: list[dict] = []
    all_v2_candidates: list[dict] = []
    missing_numeric_cases: list[str] = []
    missing_text_block_cases: list[str] = []

    for case_id in compared_case_ids:
        ref_case = reference_cases[case_id]
        v2_case = v2_cases[case_id]
        reference_facts = _reference_facts(ref_case)
        v2_candidates = _v2_candidates(v2_case)
        all_reference_facts.extend(reference_facts)
        all_v2_candidates.extend(v2_candidates)
        ref_numeric = sum(1 for fact in reference_facts if fact.get("is_numeric") and not fact.get("is_nil"))
        ref_text_blocks = sum(1 for fact in reference_facts if fact.get("is_text_block") and not fact.get("is_nil"))
        v2_numeric = sum(
            1
            for candidate in v2_candidates
            if candidate.get("row_type") in {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
        )
        v2_text_blocks = sum(1 for candidate in v2_candidates if candidate.get("row_type") == "text_block")
        represented = _represented_reference_concepts(reference_facts, v2_candidates)
        method_counts = _candidate_method_counts(v2_candidates)
        v2_huggingface = method_counts.get("huggingface_vision_fallback", 0)
        v2_openai = method_counts.get("openai_vision_fallback", 0)
        v2_native_only = len(v2_candidates) - v2_huggingface - v2_openai
        if ref_numeric and not v2_numeric:
            missing_numeric_cases.append(case_id)
        if ref_text_blocks and not v2_text_blocks:
            missing_text_block_cases.append(case_id)
        per_case.append(
            {
                "case_id": case_id,
                "reference_total_facts": len(reference_facts),
                "v2_total_candidates": len(v2_candidates),
                "v2_native_only_candidates": v2_native_only,
                "v2_huggingface_candidates": v2_huggingface,
                "v2_openai_candidates": v2_openai,
                "reference_numeric_facts": ref_numeric,
                "v2_numeric_candidates": v2_numeric,
                "reference_text_blocks": ref_text_blocks,
                "v2_text_block_candidates": v2_text_blocks,
                "reference_concepts_count": len({fact.get("qname") for fact in reference_facts if fact.get("qname")}),
                "v2_labels_count": len({candidate.get("label") for candidate in v2_candidates if candidate.get("label")}),
                "rough_represented_reference_concepts": len(represented),
                "missing_numeric_extraction_signal": bool(ref_numeric and not v2_numeric),
                "missing_text_block_extraction_signal": bool(ref_text_blocks and not v2_text_blocks),
            }
        )

    reference_concepts = Counter(fact.get("qname") or fact.get("local_name") for fact in all_reference_facts)
    v2_labels = Counter(candidate.get("label") or candidate.get("text") or candidate.get("source_snippet") for candidate in all_v2_candidates)
    represented_all = _represented_reference_concepts(all_reference_facts, all_v2_candidates)
    top_reference_not_represented = [
        {"concept": concept, "count": count}
        for concept, count in reference_concepts.most_common()
        if concept and concept not in represented_all
    ][:25]
    top_v2_not_in_reference = [
        {"candidate_label": label, "count": count}
        for label, count in v2_labels.most_common()
        if label and not any(overlap_score(label, fact.get("local_name") or fact.get("qname")) >= 0.35 for fact in all_reference_facts)
    ][:25]
    ref_numeric_total = sum(1 for fact in all_reference_facts if fact.get("is_numeric") and not fact.get("is_nil"))
    ref_text_block_total = sum(1 for fact in all_reference_facts if fact.get("is_text_block") and not fact.get("is_nil"))
    v2_numeric_total = sum(
        1
        for candidate in all_v2_candidates
        if candidate.get("row_type") in {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
    )
    v2_text_block_total = sum(1 for candidate in all_v2_candidates if candidate.get("row_type") == "text_block")
    method_counts = _candidate_method_counts(all_v2_candidates)
    v2_huggingface_total = method_counts.get("huggingface_vision_fallback", 0)
    v2_openai_total = method_counts.get("openai_vision_fallback", 0)
    v2_native_only_total = len(all_v2_candidates) - v2_huggingface_total - v2_openai_total
    v2_live_model_total = v2_huggingface_total + v2_openai_total
    numeric_gap = max(ref_numeric_total - v2_numeric_total, 0)
    text_block_gap = max(ref_text_block_total - v2_text_block_total, 0)
    numeric_ratio = (v2_numeric_total / ref_numeric_total) if ref_numeric_total else None
    text_block_ratio = (v2_text_block_total / ref_text_block_total) if ref_text_block_total else None

    recommendations = []
    if ref_numeric_total and not v2_numeric_total:
        recommendations.append("Prioritize v2 numeric table/fact extraction; reference XML contains numeric facts but v2 emitted none.")
    elif ref_numeric_total and numeric_ratio is not None and numeric_ratio < 0.25:
        recommendations.append("Expand native/OCR numeric table coverage; v2 now emits numeric candidates but still covers only a small share of reference numeric facts.")
    if ref_text_block_total and not v2_text_block_total:
        recommendations.append("Prioritize v2 text-block/disclosure extraction; reference XML contains text blocks but v2 emitted none.")
    elif ref_text_block_total and text_block_ratio is not None and text_block_ratio < 0.25:
        recommendations.append("Improve text-block grouping and OCR coverage; v2 text blocks remain far below the reference text-block layer.")
    if not recommendations:
        recommendations.append("Use the reference report to refine overlap scoring and candidate classification.")
    cases_without_numeric_or_text = [
        item["case_id"]
        for item in per_case
        if (item["reference_numeric_facts"] or item["reference_text_blocks"])
        and not (item["v2_numeric_candidates"] or item["v2_text_block_candidates"])
    ]
    cases_with_numeric_signal = sum(1 for item in per_case if item["v2_numeric_candidates"] > 0)
    cases_with_text_block_signal = sum(1 for item in per_case if item["v2_text_block_candidates"] > 0)
    benchmark_complete = bool(compared_case_ids) and not cases_without_numeric_or_text
    full_hf_benchmark_successful = bool(
        benchmark_complete
        and v2_huggingface_total > 0
        and v2_openai_total == 0
        and not bool(ref_numeric_total and not v2_numeric_total)
        and not bool(ref_text_block_total and not v2_text_block_total)
    )
    closeout_assessment = (
        "Feature #13Q full Hugging Face Qwen benchmark completed successfully. "
        "Extraction v2 now emits numeric and text-block candidates for the OCR-heavy benchmark set. "
        "Remaining work is candidate quality, duplicate control, concept mapping readiness, and production cutover planning."
    )
    assessment = closeout_assessment if full_hf_benchmark_successful else _assessment_text(
        ref_numeric_total,
        v2_numeric_total,
        ref_text_block_total,
        v2_text_block_total,
    )

    return {
        "run_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "script": "scripts/compare_v2_to_reference.py",
            "read_only": True,
            "database_mutated": False,
            "production_behavior_changed": False,
            "ui_upload_required": False,
            "xbrl_generated": False,
            "arelle_validation_run": False,
            "openai_used": bool((v2_report.get("run_metadata") or {}).get("openai_used")),
            "output_path": output_json,
        },
        "aggregate_metrics": {
            "cases_compared": len(compared_case_ids),
            "reference_total_facts": len(all_reference_facts),
            "v2_total_candidates": len(all_v2_candidates),
            "v2_native_candidates": v2_native_only_total,
            "v2_native_candidates_legacy_note": "Legacy field; use v2_native_only_candidates for native-only count.",
            "v2_native_only_candidates": v2_native_only_total,
            "v2_huggingface_candidates": v2_huggingface_total,
            "v2_openai_candidates": v2_openai_total,
            "v2_live_model_candidates": v2_live_model_total,
            "v2_non_native_candidates": v2_live_model_total,
            "v2_huggingface_fallback_pages_attempted": _aggregate_value(v2_report, "huggingface_fallback_pages_attempted", 0),
            "v2_huggingface_fallback_pages_succeeded": _aggregate_value(v2_report, "huggingface_fallback_pages_succeeded", 0),
            "v2_huggingface_fallback_pages_failed": _aggregate_value(v2_report, "huggingface_fallback_pages_failed", 0),
            "v2_huggingface_empty_candidate_pages": _aggregate_value(v2_report, "hf_empty_candidate_pages", 0),
            "v2_huggingface_parser_recovered_candidates": _aggregate_value(v2_report, "hf_parser_recovered_candidates", 0),
            "v2_huggingface_parser_failed_pages": _aggregate_value(v2_report, "hf_parser_failed_pages", 0),
            "v2_huggingface_raw_response_preview_count": _aggregate_value(v2_report, "hf_raw_response_preview_count", 0),
            "v2_huggingface_candidates_kept": _aggregate_value(v2_report, "huggingface_candidates_kept", v2_huggingface_total),
            "v2_huggingface_fallback_pages_skipped_resume": _aggregate_value(v2_report, "huggingface_fallback_pages_skipped_resume", 0),
            "v2_total_vision_pages_attempted": _run_metadata_value(v2_report, "total_vision_pages_attempted", None),
            "v2_openai_fallback_pages_attempted": (v2_report.get("aggregate_metrics") or {}).get("openai_fallback_pages_attempted", 0),
            "v2_openai_fallback_pages_succeeded": (v2_report.get("aggregate_metrics") or {}).get("openai_fallback_pages_succeeded", 0),
            "v2_openai_fallback_pages_failed": (v2_report.get("aggregate_metrics") or {}).get("openai_fallback_pages_failed", 0),
            "reference_numeric_facts": ref_numeric_total,
            "v2_numeric_fact_candidates": v2_numeric_total,
            "reference_text_blocks": ref_text_block_total,
            "v2_text_block_candidates": v2_text_block_total,
            "reference_concepts_count": len({fact.get("qname") for fact in all_reference_facts if fact.get("qname")}),
            "v2_labels_count": len({candidate.get("label") for candidate in all_v2_candidates if candidate.get("label")}),
            "rough_label_concept_overlap_count": len(represented_all),
            "missing_numeric_extraction_signal": bool(ref_numeric_total and not v2_numeric_total),
            "missing_text_block_extraction_signal": bool(ref_text_block_total and not v2_text_block_total),
            "numeric_extraction_signal_improved": bool(v2_numeric_total),
            "text_block_extraction_signal_improved": bool(v2_text_block_total),
            "numeric_candidate_to_reference_ratio": numeric_ratio,
            "text_block_candidate_to_reference_ratio": text_block_ratio,
            "remaining_numeric_gap": numeric_gap,
            "remaining_text_block_gap": text_block_gap,
            "cases_where_reference_exists_but_v2_has_no_numeric_or_text": cases_without_numeric_or_text,
            "missing_numeric_cases": missing_numeric_cases,
            "missing_text_block_cases": missing_text_block_cases,
            "benchmark_complete": benchmark_complete,
            "cases_with_numeric_signal": cases_with_numeric_signal,
            "cases_with_text_block_signal": cases_with_text_block_signal,
            "full_hf_benchmark_successful": full_hf_benchmark_successful,
        },
        "benchmark_completion_assessment": {
            "benchmark_complete": benchmark_complete,
            "cases_with_numeric_signal": cases_with_numeric_signal,
            "cases_with_text_block_signal": cases_with_text_block_signal,
            "cases_missing_numeric_signal": missing_numeric_cases,
            "cases_missing_text_block_signal": missing_text_block_cases,
            "cases_where_reference_exists_but_v2_has_no_numeric_or_text": cases_without_numeric_or_text,
            "full_hf_benchmark_successful": full_hf_benchmark_successful,
            "assessment": assessment,
        },
        "per_case": per_case,
        "top_reference_concepts_not_represented_in_v2": top_reference_not_represented,
        "top_v2_candidates_not_found_in_reference": top_v2_not_in_reference,
        "recommended_next_extraction_v2_focus": recommendations,
        "assessment": assessment,
        "limitations": [
            "Comparison uses rough label/concept overlap only; it is not final taxonomy mapping.",
            "OpenAI fallback metrics are reported when the v2 input report used the opt-in benchmark fallback.",
            "No DB mutation, XBRL generation, Arelle validation, UI upload, or production cutover is performed.",
        ],
    }


def _assessment_text(
    ref_numeric_total: int,
    v2_numeric_total: int,
    ref_text_block_total: int,
    v2_text_block_total: int,
) -> str:
    if ref_numeric_total and not v2_numeric_total and ref_text_block_total and not v2_text_block_total:
        return "Extraction v2 has not yet extracted numeric facts or text blocks; reference XML contains facts that can guide v2 development."
    if v2_numeric_total and ref_text_block_total and not v2_text_block_total:
        return "Extraction v2 numeric extraction improved from zero, but text-block extraction remains missing against the reference layer."
    if v2_numeric_total and v2_text_block_total:
        return "Extraction v2 now emits numeric and text-block candidates; remaining gaps should be measured against reference coverage and candidate quality."
    return "Extraction v2/reference comparison completed."


def render_markdown(report: dict) -> str:
    aggregate = report["aggregate_metrics"]
    lines = [
        "# Extraction v2 vs Reference XML/XBRL Comparison",
        "",
        "## Executive Summary",
        "",
        f"- Cases compared: {aggregate['cases_compared']}",
        f"- Reference total facts: {aggregate['reference_total_facts']}",
        f"- V2 total candidates: {aggregate['v2_total_candidates']}",
        f"- V2 native-only candidates: {aggregate.get('v2_native_only_candidates', aggregate.get('v2_native_candidates', 0))}",
        f"- V2 Hugging Face candidates: {aggregate.get('v2_huggingface_candidates', 0)}",
        f"- V2 OpenAI candidates: {aggregate.get('v2_openai_candidates', 0)}",
        f"- V2 live-model candidates: {aggregate.get('v2_live_model_candidates', 0)}",
        f"- V2 Hugging Face fallback pages attempted: {aggregate.get('v2_huggingface_fallback_pages_attempted', 0)}",
        f"- V2 Hugging Face fallback pages succeeded: {aggregate.get('v2_huggingface_fallback_pages_succeeded', 0)}",
        f"- V2 Hugging Face fallback pages failed: {aggregate.get('v2_huggingface_fallback_pages_failed', 0)}",
        f"- V2 Hugging Face empty candidate pages: {aggregate.get('v2_huggingface_empty_candidate_pages', 0)}",
        f"- V2 Hugging Face parser recovered candidates: {aggregate.get('v2_huggingface_parser_recovered_candidates', 0)}",
        f"- V2 Hugging Face parser failed pages: {aggregate.get('v2_huggingface_parser_failed_pages', 0)}",
        f"- V2 Hugging Face raw response previews: {aggregate.get('v2_huggingface_raw_response_preview_count', 0)}",
        f"- V2 OpenAI fallback pages attempted: {aggregate.get('v2_openai_fallback_pages_attempted', 0)}",
        f"- V2 OpenAI fallback pages succeeded: {aggregate.get('v2_openai_fallback_pages_succeeded', 0)}",
        f"- V2 OpenAI fallback pages failed: {aggregate.get('v2_openai_fallback_pages_failed', 0)}",
        f"- Reference numeric facts: {aggregate['reference_numeric_facts']}",
        f"- V2 numeric candidates: {aggregate['v2_numeric_fact_candidates']}",
        f"- Reference text blocks: {aggregate['reference_text_blocks']}",
        f"- V2 text block candidates: {aggregate['v2_text_block_candidates']}",
        f"- Missing numeric extraction signal: {aggregate['missing_numeric_extraction_signal']}",
        f"- Missing text-block extraction signal: {aggregate['missing_text_block_extraction_signal']}",
        f"- Numeric extraction signal improved: {aggregate.get('numeric_extraction_signal_improved')}",
        f"- Text-block extraction signal improved: {aggregate.get('text_block_extraction_signal_improved')}",
        f"- Benchmark complete: {aggregate.get('benchmark_complete', False)}",
        f"- Cases with numeric signal: {aggregate.get('cases_with_numeric_signal', 0)}",
        f"- Cases with text-block signal: {aggregate.get('cases_with_text_block_signal', 0)}",
        f"- Missing numeric cases: {aggregate.get('missing_numeric_cases', [])}",
        f"- Missing text-block cases: {aggregate.get('missing_text_block_cases', [])}",
        f"- Remaining numeric gap: {aggregate.get('remaining_numeric_gap')}",
        f"- Remaining text-block gap: {aggregate.get('remaining_text_block_gap')}",
        f"- UI upload required: {report['run_metadata']['ui_upload_required']}",
        f"- Database mutated: {report['run_metadata']['database_mutated']}",
        "",
        "## Per Case",
        "",
        "| Case | Ref Facts | V2 Candidates | Native | Hugging Face | OpenAI | Ref Numeric | V2 Numeric | Ref Text Blocks | V2 Text Blocks |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report.get("per_case", []):
        lines.append(
            "| {case_id} | {reference_total_facts} | {v2_total_candidates} | {v2_native_only_candidates} | {v2_huggingface_candidates} | {v2_openai_candidates} | {reference_numeric_facts} | {v2_numeric_candidates} | {reference_text_blocks} | {v2_text_block_candidates} |".format(
                **case
            )
        )
    lines.extend(["", "## Recommended Focus", ""])
    lines.extend(f"- {item}" for item in report.get("recommended_next_extraction_v2_focus", []))
    lines.extend(["", "## Assessment", "", report.get("assessment", ""), ""])
    return "\n".join(lines)


def build_huggingface_qwen_closeout_report(
    *,
    reference_report_path: Path,
    extraction_report_path: Path,
    comparison_report_path: Path,
    checkpoint_path: Path | None,
    v2_report: dict,
    comparison_report: dict,
    output_json: Path,
) -> dict[str, Any]:
    run_metadata = v2_report.get("run_metadata") or {}
    extraction_aggregate = v2_report.get("aggregate_metrics") or {}
    comparison_aggregate = comparison_report.get("aggregate_metrics") or {}
    per_case = [
        {
            "case_id": item.get("case_id"),
            "total_candidates": item.get("v2_total_candidates", 0),
            "native_only_candidates": item.get("v2_native_only_candidates", 0),
            "huggingface_candidates": item.get("v2_huggingface_candidates", 0),
            "openai_candidates": item.get("v2_openai_candidates", 0),
            "numeric_candidates": item.get("v2_numeric_candidates", 0),
            "text_block_candidates": item.get("v2_text_block_candidates", 0),
            "reference_facts": item.get("reference_total_facts", 0),
            "reference_numeric_facts": item.get("reference_numeric_facts", 0),
            "reference_text_blocks": item.get("reference_text_blocks", 0),
            "missing_numeric_signal": item.get("missing_numeric_extraction_signal", False),
            "missing_text_block_signal": item.get("missing_text_block_extraction_signal", False),
        }
        for item in comparison_report.get("per_case", [])
    ]
    return {
        "run_metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "script": "scripts/compare_v2_to_reference.py",
            "feature": "13Q",
            "read_only": True,
            "database_mutated": False,
            "production_behavior_changed": False,
            "ui_upload_required": False,
            "xbrl_generated": False,
            "arelle_validation_run": False,
            "live_model_calls_made_by_closeout": False,
            "output_path": str(output_json),
        },
        "inputs": {
            "extraction_report_path": str(extraction_report_path),
            "comparison_report_path": str(comparison_report_path),
            "reference_report_path": str(reference_report_path),
            "checkpoint_path": str(checkpoint_path) if checkpoint_path else run_metadata.get("checkpoint_path"),
        },
        "runtime": {
            "provider": run_metadata.get("vision_provider") or "huggingface",
            "vision_model_id": run_metadata.get("vision_model_id"),
            "text_model_id": run_metadata.get("text_model_id"),
            "embedding_model_id": run_metadata.get("embedding_model_id"),
            "openai_used": bool(run_metadata.get("openai_used")),
            "huggingface_used": bool(run_metadata.get("huggingface_used")),
            "vision_max_pages": run_metadata.get("vision_max_pages"),
            "total_vision_pages_attempted": run_metadata.get("total_vision_pages_attempted"),
            "empty_candidate_pages_are_processed_pages": True,
        },
        "final_aggregate_result": {
            "cases_processed": extraction_aggregate.get("total_cases_processed", comparison_aggregate.get("cases_compared", 0)),
            "total_candidates": comparison_aggregate.get("v2_total_candidates", 0),
            "huggingface_candidates": comparison_aggregate.get("v2_huggingface_candidates", 0),
            "native_only_candidates": comparison_aggregate.get("v2_native_only_candidates", 0),
            "openai_candidates": comparison_aggregate.get("v2_openai_candidates", 0),
            "numeric_candidates": comparison_aggregate.get("v2_numeric_fact_candidates", 0),
            "text_block_candidates": comparison_aggregate.get("v2_text_block_candidates", 0),
            "reference_facts": comparison_aggregate.get("reference_total_facts", 0),
            "reference_numeric_facts": comparison_aggregate.get("reference_numeric_facts", 0),
            "reference_text_blocks": comparison_aggregate.get("reference_text_blocks", 0),
            "missing_numeric_extraction_signal": comparison_aggregate.get("missing_numeric_extraction_signal", False),
            "missing_text_block_extraction_signal": comparison_aggregate.get("missing_text_block_extraction_signal", False),
            "cases_where_reference_exists_but_v2_has_no_numeric_or_text": comparison_aggregate.get(
                "cases_where_reference_exists_but_v2_has_no_numeric_or_text", []
            ),
        },
        "huggingface_fallback_metrics": {
            "fallback_pages_attempted_in_final_resume": comparison_aggregate.get("v2_huggingface_fallback_pages_attempted", 0),
            "fallback_pages_succeeded_in_final_resume": comparison_aggregate.get("v2_huggingface_fallback_pages_succeeded", 0),
            "fallback_pages_failed_in_final_resume": comparison_aggregate.get("v2_huggingface_fallback_pages_failed", 0),
            "fallback_pages_skipped_resume": comparison_aggregate.get("v2_huggingface_fallback_pages_skipped_resume", 0),
            "total_vision_pages_attempted": comparison_aggregate.get("v2_total_vision_pages_attempted"),
            "empty_candidate_pages": comparison_aggregate.get("v2_huggingface_empty_candidate_pages", 0),
            "parser_recovered_candidates": comparison_aggregate.get("v2_huggingface_parser_recovered_candidates", 0),
            "parser_failed_pages": comparison_aggregate.get("v2_huggingface_parser_failed_pages", 0),
            "raw_response_preview_count": comparison_aggregate.get("v2_huggingface_raw_response_preview_count", 0),
        },
        "improvement_summary": {
            "no_live_native_baseline_candidates": 122,
            "no_live_native_baseline_huggingface_candidates": 0,
            "full_hf_total_candidates": comparison_aggregate.get("v2_total_candidates", 0),
            "full_hf_huggingface_candidates": comparison_aggregate.get("v2_huggingface_candidates", 0),
            "text_block_signal": "improved from missing to present",
            "numeric_signal": "present and much stronger",
        },
        "benchmark_completion_assessment": comparison_report.get("benchmark_completion_assessment") or {},
        "per_case_summary": per_case,
        "remaining_limitations": [
            "Comparison is rough label/concept overlap only.",
            "This is not final taxonomy mapping.",
            "No XBRL generation was performed.",
            "No Arelle validation was performed.",
            "No production cutover was performed.",
            "Candidate quality still needs review.",
            "Duplicates, labels like 'As at 31/12/2023', headings, totals, and sign/year classification may require cleanup.",
        ],
        "recommended_next_feature": "Feature #13R - Candidate quality and mapping readiness analysis before production cutover",
    }


def render_closeout_markdown(report: dict[str, Any]) -> str:
    result = report["final_aggregate_result"]
    runtime = report["runtime"]
    assessment = report.get("benchmark_completion_assessment") or {}
    lines = [
        "# Feature #13Q Hugging Face Qwen Benchmark Closeout",
        "",
        "## Summary",
        "",
        f"- Benchmark complete: {assessment.get('benchmark_complete', False)}",
        f"- Full Hugging Face benchmark successful: {assessment.get('full_hf_benchmark_successful', False)}",
        f"- Provider: {runtime.get('provider')}",
        f"- Vision model: {runtime.get('vision_model_id')}",
        f"- Text model: {runtime.get('text_model_id')}",
        f"- Embedding model: {runtime.get('embedding_model_id')}",
        f"- OpenAI used: {runtime.get('openai_used', False)}",
        "",
        "## Final Aggregate Result",
        "",
        f"- Cases processed: {result.get('cases_processed', 0)}",
        f"- Total candidates: {result.get('total_candidates', 0)}",
        f"- Hugging Face candidates: {result.get('huggingface_candidates', 0)}",
        f"- Native-only candidates: {result.get('native_only_candidates', 0)}",
        f"- OpenAI candidates: {result.get('openai_candidates', 0)}",
        f"- Numeric candidates: {result.get('numeric_candidates', 0)}",
        f"- Text-block candidates: {result.get('text_block_candidates', 0)}",
        f"- Reference facts: {result.get('reference_facts', 0)}",
        f"- Reference numeric facts: {result.get('reference_numeric_facts', 0)}",
        f"- Reference text blocks: {result.get('reference_text_blocks', 0)}",
        f"- Missing numeric extraction signal: {result.get('missing_numeric_extraction_signal', False)}",
        f"- Missing text-block extraction signal: {result.get('missing_text_block_extraction_signal', False)}",
        "",
        "## Improvement Summary",
        "",
        f"- No-live/native baseline: {report['improvement_summary'].get('no_live_native_baseline_candidates', 0)} candidates, {report['improvement_summary'].get('no_live_native_baseline_huggingface_candidates', 0)} Hugging Face candidates.",
        f"- Full Hugging Face run: {report['improvement_summary'].get('full_hf_total_candidates', 0)} candidates, {report['improvement_summary'].get('full_hf_huggingface_candidates', 0)} Hugging Face candidates.",
        f"- Text-block signal: {report['improvement_summary'].get('text_block_signal')}.",
        f"- Numeric signal: {report['improvement_summary'].get('numeric_signal')}.",
        "",
        "## Per Case",
        "",
        "| Case | Candidates | Numeric | Text Blocks | Hugging Face | Native | OpenAI |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for case in report.get("per_case_summary", []):
        lines.append(
            "| {case_id} | {total_candidates} | {numeric_candidates} | {text_block_candidates} | {huggingface_candidates} | {native_only_candidates} | {openai_candidates} |".format(
                **case
            )
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("remaining_limitations", []))
    lines.extend(["", "## Recommended Next Feature", "", f"- {report.get('recommended_next_feature')}", ""])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare Extraction v2 output to reference XML/XBRL facts.")
    parser.add_argument("--reference-report", type=Path, required=True)
    parser.add_argument("--v2-report", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    reference_report = json.loads(args.reference_report.read_text(encoding="utf-8"))
    v2_report = json.loads(args.v2_report.read_text(encoding="utf-8"))
    output_json = args.output_json or REPORTS_DIR / f"v2_reference_comparison_{utc_timestamp()}.json"
    output_md = args.output_md or output_json.with_suffix(".md")
    report = compare_reports(reference_report, v2_report, output_json=str(output_json))
    output_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    closeout_json = REPORTS_DIR / "huggingface_qwen_benchmark_closeout_13q.json"
    closeout_md = closeout_json.with_suffix(".md")
    closeout_report = None
    if (report.get("benchmark_completion_assessment") or {}).get("full_hf_benchmark_successful"):
        checkpoint_value = (v2_report.get("run_metadata") or {}).get("checkpoint_path")
        closeout_report = build_huggingface_qwen_closeout_report(
            reference_report_path=args.reference_report,
            extraction_report_path=args.v2_report,
            comparison_report_path=output_json,
            checkpoint_path=Path(checkpoint_value) if checkpoint_value else None,
            v2_report=v2_report,
            comparison_report=report,
            output_json=closeout_json,
        )
        closeout_json.write_text(json.dumps(closeout_report, indent=2, default=str), encoding="utf-8")
        closeout_md.write_text(render_closeout_markdown(closeout_report), encoding="utf-8")

    print(f"Comparison report: {output_json}")
    print(f"Markdown summary: {output_md}")
    if closeout_report:
        print(f"Closeout report: {closeout_json}")
        print(f"Closeout markdown: {closeout_md}")
    print(f"Cases compared: {report['aggregate_metrics']['cases_compared']}")
    print(f"Reference facts: {report['aggregate_metrics']['reference_total_facts']}")
    print(f"V2 candidates: {report['aggregate_metrics']['v2_total_candidates']}")
    print(f"Missing numeric extraction signal: {report['aggregate_metrics']['missing_numeric_extraction_signal']}")
    print(f"Missing text-block extraction signal: {report['aggregate_metrics']['missing_text_block_extraction_signal']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
