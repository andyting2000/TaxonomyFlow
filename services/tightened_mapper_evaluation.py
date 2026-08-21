"""Offline tightened mapper precision and conflict-risk evaluation for Feature #18E-D."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label, normalize_label
from services.pdf_xbrl_rulebook_mapper import load_pdf_row_observations
from services.pdf_xbrl_rulebook_replay import (
    FALSE_POSITIVE_STATUSES,
    GOOD_STATUSES,
    NOT_EVALUABLE_STATUSES,
    evaluate_prediction,
    load_sample_replay_data,
)


EVALUATION_STATUSES = {
    "exact_qname_value_period_match",
    "qname_value_match_period_uncertain",
    "qname_exists_but_value_mismatch",
    "value_exists_but_different_qname",
    "predicted_qname_not_found_in_xbrl",
    "ambiguous_xbrl_support",
    "blocked_candidate_would_have_matched",
    "blocked_candidate_correctly_blocked",
    "no_xbrl_support",
    "not_evaluable",
}

SOURCE_BUCKETS = [
    "pdf_xbrl_rulebook",
    "context_template",
    "statement_template",
    "note_link_template",
    "combined_rulebook_template",
    "dictionary",
    "row_order",
    "dictionary_row_order",
    "context_dictionary",
    "unknown",
]

STATEMENT_FAMILY_BUCKETS = [
    "Statement of Financial Position",
    "Profit or Loss / Comprehensive Income",
    "Cash Flows",
    "Changes in Equity",
    "Notes",
    "Unknown",
]

LABEL_FAMILY_BUCKETS = [
    "revenue",
    "other income",
    "expenses",
    "tax",
    "profit/loss result",
    "receivables",
    "payables",
    "cash/bank",
    "PPE",
    "borrowings/loans",
    "equity",
    "totals/subtotals",
    "cash-flow movement",
    "note-detail",
    "unknown",
]

SAFETY = {
    "external_llm_called": False,
    "external_provider_called": False,
    "azure_di_live_call_made": False,
    "database_mutated": False,
    "production_behavior_changed": False,
    "production_mapper_integrated": False,
    "api_changed": False,
    "ui_changed": False,
    "ai_suggestion_table_written": False,
    "auto_applied": False,
    "auto_accept_recommended": False,
    "auto_reject_recommended": False,
    "confirmed_tag_id_mutated": False,
    "confirmed_tag_id_automation_recommended": False,
    "xbrl_generated": False,
    "arelle_run": False,
    "source_xml_included_in_reports": False,
}

FORBIDDEN_REPORT_KEYS = {
    "raw_xml",
    "auditor_xml",
    "xml_text",
    "parsed_xml",
    "xbrl_facts",
    "facts",
    "gold",
    "gold_answer",
    "correct_qname",
    "correct_concept_qname",
    "correct_template_field_id",
    "expected_qname",
    "target_correct_qname",
    "benchmark_label",
    "evaluation_label",
    "competing_xbrl_facts",
    "matched_xbrl_fact_id",
    "matched_xbrl_value",
    "matched_xbrl_context",
    "matched_xbrl_qname",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path | None) -> dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")


def safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def row_key(record: Mapping[str, Any]) -> tuple[str, str]:
    return str(record.get("sample_id") or ""), str(record.get("pdf_row_id") or record.get("row_id") or "")


def _context(record: Mapping[str, Any]) -> Mapping[str, Any]:
    context = record.get("row_context")
    return context if isinstance(context, Mapping) else {}


def _field_text(record: Mapping[str, Any], *fields: str) -> str:
    values: list[str] = []
    context = _context(record)
    for field in fields:
        if field in context:
            values.append(str(context.get(field) or ""))
        values.append(str(record.get(field) or ""))
    return " ".join(values).lower()


def candidate_source(record: Mapping[str, Any]) -> str:
    raw = str(record.get("candidate_generation_method") or record.get("suggestion_source") or "").strip()
    normalized = raw.lower()
    mapping = {
        "pdf_xbrl_rulebook": "pdf_xbrl_rulebook",
        "context_optimized": "context_template",
        "context_template": "context_template",
        "statement_template": "statement_template",
        "statement_template_pattern": "statement_template",
        "note_link_template": "note_link_template",
        "note_link_template_pattern": "note_link_template",
        "combined_rulebook_template": "combined_rulebook_template",
        "statement_concept_dictionary": "dictionary",
        "dictionary": "dictionary",
        "row_order_alignment": "row_order",
        "row_order": "row_order",
        "dictionary_row_order": "dictionary_row_order",
        "context_dictionary": "context_dictionary",
    }
    if normalized in mapping:
        return mapping[normalized]
    if record.get("dictionary_entry_id") and record.get("row_order_alignment_id"):
        return "dictionary_row_order"
    if record.get("dictionary_entry_id"):
        return "dictionary"
    if record.get("row_order_alignment_id"):
        return "row_order"
    if record.get("note_link"):
        return "note_link_template"
    if record.get("statement_template_optimization_applied"):
        return "statement_template"
    if record.get("context_optimization_applied"):
        return "context_template"
    return "unknown"


def statement_family_bucket(record: Mapping[str, Any]) -> str:
    context = _context(record)
    family = str(context.get("statement_family") or record.get("pdf_statement_family") or "").lower()
    section = str(context.get("section_block") or "").lower()
    title = str(context.get("statement_title") or record.get("pdf_statement_type") or "").lower()
    if family in {"financial_position", "balance_sheet", "statement_of_financial_position"}:
        return "Statement of Financial Position"
    if family in {"income_statement", "profit_loss", "profit_or_loss", "comprehensive_income"}:
        return "Profit or Loss / Comprehensive Income"
    if family in {"cash_flow", "cash_flows", "statement_of_cash_flows"}:
        return "Cash Flows"
    if family == "changes_in_equity":
        return "Changes in Equity"
    if family == "notes" or section.startswith("notes") or context.get("is_notes_context"):
        return "Notes"
    if "financial position" in title:
        return "Statement of Financial Position"
    if "cash flow" in title:
        return "Cash Flows"
    if "equity" in title:
        return "Changes in Equity"
    if "profit" in title or "comprehensive" in title or "income" in title:
        return "Profit or Loss / Comprehensive Income"
    if "notes" in title:
        return "Notes"
    return "Unknown"


def label_family_bucket(record: Mapping[str, Any]) -> str:
    context = _context(record)
    label = normalize_label(record.get("normalized_label") or record.get("pdf_label") or "")
    qname = str(record.get("predicted_qname") or "").lower()
    text = f"{label} {qname}"
    row_role = str(context.get("row_role") or "").lower()
    section = str(context.get("section_block") or "").lower()
    if row_role == "note_detail" or section.startswith("notes") or context.get("is_notes_context"):
        return "note-detail"
    if any(term in text for term in ("revenue", "turnover", "sales")):
        return "revenue"
    if "other income" in text or "interest income" in text or "gain" in text:
        return "other income"
    if "tax" in text or "taxation" in text:
        return "tax"
    if "cash flow" in text or "operating activities" in text or "investing activities" in text or "financing activities" in text:
        return "cash-flow movement"
    if "profit" in text or "loss" in text or "comprehensive income" in text:
        return "profit/loss result"
    if "receivable" in text or "receivables" in text:
        return "receivables"
    if "payable" in text or "payables" in text or "accrual" in text:
        return "payables"
    if "cash" in text or "bank" in text:
        return "cash/bank"
    if "property plant" in text or "ppe" in text or "plantandequipment" in text:
        return "PPE"
    if "borrow" in text or "loan" in text or "financing" in text:
        return "borrowings/loans"
    if "equity" in text or "share capital" in text or "retained" in text:
        return "equity"
    if "total" in label or "subtotal" in label or label.startswith("net "):
        return "totals/subtotals"
    if any(term in text for term in ("expense", "expenses", "fee", "remuneration", "wages", "salaries", "charges", "depreciation")):
        return "expenses"
    return "unknown"


def context_confidence_bucket(record: Mapping[str, Any]) -> str:
    value = _context(record).get("context_confidence")
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return "unknown"
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.6:
        return "medium"
    if confidence > 0:
        return "low"
    return "unknown"


def row_role_bucket(record: Mapping[str, Any]) -> str:
    return str(_context(record).get("row_role") or record.get("row_role") or "unknown")


def is_good_status(status: Any, *, strict_period_match: bool = False) -> bool:
    if strict_period_match:
        return status == "exact_qname_value_period_match"
    return str(status) in GOOD_STATUSES


def is_false_positive_status(status: Any, *, strict_period_match: bool = False) -> bool:
    if strict_period_match and status == "qname_value_match_period_uncertain":
        return True
    return str(status) in FALSE_POSITIVE_STATUSES


def classify_evaluation_result(status: Any, *, strict_period_match: bool = False) -> dict[str, Any]:
    value = str(status or "not_evaluable")
    if is_good_status(value, strict_period_match=strict_period_match):
        risk = "low" if value == "exact_qname_value_period_match" else "medium"
        return {
            "evaluation_status": value,
            "result_class": "match",
            "risk_level": risk,
            "counts_as_match": True,
            "counts_as_false_positive": False,
            "counts_as_ambiguous": False,
            "counts_as_not_evaluable": False,
        }
    if is_false_positive_status(value, strict_period_match=strict_period_match):
        risk = "critical" if value == "predicted_qname_not_found_in_xbrl" else "high"
        return {
            "evaluation_status": value,
            "result_class": "false_positive",
            "risk_level": risk,
            "counts_as_match": False,
            "counts_as_false_positive": True,
            "counts_as_ambiguous": False,
            "counts_as_not_evaluable": False,
        }
    if value == "ambiguous_xbrl_support":
        return {
            "evaluation_status": value,
            "result_class": "ambiguous",
            "risk_level": "medium",
            "counts_as_match": False,
            "counts_as_false_positive": False,
            "counts_as_ambiguous": True,
            "counts_as_not_evaluable": False,
        }
    return {
        "evaluation_status": value,
        "result_class": "not_evaluable",
        "risk_level": "medium" if value in NOT_EVALUABLE_STATUSES else "high",
        "counts_as_match": False,
        "counts_as_false_positive": False,
        "counts_as_ambiguous": False,
        "counts_as_not_evaluable": True,
    }


def classify_blocked_candidate(status: Any, *, strict_period_match: bool = False) -> str:
    if is_good_status(status, strict_period_match=strict_period_match):
        return "overblocked_true_positive"
    if is_false_positive_status(status, strict_period_match=strict_period_match):
        return "correctly_blocked_false_positive"
    if str(status) == "ambiguous_xbrl_support":
        return "ambiguous"
    return "not_evaluable"


def evaluate_candidate_record(
    record: Mapping[str, Any],
    row: PdfRowValue,
    facts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return evaluate_prediction(record, row, facts)


def evaluate_mapper_records(
    records: Sequence[Mapping[str, Any]],
    *,
    row_values: Sequence[PdfRowValue],
    facts_by_sample: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[dict[str, Any]]:
    row_by_id = {(row.sample_id, row.pdf_row_id): row for row in row_values}
    evaluated = []
    for record in records:
        row = row_by_id.get(row_key(record))
        if row is None:
            item = dict(record)
            item.update({"evaluation_status": "not_evaluable", "xbrl_support_status": "row_value_not_found"})
            evaluated.append(item)
            continue
        evaluated.append(evaluate_candidate_record(record, row, facts_by_sample.get(row.sample_id) or []))
    return evaluated


def load_local_evaluation_evidence(
    *,
    dataset_dir: str | Path,
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    loaded = load_pdf_row_observations(dataset_dir=dataset_dir)
    row_values = list(loaded.get("row_values") or [])
    samples = list(loaded.get("samples") or [])
    wanted_samples = {str(record.get("sample_id")) for record in records if record.get("sample_id")}
    facts_by_sample: dict[str, Sequence[Mapping[str, Any]]] = {}
    for sample in samples:
        sample_id = str(sample.get("sample_id") or "")
        if not sample_id or sample.get("status") != "included":
            continue
        if wanted_samples and sample_id not in wanted_samples:
            continue
        facts_by_sample[sample_id] = load_sample_replay_data(
            dataset_dir=dataset_dir,
            sample_id=sample_id,
            company_name=str(sample.get("company_name") or sample_id),
        ).get("facts") or []
    return {"row_values": row_values, "samples": samples, "facts_by_sample": facts_by_sample}


def _status_metrics(records: Sequence[Mapping[str, Any]], *, strict_period_match: bool = False) -> dict[str, int]:
    predictions = [record for record in records if record.get("predicted_qname")]
    exact = sum(1 for record in predictions if record.get("evaluation_status") == "exact_qname_value_period_match")
    period_uncertain = sum(1 for record in predictions if record.get("evaluation_status") == "qname_value_match_period_uncertain")
    good = sum(1 for record in predictions if is_good_status(record.get("evaluation_status"), strict_period_match=strict_period_match))
    false = sum(1 for record in predictions if is_false_positive_status(record.get("evaluation_status"), strict_period_match=strict_period_match))
    ambiguous = sum(1 for record in predictions if record.get("evaluation_status") == "ambiguous_xbrl_support")
    not_evaluable = sum(1 for record in predictions if str(record.get("evaluation_status")) in NOT_EVALUABLE_STATUSES)
    return {
        "candidate_count": len(predictions),
        "exact_matches": exact,
        "period_uncertain_matches": period_uncertain,
        "qname_value_matches": good,
        "false_positive_count": false,
        "ambiguous_count": ambiguous,
        "not_evaluable_count": not_evaluable,
    }


def metrics_for_records(
    records: Sequence[Mapping[str, Any]],
    *,
    total_observations: int | None = None,
    strict_period_match: bool = False,
) -> dict[str, Any]:
    total = len(records) if total_observations is None else int(total_observations)
    status_counts = Counter(str(record.get("evaluation_status") or "unknown") for record in records)
    confidence_counts = Counter(str(record.get("confidence_bucket") or "unknown") for record in records)
    source_counts = Counter(candidate_source(record) for record in records if record.get("predicted_qname"))
    metrics = _status_metrics(records, strict_period_match=strict_period_match)
    good = metrics["qname_value_matches"]
    false = metrics["false_positive_count"]
    safe_for_auto_apply_count = sum(1 for record in records if record.get("safe_for_auto_apply") is True)
    blocked_rows = sum(1 for record in records if record.get("blocked_dictionary_candidate") or record.get("blocked_row_order_candidate"))
    return {
        "total_observations": total,
        "candidate_count": metrics["candidate_count"],
        "touched_rows": metrics["candidate_count"],
        "touched_coverage_rate": safe_rate(metrics["candidate_count"], total),
        "exact_matches": metrics["exact_matches"],
        "period_uncertain_matches": metrics["period_uncertain_matches"],
        "qname_value_matches": good,
        "false_positive_count": false,
        "ambiguous_count": metrics["ambiguous_count"],
        "not_evaluable_count": metrics["not_evaluable_count"],
        "precision_on_evaluable": safe_rate(good, good + false),
        "evaluation_status_counts": dict(sorted(status_counts.items())),
        "confidence_bucket_counts": dict(sorted(confidence_counts.items())),
        "candidate_source_counts": dict(sorted(source_counts.items())),
        "blocked_candidate_rows": blocked_rows,
        "safe_for_auto_apply_count": safe_for_auto_apply_count,
        "requires_human_review_count": sum(1 for record in records if record.get("requires_human_review") is not False),
        "strict_period_match": strict_period_match,
    }


def _top_labels(records: Sequence[Mapping[str, Any]], *, limit: int = 20) -> list[dict[str, Any]]:
    counter = Counter(str(record.get("normalized_label") or canonical_label(record.get("pdf_label"))) for record in records)
    return [{"normalized_label": label, "count": count} for label, count in counter.most_common(limit) if label]


def _top_statuses(records: Sequence[Mapping[str, Any]], *, limit: int = 12) -> list[dict[str, Any]]:
    counter = Counter(str(record.get("evaluation_status") or "unknown") for record in records)
    return [{"evaluation_status": status, "count": count} for status, count in counter.most_common(limit)]


def _safe_labels(records: Sequence[Mapping[str, Any]], *, strict_period_match: bool = False, limit: int = 20) -> list[dict[str, Any]]:
    by_label: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        if record.get("predicted_qname"):
            by_label[str(record.get("normalized_label") or canonical_label(record.get("pdf_label")))].append(record)
    rows = []
    for label, items in by_label.items():
        good = sum(1 for item in items if is_good_status(item.get("evaluation_status"), strict_period_match=strict_period_match))
        false = sum(1 for item in items if is_false_positive_status(item.get("evaluation_status"), strict_period_match=strict_period_match))
        if good and not false:
            rows.append({"normalized_label": label, "qname_value_matches": good, "false_positive_count": false})
    return sorted(rows, key=lambda item: (-int(item["qname_value_matches"]), str(item["normalized_label"])))[:limit]


def _risky_labels(records: Sequence[Mapping[str, Any]], *, strict_period_match: bool = False, limit: int = 20) -> list[dict[str, Any]]:
    risky = [
        record
        for record in records
        if is_false_positive_status(record.get("evaluation_status"), strict_period_match=strict_period_match)
        or record.get("evaluation_status") == "ambiguous_xbrl_support"
    ]
    return _top_labels(risky, limit=limit)


def group_risk_level(metrics: Mapping[str, Any]) -> str:
    precision = metrics.get("precision_on_evaluable")
    false_count = int(metrics.get("false_positive_count") or 0)
    ambiguous = int(metrics.get("ambiguous_count") or 0)
    not_eval = int(metrics.get("not_evaluable_count") or 0)
    candidate_count = int(metrics.get("candidate_count") or 0)
    if not candidate_count:
        return "medium" if int(metrics.get("blocked_candidate_rows") or 0) else "low"
    if false_count >= 5 and (precision is None or precision < 0.65):
        return "critical"
    if false_count and (precision is None or precision < 0.8):
        return "high"
    if false_count or ambiguous or not_eval or (precision is not None and precision < 0.95):
        return "medium"
    return "low"


def recommendation_for_group(
    group_name: str,
    metrics: Mapping[str, Any],
    *,
    group_type: str,
) -> str:
    precision = metrics.get("precision_on_evaluable")
    false_count = int(metrics.get("false_positive_count") or 0)
    candidate_count = int(metrics.get("candidate_count") or 0)
    name = str(group_name).lower()
    if "note" in name:
        return "needs_note_link"
    if group_type == "candidate_source" and group_name in {"dictionary", "row_order", "dictionary_row_order", "context_dictionary"}:
        if false_count:
            return "tighten"
        return "keep_review_required"
    if candidate_count and (precision is None or precision < 0.5) and false_count:
        return "disable"
    if candidate_count and (precision is None or precision < 0.75):
        return "tighten"
    if false_count:
        return "keep_review_required"
    if group_name == "Unknown":
        return "needs_section_context"
    if candidate_count and precision is not None and precision >= 0.95:
        return "keep"
    return "keep_review_required"


def _group_summary(
    group_name: str,
    records: Sequence[Mapping[str, Any]],
    *,
    group_type: str,
    total_observations: int | None = None,
    strict_period_match: bool = False,
) -> dict[str, Any]:
    metrics = metrics_for_records(
        records,
        total_observations=len(records) if total_observations is None else total_observations,
        strict_period_match=strict_period_match,
    )
    false_records = [record for record in records if is_false_positive_status(record.get("evaluation_status"), strict_period_match=strict_period_match)]
    ambiguous_records = [record for record in records if record.get("evaluation_status") == "ambiguous_xbrl_support"]
    metrics.update(
        {
            "group_type": group_type,
            "name": group_name,
            "observations": len(records),
            "statement_families": [
                {"statement_family": family, "count": count}
                for family, count in Counter(statement_family_bucket(record) for record in records).most_common()
            ],
            "top_labels": _top_labels(records),
            "safe_labels": _safe_labels(records, strict_period_match=strict_period_match),
            "risky_labels": _risky_labels(records, strict_period_match=strict_period_match),
            "common_errors": _top_statuses([*false_records, *ambiguous_records]),
        }
    )
    metrics["risk_level"] = group_risk_level(metrics)
    metrics["recommendation"] = recommendation_for_group(group_name, metrics, group_type=group_type)
    return metrics


def build_source_metrics(records: Sequence[Mapping[str, Any]], *, strict_period_match: bool = False) -> list[dict[str, Any]]:
    predictions = [record for record in records if record.get("predicted_qname")]
    by_source: dict[str, list[Mapping[str, Any]]] = {source: [] for source in SOURCE_BUCKETS}
    for record in predictions:
        by_source.setdefault(candidate_source(record), []).append(record)
    return [
        _group_summary(source, by_source.get(source, []), group_type="candidate_source", strict_period_match=strict_period_match)
        for source in SOURCE_BUCKETS
    ]


def build_statement_family_metrics(records: Sequence[Mapping[str, Any]], *, strict_period_match: bool = False) -> list[dict[str, Any]]:
    by_family: dict[str, list[Mapping[str, Any]]] = {family: [] for family in STATEMENT_FAMILY_BUCKETS}
    for record in records:
        by_family.setdefault(statement_family_bucket(record), []).append(record)
    return [
        _group_summary(family, by_family.get(family, []), group_type="statement_family", strict_period_match=strict_period_match)
        for family in STATEMENT_FAMILY_BUCKETS
    ]


def build_label_family_metrics(records: Sequence[Mapping[str, Any]], *, strict_period_match: bool = False) -> list[dict[str, Any]]:
    by_family: dict[str, list[Mapping[str, Any]]] = {family: [] for family in LABEL_FAMILY_BUCKETS}
    for record in records:
        by_family.setdefault(label_family_bucket(record), []).append(record)
    return [
        _group_summary(family, by_family.get(family, []), group_type="label_family", strict_period_match=strict_period_match)
        for family in LABEL_FAMILY_BUCKETS
    ]


def _generic_group_metrics(
    records: Sequence[Mapping[str, Any]],
    *,
    group_type: str,
    key_fn,
    strict_period_match: bool = False,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        grouped[str(key_fn(record) or "unknown")].append(record)
    return [
        _group_summary(name, items, group_type=group_type, strict_period_match=strict_period_match)
        for name, items in sorted(grouped.items())
    ]


def _blocked_candidate_descriptors(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    output = []
    for source, field in (("dictionary", "blocked_dictionary_candidate"), ("row_order", "blocked_row_order_candidate")):
        candidate = record.get(field)
        if not isinstance(candidate, Mapping) or not candidate.get("target_qname"):
            continue
        output.append(
            {
                "blocked_source": source,
                "candidate_id": candidate.get("dictionary_id") or candidate.get("row_order_id"),
                "target_qname": candidate.get("target_qname"),
                "target_concept_label": candidate.get("target_concept_label"),
                "concept_family": candidate.get("concept_family"),
                "confidence_score": candidate.get("confidence_score"),
                "blocking_reasons": list(candidate.get("blocking_reasons") or []),
                "match_reasons": list(candidate.get("match_reasons") or []),
            }
        )
    return output


def analyze_blocked_candidates(
    records: Sequence[Mapping[str, Any]],
    *,
    row_values: Sequence[PdfRowValue],
    facts_by_sample: Mapping[str, Sequence[Mapping[str, Any]]],
    blocked_report: Mapping[str, Any] | None = None,
    strict_period_match: bool = False,
) -> dict[str, Any]:
    row_by_id = {(row.sample_id, row.pdf_row_id): row for row in row_values}
    rows = []
    blocked_row_count = 0
    for record in records:
        descriptors = _blocked_candidate_descriptors(record)
        if not descriptors:
            continue
        blocked_row_count += 1
        row = row_by_id.get(row_key(record))
        for descriptor in descriptors:
            prediction = dict(record)
            prediction.update(
                {
                    "predicted_qname": descriptor["target_qname"],
                    "predicted_concept_label": descriptor.get("target_concept_label"),
                    "confidence_bucket": "review_required",
                    "candidate_generation_method": descriptor["blocked_source"],
                }
            )
            if row is None:
                evaluated = dict(prediction, evaluation_status="not_evaluable", xbrl_support_status="row_value_not_found")
            else:
                evaluated = evaluate_candidate_record(prediction, row, facts_by_sample.get(row.sample_id) or [])
            outcome = classify_blocked_candidate(evaluated.get("evaluation_status"), strict_period_match=strict_period_match)
            rows.append(
                {
                    "sample_id": record.get("sample_id"),
                    "pdf_row_id": record.get("pdf_row_id"),
                    "pdf_label": record.get("pdf_label"),
                    "normalized_label": record.get("normalized_label") or canonical_label(record.get("pdf_label")),
                    "statement_family": statement_family_bucket(record),
                    "label_family": label_family_bucket(record),
                    "row_role": row_role_bucket(record),
                    "blocked_source": descriptor["blocked_source"],
                    "candidate_id": descriptor.get("candidate_id"),
                    "target_qname": descriptor.get("target_qname"),
                    "concept_family": descriptor.get("concept_family"),
                    "confidence_score": descriptor.get("confidence_score"),
                    "evaluation_status": evaluated.get("evaluation_status"),
                    "blocked_candidate_classification": outcome,
                    "risk_level": "medium" if outcome == "overblocked_true_positive" else "low" if outcome == "correctly_blocked_false_positive" else "medium",
                    "blocking_reasons": descriptor.get("blocking_reasons") or record.get("blocked_candidate_reasons") or [],
                }
            )
    class_counts = Counter(row["blocked_candidate_classification"] for row in rows)
    overblocked = [row for row in rows if row["blocked_candidate_classification"] == "overblocked_true_positive"]
    correctly_blocked = [row for row in rows if row["blocked_candidate_classification"] == "correctly_blocked_false_positive"]
    source_count = ((blocked_report or {}).get("summary") or {}).get("blocked_candidate_count")
    return {
        "summary": {
            "blocked_candidate_rows": blocked_row_count,
            "source_report_blocked_candidate_rows": source_count,
            "blocked_candidate_opportunities": len(rows),
            "correctly_blocked_false_positive_count": len(correctly_blocked),
            "overblocked_true_positive_count": len(overblocked),
            "ambiguous_count": class_counts.get("ambiguous", 0),
            "not_evaluable_count": class_counts.get("not_evaluable", 0),
            "classification_counts": dict(sorted(class_counts.items())),
            "top_overblocking_reasons": [
                {"blocking_reason": reason, "count": count}
                for reason, count in Counter(reason for row in overblocked for reason in row.get("blocking_reasons") or []).most_common(20)
            ],
            "top_useful_rules_lost": [
                {"target_qname": qname, "count": count}
                for qname, count in Counter(str(row.get("target_qname") or "") for row in overblocked).most_common(20)
                if qname
            ],
            "recommendations_to_recover_lost_true_positives": blocked_recovery_recommendations(overblocked),
            "safety": SAFETY,
        },
        "blocked_candidates": sanitize_report_value(rows),
    }


def blocked_recovery_recommendations(overblocked_rows: Sequence[Mapping[str, Any]]) -> list[str]:
    if not overblocked_rows:
        return ["No locally supported blocked true positives were found; keep current blocking thresholds."]
    reasons = Counter(reason for row in overblocked_rows for reason in row.get("blocking_reasons") or [])
    recommendations = []
    if any("row_order" in reason for reason in reasons):
        recommendations.append("Recover row-order true positives only when previous/next anchors and statement family both agree.")
    if any("dictionary" in reason for reason in reasons):
        recommendations.append("Recover dictionary true positives through exact label plus section-block confirmation, not broad aliases.")
    if any("note" in reason for reason in reasons):
        recommendations.append("Recover note-detail true positives only after note-link confirmation is present.")
    if not recommendations:
        recommendations.append("Recover overblocked true positives with a dedicated hotfix and source-specific regression cases.")
    return recommendations


def readiness_entry(group: Mapping[str, Any]) -> dict[str, Any]:
    precision = group.get("precision_on_evaluable")
    candidate_count = int(group.get("candidate_count") or 0)
    false_count = int(group.get("false_positive_count") or 0)
    ambiguous = int(group.get("ambiguous_count") or 0)
    not_eval = int(group.get("not_evaluable_count") or 0)
    name = str(group.get("name") or "")
    group_type = str(group.get("group_type") or "")
    risk = str(group.get("risk_level") or group_risk_level(group))
    safe_to_upgrade = bool(candidate_count >= 5 and precision is not None and precision >= 0.95 and not false_count and not ambiguous and not not_eval)
    should_disable = bool(candidate_count and precision is not None and precision < 0.5 and false_count)
    needs_note = "note" in name.lower() or any("note" in str(item).lower() for item in group.get("common_errors") or [])
    manual_dictionary_review = group_type == "candidate_source" and name in {"dictionary", "row_order", "dictionary_row_order", "context_dictionary"}
    needs_more_context = bool(risk in {"high", "critical"} or ambiguous or not_eval or name == "Unknown")
    return {
        "group_type": group_type,
        "name": name,
        "candidate_count": candidate_count,
        "precision_on_evaluable": precision,
        "false_positive_count": false_count,
        "ambiguous_count": ambiguous,
        "not_evaluable_count": not_eval,
        "risk_level": risk,
        "safe_to_keep_as_review_required": not should_disable,
        "safe_to_upgrade_to_advisory_medium": safe_to_upgrade,
        "should_remain_review_required": not safe_to_upgrade or false_count > 0 or needs_more_context,
        "should_be_disabled": should_disable,
        "needs_more_context": needs_more_context,
        "needs_note_link": needs_note,
        "needs_manual_dictionary_review": manual_dictionary_review,
        "auto_apply_recommended": False,
        "confirmed_tag_id_automation_recommended": False,
        "recommendation": group.get("recommendation"),
    }


def build_readiness_matrix(
    *,
    source_metrics: Sequence[Mapping[str, Any]],
    statement_family_metrics: Sequence[Mapping[str, Any]],
    label_family_metrics: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    entries = [
        *(readiness_entry(group) for group in source_metrics),
        *(readiness_entry(group) for group in statement_family_metrics),
        *(readiness_entry(group) for group in label_family_metrics),
    ]
    return {
        "summary": {
            "entries": len(entries),
            "safe_to_upgrade_to_advisory_medium_count": sum(1 for entry in entries if entry["safe_to_upgrade_to_advisory_medium"]),
            "should_be_disabled_count": sum(1 for entry in entries if entry["should_be_disabled"]),
            "needs_more_context_count": sum(1 for entry in entries if entry["needs_more_context"]),
            "needs_note_link_count": sum(1 for entry in entries if entry["needs_note_link"]),
            "auto_apply_recommended": False,
            "confirmed_tag_id_automation_recommended": False,
            "explicit_no_auto_apply_boundary": "No #18E-D readiness entry recommends auto-apply or confirmed_tag_id automation; human review remains required.",
            "safety": SAFETY,
        },
        "matrix": entries,
    }


def recommend_next_feature(overall: Mapping[str, Any], blocked_summary: Mapping[str, Any], readiness_summary: Mapping[str, Any]) -> dict[str, Any]:
    precision = overall.get("precision_on_evaluable")
    coverage = overall.get("touched_coverage_rate") or 0.0
    overblocked = int(blocked_summary.get("overblocked_true_positive_count") or 0)
    disabled = int(readiness_summary.get("should_be_disabled_count") or 0)
    if precision is not None and precision < 0.7:
        feature = "Feature #18E-B-2-hotfix-2 - Disable noisy candidate families and tighten readiness thresholds."
        reason = "Overall local precision remains below 0.70 after tightening."
    elif overblocked >= 10:
        feature = "Feature #18E-D-hotfix-1 - Recover low-risk overblocked true positives with stricter evidence."
        reason = "Several blocked candidates would have matched local XBRL facts and should be recovered only through a targeted hotfix."
    elif coverage >= 0.65 and precision is not None and precision >= 0.9 and not disabled:
        feature = "Feature #18F-A - Design deterministic mapper orchestration, offline/mock only."
        reason = "Coverage and precision are high enough to design an offline/mock orchestration layer."
    elif precision is not None and precision >= 0.7 and 0.4 <= coverage <= 0.5:
        feature = "Feature #18E-B-3 - Add safer company-format template memory and note-detail mapping boundaries."
        reason = "Precision is acceptable for review-required suggestions, but coverage remains around 45%."
    else:
        feature = "Feature #18E-B-3 - Add safer company-format template memory and note-detail mapping boundaries."
        reason = "Coverage remains the dominant gap and further expansion should use safer template and note-detail boundaries."
    return {
        "recommended_next_feature": feature,
        "reason": reason,
        "basis": {
            "touched_coverage_rate": coverage,
            "precision_on_evaluable": precision,
            "overblocked_true_positive_count": overblocked,
            "should_be_disabled_count": disabled,
            "safe_for_auto_apply_count": overall.get("safe_for_auto_apply_count"),
        },
        "auto_apply_recommended": False,
        "confirmed_tag_id_automation_recommended": False,
    }


def sanitize_report_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        output = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_REPORT_KEYS:
                continue
            output[key] = sanitize_report_value(item)
        return output
    if isinstance(value, list):
        return [sanitize_report_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_report_value(item) for item in value]
    return value


def sanitized_record(record: Mapping[str, Any], *, strict_period_match: bool = False) -> dict[str, Any]:
    classification = classify_evaluation_result(record.get("evaluation_status"), strict_period_match=strict_period_match)
    return sanitize_report_value(
        {
            "sample_id": record.get("sample_id"),
            "company_name": record.get("company_name"),
            "pdf_row_id": record.get("pdf_row_id"),
            "pdf_label": record.get("pdf_label"),
            "normalized_label": record.get("normalized_label") or canonical_label(record.get("pdf_label")),
            "pdf_value": record.get("pdf_value"),
            "statement_family": statement_family_bucket(record),
            "label_family": label_family_bucket(record),
            "candidate_source": candidate_source(record),
            "raw_candidate_generation_method": record.get("candidate_generation_method"),
            "row_role": row_role_bucket(record),
            "section_block": _context(record).get("section_block"),
            "context_confidence_bucket": context_confidence_bucket(record),
            "predicted_qname": record.get("predicted_qname"),
            "predicted_concept_label": record.get("predicted_concept_label"),
            "confidence_bucket": record.get("confidence_bucket"),
            "rule_readiness": record.get("rule_readiness"),
            "matched_rule_id": record.get("matched_rule_id"),
            "dictionary_entry_id": record.get("dictionary_entry_id"),
            "row_order_alignment_id": record.get("row_order_alignment_id"),
            "evaluation_status": record.get("evaluation_status"),
            "xbrl_support_status": record.get("xbrl_support_status"),
            "error_reason": record.get("error_reason"),
            "risk_level": classification["risk_level"],
            "result_class": classification["result_class"],
            "blocking_reasons": record.get("blocking_reasons") or [],
            "ambiguity_reasons": record.get("ambiguity_reasons") or [],
            "blocked_candidate_reasons": record.get("blocked_candidate_reasons") or [],
            "has_blocked_dictionary_candidate": bool(record.get("blocked_dictionary_candidate")),
            "has_blocked_row_order_candidate": bool(record.get("blocked_row_order_candidate")),
            "requires_human_review": record.get("requires_human_review") is not False,
            "safe_for_auto_apply": False,
        }
    )


def build_tightened_mapper_reports(
    records: Sequence[Mapping[str, Any]],
    *,
    row_values: Sequence[PdfRowValue] = (),
    facts_by_sample: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    mapper_summary: Mapping[str, Any] | None = None,
    blocked_report: Mapping[str, Any] | None = None,
    alignment_report: Mapping[str, Any] | None = None,
    generated_at: str | None = None,
    strict_period_match: bool = False,
    include_not_evaluable: bool = False,
    debug_label: str | None = None,
) -> dict[str, Any]:
    wanted = normalize_label(debug_label) if debug_label else None
    input_records = [dict(record) for record in records if not wanted or wanted in normalize_label(record.get("pdf_label") or record.get("normalized_label") or "")]
    if row_values and facts_by_sample is not None:
        evaluated = evaluate_mapper_records(input_records, row_values=row_values, facts_by_sample=facts_by_sample)
    else:
        evaluated = input_records
    generated = generated_at or utc_now()
    overall = metrics_for_records(evaluated, strict_period_match=strict_period_match)
    source_metrics = build_source_metrics(evaluated, strict_period_match=strict_period_match)
    statement_metrics = build_statement_family_metrics(evaluated, strict_period_match=strict_period_match)
    label_metrics = build_label_family_metrics(evaluated, strict_period_match=strict_period_match)
    conflict_risk = {
        "risk_by_source": source_metrics,
        "risk_by_statement_family": statement_metrics,
        "risk_by_label_family": label_metrics,
        "risk_by_context_confidence": _generic_group_metrics(
            evaluated,
            group_type="context_confidence",
            key_fn=context_confidence_bucket,
            strict_period_match=strict_period_match,
        ),
        "risk_by_row_role": _generic_group_metrics(
            evaluated,
            group_type="row_role",
            key_fn=row_role_bucket,
            strict_period_match=strict_period_match,
        ),
        "remaining_false_positives": [
            sanitized_record(record, strict_period_match=strict_period_match)
            for record in evaluated
            if is_false_positive_status(record.get("evaluation_status"), strict_period_match=strict_period_match)
        ],
        "ambiguous_cases": [
            sanitized_record(record, strict_period_match=strict_period_match)
            for record in evaluated
            if record.get("evaluation_status") == "ambiguous_xbrl_support"
        ],
    }
    blocked_analysis = analyze_blocked_candidates(
        evaluated,
        row_values=row_values,
        facts_by_sample=facts_by_sample or {},
        blocked_report=blocked_report,
        strict_period_match=strict_period_match,
    )
    readiness = build_readiness_matrix(
        source_metrics=source_metrics,
        statement_family_metrics=statement_metrics,
        label_family_metrics=label_metrics,
    )
    recommendation = recommend_next_feature(overall, blocked_analysis["summary"], readiness["summary"])
    alignment_summary = alignment_report.get("summary") if isinstance(alignment_report, Mapping) else {}
    run_metadata = {
        "feature": "18E-D",
        "generated_at": generated,
        "read_only": True,
        "offline_only": True,
        "strict_period_match": strict_period_match,
        "include_not_evaluable": include_not_evaluable,
        "debug_label": debug_label,
        "input_records": len(input_records),
        "alignment_report_observations": (alignment_summary or {}).get("pdf_row_value_observations"),
        **SAFETY,
    }
    selected_records = evaluated if include_not_evaluable else [record for record in evaluated if record.get("predicted_qname")]
    evaluation_report = {
        "run_metadata": run_metadata,
        "summary": {
            **overall,
            "exact_qname_value_period_matches": overall["exact_matches"],
            "false_positives": overall["false_positive_count"],
            "ambiguous_cases": overall["ambiguous_count"],
            "not_evaluable_cases": overall["not_evaluable_count"],
            "source_mapper_summary": sanitize_report_value(mapper_summary or {}),
            "recommended_next_feature": recommendation["recommended_next_feature"],
            "explicit_no_auto_apply_boundary": "No #18E-D output is safe for auto-apply; all mapper output remains human-review-only.",
            "safety": SAFETY,
        },
        "records": [sanitized_record(record, strict_period_match=strict_period_match) for record in selected_records],
    }
    precision_summary = {
        "run_metadata": run_metadata,
        "summary": {
            **overall,
            "recommended_next_feature": recommendation,
            "safe_labels": _safe_labels(evaluated, strict_period_match=strict_period_match, limit=40),
            "risky_labels": _risky_labels(evaluated, strict_period_match=strict_period_match, limit=40),
            "safety": SAFETY,
        },
        "by_candidate_source": source_metrics,
        "by_statement_family": statement_metrics,
        "by_label_family": label_metrics,
    }
    conflict_report = {
        "run_metadata": run_metadata,
        "summary": {
            "remaining_false_positive_count": len(conflict_risk["remaining_false_positives"]),
            "ambiguous_case_count": len(conflict_risk["ambiguous_cases"]),
            "high_or_critical_group_count": sum(
                1
                for group in [*source_metrics, *statement_metrics, *label_metrics]
                if group.get("risk_level") in {"high", "critical"}
            ),
            "safety": SAFETY,
        },
        **sanitize_report_value(conflict_risk),
    }
    blocked_candidate_report = {
        "run_metadata": run_metadata,
        **blocked_analysis,
    }
    readiness_report = {
        "run_metadata": run_metadata,
        **readiness,
        "recommendation": recommendation,
    }
    return {
        "evaluation": sanitize_report_value(evaluation_report),
        "precision_summary": sanitize_report_value(precision_summary),
        "conflict_risk": sanitize_report_value(conflict_report),
        "blocked_candidate_analysis": sanitize_report_value(blocked_candidate_report),
        "readiness_matrix": sanitize_report_value(readiness_report),
    }


def build_tightened_mapper_reports_from_files(
    *,
    dataset_dir: str | Path,
    mapper_report_path: str | Path,
    blocked_report_path: str | Path | None = None,
    alignment_report_path: str | Path | None = None,
    debug_label: str | None = None,
    include_not_evaluable: bool = False,
    strict_period_match: bool = False,
) -> dict[str, Any]:
    mapper_report = read_json(mapper_report_path)
    blocked_report = read_json(blocked_report_path)
    alignment_report = read_json(alignment_report_path)
    records = list(mapper_report.get("suggestions") or [])
    evidence = load_local_evaluation_evidence(dataset_dir=dataset_dir, records=records)
    return build_tightened_mapper_reports(
        records,
        row_values=evidence["row_values"],
        facts_by_sample=evidence["facts_by_sample"],
        mapper_summary=mapper_report.get("summary") or {},
        blocked_report=blocked_report,
        alignment_report=alignment_report,
        strict_period_match=strict_period_match,
        include_not_evaluable=include_not_evaluable,
        debug_label=debug_label,
    )


def _simple_markdown(title: str, report: Mapping[str, Any], *, rows_key: str | None = None) -> str:
    summary = report.get("summary") or {}
    lines = [f"# {title}", ""]
    for key in (
        "total_observations",
        "candidate_count",
        "touched_coverage_rate",
        "precision_on_evaluable",
        "exact_matches",
        "exact_qname_value_period_matches",
        "false_positive_count",
        "false_positives",
        "ambiguous_count",
        "ambiguous_cases",
        "not_evaluable_count",
        "not_evaluable_cases",
        "remaining_false_positive_count",
        "blocked_candidate_rows",
        "blocked_candidate_opportunities",
        "correctly_blocked_false_positive_count",
        "overblocked_true_positive_count",
        "safe_to_upgrade_to_advisory_medium_count",
        "should_be_disabled_count",
    ):
        if key in summary:
            lines.append(f"- {key}: {summary.get(key)}")
    recommendation = report.get("recommendation") or summary.get("recommended_next_feature")
    if isinstance(recommendation, Mapping):
        lines.append(f"- recommended_next_feature: {recommendation.get('recommended_next_feature')}")
        lines.append(f"- recommendation_reason: {recommendation.get('reason')}")
    elif recommendation:
        lines.append(f"- recommended_next_feature: {recommendation}")
    boundary = summary.get("explicit_no_auto_apply_boundary") or (summary.get("safety") or {}).get("explicit_no_auto_apply_boundary")
    if boundary:
        lines.append(f"- boundary: {boundary}")
    else:
        lines.append("- boundary: No auto-apply or confirmed_tag_id automation is recommended; human review remains required.")
    if rows_key and report.get(rows_key):
        lines.extend(["", "| Name | Candidates | Precision | False positives | Risk | Recommendation |", "| --- | ---: | ---: | ---: | --- | --- |"])
        for row in report.get(rows_key) or []:
            lines.append(
                f"| {row.get('name')} | {row.get('candidate_count')} | {row.get('precision_on_evaluable')} | "
                f"{row.get('false_positive_count')} | {row.get('risk_level')} | {row.get('recommendation')} |"
            )
    lines.append("")
    return "\n".join(lines)


def render_evaluation_markdown(report: Mapping[str, Any]) -> str:
    return _simple_markdown("Tightened Mapper Evaluation - Feature #18E-D", report)


def render_precision_summary_markdown(report: Mapping[str, Any]) -> str:
    lines = [_simple_markdown("Tightened Mapper Precision Summary - Feature #18E-D", report), "## Candidate Source Risk", ""]
    lines.extend(["| Source | Candidates | Precision | False positives | Risk | Recommendation |", "| --- | ---: | ---: | ---: | --- | --- |"])
    for row in report.get("by_candidate_source") or []:
        lines.append(
            f"| {row.get('name')} | {row.get('candidate_count')} | {row.get('precision_on_evaluable')} | "
            f"{row.get('false_positive_count')} | {row.get('risk_level')} | {row.get('recommendation')} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_conflict_risk_markdown(report: Mapping[str, Any]) -> str:
    return _simple_markdown("Tightened Mapper Conflict Risk - Feature #18E-D", report)


def render_blocked_candidate_markdown(report: Mapping[str, Any]) -> str:
    return _simple_markdown("Tightened Mapper Blocked Candidate Analysis - Feature #18E-D", report)


def render_readiness_matrix_markdown(report: Mapping[str, Any]) -> str:
    lines = [_simple_markdown("Tightened Mapper Readiness Matrix - Feature #18E-D", report), "## Matrix", ""]
    lines.extend(["| Group | Name | Advisory medium | Disabled | More context | Note link | Auto apply |", "| --- | --- | --- | --- | --- | --- | --- |"])
    for row in report.get("matrix") or []:
        lines.append(
            f"| {row.get('group_type')} | {row.get('name')} | {row.get('safe_to_upgrade_to_advisory_medium')} | "
            f"{row.get('should_be_disabled')} | {row.get('needs_more_context')} | {row.get('needs_note_link')} | "
            f"{row.get('auto_apply_recommended')} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_reports(reports: Mapping[str, Mapping[str, Any]], *, output_dir: str | Path) -> dict[str, str]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "evaluation_json": output / "tightened_mapper_evaluation_18e_d.json",
        "evaluation_md": output / "tightened_mapper_evaluation_18e_d.md",
        "precision_summary_json": output / "tightened_mapper_precision_summary_18e_d.json",
        "precision_summary_md": output / "tightened_mapper_precision_summary_18e_d.md",
        "conflict_risk_json": output / "tightened_mapper_conflict_risk_18e_d.json",
        "conflict_risk_md": output / "tightened_mapper_conflict_risk_18e_d.md",
        "blocked_candidate_analysis_json": output / "tightened_mapper_blocked_candidate_analysis_18e_d.json",
        "blocked_candidate_analysis_md": output / "tightened_mapper_blocked_candidate_analysis_18e_d.md",
        "readiness_matrix_json": output / "tightened_mapper_readiness_matrix_18e_d.json",
        "readiness_matrix_md": output / "tightened_mapper_readiness_matrix_18e_d.md",
    }
    write_json(paths["evaluation_json"], reports["evaluation"])
    paths["evaluation_md"].write_text(render_evaluation_markdown(reports["evaluation"]), encoding="utf-8")
    write_json(paths["precision_summary_json"], reports["precision_summary"])
    paths["precision_summary_md"].write_text(render_precision_summary_markdown(reports["precision_summary"]), encoding="utf-8")
    write_json(paths["conflict_risk_json"], reports["conflict_risk"])
    paths["conflict_risk_md"].write_text(render_conflict_risk_markdown(reports["conflict_risk"]), encoding="utf-8")
    write_json(paths["blocked_candidate_analysis_json"], reports["blocked_candidate_analysis"])
    paths["blocked_candidate_analysis_md"].write_text(render_blocked_candidate_markdown(reports["blocked_candidate_analysis"]), encoding="utf-8")
    write_json(paths["readiness_matrix_json"], reports["readiness_matrix"])
    paths["readiness_matrix_md"].write_text(render_readiness_matrix_markdown(reports["readiness_matrix"]), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
