import base64
import asyncio
import json
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from config import settings


PLACEHOLDER_API_KEYS = {
    "",
    "replace-with-your-openai-api-key",
    "replace-with-your-model-provider-token",
    "YOUR_MODEL_API_TOKEN_HERE",
}


class OpenAIProviderError(Exception):
    """Base error for the OpenAI proof-of-life provider adapter."""


class OpenAIProviderConfigurationError(OpenAIProviderError):
    """Raised when OpenAI proof-of-life configuration is incomplete."""


@dataclass(frozen=True)
class OpenAIProviderConfig:
    api_key: str
    text_model: str
    vision_model: str
    embedding_model: str
    timeout_seconds: float = 30.0


def is_openai_provider(settings_obj: Any = settings) -> bool:
    # OpenAI remains available only through explicit legacy scripts/tests. It is
    # no longer an active product/runtime provider choice.
    return False


def load_openai_config(settings_obj: Any = settings) -> OpenAIProviderConfig:
    return OpenAIProviderConfig(
        api_key=str(getattr(settings_obj, "openai_api_key", "") or "").strip(),
        text_model=str(getattr(settings_obj, "openai_text_model", "gpt-4.1-mini") or "").strip(),
        vision_model=str(getattr(settings_obj, "openai_vision_model", "gpt-4.1-mini") or "").strip(),
        embedding_model=str(
            getattr(settings_obj, "openai_embedding_model", "text-embedding-3-large") or ""
        ).strip(),
    )


def is_openai_configured(config: Optional[OpenAIProviderConfig] = None) -> bool:
    config = config or load_openai_config()
    return config.api_key not in PLACEHOLDER_API_KEYS


def configuration_error_result(operation: str, config: Optional[OpenAIProviderConfig] = None) -> Dict[str, Any]:
    config = config or load_openai_config()
    model = config.text_model
    if operation == "vision":
        model = config.vision_model
    elif operation in {"embedding", "embeddings"}:
        model = config.embedding_model
    return {
        "ok": False,
        "provider": "openai",
        "operation": operation,
        "error_type": "configuration",
        "error": "OPENAI_API_KEY is not configured; set it before running OpenAI smoke tests.",
        "model": model,
    }


def _safe_error_message(error: Exception, config: Optional[OpenAIProviderConfig] = None) -> str:
    message = str(error)
    if config and config.api_key:
        message = message.replace(config.api_key, "[redacted]")
    return message


def provider_error_result(
    operation: str,
    model: str,
    error: Exception,
    config: Optional[OpenAIProviderConfig] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "provider": "openai",
        "operation": operation,
        "error_type": error.__class__.__name__,
        "error": _safe_error_message(error, config),
        "model": model,
    }


def create_openai_client(config: Optional[OpenAIProviderConfig] = None):
    config = config or load_openai_config()
    if not is_openai_configured(config):
        raise OpenAIProviderConfigurationError(
            "OPENAI_API_KEY is not configured; set it before running OpenAI smoke tests."
        )

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIProviderConfigurationError(
            "The openai Python SDK is not installed. Run python -B -m pip install -r requirements.txt."
        ) from exc

    return OpenAI(api_key=config.api_key, timeout=config.timeout_seconds)


def extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    output = getattr(response, "output", None) or []
    chunks = []
    for item in output:
        content = getattr(item, "content", None)
        if not content and isinstance(item, dict):
            content = item.get("content")
        for content_item in content or []:
            text = getattr(content_item, "text", None)
            if text is None and isinstance(content_item, dict):
                text = content_item.get("text")
            if text:
                chunks.append(str(text))
    return "\n".join(chunks).strip()


def parse_structured_json_output(raw_output: str) -> Dict[str, Any]:
    parsed = json.loads(raw_output)
    if not isinstance(parsed, dict):
        raise ValueError("Structured JSON smoke expected a JSON object.")
    return parsed


def document_classification_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "document_type": {"type": "string"},
            "confidence": {"type": "number"},
            "notes": {"type": "string"},
        },
        "required": ["document_type", "confidence", "notes"],
    }


def stage1_classification_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "code": {"type": "string"},
                        "confidence": {"type": "number"},
                        "section_location": {"type": "string"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["code", "confidence", "section_location", "reasoning"],
                },
            }
        },
        "required": ["classifications"],
    }


def extraction_items_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "template_code": {"type": "string"},
                        "section_location": {"type": "string"},
                        "concept_id": {"type": "string"},
                        "label": {"type": "string"},
                        "value": {"type": "string"},
                        "year": {"type": ["integer", "null"]},
                        "level": {"type": ["integer", "null"]},
                        "required": {"type": "boolean"},
                    },
                    "required": [
                        "template_code",
                        "section_location",
                        "concept_id",
                        "label",
                        "value",
                        "year",
                        "level",
                        "required",
                    ],
                },
            }
        },
        "required": ["items"],
    }


def _success_result(operation: str, model: str, output_text: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    result = {
        "ok": True,
        "provider": "openai",
        "operation": operation,
        "model": model,
        "output_text": output_text,
    }
    if extra:
        result.update(extra)
    return result


def openai_text_smoke(
    prompt: str,
    *,
    client: Any = None,
    config: Optional[OpenAIProviderConfig] = None,
) -> Dict[str, Any]:
    config = config or load_openai_config()
    if not is_openai_configured(config):
        return configuration_error_result("text", config)

    try:
        client = client or create_openai_client(config)
        response = client.responses.create(
            model=config.text_model,
            input=prompt,
            max_output_tokens=160,
        )
    except OpenAIProviderConfigurationError as exc:
        return configuration_error_result("text", config) | {"error": str(exc)}
    except Exception as exc:
        return provider_error_result("text", config.text_model, exc, config)
    return _success_result("text", config.text_model, extract_response_text(response))


def openai_structured_json_smoke(
    prompt: str,
    *,
    client: Any = None,
    config: Optional[OpenAIProviderConfig] = None,
) -> Dict[str, Any]:
    config = config or load_openai_config()
    if not is_openai_configured(config):
        return configuration_error_result("structured_json", config)

    try:
        client = client or create_openai_client(config)
        response = client.responses.create(
            model=config.text_model,
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "document_classification_smoke",
                    "strict": True,
                    "schema": document_classification_schema(),
                }
            },
            max_output_tokens=200,
        )
        output_text = extract_response_text(response)
        parsed = parse_structured_json_output(output_text)
    except OpenAIProviderConfigurationError as exc:
        return configuration_error_result("structured_json", config) | {"error": str(exc)}
    except Exception as exc:
        return provider_error_result("structured_json", config.text_model, exc, config)
    return _success_result(
        "structured_json",
        config.text_model,
        output_text,
        {"parsed_json": parsed},
    )


def encode_image_data_url(image_path: str) -> str:
    path = Path(image_path)
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def build_vision_input(image_path: str, prompt: str) -> Any:
    return build_vision_input_from_data_url(encode_image_data_url(image_path), prompt)


def build_vision_input_from_data_url(data_url: str, prompt: str) -> Any:
    return [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {
                    "type": "input_image",
                    "image_url": data_url,
                    "detail": "low",
                },
            ],
        }
    ]


def build_vision_input_from_base64(image_base64: str, prompt: str, mime_type: str = "image/png") -> Any:
    return build_vision_input_from_data_url(f"data:{mime_type};base64,{image_base64}", prompt)


def _json_schema_format(name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "strict": True,
            "schema": schema,
        }
    }


def openai_text_json_response(
    prompt: str,
    *,
    operation: str = "text_extraction",
    schema_name: str = "financial_extraction",
    schema: Optional[Dict[str, Any]] = None,
    max_output_tokens: int = 4096,
    client: Any = None,
    config: Optional[OpenAIProviderConfig] = None,
) -> Dict[str, Any]:
    """Call OpenAI text model for production-path JSON output without DB writes."""
    config = config or load_openai_config()
    if not is_openai_configured(config):
        return configuration_error_result(operation, config)

    schema = schema or extraction_items_schema()

    try:
        client = client or create_openai_client(config)
        response = client.responses.create(
            model=config.text_model,
            input=prompt,
            text=_json_schema_format(schema_name, schema),
            max_output_tokens=max_output_tokens,
        )
    except OpenAIProviderConfigurationError as exc:
        return configuration_error_result(operation, config) | {"error": str(exc)}
    except Exception as exc:
        return provider_error_result(operation, config.text_model, exc, config)
    return _success_result(operation, config.text_model, extract_response_text(response))


def openai_vision_json_response_from_base64(
    image_base64: str,
    prompt: str,
    *,
    operation: str = "vision_extraction",
    schema_name: str = "financial_vision_extraction",
    schema: Optional[Dict[str, Any]] = None,
    max_output_tokens: int = 4096,
    client: Any = None,
    config: Optional[OpenAIProviderConfig] = None,
) -> Dict[str, Any]:
    """Call OpenAI vision model against a rendered page image payload."""
    config = config or load_openai_config()
    if not image_base64:
        return {
            "ok": False,
            "provider": "openai",
            "operation": operation,
            "error_type": "missing_image",
            "error": "Image payload is empty.",
            "model": config.vision_model,
        }
    if not is_openai_configured(config):
        return configuration_error_result(operation, config)

    schema = schema or extraction_items_schema()

    try:
        client = client or create_openai_client(config)
        response = client.responses.create(
            model=config.vision_model,
            input=build_vision_input_from_base64(image_base64, prompt),
            text=_json_schema_format(schema_name, schema),
            max_output_tokens=max_output_tokens,
        )
    except OpenAIProviderConfigurationError as exc:
        return configuration_error_result(operation, config) | {"error": str(exc)}
    except Exception as exc:
        return provider_error_result(operation, config.vision_model, exc, config)
    return _success_result(operation, config.vision_model, extract_response_text(response))


async def async_openai_text_json_response(*args, **kwargs) -> Dict[str, Any]:
    return await asyncio.to_thread(openai_text_json_response, *args, **kwargs)


async def async_openai_vision_json_response_from_base64(*args, **kwargs) -> Dict[str, Any]:
    return await asyncio.to_thread(openai_vision_json_response_from_base64, *args, **kwargs)


def openai_vision_smoke(
    image_path: str,
    prompt: str,
    *,
    client: Any = None,
    config: Optional[OpenAIProviderConfig] = None,
) -> Dict[str, Any]:
    config = config or load_openai_config()
    path = Path(image_path)
    if not path.exists():
        return {
            "ok": False,
            "provider": "openai",
            "operation": "vision",
            "error_type": "missing_image",
            "error": f"Image smoke skipped; file does not exist: {image_path}",
            "model": config.vision_model,
        }

    if not is_openai_configured(config):
        return configuration_error_result("vision", config)

    try:
        client = client or create_openai_client(config)
        response = client.responses.create(
            model=config.vision_model,
            input=build_vision_input(str(path), prompt),
            max_output_tokens=220,
        )
    except OpenAIProviderConfigurationError as exc:
        return configuration_error_result("vision", config) | {"error": str(exc)}
    except Exception as exc:
        return provider_error_result("vision", config.vision_model, exc, config)
    return _success_result("vision", config.vision_model, extract_response_text(response))


def _embedding_items_from_response(response: Any) -> List[List[float]]:
    data = getattr(response, "data", None)
    if data is None and isinstance(response, dict):
        data = response.get("data")

    embeddings: List[List[float]] = []
    for item in data or []:
        embedding = getattr(item, "embedding", None)
        if embedding is None and isinstance(item, dict):
            embedding = item.get("embedding")
        if embedding is None:
            continue
        embeddings.append([float(value) for value in embedding])
    return embeddings


def _usage_from_response(response: Any) -> Optional[Dict[str, Any]]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return None
    if isinstance(usage, dict):
        return dict(usage)

    result = {}
    for key in ("prompt_tokens", "total_tokens"):
        value = getattr(usage, key, None)
        if value is not None:
            result[key] = value
    return result or None


def normalize_embedding_response(
    response: Any,
    *,
    model: str,
    provider: str = "openai",
) -> Dict[str, Any]:
    embeddings = _embedding_items_from_response(response)
    dimensions = [len(embedding) for embedding in embeddings]
    unique_dimensions = sorted(set(dimensions))

    return {
        "ok": bool(embeddings),
        "provider": provider,
        "operation": "embedding",
        "model": model,
        "dimensions": unique_dimensions[0] if len(unique_dimensions) == 1 else None,
        "dimension_values": unique_dimensions,
        "embedding_count": len(embeddings),
        "embeddings": embeddings,
        "usage": _usage_from_response(response),
    }


def openai_embeddings(
    inputs: Union[str, List[str]],
    *,
    client: Any = None,
    config: Optional[OpenAIProviderConfig] = None,
) -> Dict[str, Any]:
    config = config or load_openai_config()
    if not is_openai_configured(config):
        return configuration_error_result("embedding", config)

    input_list = [inputs] if isinstance(inputs, str) else list(inputs)
    if not input_list:
        return {
            "ok": False,
            "provider": "openai",
            "operation": "embedding",
            "error_type": "empty_input",
            "error": "At least one input string is required for OpenAI embeddings.",
            "model": config.embedding_model,
        }

    try:
        client = client or create_openai_client(config)
        response = client.embeddings.create(
            model=config.embedding_model,
            input=input_list,
        )
    except OpenAIProviderConfigurationError as exc:
        return configuration_error_result("embedding", config) | {"error": str(exc)}
    except Exception as exc:
        return provider_error_result("embedding", config.embedding_model, exc, config)

    return normalize_embedding_response(response, model=config.embedding_model)
