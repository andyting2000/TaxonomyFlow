"""Independent Supervisor LLM client for #17D-B evaluation reports.

This module is deliberately separate from the production mapper LLM client. It
uses only SUPERVISOR_LLM_* settings for live calls and refuses to silently fall
back to MODEL_API_TOKEN, TEXT_MODEL_ID, or LLM_MAPPING_MODEL_ID.
"""

from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable, Mapping, Sequence

from config import settings
from services.supervisor_mapping_review import validate_supervisor_response


PLACEHOLDER_TOKENS = {
    "",
    "replace-with-your-model-provider-token",
    "replace-with-your-supervisor-token",
    "YOUR_MODEL_API_TOKEN_HERE",
    "your-token-here",
}
RESPONSE_FORMAT_MODES = {"json_schema", "json_object", "none"}
MISSING_CONFIG_MESSAGE = (
    "Supervisor LLM is not configured. Set SUPERVISOR_LLM_ENABLED=true, "
    "SUPERVISOR_LLM_MODEL_ID, and SUPERVISOR_LLM_API_TOKEN."
)

SUPERVISOR_REVIEW_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "review_decision",
        "risk_level",
        "reason",
        "issues",
        "recommended_action",
        "confidence_adjustment",
        "safe_to_accept",
    ],
    "properties": {
        "review_decision": {"type": "string", "enum": ["agree", "disagree", "needs_human_review"]},
        "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
        "reason": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "description"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
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
                        ],
                    },
                    "description": {"type": "string"},
                },
            },
        },
        "recommended_action": {
            "type": "string",
            "enum": ["accept", "reject", "keep_for_human_review", "request_better_candidate"],
        },
        "confidence_adjustment": {"type": "string", "enum": ["increase", "keep", "decrease"]},
        "safe_to_accept": {"type": "boolean"},
    },
}


class SupervisorLLMConfigurationError(RuntimeError):
    """Raised when live Supervisor evaluation is requested without config."""


class SupervisorLLMRateLimitError(RuntimeError):
    """Raised when the Supervisor provider reports a temporary rate limit."""

    def __init__(
        self,
        message: str = "Supervisor LLM provider is temporarily rate limited.",
        *,
        retry_after_seconds: float | None = None,
        attempt_count: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.attempt_count = attempt_count

    def to_summary(self) -> dict[str, Any]:
        return {
            "provider_error_type": "provider_rate_limited",
            "retry_after_seconds": self.retry_after_seconds,
            "attempt_count": self.attempt_count,
        }


class SupervisorProviderHTTPError(RuntimeError):
    """Structured non-429 HTTP error from the Supervisor provider."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        reason: str,
        sanitized_error_body: str,
        model_id: str,
        base_url: str,
        response_format_mode: str,
        json_schema_sent: bool,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.sanitized_error_body = sanitized_error_body
        self.model_id = model_id
        self.base_url = base_url
        self.response_format_mode = response_format_mode
        self.json_schema_sent = json_schema_sent
        self.guidance = provider_error_guidance(sanitized_error_body)

    def to_summary(self) -> dict[str, Any]:
        return {
            "provider_error_type": "provider_http_error",
            "status_code": self.status_code,
            "reason": self.reason,
            "sanitized_error_body": self.sanitized_error_body,
            "model_id": self.model_id,
            "base_url": self.base_url,
            "request_feature_flags": {
                "response_format_mode": self.response_format_mode,
                "json_schema_sent": self.json_schema_sent,
            },
            "guidance": list(self.guidance),
        }


class SupervisorLLMInvalidResponseError(ValueError):
    """Typed invalid Supervisor response with sanitized diagnostics."""

    def __init__(
        self,
        category: str,
        message: str,
        *,
        raw_text: str,
        raw_response_shape: str,
        config: "SupervisorLLMConfig | None" = None,
        repair_attempted: bool = False,
        repair_succeeded: bool = False,
        repair_error_category: str | None = None,
        repair_error_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.validator_error_message = message
        self.raw_response_shape = raw_response_shape
        self.sanitized_raw_response_excerpt = _sanitize_text_excerpt(raw_text, config=config, max_chars=1500)
        self.repair_attempted = repair_attempted
        self.repair_succeeded = repair_succeeded
        self.repair_error_category = repair_error_category
        self.repair_error_message = repair_error_message

    def with_repair_failure(self, repair_error: "SupervisorLLMInvalidResponseError") -> "SupervisorLLMInvalidResponseError":
        return SupervisorLLMInvalidResponseError(
            self.category,
            self.validator_error_message,
            raw_text=self.sanitized_raw_response_excerpt,
            raw_response_shape=self.raw_response_shape,
            repair_attempted=True,
            repair_succeeded=False,
            repair_error_category=repair_error.category,
            repair_error_message=repair_error.validator_error_message,
        )

    def to_diagnostic(self, *, config: "SupervisorLLMConfig") -> dict[str, Any]:
        diagnostic = {
            "validator_error_category": self.category,
            "validator_error_message": self.validator_error_message,
            "sanitized_raw_response_excerpt": self.sanitized_raw_response_excerpt,
            "raw_response_shape": self.raw_response_shape,
            "response_format_mode": config.response_format,
            "model_id": config.model_id,
            "repair_attempted": self.repair_attempted,
            "repair_succeeded": self.repair_succeeded,
        }
        if self.repair_error_category:
            diagnostic["repair_error_category"] = self.repair_error_category
        if self.repair_error_message:
            diagnostic["repair_error_message"] = self.repair_error_message
        return diagnostic


@dataclass(frozen=True)
class SupervisorLLMConfig:
    enabled: bool = False
    provider: str = "hf"
    api_token: str = ""
    model_id: str = ""
    base_url: str = "https://router.huggingface.co/v1"
    response_format: str = "json_schema"
    timeout_seconds: float = 120.0
    max_retries: int = 2
    retry_base_seconds: float = 3.0
    retry_max_seconds: float = 30.0
    repair_enabled: bool = True
    max_repair_retries: int = 1

    @classmethod
    def from_settings(cls, settings_obj: Any = settings) -> "SupervisorLLMConfig":
        return cls(
            enabled=bool(getattr(settings_obj, "supervisor_llm_enabled", False)),
            provider=str(getattr(settings_obj, "supervisor_llm_provider", "hf") or "hf").strip().lower(),
            api_token=str(getattr(settings_obj, "supervisor_llm_api_token", "") or "").strip(),
            model_id=str(getattr(settings_obj, "supervisor_llm_model_id", "") or "").strip(),
            base_url=str(
                getattr(settings_obj, "supervisor_llm_base_url", "https://router.huggingface.co/v1")
                or "https://router.huggingface.co/v1"
            ).strip(),
            response_format=str(
                getattr(settings_obj, "supervisor_llm_response_format", "json_schema") or "json_schema"
            ).strip().lower(),
            timeout_seconds=max(1.0, float(getattr(settings_obj, "supervisor_llm_timeout_seconds", 120) or 120)),
            max_retries=min(5, max(0, int(getattr(settings_obj, "supervisor_llm_max_retries", 2) or 2))),
            retry_base_seconds=max(0.0, float(getattr(settings_obj, "supervisor_llm_retry_base_seconds", 3) or 3)),
            retry_max_seconds=max(1.0, float(getattr(settings_obj, "supervisor_llm_retry_max_seconds", 30) or 30)),
            repair_enabled=bool(getattr(settings_obj, "supervisor_llm_repair_enabled", True)),
            max_repair_retries=min(3, max(0, int(getattr(settings_obj, "supervisor_llm_max_repair_retries", 1) or 1))),
        )

    def is_configured(self) -> bool:
        return self.enabled and self.model_id.strip() != "" and self.api_token.strip() not in PLACEHOLDER_TOKENS

    def require_live_config(self) -> None:
        if not self.is_configured():
            raise SupervisorLLMConfigurationError(MISSING_CONFIG_MESSAGE)
        if self.provider != "hf":
            raise SupervisorLLMConfigurationError("Only SUPERVISOR_LLM_PROVIDER=hf is supported for #17D-B.")
        if self.response_format not in RESPONSE_FORMAT_MODES:
            raise SupervisorLLMConfigurationError(
                "SUPERVISOR_LLM_RESPONSE_FORMAT must be one of: json_schema, json_object, none."
            )

    def redacted_summary(self, settings_obj: Any = settings) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "model_id": _redact_model_id(self.model_id),
            "base_url": self.base_url,
            "response_format": self.response_format,
            "api_token_configured": self.api_token.strip() not in PLACEHOLDER_TOKENS,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "retry_base_seconds": self.retry_base_seconds,
            "retry_max_seconds": self.retry_max_seconds,
            "repair_enabled": self.repair_enabled,
            "max_repair_retries": self.max_repair_retries,
            "supervisor_independence": supervisor_independence_status(self, settings_obj=settings_obj),
        }


def _redact_model_id(model_id: str) -> str:
    if not model_id:
        return ""
    if len(model_id) <= 16:
        return model_id[:4] + "..." if len(model_id) > 4 else "***"
    return f"{model_id[:10]}...{model_id[-6:]}"


def _sanitize_provider_error_body(body: str, config: SupervisorLLMConfig, *, max_chars: int = 2000) -> str:
    return _sanitize_text_excerpt(body, config=config, max_chars=max_chars)


def _sanitize_text_excerpt(body: str, *, config: SupervisorLLMConfig | None = None, max_chars: int = 1500) -> str:
    sanitized = str(body or "")
    token = (config.api_token if config is not None else "").strip()
    if token:
        sanitized = sanitized.replace(token, "[REDACTED_SUPERVISOR_TOKEN]")
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"hf_[A-Za-z0-9]{20,}", "hf_[REDACTED]", sanitized)
    return sanitized[:max_chars]


def provider_error_guidance(body: str) -> list[str]:
    text = str(body or "").lower()
    guidance: list[str] = []
    if "response_format" in text or "json_schema" in text or "schema" in text:
        guidance.append("Try SUPERVISOR_LLM_RESPONSE_FORMAT=json_object or none.")
    model_markers = (
        "model not found",
        "unknown model",
        "unsupported model",
        "provider not found",
        "not supported",
        "model_not_supported",
        "not a chat model",
        "does not exist",
        "not available",
    )
    if any(marker in text for marker in model_markers):
        guidance.append(
            "Try adding an HF router suffix such as :fastest, :preferred, :cheapest, or a specific provider suffix if supported."
        )
    return guidance


def supervisor_independence_status(
    config: SupervisorLLMConfig,
    *,
    settings_obj: Any = settings,
    mock_only: bool = False,
) -> str:
    if mock_only:
        return "mock_only"
    mapper_tokens = {
        str(getattr(settings_obj, "model_api_token", "") or "").strip(),
        str(getattr(settings_obj, "hugging_face_token", "") or "").strip(),
    } - PLACEHOLDER_TOKENS
    mapper_models = {
        str(getattr(settings_obj, "llm_mapping_model_id", "") or "").strip(),
        str(getattr(settings_obj, "ai_text_model_id", "") or "").strip(),
    } - {""}
    if config.api_token.strip() in mapper_tokens or config.model_id.strip() in mapper_models:
        return "limited_same_model_or_token"
    return "independent_model_or_token"


def is_rate_limit_error(exc: BaseException) -> bool:
    if isinstance(exc, SupervisorLLMRateLimitError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        return True
    text = str(exc).lower()
    return "429" in text or "rate limit" in text or "rate_limited" in text


def _retry_after_seconds(exc: BaseException) -> float | None:
    headers = getattr(exc, "headers", None)
    if headers is None or not hasattr(headers, "items"):
        return None
    retry_after = None
    for key, value in headers.items():
        if str(key).lower() == "retry-after":
            retry_after = value
            break
    if retry_after in {None, ""}:
        return None
    try:
        return max(0.0, float(str(retry_after).strip()))
    except (TypeError, ValueError):
        pass
    try:
        retry_at = parsedate_to_datetime(str(retry_after))
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _bounded_retry_delay(
    *,
    retry_after_seconds: float | None,
    attempt_index: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
) -> float:
    delay = retry_after_seconds
    if delay is None:
        delay = max(0.0, base_delay_seconds) * (2 ** max(0, attempt_index - 1))
    return min(max(0.0, delay), max(0.0, max_delay_seconds))


def _extract_embedded_json(text: str) -> str | None:
    start_positions = [index for index, char in enumerate(text or "") if char == "{"]
    for start in start_positions:
        stack = ["}"]
        in_string = False
        escape = False
        for index in range(start + 1, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char in "{[":
                stack.append("}" if char == "{" else "]")
                continue
            if stack and char == stack[-1]:
                stack.pop()
                if not stack:
                    return text[start : index + 1]
                continue
            if char in "}]":
                break
    return None


def _parse_json_object_candidate(
    candidate: str,
    *,
    shape: str,
    allow_nested_string: bool = True,
) -> tuple[dict[str, Any] | None, str | None, str]:
    try:
        parsed = json.loads(candidate)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, "invalid_json", shape
    if isinstance(parsed, dict):
        return parsed, None, shape
    if isinstance(parsed, str) and allow_nested_string:
        nested_text = parsed.strip()
        nested, nested_error, nested_shape = _parse_json_text(
            nested_text,
            default_shape=f"{shape}_nested_json_string",
            allow_embedded=True,
        )
        if nested is not None:
            return nested, None, nested_shape
        return None, nested_error or "invalid_json", nested_shape
    return None, "non_object_json_root", shape


def _parse_json_text(
    raw_text: str,
    *,
    default_shape: str,
    allow_embedded: bool = True,
) -> tuple[dict[str, Any] | None, str | None, str]:
    if not raw_text:
        return None, "parser_no_content", "invalid_json"
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw_text, re.IGNORECASE | re.DOTALL)
    candidates = [fence.group(1).strip()] if fence else []
    candidates.append(raw_text)
    embedded = _extract_embedded_json(raw_text) if allow_embedded else None
    if embedded and embedded not in candidates:
        candidates.append(embedded)
    first_error: str | None = None
    first_shape = "invalid_json"
    for candidate in candidates:
        shape = "markdown_json" if fence and candidate == candidates[0] else default_shape
        parsed, error, parsed_shape = _parse_json_object_candidate(candidate, shape=shape)
        if parsed is not None:
            return parsed, None, parsed_shape
        if error == "non_object_json_root" and candidate in {raw_text, candidates[0]}:
            return None, error, parsed_shape
        if first_error is None:
            first_error = error
            first_shape = parsed_shape
    return None, first_error or "invalid_json", first_shape


def _first_choice_value(choice: Any, key: str) -> Any:
    if isinstance(choice, Mapping):
        return choice.get(key)
    return getattr(choice, key, None)


def _choice_message_content(choice: Any) -> Any:
    message = _first_choice_value(choice, "message")
    if isinstance(message, Mapping):
        return message.get("content")
    return getattr(message, "content", None)


def _response_choices(raw_response: Any) -> Sequence[Any]:
    choices = raw_response.get("choices") if isinstance(raw_response, Mapping) else getattr(raw_response, "choices", None)
    return choices if isinstance(choices, (list, tuple)) else []


def parse_supervisor_llm_response(
    raw_response: Any,
    *,
    payload: Mapping[str, Any] | None = None,
    config: SupervisorLLMConfig | None = None,
) -> dict[str, Any]:
    raw_text = json.dumps(raw_response, ensure_ascii=True, default=str) if isinstance(raw_response, Mapping) else str(raw_response or "")
    parsed: dict[str, Any] | None = None
    parse_error: str | None = None
    content_text = raw_text
    shape = "direct_json"

    if isinstance(raw_response, Mapping) and "review_decision" in raw_response:
        parsed = dict(raw_response)
    else:
        choices = _response_choices(raw_response)
        if choices:
            first_choice = choices[0]
            content = _choice_message_content(first_choice)
            if content is not None:
                content_text = str(content).strip()
                parsed, parse_error, shape = _parse_json_text(
                    content_text,
                    default_shape="chat_completion_message_content",
                )
            else:
                choice_text = _first_choice_value(first_choice, "text")
                content_text = str(choice_text or "").strip()
                parsed, parse_error, shape = _parse_json_text(content_text, default_shape="chat_completion_text")
        elif isinstance(raw_response, Mapping) and raw_response.get("output_text") is not None:
            content_text = str(raw_response.get("output_text") or "").strip()
            parsed, parse_error, shape = _parse_json_text(content_text, default_shape="output_text")
        else:
            parsed, parse_error, shape = _parse_json_text(raw_text, default_shape="direct_json")

    if parse_error or parsed is None:
        raise SupervisorLLMInvalidResponseError(
            parse_error or "invalid_json",
            "Supervisor LLM response was not a valid JSON object.",
            raw_text=content_text or raw_text,
            raw_response_shape=shape,
            config=config,
        )
    try:
        review = validate_supervisor_response(parsed, payload=payload)
    except ValueError as exc:
        raise SupervisorLLMInvalidResponseError(
            "schema_validation_error",
            str(exc),
            raw_text=content_text or raw_text,
            raw_response_shape=shape,
            config=config,
        ) from exc
    return {
        "review": review,
        "raw_response_shape": shape,
        "raw_content_preview": content_text[:500],
    }


SupervisorTransport = Callable[[str, SupervisorLLMConfig], Awaitable[Any] | Any]


class SupervisorLLMClient:
    """OpenAI-compatible chat-completions client using supervisor config only."""

    def __init__(
        self,
        *,
        transport: SupervisorTransport | None = None,
        sleeper: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        self._transport = transport
        self._sleeper = sleeper or asyncio.sleep

    async def complete_review(
        self,
        prompt: str,
        *,
        payload: Mapping[str, Any],
        config: SupervisorLLMConfig | None = None,
    ) -> dict[str, Any]:
        live_config = config or SupervisorLLMConfig.from_settings()
        live_config.require_live_config()
        attempts_allowed = live_config.max_retries + 1
        last_rate_limit: BaseException | None = None

        for attempt_index in range(1, attempts_allowed + 1):
            try:
                raw_response = await asyncio.wait_for(
                    self._call_transport(prompt, live_config),
                    timeout=live_config.timeout_seconds,
                )
                parsed = parse_supervisor_llm_response(raw_response, payload=payload, config=live_config)
                parsed["attempt_count"] = attempt_index
                parsed["repair_attempted"] = False
                parsed["repair_succeeded"] = False
                return parsed
            except SupervisorLLMInvalidResponseError as exc:
                if not live_config.repair_enabled or live_config.max_repair_retries <= 0:
                    raise
                try:
                    repaired = await self._attempt_repair(
                        exc,
                        payload=payload,
                        config=live_config,
                    )
                except SupervisorLLMInvalidResponseError as repair_exc:
                    raise exc.with_repair_failure(repair_exc) from repair_exc
                repaired["attempt_count"] = attempt_index
                repaired["repair_attempted"] = True
                repaired["repair_succeeded"] = True
                repaired["initial_invalid_response"] = exc.to_diagnostic(config=live_config)
                return repaired
            except Exception as exc:
                if not is_rate_limit_error(exc):
                    raise
                last_rate_limit = exc
                retry_after = _retry_after_seconds(exc)
                if attempt_index >= attempts_allowed:
                    raise SupervisorLLMRateLimitError(
                        retry_after_seconds=retry_after,
                        attempt_count=attempt_index,
                    ) from exc
                delay = _bounded_retry_delay(
                    retry_after_seconds=retry_after,
                    attempt_index=attempt_index,
                    base_delay_seconds=live_config.retry_base_seconds,
                    max_delay_seconds=live_config.retry_max_seconds,
                )
                await self._sleeper(delay)

        raise SupervisorLLMRateLimitError(attempt_count=attempts_allowed) from last_rate_limit

    async def _call_transport(self, prompt: str, config: SupervisorLLMConfig) -> Any:
        if self._transport is not None:
            result = self._transport(prompt, config)
            if hasattr(result, "__await__"):
                return await result
            return result
        return await asyncio.to_thread(_post_chat_completion, prompt, config)

    async def _attempt_repair(
        self,
        invalid_error: SupervisorLLMInvalidResponseError,
        *,
        payload: Mapping[str, Any],
        config: SupervisorLLMConfig,
    ) -> dict[str, Any]:
        last_invalid = invalid_error
        repair_prompt = build_supervisor_repair_prompt(invalid_error)
        for repair_index in range(1, config.max_repair_retries + 1):
            raw_response = await asyncio.wait_for(
                self._call_transport(repair_prompt, config),
                timeout=config.timeout_seconds,
            )
            try:
                parsed = parse_supervisor_llm_response(raw_response, payload=payload, config=config)
                parsed["repair_attempt_count"] = repair_index
                return parsed
            except SupervisorLLMInvalidResponseError as exc:
                last_invalid = exc
        raise last_invalid


def build_supervisor_repair_prompt(invalid_error: SupervisorLLMInvalidResponseError) -> str:
    schema = {
        "review_decision": "agree|disagree|needs_human_review",
        "risk_level": "low|medium|high",
        "reason": "short reason using only the invalid response content",
        "issues": [{"type": "allowed issue type", "description": "short description"}],
        "recommended_action": "accept|reject|keep_for_human_review|request_better_candidate",
        "confidence_adjustment": "increase|keep|decrease",
        "safe_to_accept": False,
    }
    return "\n".join(
        [
            "Repair this into valid JSON only.",
            "Do not add new facts. Do not invent concepts. Return one JSON object only.",
            "Do not use markdown, fences, or explanations outside the JSON object.",
            "Use only these enum values:",
            "review_decision: agree, disagree, needs_human_review",
            "risk_level: low, medium, high",
            "recommended_action: accept, reject, keep_for_human_review, request_better_candidate",
            "confidence_adjustment: increase, keep, decrease",
            "issue.type: broad_substitute, statement_family_mismatch, weak_label_match, missing_concept_card, candidate_not_supported, person_or_company_name, note_number, ambiguous_label, no_supporting_evidence, invalid_supervisor_response, unrepaired_invalid_supervisor_response, repaired_supervisor_response, other",
            "safe_to_accept must be false unless review_decision is agree and risk_level is low.",
            "Required schema:",
            json.dumps(schema, separators=(",", ":"), ensure_ascii=True),
            f"Validator error category: {invalid_error.category}",
            f"Validator error message: {invalid_error.validator_error_message}",
            "Invalid response excerpt:",
            invalid_error.sanitized_raw_response_excerpt,
        ]
    )


def _post_chat_completion(prompt: str, config: SupervisorLLMConfig) -> Any:
    base_url = config.base_url.rstrip("/")
    url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    request_payload = {
        "model": config.model_id,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 900,
    }
    response_format = _response_format_payload(config.response_format)
    if response_format is not None:
        request_payload["response_format"] = response_format
    request = urllib.request.Request(
        url,
        data=json.dumps(request_payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.api_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        if exc.code == 429:
            raise SupervisorLLMRateLimitError(
                retry_after_seconds=_retry_after_seconds(exc),
            ) from exc
        sanitized = _sanitize_provider_error_body(error_body, config)
        raise SupervisorProviderHTTPError(
            "Supervisor LLM provider HTTP error.",
            status_code=int(exc.code),
            reason=str(exc.reason or ""),
            sanitized_error_body=sanitized,
            model_id=config.model_id,
            base_url=config.base_url,
            response_format_mode=config.response_format,
            json_schema_sent=config.response_format == "json_schema",
        ) from exc


def _response_format_payload(mode: str) -> dict[str, Any] | None:
    normalized = str(mode or "json_schema").strip().lower()
    if normalized == "none":
        return None
    if normalized == "json_object":
        return {"type": "json_object"}
    if normalized == "json_schema":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "supervisor_review",
                "strict": True,
                "schema": SUPERVISOR_REVIEW_JSON_SCHEMA,
            },
        }
    raise ValueError("unsupported supervisor response_format")
