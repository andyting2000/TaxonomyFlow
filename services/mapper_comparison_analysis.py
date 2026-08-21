"""Offline comparison of deterministic rulebook mapper output and cached Qwen suggestions."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.pdf_xbrl_rulebook_replay import FALSE_POSITIVE_STATUSES, GOOD_STATUSES


FEATURE_ID = "18E-C"
SAFETY = {
    "read_only": True,
    "offline_only": True,
    "external_llm_called": False,
    "external_provider_called": False,
    "qwen_called": False,
    "supervisor_called": False,
    "azure_di_live_call_made": False,
    "database_mutated": False,
    "production_behavior_changed": False,
    "api_changed": False,
    "ui_changed": False,
    "ai_suggestion_rows_written": False,
    "xbrl_generated": False,
    "arelle_run": False,
    "auto_applied": False,
    "confirmed_tag_id_mutated": False,
    "safe_for_auto_apply": False,
    "human_review_final": True,
}

PERIOD_SUFFIXES = {"current", "prior", "previous", "comparative"}
QWEN_REPORT_PATTERNS = (
    "golden_mbrs_fewshot_qwen_predictions_*.json",
    "golden_mbrs_current_mapping_predictions_*.json",
    "llm_taxonomy_mapping_suggestions_*.json",
    "*qwen*predictions*.json",
)
QWEN_GOOD_STATUSES = {"correct", "qwen_gold_qname_match"}
QWEN_FALSE_STATUSES = {"wrong_concept", "qwen_gold_qname_mismatch"}
HIGH_RISK_CONFLICT_TYPES = {
    "statement_family_mismatch",
    "balance_sheet_vs_cash_flow_confusion",
    "tax_expense_vs_tax_payable_deferred_tax_confusion",
    "receivable_vs_payable_confusion",
    "subtotal_vs_component_confusion",
    "note_detail_vs_main_statement_mismatch",
    "period_current_prior_mismatch",
}
GENERIC_LABELS = {
    "amount",
    "balance",
    "current",
    "equity",
    "less",
    "liabilities",
    "net",
    "other",
    "subtotal",
    "total",
    "total assets",
    "total current assets",
    "total current liabilities",
    "total liabilities",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=True, default=str) + "\n", encoding="utf-8")


def safe_rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def normalize_statement_family(value: Any) -> str | None:
    text = canonical_label(value)
    if not text:
        return None
    if text in {"financial_position", "income_statement", "cash_flow", "changes_in_equity", "notes"}:
        return text
    if "cash flow" in text:
        return "cash_flow"
    if "financial position" in text or "balance sheet" in text:
        return "financial_position"
    if "comprehensive income" in text or "income statement" in text or "profit or loss" in text:
        return "income_statement"
    if "changes in equity" in text or "equity" == text:
        return "changes_in_equity"
    if "note" in text:
        return "notes"
    return None


def value_key(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value).strip().replace(",", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    text = re.sub(r"\s+", "", text)
    try:
        decimal = Decimal(text)
    except (InvalidOperation, ValueError):
        return text.lower()
    if decimal == decimal.to_integral_value():
        return str(decimal.quantize(Decimal("1")))
    return format(decimal.normalize(), "f")


def row_id_base(row_id: Any) -> str:
    text = str(row_id or "").strip()
    if not text:
        return ""
    parts = text.split(":")
    if parts and parts[-1].lower() in PERIOD_SUFFIXES:
        return ":".join(parts[:-1])
    return text


def row_period_from_id(row_id: Any) -> str | None:
    text = str(row_id or "").strip()
    if not text:
        return None
    suffix = text.split(":")[-1].lower()
    return suffix if suffix in PERIOD_SUFFIXES else None


def _with_sample_prefix(sample_id: Any, row_id: Any) -> str:
    sample = str(sample_id or "").strip()
    text = str(row_id or "").strip()
    if not sample or not text or text.startswith(f"{sample}:"):
        return text
    return f"{sample}:{text}"


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _truncate(value: Any, *, limit: int = 500) -> str | None:
    if value in (None, ""):
        return None
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _first_mapping(*values: Any) -> Mapping[str, Any]:
    for value in values:
        if isinstance(value, Mapping):
            return value
    return {}


def _prediction_qname(prediction: Mapping[str, Any]) -> str | None:
    for key in (
        "predicted_concept_qname",
        "predicted_template_field_id",
        "selected_template_field_id",
        "selected_concept_qname",
        "concept_qname",
        "template_field_id",
        "qname",
    ):
        value = prediction.get(key)
        if value not in (None, ""):
            return str(value)
    selected = _first_mapping(prediction.get("selected_candidate"), prediction.get("top_suggestion"))
    if selected:
        return _prediction_qname(selected)
    return None


def deterministic_status(record: Mapping[str, Any]) -> str:
    bucket = str(record.get("confidence_bucket") or "")
    qname = record.get("predicted_qname")
    if qname and bucket in {"advisory_high", "advisory_medium"}:
        return "advisory"
    if qname:
        return "review_required"
    if bucket == "conflict":
        return "conflict"
    return "no_match"


def normalize_deterministic_record(record: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    period = dict(record.get("pdf_period") or {})
    row_id = str(record.get("pdf_row_id") or record.get("row_id") or "")
    family = normalize_statement_family(record.get("pdf_statement_family") or record.get("pdf_statement_type"))
    normalized = record.get("normalized_label") or canonical_label(record.get("pdf_label"))
    return {
        "index": index,
        "sample_id": str(record.get("sample_id") or ""),
        "company_name": record.get("company_name"),
        "row_id": row_id,
        "base_row_id": row_id_base(row_id),
        "pdf_label": record.get("pdf_label"),
        "normalized_label": normalized,
        "value": record.get("pdf_value"),
        "value_key": value_key(record.get("pdf_value")),
        "statement_family": family,
        "statement_type": record.get("pdf_statement_type"),
        "period": period,
        "value_role": period.get("value_role") or row_period_from_id(row_id),
        "expected_year": period.get("expected_year"),
        "status": deterministic_status(record),
        "qname": record.get("predicted_qname"),
        "confidence_bucket": record.get("confidence_bucket"),
        "confidence_score": _as_float(record.get("confidence_score")),
        "source": record.get("suggestion_source"),
        "matched_rule_id": record.get("matched_rule_id") or record.get("matched_template_pattern_id"),
        "rule_readiness": record.get("rule_readiness"),
        "match_reasons": list(record.get("match_reasons") or []),
        "blocking_reasons": list(record.get("blocking_reasons") or []),
        "row_context": dict(record.get("row_context") or {}),
        "note_link": record.get("note_link"),
        "safe_for_auto_apply": bool(record.get("safe_for_auto_apply")),
        "requires_human_review": bool(record.get("requires_human_review", True)),
        "evaluation_status": record.get("evaluation_status"),
        "xbrl_support_status": record.get("xbrl_support_status"),
    }


def load_deterministic_report(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    payload = read_json(source)
    records = payload.get("suggestions") or payload.get("records") or payload.get("mapping_records") or []
    normalized = [normalize_deterministic_record(record, index=index) for index, record in enumerate(records)]
    return {
        "status": "loaded",
        "source_file": str(source),
        "run_metadata": payload.get("run_metadata") or {},
        "summary": payload.get("summary") or {},
        "records": normalized,
    }


def discover_qwen_reports(report_dir: str | Path) -> list[Path]:
    root = Path(report_dir)
    if not root.exists():
        return []
    seen: set[Path] = set()
    ordered: list[Path] = []
    for pattern in QWEN_REPORT_PATTERNS:
        for path in sorted(root.glob(pattern)):
            resolved = path.resolve()
            if resolved in seen or not path.is_file():
                continue
            seen.add(resolved)
            ordered.append(path)
    return ordered


def _qwen_status(raw_status: Any, qname: str | None) -> str:
    if qname:
        return "suggested"
    raw = str(raw_status or "").strip()
    if raw in {"rejected", "rejected_precheck", "blocked", "provider_error", "no_prediction"}:
        return "no_safe_suggestion"
    return raw or "no_prediction"


def _qwen_eval_status(prediction: Mapping[str, Any], correct_qname: Any) -> str:
    qname = _prediction_qname(prediction)
    expected = str(correct_qname or "")
    if not expected:
        return "not_evaluable"
    if not qname:
        return "no_prediction"
    return "correct" if qname == expected else "wrong_concept"


def _expanded_qwen_row(
    *,
    source_format: str,
    source_file: str,
    source_section: str,
    row: Mapping[str, Any],
    prediction: Mapping[str, Any],
    strict_scoring: bool,
) -> list[dict[str, Any]]:
    sample_id = str(row.get("source_case_id") or row.get("sample_id") or row.get("case_id") or "")
    base_id = _with_sample_prefix(sample_id, row.get("extracted_row_id") or row.get("row_id") or row.get("pdf_row_id"))
    has_period_suffix = row_period_from_id(base_id) is not None
    qname = _prediction_qname(prediction)
    status = _qwen_status(prediction.get("status"), qname)
    family = normalize_statement_family(row.get("statement_type") or row.get("pdf_statement_family"))
    eval_status = _qwen_eval_status(prediction, row.get("correct_concept_qname"))
    values: list[tuple[str | None, Any]] = []
    if has_period_suffix:
        values.append((row_period_from_id(base_id), row.get("extracted_value") or row.get("value") or row.get("pdf_value")))
    else:
        values.append(("current", row.get("extracted_value") or row.get("value") or row.get("pdf_value")))
        previous = row.get("previous_value") or row.get("value_previous_year") or row.get("prior_value")
        if previous not in (None, ""):
            values.append(("prior", previous))

    records = []
    for role, value in values:
        row_id = base_id if has_period_suffix or not role else f"{base_id}:{role}"
        records.append(
            {
                "source_format": source_format,
                "source_file": source_file,
                "source_section": source_section,
                "strict_scoring": strict_scoring,
                "comparable": strict_scoring,
                "sample_id": sample_id,
                "row_id": row_id,
                "base_row_id": row_id_base(row_id),
                "pdf_label": row.get("extracted_label") or row.get("pdf_label") or row.get("label"),
                "normalized_label": canonical_label(row.get("extracted_label") or row.get("pdf_label") or row.get("label")),
                "value": value,
                "value_key": value_key(value),
                "statement_family": family,
                "statement_type": row.get("statement_type") or row.get("pdf_statement_type"),
                "period": {"value_role": role},
                "value_role": role,
                "status": status,
                "raw_status": prediction.get("status"),
                "qname": qname,
                "confidence": _as_float(prediction.get("confidence")),
                "confidence_tier": prediction.get("confidence_tier") or prediction.get("confidence_category"),
                "reason": _truncate(prediction.get("reason") or prediction.get("rejection_reason")),
                "local_evaluation_status": eval_status,
                "local_evaluation_basis": "strict_gold_qname" if strict_scoring else "not_evaluable",
            }
        )
    return records


def _load_fewshot_qwen_predictions(payload: Mapping[str, Any], *, source_file: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in payload.get("strict_scoring_rows") or []:
        prediction = dict(row.get("fewshot_qwen_prediction") or row.get("qwen_prediction") or {})
        records.extend(
            _expanded_qwen_row(
                source_format="golden_mbrs_fewshot_qwen_predictions",
                source_file=source_file,
                source_section="strict_scoring_rows",
                row=row,
                prediction=prediction,
                strict_scoring=True,
            )
        )
    for row in payload.get("ambiguous_diagnostic_rows") or []:
        records.extend(
            _expanded_qwen_row(
                source_format="golden_mbrs_fewshot_qwen_predictions",
                source_file=source_file,
                source_section="ambiguous_diagnostic_rows",
                row=row,
                prediction={"status": "diagnostic_only", "reason": row.get("reason")},
                strict_scoring=False,
            )
        )
    return records


def _load_llm_taxonomy_rows(payload: Mapping[str, Any], *, source_file: str) -> list[dict[str, Any]]:
    records = []
    for index, row in enumerate(payload.get("rows") or []):
        suggestion = dict(row.get("suggestion") or {})
        selected = _first_mapping(suggestion.get("selected_candidate"))
        if selected and not suggestion.get("selected_template_field_id"):
            suggestion["selected_template_field_id"] = selected.get("template_field_id")
        qname = _prediction_qname(suggestion)
        status = _qwen_status(suggestion.get("status"), qname)
        row_id = str(row.get("extracted_data_item_id") or row.get("row_id") or f"llm_row_{index}")
        family = normalize_statement_family(row.get("statement_type"))
        records.append(
            {
                "source_format": "llm_taxonomy_mapping_suggestions",
                "source_file": source_file,
                "source_section": "rows",
                "strict_scoring": False,
                "comparable": False,
                "sample_id": str(row.get("sample_id") or ""),
                "row_id": row_id,
                "base_row_id": row_id_base(row_id),
                "pdf_label": row.get("extracted_label"),
                "normalized_label": canonical_label(row.get("extracted_label")),
                "value": row.get("extracted_value"),
                "value_key": value_key(row.get("extracted_value")),
                "statement_family": family,
                "statement_type": row.get("statement_type"),
                "period": {},
                "value_role": None,
                "status": status,
                "raw_status": suggestion.get("status"),
                "qname": qname,
                "confidence": _as_float(suggestion.get("confidence")),
                "confidence_tier": suggestion.get("confidence_category"),
                "reason": _truncate(suggestion.get("reason") or suggestion.get("rejection_reason")),
                "local_evaluation_status": "not_evaluable",
                "local_evaluation_basis": "no_local_gold_in_report",
            }
        )
    return records


def load_qwen_report(
    *,
    qwen_report: str | Path | None = None,
    report_dir: str | Path = "reports",
    allow_missing: bool = False,
) -> dict[str, Any]:
    source: Path | None = Path(qwen_report) if qwen_report else None
    if source is None:
        discovered = discover_qwen_reports(report_dir)
        source = discovered[0] if discovered else None
    if source is None or not source.exists():
        if allow_missing:
            return {
                "status": "missing",
                "source_file": str(source) if source else None,
                "source_format": None,
                "run_metadata": {},
                "summary": {"qwen_input_available": False, "qwen_suggestions_loaded": 0},
                "records": [],
            }
        raise FileNotFoundError(f"Qwen report not found: {source or report_dir}")

    payload = read_json(source)
    if isinstance(payload, Mapping) and "strict_scoring_rows" in payload:
        records = _load_fewshot_qwen_predictions(payload, source_file=str(source))
        source_format = "golden_mbrs_fewshot_qwen_predictions"
    elif isinstance(payload, Mapping) and "rows" in payload:
        records = _load_llm_taxonomy_rows(payload, source_file=str(source))
        source_format = "llm_taxonomy_mapping_suggestions"
    else:
        records = []
        source_format = "unsupported_qwen_report_shape"

    comparable = [record for record in records if record.get("comparable")]
    return {
        "status": "loaded",
        "source_file": str(source),
        "source_format": source_format,
        "run_metadata": payload.get("run_metadata") if isinstance(payload, Mapping) else {},
        "summary": {
            "qwen_input_available": True,
            "qwen_suggestions_loaded": len(records),
            "qwen_comparable_rows_loaded": len(comparable),
            "qwen_suggested_rows_loaded": sum(1 for record in records if record.get("qname")),
            "qwen_source_sections": dict(Counter(str(record.get("source_section")) for record in records)),
        },
        "records": records,
    }


def _index_values(records: Sequence[Mapping[str, Any]], key_fn: Any) -> dict[tuple[Any, ...], list[Mapping[str, Any]]]:
    index: dict[tuple[Any, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        key = key_fn(record)
        if all(part not in (None, "") for part in key):
            index[key].append(record)
    return index


def build_qwen_index(records: Sequence[Mapping[str, Any]]) -> dict[str, dict[tuple[Any, ...], list[Mapping[str, Any]]]]:
    return {
        "exact": _index_values(records, lambda item: (item.get("sample_id"), item.get("row_id"))),
        "base_value": _index_values(records, lambda item: (item.get("sample_id"), item.get("base_row_id"), item.get("value_key"))),
        "label_value_family": _index_values(
            records,
            lambda item: (item.get("sample_id"), item.get("normalized_label"), item.get("value_key"), item.get("statement_family")),
        ),
        "label_value": _index_values(records, lambda item: (item.get("sample_id"), item.get("normalized_label"), item.get("value_key"))),
    }


def _unique_match(matches: Sequence[Mapping[str, Any]]) -> tuple[Mapping[str, Any] | None, str]:
    if len(matches) == 1:
        return matches[0], "matched"
    if len(matches) > 1:
        return None, "ambiguous_alignment"
    return None, "missing"


def align_qwen_record(
    deterministic: Mapping[str, Any],
    qwen_index: Mapping[str, Mapping[tuple[Any, ...], Sequence[Mapping[str, Any]]]],
) -> tuple[Mapping[str, Any] | None, str]:
    candidates, status = _unique_match(
        qwen_index["exact"].get((deterministic.get("sample_id"), deterministic.get("row_id")), [])
    )
    if candidates:
        return candidates, "row_id_exact"
    if status == "ambiguous_alignment":
        return None, status

    candidates, status = _unique_match(
        qwen_index["base_value"].get(
            (deterministic.get("sample_id"), deterministic.get("base_row_id"), deterministic.get("value_key")),
            [],
        )
    )
    if candidates:
        return candidates, "row_id_base_value"
    if status == "ambiguous_alignment":
        return None, status

    candidates, status = _unique_match(
        qwen_index["label_value_family"].get(
            (
                deterministic.get("sample_id"),
                deterministic.get("normalized_label"),
                deterministic.get("value_key"),
                deterministic.get("statement_family"),
            ),
            [],
        )
    )
    if candidates:
        return candidates, "label_value_statement_family"
    if status == "ambiguous_alignment":
        return None, status

    candidates, status = _unique_match(
        qwen_index["label_value"].get(
            (deterministic.get("sample_id"), deterministic.get("normalized_label"), deterministic.get("value_key")),
            [],
        )
    )
    if candidates:
        return candidates, "label_value"
    if status == "ambiguous_alignment":
        return None, status
    return None, "qwen_missing"


def _qname_words(qname: Any) -> set[str]:
    local = str(qname or "").split(":")[-1]
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", local)
    return {token for token in canonical_label(spaced).split() if token}


def _contains_any(text: str, terms: Sequence[str]) -> bool:
    return any(term in text for term in terms)


def classify_conflict(
    deterministic: Mapping[str, Any],
    qwen: Mapping[str, Any],
) -> str:
    det_qname = deterministic.get("qname")
    qwen_qname = qwen.get("qname")
    det_words = _qname_words(det_qname)
    qwen_words = _qname_words(qwen_qname)
    det_text = " ".join(sorted(det_words))
    qwen_text = " ".join(sorted(qwen_words))
    label = canonical_label(deterministic.get("pdf_label") or deterministic.get("normalized_label"))
    det_family = deterministic.get("statement_family")
    qwen_family = qwen.get("statement_family")
    det_role = deterministic.get("value_role")
    qwen_role = qwen.get("value_role")
    row_context = deterministic.get("row_context") or {}

    if det_role and qwen_role and det_role != qwen_role:
        return "period_current_prior_mismatch"
    if _contains_any(f"{label} {det_text} {qwen_text}", ["tax"]):
        expense = "expense" in det_text or "expense" in qwen_text or "income tax" in det_text or "income tax" in qwen_text
        payable = _contains_any(f"{det_text} {qwen_text}", ["payable", "liabil", "deferred", "current tax"])
        if expense and payable:
            return "tax_expense_vs_tax_payable_deferred_tax_confusion"
    if ("receivable" in det_text and "payable" in qwen_text) or ("payable" in det_text and "receivable" in qwen_text):
        return "receivable_vs_payable_confusion"
    cash_flow_terms = ["activities", "proceeds", "purchase", "payments", "increase decrease", "classified as"]
    if (
        (det_family == "cash_flow" and qwen_family == "financial_position")
        or (det_family == "financial_position" and qwen_family == "cash_flow")
        or ("cash" in det_words | qwen_words and _contains_any(f"{det_text} {qwen_text}", cash_flow_terms))
    ):
        return "balance_sheet_vs_cash_flow_confusion"
    row_role = str(row_context.get("row_role") or "")
    if row_role in {"subtotal", "total"} or label.startswith(("total ", "net ", "gross ")):
        return "subtotal_vs_component_confusion"
    if bool(row_context.get("is_notes_context")) and qwen_family and qwen_family != "notes":
        return "note_detail_vs_main_statement_mismatch"
    if det_family and qwen_family and det_family != qwen_family:
        return "statement_family_mismatch"
    if label in GENERIC_LABELS or len(label.split()) <= 2 and _contains_any(label, ["other", "total", "net"]):
        return "generic_label_conflict"
    overlap = len(det_words & qwen_words) / len(det_words | qwen_words) if det_words and qwen_words else 0.0
    if overlap >= 0.35:
        return "same_concept_family_different_specificity"
    broad_terms = {"other", "trade", "current", "noncurrent", "assets", "liabilities"}
    if (det_words & broad_terms) or (qwen_words & broad_terms):
        return "broad_substitute"
    return "unknown"


def eval_outcome(status: Any, *, mapper: str) -> str:
    value = str(status or "")
    if mapper == "qwen":
        if value in QWEN_GOOD_STATUSES:
            return "good"
        if value in QWEN_FALSE_STATUSES:
            return "false_positive"
    if value in GOOD_STATUSES:
        return "good"
    if value in FALSE_POSITIVE_STATUSES:
        return "false_positive"
    return "not_evaluable"


def _preferred_policy(det: Mapping[str, Any], qwen: Mapping[str, Any] | None, comparison_status: str, conflict_type: str | None) -> str:
    if comparison_status == "both_agree_same_qname":
        return "prefer_agreed_candidate_human_review"
    if comparison_status == "both_suggest_conflict":
        return "manual_review_required_conflict"
    if comparison_status == "deterministic_only":
        if det.get("status") == "advisory":
            return "deterministic_advisory_candidate_human_review"
        return "deterministic_review_candidate_human_review"
    if comparison_status == "qwen_only":
        if qwen and qwen.get("confidence_tier") == "high":
            return "qwen_high_confidence_candidate_human_review"
        return "qwen_candidate_human_review"
    if comparison_status == "both_no_match":
        return "no_candidate_escalate_only_if_required"
    if conflict_type in HIGH_RISK_CONFLICT_TYPES:
        return "manual_review_required_high_risk_conflict"
    return "human_review_required"


def _review_priority(comparison_status: str, conflict_type: str | None, det: Mapping[str, Any], qwen: Mapping[str, Any] | None) -> str:
    if comparison_status == "both_suggest_conflict":
        return "high" if conflict_type in HIGH_RISK_CONFLICT_TYPES else "medium"
    if comparison_status == "qwen_only" and qwen and qwen.get("confidence_tier") == "high":
        return "medium"
    if comparison_status in {"deterministic_only", "qwen_only"}:
        return "medium"
    if comparison_status == "both_agree_same_qname" and det.get("status") == "advisory":
        return "low"
    if comparison_status == "both_no_match":
        return "low"
    return "medium"


def compare_records(
    deterministic_records: Sequence[Mapping[str, Any]],
    qwen_records: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    qwen_index = build_qwen_index(qwen_records)
    aligned_qwen_ids: set[int] = set()
    comparison_records: list[dict[str, Any]] = []

    for det in deterministic_records:
        qwen, alignment_status = align_qwen_record(det, qwen_index)
        if qwen is not None:
            aligned_qwen_ids.add(id(qwen))
        det_qname = det.get("qname")
        qwen_qname = qwen.get("qname") if qwen else None
        qwen_comparable = bool(qwen and qwen.get("comparable"))

        if not qwen:
            comparison_status = "not_comparable" if alignment_status == "ambiguous_alignment" else "qwen_missing"
        elif not qwen_comparable:
            comparison_status = "not_comparable"
        elif det_qname and qwen_qname:
            comparison_status = "both_agree_same_qname" if det_qname == qwen_qname else "both_suggest_conflict"
        elif det_qname:
            comparison_status = "deterministic_only"
        elif qwen_qname:
            comparison_status = "qwen_only"
        else:
            comparison_status = "both_no_match"

        conflict_type = classify_conflict(det, qwen) if comparison_status == "both_suggest_conflict" and qwen else None
        local_status = {
            "deterministic": det.get("evaluation_status") or "not_evaluable",
            "qwen": qwen.get("local_evaluation_status") if qwen else "not_available",
        }
        comparison_records.append(
            {
                "sample_id": det.get("sample_id"),
                "row_id": det.get("row_id"),
                "pdf_label": det.get("pdf_label"),
                "normalized_label": det.get("normalized_label"),
                "value": det.get("value"),
                "statement_family": det.get("statement_family"),
                "statement_type": det.get("statement_type"),
                "period": det.get("period") or {},
                "deterministic_status": det.get("status"),
                "deterministic_qname": det_qname,
                "deterministic_confidence_bucket": det.get("confidence_bucket"),
                "deterministic_source": det.get("source"),
                "deterministic_rule_id": det.get("matched_rule_id"),
                "deterministic_reasons": {
                    "match_reasons": det.get("match_reasons") or [],
                    "blocking_reasons": det.get("blocking_reasons") or [],
                },
                "qwen_alignment_status": alignment_status,
                "qwen_status": qwen.get("status") if qwen else ("ambiguous_alignment" if alignment_status == "ambiguous_alignment" else "missing"),
                "qwen_raw_status": qwen.get("raw_status") if qwen else None,
                "qwen_qname": qwen_qname,
                "qwen_confidence": qwen.get("confidence") if qwen else None,
                "qwen_confidence_tier": qwen.get("confidence_tier") if qwen else None,
                "qwen_reason": qwen.get("reason") if qwen else None,
                "qwen_source_format": qwen.get("source_format") if qwen else None,
                "comparison_status": comparison_status,
                "local_evaluation_status": local_status,
                "preferred_candidate_policy": _preferred_policy(det, qwen, comparison_status, conflict_type),
                "review_priority": _review_priority(comparison_status, conflict_type, det, qwen),
                "conflict_reason": conflict_type,
                "safe_for_auto_apply": False,
                "requires_human_review": True,
            }
        )

    unaligned = [dict(record) for record in qwen_records if id(record) not in aligned_qwen_ids]
    return comparison_records, unaligned


def _precision(records: Sequence[Mapping[str, Any]], *, mapper: str) -> dict[str, Any]:
    good = false = not_evaluable = predictions = 0
    for record in records:
        if mapper == "deterministic":
            if not record.get("deterministic_qname"):
                continue
            status = (record.get("local_evaluation_status") or {}).get("deterministic")
        else:
            if not record.get("qwen_qname"):
                continue
            status = (record.get("local_evaluation_status") or {}).get("qwen")
        predictions += 1
        outcome = eval_outcome(status, mapper=mapper)
        if outcome == "good":
            good += 1
        elif outcome == "false_positive":
            false += 1
        else:
            not_evaluable += 1
    return {
        "predictions": predictions,
        "good": good,
        "false_positive": false,
        "not_evaluable": not_evaluable,
        "precision_on_evaluable": safe_rate(good, good + false),
    }


def _status_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get("comparison_status")) for record in records).items()))


def summarize_comparison(
    records: Sequence[Mapping[str, Any]],
    *,
    deterministic_report: Mapping[str, Any],
    qwen_report: Mapping[str, Any],
    unaligned_qwen: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    total = len(records)
    det_touched = sum(1 for record in records if record.get("deterministic_qname"))
    qwen_touched = sum(1 for record in records if record.get("qwen_qname"))
    both_touched = sum(1 for record in records if record.get("deterministic_qname") and record.get("qwen_qname"))
    both_agree = sum(1 for record in records if record.get("comparison_status") == "both_agree_same_qname")
    conflicts = [record for record in records if record.get("comparison_status") == "both_suggest_conflict"]
    combined_touched = sum(1 for record in records if record.get("deterministic_qname") or record.get("qwen_qname"))
    qwen_comparable = sum(1 for record in records if record.get("qwen_alignment_status") != "qwen_missing" and record.get("comparison_status") != "not_comparable")
    high_risk_conflicts = [record for record in conflicts if record.get("conflict_reason") in HIGH_RISK_CONFLICT_TYPES]
    per_statement: dict[str, Counter[str]] = defaultdict(Counter)
    for record in records:
        family = str(record.get("statement_family") or "unknown")
        per_statement[family]["total"] += 1
        if record.get("deterministic_qname"):
            per_statement[family]["deterministic_touched"] += 1
        if record.get("qwen_qname"):
            per_statement[family]["qwen_touched"] += 1
        if record.get("deterministic_qname") or record.get("qwen_qname"):
            per_statement[family]["combined_touched"] += 1
        per_statement[family][str(record.get("comparison_status"))] += 1

    statement_metrics = []
    for family, counts in sorted(per_statement.items()):
        family_total = counts["total"]
        statement_metrics.append(
            {
                "statement_family": family,
                "total_observations": family_total,
                "deterministic_touched": counts["deterministic_touched"],
                "deterministic_coverage_rate": safe_rate(counts["deterministic_touched"], family_total),
                "qwen_touched": counts["qwen_touched"],
                "qwen_coverage_rate": safe_rate(counts["qwen_touched"], family_total),
                "combined_touched": counts["combined_touched"],
                "combined_coverage_rate": safe_rate(counts["combined_touched"], family_total),
                "comparison_status_counts": {
                    key: count
                    for key, count in sorted(counts.items())
                    if key
                    not in {
                        "total",
                        "deterministic_touched",
                        "qwen_touched",
                        "combined_touched",
                    }
                },
            }
        )

    return {
        "feature": FEATURE_ID,
        "total_observations": total,
        "deterministic_source_file": deterministic_report.get("source_file"),
        "qwen_source_file": qwen_report.get("source_file"),
        "qwen_source_format": qwen_report.get("source_format"),
        "qwen_report_status": qwen_report.get("status"),
        "deterministic_touched": det_touched,
        "deterministic_coverage_rate": safe_rate(det_touched, total),
        "qwen_comparable_observations": qwen_comparable,
        "qwen_touched": qwen_touched,
        "qwen_coverage_rate": safe_rate(qwen_touched, total),
        "both_touched": both_touched,
        "both_agree_same_qname": both_agree,
        "both_suggest_conflict": len(conflicts),
        "deterministic_only": sum(1 for record in records if record.get("comparison_status") == "deterministic_only"),
        "qwen_only": sum(1 for record in records if record.get("comparison_status") == "qwen_only"),
        "both_no_match": sum(1 for record in records if record.get("comparison_status") == "both_no_match"),
        "qwen_missing": sum(1 for record in records if record.get("comparison_status") == "qwen_missing"),
        "not_comparable": sum(1 for record in records if record.get("comparison_status") == "not_comparable"),
        "combined_touched": combined_touched,
        "combined_coverage_rate": safe_rate(combined_touched, total),
        "hybrid_reaches_80_percent": bool(total and combined_touched / total >= 0.8),
        "hybrid_coverage_gap_to_80_percent": round(max(0.0, 0.8 - (combined_touched / total if total else 0.0)), 4),
        "comparison_status_counts": _status_counts(records),
        "conflict_type_counts": dict(sorted(Counter(record.get("conflict_reason") for record in conflicts).items())),
        "high_risk_conflict_count": len(high_risk_conflicts),
        "deterministic_local_precision": _precision(records, mapper="deterministic"),
        "qwen_local_precision_where_available": _precision(records, mapper="qwen"),
        "qwen_records_loaded": len(qwen_report.get("records") or []),
        "qwen_unaligned_records": len(unaligned_qwen),
        "qwen_unaligned_by_sample": dict(sorted(Counter(str(record.get("sample_id") or "(missing)") for record in unaligned_qwen).items())),
        "per_statement_family": statement_metrics,
    }


def recommend_next_feature(summary: Mapping[str, Any]) -> dict[str, Any]:
    combined_coverage = float(summary.get("combined_coverage_rate") or 0.0)
    conflict_count = int(summary.get("both_suggest_conflict") or 0)
    both_touched = int(summary.get("both_touched") or 0)
    high_risk = int(summary.get("high_risk_conflict_count") or 0)
    qwen_status = str(summary.get("qwen_report_status") or "")
    qwen_comparable = int(summary.get("qwen_comparable_observations") or 0)
    conflict_rate = conflict_count / both_touched if both_touched else 0.0
    if qwen_status != "loaded" or qwen_comparable == 0:
        next_feature = "Feature #18E-C-prep - Collect or export comparable cached Qwen rows for the benchmark."
        reason = "No comparable cached Qwen rows were available."
    elif high_risk >= 3 or conflict_rate >= 0.25:
        next_feature = "Feature #18E-C-hotfix-1 - Triage high-risk deterministic/Qwen conflicts before expansion."
        reason = "High-risk or frequent conflicts need targeted hardening before a hybrid workflow."
    elif combined_coverage >= 0.7:
        next_feature = "Feature #18F-A - Design review-only hybrid mapper workflow using deterministic and Qwen evidence."
        reason = "Combined offline coverage is at least 70% with manageable conflicts."
    else:
        next_feature = "Feature #18E-B-2 - Expand deterministic mapper coverage for rows neither mapper covers."
        reason = "Combined offline coverage is below 70%."
    return {
        "recommended_next_feature": next_feature,
        "reason": reason,
        "basis": {
            "combined_coverage_rate": combined_coverage,
            "qwen_comparable_observations": qwen_comparable,
            "both_touched": both_touched,
            "both_suggest_conflict": conflict_count,
            "conflict_rate_when_both_touched": round(conflict_rate, 4) if both_touched else 0.0,
            "high_risk_conflict_count": high_risk,
        },
    }


def build_hybrid_policy(summary: Mapping[str, Any]) -> dict[str, Any]:
    recommendation = recommend_next_feature(summary)
    return {
        "run_metadata": {
            "feature": FEATURE_ID,
            "generated_at": utc_now(),
            **SAFETY,
        },
        "summary": {
            "safe_for_auto_apply": False,
            "human_review_final": True,
            "confirmed_tag_id_automation": False,
            "ai_suggestion_writes": False,
            "combined_coverage_rate": summary.get("combined_coverage_rate"),
            "hybrid_reaches_80_percent": summary.get("hybrid_reaches_80_percent"),
            "hybrid_coverage_gap_to_80_percent": summary.get("hybrid_coverage_gap_to_80_percent"),
            "recommended_next_feature": recommendation["recommended_next_feature"],
            "recommendation_reason": recommendation["reason"],
            "recommendation_basis": recommendation["basis"],
        },
        "policy_rules": [
            {
                "when": "deterministic and Qwen agree on the same QName",
                "action": "show as strongest review candidate",
                "safe_for_auto_apply": False,
                "requires_human_review": True,
            },
            {
                "when": "deterministic advisory exists but Qwen is missing or abstains",
                "action": "show deterministic advisory as review candidate",
                "safe_for_auto_apply": False,
                "requires_human_review": True,
            },
            {
                "when": "Qwen suggests a QName where deterministic mapper has no match",
                "action": "show Qwen candidate as review evidence only",
                "safe_for_auto_apply": False,
                "requires_human_review": True,
            },
            {
                "when": "deterministic and Qwen suggest different QNames",
                "action": "raise conflict for manual review and do not prefer either automatically",
                "safe_for_auto_apply": False,
                "requires_human_review": True,
            },
            {
                "when": "neither mapper covers the row",
                "action": "leave unmapped and queue for future deterministic hardening if business-critical",
                "safe_for_auto_apply": False,
                "requires_human_review": True,
            },
        ],
        "non_goals_confirmed": [
            "No confirmed_tag_id automation",
            "No AI suggestion table writes",
            "No auto-apply",
            "No production mapper integration",
            "No API/UI/database changes",
            "No XBRL generation or Arelle run",
        ],
    }


def build_reports(
    deterministic_report: Mapping[str, Any],
    qwen_report: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    records, unaligned_qwen = compare_records(deterministic_report.get("records") or [], qwen_report.get("records") or [])
    summary = summarize_comparison(
        records,
        deterministic_report=deterministic_report,
        qwen_report=qwen_report,
        unaligned_qwen=unaligned_qwen,
    )
    recommendation = recommend_next_feature(summary)
    conflicts = [record for record in records if record.get("comparison_status") == "both_suggest_conflict"]
    uncovered = [
        record
        for record in records
        if not record.get("deterministic_qname") and not record.get("qwen_qname")
    ]
    run_metadata = {
        "feature": FEATURE_ID,
        "generated_at": utc_now(),
        "deterministic_report": deterministic_report.get("source_file"),
        "qwen_report": qwen_report.get("source_file"),
        **SAFETY,
    }
    comparison_report = {
        "run_metadata": run_metadata,
        "summary": {**summary, "recommendation": recommendation},
        "comparison_records": records,
        "unaligned_qwen_records": unaligned_qwen[:100],
    }
    summary_report = {
        "run_metadata": run_metadata,
        "summary": summary,
        "recommendation": recommendation,
    }
    conflict_report = {
        "run_metadata": run_metadata,
        "summary": {
            "conflict_count": len(conflicts),
            "high_risk_conflict_count": summary.get("high_risk_conflict_count"),
            "conflict_type_counts": summary.get("conflict_type_counts"),
        },
        "conflicts": conflicts,
    }
    uncovered_report = {
        "run_metadata": run_metadata,
        "summary": {
            "uncovered_count": len(uncovered),
            "uncovered_rate": safe_rate(len(uncovered), len(records)),
            "uncovered_with_qwen_missing": sum(1 for record in uncovered if record.get("qwen_status") == "missing"),
            "uncovered_with_qwen_abstention": sum(1 for record in uncovered if record.get("qwen_status") == "no_safe_suggestion"),
            "top_uncovered_labels": [
                {"normalized_label": label, "count": count}
                for label, count in Counter(str(record.get("normalized_label") or "") for record in uncovered).most_common(40)
                if label
            ],
        },
        "uncovered_records": uncovered,
    }
    return {
        "comparison": comparison_report,
        "summary": summary_report,
        "conflicts": conflict_report,
        "uncovered": uncovered_report,
        "hybrid_policy": build_hybrid_policy(summary),
    }


def render_comparison_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Mapper Comparison - Feature #18E-C",
        "",
        f"- Total observations: `{summary.get('total_observations')}`",
        f"- Deterministic touched: `{summary.get('deterministic_touched')}` ({summary.get('deterministic_coverage_rate')})",
        f"- Qwen touched: `{summary.get('qwen_touched')}` ({summary.get('qwen_coverage_rate')})",
        f"- Both agree: `{summary.get('both_agree_same_qname')}`",
        f"- Conflicts: `{summary.get('both_suggest_conflict')}`",
        f"- Combined touched: `{summary.get('combined_touched')}` ({summary.get('combined_coverage_rate')})",
        f"- Hybrid reaches 80%: `{summary.get('hybrid_reaches_80_percent')}`",
        "",
        "## Status Counts",
        "",
        "| Status | Count |",
        "| --- | ---: |",
    ]
    for status, count in (summary.get("comparison_status_counts") or {}).items():
        lines.append(f"| {status} | {count} |")
    lines.append("")
    return "\n".join(lines)


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    recommendation = report.get("recommendation") or {}
    lines = [
        "# Mapper Comparison Summary - Feature #18E-C",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| total_observations | {summary.get('total_observations')} |",
        f"| deterministic_coverage_rate | {summary.get('deterministic_coverage_rate')} |",
        f"| qwen_comparable_observations | {summary.get('qwen_comparable_observations')} |",
        f"| qwen_coverage_rate | {summary.get('qwen_coverage_rate')} |",
        f"| combined_coverage_rate | {summary.get('combined_coverage_rate')} |",
        f"| high_risk_conflict_count | {summary.get('high_risk_conflict_count')} |",
        "",
        f"- Recommended next feature: {recommendation.get('recommended_next_feature')}",
        f"- Reason: {recommendation.get('reason')}",
        "",
    ]
    return "\n".join(lines)


def render_conflicts_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Mapper Comparison Conflicts - Feature #18E-C",
        "",
        f"- Conflict count: `{summary.get('conflict_count')}`",
        f"- High-risk conflicts: `{summary.get('high_risk_conflict_count')}`",
        "",
        "| Sample | Label | Deterministic | Qwen | Reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for record in (report.get("conflicts") or [])[:80]:
        lines.append(
            f"| {record.get('sample_id')} | {record.get('pdf_label')} | "
            f"{record.get('deterministic_qname')} | {record.get('qwen_qname')} | {record.get('conflict_reason')} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_uncovered_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Mapper Comparison Uncovered Rows - Feature #18E-C",
        "",
        f"- Uncovered count: `{summary.get('uncovered_count')}`",
        f"- Uncovered rate: `{summary.get('uncovered_rate')}`",
        f"- Rows with Qwen missing locally: `{summary.get('uncovered_with_qwen_missing')}`",
        f"- Rows with Qwen abstention: `{summary.get('uncovered_with_qwen_abstention')}`",
        "",
        "| Label | Count |",
        "| --- | ---: |",
    ]
    for item in summary.get("top_uncovered_labels") or []:
        lines.append(f"| {item.get('normalized_label')} | {item.get('count')} |")
    lines.append("")
    return "\n".join(lines)


def render_policy_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Hybrid Mapper Policy - Feature #18E-C",
        "",
        f"- Safe for auto-apply: `{summary.get('safe_for_auto_apply')}`",
        f"- Human review final: `{summary.get('human_review_final')}`",
        f"- Confirmed tag automation: `{summary.get('confirmed_tag_id_automation')}`",
        f"- Combined coverage: `{summary.get('combined_coverage_rate')}`",
        f"- Hybrid reaches 80%: `{summary.get('hybrid_reaches_80_percent')}`",
        f"- Recommended next feature: {summary.get('recommended_next_feature')}",
        "",
        "| When | Action |",
        "| --- | --- |",
    ]
    for rule in report.get("policy_rules") or []:
        lines.append(f"| {rule.get('when')} | {rule.get('action')} |")
    lines.append("")
    return "\n".join(lines)


def write_reports(reports: Mapping[str, Mapping[str, Any]], *, output_dir: str | Path) -> dict[str, str]:
    root = Path(output_dir)
    paths = {
        "comparison_json": root / "mapper_comparison_18e_c.json",
        "comparison_md": root / "mapper_comparison_18e_c.md",
        "summary_json": root / "mapper_comparison_summary_18e_c.json",
        "summary_md": root / "mapper_comparison_summary_18e_c.md",
        "conflicts_json": root / "mapper_comparison_conflicts_18e_c.json",
        "conflicts_md": root / "mapper_comparison_conflicts_18e_c.md",
        "uncovered_json": root / "mapper_comparison_uncovered_18e_c.json",
        "uncovered_md": root / "mapper_comparison_uncovered_18e_c.md",
        "hybrid_policy_json": root / "hybrid_mapper_policy_18e_c.json",
        "hybrid_policy_md": root / "hybrid_mapper_policy_18e_c.md",
    }
    write_json(paths["comparison_json"], reports["comparison"])
    paths["comparison_md"].write_text(render_comparison_markdown(reports["comparison"]), encoding="utf-8")
    write_json(paths["summary_json"], reports["summary"])
    paths["summary_md"].write_text(render_summary_markdown(reports["summary"]), encoding="utf-8")
    write_json(paths["conflicts_json"], reports["conflicts"])
    paths["conflicts_md"].write_text(render_conflicts_markdown(reports["conflicts"]), encoding="utf-8")
    write_json(paths["uncovered_json"], reports["uncovered"])
    paths["uncovered_md"].write_text(render_uncovered_markdown(reports["uncovered"]), encoding="utf-8")
    write_json(paths["hybrid_policy_json"], reports["hybrid_policy"])
    paths["hybrid_policy_md"].write_text(render_policy_markdown(reports["hybrid_policy"]), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}
