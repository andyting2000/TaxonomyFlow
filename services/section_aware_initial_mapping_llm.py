"""Candidate-only, one-call Mapping LLM boundary for Feature #19C."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
from typing import Any, Mapping, Sequence

from config import settings
from schemas import SectionAwareCandidateSet
from services.llm_taxonomy_mapping import (
    HuggingFaceQwenMappingClient,
    LLMMappingConfig,
)


PROMPT_VERSION = "19C-initial-mapping-prompt-v1"
ALLOWED_DECISIONS = {
    "mapped",
    "ambiguous",
    "abstain",
    "no_safe_mapping",
    "structural_only",
    "provider_failed",
    "validation_failed",
    "retrieval_failed",
}
RESPONSE_KEYS = {
    "decision",
    "selected_concept_id",
    "selected_qname",
    "confidence",
    "reason",
    "alternative_concept_ids",
    "requires_human_review",
}
FORBIDDEN_PAYLOAD_KEY_FRAGMENTS = {
    "auditor_xml",
    "reference_xml",
    "parsed_xbrl",
    "generated_xbrl",
    "benchmark_gold",
    "gold_mapping",
    "gold_qname",
    "correct_qname",
    "expected_qname",
    "correctness_label",
    "evaluation_label",
    "evaluation_verdict",
    "hidden_gold",
    "human_approved",
    "confirmed_tag_id",
    "final_mapping",
}


class InitialMappingResponseValidationError(ValueError):
    pass


class InitialMappingPayloadBoundaryError(ValueError):
    pass


@dataclass(frozen=True)
class InitialMappingLLMConfig:
    mode: str = "deterministic_only"
    enabled: bool = False
    live_llm_enabled: bool = False
    model_id: str = "Qwen/Qwen3-235B-A22B-Instruct-2507"
    timeout_seconds: float = 120.0

    @classmethod
    def from_settings(cls, settings_obj: Any = settings) -> "InitialMappingLLMConfig":
        return cls(
            mode=str(getattr(settings_obj, "toc_aware_initial_mapping_mode", "deterministic_only") or "deterministic_only").strip().lower(),
            enabled=bool(getattr(settings_obj, "toc_aware_initial_mapping_enabled", False)),
            live_llm_enabled=bool(getattr(settings_obj, "toc_aware_initial_mapping_live_llm_enabled", False)),
            model_id=str(getattr(settings_obj, "toc_aware_initial_mapping_model_id", "") or "Qwen/Qwen3-235B-A22B-Instruct-2507").strip(),
            timeout_seconds=max(1.0, float(getattr(settings_obj, "toc_aware_initial_mapping_row_timeout_seconds", 120) or 120)),
        )


def _walk_payload(value: Any, path: str = "$"):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield f"{path}.{key}", str(key).lower()
            yield from _walk_payload(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _walk_payload(child, f"{path}[{index}]")


def assert_safe_external_payload(payload: Mapping[str, Any]) -> None:
    violations = []
    for path, key in _walk_payload(payload):
        if any(fragment in key for fragment in FORBIDDEN_PAYLOAD_KEY_FRAGMENTS):
            violations.append(path)
    if violations:
        raise InitialMappingPayloadBoundaryError(
            "Forbidden external payload fields: " + ", ".join(sorted(violations))
        )


def build_initial_mapping_prompt(context: Mapping[str, Any]) -> tuple[str, str]:
    payload = {"prompt_version": PROMPT_VERSION, "row_context": dict(context)}
    assert_safe_external_payload(payload)
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    prompt = (
        "You are an advisory SSM MPERS taxonomy mapper. Use only the supplied candidate_concepts. "
        "Return exactly one JSON object with exactly these keys: decision, selected_concept_id, "
        "selected_qname, confidence, reason, alternative_concept_ids, requires_human_review. "
        "decision must be mapped, ambiguous, abstain, or no_safe_mapping. Never invent a concept, "
        "change a source value, or claim acceptance/finality. requires_human_review must be true. "
        "For mapped, select exactly one supplied concept ID and its exact qname. For abstain or "
        "no_safe_mapping, selected fields must be null. No markdown and no text outside JSON.\n"
        "INPUT_JSON=" + encoded
    )
    return prompt, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _response_text(raw_response: Any) -> str:
    if isinstance(raw_response, str):
        return raw_response
    if isinstance(raw_response, bytes):
        return raw_response.decode("utf-8")
    if isinstance(raw_response, Mapping):
        if set(raw_response).intersection(RESPONSE_KEYS):
            return json.dumps(dict(raw_response), ensure_ascii=True)
        choices = raw_response.get("choices")
    else:
        choices = getattr(raw_response, "choices", None)
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or not choices:
        raise InitialMappingResponseValidationError("Provider response has no JSON content")
    first = choices[0]
    message = first.get("message") if isinstance(first, Mapping) else getattr(first, "message", None)
    if isinstance(message, Mapping):
        content = message.get("content")
    else:
        content = getattr(message, "content", None)
    if content is None:
        content = first.get("text") if isinstance(first, Mapping) else getattr(first, "text", None)
    if not isinstance(content, str):
        raise InitialMappingResponseValidationError("Provider response content is not text")
    return content


def parse_strict_initial_mapping_response(raw_response: Any) -> dict[str, Any]:
    text = _response_text(raw_response).strip()
    if not text.startswith("{") or not text.endswith("}"):
        raise InitialMappingResponseValidationError("Response must contain only one JSON object")
    try:
        duplicate_keys: list[str] = []

        def reject_duplicate_keys(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    duplicate_keys.append(str(key))
                result[key] = value
            return result

        payload = json.loads(text, object_pairs_hook=reject_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise InitialMappingResponseValidationError("Response is invalid JSON") from exc
    if duplicate_keys:
        raise InitialMappingResponseValidationError(
            "Response JSON contains duplicate keys: " + ", ".join(sorted(set(duplicate_keys)))
        )
    if not isinstance(payload, dict):
        raise InitialMappingResponseValidationError("Response JSON must be an object")
    missing = RESPONSE_KEYS - set(payload)
    unknown = set(payload) - RESPONSE_KEYS
    if missing or unknown:
        raise InitialMappingResponseValidationError(
            f"Response keys are invalid; missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    return payload


def validate_initial_mapping_response(
    payload: Mapping[str, Any],
    candidate_set: SectionAwareCandidateSet,
) -> dict[str, Any]:
    decision = str(payload.get("decision") or "").strip()
    if decision not in ALLOWED_DECISIONS - {
        "provider_failed",
        "validation_failed",
        "retrieval_failed",
        "structural_only",
    }:
        raise InitialMappingResponseValidationError("Unknown or externally forbidden decision")
    if payload.get("requires_human_review") is not True:
        raise InitialMappingResponseValidationError("Every #19C response must require human review")
    confidence = payload.get("confidence")
    if isinstance(confidence, bool):
        raise InitialMappingResponseValidationError("confidence must be numeric")
    try:
        confidence = float(confidence)
    except (TypeError, ValueError) as exc:
        raise InitialMappingResponseValidationError("confidence must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise InitialMappingResponseValidationError("confidence must be between 0 and 1")
    reason = " ".join(str(payload.get("reason") or "").split())
    if not reason:
        raise InitialMappingResponseValidationError("reason is required")

    by_id = {candidate.concept_id: candidate for candidate in candidate_set.candidates}
    selected_id = payload.get("selected_concept_id")
    selected_qname = payload.get("selected_qname")
    if selected_id is not None:
        selected_id = str(selected_id)
    if selected_qname is not None:
        selected_qname = str(selected_qname)
    if (selected_id is None) != (selected_qname is None):
        raise InitialMappingResponseValidationError(
            "selected_concept_id and selected_qname must both be present or both be null"
        )
    if decision == "mapped":
        if not selected_id or selected_id not in by_id:
            raise InitialMappingResponseValidationError("Mapped concept is not in the supplied candidate set")
        if selected_qname != by_id[selected_id].qname:
            raise InitialMappingResponseValidationError("Selected qname does not match the supplied concept card")
    elif decision in {"abstain", "no_safe_mapping"}:
        if selected_id is not None or selected_qname is not None:
            raise InitialMappingResponseValidationError("Abstention cannot carry a selected concept")
    elif selected_id is not None:
        if selected_id not in by_id or selected_qname != by_id[selected_id].qname:
            raise InitialMappingResponseValidationError("Ambiguous selected concept is not supplied")

    raw_alternatives = payload.get("alternative_concept_ids")
    if not isinstance(raw_alternatives, list):
        raise InitialMappingResponseValidationError("alternative_concept_ids must be an array")
    alternatives = []
    for item in raw_alternatives:
        concept_id = str(item)
        if concept_id not in by_id:
            raise InitialMappingResponseValidationError("Alternative concept is not in the supplied candidate set")
        if concept_id != selected_id and concept_id not in alternatives:
            alternatives.append(concept_id)
    return {
        "decision": decision,
        "selected_concept_id": selected_id,
        "selected_qname": selected_qname,
        "confidence": confidence,
        "reason": reason,
        "alternative_concept_ids": alternatives,
        "requires_human_review": True,
    }


def deterministic_initial_mapping_decision(candidate_set: SectionAwareCandidateSet) -> dict[str, Any]:
    if candidate_set.candidate_outcome == "retrieval_failed":
        return {
            "decision": "retrieval_failed",
            "selected_concept_id": None,
            "selected_qname": None,
            "confidence": 0.0,
            "reason": "Candidate retrieval failed locally for this row; no mapping was attempted.",
            "alternative_concept_ids": [],
            "requires_human_review": True,
        }
    if not candidate_set.row_eligibility.eligible:
        return {
            "decision": "structural_only",
            "selected_concept_id": None,
            "selected_qname": None,
            "confidence": 0.0,
            "reason": f"Row retained as {candidate_set.row_eligibility.outcome}; no fact mapping was attempted.",
            "alternative_concept_ids": [],
            "requires_human_review": True,
        }
    if not candidate_set.candidates:
        return {
            "decision": "no_safe_mapping",
            "selected_concept_id": None,
            "selected_qname": None,
            "confidence": 0.0,
            "reason": "No selectable concept survived the classified template-group and compatibility filters.",
            "alternative_concept_ids": [],
            "requires_human_review": True,
        }
    if candidate_set.semantic_scope_limitations:
        return {
            "decision": "abstain",
            "selected_concept_id": None,
            "selected_qname": None,
            "confidence": 0.0,
            "reason": (
                "The source semantic family is absent from the authoritative classified "
                "template scope; related concepts remain visible for review but are not a "
                "safe mapping recommendation."
            ),
            "alternative_concept_ids": [],
            "requires_human_review": True,
        }
    top = candidate_set.candidates[0]
    second = candidate_set.candidates[1] if len(candidate_set.candidates) > 1 else None
    gap = top.score.total_score - (second.score.total_score if second else 0.0)
    if top.score.total_score >= 0.70 and gap >= 0.04:
        return {
            "decision": "mapped",
            "selected_concept_id": top.concept_id,
            "selected_qname": top.qname,
            "confidence": round(min(0.75, top.score.total_score), 4),
            "reason": "Deterministic advisory recommendation based on a strong local rank and separation; not an acceptance or correctness probability.",
            "alternative_concept_ids": [],
            "requires_human_review": True,
        }
    if second and top.score.total_score >= 0.60 and gap < 0.04:
        return {
            "decision": "ambiguous",
            "selected_concept_id": None,
            "selected_qname": None,
            "confidence": 0.0,
            "reason": "The leading deterministic candidates are too close to recommend one safely.",
            "alternative_concept_ids": [top.concept_id, second.concept_id],
            "requires_human_review": True,
        }
    return {
        "decision": "abstain",
        "selected_concept_id": None,
        "selected_qname": None,
        "confidence": 0.0,
        "reason": "Local candidate evidence is insufficient for a deterministic advisory recommendation.",
        "alternative_concept_ids": [top.concept_id],
        "requires_human_review": True,
    }


def _legacy_client_config(config: InitialMappingLLMConfig, max_candidates: int) -> LLMMappingConfig:
    return LLMMappingConfig(
        model_id=config.model_id,
        max_candidates=max_candidates,
        timeout_seconds=config.timeout_seconds,
        high_confidence_threshold=1.0,
        min_display_confidence=0.0,
        min_manual_confidence=0.0,
        max_rows_per_job=1,
        auto_apply_high_confidence=False,
        fewshot_enabled=False,
        fewshot_max_examples=0,
        fewshot_guardrails_enabled=True,
        fewshot_fallback_to_base_prompt=False,
        provider_rate_limit_max_retries=0,
        provider_request_delay_seconds=0.0,
    )


async def run_bounded_initial_mapping_llm(
    *,
    context: Mapping[str, Any],
    candidate_set: SectionAwareCandidateSet,
    config: InitialMappingLLMConfig,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    if config.mode == "deterministic_only":
        return {
            **deterministic_initial_mapping_decision(candidate_set),
            "mapping_method": "deterministic_only",
            "provider": None,
            "model": None,
            "provider_calls": 0,
            "prompt_hash": None,
            "payload_boundary_violations": 0,
        }
    if config.mode not in {"mock_llm", "live_llm"}:
        raise ValueError("Initial mapping mode must be deterministic_only, mock_llm, or live_llm")
    if not candidate_set.row_eligibility.eligible or not candidate_set.candidates:
        return {
            **deterministic_initial_mapping_decision(candidate_set),
            "mapping_method": "abstained",
            "provider": None,
            "model": None,
            "provider_calls": 0,
            "prompt_hash": None,
            "payload_boundary_violations": 0,
        }
    if config.mode == "live_llm" and (not config.enabled or not config.live_llm_enabled):
        return {
            "decision": "provider_failed",
            "selected_concept_id": None,
            "selected_qname": None,
            "confidence": 0.0,
            "reason": "Live initial mapping is not enabled.",
            "alternative_concept_ids": [],
            "requires_human_review": True,
            "mapping_method": "failed",
            "provider": "huggingface",
            "model": config.model_id,
            "provider_calls": 0,
            "prompt_hash": None,
            "payload_boundary_violations": 0,
        }
    prompt, prompt_hash = build_initial_mapping_prompt(context)
    client = llm_client or HuggingFaceQwenMappingClient()
    try:
        raw = await asyncio.wait_for(
            client.complete(
                prompt,
                config=_legacy_client_config(config, len(candidate_set.candidates)),
            ),
            timeout=config.timeout_seconds,
        )
    except Exception as exc:
        return {
            "decision": "provider_failed",
            "selected_concept_id": None,
            "selected_qname": None,
            "confidence": 0.0,
            "reason": f"Initial mapping provider failed safely: {type(exc).__name__}.",
            "alternative_concept_ids": [],
            "requires_human_review": True,
            "mapping_method": "failed",
            "provider": "mock" if config.mode == "mock_llm" else "huggingface",
            "model": config.model_id,
            "provider_calls": 1,
            "prompt_hash": prompt_hash,
            "payload_boundary_violations": 0,
        }
    try:
        validated = validate_initial_mapping_response(
            parse_strict_initial_mapping_response(raw),
            candidate_set,
        )
    except InitialMappingResponseValidationError as exc:
        return {
            "decision": "validation_failed",
            "selected_concept_id": None,
            "selected_qname": None,
            "confidence": 0.0,
            "reason": f"Initial mapping response failed closed: {exc}.",
            "alternative_concept_ids": [],
            "requires_human_review": True,
            "mapping_method": "failed",
            "provider": "mock" if config.mode == "mock_llm" else "huggingface",
            "model": config.model_id,
            "provider_calls": 1,
            "prompt_hash": prompt_hash,
            "payload_boundary_violations": 0,
        }
    return {
        **validated,
        "mapping_method": "bounded_llm",
        "provider": "mock" if config.mode == "mock_llm" else "huggingface",
        "model": config.model_id,
        "provider_calls": 1,
        "prompt_hash": prompt_hash,
        "payload_boundary_violations": 0,
    }
