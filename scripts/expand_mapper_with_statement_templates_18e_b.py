"""Run Feature #18E-B statement-template optimized offline mapper reports."""

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

from services.pdf_note_link_extraction import build_note_link_report, note_link_index, render_note_link_markdown
from services.pdf_row_context_extraction import build_row_context_report
from services.pdf_statement_template_patterns import (
    build_statement_template_report,
    render_statement_template_markdown,
)
from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label
from services.pdf_xbrl_rulebook_mapper import (
    SAFETY,
    apply_context_optimized_mapping,
    apply_statement_template_mapping,
    build_mapper_reports,
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def _safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _row_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record.get("sample_id") or ""), str(record.get("pdf_row_id") or "")


def _context_key(context: Mapping[str, Any]) -> tuple[str, str]:
    return str(context.get("sample_id") or ""), str(context.get("row_id") or "")


def _advisory(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in records if item.get("confidence_bucket") in {"advisory_high", "advisory_medium"}]


def _review(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in records if item.get("confidence_bucket") == "review_required" and item.get("predicted_qname")]


def _no_match(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [item for item in records if item.get("confidence_bucket") == "no_match"]


def _top_no_match_labels(records: Sequence[Mapping[str, Any]], *, limit: int = 40) -> list[dict[str, Any]]:
    counter = Counter(str(item.get("normalized_label") or canonical_label(item.get("pdf_label"))) for item in records)
    return [{"normalized_label": label, "count": count} for label, count in counter.most_common(limit) if label]


def _top_template_usage(records: Sequence[Mapping[str, Any]], *, limit: int = 40) -> list[dict[str, Any]]:
    counter = Counter(str(item.get("matched_template_pattern_id") or "") for item in records if item.get("matched_template_pattern_id"))
    return [{"matched_template_pattern_id": key, "count": count} for key, count in counter.most_common(limit) if key]


def _top_records(records: Sequence[Mapping[str, Any]], *, limit: int = 80) -> list[dict[str, Any]]:
    rows = list(records)
    rows.sort(key=lambda item: (str(item.get("sample_id")), str(item.get("normalized_label")), str(item.get("pdf_row_id"))))
    return [
        {
            "sample_id": item.get("sample_id"),
            "pdf_row_id": item.get("pdf_row_id"),
            "pdf_label": item.get("pdf_label"),
            "pdf_value": item.get("pdf_value"),
            "predicted_qname": item.get("predicted_qname"),
            "confidence_bucket": item.get("confidence_bucket"),
            "matched_rule_id": item.get("matched_rule_id"),
            "matched_template_pattern_id": item.get("matched_template_pattern_id"),
            "candidate_source": item.get("candidate_source"),
            "note_link": item.get("note_link"),
            "blocking_reasons": item.get("blocking_reasons") or [],
            "evaluation_status": item.get("evaluation_status"),
            "error_reason": item.get("error_reason"),
        }
        for item in rows[:limit]
    ]


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
    advisory = _advisory(records)
    review = _review(records)
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


def _touched(summary: Mapping[str, Any]) -> int:
    return (
        int(summary.get("advisory_suggestions_count") or 0)
        + int(summary.get("review_required_suggestions_count") or 0)
        + int(summary.get("conflicts_count") or 0)
    )


def _recommend_next(total: int, touched: int, advisory_precision: float | None) -> dict[str, Any]:
    coverage = _safe_rate(touched, total) or 0.0
    if advisory_precision is not None and advisory_precision < 0.9:
        next_feature = "Feature #18E-B-hotfix-1 - Tighten template expansion before further mapper comparison."
    elif coverage < 0.4:
        next_feature = "Feature #18E-B-hotfix-1 - Add safer statement templates for remaining high-frequency no-match rows."
    else:
        next_feature = "Feature #18E-C - Compare expanded deterministic mapper against Qwen on the same offline benchmark."
    return {
        "recommended_next_feature": next_feature,
        "basis": {
            "touched_coverage_rate": coverage,
            "advisory_precision_on_evaluable": advisory_precision,
            "safe_for_auto_apply_count": 0,
        },
    }


def _render_optimized_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    evaluation = summary.get("local_xbrl_evaluation") or {}
    lines = [
        "# Rulebook Mapper Template Optimized - Feature #18E-B",
        "",
        f"- Total observations: {summary.get('total_pdf_row_value_observations', 0)}",
        f"- Advisory suggestions: {summary.get('advisory_suggestions_count', 0)}",
        f"- Review-required suggestions: {summary.get('review_required_suggestions_count', 0)}",
        f"- No-match: {summary.get('no_match_count', 0)}",
        f"- Statement-template optimizations applied: {summary.get('statement_template_optimization_applied_count', 0)}",
        f"- Safe for auto-apply: {summary.get('safe_for_auto_apply_count', 0)}",
        f"- Advisory precision on locally evaluable rows: {evaluation.get('advisory_precision_on_evaluable')}",
        "",
        "## Template Usage",
        "",
        "| Template | Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("top_template_usage") or []:
        lines.append(f"| {item.get('matched_template_pattern_id')} | {item.get('count')} |")
    lines.append("")
    return "\n".join(lines)


def _render_comparison_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Rulebook Mapper Template Coverage Comparison - Feature #18E-B",
        "",
        "| Metric | Context optimized #18E-A | Template optimized #18E-B |",
        "| --- | ---: | ---: |",
    ]
    for key in (
        "total_pdf_row_value_observations",
        "advisory_suggestions_count",
        "review_required_suggestions_count",
        "no_match_count",
        "touched_suggestions_count",
        "touched_coverage_rate",
        "advisory_precision_on_evaluable",
    ):
        lines.append(
            f"| {key} | {summary.get('context_optimized', {}).get(key)} | {summary.get('template_optimized', {}).get(key)} |"
        )
    lines.extend(["", f"- Next: {(summary.get('recommendation') or {}).get('recommended_next_feature')}", ""])
    return "\n".join(lines)


def _render_errors_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Rulebook Mapper Template Errors - Feature #18E-B",
        "",
        f"- False positives: {summary.get('false_positive_count', 0)}",
        f"- Not evaluable predictions: {summary.get('not_evaluable_count', 0)}",
        "",
        "| Sample | Label | Value | QName | Status | Reason |",
        "| --- | --- | ---: | --- | --- | --- |",
    ]
    for item in report.get("errors") or []:
        lines.append(
            f"| {item.get('sample_id')} | {item.get('pdf_label')} | {item.get('pdf_value')} | "
            f"{item.get('predicted_qname')} | {item.get('evaluation_status')} | {item.get('error_reason')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_no_match_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Rulebook Mapper Template No-Match Rows - Feature #18E-B",
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
    parser = argparse.ArgumentParser(description="Expand #18E-A mapper coverage with statement templates and note links.")
    parser.add_argument("--dataset-dir", default="benchmark_mbrs_pairs", help="Local benchmark PDF/XML pair directory.")
    parser.add_argument("--hardened-rulebook", default="reports/pdf_xbrl_rulebook_hardening_18d_b.json", help="Feature #18D-B hardened rulebook/readiness report.")
    parser.add_argument("--output-dir", default="reports", help="Directory for #18E-B reports.")
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

    row_context_report = build_row_context_report(
        dataset_dir=args.dataset_dir,
        include_samples=args.include_sample,
        exclude_samples=args.exclude_sample,
        include_outlier=args.include_outlier,
    )
    contexts = row_context_report["row_contexts"]
    context_by_row = {_context_key(item): item for item in contexts}

    statement_template_report = build_statement_template_report(contexts)
    statement_patterns = statement_template_report["statement_template_patterns"]

    note_link_report = build_note_link_report(
        dataset_dir=args.dataset_dir,
        include_samples=args.include_sample,
        exclude_samples=args.exclude_sample,
        include_outlier=args.include_outlier,
    )
    note_by_row = note_link_index(note_link_report["note_links"])

    loaded_rows = load_pdf_row_observations(
        dataset_dir=args.dataset_dir,
        include_samples=args.include_sample,
        exclude_samples=args.exclude_sample,
        include_outlier=args.include_outlier,
    )
    row_values = loaded_rows["row_values"]
    samples = loaded_rows["samples"]
    included_samples = [item for item in samples if item.get("status") == "included"]

    baseline_reports = build_mapper_reports(
        dataset_dir=args.dataset_dir,
        hardened_rulebook=hardened,
        include_samples=args.include_sample,
        exclude_samples=args.exclude_sample,
        include_outlier=args.include_outlier,
        debug_label=args.debug_label,
    )
    baseline_records = baseline_reports["suggestions"]["suggestions"]
    context_records = [
        apply_context_optimized_mapping(record, context_by_row.get(_row_key(record)))
        for record in baseline_records
    ]
    template_records = [
        apply_statement_template_mapping(
            record,
            context_by_row.get(_row_key(record)),
            statement_patterns,
            note_link=note_by_row.get(_row_key(record)),
        )
        for record in context_records
    ]

    facts_by_sample = {
        str(sample.get("sample_id")): load_sample_replay_data(
            dataset_dir=args.dataset_dir,
            sample_id=str(sample.get("sample_id")),
            company_name=str(sample.get("company_name") or sample.get("sample_id")),
        ).get("facts")
        or []
        for sample in included_samples
    }
    context_evaluated = _evaluate_records(context_records, row_values=row_values, facts_by_sample=facts_by_sample)
    template_evaluated = _evaluate_records(template_records, row_values=row_values, facts_by_sample=facts_by_sample)

    context_summary = summarize_mapper_records(context_records, samples=samples, rules=rules, generated_at=generated_at)
    context_summary["feature"] = "18E-A"
    context_summary["local_xbrl_evaluation"] = _eval_summary(context_evaluated)

    template_summary = summarize_mapper_records(template_records, samples=samples, rules=rules, generated_at=generated_at)
    template_summary["feature"] = "18E-B"
    template_summary["statement_template_optimization_applied_count"] = sum(
        1 for item in template_records if item.get("statement_template_optimization_applied")
    )
    template_summary["note_link_attached_count"] = sum(1 for item in template_records if item.get("note_link"))
    template_summary["top_template_usage"] = _top_template_usage(template_records)
    template_summary["local_xbrl_evaluation"] = _eval_summary(template_evaluated)
    template_summary["explicit_auto_apply_statement"] = "No #18E-B suggestion is safe for auto-apply; human review remains required."

    total = int(template_summary.get("total_pdf_row_value_observations") or 0)
    context_touched = _touched(context_summary)
    template_touched = _touched(template_summary)
    recommendation = _recommend_next(
        total,
        template_touched,
        template_summary["local_xbrl_evaluation"].get("advisory_precision_on_evaluable"),
    )
    template_summary["recommendation"] = recommendation

    run_metadata = {
        "feature": "18E-B",
        "generated_at": generated_at,
        "read_only": True,
        "offline_only": True,
        "dataset_dir": str(args.dataset_dir),
        "hardened_rulebook": str(args.hardened_rulebook),
        "include_samples": list(args.include_sample),
        "exclude_samples": list(args.exclude_sample),
        "include_outlier": args.include_outlier,
        "debug_label": args.debug_label,
        **SAFETY,
    }

    optimized_report = {
        "run_metadata": run_metadata,
        "summary": template_summary,
        "suggestions": template_evaluated,
    }
    comparison_report = {
        "run_metadata": run_metadata,
        "summary": {
            "context_optimized": {
                "total_pdf_row_value_observations": context_summary.get("total_pdf_row_value_observations"),
                "advisory_suggestions_count": context_summary.get("advisory_suggestions_count"),
                "review_required_suggestions_count": context_summary.get("review_required_suggestions_count"),
                "no_match_count": context_summary.get("no_match_count"),
                "touched_suggestions_count": context_touched,
                "touched_coverage_rate": _safe_rate(context_touched, total),
                "advisory_precision_on_evaluable": context_summary["local_xbrl_evaluation"].get("advisory_precision_on_evaluable"),
            },
            "template_optimized": {
                "total_pdf_row_value_observations": template_summary.get("total_pdf_row_value_observations"),
                "advisory_suggestions_count": template_summary.get("advisory_suggestions_count"),
                "review_required_suggestions_count": template_summary.get("review_required_suggestions_count"),
                "no_match_count": template_summary.get("no_match_count"),
                "touched_suggestions_count": template_touched,
                "touched_coverage_rate": _safe_rate(template_touched, total),
                "advisory_precision_on_evaluable": template_summary["local_xbrl_evaluation"].get("advisory_precision_on_evaluable"),
            },
            "improvement": {
                "touched_suggestions_delta": template_touched - context_touched,
                "no_match_delta": int(template_summary.get("no_match_count") or 0) - int(context_summary.get("no_match_count") or 0),
            },
            "recommendation": recommendation,
            "safety": SAFETY,
        },
    }
    errors = [
        item
        for item in template_evaluated
        if item.get("predicted_qname") and item.get("evaluation_status") in (FALSE_POSITIVE_STATUSES | NOT_EVALUABLE_STATUSES)
    ]
    errors_report = {
        "run_metadata": run_metadata,
        "summary": {
            "false_positive_count": sum(1 for item in template_evaluated if item.get("evaluation_status") in FALSE_POSITIVE_STATUSES),
            "not_evaluable_count": sum(1 for item in template_evaluated if item.get("predicted_qname") and item.get("evaluation_status") in NOT_EVALUABLE_STATUSES),
            "evaluation_status_counts": template_summary["local_xbrl_evaluation"].get("evaluation_status_counts"),
            "safety": SAFETY,
        },
        "errors": _top_records(errors, limit=120),
    }
    no_match_rows = _no_match(template_records)
    no_match_report = {
        "run_metadata": run_metadata,
        "summary": {
            "no_match_count": len(no_match_rows),
            "top_no_match_labels": _top_no_match_labels(no_match_rows, limit=50),
            "safety": SAFETY,
        },
        "no_match": no_match_rows,
    }

    paths = {
        "template_patterns_json": output / "statement_template_patterns_18e_b.json",
        "template_patterns_md": output / "statement_template_patterns_18e_b.md",
        "note_links_json": output / "pdf_note_links_18e_b.json",
        "note_links_md": output / "pdf_note_links_18e_b.md",
        "optimized_json": output / "rulebook_mapper_template_optimized_18e_b.json",
        "optimized_md": output / "rulebook_mapper_template_optimized_18e_b.md",
        "comparison_json": output / "rulebook_mapper_template_coverage_comparison_18e_b.json",
        "comparison_md": output / "rulebook_mapper_template_coverage_comparison_18e_b.md",
        "errors_json": output / "rulebook_mapper_template_errors_18e_b.json",
        "errors_md": output / "rulebook_mapper_template_errors_18e_b.md",
        "no_match_json": output / "rulebook_mapper_template_no_match_18e_b.json",
        "no_match_md": output / "rulebook_mapper_template_no_match_18e_b.md",
    }
    _write_json(paths["template_patterns_json"], statement_template_report)
    paths["template_patterns_md"].write_text(render_statement_template_markdown(statement_template_report), encoding="utf-8")
    _write_json(paths["note_links_json"], note_link_report)
    paths["note_links_md"].write_text(render_note_link_markdown(note_link_report), encoding="utf-8")
    _write_json(paths["optimized_json"], optimized_report)
    paths["optimized_md"].write_text(_render_optimized_markdown(optimized_report), encoding="utf-8")
    _write_json(paths["comparison_json"], comparison_report)
    paths["comparison_md"].write_text(_render_comparison_markdown(comparison_report), encoding="utf-8")
    _write_json(paths["errors_json"], errors_report)
    paths["errors_md"].write_text(_render_errors_markdown(errors_report), encoding="utf-8")
    _write_json(paths["no_match_json"], no_match_report)
    paths["no_match_md"].write_text(_render_no_match_markdown(no_match_report), encoding="utf-8")

    print("Feature #18E-B statement-template mapper reports written:")
    for name, path in paths.items():
        print(f"- {name}: {path}")
    print("")
    print("Coverage comparison:")
    print(f"- context_touched_coverage_rate: {comparison_report['summary']['context_optimized']['touched_coverage_rate']}")
    print(f"- template_touched_coverage_rate: {comparison_report['summary']['template_optimized']['touched_coverage_rate']}")
    print(f"- template_advisory_precision_on_evaluable: {comparison_report['summary']['template_optimized']['advisory_precision_on_evaluable']}")
    print(f"- safe_for_auto_apply_count: {template_summary['safe_for_auto_apply_count']}")
    print(f"- next: {recommendation['recommended_next_feature']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
