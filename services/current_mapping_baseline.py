"""Report-only current mapping baseline against the local Golden MBRS dataset."""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.azure_di_production_mapping import (
    TEMPLATE_CODE_FAMILY,
    diagnose_azure_di_candidate_mapping,
    normalize_text,
    strip_note_references,
)
from services.golden_mbrs_dataset import (
    PROJECT_ROOT,
    discover_golden_cases,
    load_normalized_extraction_rows,
)
from services.llm_taxonomy_mapping import (
    HuggingFaceQwenMappingClient,
    LLMMappingRateLimitError,
    _candidate_rows_for_llm,
    _hard_precheck_rejection_reason,
    build_mapping_prompt,
    is_rate_limit_error,
    load_llm_mapping_config,
    parse_llm_json_response,
    validate_llm_mapping_output,
)
from services.xbrl_template_service import get_xbrl_template_service


DEFAULT_ALIGNMENT_REPORT = PROJECT_ROOT / "reports" / "golden_mbrs_mapping_alignment_17a.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "reports"
OUTPUT_STEM_PREDICTIONS = "golden_mbrs_current_mapping_predictions_17b_pre"
OUTPUT_STEM_ACCURACY = "golden_mbrs_current_mapping_accuracy_17b_pre"
OUTPUT_STEM_ERRORS = "golden_mbrs_mapping_error_analysis_17b_pre"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _candidate_id(row: Mapping[str, Any]) -> str:
    for key in ("original_candidate_id", "source_candidate_id", "candidate_id", "mapping_input_id", "row_id"):
        if row.get(key):
            return str(row[key])
    return ""


def _safe_label_family(value: Any) -> str:
    label = normalize_text(strip_note_references(value))
    label = re.sub(r"^(?:total|net)\s+", "", label).strip()
    return label or "(empty)"


def _prediction_qname(prediction: Mapping[str, Any] | None) -> str | None:
    if not prediction:
        return None
    value = prediction.get("predicted_concept_qname") or prediction.get("predicted_template_field_id")
    return str(value) if value else None


def _concept_families(qname: Any) -> set[str]:
    concept = str(qname or "")
    if not concept:
        return set()
    service = get_xbrl_template_service()
    return {
        TEMPLATE_CODE_FAMILY[code]
        for code in service.templates_by_concept.get(concept, [])
        if code in TEMPLATE_CODE_FAMILY
    }


def _statement_family_match(expected_qname: Any, predicted_qname: Any) -> bool | None:
    expected = _concept_families(expected_qname)
    predicted = _concept_families(predicted_qname)
    if not expected or not predicted:
        return None
    return bool(expected & predicted)


def load_golden_prediction_inputs(
    *,
    golden_dir: str | Path,
    alignment_report_path: str | Path = DEFAULT_ALIGNMENT_REPORT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Load local strong rows for strict scoring and ambiguous rows for diagnostics."""

    alignment_report = _read_json(alignment_report_path)
    row_index: dict[tuple[str, str], dict[str, Any]] = {}
    capture_sources: dict[str, list[str]] = {}
    for case in discover_golden_cases(golden_dir):
        rows, sources = load_normalized_extraction_rows(case)
        case_id = str(case["case_id"])
        capture_sources[case_id] = sources
        for row in rows:
            row_index[(case_id, _candidate_id(row))] = dict(row)

    strict_rows: list[dict[str, Any]] = []
    for alignment in alignment_report.get("alignments") or []:
        if alignment.get("alignment_status") != "strong":
            continue
        case_id = str(alignment.get("source_case_id") or "")
        extracted_row_id = str(alignment.get("extracted_row_id") or "")
        source = dict(row_index.get((case_id, extracted_row_id)) or {})
        strict_rows.append(
            {
                "source_case_id": case_id,
                "extracted_row_id": extracted_row_id,
                "extracted_label": alignment.get("extracted_label"),
                "extracted_value": alignment.get("extracted_value"),
                "previous_value": alignment.get("previous_value"),
                "statement_type": alignment.get("statement_type"),
                "row_type": alignment.get("row_type"),
                "page_number": source.get("page_number"),
                "source_candidate": source,
                "correct_concept_qname": alignment.get("correct_concept_qname"),
                "correct_template_field_id": alignment.get("correct_template_field_id"),
                "gold_alignment_reason": alignment.get("reason"),
                "gold_alignment_evidence": alignment.get("evidence") or {},
            }
        )

    ambiguous_rows = [
        {
            "source_case_id": row.get("source_case_id"),
            "extracted_row_id": row.get("extracted_row_id"),
            "extracted_label": row.get("extracted_label"),
            "extracted_value": row.get("extracted_value"),
            "statement_type": row.get("statement_type"),
            "reason": row.get("reason"),
            "candidate_fact_count": len(row.get("candidate_facts") or []),
            "current_prior_ambiguity": bool(row.get("current_prior_ambiguity")),
        }
        for row in alignment_report.get("ambiguous_alignments") or []
    ]
    return strict_rows, ambiguous_rows, {
        "alignment_report": str(Path(alignment_report_path)),
        "normalized_capture_sources": capture_sources,
        "strict_scoring_rows": len(strict_rows),
        "ambiguous_diagnostic_rows": len(ambiguous_rows),
    }


def _candidate_for_prediction(row: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(row.get("source_candidate") or {})
    source.setdefault("row_type", row.get("row_type"))
    source.setdefault("label", row.get("extracted_label"))
    source.setdefault("value", row.get("extracted_value"))
    source.setdefault("previous_value", row.get("previous_value"))
    source.setdefault("statement_section", row.get("statement_type"))
    source.setdefault("page_number", row.get("page_number"))
    return source


def _prediction_input(row: Mapping[str, Any]) -> dict[str, Any]:
    """Provider-safe input. Deliberately excludes XML paths, facts, and gold answers."""

    return {
        "source_case_id": row.get("source_case_id"),
        "extracted_row_id": row.get("extracted_row_id"),
        "extracted_label": row.get("extracted_label"),
        "extracted_value": row.get("extracted_value"),
        "previous_value": row.get("previous_value"),
        "statement_type": row.get("statement_type"),
        "row_type": row.get("row_type"),
        "page_number": row.get("page_number"),
    }


def _qwen_row_context(row: Mapping[str, Any]) -> dict[str, Any]:
    prediction_input = _prediction_input(row)
    return {
        "extracted_data_item_id": prediction_input["extracted_row_id"],
        "extracted_label": prediction_input["extracted_label"],
        "extracted_value": prediction_input["extracted_value"],
        "value_previous_year": prediction_input["previous_value"],
        "financial_year": (row.get("source_candidate") or {}).get("current_year"),
        "financial_year_previous": (row.get("source_candidate") or {}).get("prior_year"),
        "statement_type": prediction_input["statement_type"],
        "page_number": prediction_input["page_number"],
        "nearby_rows": [],
    }


def build_qwen_prompt_for_record(row: Mapping[str, Any], candidate_concepts: Sequence[Mapping[str, Any]]) -> str:
    """Build the existing candidate-constrained prompt without local answer-key fields."""

    return build_mapping_prompt(_qwen_row_context(row), candidate_concepts)


def _deterministic_prediction(row: Mapping[str, Any]) -> dict[str, Any]:
    candidate = _candidate_for_prediction(row)
    diagnosis = diagnose_azure_di_candidate_mapping(candidate)
    matches = diagnosis.get("top_candidate_matches") or []
    predicted = diagnosis.get("template_field_id")
    return {
        "status": "predicted" if predicted else "no_prediction",
        "predicted_concept_qname": predicted,
        "predicted_template_field_id": predicted,
        "confidence": diagnosis.get("mapping_score") or 0.0,
        "confidence_tier": "high" if predicted else None,
        "reason": diagnosis.get("mapping_method") or diagnosis.get("mapping_rejection_reason"),
        "classified_statement_type": diagnosis.get("classified_statement_type"),
        "classified_template_code": diagnosis.get("classified_template_code"),
        "candidate_concepts": matches,
    }


def _qwen_candidates(row: Mapping[str, Any], *, max_candidates: int) -> tuple[list[dict[str, Any]], str | None]:
    candidate = _candidate_for_prediction(row)
    diagnosis = diagnose_azure_di_candidate_mapping(candidate)
    rejection = _hard_precheck_rejection_reason(candidate, diagnosis)
    if rejection:
        return [], rejection
    candidates = _candidate_rows_for_llm(candidate, limit=max_candidates)
    return candidates, None if candidates else "rejected_no_template_candidate"


def _blocked_qwen_prediction(reason: str, candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "status": "blocked",
        "predicted_concept_qname": None,
        "predicted_template_field_id": None,
        "confidence": 0.0,
        "confidence_tier": None,
        "reason": reason,
        "candidate_concepts": list(candidates),
        "external_llm_called": False,
        "hallucinated_concept": False,
    }


async def _live_qwen_prediction(
    row: Mapping[str, Any],
    *,
    candidates: Sequence[Mapping[str, Any]],
    llm_client: Any,
    config: Any,
    max_rate_limit_retries: int,
    rate_limit_backoff_seconds: float,
) -> dict[str, Any]:
    prompt = build_qwen_prompt_for_record(row, candidates)
    rate_limit_retries = 0
    while True:
        try:
            raw = await llm_client.complete(prompt, config=config)
            parsed, parse_error, _raw_text, _parsed_content, response_shape = parse_llm_json_response(raw)
            break
        except Exception as exc:
            if not is_rate_limit_error(exc):
                return {
                    **_blocked_qwen_prediction(f"llm_call_failed: {exc}", candidates),
                    "status": "provider_error",
                    "external_llm_called": True,
                    "rate_limit_retries": rate_limit_retries,
                }
            if rate_limit_retries >= max_rate_limit_retries:
                raise LLMMappingRateLimitError("AI provider is rate limited.") from exc
            await asyncio.sleep(rate_limit_backoff_seconds * (2**rate_limit_retries))
            rate_limit_retries += 1
    suggestion = validate_llm_mapping_output(
        parsed,
        candidates=candidates,
        high_confidence_threshold=config.high_confidence_threshold,
        min_display_confidence=config.min_display_confidence,
        min_manual_confidence=config.min_manual_confidence,
        parse_error=parse_error,
    )
    predicted = suggestion.get("selected_template_field_id") if suggestion.get("status") == "suggested" else None
    return {
        "status": suggestion.get("status"),
        "predicted_concept_qname": predicted,
        "predicted_template_field_id": predicted,
        "confidence": suggestion.get("confidence") or 0.0,
        "confidence_tier": suggestion.get("confidence_category"),
        "reason": suggestion.get("reason") or suggestion.get("rejection_reason"),
        "rejection_reason": suggestion.get("rejection_reason"),
        "candidate_concepts": list(candidates),
        "external_llm_called": True,
        "hallucinated_concept": bool(suggestion.get("hallucinated_concept")),
        "invalid_response": bool(suggestion.get("invalid_response")),
        "warning_level": suggestion.get("warning_level"),
        "ranked_candidates": suggestion.get("ranked_candidates") or [],
        "normalized_response_shape": response_shape,
        "rate_limit_retries": rate_limit_retries,
    }


def _candidate_missing(expected: Any, candidates: Sequence[Mapping[str, Any]]) -> bool:
    expected_id = str(expected or "")
    return bool(expected_id) and expected_id not in {
        str(row.get("template_field_id") or row.get("concept_qname") or "") for row in candidates
    }


def score_prediction_records(records: Sequence[Mapping[str, Any]], *, predictor: str) -> dict[str, Any]:
    """Score one predictor while keeping no-prediction separate from wrong-concept."""

    outcome_counts: Counter[str] = Counter()
    statement_rows: dict[str, Counter[str]] = defaultdict(Counter)
    label_rows: dict[str, Counter[str]] = defaultdict(Counter)
    confidence_rows: dict[str, Counter[str]] = defaultdict(Counter)
    confused: Counter[str] = Counter()
    family_measurable = 0
    family_correct = 0
    template_field_correct = 0
    for record in records:
        expected = str(record.get("correct_concept_qname") or "")
        expected_template_field = str(record.get("correct_template_field_id") or "")
        prediction = record.get(f"{predictor}_prediction") or {}
        predicted = _prediction_qname(prediction)
        predicted_template_field = str(prediction.get("predicted_template_field_id") or "")
        candidates = prediction.get("candidate_concepts") or []
        if _candidate_missing(expected, candidates):
            outcome_counts["candidate_missing"] += 1
        if prediction.get("hallucinated_concept"):
            outcome = "hallucinated_concept_rejected"
        elif not predicted:
            outcome = "no_prediction"
        elif predicted == expected:
            outcome = "correct"
        else:
            outcome = "wrong_concept"
            confused[f"{expected} -> {predicted}"] += 1
        outcome_counts[outcome] += 1
        if predicted:
            outcome_counts["predicted"] += 1
        if expected_template_field and predicted_template_field == expected_template_field:
            template_field_correct += 1
        if prediction.get("warning_level") == "low_confidence":
            outcome_counts["low_confidence_suggestion"] += 1
        if prediction.get("invalid_response"):
            outcome_counts["invalid_response"] += 1
        if outcome == "correct" and prediction.get("confidence_tier") not in {None, "high"}:
            outcome_counts["correct_but_not_high_confidence"] += 1

        statement = str(record.get("statement_type") or "(empty)")
        label_family = _safe_label_family(record.get("extracted_label"))
        statement_rows[statement][outcome] += 1
        label_rows[label_family][outcome] += 1
        confidence = str(prediction.get("confidence_tier") or "none")
        confidence_rows[confidence][outcome] += 1
        family_match = _statement_family_match(expected, predicted)
        if family_match is not None:
            family_measurable += 1
            family_correct += int(family_match)

    total = len(records)
    predicted_count = outcome_counts["predicted"]
    correct = outcome_counts["correct"]

    def grouped(rows: Mapping[str, Counter[str]]) -> list[dict[str, Any]]:
        result = []
        for key, counts in rows.items():
            measured = sum(counts.values())
            result.append(
                {
                    "group": key,
                    "rows": measured,
                    "correct": counts["correct"],
                    "accuracy": round(counts["correct"] / measured, 4) if measured else None,
                    "no_prediction": counts["no_prediction"],
                    "wrong_concept": counts["wrong_concept"],
                }
            )
        return sorted(result, key=lambda row: (-row["rows"], row["group"]))

    def confidence_accuracy(tier: str) -> float | None:
        counts = confidence_rows[tier]
        rows = sum(counts.values())
        return round(counts["correct"] / rows, 4) if rows else None

    return {
        "strict_scoring_rows": total,
        "predicted_rows": predicted_count,
        "coverage": round(predicted_count / total, 4) if total else None,
        "correct": correct,
        "qname_exact_correct": correct,
        "qname_exact_accuracy": round(correct / total, 4) if total else None,
        "template_field_id_exact_correct": template_field_correct,
        "template_field_id_exact_accuracy": round(template_field_correct / total, 4) if total else None,
        "accuracy": round(correct / total, 4) if total else None,
        "accuracy_when_predicted": round(correct / predicted_count, 4) if predicted_count else None,
        "wrong_concept": outcome_counts["wrong_concept"],
        "no_prediction": outcome_counts["no_prediction"],
        "candidate_missing": outcome_counts["candidate_missing"],
        "hallucinated_concept_rejected": outcome_counts["hallucinated_concept_rejected"],
        "invalid_response": outcome_counts["invalid_response"],
        "low_confidence_suggestion": outcome_counts["low_confidence_suggestion"],
        "correct_but_not_high_confidence": outcome_counts["correct_but_not_high_confidence"],
        "high_confidence_accuracy": confidence_accuracy("high"),
        "medium_confidence_accuracy": confidence_accuracy("medium"),
        "low_confidence_accuracy": confidence_accuracy("low"),
        "statement_family_measurable_rows": family_measurable,
        "statement_family_correct": family_correct,
        "statement_family_accuracy": round(family_correct / family_measurable, 4) if family_measurable else None,
        "accuracy_by_statement_type": grouped(statement_rows),
        "accuracy_by_label_family": grouped(label_rows),
        "accuracy_by_confidence_tier": grouped(confidence_rows),
        "top_confused_concepts": [
            {"pair": pair, "count": count} for pair, count in confused.most_common(15)
        ],
    }


def _report_metadata(*, use_live_llm: bool, external_llm_called: bool, qwen_status: str) -> dict[str, Any]:
    return {
        "feature": "17B-pre",
        "generated_at": _utc_now(),
        "report_only": True,
        "database_mutated": False,
        "production_filing_jobs_mutated": False,
        "production_extraction_changed": False,
        "qwen_prompt_changed": False,
        "react_ui_changed": False,
        "auto_apply_mappings": False,
        "confirmed_tag_id_set": False,
        "xbrl_generated": False,
        "arelle_run": False,
        "live_llm_requested": use_live_llm,
        "external_llm_called": external_llm_called,
        "qwen_status": qwen_status,
        "auditor_xml_sent_to_external_provider": False,
        "gold_answers_sent_to_external_provider": False,
        "external_qwen_payload_policy": "extracted row context plus locally retrieved candidate concepts only",
    }


async def build_current_mapping_baseline_reports(
    *,
    golden_dir: str | Path,
    alignment_report_path: str | Path = DEFAULT_ALIGNMENT_REPORT,
    use_live_llm: bool = False,
    llm_client: Any | None = None,
    max_rate_limit_retries: int = 2,
    rate_limit_backoff_seconds: float = 1.0,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    strict_rows, ambiguous_rows, inputs_metadata = load_golden_prediction_inputs(
        golden_dir=golden_dir,
        alignment_report_path=alignment_report_path,
    )
    config = load_llm_mapping_config()
    client = llm_client or (HuggingFaceQwenMappingClient() if use_live_llm else None)
    external_llm_called = False
    qwen_status = "completed" if use_live_llm else "blocked_live_llm_not_approved"
    rate_limited = False
    rows_blocked_by_rate_limit = 0
    provider_rate_limit_events = 0
    completed_provider_rows = 0
    records = []
    for row in strict_rows:
        candidates, precheck_reason = _qwen_candidates(row, max_candidates=config.max_candidates)
        if not use_live_llm:
            qwen = _blocked_qwen_prediction("live_qwen_not_approved", candidates)
        elif rate_limited:
            qwen = _blocked_qwen_prediction("live_qwen_rate_limited_run_stopped", candidates)
            rows_blocked_by_rate_limit += 1
        elif precheck_reason:
            qwen = {
                **_blocked_qwen_prediction(precheck_reason, candidates),
                "status": "rejected_precheck",
            }
        else:
            external_llm_called = True
            try:
                qwen = await _live_qwen_prediction(
                    row,
                    candidates=candidates,
                    llm_client=client,
                    config=config,
                    max_rate_limit_retries=max_rate_limit_retries,
                    rate_limit_backoff_seconds=rate_limit_backoff_seconds,
                )
                completed_provider_rows += 1
                provider_rate_limit_events += int(qwen.get("rate_limit_retries") or 0)
            except LLMMappingRateLimitError:
                rate_limited = True
                qwen_status = "blocked_rate_limited"
                provider_rate_limit_events += max_rate_limit_retries + 1
                rows_blocked_by_rate_limit += 1
                qwen = {
                    **_blocked_qwen_prediction("live_qwen_rate_limited_run_stopped", candidates),
                    "external_llm_called": True,
                    "rate_limit_retries": max_rate_limit_retries,
                }
        records.append(
            {
                **_prediction_input(row),
                "correct_concept_qname": row.get("correct_concept_qname"),
                "correct_template_field_id": row.get("correct_template_field_id"),
                "deterministic_prediction": _deterministic_prediction(row),
                "qwen_prediction": qwen,
                "qwen_prompt_payload_policy": "row_context_and_candidate_concepts_only_no_xml_no_gold_answers",
                "qwen_gold_candidate_missing": _candidate_missing(row.get("correct_concept_qname"), candidates),
            }
        )

    if use_live_llm and not external_llm_called and not rate_limited:
        qwen_status = "completed_without_provider_rows"
    metadata = _report_metadata(
        use_live_llm=use_live_llm,
        external_llm_called=external_llm_called,
        qwen_status=qwen_status,
    )
    deterministic_score = score_prediction_records(records, predictor="deterministic")
    qwen_score = score_prediction_records(records, predictor="qwen")
    predictions = {
        "run_metadata": metadata,
        "inputs_metadata": inputs_metadata,
        "strict_scoring_rows": records,
        "ambiguous_diagnostic_rows": ambiguous_rows,
    }
    accuracy = {
        "run_metadata": metadata,
        "strict_scoring_policy": "Only #17A strong alignments are scored. Ambiguous alignments are diagnostics only.",
        "strict_scoring_rows": len(records),
        "ambiguous_diagnostic_rows": len(ambiguous_rows),
        "deterministic_mapping": deterministic_score,
        "qwen_mapping": {
            **qwen_score,
            "measurable": use_live_llm and qwen_status in {"completed", "completed_without_provider_rows"},
            "status": qwen_status,
            "completed_provider_rows": completed_provider_rows,
            "rows_blocked_by_rate_limit": rows_blocked_by_rate_limit,
            "provider_rate_limit_events": provider_rate_limit_events,
        },
    }
    errors = {
        "run_metadata": metadata,
        "strict_scoring_rows": len(records),
        "ambiguous_diagnostic_rows": len(ambiguous_rows),
        "deterministic": {
            key: deterministic_score[key]
            for key in (
                "wrong_concept",
                "no_prediction",
                "candidate_missing",
                "top_confused_concepts",
                "accuracy_by_statement_type",
                "accuracy_by_label_family",
            )
        },
        "qwen": {
            key: qwen_score[key]
            for key in (
                "wrong_concept",
                "no_prediction",
                "candidate_missing",
                "hallucinated_concept_rejected",
                "invalid_response",
                "low_confidence_suggestion",
                "correct_but_not_high_confidence",
                "top_confused_concepts",
                "accuracy_by_statement_type",
                "accuracy_by_label_family",
                "accuracy_by_confidence_tier",
            )
        },
        "ambiguous_alignments": ambiguous_rows,
    }
    return predictions, accuracy, errors


def _render_markdown(title: str, report: Mapping[str, Any]) -> str:
    metadata = report.get("run_metadata") or {}
    lines = [
        f"# {title}",
        "",
        f"- Generated: `{metadata.get('generated_at')}`",
        f"- Report only: `{metadata.get('report_only')}`",
        f"- Database mutated: `{metadata.get('database_mutated')}`",
        f"- External LLM called: `{metadata.get('external_llm_called')}`",
        f"- Auditor XML sent externally: `{metadata.get('auditor_xml_sent_to_external_provider')}`",
        f"- Gold answers sent externally: `{metadata.get('gold_answers_sent_to_external_provider')}`",
        "",
    ]
    if "strict_scoring_rows" in report:
        strict = report["strict_scoring_rows"]
        lines.append(f"- Strict scoring rows: `{len(strict) if isinstance(strict, list) else strict}`")
    if "ambiguous_diagnostic_rows" in report:
        ambiguous = report["ambiguous_diagnostic_rows"]
        lines.append(f"- Ambiguous diagnostic rows: `{len(ambiguous) if isinstance(ambiguous, list) else ambiguous}`")
    for name in ("deterministic_mapping", "qwen_mapping"):
        score = report.get(name)
        if not isinstance(score, Mapping):
            continue
        lines.extend(
            [
                "",
                f"## {name.replace('_', ' ').title()}",
                "",
                f"- Coverage: `{score.get('coverage')}`",
                f"- Accuracy: `{score.get('accuracy')}`",
                f"- Correct: `{score.get('correct')}`",
                f"- Wrong concept: `{score.get('wrong_concept')}`",
                f"- No prediction: `{score.get('no_prediction')}`",
                f"- Candidate missing: `{score.get('candidate_missing')}`",
            ]
        )
    return "\n".join(lines) + "\n"


async def write_current_mapping_baseline_reports(
    *,
    golden_dir: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    alignment_report_path: str | Path = DEFAULT_ALIGNMENT_REPORT,
    use_live_llm: bool = False,
    llm_client: Any | None = None,
    max_rate_limit_retries: int = 2,
    rate_limit_backoff_seconds: float = 1.0,
) -> dict[str, Any]:
    predictions, accuracy, errors = await build_current_mapping_baseline_reports(
        golden_dir=golden_dir,
        alignment_report_path=alignment_report_path,
        use_live_llm=use_live_llm,
        llm_client=llm_client,
        max_rate_limit_retries=max_rate_limit_retries,
        rate_limit_backoff_seconds=rate_limit_backoff_seconds,
    )
    root = Path(output_dir)
    paths = {
        "predictions_json": root / f"{OUTPUT_STEM_PREDICTIONS}.json",
        "predictions_md": root / f"{OUTPUT_STEM_PREDICTIONS}.md",
        "accuracy_json": root / f"{OUTPUT_STEM_ACCURACY}.json",
        "accuracy_md": root / f"{OUTPUT_STEM_ACCURACY}.md",
        "errors_json": root / f"{OUTPUT_STEM_ERRORS}.json",
        "errors_md": root / f"{OUTPUT_STEM_ERRORS}.md",
    }
    _write_json(paths["predictions_json"], predictions)
    _write_json(paths["accuracy_json"], accuracy)
    _write_json(paths["errors_json"], errors)
    paths["predictions_md"].write_text(
        _render_markdown("Golden MBRS Current Mapping Predictions #17B-pre", predictions),
        encoding="utf-8",
    )
    paths["accuracy_md"].write_text(
        _render_markdown("Golden MBRS Current Mapping Accuracy #17B-pre", accuracy),
        encoding="utf-8",
    )
    paths["errors_md"].write_text(
        _render_markdown("Golden MBRS Mapping Error Analysis #17B-pre", errors),
        encoding="utf-8",
    )
    return {
        "paths": {key: str(path) for key, path in paths.items()},
        "predictions": predictions,
        "accuracy": accuracy,
        "errors": errors,
    }
