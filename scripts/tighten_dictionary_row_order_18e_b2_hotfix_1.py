"""Run Feature #18E-B-2-hotfix-1 tightened dictionary/row-order reports."""

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

from scripts.expand_mapper_with_dictionary_row_order_18e_b2 import (
    _context_key,
    _eval_summary,
    _evaluate_records,
    _read_json,
    _record_context,
    _row_key,
    _safe_rate,
    _top_labels,
    _top_records,
    _touched_summary,
    _write_json,
)
from services.pdf_row_context_extraction import build_row_context_report
from services.pdf_statement_row_order_alignment import (
    build_statement_row_order_alignment_report,
    row_order_alignment_index,
)
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
    evaluate_prediction,
    load_sample_replay_data,
)
from services.statement_concept_candidate_dictionary import statement_concept_candidate_entries


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _newly_covered(baseline_records: Sequence[Mapping[str, Any]], records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    baseline_by_key = {_row_key(record): record for record in baseline_records}
    output = []
    for record in records:
        baseline = baseline_by_key.get(_row_key(record)) or {}
        if baseline.get("predicted_qname") or not record.get("predicted_qname"):
            continue
        output.append(dict(record))
    return output


def _selected_row(record: Mapping[str, Any]) -> dict[str, Any]:
    context = record.get("row_context") if isinstance(record.get("row_context"), Mapping) else {}
    return {
        "sample_id": record.get("sample_id"),
        "pdf_row_id": record.get("pdf_row_id"),
        "pdf_label": record.get("pdf_label"),
        "normalized_label": record.get("normalized_label"),
        "statement_family": context.get("statement_family"),
        "section_block": context.get("section_block"),
        "row_role": context.get("row_role"),
        "predicted_qname": record.get("predicted_qname"),
        "candidate_generation_method": record.get("candidate_generation_method"),
        "dictionary_entry_id": record.get("dictionary_entry_id"),
        "row_order_alignment_id": record.get("row_order_alignment_id"),
        "evaluation_status": record.get("evaluation_status"),
        "error_reason": record.get("error_reason"),
        "blocking_reasons": record.get("blocking_reasons") or [],
        "blocked_candidate_reasons": record.get("blocked_candidate_reasons") or [],
    }


def _field_value(record: Mapping[str, Any], field: str) -> str:
    context = record.get("row_context") if isinstance(record.get("row_context"), Mapping) else {}
    if field in {"statement_family", "section_block", "row_role"}:
        return str(context.get(field) or "")
    return str(record.get(field) or "")


def _group_counts(records: Sequence[Mapping[str, Any]], fields: Sequence[str], *, limit: int = 40) -> list[dict[str, Any]]:
    counter = Counter(tuple(_field_value(record, field) for field in fields) for record in records)
    rows = []
    for key, count in counter.most_common(limit):
        item = {field: value for field, value in zip(fields, key)}
        item["count"] = count
        rows.append(item)
    return rows


def _root_causes(record: Mapping[str, Any]) -> list[str]:
    label = str(record.get("normalized_label") or "").lower()
    qname = str(record.get("predicted_qname") or "")
    method = str(record.get("candidate_generation_method") or "")
    entry_id = str(record.get("dictionary_entry_id") or "")
    context = record.get("row_context") if isinstance(record.get("row_context"), Mapping) else {}
    section = str(context.get("section_block") or "")
    family = str(context.get("statement_family") or "")
    row_role = str(context.get("row_role") or "")
    causes = []
    tokens = [token for token in label.split() if token]
    if len(tokens) <= 1 or label in {"amount", "balance", "current", "less", "net", "other", "subtotal", "total"}:
        causes.append("generic label overreach")
    if row_role == "note_detail" or section.startswith("notes_") or family in {"", "notes"}:
        causes.append("note-detail row incorrectly mapped to main-statement concept")
        causes.append("missing note-link confirmation")
    if method == "row_order_alignment":
        causes.append("row-order guessed too broadly")
        if not record.get("row_order_alignment_id"):
            causes.append("missing previous/next row confirmation")
    if qname == "ifrs-smes:AdministrativeExpense" or entry_id == "18E-B2-is-administrative-expenses":
        causes.append("subtotal/component confusion")
    if "CashFlowsFromUsedIn" in qname and any(term in label for term in ("before taxation", "profit", "loss", "decrease")):
        causes.append("cash-flow total confused with component row")
    if qname == "ifrs-smes:IncomeTaxExpenseContinuingOperations":
        if any(term in label for term in ("payable", "recoverable", "deferred")):
            causes.append("P&L tax expense vs balance-sheet tax confusion")
        elif section.startswith("notes_") or row_role == "note_detail":
            causes.append("note-detail tax reconciliation row mapped to P&L tax expense")
        else:
            causes.append("P&L tax subtotal/final-result confusion")
    if qname in {"ifrs-smes:TradeAndOtherCurrentReceivables", "ifrs-smes:TradeAndOtherCurrentPayables"}:
        causes.append("receivable/payable confusion")
    if qname in {"ifrs-smes:ProfitLoss", "ssmt-mpers:ProfitLossFromOperatingActivities"}:
        causes.append("profit/loss subtotal vs final result confusion")
    if family == "changes_in_equity":
        causes.append("equity row confusion")
    if entry_id == "18E-B2-sfp-borrowings":
        causes.append("value-only or weak-label candidate")
    return sorted(dict.fromkeys(causes or ["unknown false-positive cause"]))


def _false_positive_analysis(
    newly_covered_rows: Sequence[Mapping[str, Any]],
    pre_hotfix_errors: Mapping[str, Any],
) -> dict[str, Any]:
    false_rows = [dict(record) for record in newly_covered_rows if record.get("evaluation_status") in FALSE_POSITIVE_STATUSES]
    for record in false_rows:
        record["root_cause_categories"] = _root_causes(record)
    cause_counter = Counter(cause for record in false_rows for cause in record.get("root_cause_categories", []))
    return {
        "summary": {
            "pre_hotfix_new_false_positive_count": len(false_rows),
            "pre_hotfix_error_report_false_positive_count": (pre_hotfix_errors.get("summary") or {}).get("false_positive_count"),
            "root_cause_counts": [
                {"root_cause": cause, "count": count}
                for cause, count in cause_counter.most_common()
            ],
            "by_normalized_label": _group_counts(false_rows, ["normalized_label"], limit=60),
            "by_statement_family_section_qname": _group_counts(
                false_rows,
                ["statement_family", "section_block", "predicted_qname"],
                limit=60,
            ),
            "by_candidate_family": _group_counts(
                false_rows,
                ["candidate_generation_method", "dictionary_entry_id", "predicted_qname", "evaluation_status"],
                limit=80,
            ),
        },
        "false_positive_rows": [_selected_row(record) | {"root_cause_categories": record.get("root_cause_categories", [])} for record in false_rows],
    }


def _blocked_candidates(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    blocked = []
    for record in records:
        if not (record.get("blocked_dictionary_candidate") or record.get("blocked_row_order_candidate")):
            continue
        item = _selected_row(record)
        item["blocked_dictionary_candidate"] = record.get("blocked_dictionary_candidate")
        item["blocked_row_order_candidate"] = record.get("blocked_row_order_candidate")
        blocked.append(item)
    return blocked


def _comparison_lists(
    *,
    pre_new: Sequence[Mapping[str, Any]],
    post_new: Sequence[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    post_by_key = {_row_key(record): record for record in post_new}
    pre_good = [record for record in pre_new if record.get("evaluation_status") in GOOD_STATUSES]
    pre_false = [record for record in pre_new if record.get("evaluation_status") in FALSE_POSITIVE_STATUSES]
    correct_preserved = []
    correct_lost = []
    for record in pre_good:
        post = post_by_key.get(_row_key(record))
        if post and post.get("predicted_qname") == record.get("predicted_qname"):
            correct_preserved.append(_selected_row(post))
        else:
            lost = _selected_row(record)
            lost["post_hotfix_status"] = "blocked_or_no_match"
            correct_lost.append(lost)
    false_removed = []
    false_remaining = []
    for record in pre_false:
        post = post_by_key.get(_row_key(record))
        if post and post.get("predicted_qname") == record.get("predicted_qname"):
            false_remaining.append(_selected_row(post))
        else:
            removed = _selected_row(record)
            removed["post_hotfix_status"] = "blocked_or_no_match"
            false_removed.append(removed)
    return {
        "correct_candidates_preserved": correct_preserved,
        "correct_candidates_lost": correct_lost,
        "false_positives_removed": false_removed,
        "false_positives_remaining": false_remaining,
    }


def _recommend_next(post_coverage: float | None, post_precision: float | None, pre_precision: float | None) -> dict[str, Any]:
    coverage = post_coverage or 0.0
    precision = post_precision or 0.0
    improved = pre_precision is not None and post_precision is not None and post_precision > pre_precision
    if coverage >= 0.5 and precision >= 0.7:
        feature = "Feature #18E-D - Evaluate tightened mapper precision and conflict risk against local XBRL facts."
        reason = "Post-hotfix coverage remains at least 50% and new-candidate precision improved materially."
    elif coverage < 0.45 and improved:
        feature = "Feature #18E-B-3 - Add safer company-format template memory and note-detail boundaries."
        reason = "Precision improved but coverage dropped below 45%, so safer template/note boundaries are the next coverage path."
    elif precision < 0.7:
        feature = "Feature #18E-B-2-hotfix-2 - Disable noisy dictionary/row-order candidate families."
        reason = "Post-hotfix new-candidate precision remains below 0.70."
    else:
        feature = "Feature #18E-D - Evaluate tightened mapper precision and conflict risk against local XBRL facts."
        reason = "Precision improved enough for offline evaluation before further expansion."
    return {
        "recommended_next_feature": feature,
        "reason": reason,
        "basis": {
            "post_hotfix_touched_coverage_rate": post_coverage,
            "post_hotfix_new_candidate_precision_on_evaluable": post_precision,
            "pre_hotfix_new_candidate_precision_on_evaluable": pre_precision,
            "safe_for_auto_apply_count": 0,
        },
    }


def _render_table_report(title: str, report: Mapping[str, Any], rows_key: str) -> str:
    summary = report.get("summary") or {}
    lines = [f"# {title}", ""]
    for key, value in summary.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            lines.append(f"- {key}: {value}")
    lines.extend(["", "| Sample | Label | QName | Status | Reason |", "| --- | --- | --- | --- | --- |"])
    for item in report.get(rows_key) or []:
        reasons = ", ".join(item.get("blocked_candidate_reasons") or item.get("blocking_reasons") or item.get("root_cause_categories") or [])
        lines.append(
            f"| {item.get('sample_id')} | {item.get('pdf_label')} | {item.get('predicted_qname')} | "
            f"{item.get('evaluation_status')} | {reasons} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Dictionary/Row-Order Tightening Summary - Feature #18E-B-2-hotfix-1",
        "",
        "| Metric | #18E-B baseline | #18E-B-2 pre-hotfix | #18E-B-2-hotfix-1 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for key in ("touched_coverage_rate", "touched_suggestions_count", "no_match_count", "precision_on_evaluable"):
        lines.append(
            f"| {key} | {summary.get('baseline', {}).get(key)} | "
            f"{summary.get('pre_hotfix', {}).get(key)} | {summary.get('post_hotfix', {}).get(key)} |"
        )
    new_eval = summary.get("new_candidate_precision") or {}
    lines.extend(
        [
            "",
            f"- Pre-hotfix new candidate precision: {new_eval.get('pre_hotfix')}",
            f"- Post-hotfix new candidate precision: {new_eval.get('post_hotfix')}",
            f"- Correct candidates preserved: {summary.get('correct_candidates_preserved_count')}",
            f"- Correct candidates lost: {summary.get('correct_candidates_lost_count')}",
            f"- False positives removed: {summary.get('false_positives_removed_count')}",
            f"- False positives remaining: {summary.get('false_positives_remaining_count')}",
            f"- Blocked candidate rows: {summary.get('blocked_candidate_count')}",
            f"- Next: {(summary.get('recommendation') or {}).get('recommended_next_feature')}",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tighten #18E-B-2 dictionary/row-order mapper candidates.")
    parser.add_argument("--dataset-dir", default="benchmark_mbrs_pairs")
    parser.add_argument("--hardened-rulebook", default="reports/pdf_xbrl_rulebook_hardening_18d_b.json")
    parser.add_argument("--baseline-report", default="reports/rulebook_mapper_template_optimized_18e_b.json")
    parser.add_argument("--pre-hotfix-report", default="reports/rulebook_mapper_dictionary_optimized_18e_b2.json")
    parser.add_argument("--pre-hotfix-errors", default="reports/rulebook_mapper_dictionary_errors_18e_b2.json")
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--include-sample", action="append", default=[])
    parser.add_argument("--exclude-sample", action="append", default=[])
    parser.add_argument("--include-outlier", action="store_true")
    parser.add_argument("--debug-label")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    generated_at = _utc_now()

    hardened = _read_json(args.hardened_rulebook)
    rules = load_hardened_mapper_rules(hardened)
    baseline_report = _read_json(args.baseline_report)
    pre_hotfix_report = _read_json(args.pre_hotfix_report)
    pre_hotfix_errors = _read_json(args.pre_hotfix_errors)
    baseline_records = list(baseline_report.get("suggestions") or [])
    baseline_summary = dict(baseline_report.get("summary") or {})
    pre_records = list(pre_hotfix_report.get("suggestions") or [])
    pre_summary = dict(pre_hotfix_report.get("summary") or {})

    row_context_report = build_row_context_report(
        dataset_dir=args.dataset_dir,
        include_samples=args.include_sample,
        exclude_samples=args.exclude_sample,
        include_outlier=args.include_outlier,
    )
    contexts = row_context_report["row_contexts"]
    context_by_row = {_context_key(item): item for item in contexts}
    dictionary_entries = statement_concept_candidate_entries()
    row_order_report = build_statement_row_order_alignment_report(contexts)
    alignment_by_row = row_order_alignment_index(row_order_report["row_order_alignments"])

    post_records = []
    for record in baseline_records:
        if args.debug_label and args.debug_label.lower() not in str(record.get("pdf_label") or "").lower():
            continue
        context = _record_context(record, context_by_row)
        post_records.append(
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
    facts_by_sample = {
        str(sample.get("sample_id")): load_sample_replay_data(
            dataset_dir=args.dataset_dir,
            sample_id=str(sample.get("sample_id")),
            company_name=str(sample.get("company_name") or sample.get("sample_id")),
        ).get("facts")
        or []
        for sample in samples
        if sample.get("status") == "included"
    }
    evaluated = _evaluate_records(post_records, row_values=row_values, facts_by_sample=facts_by_sample)
    pre_new = _newly_covered(baseline_records, pre_records)
    post_new = _newly_covered(baseline_records, evaluated)
    pre_new_eval = _eval_summary(pre_new)
    post_new_eval = _eval_summary(post_new)
    comparison_lists = _comparison_lists(pre_new=pre_new, post_new=post_new)
    blocked = _blocked_candidates(evaluated)
    false_positive_analysis = _false_positive_analysis(pre_new, pre_hotfix_errors)

    post_summary = summarize_mapper_records(evaluated, samples=samples, rules=rules, generated_at=generated_at)
    post_summary["feature"] = "18E-B-2-hotfix-1"
    post_summary["local_xbrl_evaluation"] = _eval_summary(evaluated)
    post_summary["newly_covered_count"] = len(post_new)
    post_summary["newly_covered_labels"] = _top_labels(post_new, limit=50)
    post_summary["new_dictionary_row_order_precision"] = post_new_eval
    post_summary["blocked_candidate_count"] = len(blocked)
    post_summary["blocked_candidate_reason_counts"] = [
        {"blocking_reason": reason, "count": count}
        for reason, count in Counter(reason for item in blocked for reason in item.get("blocked_candidate_reasons", [])).most_common(40)
    ]
    post_summary["safe_for_auto_apply_count"] = 0
    post_summary["explicit_auto_apply_statement"] = "No #18E-B-2-hotfix-1 suggestion is safe for auto-apply; human review remains required."

    total = int(post_summary.get("total_pdf_row_value_observations") or 0)
    baseline_touched = _touched_summary(baseline_summary)
    pre_touched = _touched_summary(pre_summary)
    post_touched = _touched_summary(post_summary)
    baseline_precision = (baseline_summary.get("local_xbrl_evaluation") or {}).get("precision_on_evaluable")
    pre_precision = (pre_summary.get("local_xbrl_evaluation") or {}).get("precision_on_evaluable")
    post_precision = post_summary["local_xbrl_evaluation"].get("precision_on_evaluable")
    recommendation = _recommend_next(
        _safe_rate(post_touched, total),
        post_new_eval.get("precision_on_evaluable"),
        pre_new_eval.get("precision_on_evaluable"),
    )
    post_summary["recommendation"] = recommendation

    run_metadata = {
        "feature": "18E-B-2-hotfix-1",
        "generated_at": generated_at,
        "read_only": True,
        "offline_only": True,
        "dataset_dir": str(args.dataset_dir),
        "hardened_rulebook": str(args.hardened_rulebook),
        "baseline_report": str(args.baseline_report),
        "pre_hotfix_report": str(args.pre_hotfix_report),
        "pre_hotfix_errors": str(args.pre_hotfix_errors),
        "include_samples": list(args.include_sample),
        "exclude_samples": list(args.exclude_sample),
        "include_outlier": args.include_outlier,
        "debug_label": args.debug_label,
        **SAFETY,
    }

    tightened_report = {
        "run_metadata": run_metadata,
        "summary": post_summary,
        "suggestions": evaluated,
    }
    summary_report = {
        "run_metadata": run_metadata,
        "summary": {
            "baseline": {
                "touched_suggestions_count": baseline_touched,
                "touched_coverage_rate": _safe_rate(baseline_touched, total),
                "no_match_count": baseline_summary.get("no_match_count"),
                "precision_on_evaluable": baseline_precision,
            },
            "pre_hotfix": {
                "touched_suggestions_count": pre_touched,
                "touched_coverage_rate": _safe_rate(pre_touched, total),
                "no_match_count": pre_summary.get("no_match_count"),
                "precision_on_evaluable": pre_precision,
                "new_candidate_eval": pre_new_eval,
            },
            "post_hotfix": {
                "touched_suggestions_count": post_touched,
                "touched_coverage_rate": _safe_rate(post_touched, total),
                "no_match_count": post_summary.get("no_match_count"),
                "precision_on_evaluable": post_precision,
                "new_candidate_eval": post_new_eval,
            },
            "new_candidate_precision": {
                "pre_hotfix": pre_new_eval.get("precision_on_evaluable"),
                "post_hotfix": post_new_eval.get("precision_on_evaluable"),
            },
            "correct_candidates_preserved_count": len(comparison_lists["correct_candidates_preserved"]),
            "correct_candidates_lost_count": len(comparison_lists["correct_candidates_lost"]),
            "false_positives_removed_count": len(comparison_lists["false_positives_removed"]),
            "false_positives_remaining_count": len(comparison_lists["false_positives_remaining"]),
            "blocked_candidate_count": len(blocked),
            "top_blocking_reasons": post_summary["blocked_candidate_reason_counts"],
            "top_post_hotfix_no_match_labels": _top_labels([item for item in evaluated if item.get("confidence_bucket") == "no_match"], limit=60),
            "recommendation": recommendation,
            "safety": SAFETY,
        },
        **comparison_lists,
    }
    false_positive_report = {
        "run_metadata": run_metadata,
        **false_positive_analysis,
    }
    blocked_report = {
        "run_metadata": run_metadata,
        "summary": {
            "blocked_candidate_count": len(blocked),
            "top_blocking_reasons": post_summary["blocked_candidate_reason_counts"],
            "labels_most_affected": _top_labels(blocked, limit=60),
            "safety": SAFETY,
        },
        "blocked_candidates": blocked,
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
        "tightened_json": output / "rulebook_mapper_dictionary_tightened_18e_b2_hotfix_1.json",
        "tightened_md": output / "rulebook_mapper_dictionary_tightened_18e_b2_hotfix_1.md",
        "summary_json": output / "rulebook_mapper_dictionary_tightening_summary_18e_b2_hotfix_1.json",
        "summary_md": output / "rulebook_mapper_dictionary_tightening_summary_18e_b2_hotfix_1.md",
        "false_positive_json": output / "rulebook_mapper_dictionary_false_positive_analysis_18e_b2_hotfix_1.json",
        "false_positive_md": output / "rulebook_mapper_dictionary_false_positive_analysis_18e_b2_hotfix_1.md",
        "blocked_json": output / "rulebook_mapper_dictionary_blocked_candidates_18e_b2_hotfix_1.json",
        "blocked_md": output / "rulebook_mapper_dictionary_blocked_candidates_18e_b2_hotfix_1.md",
        "no_match_json": output / "rulebook_mapper_dictionary_no_match_18e_b2_hotfix_1.json",
        "no_match_md": output / "rulebook_mapper_dictionary_no_match_18e_b2_hotfix_1.md",
    }
    _write_json(paths["tightened_json"], tightened_report)
    paths["tightened_md"].write_text(_render_table_report("Dictionary/Row-Order Tightened Mapper - Feature #18E-B-2-hotfix-1", tightened_report, "suggestions"), encoding="utf-8")
    _write_json(paths["summary_json"], summary_report)
    paths["summary_md"].write_text(_render_summary_markdown(summary_report), encoding="utf-8")
    _write_json(paths["false_positive_json"], false_positive_report)
    paths["false_positive_md"].write_text(_render_table_report("Dictionary/Row-Order False-Positive Analysis - Feature #18E-B-2-hotfix-1", false_positive_report, "false_positive_rows"), encoding="utf-8")
    _write_json(paths["blocked_json"], blocked_report)
    paths["blocked_md"].write_text(_render_table_report("Dictionary/Row-Order Blocked Candidates - Feature #18E-B-2-hotfix-1", blocked_report, "blocked_candidates"), encoding="utf-8")
    _write_json(paths["no_match_json"], no_match_report)
    paths["no_match_md"].write_text(_render_table_report("Dictionary/Row-Order No-Match Rows - Feature #18E-B-2-hotfix-1", no_match_report, "no_match"), encoding="utf-8")

    print("Feature #18E-B-2-hotfix-1 tightened mapper reports written:")
    for name, path in paths.items():
        print(f"- {name}: {path}")
    print("")
    print("Tightening comparison:")
    print(f"- pre_hotfix_touched_coverage_rate: {_safe_rate(pre_touched, total)}")
    print(f"- post_hotfix_touched_coverage_rate: {_safe_rate(post_touched, total)}")
    print(f"- pre_hotfix_new_candidate_precision: {pre_new_eval.get('precision_on_evaluable')}")
    print(f"- post_hotfix_new_candidate_precision: {post_new_eval.get('precision_on_evaluable')}")
    print(f"- false_positives_removed_count: {len(comparison_lists['false_positives_removed'])}")
    print(f"- blocked_candidate_count: {len(blocked)}")
    print(f"- safe_for_auto_apply_count: {post_summary['safe_for_auto_apply_count']}")
    print(f"- next: {recommendation['recommended_next_feature']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
