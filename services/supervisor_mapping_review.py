"""Local Supervisor mapping review scaffold for #17D-A.

This module prepares payloads and deterministic mock review decisions for a
future Supervisor LLM. It is intentionally local-only: no provider call, DB
mutation, production job mutation, XBRL generation, or Arelle run occurs here.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Sequence

from services.fs_mpers_concept_playbook import (
    build_rag_evidence_payload,
    load_concept_playbook,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REVIEW_DECISIONS = {"agree", "disagree", "needs_human_review"}
RISK_LEVELS = {"low", "medium", "high"}
RECOMMENDED_ACTIONS = {"accept", "reject", "keep_for_human_review", "request_better_candidate"}
CONFIDENCE_ADJUSTMENTS = {"increase", "keep", "decrease"}
ISSUE_TYPES = {
    "broad_substitute",
    "statement_family_mismatch",
    "weak_label_match",
    "missing_concept_card",
    "candidate_not_supported",
    "person_or_company_name",
    "note_number",
    "ambiguous_label",
    "no_supporting_evidence",
    "invalid_supervisor_response",
    "unrepaired_invalid_supervisor_response",
    "repaired_supervisor_response",
    "other",
}
SAFE_ACCEPT_BLOCKING_ISSUES = {
    "broad_substitute",
    "statement_family_mismatch",
    "weak_label_match",
    "missing_concept_card",
    "candidate_not_supported",
    "person_or_company_name",
    "note_number",
    "ambiguous_label",
    "no_supporting_evidence",
    "invalid_supervisor_response",
    "unrepaired_invalid_supervisor_response",
}
SAFE_ACCEPT_MIN_CONFIDENCE = 0.90
SAFE_ACCEPT_WITHHELD_REASON_LABELS = {
    "non_agree_cannot_be_safe_accept": "Supervisor decision was not agree",
    "medium_or_high_risk_cannot_be_safe_accept": "Supervisor risk was not low",
    "recommended_action_not_accept_cannot_be_safe_accept": "Supervisor recommended action was not accept",
    "broad_substitute_requires_human_review": "broad substitute risk requires human review",
    "ambiguous_label_requires_human_review": "ambiguous label requires human review",
    "issue_type_requires_human_review": "a Supervisor issue requires human review",
    "selected_concept_not_in_candidates_cannot_be_safe_accept": "selected concept was not in the candidate list",
    "missing_selected_concept_cannot_be_safe_accept": "no selected concept was available",
    "non_fact_row_cannot_be_safe_accept": "row appears to be narrative or non-fact content",
    "mapper_confidence_below_safe_threshold": "mapper confidence was below the safe-accept threshold",
}
LEAKAGE_MARKERS = (
    "auditor_xml",
    "reference_xml",
    "parsed_xml_fact",
    "parsed_xml_facts",
    "target_gold_answer",
    "evaluation_label",
    "correct_concept_qname",
    "correct_template_field_id",
    "candidate_facts",
    "fact_id",
    "context_ref",
    "unit_ref",
)
STOPWORDS = {
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "total",
    "year",
}
BROAD_TERMS = (
    "assets",
    "liabilities",
    "equity and liabilities",
    "current assets",
    "current liabilities",
    "non-current assets",
    "non-current liabilities",
    "total assets",
    "total liabilities",
)
COMPANY_PERSON_PATTERNS = (
    r"\bsd[n.]?\s*bhd\b",
    r"\bberhad\b",
    r"\bbhd\b",
    r"\bltd\b",
    r"\blimited\b",
    r"\bplc\b",
    r"\bdirector\b",
    r"\bshareholder\b",
)
AMBIGUOUS_LABELS = {
    "other",
    "others",
    "miscellaneous",
    "capital",
    "expenses",
    "income",
    "amount due",
    "amount due from",
    "amount due to",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def _normalize_label(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _normalize_text(value))).strip()


def _tokens(value: Any) -> set[str]:
    return {token for token in _normalize_label(value).split() if token and token not in STOPWORDS}


def _token_overlap(left: Any, right: Any) -> float:
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _similarity(left: Any, right: Any) -> float:
    left_text = _normalize_label(left)
    right_text = _normalize_label(right)
    if not left_text or not right_text:
        return 0.0
    return max(SequenceMatcher(None, left_text, right_text).ratio(), _token_overlap(left_text, right_text))


def _compact_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "template_field_id",
        "concept_qname",
        "qname",
        "label",
        "statement_type",
        "template_code",
        "deterministic_score",
        "deterministic_method",
        "namespace",
        "required",
        "position",
    )
    return {key: candidate.get(key) for key in allowed if candidate.get(key) is not None}


def _candidate_ids(candidates: Sequence[Mapping[str, Any]]) -> set[str]:
    ids: set[str] = set()
    for candidate in candidates:
        for key in ("template_field_id", "concept_qname", "qname", "id", "xbrl_tag"):
            if candidate.get(key):
                ids.add(str(candidate[key]))
    return ids


def _risk_at_least_medium(risk: str) -> str:
    return "medium" if risk == "low" else risk


def _has_obvious_deterministic_evidence(payload: Mapping[str, Any] | None) -> bool:
    if payload is None:
        return False
    mapper = payload.get("mapper_suggestion") or {}
    try:
        confidence = float(mapper.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    selected_ids = {
        str(mapper.get("selected_template_field_id") or ""),
        str(mapper.get("selected_concept_qname") or ""),
    }
    selected_ids.discard("")
    for candidate in payload.get("candidate_concepts") or []:
        if not any(str(candidate.get(key) or "") in selected_ids for key in ("template_field_id", "concept_qname", "qname")):
            continue
        method = _normalize_text(candidate.get("deterministic_method"))
        try:
            score = float(candidate.get("deterministic_score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if confidence >= 0.97 and (score >= 0.97 or "exact" in method):
            return True
    return False


def _row_appears_non_fact(payload: Mapping[str, Any] | None) -> bool:
    if payload is None:
        return False
    row = payload.get("row") or {}
    label = _normalize_label(row.get("label"))
    row_type = _normalize_label(row.get("row_type"))
    if row_type in {"section_header", "heading", "text_block", "narrative", "context_only"}:
        return True
    non_fact_markers = {
        "discussion",
        "directors report",
        "statement by directors",
        "note",
        "notes",
        "schedule",
    }
    return any(marker in label for marker in non_fact_markers)


def _normalization_diagnostics(
    *,
    original: Mapping[str, Any],
    normalized: Mapping[str, Any],
    reasons: Sequence[str],
) -> dict[str, Any]:
    return {
        "changed": bool(reasons),
        "original_review_decision": original.get("review_decision"),
        "original_risk_level": original.get("risk_level"),
        "original_recommended_action": original.get("recommended_action"),
        "original_safe_to_accept": bool(original.get("safe_to_accept")),
        "normalized_review_decision": normalized.get("review_decision"),
        "normalized_risk_level": normalized.get("risk_level"),
        "normalized_recommended_action": normalized.get("recommended_action"),
        "normalized_safe_to_accept": bool(normalized.get("safe_to_accept")),
        "normalization_reasons": list(dict.fromkeys(reasons)),
    }


def _safe_accept_withheld_issue(reasons: Sequence[str]) -> dict[str, str]:
    labels = [
        SAFE_ACCEPT_WITHHELD_REASON_LABELS.get(reason, reason.replace("_", " "))
        for reason in dict.fromkeys(reasons)
    ]
    return {
        "type": "other",
        "description": "Safe flag withheld by guardrail: " + "; ".join(labels[:3]) + ".",
    }


def _normalize_safe_to_accept(review: dict[str, Any], payload: Mapping[str, Any] | None) -> dict[str, Any]:
    original = dict(review)
    normalized = dict(review)
    reasons: list[str] = []
    issue_types = {str(issue.get("type") or "") for issue in normalized.get("issues") or [] if isinstance(issue, Mapping)}

    if normalized["review_decision"] != "agree":
        reasons.append("non_agree_cannot_be_safe_accept")
    if normalized["risk_level"] != "low":
        reasons.append("medium_or_high_risk_cannot_be_safe_accept")
    if normalized["recommended_action"] != "accept":
        reasons.append("recommended_action_not_accept_cannot_be_safe_accept")

    if "broad_substitute" in issue_types:
        reasons.append("broad_substitute_requires_human_review")
        normalized["risk_level"] = _risk_at_least_medium(str(normalized["risk_level"]))
        normalized["recommended_action"] = "keep_for_human_review"
        normalized["confidence_adjustment"] = "decrease"
    if "ambiguous_label" in issue_types:
        reasons.append("ambiguous_label_requires_human_review")
        normalized["risk_level"] = _risk_at_least_medium(str(normalized["risk_level"]))
        normalized["recommended_action"] = "keep_for_human_review"
    blocking_issues = issue_types & SAFE_ACCEPT_BLOCKING_ISSUES
    if blocking_issues:
        if blocking_issues == {"missing_concept_card"} and _has_obvious_deterministic_evidence(payload):
            pass
        else:
            reasons.append("issue_type_requires_human_review")

    if payload is not None:
        mapper = payload.get("mapper_suggestion") or {}
        selected = str(mapper.get("selected_template_field_id") or mapper.get("selected_concept_qname") or "").strip()
        candidate_ids = _candidate_ids(payload.get("candidate_concepts") or [])
        if selected and selected not in candidate_ids:
            reasons.append("selected_concept_not_in_candidates_cannot_be_safe_accept")
        if not selected and normalized["recommended_action"] == "accept":
            reasons.append("missing_selected_concept_cannot_be_safe_accept")
        if _row_appears_non_fact(payload):
            reasons.append("non_fact_row_cannot_be_safe_accept")
        try:
            confidence = float(mapper.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if mapper.get("confidence") is not None and confidence < SAFE_ACCEPT_MIN_CONFIDENCE:
            reasons.append("mapper_confidence_below_safe_threshold")

    if reasons:
        normalized["safe_to_accept"] = False
        if not normalized.get("issues"):
            normalized["issues"] = [_safe_accept_withheld_issue(reasons)]
    normalized["normalization_diagnostics"] = _normalization_diagnostics(
        original=original,
        normalized=normalized,
        reasons=reasons,
    )
    return normalized


def _mapper_suggestion(row: Mapping[str, Any], mapper_suggestion: Mapping[str, Any] | None) -> dict[str, Any]:
    source = dict(mapper_suggestion or row.get("fewshot_qwen_prediction") or row.get("qwen_prediction") or {})
    selected_template = (
        source.get("predicted_template_field_id")
        or source.get("selected_template_field_id")
        or source.get("template_field_id")
    )
    selected_concept = (
        source.get("predicted_concept_qname")
        or source.get("selected_concept_qname")
        or source.get("concept_qname")
        or selected_template
    )
    return {
        "status": source.get("status"),
        "selected_template_field_id": selected_template,
        "selected_concept_qname": selected_concept,
        "confidence": source.get("confidence"),
        "confidence_tier": source.get("confidence_tier"),
        "reason": source.get("reason"),
        "rejection_reason": source.get("rejection_reason"),
        "ranked_candidates": [
            {
                key: ranked.get(key)
                for key in ("template_field_id", "concept_qname", "confidence", "reason")
                if ranked.get(key) is not None
            }
            for ranked in (source.get("ranked_candidates") or [])[:5]
            if isinstance(ranked, Mapping)
        ],
    }


def _row_context(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "label": row.get("label") or row.get("extracted_label"),
        "value": row.get("value") or row.get("extracted_value"),
        "previous_value": row.get("previous_value"),
        "statement_type": row.get("statement_type"),
        "row_type": row.get("row_type"),
        "page_number": row.get("page_number"),
        "source_case_id": row.get("source_case_id"),
        "extracted_row_id": row.get("extracted_row_id"),
    }


def _do_not_confuse_notes(cards: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    notes = []
    for card in cards:
        for confused in card.get("do_not_confuse_with") or []:
            notes.append(
                {
                    "selected_card": card.get("concept_qname"),
                    "confusable_concept_qname": confused.get("concept_qname"),
                    "reason": confused.get("reason"),
                    "example_labels": list(confused.get("example_labels") or [])[:3],
                }
            )
    return notes[:8]


def assert_supervisor_payload_is_leakage_safe(payload: Mapping[str, Any]) -> None:
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True).lower()
    for marker in LEAKAGE_MARKERS:
        if marker.lower() in text:
            raise ValueError(f"Supervisor payload contains forbidden marker: {marker}")


def build_supervisor_review_payload(
    row: Mapping[str, Any],
    mapper_suggestion: Mapping[str, Any] | None = None,
    candidate_concepts: Sequence[Mapping[str, Any]] | None = None,
    *,
    playbook: Mapping[str, Any] | None = None,
    max_cards: int = 5,
    max_examples: int = 3,
) -> dict[str, Any]:
    """Build a leakage-safe review payload for the future Supervisor LLM."""

    mapper = _mapper_suggestion(row, mapper_suggestion)
    raw_candidates = list(candidate_concepts or [])
    if not raw_candidates:
        source = mapper_suggestion or row.get("fewshot_qwen_prediction") or {}
        raw_candidates = list((source or {}).get("candidate_concepts") or row.get("candidate_concepts") or [])

    compact_candidates = [_compact_candidate(candidate) for candidate in raw_candidates if isinstance(candidate, Mapping)]
    row_context = _row_context(row)
    rag_row = {
        "label": row_context.get("label"),
        "value": row_context.get("value"),
        "statement_type": row_context.get("statement_type"),
        "source_case_id": row_context.get("source_case_id"),
    }
    evidence_payload = build_rag_evidence_payload(
        rag_row,
        compact_candidates,
        max_cards=max_cards,
        max_examples=max_examples,
        playbook=playbook or load_concept_playbook(),
    )
    cards = list(evidence_payload.get("retrieved_concept_cards") or [])
    examples = list(evidence_payload.get("retrieved_fewshot_examples") or [])
    payload = {
        "run_metadata": {
            "feature": "17D-A",
            "generated_at": _utc_now(),
            "local_only": True,
            "external_llm_called": False,
            "mock_review_only": True,
        },
        "row": row_context,
        "mapper_suggestion": mapper,
        "candidate_concepts": compact_candidates,
        "retrieved_concept_cards": cards,
        "retrieved_fewshot_examples": examples,
        "do_not_confuse_notes": _do_not_confuse_notes(cards),
        "missing_concept_card_diagnostics": evidence_payload.get("retrieval_diagnostics") or {},
        "guardrail_notes": list(evidence_payload.get("guardrail_notes") or [])[:8],
        "safety": {
            "auditor_source_included": False,
            "reference_fact_details_included": False,
            "target_answer_included": False,
            "scoring_labels_included": False,
            "external_llm_required": False,
        },
    }
    assert_supervisor_payload_is_leakage_safe(payload)
    return payload


def build_supervisor_prompt(payload: Mapping[str, Any]) -> str:
    """Build the future Supervisor prompt without calling any provider."""

    assert_supervisor_payload_is_leakage_safe(payload)
    valid_example = {
        "review_decision": "needs_human_review",
        "risk_level": "high",
        "reason": "The mapper selection is not strongly supported by the provided candidate and concept-card evidence.",
        "issues": [
            {
                "type": "weak_label_match",
                "description": "The row label and selected concept label are not a strong semantic match.",
            }
        ],
        "recommended_action": "keep_for_human_review",
        "confidence_adjustment": "decrease",
        "safe_to_accept": False,
    }
    instructions = (
        "You are reviewing a mapping suggestion, not creating a new mapping.\n"
        "Do not invent XBRL concepts.\n"
        "Do not replace the mapper answer with an unprovided concept.\n"
        "Use only the provided row, candidates, mapper suggestion, concept cards, few-shot examples, and do-not-confuse notes.\n"
        "If the mapper selected a concept that is not in the candidate list, reject it.\n"
        "Flag broad_substitute only when the selected concept is materially less specific than the row label.\n"
        "Do not flag broad_substitute for ordinary total/subtotal labels when the selected concept is the matching total/category concept, statement family matches, and candidate or concept-card evidence supports the same family.\n"
        "Still flag broad_substitute when a specific row label is mapped to a broad category, a clearer specific candidate exists, the selected concept loses material specificity, or do-not-confuse notes warn against the substitution.\n"
        "Mapper omission is a risk: if the mapper rejected or returned no prediction for a numeric fact-like row and candidates contain plausible concepts, choose needs_human_review or request_better_candidate.\n"
        "Do not agree with rejection only because the label is unusual, noisy, or uncommon when numeric financial fact context remains plausible.\n"
        "Section headers, discussion labels, and narrative-only rows can be accepted as non-facts only when numeric fact context is absent.\n"
        "If statement family mismatches, flag statement_family_mismatch.\n"
        "If concept card evidence is missing, do not overstate confidence.\n"
        "If evidence is weak, choose needs_human_review.\n"
        "Return strict JSON only: exactly one JSON object. Do not include markdown, fences, prose, or explanations outside the JSON object.\n"
        "Allowed review_decision: agree, disagree, needs_human_review.\n"
        "Allowed risk_level: low, medium, high.\n"
        "Allowed recommended_action: accept, reject, keep_for_human_review, request_better_candidate.\n"
        "Allowed confidence_adjustment: increase, keep, decrease.\n"
        "Allowed issue.type values: "
        + ", ".join(sorted(ISSUE_TYPES))
        + ".\n"
        "Set safe_to_accept=true only when review_decision=agree and risk_level=low; otherwise set safe_to_accept=false.\n"
        "safe_to_accept must remain false when hard risk issues exist, including broad_substitute, ambiguous_label, candidate_not_supported, statement_family_mismatch, missing_concept_card, no_supporting_evidence, person_or_company_name, or note_number.\n"
        "If candidates are close but not exact, return needs_human_review with safe_to_accept=false.\n"
    )
    schema = {
        "review_decision": "agree|disagree|needs_human_review",
        "risk_level": "low|medium|high",
        "reason": "short evidence-based reason",
        "issues": [{"type": "one allowed issue.type", "description": "short description"}],
        "recommended_action": "accept|reject|keep_for_human_review|request_better_candidate",
        "confidence_adjustment": "increase|keep|decrease",
        "safe_to_accept": False,
    }
    return (
        instructions
        + "\nSUPERVISOR_REVIEW_INPUT_JSON:\n"
        + json.dumps(payload, indent=2, ensure_ascii=True)
        + "\n\nREQUIRED_OUTPUT_JSON_SCHEMA_AT_END:\n"
        + json.dumps(schema, indent=2, ensure_ascii=True)
        + "\n\nCOMPACT_VALID_JSON_EXAMPLE:\n"
        + json.dumps(valid_example, separators=(",", ":"), ensure_ascii=True)
        + "\nReturn one JSON object only now."
    )


def _validate_issue(issue: Any) -> dict[str, str]:
    if not isinstance(issue, Mapping):
        raise ValueError("issue must be an object")
    issue_type = str(issue.get("type") or "")
    if issue_type not in ISSUE_TYPES:
        raise ValueError(f"invalid issue type: {issue_type}")
    description = str(issue.get("description") or "").strip()
    if not description:
        raise ValueError("issue description is required")
    return {"type": issue_type, "description": description[:500]}


def validate_supervisor_response(
    response: Mapping[str, Any] | str,
    *,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and normalize a strict Supervisor JSON response."""

    parsed = json.loads(response) if isinstance(response, str) else dict(response)
    decision = str(parsed.get("review_decision") or "")
    risk = str(parsed.get("risk_level") or "")
    action = str(parsed.get("recommended_action") or "")
    confidence_adjustment = str(parsed.get("confidence_adjustment") or "")
    if decision not in REVIEW_DECISIONS:
        raise ValueError(f"invalid review_decision: {decision}")
    if risk not in RISK_LEVELS:
        raise ValueError(f"invalid risk_level: {risk}")
    if action not in RECOMMENDED_ACTIONS:
        raise ValueError(f"invalid recommended_action: {action}")
    if confidence_adjustment not in CONFIDENCE_ADJUSTMENTS:
        raise ValueError(f"invalid confidence_adjustment: {confidence_adjustment}")

    issues = [_validate_issue(issue) for issue in (parsed.get("issues") or [])]
    replacement_keys = (
        "replacement_concept_qname",
        "replacement_template_field_id",
        "selected_replacement_concept",
        "correct_concept_qname",
        "correct_template_field_id",
    )
    replacement_values = [str(parsed.get(key) or "").strip() for key in replacement_keys if parsed.get(key)]
    if payload is not None and replacement_values:
        candidate_ids = _candidate_ids(payload.get("candidate_concepts") or [])
        if any(value not in candidate_ids for value in replacement_values):
            raise ValueError("Supervisor response introduced a replacement concept outside candidate list")
    safe_to_accept = bool(parsed.get("safe_to_accept"))
    reason = str(parsed.get("reason") or "").strip()
    if not reason:
        raise ValueError("reason is required")
    normalized = {
        "review_decision": decision,
        "risk_level": risk,
        "reason": reason[:1000],
        "issues": issues,
        "recommended_action": action,
        "confidence_adjustment": confidence_adjustment,
        "safe_to_accept": safe_to_accept,
    }
    return _normalize_safe_to_accept(normalized, payload)


def _selected_card(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    mapper = payload.get("mapper_suggestion") or {}
    selected_ids = {
        str(mapper.get("selected_template_field_id") or ""),
        str(mapper.get("selected_concept_qname") or ""),
    }
    selected_ids.discard("")
    for card in payload.get("retrieved_concept_cards") or []:
        if card.get("template_field_id") in selected_ids or card.get("concept_qname") in selected_ids:
            return card
    return None


def _selected_candidate(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    mapper = payload.get("mapper_suggestion") or {}
    selected_ids = {
        str(mapper.get("selected_template_field_id") or ""),
        str(mapper.get("selected_concept_qname") or ""),
    }
    selected_ids.discard("")
    for candidate in payload.get("candidate_concepts") or []:
        if any(candidate.get(key) in selected_ids for key in ("template_field_id", "concept_qname", "qname")):
            return candidate
    return None


def _statement_compatible(row_statement: Any, candidate_or_card: Mapping[str, Any]) -> bool:
    row_text = _normalize_label(row_statement)
    if not row_text:
        return True
    statements = []
    if candidate_or_card.get("statement_type"):
        statements.append(candidate_or_card.get("statement_type"))
    statements.extend(candidate_or_card.get("statement_families_observed") or [])
    if not statements:
        return True
    return any(row_text in _normalize_label(statement) or _normalize_label(statement) in row_text for statement in statements)


def _is_person_or_company_name(label: Any) -> bool:
    text = _normalize_text(label)
    if any(re.search(pattern, text) for pattern in COMPANY_PERSON_PATTERNS):
        return True
    tokens = str(label or "").split()
    return len(tokens) >= 3 and sum(1 for token in tokens if token.isupper() and len(token) > 1) >= 2


def _is_note_number(label: Any) -> bool:
    text = _normalize_label(label)
    return bool(re.fullmatch(r"(note\s*)?\d+[a-z]?", text) or re.fullmatch(r"\d+\s+.+", text))


def _is_ambiguous_label(label: Any) -> bool:
    text = _normalize_label(label)
    if text in AMBIGUOUS_LABELS:
        return True
    return len(_tokens(text)) <= 1 and text not in {"cash", "accruals"}


def _is_broad_substitute(payload: Mapping[str, Any], selected: Mapping[str, Any] | None) -> bool:
    if not selected:
        return False
    row_label = (payload.get("row") or {}).get("label")
    row_text = _normalize_label(row_label)
    selected_text = _normalize_label(
        " ".join(
            str(selected.get(key) or "")
            for key in ("template_field_id", "concept_qname", "qname", "label", "canonical_label")
        )
    )
    selected_families = set(selected.get("semantic_families") or [])
    if "broad_subtotal" in selected_families:
        return "total" not in row_text and len(_tokens(row_text)) > 1
    return any(term in selected_text for term in BROAD_TERMS) and "total" not in row_text and len(_tokens(row_text)) > 1


def _supporting_evidence(payload: Mapping[str, Any], selected_card: Mapping[str, Any] | None) -> bool:
    if selected_card:
        score = selected_card.get("retrieval_score")
        if score is None or float(score or 0.0) > 0:
            return True
    mapper = payload.get("mapper_suggestion") or {}
    selected = str(mapper.get("selected_template_field_id") or mapper.get("selected_concept_qname") or "")
    for example in payload.get("retrieved_fewshot_examples") or []:
        if selected and selected in {
            str(example.get("mapped_template_field_id") or ""),
            str(example.get("mapped_concept_qname") or ""),
        }:
            return True
    return False


def _add_issue(issues: list[dict[str, str]], issue_type: str, description: str) -> None:
    if not any(issue["type"] == issue_type for issue in issues):
        issues.append({"type": issue_type, "description": description})


def mock_supervisor_review(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Deterministic dry-run reviewer for local tests and reports."""

    assert_supervisor_payload_is_leakage_safe(payload)
    row = payload.get("row") or {}
    mapper = payload.get("mapper_suggestion") or {}
    label = row.get("label")
    selected = str(mapper.get("selected_template_field_id") or mapper.get("selected_concept_qname") or "")
    selected_candidate = _selected_candidate(payload)
    selected_card = _selected_card(payload)
    issues: list[dict[str, str]] = []

    if selected and selected not in _candidate_ids(payload.get("candidate_concepts") or []):
        _add_issue(issues, "candidate_not_supported", "Mapper selected concept is not present in candidate_concepts.")
    if _is_broad_substitute(payload, selected_card or selected_candidate):
        _add_issue(issues, "broad_substitute", "Selected concept appears broader than the specific extracted row label.")
    if not _statement_compatible(row.get("statement_type"), selected_card or selected_candidate or {}):
        _add_issue(issues, "statement_family_mismatch", "Selected concept statement family does not match the extracted row statement type.")
    if (payload.get("missing_concept_card_diagnostics") or {}).get("missing_relevant_concept_card"):
        _add_issue(issues, "missing_concept_card", "Local concept-card playbook reports no matching concept card for the expected semantic family.")
    if selected_card:
        breakdown = selected_card.get("score_breakdown") or {}
        if float(breakdown.get("label_similarity") or 0.0) < 0.35 and not breakdown.get("phrase_match_score"):
            _add_issue(issues, "weak_label_match", "Selected concept card has weak label similarity to the extracted row.")
    elif selected:
        candidate_label = (selected_candidate or {}).get("label")
        if _similarity(label, candidate_label) < 0.35:
            _add_issue(issues, "weak_label_match", "Selected candidate label has weak semantic similarity to the extracted row.")
    if _is_person_or_company_name(label):
        _add_issue(issues, "person_or_company_name", "Extracted row label appears to be a person or company name.")
    if _is_note_number(label):
        _add_issue(issues, "note_number", "Extracted row label appears to be a note number or note heading.")
    if _is_ambiguous_label(label):
        _add_issue(issues, "ambiguous_label", "Extracted row label is too generic or ambiguous for automatic acceptance.")
    if not _supporting_evidence(payload, selected_card):
        _add_issue(issues, "no_supporting_evidence", "No retrieved concept card or few-shot example directly supports the mapper selection.")

    issue_types = {issue["type"] for issue in issues}
    high_risk = issue_types & {"candidate_not_supported", "broad_substitute", "statement_family_mismatch", "person_or_company_name", "note_number"}
    if high_risk:
        decision = "disagree" if issue_types & {"candidate_not_supported", "broad_substitute", "statement_family_mismatch"} else "needs_human_review"
        risk = "high"
        action = "reject" if decision == "disagree" else "keep_for_human_review"
        confidence_adjustment = "decrease"
    elif issues:
        decision = "needs_human_review"
        risk = "medium"
        action = "request_better_candidate" if "missing_concept_card" in issue_types else "keep_for_human_review"
        confidence_adjustment = "decrease"
    else:
        decision = "agree"
        risk = "low"
        action = "accept"
        confidence_adjustment = "keep"

    reason = (
        "Mapper selection is supported by candidate, statement, and local concept-card/few-shot evidence."
        if decision == "agree"
        else "Supervisor mock found review issues: " + ", ".join(sorted(issue_types))
    )
    response = {
        "review_decision": decision,
        "risk_level": risk,
        "reason": reason,
        "issues": issues,
        "recommended_action": action,
        "confidence_adjustment": confidence_adjustment,
        "safe_to_accept": decision == "agree" and risk == "low",
    }
    return validate_supervisor_response(response, payload=payload)


def summarize_supervisor_review(reviews: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    decisions = Counter(str(review.get("review_decision") or "unknown") for review in reviews)
    risks = Counter(str(review.get("risk_level") or "unknown") for review in reviews)
    issues = Counter(
        issue.get("type")
        for review in reviews
        for issue in (review.get("issues") or [])
        if isinstance(issue, Mapping) and issue.get("type")
    )
    return {
        "total_reviewed": len(reviews),
        "agree": int(decisions.get("agree", 0)),
        "disagree": int(decisions.get("disagree", 0)),
        "needs_human_review": int(decisions.get("needs_human_review", 0)),
        "risk_level_counts": dict(sorted(risks.items())),
        "issue_type_counts": dict(sorted(issues.items())),
        "safe_to_accept": sum(1 for review in reviews if review.get("safe_to_accept") is True),
    }
