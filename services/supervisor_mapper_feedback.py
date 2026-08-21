"""Leakage-safe Supervisor feedback payload for one manual mapper correction."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from database import LLMMappingSuggestion, MappingSupervisorReview
from services.azure_di_production_mapping import normalize_text
from services.llm_taxonomy_mapping import suggestion_template_metadata
from services.supervisor_production_review import build_production_supervisor_payload


FORBIDDEN_FEEDBACK_KEYS = {
    "auditor_xml",
    "paired_auditor_xbrl_facts",
    "parsed_xml_fact",
    "parsed_xml_facts",
    "xml_facts",
    "benchmark_gold_qname",
    "benchmark_gold_qnames",
    "benchmark_label",
    "expected_qname",
    "gold_qname",
    "gold_answer",
    "gold_answers",
    "target_gold_answer",
    "target_correct_qname",
    "target_correct_template_field_id",
    "target_template_field_id",
    "correct_concept_qname",
    "correct_template_field_id",
    "evaluation_label",
    "evaluation_labels",
    "is_correct",
    "strict_accuracy",
    "accuracy_when_predicted",
}

UNSAFE_REVIEW_ISSUES = {
    "invalid_supervisor_response",
    "unrepaired_invalid_supervisor_response",
    "unsafe_response",
}

CONCRETE_MAPPING_ISSUES = {
    "ambiguous_label",
    "broad_substitute",
    "candidate_not_supported",
    "missing_concept_card",
    "no_supporting_evidence",
    "statement_family_mismatch",
    "weak_label_match",
}


def _json_value(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback
    return decoded


def _clean(value: Any, limit: int = 1000) -> str:
    return " ".join(str(value or "").split())[:limit]


def _forbidden_paths(value: Any, path: str = "$") -> list[str]:
    paths: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            next_path = f"{path}.{key}"
            if str(key).lower() in FORBIDDEN_FEEDBACK_KEYS:
                paths.append(next_path)
            paths.extend(_forbidden_paths(nested, next_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            paths.extend(_forbidden_paths(nested, f"{path}[{index}]"))
    return paths


def assert_supervisor_mapper_feedback_safe(payload: Mapping[str, Any]) -> None:
    paths = _forbidden_paths(payload)
    if paths:
        raise ValueError(
            "Supervisor mapper feedback contains forbidden fields: "
            + ", ".join(sorted(paths))
        )


def supervisor_review_issues(review: MappingSupervisorReview) -> list[dict[str, Any]]:
    raw = _json_value(getattr(review, "supervisor_issues_json", None), [])
    if not isinstance(raw, list):
        return []
    return [dict(issue) for issue in raw if isinstance(issue, Mapping)][:12]


def supervisor_feedback_eligibility(review: MappingSupervisorReview | None) -> tuple[bool, str]:
    if review is None:
        return False, "missing_supervisor_review"
    if getattr(review, "review_status", None) != "completed":
        return False, "supervisor_review_not_completed"
    if getattr(review, "error_type", None):
        return False, "invalid_supervisor_review"

    issues = supervisor_review_issues(review)
    issue_types = {_clean(issue.get("type"), 80) for issue in issues}
    if issue_types & UNSAFE_REVIEW_ISSUES:
        return False, "unsafe_supervisor_review"

    decision = _clean(getattr(review, "supervisor_decision", None), 80).lower()
    action = _clean(getattr(review, "supervisor_recommended_action", None), 80).lower()
    if decision == "agree":
        return False, "supervisor_agreed"
    if decision in {"disagree", "prefer_alternative_candidate"}:
        return True, "eligible_supervisor_disagreement"
    if action in {"prefer_alternative_candidate", "request_better_candidate"}:
        return True, "eligible_better_candidate_request"
    if decision == "needs_human_review" and issue_types & CONCRETE_MAPPING_ISSUES:
        return True, "eligible_concrete_mapping_issue"
    return False, "supervisor_review_has_no_actionable_mapping_issue"


def _candidate_rows(suggestion: LLMMappingSuggestion) -> list[dict[str, Any]]:
    raw = _json_value(getattr(suggestion, "ranked_candidates_json", None), [])
    rows = raw if isinstance(raw, list) else []
    selected = _clean(getattr(suggestion, "suggested_template_field_id", None), 300)
    if selected and not any(
        _clean((row or {}).get("template_field_id"), 300) == selected
        for row in rows
        if isinstance(row, Mapping)
    ):
        rows.insert(
            0,
            {
                "template_field_id": selected,
                "confidence": getattr(suggestion, "confidence", None),
                "reason": getattr(suggestion, "reason", None),
            },
        )

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_row in rows:
        if not isinstance(raw_row, Mapping):
            continue
        template_field_id = _clean(
            raw_row.get("template_field_id")
            or raw_row.get("concept_qname")
            or raw_row.get("qname"),
            300,
        )
        if not template_field_id or template_field_id in seen:
            continue
        seen.add(template_field_id)
        metadata = suggestion_template_metadata(template_field_id) or {}
        candidates.append(
            {
                "template_field_id": template_field_id,
                "concept_qname": template_field_id,
                "label": _clean(raw_row.get("label") or metadata.get("label"), 500),
                "statement_type": _clean(
                    raw_row.get("statement_type") or metadata.get("statement_type"),
                    220,
                ),
                "template_code": _clean(
                    raw_row.get("template_code") or metadata.get("template_code"),
                    30,
                ),
                "confidence": raw_row.get("confidence"),
                "reason": _clean(raw_row.get("reason"), 600),
            }
        )
    return candidates[:10]


def _sanitized_concept_cards(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    allowed = (
        "concept_qname",
        "template_field_id",
        "canonical_label",
        "concept_label",
        "concept_family",
        "statement_type",
        "statement_families",
        "aliases",
        "definition",
        "when_to_use",
    )
    cards = []
    for card in payload.get("retrieved_concept_cards") or []:
        if isinstance(card, Mapping):
            cards.append({key: card.get(key) for key in allowed if key in card})
    return cards[:5]


def _sanitized_do_not_confuse(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    allowed = ("selected_card", "confusable_concept_qname", "reason", "example_labels")
    notes = []
    for note in payload.get("do_not_confuse_notes") or []:
        if isinstance(note, Mapping):
            notes.append({key: note.get(key) for key in allowed if key in note})
    return notes[:8]


def _supervisor_alternatives(issues: Sequence[Mapping[str, Any]]) -> tuple[list[Any], Any]:
    alternatives: list[Any] = []
    preferred: Any = None
    for issue in issues:
        for key in ("alternatives", "alternative_candidates"):
            value = issue.get(key)
            if isinstance(value, list):
                alternatives.extend(value[:5])
        candidate = issue.get("preferred_candidate") or issue.get("alternative_candidate")
        if candidate is not None and preferred is None:
            preferred = candidate
    return alternatives[:5], preferred


def build_supervisor_mapper_feedback_payload(
    suggestion: LLMMappingSuggestion,
    review: MappingSupervisorReview,
) -> dict[str, Any]:
    item = suggestion.extracted_data_item
    diagnostic = _json_value(getattr(suggestion, "diagnostic_json", None), {})
    diagnostic = diagnostic if isinstance(diagnostic, Mapping) else {}
    candidates = _candidate_rows(suggestion)
    review_issues = supervisor_review_issues(review)
    alternatives, preferred = _supervisor_alternatives(review_issues)
    evidence_source = build_production_supervisor_payload(suggestion)

    row_label = getattr(item, "extracted_label", None)
    payload = {
        "row": {
            "extracted_data_item_id": suggestion.extracted_data_item_id,
            "extracted_label": row_label,
            "normalized_label": normalize_text(row_label),
            "extracted_value": getattr(item, "extracted_value", None),
            "period": {
                "current_year": getattr(item, "financial_year", None),
                "previous_year": getattr(item, "financial_year_previous", None),
            },
            "statement_family": getattr(item, "statement_type", None),
            "section_block": diagnostic.get("section_block"),
            "row_role": diagnostic.get("row_role"),
            "note_boundary": diagnostic.get("note_boundary")
            or diagnostic.get("note_boundary_type"),
        },
        "initial_mapping_suggestion": {
            "suggested_template_field_id": suggestion.suggested_template_field_id,
            "suggested_concept_qname": suggestion.suggested_template_field_id,
            "confidence": suggestion.confidence,
            "reason": suggestion.reason,
            "status": suggestion.status,
        },
        "candidate_concepts": candidates,
        "supervisor_feedback": {
            "review_id": review.id,
            "decision": review.supervisor_decision,
            "reason": review.supervisor_reason,
            "issues": review_issues,
            "recommended_action": review.supervisor_recommended_action,
            "alternatives": alternatives,
            "preferred_candidate": preferred,
        },
        "permitted_concept_card_evidence": _sanitized_concept_cards(evidence_source),
        "do_not_confuse_guidance": _sanitized_do_not_confuse(evidence_source),
        "safety": {
            "supervisor_feedback_is_advisory": True,
            "auditor_xml_included": False,
            "parsed_xml_facts_included": False,
            "target_gold_answers_included": False,
            "evaluation_labels_included": False,
        },
    }
    assert_supervisor_mapper_feedback_safe(payload)
    return payload


def build_supervisor_guided_mapping_prompt(payload: Mapping[str, Any]) -> str:
    assert_supervisor_mapper_feedback_safe(payload)
    prompt_payload = {
        **payload,
        "required_output_schema": {
            "selected_template_field_id": "string from candidate_concepts or null",
            "confidence": 0.0,
            "reason": "short evidence-based reason",
            "ranked_candidates": [
                {
                    "template_field_id": "string from candidate_concepts",
                    "confidence": 0.0,
                    "reason": "short evidence-based reason",
                }
            ],
            "addressed_supervisor_issues": [
                {"type": "issue type", "resolution": "how evidence addressed it"}
            ],
            "remaining_ambiguities": ["short ambiguity"],
            "requires_human_confirmation": True,
            "rejection_reason": "string or null",
        },
    }
    return (
        "You are reconsidering one candidate-constrained financial taxonomy mapping.\n\n"
        "Rules:\n"
        "- Supervisor feedback is advisory evidence and is not guaranteed to be correct.\n"
        "- Reconsider the original mapping independently and address each concrete issue.\n"
        "- Choose only a candidate_concepts.template_field_id; never invent a concept.\n"
        "- Prefer null when label meaning, statement family, row role, period, or note boundary is insufficient.\n"
        "- If evidence remains insufficient, return null and describe it in remaining_ambiguities.\n"
        "- Do not use or infer auditor XML, benchmark gold answers, target correct qnames, or evaluation labels.\n"
        "- The result always requires human confirmation and is never safe for automatic apply.\n"
        "- Return strict JSON only, without markdown or surrounding commentary.\n\n"
        "Input:\n"
        + json.dumps(prompt_payload, ensure_ascii=True, sort_keys=True)
    )
