"""Offline golden MBRS PDF/XML mapping dataset builder for Feature #17A."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from services.reference_xbrl_parser import parse_reference_xbrl
from services.reference_xbrl_schema import clean_text, normalize_numeric_value


PROJECT_ROOT = Path(__file__).resolve().parents[1]
NUMERIC_ROW_TYPES = {"numeric_fact", "comparative_numeric_fact", "subtotal_or_total"}
ALIGNABLE_ROW_TYPES = NUMERIC_ROW_TYPES | {"text_block"}
DEFAULT_TEMPLATE_PATH = PROJECT_ROOT / "mpers_templates.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _normalize_label(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _normalize_text(value))).strip()


def _token_overlap(left: Any, right: Any) -> float:
    left_tokens = set(_normalize_label(left).split())
    right_tokens = set(_normalize_label(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _similarity(left: Any, right: Any) -> float:
    left_text = _normalize_label(left)
    right_text = _normalize_label(right)
    if not left_text or not right_text:
        return 0.0
    return max(SequenceMatcher(None, left_text, right_text).ratio(), _token_overlap(left_text, right_text))


def _local_name(qname: Any) -> str:
    return str(qname or "").split(":")[-1]


def _concept_label(qname: Any) -> str:
    value = _local_name(qname)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    return value


def _period_year(fact: Mapping[str, Any]) -> int | None:
    value = fact.get("instant") or fact.get("period_end") or fact.get("period_start")
    match = re.match(r"(\d{4})", str(value or ""))
    return int(match.group(1)) if match else None


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _resolve_path(value: str | Path, *, case_dir: Path | None = None) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if case_dir is not None and (case_dir / path).exists():
        return case_dir / path
    return PROJECT_ROOT / path


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def discover_golden_cases(cases_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(cases_dir)
    cases = []
    for case_dir in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda item: item.name):
        metadata_path = case_dir / "metadata.json"
        metadata = _read_json(metadata_path) if metadata_path.exists() else {}
        pdf_path = case_dir / "source.pdf"
        reference_path = case_dir / "reference.xml"
        cases.append(
            {
                "case_id": case_dir.name,
                "case_dir": case_dir,
                "pdf_path": pdf_path,
                "reference_path": reference_path,
                "metadata_path": metadata_path if metadata_path.exists() else None,
                "metadata": metadata,
                "status": "ready" if pdf_path.exists() and reference_path.exists() else "incomplete",
            }
        )
    return cases


def _case_aliases(case: Mapping[str, Any]) -> set[str]:
    metadata = case.get("metadata") or {}
    aliases = {
        str(case.get("case_id") or ""),
        str(metadata.get("source_case_id") or ""),
        str(metadata.get("azure_di_case_id") or ""),
        Path(str(metadata.get("source_case_dir") or "")).name,
        Path(str(case.get("pdf_path") or "")).stem,
    }
    return {_normalize_label(value) for value in aliases if value}


def _extract_rows_from_report(report: Any, case: Mapping[str, Any]) -> list[dict[str, Any]]:
    if isinstance(report, list):
        return [dict(row) for row in report if isinstance(row, Mapping)]
    if not isinstance(report, Mapping):
        return []
    if isinstance(report.get("candidates"), list):
        return [dict(row) for row in report["candidates"] if isinstance(row, Mapping)]
    if isinstance(report.get("rows"), list):
        return [dict(row) for row in report["rows"] if isinstance(row, Mapping)]
    aliases = _case_aliases(case)
    for case_report in report.get("case_reports") or []:
        if _normalize_label(case_report.get("case_id")) in aliases:
            return [dict(row) for row in case_report.get("candidates") or [] if isinstance(row, Mapping)]
    return []


def _candidate_id(row: Mapping[str, Any]) -> str | None:
    for key in ("original_candidate_id", "source_candidate_id", "candidate_id", "mapping_input_id", "row_id"):
        if row.get(key):
            return str(row[key])
    return None


def _prediction_index(report_paths: Iterable[Path], *, prediction_kind: str) -> tuple[dict[str, str], dict[tuple[str, str, str], str]]:
    by_id: dict[str, str] = {}
    by_row: dict[tuple[str, str, str], str] = {}
    for path in report_paths:
        if not path.exists():
            continue
        report = _read_json(path)
        records = report.get("mapping_records") or report.get("rows") or []
        for record in records:
            if not isinstance(record, Mapping):
                continue
            suggestion = record.get("top_suggestion") or record.get("suggestion") or {}
            qname = (
                suggestion.get("concept_qname")
                or suggestion.get("selected_template_field_id")
                or record.get(f"{prediction_kind}_concept_qname")
            )
            if not qname:
                continue
            for key in ("source_candidate_id", "original_candidate_id", "candidate_id", "mapping_input_id", "row_id"):
                if record.get(key):
                    by_id[str(record[key])] = str(qname)
            row_key = (
                _normalize_label(record.get("case_id")),
                _normalize_label(record.get("label") or record.get("extracted_label")),
                str(normalize_numeric_value(record.get("value") or record.get("extracted_value")) or ""),
            )
            by_row[row_key] = str(qname)
    return by_id, by_row


def _attach_predictions(
    rows: list[dict[str, Any]],
    *,
    case: Mapping[str, Any],
    deterministic_indexes: tuple[dict[str, str], dict[tuple[str, str, str], str]],
    qwen_indexes: tuple[dict[str, str], dict[tuple[str, str, str], str]],
) -> None:
    case_name = _normalize_label((case.get("metadata") or {}).get("azure_di_case_id") or case.get("case_id"))
    for row in rows:
        candidate_id = _candidate_id(row)
        row_key = (
            _normalize_label(row.get("case_id") or case_name),
            _normalize_label(row.get("label") or row.get("extracted_label")),
            str(normalize_numeric_value(row.get("value") or row.get("extracted_value")) or ""),
        )
        if not row.get("deterministic_concept_qname"):
            row["deterministic_concept_qname"] = deterministic_indexes[0].get(candidate_id or "") or deterministic_indexes[1].get(row_key)
        if not row.get("qwen_concept_qname"):
            row["qwen_concept_qname"] = qwen_indexes[0].get(candidate_id or "") or qwen_indexes[1].get(row_key)


def _metadata_report_paths(case: Mapping[str, Any], key: str) -> list[Path]:
    value = (case.get("metadata") or {}).get(key)
    if not value:
        return []
    values = value if isinstance(value, list) else [value]
    return [_resolve_path(item, case_dir=case.get("case_dir")) for item in values]


def load_normalized_extraction_rows(
    case: Mapping[str, Any],
    *,
    report_paths: Sequence[str | Path] = (),
) -> tuple[list[dict[str, Any]], list[str]]:
    paths = []
    local_path = Path(case["case_dir"]) / "normalized_extraction.json"
    if local_path.exists():
        paths.append(local_path)
    paths.extend(_metadata_report_paths(case, "azure_di_normalized_extraction_report"))
    paths.extend(_resolve_path(path) for path in report_paths)
    sources: list[str] = []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        resolved = path.resolve()
        if str(resolved) in seen or not path.exists():
            continue
        seen.add(str(resolved))
        extracted = _extract_rows_from_report(_read_json(path), case)
        if extracted:
            rows.extend(extracted)
            sources.append(_display_path(path))
            break
    return rows, sources


def _load_template_qnames(template_path: Path = DEFAULT_TEMPLATE_PATH) -> dict[str, str]:
    if not template_path.exists():
        return {}
    found: dict[str, str] = {}

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if isinstance(key, str) and ":" in key:
                    found.setdefault(key.lower(), key)
                if key in {"id", "xbrl_tag", "qname", "template_field_id"} and isinstance(nested, str) and ":" in nested:
                    found.setdefault(nested.lower(), nested)
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(_read_json(template_path))
    return found


def _statement_match(row: Mapping[str, Any], fact: Mapping[str, Any]) -> bool:
    section = _normalize_label(row.get("statement_type") or row.get("statement_section"))
    concept = _normalize_label(_concept_label(fact.get("qname")))
    if not section or not concept:
        return False
    groups = (
        {"financial position", "asset", "liabilit", "equity"},
        {"comprehensive income", "income", "expense", "revenue", "profit", "loss"},
        {"cash flow", "cash"},
        {"notes", "disclosure", "policy", "explanatory"},
    )
    return any(any(token in section for token in group) and any(token in concept for token in group) for group in groups)


def _row_value_options(row: Mapping[str, Any]) -> list[tuple[str, str, int | None]]:
    values = []
    current = normalize_numeric_value(row.get("value") or row.get("extracted_value"))
    previous = normalize_numeric_value(row.get("previous_value") or row.get("value_previous_year"))
    if current is not None:
        values.append(("current", current, _safe_year(row.get("current_year"))))
    if previous is not None:
        values.append(("prior", previous, _safe_year(row.get("prior_year"))))
    return values


def _safe_year(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _text_match(row: Mapping[str, Any], fact: Mapping[str, Any]) -> float:
    row_text = _normalize_text(row.get("text") or row.get("source_snippet") or row.get("value"))
    fact_text = _normalize_text(fact.get("value"))
    if not row_text or not fact_text:
        return 0.0
    if row_text in fact_text or fact_text in row_text:
        return min(len(row_text), len(fact_text)) / max(len(row_text), len(fact_text))
    return SequenceMatcher(None, row_text, fact_text).ratio()


def _score_fact(row: Mapping[str, Any], fact: Mapping[str, Any]) -> dict[str, Any] | None:
    row_type = str(row.get("row_type") or "")
    label_similarity = _similarity(row.get("label") or row.get("extracted_label"), _concept_label(fact.get("qname")))
    statement_match = _statement_match(row, fact)
    context_evidence = bool(fact.get("context_ref"))
    unit_evidence = bool(fact.get("unit_ref"))
    period_match = False
    value_role = None
    value_match = False
    text_similarity = 0.0

    if row_type in NUMERIC_ROW_TYPES:
        if not fact.get("is_numeric") or fact.get("is_nil"):
            return None
        fact_value = fact.get("normalized_value")
        options = [option for option in _row_value_options(row) if option[1] == fact_value]
        if not options:
            return None
        value_role, _value, expected_year = max(
            options,
            key=lambda option: int(option[2] is not None and option[2] == _period_year(fact)),
        )
        period_match = expected_year is not None and expected_year == _period_year(fact)
        value_match = True
        score = 0.65 + (0.25 * label_similarity) + (0.04 if statement_match else 0.0)
        score += 0.03 if period_match else 0.0
        score += 0.02 if context_evidence else 0.0
        score += 0.01 if unit_evidence else 0.0
    elif row_type == "text_block":
        if fact.get("is_numeric") or fact.get("is_nil"):
            return None
        text_similarity = _text_match(row, fact)
        if text_similarity < 0.72:
            return None
        value_match = True
        score = (0.7 * text_similarity) + (0.22 * label_similarity) + (0.05 if statement_match else 0.0)
        score += 0.03 if context_evidence else 0.0
    else:
        return None

    return {
        "fact_id": fact.get("fact_id"),
        "correct_concept_qname": fact.get("qname"),
        "context_ref": fact.get("context_ref"),
        "unit_ref": fact.get("unit_ref"),
        "period": fact.get("period"),
        "dimensions": fact.get("dimensions") or [],
        "decimals": fact.get("decimals"),
        "value_role": value_role,
        "score": round(min(score, 1.0), 4),
        "evidence": {
            "value_match": value_match,
            "text_similarity": round(text_similarity, 4),
            "label_similarity": round(label_similarity, 4),
            "statement_match": statement_match,
            "period_match": period_match,
            "context_evidence": context_evidence,
            "unit_evidence": unit_evidence,
        },
    }


def align_extracted_row(
    *,
    case_id: str,
    row: Mapping[str, Any],
    facts: Sequence[Mapping[str, Any]],
    template_qnames: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    row_id = _candidate_id(row) or f"{case_id}:row"
    base = {
        "source_case_id": case_id,
        "extracted_row_id": row_id,
        "extracted_label": row.get("label") or row.get("extracted_label"),
        "extracted_value": row.get("value") or row.get("extracted_value"),
        "previous_value": row.get("previous_value") or row.get("value_previous_year"),
        "statement_type": row.get("statement_type") or row.get("statement_section"),
        "row_type": row.get("row_type"),
        "deterministic_concept_qname": row.get("deterministic_concept_qname"),
        "qwen_concept_qname": row.get("qwen_concept_qname"),
    }
    if str(row.get("row_type") or "") not in ALIGNABLE_ROW_TYPES:
        return {**base, "alignment_status": "unaligned", "reason": "row_type_not_alignable", "candidate_facts": []}

    candidates = [candidate for fact in facts if (candidate := _score_fact(row, fact)) is not None]
    candidates.sort(key=lambda item: (-float(item["score"]), str(item["correct_concept_qname"]), str(item["fact_id"])))
    if not candidates:
        return {**base, "alignment_status": "unaligned", "reason": "no_reference_value_match", "candidate_facts": []}

    concept_candidates: list[dict[str, Any]] = []
    seen_concepts: set[str] = set()
    for candidate in candidates:
        qname = str(candidate.get("correct_concept_qname") or "")
        if qname not in seen_concepts:
            seen_concepts.add(qname)
            concept_candidates.append(candidate)
    top = concept_candidates[0]
    runner_up = concept_candidates[1] if len(concept_candidates) > 1 else None
    gap = round(float(top["score"]) - float(runner_up["score"]), 4) if runner_up else None
    same_qname_periods = {
        json.dumps(candidate.get("period") or {}, sort_keys=True)
        for candidate in candidates
        if candidate.get("correct_concept_qname") == top.get("correct_concept_qname")
    }
    row_values = _row_value_options(row)
    current_prior_ambiguity = len(same_qname_periods) > 1 and len(row_values) <= 1 and not top["evidence"]["period_match"]
    identical_current_prior = len(row_values) > 1 and row_values[0][1] == row_values[1][1]
    close_competing_concept = bool(
        runner_up
        and gap is not None
        and gap < 0.05
        and float(top["evidence"]["label_similarity"]) < 0.85
    )
    ambiguous = bool(
        current_prior_ambiguity
        or identical_current_prior
        or close_competing_concept
    )
    strong = not ambiguous and float(top["score"]) >= 0.8
    qname = str(top.get("correct_concept_qname") or "")
    template_field_id = (template_qnames or {}).get(qname.lower())
    reason = "clear_high_evidence_alignment" if strong else "multiple_plausible_reference_facts" if ambiguous else "insufficient_alignment_evidence"
    return {
        **base,
        "alignment_status": "strong" if strong else "ambiguous" if ambiguous else "unaligned",
        "reason": reason,
        "correct_concept_qname": qname if strong else None,
        "correct_template_field_id": template_field_id if strong else None,
        "evidence": top.get("evidence"),
        "alignment_score": top.get("score"),
        "score_gap_to_runner_up": gap,
        "current_prior_ambiguity": current_prior_ambiguity or identical_current_prior,
        "candidate_facts": candidates[:5],
    }


def _gold_example(alignment: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "extracted_label": alignment.get("extracted_label"),
        "extracted_value": alignment.get("extracted_value"),
        "statement_type": alignment.get("statement_type"),
        "correct_concept_qname": alignment.get("correct_concept_qname"),
        "correct_template_field_id": alignment.get("correct_template_field_id"),
        "evidence": alignment.get("evidence"),
        "reason": alignment.get("reason"),
        "source_case_id": alignment.get("source_case_id"),
    }


def _baseline_metrics(gold_alignments: Sequence[Mapping[str, Any]], prediction_key: str) -> dict[str, Any]:
    measured = [row for row in gold_alignments if row.get(prediction_key)]
    correct = [
        row for row in measured
        if str(row.get(prediction_key)).lower() == str(row.get("correct_concept_qname")).lower()
    ]
    return {
        "measurable_rows": len(measured),
        "correct_rows": len(correct),
        "accuracy": round(len(correct) / len(measured), 4) if measured else None,
    }


def _report_metadata(cases_dir: Path) -> dict[str, Any]:
    return {
        "feature": "17A",
        "generated_at": _utc_now(),
        "cases_dir": _display_path(cases_dir),
        "read_only": True,
        "database_mutated": False,
        "production_behavior_changed": False,
        "production_azure_di_extraction_changed": False,
        "qwen_prompt_changed": False,
        "react_ui_changed": False,
        "confirmed_tag_id_set": False,
        "external_llm_called": False,
        "auditor_xml_sent_to_external_provider": False,
        "arelle_feedback_loop_run": False,
    }


def build_golden_mbrs_reports(
    *,
    cases_dir: str | Path,
    normalized_extraction_reports: Sequence[str | Path] = (),
    deterministic_mapping_reports: Sequence[str | Path] = (),
    qwen_mapping_reports: Sequence[str | Path] = (),
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = Path(cases_dir)
    cases = discover_golden_cases(root)
    template_qnames = _load_template_qnames(Path(template_path))
    case_summaries = []
    alignments = []
    all_facts: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []

    for case in cases:
        if case["status"] != "ready":
            case_summaries.append({"case_id": case["case_id"], "status": "incomplete_pair"})
            continue
        reference = parse_reference_xbrl(case["case_id"], case["reference_path"], "xml")
        facts = reference.get("facts") or []
        rows, extraction_sources = load_normalized_extraction_rows(case, report_paths=normalized_extraction_reports)
        deterministic_paths = [*_metadata_report_paths(case, "deterministic_mapping_report"), *(_resolve_path(path) for path in deterministic_mapping_reports)]
        qwen_paths = [*_metadata_report_paths(case, "qwen_mapping_report"), *(_resolve_path(path) for path in qwen_mapping_reports)]
        _attach_predictions(
            rows,
            case=case,
            deterministic_indexes=_prediction_index(deterministic_paths, prediction_kind="deterministic"),
            qwen_indexes=_prediction_index(qwen_paths, prediction_kind="qwen"),
        )
        case_alignments = [
            align_extracted_row(case_id=case["case_id"], row=row, facts=facts, template_qnames=template_qnames)
            for row in rows
        ]
        all_facts.extend(facts)
        all_rows.extend(rows)
        alignments.extend(case_alignments)
        case_summaries.append(
            {
                "case_id": case["case_id"],
                "status": "ready",
                "pdf_path": _display_path(case["pdf_path"]),
                "reference_path": _display_path(case["reference_path"]),
                "normalized_extraction_status": "consumed" if rows else "missing_local_capture",
                "normalized_extraction_sources": extraction_sources,
                "total_xml_facts": len(facts),
                "total_extracted_rows": len(rows),
                "strong_gold_examples": sum(1 for row in case_alignments if row["alignment_status"] == "strong"),
                "ambiguous_alignments": sum(1 for row in case_alignments if row["alignment_status"] == "ambiguous"),
                "unaligned_rows": sum(1 for row in case_alignments if row["alignment_status"] == "unaligned"),
            }
        )

    gold_alignments = [row for row in alignments if row["alignment_status"] == "strong"]
    ambiguous = [row for row in alignments if row["alignment_status"] == "ambiguous"]
    unaligned = [row for row in alignments if row["alignment_status"] == "unaligned"]
    matched_values = [row for row in alignments if (row.get("evidence") or {}).get("value_match")]
    unique_gold_concepts = {row.get("correct_concept_qname") for row in gold_alignments if row.get("correct_concept_qname")}
    unique_reference_concepts = {fact.get("qname") for fact in all_facts if fact.get("qname")}
    metrics = {
        "total_cases": len(cases),
        "ready_pdf_xml_pairs": sum(1 for case in case_summaries if case.get("status") == "ready"),
        "cases_with_normalized_azure_di_extraction": sum(1 for case in case_summaries if case.get("normalized_extraction_status") == "consumed"),
        "cases_missing_normalized_azure_di_extraction": sum(1 for case in case_summaries if case.get("normalized_extraction_status") == "missing_local_capture"),
        "total_extracted_rows": len(all_rows),
        "total_xml_facts": len(all_facts),
        "aligned_rows": len(gold_alignments),
        "unaligned_rows": len(unaligned),
        "strong_gold_examples": len(gold_alignments),
        "ambiguous_alignments": len(ambiguous),
        "concept_coverage": {
            "strong_gold_concepts": len(unique_gold_concepts),
            "reference_concepts": len(unique_reference_concepts),
            "ratio": round(len(unique_gold_concepts) / len(unique_reference_concepts), 4) if unique_reference_concepts else 0.0,
        },
        "value_match_rate": round(len(matched_values) / len(all_rows), 4) if all_rows else 0.0,
        "current_prior_ambiguity": sum(1 for row in alignments if row.get("current_prior_ambiguity")),
    }
    metadata = _report_metadata(root)
    summary = {
        "run_metadata": metadata,
        "metrics": metrics,
        "cases": case_summaries,
        "limitations": [
            "Only local normalized Azure DI reports are consumed; missing captures are reported explicitly.",
            "Strong gold examples are conservative alignments, not automatically applied mappings.",
            "Auditor XML remains local and is not sent to any external provider or LLM.",
        ],
    }
    alignment_report = {
        "run_metadata": metadata,
        "metrics": metrics,
        "gold_examples": [_gold_example(row) for row in gold_alignments],
        "ambiguous_alignments": ambiguous,
        "unaligned_rows": unaligned,
        "alignments": alignments,
    }
    baseline = {
        "run_metadata": metadata,
        "metrics": metrics,
        "deterministic_mapping_accuracy": _baseline_metrics(gold_alignments, "deterministic_concept_qname"),
        "qwen_mapping_accuracy": _baseline_metrics(gold_alignments, "qwen_concept_qname"),
        "measurement_policy": "Accuracy is reported only for strong gold rows that also have a local baseline prediction.",
    }
    return summary, alignment_report, baseline


def render_summary_markdown(report: Mapping[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    lines = ["# Golden MBRS Dataset Summary - Feature #17A", "", "## Metrics", ""]
    for key, value in metrics.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Cases", "", "| Case | Pair | Azure DI | XML Facts | Extracted Rows | Strong Gold | Ambiguous | Unaligned |", "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"])
    for case in report.get("cases") or []:
        lines.append(
            f"| {case.get('case_id')} | {case.get('status')} | {case.get('normalized_extraction_status', 'n/a')} | "
            f"{case.get('total_xml_facts', 0)} | {case.get('total_extracted_rows', 0)} | "
            f"{case.get('strong_gold_examples', 0)} | {case.get('ambiguous_alignments', 0)} | {case.get('unaligned_rows', 0)} |"
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report.get("limitations") or [])
    lines.append("")
    return "\n".join(lines)


def render_alignment_markdown(report: Mapping[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    return "\n".join(
        [
            "# Golden MBRS Mapping Alignment - Feature #17A",
            "",
            f"- Strong gold examples: {metrics.get('strong_gold_examples', 0)}",
            f"- Ambiguous alignments: {metrics.get('ambiguous_alignments', 0)}",
            f"- Unaligned rows: {metrics.get('unaligned_rows', 0)}",
            f"- Current/prior ambiguity: {metrics.get('current_prior_ambiguity', 0)}",
            "",
            "Ambiguous rows remain flagged and are not promoted into gold examples.",
            "",
        ]
    )


def render_baseline_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# Golden MBRS Evaluation Baseline - Feature #17A",
            "",
            f"- Deterministic mapping accuracy: {report.get('deterministic_mapping_accuracy')}",
            f"- Qwen mapping accuracy: {report.get('qwen_mapping_accuracy')}",
            f"- Policy: {report.get('measurement_policy')}",
            "",
        ]
    )


def write_golden_mbrs_reports(
    *,
    cases_dir: str | Path,
    output_dir: str | Path,
    normalized_extraction_reports: Sequence[str | Path] = (),
    deterministic_mapping_reports: Sequence[str | Path] = (),
    qwen_mapping_reports: Sequence[str | Path] = (),
) -> dict[str, Any]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    summary, alignment, baseline = build_golden_mbrs_reports(
        cases_dir=cases_dir,
        normalized_extraction_reports=normalized_extraction_reports,
        deterministic_mapping_reports=deterministic_mapping_reports,
        qwen_mapping_reports=qwen_mapping_reports,
    )
    paths = {
        "summary_json": output / "golden_mbrs_dataset_summary_17a.json",
        "summary_md": output / "golden_mbrs_dataset_summary_17a.md",
        "alignment_json": output / "golden_mbrs_mapping_alignment_17a.json",
        "alignment_md": output / "golden_mbrs_mapping_alignment_17a.md",
        "baseline_json": output / "golden_mbrs_evaluation_baseline_17a.json",
        "baseline_md": output / "golden_mbrs_evaluation_baseline_17a.md",
    }
    for path, payload in (
        (paths["summary_json"], summary),
        (paths["alignment_json"], alignment),
        (paths["baseline_json"], baseline),
    ):
        path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    paths["summary_md"].write_text(render_summary_markdown(summary), encoding="utf-8")
    paths["alignment_md"].write_text(render_alignment_markdown(alignment), encoding="utf-8")
    paths["baseline_md"].write_text(render_baseline_markdown(baseline), encoding="utf-8")
    return {"paths": paths, "summary": summary, "alignment": alignment, "baseline": baseline}
