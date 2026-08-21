"""Run Feature #18E-B-2 dictionary and row-order optimized offline mapper reports."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.pdf_note_link_extraction import build_note_link_report, note_link_index
from services.pdf_row_context_extraction import build_row_context_report
from services.pdf_statement_row_order_alignment import (
    build_statement_row_order_alignment_report,
    render_statement_row_order_alignment_markdown,
    row_order_alignment_index,
)
from services.pdf_statement_template_patterns import build_statement_template_report
from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label
from services.pdf_xbrl_rulebook_mapper import (
    SAFETY,
    apply_dictionary_row_order_mapping,
    load_hardened_mapper_rules,
    load_pdf_row_observations,
    summarize_mapper_records,
)
from services.pdf_xbrl_rulebook_replay import (
    FALSE_POSITIVE_STATUSES,
    GOOD_STATUSES,
    NOT_EVALUABLE_STATUSES,
    evaluate_prediction,
    load_sample_replay_data,
)
from services.statement_concept_candidate_dictionary import (
    build_statement_concept_candidate_dictionary_report,
    render_statement_concept_candidate_dictionary_markdown,
    statement_concept_candidate_entries,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _row_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record.get("sample_id") or ""), str(record.get("pdf_row_id") or record.get("row_id") or "")


def _context_key(context: Mapping[str, Any]) -> tuple[str, str]:
    return str(context.get("sample_id") or ""), str(context.get("row_id") or "")


def _record_context(record: Mapping[str, Any], context_by_row: Mapping[tuple[str, str], Mapping[str, Any]]) -> dict[str, Any]:
    context = dict(record.get("row_context") or {})
    context.update(context_by_row.get(_row_key(record)) or {})
    context.setdefault("sample_id", record.get("sample_id"))
    context.setdefault("row_id", record.get("pdf_row_id"))
    context.setdefault("original_label", record.get("pdf_label"))
    context.setdefault("normalized_label", record.get("normalized_label") or canonical_label(record.get("pdf_label")))
    context.setdefault("statement_family", record.get("pdf_statement_family"))
    context.setdefault("statement_title", record.get("pdf_statement_type"))
    context.setdefault("section_block", (record.get("row_context") or {}).get("section_block"))
    context.setdefault("row_role", (record.get("row_context") or {}).get("row_role"))
    return context


def _evaluate_records(
    records: Sequence[Mapping[str, Any]],
    *,
    row_values: Sequence[PdfRowValue],
    facts_by_sample: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    row_by_id = {(row.sample_id, row.pdf_row_id): row for row in row_values}
    evaluated = []
    for record in records:
        row = row_by_id.get(_row_key(record))
        if row is None:
            item = dict(record)
            item.update({"evaluation_status": "not_evaluable", "xbrl_support_status": "row_value_not_found"})
            evaluated.append(item)
            continue
        evaluated.append(evaluate_prediction(record, row, facts_by_sample.get(row.sample_id) or []))
    return evaluated


def _eval_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    predictions = [item for item in records if item.get("predicted_qname")]
    advisory = [item for item in records if item.get("confidence_bucket") in {"advisory_high", "advisory_medium"}]
    review = [item for item in records if item.get("confidence_bucket") == "review_required" and item.get("predicted_qname")]
    good = sum(1 for item in predictions if item.get("evaluation_status") in GOOD_STATUSES)
    false = sum(1 for item in predictions if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES)
    not_evaluable = sum(1 for item in predictions if item.get("evaluation_status") in NOT_EVALUABLE_STATUSES)
    advisory_good = sum(1 for item in advisory if item.get("evaluation_status") in GOOD_STATUSES)
    advisory_false = sum(1 for item in advisory if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES)
    review_good = sum(1 for item in review if item.get("evaluation_status") in GOOD_STATUSES)
    review_false = sum(1 for item in review if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES)
    status_counts = Counter(str(item.get("evaluation_status") or "unknown") for item in records)
    return {
        "predictions": len(predictions),
        "coverage_rate": _safe_rate(len(predictions), len(records)),
        "qname_value_matches": good,
        "false_positive_count": false,
        "not_evaluable_count": not_evaluable,
        "precision_on_evaluable": _safe_rate(good, good + false),
        "advisory_predictions": len(advisory),
        "advisory_qname_value_matches": advisory_good,
        "advisory_false_positive_count": advisory_false,
        "advisory_precision_on_evaluable": _safe_rate(advisory_good, advisory_good + advisory_false),
        "review_required_predictions": len(review),
        "review_required_qname_value_matches": review_good,
        "review_required_false_positive_count": review_false,
        "review_required_precision_on_evaluable": _safe_rate(review_good, review_good + review_false),
        "evaluation_status_counts": dict(sorted(status_counts.items())),
    }


def _touched_summary(summary: Mapping[str, Any]) -> int:
    return (
        int(summary.get("advisory_suggestions_count") or 0)
        + int(summary.get("review_required_suggestions_count") or 0)
        + int(summary.get("conflicts_count") or 0)
    )


def _top_labels(records: Sequence[Mapping[str, Any]], *, limit: int = 40) -> list[dict[str, Any]]:
    counter = Counter(str(item.get("normalized_label") or canonical_label(item.get("pdf_label"))) for item in records)
    return [{"normalized_label": label, "count": count} for label, count in counter.most_common(limit) if label]


def _top_records(records: Sequence[Mapping[str, Any]], *, limit: int = 100) -> list[dict[str, Any]]:
    rows = sorted(records, key=lambda item: (str(item.get("sample_id")), str(item.get("pdf_row_id"))))
    return [
        {
            "sample_id": item.get("sample_id"),
            "pdf_row_id": item.get("pdf_row_id"),
            "pdf_label": item.get("pdf_label"),
            "pdf_value": item.get("pdf_value"),
            "predicted_qname": item.get("predicted_qname"),
            "confidence_bucket": item.get("confidence_bucket"),
            "candidate_generation_method": item.get("candidate_generation_method"),
            "dictionary_entry_id": item.get("dictionary_entry_id"),
            "row_order_alignment_id": item.get("row_order_alignment_id"),
            "blocking_reasons": item.get("blocking_reasons") or [],
            "ambiguity_reasons": item.get("ambiguity_reasons") or [],
            "evaluation_status": item.get("evaluation_status"),
            "error_reason": item.get("error_reason"),
        }
        for item in rows[:limit]
    ]


def _newly_covered(baseline_records: Sequence[Mapping[str, Any]], optimized_records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    baseline_by_key = {_row_key(record): record for record in baseline_records}
    output = []
    for record in optimized_records:
        baseline = baseline_by_key.get(_row_key(record)) or {}
        if baseline.get("predicted_qname") or not record.get("predicted_qname"):
            continue
        output.append(dict(record))
    return output


def _high_risk(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    risk_terms = (
        "conflict",
        "generic_label_row_order_only",
        "notes_context_requires_review",
        "cash_flow_cash_equivalents_requires_review",
    )
    output = []
    for item in records:
        text = " ".join(str(value) for value in [*(item.get("blocking_reasons") or []), *(item.get("ambiguity_reasons") or [])])
        if any(term in text for term in risk_terms):
            output.append(dict(item))
    return output


def _recommend_next(total: int, touched: int, new_precision: float | None) -> dict[str, Any]:
    coverage = _safe_rate(touched, total) or 0.0
    if new_precision is not None and new_precision < 0.9:
        next_feature = "Feature #18E-B-2-hotfix-1 - Tighten dictionary/row-order candidates before further expansion."
        reason = "New dictionary/row-order candidates fell below 0.90 local precision on evaluable rows."
    elif coverage >= 0.78:
        next_feature = "Feature #18F-A - Design hybrid deterministic mapper orchestration."
        reason = "Coverage is near the 80% candidate coverage target."
    elif coverage >= 0.6:
        next_feature = "Feature #18E-D - Evaluate mapper precision and conflict risk against local XBRL facts."
        reason = "Coverage reached the 60-70% range and needs precision/conflict hardening."
    elif coverage < 0.55:
        next_feature = "Feature #18E-B-3 - Add company-format template memory and note-detail mapping boundaries."
        reason = "Coverage remains below 55%."
    else:
        next_feature = "Feature #18E-D - Evaluate mapper precision and conflict risk against local XBRL facts."
        reason = "Coverage reached the lower target range and should be evaluated before more expansion."
    return {
        "recommended_next_feature": next_feature,
        "reason": reason,
        "basis": {
            "touched_coverage_rate": coverage,
            "new_candidate_precision_on_evaluable": new_precision,
            "safe_for_auto_apply_count": 0,
        },
    }


def _render_optimized_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    evaluation = summary.get("local_xbrl_evaluation") or {}
    lines = [
        "# Rulebook Mapper Dictionary Optimized - Feature #18E-B-2",
        "",
        f"- Total observations: {summary.get('total_pdf_row_value_observations', 0)}",
        f"- Advisory suggestions: {summary.get('advisory_suggestions_count', 0)}",
        f"- Review-required suggestions: {summary.get('review_required_suggestions_count', 0)}",
        f"- No-match: {summary.get('no_match_count', 0)}",
        f"- Dictionary/row-order optimizations applied: {summary.get('dictionary_row_order_optimization_applied_count', 0)}",
        f"- Safe for auto-apply: {summary.get('safe_for_auto_apply_count', 0)}",
        f"- Precision on locally evaluable rows: {evaluation.get('precision_on_evaluable')}",
        "",
        "## Newly Covered Labels",
        "",
        "| Label | Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("newly_covered_labels") or []:
        lines.append(f"| {item.get('normalized_label')} | {item.get('count')} |")
    lines.append("")
    return "\n".join(lines)


def _render_comparison_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Rulebook Mapper Dictionary Coverage Comparison - Feature #18E-B-2",
        "",
        "| Metric | #18E-B baseline | #18E-B-2 optimized |",
        "| --- | ---: | ---: |",
    ]
    for key in (
        "total_pdf_row_value_observations",
        "advisory_suggestions_count",
        "review_required_suggestions_count",
        "no_match_count",
        "touched_suggestions_count",
        "touched_coverage_rate",
        "precision_on_evaluable",
    ):
        lines.append(f"| {key} | {summary.get('baseline', {}).get(key)} | {summary.get('optimized', {}).get(key)} |")
    new_eval = (summary.get("improvement") or {}).get("newly_covered_local_xbrl_evaluation") or {}
    lines.extend(["", f"- Next: {(summary.get('recommendation') or {}).get('recommended_next_feature')}", ""])
    lines.insert(-1, f"- Newly covered precision on locally evaluable rows: {new_eval.get('precision_on_evaluable')}")
    return "\n".join(lines)


def _render_errors_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Rulebook Mapper Dictionary Errors - Feature #18E-B-2",
        "",
        f"- False positives: {summary.get('false_positive_count', 0)}",
        f"- High-risk ambiguity cases: {summary.get('high_risk_ambiguity_count', 0)}",
        "",
        "| Sample | Label | QName | Status | Method |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in report.get("errors") or []:
        lines.append(
            f"| {item.get('sample_id')} | {item.get('pdf_label')} | {item.get('predicted_qname')} | "
            f"{item.get('evaluation_status')} | {item.get('candidate_generation_method')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_no_match_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Rulebook Mapper Dictionary No-Match Rows - Feature #18E-B-2",
        "",
        f"- No-match rows: {summary.get('no_match_count', 0)}",
        "",
        "| Normalized label | Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("top_no_match_labels") or []:
        lines.append(f"| {item.get('normalized_label')} | {item.get('count')} |")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Expand #18E-B mapper coverage with dictionary and row-order candidates.")
    parser.add_argument("--dataset-dir", default="benchmark_mbrs_pairs", help="Local benchmark PDF/XML pair directory.")
    parser.add_argument("--hardened-rulebook", default="reports/pdf_xbrl_rulebook_hardening_18d_b.json", help="Feature #18D-B hardened rulebook/readiness report.")
    parser.add_argument("--baseline-report", default="reports/rulebook_mapper_template_optimized_18e_b.json", help="Feature #18E-B optimized mapper report.")
    parser.add_argument("--uncovered-report", default="reports/mapper_comparison_uncovered_18e_c.json", help="Feature #18E-C uncovered rows report.")
    parser.add_argument("--output-dir", default="reports", help="Directory for #18E-B-2 reports.")
    parser.add_argument("--include-sample", action="append", default=[], help="Sample id to include; repeat for multiple samples.")
    parser.add_argument("--exclude-sample", action="append", default=[], help="Sample id to exclude; repeat for multiple samples.")
    parser.add_argument("--include-outlier", action="store_true", help="Include outlier samples such as Shield Plus.")
    parser.add_argument("--debug-label", help="Only map rows whose normalized label contains this text.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generated_at = _utc_now()
    hardened = _read_json(args.hardened_rulebook)
    rules = load_hardened_mapper_rules(hardened)
    baseline_report = _read_json(args.baseline_report)
    baseline_records = list(baseline_report.get("suggestions") or [])
    baseline_summary = dict(baseline_report.get("summary") or {})

    row_context_report = build_row_context_report(
        dataset_dir=args.dataset_dir,
        include_samples=args.include_sample,
        exclude_samples=args.exclude_sample,
        include_outlier=args.include_outlier,
    )
    contexts = row_context_report["row_contexts"]
    context_by_row = {_context_key(item): item for item in contexts}

    dictionary_entries = statement_concept_candidate_entries()
    dictionary_report = build_statement_concept_candidate_dictionary_report(contexts=contexts, entries=dictionary_entries)
    row_order_report = build_statement_row_order_alignment_report(contexts)
    alignment_by_row = row_order_alignment_index(row_order_report["row_order_alignments"])

    optimized_records = []
    for record in baseline_records:
        if args.debug_label and args.debug_label.lower() not in str(record.get("pdf_label") or "").lower():
            continue
        context = _record_context(record, context_by_row)
        optimized_records.append(
            apply_dictionary_row_order_mapping(
                record,
                context,
                dictionary_entries,
                row_order_alignment=alignment_by_row.get(_row_key(record)),
            )
        )

    loaded_rows = load_pdf_row_observations(
        dataset_dir=args.dataset_dir,
        include_samples=args.include_sample,
        exclude_samples=args.exclude_sample,
        include_outlier=args.include_outlier,
    )
    row_values = loaded_rows["row_values"]
    samples = loaded_rows["samples"]
    included_samples = [item for item in samples if item.get("status") == "included"]
    facts_by_sample = {
        str(sample.get("sample_id")): load_sample_replay_data(
            dataset_dir=args.dataset_dir,
            sample_id=str(sample.get("sample_id")),
            company_name=str(sample.get("company_name") or sample.get("sample_id")),
        ).get("facts")
        or []
        for sample in included_samples
    }
    evaluated = _evaluate_records(optimized_records, row_values=row_values, facts_by_sample=facts_by_sample)
    newly_covered = _newly_covered(baseline_records, evaluated)
    new_eval = _eval_summary(newly_covered)
    optimized_summary = summarize_mapper_records(evaluated, samples=samples, rules=rules, generated_at=generated_at)
    optimized_summary["feature"] = "18E-B-2"
    optimized_summary["local_xbrl_evaluation"] = _eval_summary(evaluated)
    optimized_summary["newly_covered_count"] = len(newly_covered)
    optimized_summary["newly_covered_labels"] = _top_labels(newly_covered, limit=50)
    optimized_summary["new_dictionary_row_order_precision"] = new_eval
    optimized_summary["dictionary_row_order_optimization_applied_count"] = sum(
        1 for item in evaluated if item.get("dictionary_row_order_optimization_applied")
    )
    optimized_summary["dictionary_candidate_usage"] = [
        {"dictionary_entry_id": key, "count": count}
        for key, count in Counter(str(item.get("dictionary_entry_id")) for item in evaluated if item.get("dictionary_entry_id")).most_common(40)
    ]
    optimized_summary["row_order_candidate_usage"] = [
        {"expected_qname": key, "count": count}
        for key, count in Counter(str(item.get("predicted_qname")) for item in evaluated if item.get("row_order_alignment_id")).most_common(40)
    ]
    optimized_summary["dictionary_row_order_agreement_count"] = sum(
        1 for item in evaluated if item.get("candidate_generation_method") == "dictionary_row_order_agreement"
    )
    optimized_summary["high_risk_ambiguity_count"] = len(_high_risk(evaluated))
    optimized_summary["still_uncovered_labels"] = _top_labels([item for item in evaluated if item.get("confidence_bucket") == "no_match"], limit=50)

    total = int(optimized_summary.get("total_pdf_row_value_observations") or 0)
    baseline_touched = _touched_summary(baseline_summary)
    optimized_touched = _touched_summary(optimized_summary)
    recommendation = _recommend_next(total, optimized_touched, new_eval.get("precision_on_evaluable"))
    optimized_summary["recommendation"] = recommendation
    optimized_summary["eighty_percent_candidate_coverage_realistic_after_this_pass"] = bool(
        optimized_touched and optimized_touched / total >= 0.65 and len(newly_covered) >= 100
    )
    optimized_summary["explicit_auto_apply_statement"] = "No #18E-B-2 suggestion is safe for auto-apply; human review remains required."

    run_metadata = {
        "feature": "18E-B-2",
        "generated_at": generated_at,
        "read_only": True,
        "offline_only": True,
        "dataset_dir": str(args.dataset_dir),
        "hardened_rulebook": str(args.hardened_rulebook),
        "baseline_report": str(args.baseline_report),
        "uncovered_report": str(args.uncovered_report),
        "include_samples": list(args.include_sample),
        "exclude_samples": list(args.exclude_sample),
        "include_outlier": args.include_outlier,
        "debug_label": args.debug_label,
        **SAFETY,
    }

    optimized_report = {
        "run_metadata": run_metadata,
        "summary": optimized_summary,
        "suggestions": evaluated,
    }
    comparison_report = {
        "run_metadata": run_metadata,
        "summary": {
            "baseline": {
                "total_pdf_row_value_observations": baseline_summary.get("total_pdf_row_value_observations"),
                "advisory_suggestions_count": baseline_summary.get("advisory_suggestions_count"),
                "review_required_suggestions_count": baseline_summary.get("review_required_suggestions_count"),
                "no_match_count": baseline_summary.get("no_match_count"),
                "touched_suggestions_count": baseline_touched,
                "touched_coverage_rate": _safe_rate(baseline_touched, total),
                "precision_on_evaluable": (baseline_summary.get("local_xbrl_evaluation") or {}).get("precision_on_evaluable"),
            },
            "optimized": {
                "total_pdf_row_value_observations": optimized_summary.get("total_pdf_row_value_observations"),
                "advisory_suggestions_count": optimized_summary.get("advisory_suggestions_count"),
                "review_required_suggestions_count": optimized_summary.get("review_required_suggestions_count"),
                "no_match_count": optimized_summary.get("no_match_count"),
                "touched_suggestions_count": optimized_touched,
                "touched_coverage_rate": _safe_rate(optimized_touched, total),
                "precision_on_evaluable": optimized_summary["local_xbrl_evaluation"].get("precision_on_evaluable"),
            },
            "improvement": {
                "touched_suggestions_delta": optimized_touched - baseline_touched,
                "coverage_rate_delta": round((_safe_rate(optimized_touched, total) or 0) - (_safe_rate(baseline_touched, total) or 0), 4),
                "no_match_delta": int(optimized_summary.get("no_match_count") or 0) - int(baseline_summary.get("no_match_count") or 0),
                "newly_covered_count": len(newly_covered),
                "newly_covered_labels": _top_labels(newly_covered, limit=50),
                "newly_covered_local_xbrl_evaluation": new_eval,
            },
            "dictionary_candidate_usage": optimized_summary["dictionary_candidate_usage"],
            "row_order_candidate_usage": optimized_summary["row_order_candidate_usage"],
            "dictionary_row_order_agreement_count": optimized_summary["dictionary_row_order_agreement_count"],
            "high_risk_ambiguity_count": optimized_summary["high_risk_ambiguity_count"],
            "eighty_percent_candidate_coverage_realistic_after_this_pass": optimized_summary[
                "eighty_percent_candidate_coverage_realistic_after_this_pass"
            ],
            "recommendation": recommendation,
            "safety": SAFETY,
        },
        "newly_covered_rows": _top_records(newly_covered, limit=200),
    }
    false_or_uncertain = [
        item
        for item in evaluated
        if item.get("predicted_qname") and item.get("evaluation_status") in (FALSE_POSITIVE_STATUSES | NOT_EVALUABLE_STATUSES)
    ]
    high_risk = _high_risk(evaluated)
    errors_report = {
        "run_metadata": run_metadata,
        "summary": {
            "false_positive_count": sum(1 for item in evaluated if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES),
            "not_evaluable_count": sum(1 for item in evaluated if item.get("predicted_qname") and item.get("evaluation_status") in NOT_EVALUABLE_STATUSES),
            "high_risk_ambiguity_count": len(high_risk),
            "evaluation_status_counts": optimized_summary["local_xbrl_evaluation"].get("evaluation_status_counts"),
            "safety": SAFETY,
        },
        "errors": _top_records(false_or_uncertain, limit=200),
        "high_risk_ambiguity_cases": _top_records(high_risk, limit=200),
    }
    no_match_rows = [item for item in evaluated if item.get("confidence_bucket") == "no_match"]
    no_match_report = {
        "run_metadata": run_metadata,
        "summary": {
            "no_match_count": len(no_match_rows),
            "top_no_match_labels": _top_labels(no_match_rows, limit=60),
            "safety": SAFETY,
        },
        "no_match": no_match_rows,
    }

    paths = {
        "dictionary_json": output / "statement_concept_candidate_dictionary_18e_b2.json",
        "dictionary_md": output / "statement_concept_candidate_dictionary_18e_b2.md",
        "row_order_json": output / "statement_row_order_alignment_18e_b2.json",
        "row_order_md": output / "statement_row_order_alignment_18e_b2.md",
        "optimized_json": output / "rulebook_mapper_dictionary_optimized_18e_b2.json",
        "optimized_md": output / "rulebook_mapper_dictionary_optimized_18e_b2.md",
        "comparison_json": output / "rulebook_mapper_dictionary_coverage_comparison_18e_b2.json",
        "comparison_md": output / "rulebook_mapper_dictionary_coverage_comparison_18e_b2.md",
        "errors_json": output / "rulebook_mapper_dictionary_errors_18e_b2.json",
        "errors_md": output / "rulebook_mapper_dictionary_errors_18e_b2.md",
        "no_match_json": output / "rulebook_mapper_dictionary_no_match_18e_b2.json",
        "no_match_md": output / "rulebook_mapper_dictionary_no_match_18e_b2.md",
    }
    _write_json(paths["dictionary_json"], dictionary_report)
    paths["dictionary_md"].write_text(render_statement_concept_candidate_dictionary_markdown(dictionary_report), encoding="utf-8")
    _write_json(paths["row_order_json"], row_order_report)
    paths["row_order_md"].write_text(render_statement_row_order_alignment_markdown(row_order_report), encoding="utf-8")
    _write_json(paths["optimized_json"], optimized_report)
    paths["optimized_md"].write_text(_render_optimized_markdown(optimized_report), encoding="utf-8")
    _write_json(paths["comparison_json"], comparison_report)
    paths["comparison_md"].write_text(_render_comparison_markdown(comparison_report), encoding="utf-8")
    _write_json(paths["errors_json"], errors_report)
    paths["errors_md"].write_text(_render_errors_markdown(errors_report), encoding="utf-8")
    _write_json(paths["no_match_json"], no_match_report)
    paths["no_match_md"].write_text(_render_no_match_markdown(no_match_report), encoding="utf-8")

    print("Feature #18E-B-2 dictionary/row-order mapper reports written:")
    for name, path in paths.items():
        print(f"- {name}: {path}")
    print("")
    print("Coverage comparison:")
    print(f"- baseline_touched_coverage_rate: {comparison_report['summary']['baseline']['touched_coverage_rate']}")
    print(f"- optimized_touched_coverage_rate: {comparison_report['summary']['optimized']['touched_coverage_rate']}")
    print(f"- newly_covered_count: {len(newly_covered)}")
    print(f"- new_candidate_precision_on_evaluable: {new_eval.get('precision_on_evaluable')}")
    print(f"- safe_for_auto_apply_count: {optimized_summary['safe_for_auto_apply_count']}")
    print(f"- next: {recommendation['recommended_next_feature']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
