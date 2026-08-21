"""Report-only few-shot Qwen evaluation against the local Golden MBRS dataset."""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.azure_di_production_mapping import normalize_text, strip_note_references
from services.current_mapping_baseline import (
    DEFAULT_ALIGNMENT_REPORT,
    DEFAULT_OUTPUT_DIR,
    _candidate_missing,
    _prediction_input,
    _qwen_candidates,
    _qwen_row_context,
    _read_json,
    _render_markdown,
    _write_json,
    load_golden_prediction_inputs,
    score_prediction_records,
)
from services.golden_mbrs_dataset import PROJECT_ROOT
from services.llm_taxonomy_mapping import (
    HuggingFaceQwenMappingClient,
    LLMMappingRateLimitError,
    is_rate_limit_error,
    load_llm_mapping_config,
    parse_llm_json_response,
    validate_llm_mapping_output,
)


DEFAULT_BASELINE_ACCURACY_REPORT = PROJECT_ROOT / "reports" / "golden_mbrs_current_mapping_accuracy_17b_pre.json"
DEFAULT_BASELINE_PREDICTIONS_REPORT = PROJECT_ROOT / "reports" / "golden_mbrs_current_mapping_predictions_17b_pre.json"
OUTPUT_STEM_PREDICTIONS = "golden_mbrs_fewshot_qwen_predictions_17b"
OUTPUT_STEM_ACCURACY = "golden_mbrs_fewshot_qwen_accuracy_17b"
OUTPUT_STEM_ERRORS = "golden_mbrs_fewshot_qwen_error_analysis_17b"
OUTPUT_STEM_COMPARISON = "golden_mbrs_fewshot_vs_baseline_17b"
OUTPUT_STEM_GUARDRAIL_ANALYSIS = "golden_mbrs_fewshot_guardrail_analysis_17b_hotfix_1"
OUTPUT_STEM_GUARDRAIL_COMPARISON = "golden_mbrs_fewshot_guardrail_comparison_17b_hotfix_1"
MIN_FEWSHOT_RETRIEVAL_SCORE = 0.45
HIGH_SIMILARITY_EXAMPLE_SCORE = 0.75

SYNONYM_GROUPS = (
    {"capital", "share capital", "contributed share capital", "issued capital"},
    {"bank overdraft", "overdraft", "unsecured bank overdraft"},
    {"receivable", "receivables", "other receivable", "trade receivables"},
    {"payable", "payables", "other payable", "trade payables", "director account"},
    {"accrual", "accruals"},
    {"cash", "cash equivalents", "cash and cash equivalents", "bank balances"},
    {"loss", "net loss", "profit loss", "profit"},
    {"tax", "tax expense", "taxation"},
    {"administrative expenses", "administration expenses", "operating expenses"},
)

GENERIC_FEWSHOT_LABELS = {
    "assets",
    "current assets",
    "current liabilities",
    "equity",
    "liabilities",
    "other",
    "total assets",
    "total current assets",
    "total current liabilities",
    "total liabilities",
    "total operating expenses",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _tokens(value: Any) -> set[str]:
    return {token for token in normalize_text(strip_note_references(value)).split() if token}


def _token_overlap(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _synonym_overlap(left: Any, right: Any) -> float:
    text_left = normalize_text(left)
    text_right = normalize_text(right)
    matches = 0
    for group in SYNONYM_GROUPS:
        left_hit = any(term in text_left for term in group)
        right_hit = any(term in text_right for term in group)
        if left_hit and right_hit:
            matches += 1
    return min(1.0, matches / 2) if matches else 0.0


def _concept_family(value: Any) -> str:
    text = normalize_text(value)
    if "cash" in text:
        return "cash"
    if "receivable" in text:
        return "receivables"
    if "payable" in text or "director" in text:
        return "payables"
    if "capital" in text or "equity" in text:
        return "equity"
    if "tax" in text:
        return "tax"
    if "expense" in text or "administr" in text:
        return "expenses"
    if "loss" in text or "profit" in text:
        return "profit_loss"
    if "asset" in text:
        return "assets"
    if "liabil" in text:
        return "liabilities"
    return "other"


def _is_generic_fewshot_label(value: Any) -> bool:
    label = re.sub(r"^(?:total|net)\s+", "", normalize_text(strip_note_references(value))).strip()
    return label in GENERIC_FEWSHOT_LABELS or label.startswith("total ")


def deterministic_case_split(
    case_ids: Sequence[str],
    *,
    train_case_count: int = 4,
    holdout_cases: Sequence[str] | None = None,
) -> dict[str, list[str]]:
    ordered = sorted({str(case_id) for case_id in case_ids})
    if holdout_cases:
        holdout = sorted({str(case_id) for case_id in holdout_cases})
        train = [case_id for case_id in ordered if case_id not in set(holdout)]
    else:
        train = ordered[:train_case_count]
        holdout = ordered[train_case_count:]
    return {"train_cases": train, "holdout_cases": holdout}


def build_fewshot_example_store(rows: Sequence[Mapping[str, Any]], *, train_cases: Sequence[str]) -> list[dict[str, Any]]:
    train = set(train_cases)
    examples = []
    for row in rows:
        if row.get("source_case_id") not in train:
            continue
        qname = row.get("correct_concept_qname")
        if not qname:
            continue
        evidence = row.get("gold_alignment_evidence") or {}
        examples.append(
            {
                "source_case_id": row.get("source_case_id"),
                "extracted_row_id": row.get("extracted_row_id"),
                "extracted_label": row.get("extracted_label"),
                "extracted_value_pattern": _value_pattern(row.get("extracted_value")),
                "statement_type": row.get("statement_type"),
                "correct_concept_qname": qname,
                "correct_template_field_id": row.get("correct_template_field_id") or qname,
                "concept_family": _concept_family(f"{qname} {row.get('extracted_label')}"),
                "rationale": _example_rationale(row, evidence),
            }
        )
    return examples


def _value_pattern(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace(",", "")
    sign = "negative" if normalized.startswith("-") or (normalized.startswith("(") and normalized.endswith(")")) else "positive"
    digits = len(re.sub(r"\D", "", normalized))
    if digits >= 6:
        magnitude = "large"
    elif digits >= 4:
        magnitude = "medium"
    else:
        magnitude = "small"
    return f"{sign}_{magnitude}_numeric"


def _example_rationale(row: Mapping[str, Any], evidence: Mapping[str, Any]) -> str:
    parts = []
    if evidence.get("value_match"):
        parts.append("value matched reference fact")
    if evidence.get("period_match"):
        parts.append("period evidence aligned")
    if evidence.get("unit_evidence"):
        parts.append("unit/context evidence aligned")
    if evidence.get("label_similarity") is not None:
        parts.append(f"label similarity {evidence.get('label_similarity')}")
    return "; ".join(parts[:3]) or "strong local gold alignment"


def retrieve_similar_examples(
    *,
    target_row: Mapping[str, Any],
    example_store: Sequence[Mapping[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    target_case = target_row.get("source_case_id")
    target_id = target_row.get("extracted_row_id")
    target_label = target_row.get("extracted_label")
    target_statement = normalize_text(target_row.get("statement_type"))
    target_family = _concept_family(f"{target_label} {target_row.get('statement_type')}")
    scored = []
    for example in example_store:
        if example.get("source_case_id") == target_case:
            continue
        if example.get("extracted_row_id") == target_id:
            continue
        label = example.get("extracted_label")
        statement = normalize_text(example.get("statement_type"))
        label_score = max(_token_overlap(target_label, label), SequenceMatcher(None, normalize_text(target_label), normalize_text(label)).ratio())
        synonym_score = _synonym_overlap(target_label, label)
        statement_score = 1.0 if target_statement and statement and target_statement == statement else _token_overlap(target_statement, statement)
        family_score = 1.0 if target_family == example.get("concept_family") else 0.0
        score = (0.48 * label_score) + (0.22 * synonym_score) + (0.18 * statement_score) + (0.12 * family_score)
        if score < MIN_FEWSHOT_RETRIEVAL_SCORE:
            continue
        if _is_generic_fewshot_label(label) and label_score < 0.72:
            continue
        if family_score == 0.0 and statement_score < 0.35 and label_score < 0.65:
            continue
        safe = {
            "source_case_id": example.get("source_case_id"),
            "extracted_label": example.get("extracted_label"),
            "extracted_value_pattern": example.get("extracted_value_pattern"),
            "statement_type": example.get("statement_type"),
            "correct_concept_qname": example.get("correct_concept_qname"),
            "correct_template_field_id": example.get("correct_template_field_id"),
            "rationale": example.get("rationale"),
            "retrieval_score": round(score, 4),
        }
        scored.append(safe)
    scored.sort(key=lambda row: (-float(row["retrieval_score"]), str(row["correct_template_field_id"]), str(row["extracted_label"])))
    return scored[:limit]


def build_guardrail_context(
    *,
    target_row: Mapping[str, Any],
    candidate_concepts: Sequence[Mapping[str, Any]],
    fewshot_examples: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    target_label = target_row.get("extracted_label")
    target_label_norm = normalize_text(strip_note_references(target_label))
    target_family = _concept_family(f"{target_label} {target_row.get('statement_type')}")
    candidate_ids = {str(row.get("template_field_id") or "") for row in candidate_concepts}
    warnings: list[str] = []
    absent_similar_example_concepts = []
    for example in fewshot_examples:
        concept = str(example.get("correct_template_field_id") or "")
        if not concept or concept in candidate_ids:
            continue
        if float(example.get("retrieval_score") or 0.0) >= HIGH_SIMILARITY_EXAMPLE_SCORE:
            absent_similar_example_concepts.append(
                {
                    "example_label": example.get("extracted_label"),
                    "example_concept": concept,
                    "retrieval_score": example.get("retrieval_score"),
                }
            )
    if absent_similar_example_concepts:
        warnings.append(
            "A close training example maps to a concept that is absent from candidate_concepts; do not select a broader substitute only by analogy."
        )
    if "other receivable" in target_label_norm or "other receivables" in target_label_norm:
        warnings.extend(_broad_substitution_warnings(target_label_norm, candidate_concepts, family="receivables"))
    if "other payable" in target_label_norm or "other payables" in target_label_norm:
        warnings.extend(_broad_substitution_warnings(target_label_norm, candidate_concepts, family="payables"))
    return {
        "target_label_family": target_family,
        "selection_guardrails": [
            "Return null if candidate concepts are close but not an exact semantic fit for the target label.",
            "Do not overgeneralize from few-shot examples; they are guidance, not answer keys for the target row.",
            "Prefer null when statement type and concept family do not align.",
            "High confidence requires strong label meaning and statement-context evidence, not value pattern alone.",
            "Avoid broad summary concepts when the row label is a more specific receivable/payable/accrual/nontrade item.",
        ],
        "candidate_warnings": warnings,
        "absent_similar_example_concepts": absent_similar_example_concepts,
    }


def _broad_substitution_warnings(
    target_label_norm: str,
    candidate_concepts: Sequence[Mapping[str, Any]],
    *,
    family: str,
) -> list[str]:
    warnings = []
    lacks_trade = "trade" not in target_label_norm
    lacks_current = "current" not in target_label_norm
    lacks_noncurrent = "noncurrent" not in target_label_norm and "non current" not in target_label_norm
    lacks_nontrade = "nontrade" not in target_label_norm and "non trade" not in target_label_norm
    for candidate in candidate_concepts:
        candidate_id = str(candidate.get("template_field_id") or "")
        candidate_text = normalize_text(f"{candidate_id} {candidate.get('label')}")
        if family == "receivables" and "receivable" not in candidate_text:
            continue
        if family == "payables" and "payable" not in candidate_text:
            continue
        reasons = []
        if lacks_trade and "trade" in candidate_text:
            reasons.append("target label lacks trade evidence")
        if lacks_current and "current" in candidate_text:
            reasons.append("target label lacks current-period classification wording")
        if lacks_noncurrent and "noncurrent" in candidate_text:
            reasons.append("target label lacks noncurrent classification wording")
        if lacks_nontrade and "nontrade" in candidate_text:
            reasons.append("target label lacks nontrade wording")
        if "total" in candidate_text and "total" not in target_label_norm:
            reasons.append("candidate is a broader total/summary concept")
        if reasons:
            warnings.append(f"{candidate_id}: broad-substitution risk ({'; '.join(reasons)}).")
    return warnings[:5]


def build_fewshot_qwen_prompt(
    *,
    target_row: Mapping[str, Any],
    candidate_concepts: Sequence[Mapping[str, Any]],
    fewshot_examples: Sequence[Mapping[str, Any]],
) -> str:
    payload = {
        "row": _qwen_row_context(target_row),
        "few_shot_examples": list(fewshot_examples),
        "candidate_concepts": list(candidate_concepts),
        "guardrail_context": build_guardrail_context(
            target_row=target_row,
            candidate_concepts=candidate_concepts,
            fewshot_examples=fewshot_examples,
        ),
        "required_output_schema": {
            "selected_template_field_id": "string or null",
            "confidence": 0.0,
            "reason": "string",
            "ranked_candidates": [
                {
                    "template_field_id": "string",
                    "confidence": 0.0,
                    "reason": "string",
                }
            ],
            "requires_human_confirmation": True,
            "rejection_reason": "string or null",
        },
    }
    return (
        "You are mapping one extracted financial statement row to one of the provided XBRL/MPERS template concepts.\n\n"
        "Rules:\n"
        "- Choose only from candidate_concepts.template_field_id.\n"
        "- Use few_shot_examples only as mapping-pattern guidance from other training cases.\n"
        "- Never copy a few-shot answer unless the target row and provided candidate evidence support it.\n"
        "- Do not select a broader summary concept when a close specific concept appears to be absent from candidate_concepts.\n"
        "- A candidate that matches only value pattern, generic family, or broad receivable/payable wording is not enough.\n"
        "- Reduce confidence or return null when label meaning and concept specificity do not align.\n"
        "- If none is safe, return selected_template_field_id as null.\n"
        "- Do not invent qnames, template fields, values, facts, periods, units, or statement sections.\n"
        "- Do not map person/company names or note numbers as financial facts.\n"
        "- Do not force ambiguous rows; prefer null if uncertain.\n"
        "- Return strict JSON only, with no markdown fences or commentary.\n\n"
        "Input:\n"
        f"{json.dumps(payload, ensure_ascii=True, sort_keys=True)}"
    )


async def _fewshot_live_prediction(
    row: Mapping[str, Any],
    *,
    candidates: Sequence[Mapping[str, Any]],
    examples: Sequence[Mapping[str, Any]],
    llm_client: Any,
    config: Any,
    max_rate_limit_retries: int,
    rate_limit_backoff_seconds: float,
) -> dict[str, Any]:
    prompt = build_fewshot_qwen_prompt(target_row=row, candidate_concepts=candidates, fewshot_examples=examples)
    rate_limit_retries = 0
    while True:
        try:
            raw = await llm_client.complete(prompt, config=config)
            parsed, parse_error, _raw_text, _parsed_content, response_shape = parse_llm_json_response(raw)
            break
        except Exception as exc:
            if not is_rate_limit_error(exc):
                return _prediction_from_rejection(
                    status="provider_error",
                    reason=f"llm_call_failed: {exc}",
                    candidates=candidates,
                    examples=examples,
                    external_llm_called=True,
                    rate_limit_retries=rate_limit_retries,
                )
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
        "few_shot_examples": list(examples),
        "few_shot_example_count": len(examples),
        "external_llm_called": True,
        "hallucinated_concept": bool(suggestion.get("hallucinated_concept")),
        "invalid_response": bool(suggestion.get("invalid_response")),
        "warning_level": suggestion.get("warning_level"),
        "ranked_candidates": suggestion.get("ranked_candidates") or [],
        "normalized_response_shape": response_shape,
        "rate_limit_retries": rate_limit_retries,
    }


def _prediction_from_rejection(
    *,
    status: str,
    reason: str,
    candidates: Sequence[Mapping[str, Any]],
    examples: Sequence[Mapping[str, Any]],
    external_llm_called: bool = False,
    rate_limit_retries: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "predicted_concept_qname": None,
        "predicted_template_field_id": None,
        "confidence": 0.0,
        "confidence_tier": None,
        "reason": reason,
        "candidate_concepts": list(candidates),
        "few_shot_examples": list(examples),
        "few_shot_example_count": len(examples),
        "external_llm_called": external_llm_called,
        "hallucinated_concept": False,
        "invalid_response": False,
        "rate_limit_retries": rate_limit_retries,
    }


def _metadata(*, use_live_llm: bool, external_llm_called: bool, status: str, split: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "feature": "17B",
        "generated_at": _utc_now(),
        "report_only": True,
        "database_mutated": False,
        "production_filing_jobs_mutated": False,
        "production_extraction_changed": False,
        "qwen_production_prompt_changed": False,
        "react_ui_changed": False,
        "admin_user_management_changed": False,
        "auto_apply_mappings": False,
        "confirmed_tag_id_set": False,
        "xbrl_generated": False,
        "arelle_run": False,
        "live_llm_requested": use_live_llm,
        "external_llm_called": external_llm_called,
        "qwen_status": status,
        "auditor_xml_sent_to_external_provider": False,
        "parsed_xml_facts_sent_to_external_provider": False,
        "target_gold_answers_sent_to_external_provider": False,
        "target_correct_qnames_sent_to_external_provider": False,
        "target_correct_template_fields_sent_to_external_provider": False,
        "evaluation_labels_sent_to_external_provider": False,
        "external_qwen_payload_policy": "holdout extracted row context plus locally retrieved candidate concepts plus selected training-case few-shot examples only",
        "split": dict(split),
    }


async def build_fewshot_qwen_reports(
    *,
    golden_dir: str | Path,
    alignment_report_path: str | Path = DEFAULT_ALIGNMENT_REPORT,
    baseline_accuracy_report_path: str | Path = DEFAULT_BASELINE_ACCURACY_REPORT,
    baseline_predictions_report_path: str | Path = DEFAULT_BASELINE_PREDICTIONS_REPORT,
    use_live_llm: bool = False,
    llm_client: Any | None = None,
    train_case_count: int = 4,
    holdout_cases: Sequence[str] | None = None,
    examples_per_row: int = 5,
    max_rate_limit_retries: int = 2,
    rate_limit_backoff_seconds: float = 1.0,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    strict_rows, ambiguous_rows, inputs_metadata = load_golden_prediction_inputs(
        golden_dir=golden_dir,
        alignment_report_path=alignment_report_path,
    )
    split = deterministic_case_split(
        [str(row.get("source_case_id")) for row in strict_rows],
        train_case_count=train_case_count,
        holdout_cases=holdout_cases,
    )
    example_store = build_fewshot_example_store(strict_rows, train_cases=split["train_cases"])
    holdout = [row for row in strict_rows if row.get("source_case_id") in set(split["holdout_cases"])]
    config = load_llm_mapping_config()
    client = llm_client or (HuggingFaceQwenMappingClient() if use_live_llm else None)
    status = "completed" if use_live_llm else "blocked_live_llm_not_requested"
    external_llm_called = False
    rate_limited = False
    provider_rate_limit_events = 0
    rows_blocked_by_rate_limit = 0
    completed_provider_rows = 0
    records = []

    for row in holdout:
        candidates, precheck_reason = _qwen_candidates(row, max_candidates=config.max_candidates)
        examples = retrieve_similar_examples(target_row=row, example_store=example_store, limit=examples_per_row)
        guardrail_context = build_guardrail_context(
            target_row=row,
            candidate_concepts=candidates,
            fewshot_examples=examples,
        )
        if not use_live_llm:
            prediction = _prediction_from_rejection(
                status="blocked",
                reason="live_qwen_not_requested",
                candidates=candidates,
                examples=examples,
            )
        elif rate_limited:
            rows_blocked_by_rate_limit += 1
            prediction = _prediction_from_rejection(
                status="blocked",
                reason="live_qwen_rate_limited_run_stopped",
                candidates=candidates,
                examples=examples,
            )
        elif precheck_reason:
            prediction = _prediction_from_rejection(
                status="rejected_precheck",
                reason=precheck_reason,
                candidates=candidates,
                examples=examples,
            )
        else:
            external_llm_called = True
            try:
                prediction = await _fewshot_live_prediction(
                    row,
                    candidates=candidates,
                    examples=examples,
                    llm_client=client,
                    config=config,
                    max_rate_limit_retries=max_rate_limit_retries,
                    rate_limit_backoff_seconds=rate_limit_backoff_seconds,
                )
                completed_provider_rows += 1
                provider_rate_limit_events += int(prediction.get("rate_limit_retries") or 0)
            except LLMMappingRateLimitError:
                status = "blocked_rate_limited"
                rate_limited = True
                provider_rate_limit_events += max_rate_limit_retries + 1
                rows_blocked_by_rate_limit += 1
                prediction = _prediction_from_rejection(
                    status="blocked",
                    reason="live_qwen_rate_limited_run_stopped",
                    candidates=candidates,
                    examples=examples,
                    external_llm_called=True,
                    rate_limit_retries=max_rate_limit_retries,
                )
        records.append(
            {
                **_prediction_input(row),
                "correct_concept_qname": row.get("correct_concept_qname"),
                "correct_template_field_id": row.get("correct_template_field_id"),
                "fewshot_qwen_prediction": prediction,
                "guardrail_context": guardrail_context,
                "fewshot_gold_candidate_missing": _candidate_missing(row.get("correct_concept_qname"), candidates),
                "fewshot_prompt_payload_policy": "target_row_context_candidate_concepts_training_case_examples_only_no_target_gold_no_xml_no_evaluation_labels",
            }
        )

    metadata = _metadata(use_live_llm=use_live_llm, external_llm_called=external_llm_called, status=status, split=split)
    score = score_prediction_records(records, predictor="fewshot_qwen")
    baseline_accuracy = _read_json(baseline_accuracy_report_path)
    baseline_predictions = _read_json(baseline_predictions_report_path)
    baseline_holdout_records = _baseline_records_for_holdout(baseline_predictions, split["holdout_cases"])
    baseline_holdout_score = score_prediction_records(baseline_holdout_records, predictor="qwen")
    predictions = {
        "run_metadata": metadata,
        "inputs_metadata": inputs_metadata,
        "example_store_count": len(example_store),
        "strict_scoring_rows": records,
        "ambiguous_diagnostic_rows": ambiguous_rows,
    }
    accuracy = {
        "run_metadata": metadata,
        "strict_scoring_policy": "Only holdout #17A strong alignments are scored. Ambiguous alignments are diagnostics only.",
        "strict_scoring_rows": len(records),
        "total_strong_gold_rows": len(strict_rows),
        "ambiguous_diagnostic_rows": len(ambiguous_rows),
        "fewshot_qwen_mapping": {
            **score,
            "measurable": use_live_llm and status == "completed",
            "status": status,
            "completed_provider_rows": completed_provider_rows,
            "rows_blocked_by_rate_limit": rows_blocked_by_rate_limit,
            "provider_rate_limit_events": provider_rate_limit_events,
        },
    }
    errors = {
        "run_metadata": metadata,
        "strict_scoring_rows": len(records),
        "fewshot_qwen": {
            key: score[key]
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
    comparison = build_baseline_comparison(
        metadata=metadata,
        fewshot_score=accuracy["fewshot_qwen_mapping"],
        baseline_full=baseline_accuracy.get("qwen_mapping") or {},
        baseline_holdout=baseline_holdout_score,
        holdout_rows=len(records),
    )
    return predictions, accuracy, errors, comparison


def _baseline_records_for_holdout(baseline_predictions: Mapping[str, Any], holdout_cases: Sequence[str]) -> list[dict[str, Any]]:
    holdout = set(holdout_cases)
    records = []
    for row in baseline_predictions.get("strict_scoring_rows") or []:
        if row.get("source_case_id") in holdout:
            records.append(dict(row))
    return records


def build_baseline_comparison(
    *,
    metadata: Mapping[str, Any],
    fewshot_score: Mapping[str, Any],
    baseline_full: Mapping[str, Any],
    baseline_holdout: Mapping[str, Any],
    holdout_rows: int,
) -> dict[str, Any]:
    keys = ("coverage", "accuracy", "accuracy_when_predicted", "wrong_concept", "no_prediction", "correct")

    def delta(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
        values = {}
        for key in keys:
            if isinstance(left.get(key), (int, float)) and isinstance(right.get(key), (int, float)):
                values[key] = round(float(left[key]) - float(right[key]), 4)
            else:
                values[key] = None
        return values

    return {
        "run_metadata": dict(metadata),
        "comparison_policy": "Primary fair comparison is against #17B-pre Qwen on the same deterministic holdout cases; full #17B-pre headline metrics are included for context.",
        "holdout_rows": holdout_rows,
        "fewshot_qwen": dict(fewshot_score),
        "baseline_qwen_same_holdout": dict(baseline_holdout),
        "baseline_qwen_full_17b_pre": dict(baseline_full),
        "delta_vs_same_holdout_baseline": delta(fewshot_score, baseline_holdout),
        "delta_vs_full_baseline_context": delta(fewshot_score, baseline_full),
    }


def _render_comparison_markdown(report: Mapping[str, Any]) -> str:
    fewshot = report.get("fewshot_qwen") or {}
    holdout = report.get("baseline_qwen_same_holdout") or {}
    delta = report.get("delta_vs_same_holdout_baseline") or {}
    lines = [
        "# Golden MBRS Few-Shot Qwen vs Baseline #17B",
        "",
        f"- Holdout rows: `{report.get('holdout_rows')}`",
        f"- External LLM called: `{(report.get('run_metadata') or {}).get('external_llm_called')}`",
        f"- Auditor XML sent externally: `{(report.get('run_metadata') or {}).get('auditor_xml_sent_to_external_provider')}`",
        f"- Target gold answers sent externally: `{(report.get('run_metadata') or {}).get('target_gold_answers_sent_to_external_provider')}`",
        "",
        "| Metric | Few-shot Qwen | #17B-pre Qwen Same Holdout | Delta |",
        "|---|---:|---:|---:|",
    ]
    for key in ("coverage", "accuracy", "accuracy_when_predicted", "correct", "wrong_concept", "no_prediction"):
        lines.append(f"| {key} | `{fewshot.get(key)}` | `{holdout.get(key)}` | `{delta.get(key)}` |")
    return "\n".join(lines) + "\n"


async def write_fewshot_qwen_reports(
    *,
    golden_dir: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    alignment_report_path: str | Path = DEFAULT_ALIGNMENT_REPORT,
    baseline_accuracy_report_path: str | Path = DEFAULT_BASELINE_ACCURACY_REPORT,
    baseline_predictions_report_path: str | Path = DEFAULT_BASELINE_PREDICTIONS_REPORT,
    use_live_llm: bool = False,
    llm_client: Any | None = None,
    train_case_count: int = 4,
    holdout_cases: Sequence[str] | None = None,
    examples_per_row: int = 5,
    max_rate_limit_retries: int = 2,
    rate_limit_backoff_seconds: float = 1.0,
) -> dict[str, Any]:
    predictions, accuracy, errors, comparison = await build_fewshot_qwen_reports(
        golden_dir=golden_dir,
        alignment_report_path=alignment_report_path,
        baseline_accuracy_report_path=baseline_accuracy_report_path,
        baseline_predictions_report_path=baseline_predictions_report_path,
        use_live_llm=use_live_llm,
        llm_client=llm_client,
        train_case_count=train_case_count,
        holdout_cases=holdout_cases,
        examples_per_row=examples_per_row,
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
        "comparison_json": root / f"{OUTPUT_STEM_COMPARISON}.json",
        "comparison_md": root / f"{OUTPUT_STEM_COMPARISON}.md",
    }
    _write_json(paths["predictions_json"], predictions)
    _write_json(paths["accuracy_json"], accuracy)
    _write_json(paths["errors_json"], errors)
    _write_json(paths["comparison_json"], comparison)
    paths["predictions_md"].write_text(_render_markdown("Golden MBRS Few-Shot Qwen Predictions #17B", predictions), encoding="utf-8")
    paths["accuracy_md"].write_text(_render_markdown("Golden MBRS Few-Shot Qwen Accuracy #17B", accuracy), encoding="utf-8")
    paths["errors_md"].write_text(_render_markdown("Golden MBRS Few-Shot Qwen Error Analysis #17B", errors), encoding="utf-8")
    paths["comparison_md"].write_text(_render_comparison_markdown(comparison), encoding="utf-8")
    return {
        "paths": {key: str(path) for key, path in paths.items()},
        "predictions": predictions,
        "accuracy": accuracy,
        "errors": errors,
        "comparison": comparison,
    }


def build_guardrail_analysis_report(
    *,
    predictions_report_path: str | Path = PROJECT_ROOT / "reports" / f"{OUTPUT_STEM_PREDICTIONS}.json",
    accuracy_report_path: str | Path = PROJECT_ROOT / "reports" / f"{OUTPUT_STEM_ACCURACY}.json",
    comparison_report_path: str | Path = PROJECT_ROOT / "reports" / f"{OUTPUT_STEM_COMPARISON}.json",
) -> tuple[dict[str, Any], dict[str, Any]]:
    predictions = _read_json(predictions_report_path)
    accuracy = _read_json(accuracy_report_path)
    comparison = _read_json(comparison_report_path)
    wrong_rows = []
    for row in predictions.get("strict_scoring_rows") or []:
        prediction = row.get("fewshot_qwen_prediction") or {}
        predicted = prediction.get("predicted_concept_qname") or prediction.get("predicted_template_field_id")
        correct = row.get("correct_concept_qname")
        if not predicted or predicted == correct:
            continue
        wrong_rows.append(_analyze_wrong_row(row))

    root_causes = Counter(row["likely_error_source"] for row in wrong_rows)
    analysis = {
        "run_metadata": _guardrail_metadata(source_reports=[str(predictions_report_path), str(accuracy_report_path), str(comparison_report_path)]),
        "summary": {
            "wrong_concept_rows": len(wrong_rows),
            "candidate_missing_wrong_rows": sum(1 for row in wrong_rows if row["correct_concept_in_candidates"] is False),
            "broad_substitution_wrong_rows": sum(1 for row in wrong_rows if row["selected_broad_summary_concept"]),
            "high_confidence_wrong_rows": sum(1 for row in wrong_rows if str(row.get("confidence_tier")) == "high"),
            "root_causes": [{"cause": cause, "count": count} for cause, count in root_causes.most_common()],
        },
        "wrong_concept_rows": wrong_rows,
        "guardrail_changes": [
            "Raise few-shot retrieval minimum score to avoid weak analogies.",
            "Drop generic total/broad examples unless label similarity is strong.",
            "Add prompt guardrails that forbid broad summary substitutions when a close specific concept appears absent from candidates.",
            "Add prompt guardrails that require label meaning and concept specificity, not value pattern or broad family alone.",
            "Add explicit null preference for receivable/payable candidates with trade/current/noncurrent/nontrade qualifiers absent from the target label.",
        ],
    }
    comparison_report = _build_guardrail_comparison_report(
        metadata=analysis["run_metadata"],
        accuracy=accuracy,
        comparison=comparison,
        wrong_rows=wrong_rows,
    )
    return analysis, comparison_report


def _guardrail_metadata(*, source_reports: Sequence[str]) -> dict[str, Any]:
    return {
        "feature": "17B-hotfix-1",
        "generated_at": _utc_now(),
        "report_only": True,
        "source_reports": list(source_reports),
        "source_report_snapshot_note": "This report embeds the analyzed rows and metrics as a local snapshot; source report paths can be refreshed by later evaluator commands.",
        "database_mutated": False,
        "production_filing_jobs_mutated": False,
        "production_extraction_changed": False,
        "qwen_production_prompt_changed": False,
        "react_ui_changed": False,
        "admin_user_management_changed": False,
        "auto_apply_mappings": False,
        "confirmed_tag_id_set": False,
        "xbrl_generated": False,
        "arelle_run": False,
        "external_llm_called": False,
        "auditor_xml_sent_to_external_provider": False,
        "parsed_xml_facts_sent_to_external_provider": False,
        "target_gold_answers_sent_to_external_provider": False,
        "target_correct_qnames_sent_to_external_provider": False,
        "target_correct_template_fields_sent_to_external_provider": False,
        "evaluation_labels_sent_to_external_provider": False,
    }


def _analyze_wrong_row(row: Mapping[str, Any]) -> dict[str, Any]:
    prediction = row.get("fewshot_qwen_prediction") or {}
    candidates = list(prediction.get("candidate_concepts") or [])
    examples = list(prediction.get("few_shot_examples") or [])
    selected = prediction.get("predicted_concept_qname") or prediction.get("predicted_template_field_id")
    correct = row.get("correct_concept_qname")
    selected_candidate = next(
        (candidate for candidate in candidates if candidate.get("template_field_id") == selected),
        {},
    )
    correct_in_candidates = correct in {candidate.get("template_field_id") for candidate in candidates}
    selected_broad = _is_broad_summary_selection(row.get("extracted_label"), selected_candidate)
    weak_examples = [
        {
            "source_case_id": example.get("source_case_id"),
            "extracted_label": example.get("extracted_label"),
            "correct_template_field_id": example.get("correct_template_field_id"),
            "retrieval_score": example.get("retrieval_score"),
            "issue": _example_issue(row, example),
        }
        for example in examples
        if _example_issue(row, example)
    ]
    guardrail_context = build_guardrail_context(
        target_row=row,
        candidate_concepts=candidates,
        fewshot_examples=examples,
    )
    if not correct_in_candidates and selected_broad:
        likely = "candidate_missing_broad_substitution"
    elif weak_examples:
        likely = "misleading_or_weak_fewshot_example"
    elif not correct_in_candidates:
        likely = "candidate_missing"
    else:
        likely = "prompt_over_aggression"
    return {
        "source_case_id": row.get("source_case_id"),
        "extracted_row_id": row.get("extracted_row_id"),
        "extracted_label": row.get("extracted_label"),
        "statement_type": row.get("statement_type"),
        "correct_concept_qname": correct,
        "selected_wrong_concept": selected,
        "confidence": prediction.get("confidence"),
        "confidence_tier": prediction.get("confidence_tier"),
        "reason": prediction.get("reason"),
        "correct_concept_in_candidates": correct_in_candidates,
        "selected_broad_summary_concept": selected_broad,
        "likely_error_source": likely,
        "candidate_concepts": [
            {
                "template_field_id": candidate.get("template_field_id"),
                "label": candidate.get("label"),
                "deterministic_score": candidate.get("deterministic_score"),
                "deterministic_method": candidate.get("deterministic_method"),
            }
            for candidate in candidates
        ],
        "few_shot_examples": [
            {
                "source_case_id": example.get("source_case_id"),
                "extracted_label": example.get("extracted_label"),
                "correct_template_field_id": example.get("correct_template_field_id"),
                "retrieval_score": example.get("retrieval_score"),
            }
            for example in examples
        ],
        "weak_or_misleading_examples": weak_examples,
        "recommended_guardrails": _recommended_guardrails(likely, guardrail_context),
        "guardrail_context_after_hotfix": guardrail_context,
    }


def _is_broad_summary_selection(label: Any, candidate: Mapping[str, Any]) -> bool:
    label_norm = normalize_text(strip_note_references(label))
    candidate_text = normalize_text(f"{candidate.get('template_field_id')} {candidate.get('label')}")
    if not candidate_text:
        return False
    broad_terms = ("trade and other", "total", "current", "noncurrent", "other current", "other payables", "other receivables")
    if not any(term in candidate_text for term in broad_terms):
        return False
    if "trade" in candidate_text and "trade" not in label_norm:
        return True
    if "current" in candidate_text and "current" not in label_norm:
        return True
    if "noncurrent" in candidate_text and "noncurrent" not in label_norm:
        return True
    if "total" in candidate_text and "total" not in label_norm:
        return True
    return "other payable" in label_norm or "other receivable" in label_norm


def _example_issue(target_row: Mapping[str, Any], example: Mapping[str, Any]) -> str | None:
    score = float(example.get("retrieval_score") or 0.0)
    if score < MIN_FEWSHOT_RETRIEVAL_SCORE:
        return "below_new_retrieval_threshold"
    if _is_generic_fewshot_label(example.get("extracted_label")) and score < 0.72:
        return "generic_example_label"
    target_family = _concept_family(f"{target_row.get('extracted_label')} {target_row.get('statement_type')}")
    example_family = _concept_family(f"{example.get('extracted_label')} {example.get('correct_template_field_id')}")
    if target_family != "other" and example_family != "other" and target_family != example_family and score < HIGH_SIMILARITY_EXAMPLE_SCORE:
        return "concept_family_mismatch"
    return None


def _recommended_guardrails(cause: str, guardrail_context: Mapping[str, Any]) -> list[str]:
    recommendations = []
    if cause in {"candidate_missing_broad_substitution", "candidate_missing"}:
        recommendations.append("Return null when a close specific training-case concept is absent from candidate_concepts instead of selecting a broader substitute.")
    if cause == "misleading_or_weak_fewshot_example":
        recommendations.append("Filter weak or generic few-shot examples unless label similarity and concept family are both strong.")
    recommendations.extend(guardrail_context.get("selection_guardrails") or [])
    recommendations.extend(guardrail_context.get("candidate_warnings") or [])
    return list(dict.fromkeys(recommendations))[:8]


def _build_guardrail_comparison_report(
    *,
    metadata: Mapping[str, Any],
    accuracy: Mapping[str, Any],
    comparison: Mapping[str, Any],
    wrong_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    current = dict(accuracy.get("fewshot_qwen_mapping") or {})
    total = int(accuracy.get("strict_scoring_rows") or current.get("strict_scoring_rows") or 0)
    blockable_wrong = sum(
        1
        for row in wrong_rows
        if row.get("likely_error_source") == "candidate_missing_broad_substitution"
    )
    projected = {
        "strict_scoring_rows": current.get("strict_scoring_rows"),
        "projection_policy": "local_projection_if_guardrails_force_candidate-missing broad substitutions to null; not a live Qwen rerun",
        "projection_scope": "aggregate metrics only; detailed statement/confidence breakdown requires a separately approved live rerun",
        "predicted_rows": current.get("predicted_rows"),
        "coverage": current.get("coverage"),
        "correct": current.get("correct"),
        "accuracy": current.get("accuracy"),
        "accuracy_when_predicted": current.get("accuracy_when_predicted"),
        "wrong_concept": current.get("wrong_concept"),
        "no_prediction": current.get("no_prediction"),
        "blocked_wrong_concept_rows": 0,
    }
    if total and blockable_wrong:
        predicted_rows = max(0, int(current.get("predicted_rows") or 0) - blockable_wrong)
        correct = int(current.get("correct") or 0)
        projected.update(
            {
                "predicted_rows": predicted_rows,
                "coverage": round(predicted_rows / total, 4),
                "correct": correct,
                "accuracy": round(correct / total, 4),
                "accuracy_when_predicted": round(correct / predicted_rows, 4) if predicted_rows else None,
                "wrong_concept": max(0, int(current.get("wrong_concept") or 0) - blockable_wrong),
                "no_prediction": int(current.get("no_prediction") or 0) + blockable_wrong,
                "blocked_wrong_concept_rows": blockable_wrong,
            }
        )
    return {
        "run_metadata": dict(metadata),
        "comparison_policy": "No live Qwen rerun was performed. This compares current #17B live metrics with a local guardrail projection from identified wrong rows.",
        "current_fewshot_live": current,
        "same_holdout_baseline": comparison.get("baseline_qwen_same_holdout") or {},
        "delta_vs_same_holdout_baseline": comparison.get("delta_vs_same_holdout_baseline") or {},
        "projected_after_guardrails": projected,
        "projected_tradeoff": _projected_tradeoff(current, projected),
        "success_criteria_assessment": {
            "wrong_concepts_decrease_projected": (projected.get("wrong_concept") or 0) < (current.get("wrong_concept") or 0),
            "accuracy_when_predicted_recovers_projected": _compare_optional(projected.get("accuracy_when_predicted"), current.get("accuracy_when_predicted")) > 0,
            "coverage_remains_above_deterministic_baseline_projected": _compare_optional(projected.get("coverage"), 0.3909) > 0,
            "live_rerun_required_for_measured_result": True,
        },
    }


def _compare_optional(left: Any, right: Any) -> float:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return 0.0
    return float(left) - float(right)


def _projected_tradeoff(current: Mapping[str, Any], projected: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("coverage", "accuracy", "accuracy_when_predicted", "wrong_concept", "no_prediction", "correct")
    return {
        key: round(float(projected[key]) - float(current[key]), 4)
        for key in keys
        if isinstance(current.get(key), (int, float)) and isinstance(projected.get(key), (int, float))
    }


def _render_guardrail_analysis_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Golden MBRS Few-Shot Guardrail Analysis #17B Hotfix 1",
        "",
        f"- Wrong concept rows: `{summary.get('wrong_concept_rows')}`",
        f"- Candidate-missing wrong rows: `{summary.get('candidate_missing_wrong_rows')}`",
        f"- Broad-substitution wrong rows: `{summary.get('broad_substitution_wrong_rows')}`",
        f"- External LLM called: `{(report.get('run_metadata') or {}).get('external_llm_called')}`",
        "",
        "## Wrong Rows",
        "",
    ]
    for row in report.get("wrong_concept_rows") or []:
        lines.extend(
            [
                f"- `{row.get('source_case_id')}` `{row.get('extracted_row_id')}` `{row.get('extracted_label')}`",
                f"  - correct: `{row.get('correct_concept_qname')}`",
                f"  - selected: `{row.get('selected_wrong_concept')}`",
                f"  - likely source: `{row.get('likely_error_source')}`",
            ]
        )
    return "\n".join(lines) + "\n"


def _render_guardrail_comparison_markdown(report: Mapping[str, Any]) -> str:
    current = report.get("current_fewshot_live") or {}
    projected = report.get("projected_after_guardrails") or {}
    lines = [
        "# Golden MBRS Few-Shot Guardrail Comparison #17B Hotfix 1",
        "",
        "- No live Qwen rerun was performed for this hotfix report.",
        "",
        "| Metric | Current Few-Shot Live | Projected Guardrail Behavior |",
        "|---|---:|---:|",
    ]
    for key in ("coverage", "accuracy", "accuracy_when_predicted", "wrong_concept", "no_prediction", "correct"):
        lines.append(f"| {key} | `{current.get(key)}` | `{projected.get(key)}` |")
    return "\n".join(lines) + "\n"


def write_guardrail_hotfix_reports(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    predictions_report_path: str | Path = PROJECT_ROOT / "reports" / f"{OUTPUT_STEM_PREDICTIONS}.json",
    accuracy_report_path: str | Path = PROJECT_ROOT / "reports" / f"{OUTPUT_STEM_ACCURACY}.json",
    comparison_report_path: str | Path = PROJECT_ROOT / "reports" / f"{OUTPUT_STEM_COMPARISON}.json",
) -> dict[str, Any]:
    analysis, comparison = build_guardrail_analysis_report(
        predictions_report_path=predictions_report_path,
        accuracy_report_path=accuracy_report_path,
        comparison_report_path=comparison_report_path,
    )
    root = Path(output_dir)
    paths = {
        "analysis_json": root / f"{OUTPUT_STEM_GUARDRAIL_ANALYSIS}.json",
        "analysis_md": root / f"{OUTPUT_STEM_GUARDRAIL_ANALYSIS}.md",
        "comparison_json": root / f"{OUTPUT_STEM_GUARDRAIL_COMPARISON}.json",
        "comparison_md": root / f"{OUTPUT_STEM_GUARDRAIL_COMPARISON}.md",
    }
    _write_json(paths["analysis_json"], analysis)
    _write_json(paths["comparison_json"], comparison)
    paths["analysis_md"].write_text(_render_guardrail_analysis_markdown(analysis), encoding="utf-8")
    paths["comparison_md"].write_text(_render_guardrail_comparison_markdown(comparison), encoding="utf-8")
    return {
        "paths": {key: str(path) for key, path in paths.items()},
        "analysis": analysis,
        "comparison": comparison,
    }
