"""Single-call, strict-JSON fallback classifier for unresolved #19B sections."""

from __future__ import annotations

import json
from typing import Any, Mapping, Protocol, Sequence

from config import settings
from schemas import (
    SectionClassificationOutcome,
    SectionClassificationOutcomeType,
    TemplateGroupAssignment,
    TemplateGroupAssignmentMethod,
    TemplateGroupCard,
)


PROMPT_VERSION = "19B-template-group-v1"
PROVIDER = "huggingface"
ALLOWED_OUTCOMES = {
    "matched",
    "multiple_templates",
    "narrative_only",
    "container_only",
    "not_applicable",
    "ambiguous",
    "unassigned",
}


class TemplateGroupLLMError(ValueError):
    """Safe, fail-closed error for provider or structured-output failures."""


class TemplateGroupLLMClient(Protocol):
    async def complete(self, prompt: str, *, model_id: str) -> Any: ...


class HuggingFaceTemplateGroupClassificationClient:
    """Minimal one-request Hugging Face chat client; no retry loop."""

    async def complete(self, prompt: str, *, model_id: str) -> Any:
        token = str(getattr(settings, "model_api_token", "") or "").strip()
        if token in {"", "replace-with-your-model-provider-token", "YOUR_MODEL_API_TOKEN_HERE"}:
            raise TemplateGroupLLMError("Template classification provider is not configured")
        try:
            from huggingface_hub import AsyncInferenceClient
        except ImportError as exc:
            raise TemplateGroupLLMError(
                "Template classification provider client is unavailable"
            ) from exc
        client = AsyncInferenceClient(model=model_id, token=token)
        try:
            return await client.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Classify only from the supplied canonical template cards. "
                            "Return strict JSON and never invent an ID."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=800,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            raise TemplateGroupLLMError("Template classification provider call failed") from exc


def _extract_payload(raw: Any) -> Mapping[str, Any]:
    value = raw
    if hasattr(value, "choices"):
        choices = getattr(value, "choices") or []
        if choices:
            message = getattr(choices[0], "message", None)
            value = getattr(message, "content", message)
    elif isinstance(value, Mapping) and "choices" in value:
        choices = value.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            value = message.get("content", message)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise TemplateGroupLLMError("Template classification response is not valid JSON") from exc
    if not isinstance(value, Mapping):
        raise TemplateGroupLLMError("Template classification response must be a JSON object")
    return value


def _confidence(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TemplateGroupLLMError("Template classification confidence is invalid") from exc
    if not 0 <= result <= 1:
        raise TemplateGroupLLMError("Template classification confidence is outside 0..1")
    return result


def validate_template_group_llm_response(
    raw: Any,
    *,
    cards: Sequence[TemplateGroupCard],
    source_section_id: str,
    raw_title: str,
    normalized_title: str,
    canonical_section_type: str,
    parent_section_id: str | None,
    section_level: int,
    page_range: dict,
    provider: str = PROVIDER,
    model: str,
) -> SectionClassificationOutcome:
    """Validate IDs and outcome invariants; invalid output never degrades silently."""
    payload = _extract_payload(raw)
    outcome_text = str(payload.get("outcome") or "")
    if outcome_text not in ALLOWED_OUTCOMES:
        raise TemplateGroupLLMError("Template classification outcome is invalid")
    by_id = {card.template_group_id: card for card in cards}
    raw_assignments = payload.get("assignments") or []
    if not isinstance(raw_assignments, list):
        raise TemplateGroupLLMError("Template classification assignments must be a list")
    assignments: list[TemplateGroupAssignment] = []
    seen: set[str] = set()
    for raw_assignment in raw_assignments:
        if not isinstance(raw_assignment, Mapping):
            raise TemplateGroupLLMError("Template classification assignment is invalid")
        template_group_id = str(raw_assignment.get("template_group_id") or "")
        card = by_id.get(template_group_id)
        if card is None:
            raise TemplateGroupLLMError("Template classification returned an unknown ID")
        if template_group_id in seen:
            continue
        seen.add(template_group_id)
        evidence = raw_assignment.get("evidence") or []
        if not isinstance(evidence, list):
            raise TemplateGroupLLMError("Template classification evidence must be a list")
        confidence = _confidence(raw_assignment.get("confidence"))
        assignments.append(
            TemplateGroupAssignment(
                assignment_id=f"{source_section_id}:{template_group_id}",
                source_section_id=source_section_id,
                parent_section_id=parent_section_id,
                template_group_id=template_group_id,
                template_code=card.code,
                canonical_template_name=card.canonical_name,
                assignment_method=TemplateGroupAssignmentMethod.BOUNDED_LLM,
                confidence=confidence,
                evidence=[
                    str(item)[:500]
                    for item in evidence[:5]
                    if str(item).strip()
                ],
                requires_human_review=bool(
                    payload.get("requires_human_review")
                    or confidence < 0.7
                ),
            )
        )

    if outcome_text == "matched" and len(assignments) != 1:
        raise TemplateGroupLLMError("Matched outcome requires exactly one assignment")
    if outcome_text == "multiple_templates" and len(assignments) < 2:
        raise TemplateGroupLLMError(
            "Multiple-templates outcome requires at least two assignments"
        )
    if outcome_text in {
        "narrative_only",
        "container_only",
        "not_applicable",
        "ambiguous",
        "unassigned",
    } and assignments:
        raise TemplateGroupLLMError(
            f"{outcome_text} outcome cannot carry template assignments"
        )

    alternatives = payload.get("alternative_template_group_ids") or []
    if not isinstance(alternatives, list):
        raise TemplateGroupLLMError("Alternative template IDs must be a list")
    alternative_ids: list[str] = []
    for value in alternatives:
        template_group_id = str(value)
        if template_group_id not in by_id:
            raise TemplateGroupLLMError("Template classification returned an unknown ID")
        if template_group_id not in alternative_ids:
            alternative_ids.append(template_group_id)
    confidence = (
        min(assignment.confidence for assignment in assignments)
        if assignments
        else _confidence(payload.get("confidence", 0.35))
    )
    requires_review = bool(
        payload.get("requires_human_review")
        or confidence < 0.7
        or outcome_text in {"ambiguous", "unassigned"}
    )
    if requires_review:
        for assignment in assignments:
            assignment.requires_human_review = True
    reason = str(payload.get("reason") or "")[:1000]
    return SectionClassificationOutcome(
        section_id=source_section_id,
        raw_title=raw_title,
        normalized_title=normalized_title,
        canonical_section_type=canonical_section_type,
        section_level=section_level,
        parent_section_id=parent_section_id,
        page_range=dict(page_range),
        outcome=SectionClassificationOutcomeType(outcome_text),
        assignments=assignments,
        alternative_template_group_ids=alternative_ids,
        confidence=confidence,
        evidence=[reason] if reason else [],
        warnings=["low_confidence_requires_human_review"] if requires_review else [],
        requires_human_review=requires_review,
        llm_called=True,
        provider=provider,
        model=model,
        prompt_version=PROMPT_VERSION,
    )


async def classify_with_bounded_llm(
    *,
    context: Mapping[str, Any],
    cards: Sequence[TemplateGroupCard],
    source_section_id: str,
    raw_title: str,
    normalized_title: str,
    canonical_section_type: str,
    parent_section_id: str | None,
    section_level: int,
    page_range: dict,
    client: TemplateGroupLLMClient | None = None,
) -> SectionClassificationOutcome:
    """Make exactly one provider call for one unresolved subsection."""
    if not bool(
        getattr(
            settings,
            "toc_aware_template_classification_live_llm_enabled",
            False,
        )
    ):
        raise TemplateGroupLLMError("Live template classification fallback is disabled")
    model_id = str(
        getattr(settings, "toc_aware_template_classification_model_id", "") or ""
    )
    prompt = json.dumps(
        {
            "task": "classify_document_section_into_canonical_template_groups",
            "allowed_outcomes": sorted(ALLOWED_OUTCOMES),
            "required_response": {
                "outcome": "matched",
                "assignments": [
                    {
                        "template_group_id": "one supplied ID",
                        "confidence": 0.0,
                        "evidence": ["bounded source evidence"],
                    }
                ],
                "alternative_template_group_ids": [],
                "requires_human_review": False,
                "reason": "brief reason",
            },
            "context": dict(context),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raw = await (client or HuggingFaceTemplateGroupClassificationClient()).complete(
        prompt,
        model_id=model_id,
    )
    return validate_template_group_llm_response(
        raw,
        cards=cards,
        source_section_id=source_section_id,
        raw_title=raw_title,
        normalized_title=normalized_title,
        canonical_section_type=canonical_section_type,
        parent_section_id=parent_section_id,
        section_level=section_level,
        page_range=page_range,
        provider=PROVIDER,
        model=model_id,
    )
