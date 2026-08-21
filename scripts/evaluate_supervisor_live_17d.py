"""Evaluate #17D-B Supervisor review in mock or live mode."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.supervisor_llm_client import (  # noqa: E402
    MISSING_CONFIG_MESSAGE,
    SupervisorLLMClient,
    SupervisorLLMConfig,
    SupervisorLLMConfigurationError,
    SupervisorLLMInvalidResponseError,
    SupervisorProviderHTTPError,
    SupervisorLLMRateLimitError,
    supervisor_independence_status,
)
from services.supervisor_mapping_review import (  # noqa: E402
    assert_supervisor_payload_is_leakage_safe,
    build_supervisor_prompt,
    build_supervisor_review_payload,
    mock_supervisor_review,
    summarize_supervisor_review,
)


DEFAULT_PREDICTIONS_REPORT = PROJECT_ROOT / "reports" / "golden_mbrs_fewshot_qwen_predictions_17b.json"
DEFAULT_PLAYBOOK_REPORT = PROJECT_ROOT / "reports" / "fs_mpers_concept_playbook_17d_pre.json"
PREFLIGHT_PROMPT = (
    'Return strict JSON: {"review_decision":"agree","risk_level":"low","reason":"preflight",'
    '"issues":[],"recommended_action":"accept","confidence_adjustment":"keep","safe_to_accept":true}'
)
PREFLIGHT_PAYLOAD = {
    "mapper_suggestion": {
        "selected_template_field_id": "preflight:Concept",
        "selected_concept_qname": "preflight:Concept",
    },
    "candidate_concepts": [
        {
            "template_field_id": "preflight:Concept",
            "concept_qname": "preflight:Concept",
            "label": "Preflight concept",
        }
    ],
}


def _report_paths(reports_root: Path) -> dict[str, Path]:
    return {
        "review_json": reports_root / "supervisor_live_review_17d_b.json",
        "review_md": reports_root / "supervisor_live_review_17d_b.md",
        "accuracy_json": reports_root / "supervisor_live_review_accuracy_17d_b.json",
        "accuracy_md": reports_root / "supervisor_live_review_accuracy_17d_b.md",
        "error_analysis_json": reports_root / "supervisor_live_review_error_analysis_17d_b.json",
        "error_analysis_md": reports_root / "supervisor_live_review_error_analysis_17d_b.md",
        "vs_mock_json": reports_root / "supervisor_live_vs_mock_17d_b.json",
        "vs_mock_md": reports_root / "supervisor_live_vs_mock_17d_b.md",
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def _display(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _mapper_suggestion(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return row.get("fewshot_qwen_prediction") or row.get("qwen_prediction") or {}


def _selected_template_id(mapper: Mapping[str, Any]) -> str:
    return str(
        mapper.get("predicted_template_field_id")
        or mapper.get("selected_template_field_id")
        or mapper.get("template_field_id")
        or ""
    ).strip()


def _selected_concept_qname(mapper: Mapping[str, Any]) -> str:
    return str(
        mapper.get("predicted_concept_qname")
        or mapper.get("selected_concept_qname")
        or mapper.get("concept_qname")
        or _selected_template_id(mapper)
        or ""
    ).strip()


def _selected_candidate_label(payload: Mapping[str, Any]) -> str | None:
    mapper = payload.get("mapper_suggestion") or {}
    selected_ids = {
        str(mapper.get("selected_template_field_id") or ""),
        str(mapper.get("selected_concept_qname") or ""),
    }
    selected_ids.discard("")
    for candidate in payload.get("candidate_concepts") or []:
        if any(str(candidate.get(key) or "") in selected_ids for key in ("template_field_id", "concept_qname", "qname")):
            return str(candidate.get("label") or "").strip() or None
    return None


def _row_id(row: Mapping[str, Any]) -> str:
    return str(row.get("extracted_row_id") or f"{row.get('source_case_id')}:{row.get('extracted_label')}")


def _mapping_score(row: Mapping[str, Any], mapper: Mapping[str, Any], review: Mapping[str, Any]) -> dict[str, Any]:
    selected_template = _selected_template_id(mapper)
    selected_concept = _selected_concept_qname(mapper)
    correct_template = str(row.get("correct_template_field_id") or "").strip()
    correct_concept = str(row.get("correct_concept_qname") or "").strip()
    mapper_has_prediction = bool(selected_template or selected_concept)
    mapper_correct = bool(
        mapper_has_prediction
        and (
            (correct_template and selected_template == correct_template)
            or (correct_concept and selected_concept == correct_concept)
        )
    )
    mapper_wrong = bool(mapper_has_prediction and not mapper_correct)
    decision = str(review.get("review_decision") or "")
    safe = bool(review.get("safe_to_accept"))
    blocked_from_safe_accept = not safe
    return {
        "correct_template_field_id": correct_template,
        "correct_concept_qname": correct_concept,
        "mapper_selected_template_field_id": selected_template or None,
        "mapper_selected_concept_qname": selected_concept or None,
        "mapper_has_prediction": mapper_has_prediction,
        "mapper_correct": mapper_correct,
        "mapper_wrong": mapper_wrong,
        "supervisor_agreed": decision == "agree",
        "supervisor_safe_to_accept": safe,
        "false_agree": bool(decision == "agree" and mapper_wrong),
        "false_safe_accept": bool(safe and mapper_wrong),
        "false_disagree": bool(decision == "disagree" and mapper_correct),
        "wrong_mapper_mapping_caught": bool(mapper_wrong and blocked_from_safe_accept),
        "wrong_mapper_mapping_missed": bool(mapper_wrong and safe),
        "correct_mapping_unnecessarily_blocked": bool(mapper_correct and blocked_from_safe_accept),
    }


def _safe_record(
    *,
    row: Mapping[str, Any],
    payload: Mapping[str, Any],
    review: Mapping[str, Any],
    mock_review: Mapping[str, Any],
    response_metadata: Mapping[str, Any] | None = None,
    invalid_response_error: str | None = None,
    invalid_response_diagnostic: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    mapper = payload.get("mapper_suggestion") or {}
    score = _mapping_score(row, mapper, review)
    return {
        "row": dict(payload.get("row") or {}),
        "mapper_selection": {
            "status": mapper.get("status"),
            "selected_template_field_id": mapper.get("selected_template_field_id"),
            "selected_concept_qname": mapper.get("selected_concept_qname"),
            "confidence": mapper.get("confidence"),
            "confidence_tier": mapper.get("confidence_tier"),
            "reason": mapper.get("reason"),
        },
        "candidate_count": len(payload.get("candidate_concepts") or []),
        "retrieved_card_count": len(payload.get("retrieved_concept_cards") or []),
        "retrieved_fewshot_example_count": len(payload.get("retrieved_fewshot_examples") or []),
        "missing_concept_card_diagnostics": dict(payload.get("missing_concept_card_diagnostics") or {}),
        "supervisor_review": dict(review),
        "mock_review": dict(mock_review),
        "response_metadata": dict(response_metadata or {}),
        "invalid_response_error": invalid_response_error,
        "invalid_response_diagnostic": dict(invalid_response_diagnostic or {}),
        "local_scoring": score,
    }


def _placeholder_invalid_review(error: str) -> dict[str, Any]:
    return {
        "review_decision": "needs_human_review",
        "risk_level": "high",
        "reason": f"Invalid Supervisor LLM response: {error}",
        "issues": [{"type": "unrepaired_invalid_supervisor_response", "description": "Supervisor LLM response was invalid and repair did not produce a valid review."}],
        "recommended_action": "keep_for_human_review",
        "confidence_adjustment": "decrease",
        "safe_to_accept": False,
    }


def _placeholder_provider_error_review(error: SupervisorProviderHTTPError) -> dict[str, Any]:
    return {
        "review_decision": "needs_human_review",
        "risk_level": "high",
        "reason": f"Supervisor provider HTTP {error.status_code}: {error.reason}",
        "issues": [{"type": "other", "description": "blocked_provider_bad_request"}],
        "recommended_action": "keep_for_human_review",
        "confidence_adjustment": "decrease",
        "safe_to_accept": False,
    }


def _invalid_response_diagnostic(
    *,
    row_index: int,
    payload: Mapping[str, Any],
    config: SupervisorLLMConfig,
    error_summary: Mapping[str, Any],
    repair_attempted: bool,
    repair_succeeded: bool,
) -> dict[str, Any]:
    mapper = payload.get("mapper_suggestion") or {}
    return {
        "row_index": row_index,
        "row": dict(payload.get("row") or {}),
        "selected_mapper_qname": mapper.get("selected_concept_qname"),
        "selected_mapper_label": _selected_candidate_label(payload),
        "validator_error_category": error_summary.get("validator_error_category"),
        "validator_error_message": error_summary.get("validator_error_message"),
        "sanitized_raw_response_excerpt": error_summary.get("sanitized_raw_response_excerpt", ""),
        "response_format_mode": error_summary.get("response_format_mode") or config.response_format,
        "model_id": error_summary.get("model_id") or config.model_id,
        "repair_attempted": repair_attempted,
        "repair_succeeded": repair_succeeded,
    }


def _summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    reviews = [record.get("supervisor_review") or {} for record in records]
    summary = summarize_supervisor_review(reviews)
    scores = [record.get("local_scoring") or {} for record in records]
    agree_scores = [score for record, score in zip(records, scores) if (record.get("supervisor_review") or {}).get("review_decision") == "agree"]
    safe_scores = [score for score in scores if score.get("supervisor_safe_to_accept")]
    mapper_wrong_scores = [score for score in scores if score.get("mapper_wrong")]
    summary.update(
        {
            "safe_to_accept_accuracy": round(
                sum(1 for score in safe_scores if score.get("mapper_correct")) / len(safe_scores),
                4,
            )
            if safe_scores
            else None,
            "agree_accuracy": round(
                sum(1 for score in agree_scores if score.get("mapper_correct")) / len(agree_scores),
                4,
            )
            if agree_scores
            else None,
            "false_agree_count": sum(1 for score in scores if score.get("false_agree")),
            "false_safe_accept_count": sum(1 for score in scores if score.get("false_safe_accept")),
            "false_disagree_count": sum(1 for score in scores if score.get("false_disagree")),
            "wrong_mapper_mappings": len(mapper_wrong_scores),
            "wrong_mapper_mappings_caught": sum(1 for score in scores if score.get("wrong_mapper_mapping_caught")),
            "wrong_mapper_mappings_missed": sum(1 for score in scores if score.get("wrong_mapper_mapping_missed")),
            "blocked_correct_mapping_count": sum(
                1 for score in scores if score.get("correct_mapping_unnecessarily_blocked")
            ),
            "correct_mappings_unnecessarily_blocked": sum(
                1 for score in scores if score.get("correct_mapping_unnecessarily_blocked")
            ),
            "unsafe_agree_count": sum(
                1
                for record in records
                if (record.get("supervisor_review") or {}).get("review_decision") == "agree"
                and not (record.get("supervisor_review") or {}).get("safe_to_accept")
            ),
            "unsafe_agree_downgraded_count": sum(
                1
                for record in records
                if ((record.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_review_decision")
                == "agree"
                and ((record.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_safe_to_accept")
                is True
                and (record.get("supervisor_review") or {}).get("safe_to_accept") is False
            ),
            "safe_to_accept_forced_false_count": sum(
                1
                for record in records
                if ((record.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_safe_to_accept")
                is True
                and (record.get("supervisor_review") or {}).get("safe_to_accept") is False
            ),
            "invalid_response_count": sum(
                1
                for record in records
                if record.get("invalid_response_error")
                or (record.get("response_metadata") or {}).get("initial_invalid_response")
            ),
            "repaired_response_count": sum(
                1 for record in records if (record.get("response_metadata") or {}).get("repair_succeeded")
            ),
            "unrepaired_invalid_response_count": sum(
                1
                for record in records
                if record.get("invalid_response_error")
                and not (record.get("response_metadata") or {}).get("repair_succeeded")
            ),
            "no_supporting_evidence_count": sum(
                1
                for record in records
                for issue in ((record.get("supervisor_review") or {}).get("issues") or [])
                if issue.get("type") == "no_supporting_evidence"
            ),
            "missing_concept_card_count": sum(
                1
                for record in records
                for issue in ((record.get("supervisor_review") or {}).get("issues") or [])
                if issue.get("type") == "missing_concept_card"
            ),
        }
    )
    return summary


def _examples(records: Sequence[Mapping[str, Any]], predicate: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    selected = []
    for record in records:
        if not predicate(record):
            continue
        selected.append(
            {
                "row": record.get("row"),
                "mapper_selection": record.get("mapper_selection"),
                "supervisor_review": record.get("supervisor_review"),
                "mock_review": record.get("mock_review"),
                "local_scoring": record.get("local_scoring"),
                "invalid_response_error": record.get("invalid_response_error"),
                "invalid_response_diagnostic": record.get("invalid_response_diagnostic"),
                "normalization_diagnostics": (record.get("supervisor_review") or {}).get("normalization_diagnostics"),
            }
        )
        if len(selected) >= limit:
            break
    return selected


def _compare_mock(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    pairs = Counter(
        (
            str((record.get("mock_review") or {}).get("review_decision") or "unknown"),
            str((record.get("supervisor_review") or {}).get("review_decision") or "unknown"),
        )
        for record in records
    )
    return {
        "total_compared": len(records),
        "same_decision_count": sum(
            1
            for record in records
            if (record.get("mock_review") or {}).get("review_decision")
            == (record.get("supervisor_review") or {}).get("review_decision")
        ),
        "decision_pair_counts": {f"{left}_to_{right}": count for (left, right), count in sorted(pairs.items())},
        "risk_pair_counts": dict(
            sorted(
                Counter(
                    f"{(record.get('mock_review') or {}).get('risk_level', 'unknown')}_to_"
                    f"{(record.get('supervisor_review') or {}).get('risk_level', 'unknown')}"
                    for record in records
                ).items()
            )
        ),
    }


def _metadata(
    *,
    golden_dir: str | Path,
    predictions_path: Path,
    playbook_path: Path,
    mode: str,
    config: SupervisorLLMConfig,
    rate_limit_summary: Mapping[str, Any] | None = None,
    provider_error_summary: Mapping[str, Any] | None = None,
    preflight_result: Mapping[str, Any] | None = None,
    partial: bool = False,
) -> dict[str, Any]:
    mock_only = mode != "live"
    live_status = "not_run"
    if mode == "mock":
        live_status = "mock_only"
    elif provider_error_summary:
        live_status = "blocked_provider_bad_request" if provider_error_summary.get("status_code") == 400 else "blocked_provider_http_error"
    elif rate_limit_summary:
        live_status = "blocked_provider_rate_limited"
    elif mode == "live":
        live_status = "completed"
    return {
        "feature": "17D-B",
        "golden_dir": str(golden_dir),
        "source_reports": {
            "predictions": _display(predictions_path),
            "concept_playbook": _display(playbook_path),
        },
        "mode": mode,
        "live_status": live_status,
        "partial": partial,
        "supervisor_config_summary": config.redacted_summary(),
        "supervisor_independence": supervisor_independence_status(config, mock_only=mock_only),
        "external_supervisor_llm_called": mode == "live",
        "auditor_xml_sent_externally": False,
        "parsed_xml_facts_sent_externally": False,
        "target_gold_answers_sent_externally": False,
        "evaluation_labels_sent_externally": False,
        "database_mutated": False,
        "production_job_mutated": False,
        "confirmed_tag_id_automated": False,
        "xbrl_generated": False,
        "arelle_run": False,
        "azure_di_extraction_changed": False,
        "react_ui_changed": False,
        "production_workflow_changed": False,
        "response_format_guidance": (
            "Provider enforces JSON object shape only, not this application schema."
            if config.response_format == "json_object"
            else ""
        ),
        "rate_limit_summary": dict(rate_limit_summary or {}),
        "provider_error_summary": dict(provider_error_summary or {}),
        "preflight_result": dict(preflight_result or {}),
    }


async def run_preflight(
    *,
    client: SupervisorLLMClient | None = None,
    config: SupervisorLLMConfig | None = None,
) -> dict[str, Any]:
    live_config = config or SupervisorLLMConfig.from_settings()
    live_config.require_live_config()
    llm_client = client or SupervisorLLMClient()
    result = await llm_client.complete_review(PREFLIGHT_PROMPT, payload=PREFLIGHT_PAYLOAD, config=live_config)
    return {
        "status": "completed",
        "review": result.get("review"),
        "response_metadata": {
            "raw_response_shape": result.get("raw_response_shape"),
            "attempt_count": result.get("attempt_count"),
            "repair_attempted": result.get("repair_attempted"),
            "repair_succeeded": result.get("repair_succeeded"),
        },
        "prompt_policy": "minimal_non_sensitive_preflight_prompt_only",
        "project_row_data_sent": False,
        "gold_answers_sent": False,
        "evaluation_labels_sent": False,
    }


async def build_reports(
    *,
    golden_dir: str | Path,
    reports_dir: str | Path = PROJECT_ROOT / "reports",
    predictions_report_path: str | Path = DEFAULT_PREDICTIONS_REPORT,
    playbook_report_path: str | Path = DEFAULT_PLAYBOOK_REPORT,
    use_live_llm: bool = False,
    mock: bool = False,
    no_live_llm: bool = False,
    limit: int | None = None,
    resume: bool = False,
    preflight: bool = False,
    client: SupervisorLLMClient | None = None,
) -> dict[str, Path]:
    predictions_path = _resolve(predictions_report_path)
    playbook_path = _resolve(playbook_report_path)
    reports_root = _resolve(reports_dir)
    predictions = {} if preflight else _read_json(predictions_path)
    playbook = {} if preflight else _read_json(playbook_path)
    rows = [] if preflight else [row for row in predictions.get("strict_scoring_rows") or [] if isinstance(row, Mapping)]
    if limit is not None:
        rows = rows[: max(0, limit)]

    config = SupervisorLLMConfig.from_settings()
    mode = "live" if use_live_llm and not no_live_llm else "mock"
    if mode == "live":
        config.require_live_config()

    paths = _report_paths(reports_root)

    prior_records: dict[str, Mapping[str, Any]] = {}
    if resume and paths["review_json"].exists():
        prior = _read_json(paths["review_json"])
        prior_records = {
            _row_id((record.get("row") or {})): record
            for record in (prior.get("review_records") or [])
            if isinstance(record, Mapping) and not record.get("invalid_response_error")
        }

    review_records: list[dict[str, Any]] = []
    invalid_response_diagnostics: list[dict[str, Any]] = []
    leakage_errors: list[str] = []
    rate_limit_summary: dict[str, Any] | None = None
    provider_error_summary: dict[str, Any] | None = None
    preflight_result: dict[str, Any] | None = None
    llm_client = client or SupervisorLLMClient()

    if preflight and mode == "live":
        try:
            preflight_result = await run_preflight(client=llm_client, config=config)
        except SupervisorProviderHTTPError as exc:
            provider_error_summary = exc.to_summary()
            preflight_result = {
                "status": "blocked_provider_bad_request" if exc.status_code == 400 else "blocked_provider_http_error",
                "provider_error_summary": provider_error_summary,
                "prompt_policy": "minimal_non_sensitive_preflight_prompt_only",
                "project_row_data_sent": False,
                "gold_answers_sent": False,
                "evaluation_labels_sent": False,
            }
        except SupervisorLLMRateLimitError as exc:
            rate_limit_summary = exc.to_summary()
            preflight_result = {
                "status": "blocked_provider_rate_limited",
                "prompt_policy": "minimal_non_sensitive_preflight_prompt_only",
                "project_row_data_sent": False,
                "gold_answers_sent": False,
                "evaluation_labels_sent": False,
            }

    for row_index, row in enumerate(rows):
        row_key = _row_id(row)
        if mode == "live" and resume and row_key in prior_records:
            review_records.append(dict(prior_records[row_key]))
            continue

        mapper = _mapper_suggestion(row)
        payload = build_supervisor_review_payload(
            row,
            mapper_suggestion=mapper,
            candidate_concepts=mapper.get("candidate_concepts") or [],
            playbook=playbook,
        )
        try:
            assert_supervisor_payload_is_leakage_safe(payload)
        except ValueError as exc:
            leakage_errors.append(f"{row_key}: {exc}")
        mock_review = mock_supervisor_review(payload)

        if mode == "live":
            try:
                prompt = build_supervisor_prompt(payload)
                live_result = await llm_client.complete_review(prompt, payload=payload, config=config)
                review = live_result["review"]
                response_metadata = {
                    "raw_response_shape": live_result.get("raw_response_shape"),
                    "attempt_count": live_result.get("attempt_count"),
                    "repair_attempted": live_result.get("repair_attempted"),
                    "repair_succeeded": live_result.get("repair_succeeded"),
                    "repair_attempt_count": live_result.get("repair_attempt_count"),
                }
                if live_result.get("initial_invalid_response"):
                    response_metadata["initial_invalid_response"] = live_result.get("initial_invalid_response")
                    repaired_issue = {
                        "type": "repaired_supervisor_response",
                        "description": "Initial Supervisor response was invalid, then repaired and revalidated.",
                    }
                    if not any((issue or {}).get("type") == "repaired_supervisor_response" for issue in review.get("issues") or []):
                        review = {**review, "issues": list(review.get("issues") or []) + [repaired_issue]}
                    invalid_diagnostic = _invalid_response_diagnostic(
                        row_index=row_index,
                        payload=payload,
                        config=config,
                        error_summary=live_result.get("initial_invalid_response") or {},
                        repair_attempted=True,
                        repair_succeeded=True,
                    )
                    invalid_response_diagnostics.append(invalid_diagnostic)
                else:
                    invalid_diagnostic = None
                invalid_error = None
            except SupervisorLLMRateLimitError as exc:
                rate_limit_summary = {
                    **exc.to_summary(),
                    "processed_rows_before_rate_limit": len(review_records),
                    "pending_rows_after_rate_limit": max(0, len(rows) - len(review_records)),
                    "failed_row_id": row_key,
                }
                break
            except SupervisorProviderHTTPError as exc:
                provider_error_summary = {
                    **exc.to_summary(),
                    "processed_rows_before_provider_error": len(review_records),
                    "pending_rows_after_provider_error": max(0, len(rows) - len(review_records)),
                    "failed_row_id": row_key,
                }
                review = _placeholder_provider_error_review(exc)
                response_metadata = {"provider_error": provider_error_summary}
                invalid_error = "blocked_provider_bad_request" if exc.status_code == 400 else "blocked_provider_http_error"
                review_records.append(
                    _safe_record(
                        row=row,
                        payload=payload,
                        review=review,
                        mock_review=mock_review,
                        response_metadata=response_metadata,
                        invalid_response_error=invalid_error,
                        invalid_response_diagnostic={},
                    )
                )
                break
            except SupervisorLLMInvalidResponseError as exc:
                review = _placeholder_invalid_review(str(exc))
                response_metadata = {
                    "repair_attempted": exc.repair_attempted,
                    "repair_succeeded": exc.repair_succeeded,
                }
                invalid_error = str(exc)
                invalid_diagnostic = _invalid_response_diagnostic(
                    row_index=row_index,
                    payload=payload,
                    config=config,
                    error_summary=exc.to_diagnostic(config=config),
                    repair_attempted=exc.repair_attempted,
                    repair_succeeded=exc.repair_succeeded,
                )
                invalid_response_diagnostics.append(invalid_diagnostic)
            except ValueError as exc:
                review = _placeholder_invalid_review(str(exc))
                response_metadata = {"repair_attempted": False, "repair_succeeded": False}
                invalid_error = str(exc)
                invalid_diagnostic = _invalid_response_diagnostic(
                    row_index=row_index,
                    payload=payload,
                    config=config,
                    error_summary={
                        "validator_error_category": "value_error",
                        "validator_error_message": str(exc),
                        "sanitized_raw_response_excerpt": "",
                    },
                    repair_attempted=False,
                    repair_succeeded=False,
                )
                invalid_response_diagnostics.append(invalid_diagnostic)
        else:
            review = mock_review
            response_metadata = {"raw_response_shape": "mock_only", "attempt_count": 0}
            invalid_error = None
            invalid_diagnostic = None

        review_records.append(
            _safe_record(
                row=row,
                payload=payload,
                review=review,
                mock_review=mock_review,
                response_metadata=response_metadata,
                invalid_response_error=invalid_error,
                invalid_response_diagnostic=invalid_diagnostic or {},
            )
        )

    partial = rate_limit_summary is not None or provider_error_summary is not None
    metadata = _metadata(
        golden_dir=golden_dir,
        predictions_path=predictions_path,
        playbook_path=playbook_path,
        mode=mode,
        config=config,
        rate_limit_summary=rate_limit_summary,
        provider_error_summary=provider_error_summary,
        preflight_result=preflight_result,
        partial=partial,
    )
    summary = _summary(review_records)
    review_report = {
        "run_metadata": metadata,
        "summary": summary,
        "invalid_response_diagnostics": invalid_response_diagnostics,
        "leakage_safety": {
            "payloads_checked": len(review_records),
            "leakage_errors": leakage_errors,
            "auditor_source_included": False,
            "reference_fact_details_included": False,
            "target_answer_included": False,
            "scoring_labels_included": False,
        },
        "examples": {
            "agree": _examples(review_records, lambda r: (r.get("supervisor_review") or {}).get("review_decision") == "agree"),
            "disagree": _examples(review_records, lambda r: (r.get("supervisor_review") or {}).get("review_decision") == "disagree"),
            "needs_human_review": _examples(
                review_records,
                lambda r: (r.get("supervisor_review") or {}).get("review_decision") == "needs_human_review",
            ),
            "safe_to_accept": _examples(review_records, lambda r: (r.get("supervisor_review") or {}).get("safe_to_accept") is True),
            "safe_to_accept_forced_false_broad_substitute": _examples(
                review_records,
                lambda r: "broad_substitute_requires_human_review"
                in (((r.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("normalization_reasons") or []),
            ),
            "safe_to_accept_forced_false_ambiguous_label": _examples(
                review_records,
                lambda r: "ambiguous_label_requires_human_review"
                in (((r.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("normalization_reasons") or []),
            ),
            "unsafe_agree_downgraded": _examples(
                review_records,
                lambda r: ((r.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_review_decision")
                == "agree"
                and ((r.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_safe_to_accept")
                is True
                and (r.get("supervisor_review") or {}).get("safe_to_accept") is False,
            ),
            "correct_mapping_blocked": _examples(
                review_records,
                lambda r: (r.get("local_scoring") or {}).get("correct_mapping_unnecessarily_blocked"),
            ),
            "true_safe_accept": _examples(
                review_records,
                lambda r: (r.get("supervisor_review") or {}).get("safe_to_accept") is True
                and (r.get("local_scoring") or {}).get("mapper_correct") is True,
            ),
            "false_safe_accept": _examples(
                review_records,
                lambda r: (r.get("local_scoring") or {}).get("false_safe_accept"),
            ),
        },
        "review_records": review_records,
    }
    accuracy_report = {
        "run_metadata": metadata,
        "metrics": summary,
        "scoring_policy": "Gold answers are used only locally after Supervisor responses return.",
    }
    error_report = {
        "run_metadata": metadata,
        "summary": summary,
        "invalid_response_diagnostics": invalid_response_diagnostics,
        "wrong_mapper_mapping_caught": _examples(
            review_records,
            lambda r: (r.get("local_scoring") or {}).get("wrong_mapper_mapping_caught"),
        ),
        "wrong_mapper_mapping_missed": _examples(
            review_records,
            lambda r: (r.get("local_scoring") or {}).get("wrong_mapper_mapping_missed"),
        ),
        "false_agree": _examples(review_records, lambda r: (r.get("local_scoring") or {}).get("false_agree")),
        "false_safe_accept": _examples(review_records, lambda r: (r.get("local_scoring") or {}).get("false_safe_accept")),
        "safe_to_accept_forced_false": _examples(
            review_records,
            lambda r: ((r.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_safe_to_accept")
            is True
            and (r.get("supervisor_review") or {}).get("safe_to_accept") is False,
        ),
        "unsafe_agree_downgraded": _examples(
            review_records,
            lambda r: ((r.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_review_decision")
            == "agree"
            and ((r.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_safe_to_accept")
            is True
            and (r.get("supervisor_review") or {}).get("safe_to_accept") is False,
        ),
        "overly_conservative": _examples(
            review_records,
            lambda r: (r.get("local_scoring") or {}).get("correct_mapping_unnecessarily_blocked"),
        ),
        "invalid_response_cases": _examples(review_records, lambda r: r.get("invalid_response_error")),
        "rate_limit_partial_result": rate_limit_summary or {},
        "provider_error_result": provider_error_summary or {},
    }
    vs_mock_report = {
        "run_metadata": metadata,
        "comparison": _compare_mock(review_records),
        "mock_summary": summarize_supervisor_review([record.get("mock_review") or {} for record in review_records]),
        "supervisor_summary": summary,
    }

    _write_json(paths["review_json"], review_report)
    paths["review_md"].write_text(render_review_markdown(review_report), encoding="utf-8")
    _write_json(paths["accuracy_json"], accuracy_report)
    paths["accuracy_md"].write_text(render_accuracy_markdown(accuracy_report), encoding="utf-8")
    _write_json(paths["error_analysis_json"], error_report)
    paths["error_analysis_md"].write_text(render_error_markdown(error_report), encoding="utf-8")
    _write_json(paths["vs_mock_json"], vs_mock_report)
    paths["vs_mock_md"].write_text(render_vs_mock_markdown(vs_mock_report), encoding="utf-8")
    return paths


def rebuild_reports_from_existing_review(*, reports_dir: str | Path = PROJECT_ROOT / "reports") -> dict[str, Path]:
    reports_root = _resolve(reports_dir)
    paths = _report_paths(reports_root)
    review_report = _read_json(paths["review_json"])
    review_records = [record for record in review_report.get("review_records") or [] if isinstance(record, Mapping)]
    metadata = dict(review_report.get("run_metadata") or {})
    metadata["report_only_refreshed_at"] = _utc_now()
    summary = _summary(review_records)
    review_report = {
        **review_report,
        "run_metadata": metadata,
        "summary": summary,
        "examples": {
            "agree": _examples(review_records, lambda r: (r.get("supervisor_review") or {}).get("review_decision") == "agree"),
            "disagree": _examples(review_records, lambda r: (r.get("supervisor_review") or {}).get("review_decision") == "disagree"),
            "needs_human_review": _examples(
                review_records,
                lambda r: (r.get("supervisor_review") or {}).get("review_decision") == "needs_human_review",
            ),
            "safe_to_accept": _examples(review_records, lambda r: (r.get("supervisor_review") or {}).get("safe_to_accept") is True),
            "correct_mapping_blocked": _examples(
                review_records,
                lambda r: (r.get("local_scoring") or {}).get("correct_mapping_unnecessarily_blocked"),
            ),
            "true_safe_accept": _examples(
                review_records,
                lambda r: (r.get("supervisor_review") or {}).get("safe_to_accept") is True
                and (r.get("local_scoring") or {}).get("mapper_correct") is True,
            ),
            "false_safe_accept": _examples(review_records, lambda r: (r.get("local_scoring") or {}).get("false_safe_accept")),
        },
        "review_records": review_records,
    }
    accuracy_report = {
        "run_metadata": metadata,
        "metrics": summary,
        "scoring_policy": "Gold answers are used only locally after Supervisor responses return.",
    }
    error_report = {
        "run_metadata": metadata,
        "summary": summary,
        "invalid_response_diagnostics": review_report.get("invalid_response_diagnostics") or [],
        "wrong_mapper_mapping_caught": _examples(
            review_records,
            lambda r: (r.get("local_scoring") or {}).get("wrong_mapper_mapping_caught"),
        ),
        "wrong_mapper_mapping_missed": _examples(
            review_records,
            lambda r: (r.get("local_scoring") or {}).get("wrong_mapper_mapping_missed"),
        ),
        "false_agree": _examples(review_records, lambda r: (r.get("local_scoring") or {}).get("false_agree")),
        "false_safe_accept": _examples(review_records, lambda r: (r.get("local_scoring") or {}).get("false_safe_accept")),
        "safe_to_accept_forced_false": _examples(
            review_records,
            lambda r: ((r.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_safe_to_accept")
            is True
            and (r.get("supervisor_review") or {}).get("safe_to_accept") is False,
        ),
        "unsafe_agree_downgraded": _examples(
            review_records,
            lambda r: ((r.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_review_decision")
            == "agree"
            and ((r.get("supervisor_review") or {}).get("normalization_diagnostics") or {}).get("original_safe_to_accept")
            is True
            and (r.get("supervisor_review") or {}).get("safe_to_accept") is False,
        ),
        "overly_conservative": _examples(
            review_records,
            lambda r: (r.get("local_scoring") or {}).get("correct_mapping_unnecessarily_blocked"),
        ),
        "invalid_response_cases": _examples(review_records, lambda r: r.get("invalid_response_error")),
        "rate_limit_partial_result": metadata.get("rate_limit_summary") or {},
        "provider_error_result": metadata.get("provider_error_summary") or {},
    }
    vs_mock_report = {
        "run_metadata": metadata,
        "comparison": _compare_mock(review_records),
        "mock_summary": summarize_supervisor_review([record.get("mock_review") or {} for record in review_records]),
        "supervisor_summary": summary,
    }
    _write_json(paths["review_json"], review_report)
    paths["review_md"].write_text(render_review_markdown(review_report), encoding="utf-8")
    _write_json(paths["accuracy_json"], accuracy_report)
    paths["accuracy_md"].write_text(render_accuracy_markdown(accuracy_report), encoding="utf-8")
    _write_json(paths["error_analysis_json"], error_report)
    paths["error_analysis_md"].write_text(render_error_markdown(error_report), encoding="utf-8")
    _write_json(paths["vs_mock_json"], vs_mock_report)
    paths["vs_mock_md"].write_text(render_vs_mock_markdown(vs_mock_report), encoding="utf-8")
    return paths


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        output.append("| " + " | ".join(str(value).replace("|", "\\|") for value in row) + " |")
    return "\n".join(output)


def render_review_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    metadata = report.get("run_metadata") or {}
    return "\n\n".join(
        [
            "# Supervisor Live Review #17D-B",
            f"- Mode: `{metadata.get('mode')}`",
            f"- Live status: `{metadata.get('live_status')}`",
            f"- Total reviewed: `{summary.get('total_reviewed')}`",
            f"- Agree: `{summary.get('agree')}`",
            f"- Disagree: `{summary.get('disagree')}`",
            f"- Needs human review: `{summary.get('needs_human_review')}`",
            f"- Safe to accept: `{summary.get('safe_to_accept')}`",
            f"- Safe accept forced false: `{summary.get('safe_to_accept_forced_false_count')}`",
            f"- Independence: `{metadata.get('supervisor_independence')}`",
            "## Safety",
            f"- External Supervisor LLM called: `{metadata.get('external_supervisor_llm_called')}`",
            f"- Auditor XML sent externally: `{metadata.get('auditor_xml_sent_externally')}`",
            f"- Target gold answers sent externally: `{metadata.get('target_gold_answers_sent_externally')}`",
            "## Provider Error",
            f"- Status code: `{((metadata.get('provider_error_summary') or {}).get('status_code'))}`",
            f"- Guidance: `{'; '.join((metadata.get('provider_error_summary') or {}).get('guidance') or [])}`",
        ]
    ) + "\n"


def render_accuracy_markdown(report: Mapping[str, Any]) -> str:
    metrics = report.get("metrics") or {}
    rows = [[key, value] for key, value in metrics.items() if not isinstance(value, dict)]
    return "# Supervisor Live Review Accuracy #17D-B\n\n" + _markdown_table(["Metric", "Value"], rows) + "\n"


def render_error_markdown(report: Mapping[str, Any]) -> str:
    summary = report.get("summary") or {}
    return "\n\n".join(
        [
            "# Supervisor Live Review Error Analysis #17D-B",
            f"- False agree count: `{summary.get('false_agree_count')}`",
            f"- False safe accept count: `{summary.get('false_safe_accept_count')}`",
            f"- Safe accept forced false: `{summary.get('safe_to_accept_forced_false_count')}`",
            f"- Unsafe agree downgraded: `{summary.get('unsafe_agree_downgraded_count')}`",
            f"- Wrong mapper mappings caught: `{summary.get('wrong_mapper_mappings_caught')}`",
            f"- Wrong mapper mappings missed: `{summary.get('wrong_mapper_mappings_missed')}`",
            f"- Correct mappings unnecessarily blocked: `{summary.get('correct_mappings_unnecessarily_blocked')}`",
            f"- Invalid responses: `{summary.get('invalid_response_count')}`",
            f"- Provider error status: `{((report.get('run_metadata') or {}).get('live_status'))}`",
        ]
    ) + "\n"


def render_vs_mock_markdown(report: Mapping[str, Any]) -> str:
    comparison = report.get("comparison") or {}
    rows = [[key, value] for key, value in (comparison.get("decision_pair_counts") or {}).items()]
    return "\n\n".join(
        [
            "# Supervisor Live vs Mock #17D-B",
            f"- Total compared: `{comparison.get('total_compared')}`",
            f"- Same decision count: `{comparison.get('same_decision_count')}`",
            "## Decision Pairs",
            _markdown_table(["Mock to Supervisor", "Count"], rows),
        ]
    ) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate #17D-B Supervisor review in mock or live mode.")
    parser.add_argument("--golden-dir", default="benchmark_mbrs_pairs")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--mock", action="store_true", help="Run deterministic local mock Supervisor review.")
    parser.add_argument("--use-live-llm", action="store_true", help="Call configured independent Supervisor LLM.")
    parser.add_argument("--no-live-llm", action="store_true", help="Force local mock mode and do not call a live provider.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--preflight", action="store_true", help="Send only a minimal non-sensitive live provider preflight prompt.")
    parser.add_argument("--report-only", action="store_true", help="Refresh reports from existing review JSON without running mock or live review.")
    return parser.parse_args()


async def _main_async() -> int:
    args = parse_args()
    try:
        if args.report_only:
            paths = rebuild_reports_from_existing_review(reports_dir=args.reports_dir)
        else:
            paths = await build_reports(
                golden_dir=args.golden_dir,
                reports_dir=args.reports_dir,
                use_live_llm=bool(args.use_live_llm),
                mock=bool(args.mock),
                no_live_llm=bool(args.no_live_llm),
                limit=args.limit,
                resume=bool(args.resume),
                preflight=bool(args.preflight),
            )
    except SupervisorLLMConfigurationError as exc:
        print(str(exc) or MISSING_CONFIG_MESSAGE, file=sys.stderr)
        return 2
    report = _read_json(paths["review_json"])
    summary = report.get("summary") or {}
    print("supervisor_17d_b_reports", json.dumps({key: str(value) for key, value in paths.items()}, sort_keys=True))
    print("supervisor_17d_b_summary", json.dumps(summary, sort_keys=True))
    if (report.get("run_metadata") or {}).get("partial"):
        return 3
    return 0


def main() -> int:
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
