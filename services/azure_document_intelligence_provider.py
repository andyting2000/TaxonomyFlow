"""Read-only Azure Document Intelligence provider wrapper for benchmark spikes."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable


PLACEHOLDER_KEYS = {
    "",
    "replace-with-your-azure-document-intelligence-key",
    "YOUR_AZURE_DOCUMENT_INTELLIGENCE_KEY",
}


class AzureDocumentIntelligenceConfigError(RuntimeError):
    """Raised when Azure Document Intelligence spike configuration is incomplete."""


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _to_plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_plain(item) for key, item in value.items()}
    if hasattr(value, "as_dict"):
        try:
            return _to_plain(value.as_dict())
        except Exception:
            pass
    if hasattr(value, "to_dict"):
        try:
            return _to_plain(value.to_dict())
        except Exception:
            pass
    return str(value)


def _bounding_regions(value: Any) -> list[dict[str, Any]]:
    regions = _get_attr(value, "bounding_regions", []) or []
    rows: list[dict[str, Any]] = []
    for region in regions:
        rows.append(
            {
                "page_number": _get_attr(region, "page_number"),
                "polygon": _to_plain(_get_attr(region, "polygon", [])),
            }
        )
    return rows


def _spans(value: Any) -> list[dict[str, Any]]:
    spans = _get_attr(value, "spans", []) or []
    return [
        {
            "offset": _get_attr(span, "offset"),
            "length": _get_attr(span, "length"),
        }
        for span in spans
    ]


def _normalize_line(line: Any, page_number: int | None) -> dict[str, Any]:
    return {
        "content": _get_attr(line, "content", ""),
        "page_number": page_number,
        "polygon": _to_plain(_get_attr(line, "polygon", [])),
        "spans": _spans(line),
    }


def _normalize_word(word: Any, page_number: int | None) -> dict[str, Any]:
    return {
        "content": _get_attr(word, "content", ""),
        "page_number": page_number,
        "confidence": _get_attr(word, "confidence"),
        "polygon": _to_plain(_get_attr(word, "polygon", [])),
        "span": _to_plain(_get_attr(word, "span")),
    }


def _normalize_page(page: Any) -> dict[str, Any]:
    page_number = _get_attr(page, "page_number")
    return {
        "page_number": page_number,
        "width": _get_attr(page, "width"),
        "height": _get_attr(page, "height"),
        "unit": _get_attr(page, "unit"),
        "angle": _get_attr(page, "angle"),
        "lines": [_normalize_line(line, page_number) for line in (_get_attr(page, "lines", []) or [])],
        "words": [_normalize_word(word, page_number) for word in (_get_attr(page, "words", []) or [])],
        "spans": _spans(page),
    }


def _normalize_paragraph(paragraph: Any, index: int) -> dict[str, Any]:
    regions = _bounding_regions(paragraph)
    return {
        "paragraph_index": index,
        "content": _get_attr(paragraph, "content", ""),
        "role": _get_attr(paragraph, "role"),
        "page_number": regions[0].get("page_number") if regions else None,
        "bounding_regions": regions,
        "spans": _spans(paragraph),
    }


def _normalize_cell(cell: Any) -> dict[str, Any]:
    regions = _bounding_regions(cell)
    return {
        "content": _get_attr(cell, "content", ""),
        "kind": _get_attr(cell, "kind"),
        "row_index": _get_attr(cell, "row_index"),
        "column_index": _get_attr(cell, "column_index"),
        "row_span": _get_attr(cell, "row_span", 1),
        "column_span": _get_attr(cell, "column_span", 1),
        "page_number": regions[0].get("page_number") if regions else None,
        "bounding_regions": regions,
        "spans": _spans(cell),
    }


def _normalize_table(table: Any, index: int) -> dict[str, Any]:
    cells = [_normalize_cell(cell) for cell in (_get_attr(table, "cells", []) or [])]
    page_numbers = sorted({cell.get("page_number") for cell in cells if cell.get("page_number")})
    return {
        "table_index": index,
        "row_count": _get_attr(table, "row_count", 0),
        "column_count": _get_attr(table, "column_count", 0),
        "page_numbers": page_numbers,
        "cells": cells,
        "bounding_regions": _bounding_regions(table),
        "spans": _spans(table),
    }


def normalize_azure_document_result(
    result: Any,
    *,
    model_id: str,
    runtime_seconds: float,
    source_pdf: str | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    pages = [_normalize_page(page) for page in (_get_attr(result, "pages", []) or [])]
    paragraphs = [
        _normalize_paragraph(paragraph, index)
        for index, paragraph in enumerate(_get_attr(result, "paragraphs", []) or [])
    ]
    tables = [
        _normalize_table(table, index)
        for index, table in enumerate(_get_attr(result, "tables", []) or [])
    ]
    content = _get_attr(result, "content", "") or ""
    return {
        "ok": True,
        "provider": "azure_document_intelligence",
        "model_id": model_id,
        "source_pdf": source_pdf,
        "runtime_seconds": round(float(runtime_seconds), 3),
        "pages_count": len(pages),
        "content_length": len(content),
        "content": content,
        "pages": pages,
        "lines": [line for page in pages for line in page.get("lines", [])],
        "words": [word for page in pages for word in page.get("words", [])],
        "paragraphs": paragraphs,
        "tables": tables,
        "table_cells": [cell for table in tables for cell in table.get("cells", [])],
        "warnings": warnings or [],
        "errors": [],
        "reference_xml_sent_to_provider": False,
    }


def redact_secret(text: Any, secret: str | None) -> str:
    value = str(text)
    if secret:
        value = value.replace(secret, "[redacted]")
    return value


class AzureDocumentIntelligenceProvider:
    def __init__(
        self,
        *,
        endpoint: str | None = None,
        key: str | None = None,
        model_id: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        default_pages: str | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        if endpoint is None or key is None or model_id is None or timeout_seconds is None or max_retries is None or default_pages is None:
            from config import settings

            endpoint = endpoint if endpoint is not None else settings.azure_document_intelligence_endpoint
            key = key if key is not None else settings.azure_document_intelligence_key
            model_id = model_id if model_id is not None else settings.azure_document_intelligence_model_id
            timeout_seconds = (
                timeout_seconds
                if timeout_seconds is not None
                else settings.azure_document_intelligence_timeout_seconds
            )
            max_retries = (
                max_retries
                if max_retries is not None
                else settings.azure_document_intelligence_max_retries
            )
            default_pages = default_pages if default_pages is not None else settings.azure_document_intelligence_pages

        self.endpoint = str(endpoint or "").strip()
        self.key = str(key or "").strip()
        self.model_id = str(model_id or "prebuilt-layout").strip()
        self.timeout_seconds = int(timeout_seconds or 180)
        self.max_retries = int(max_retries if max_retries is not None else 2)
        self.default_pages = str(default_pages or "").strip() or None
        self._client_factory = client_factory
        self._client = None

    def validate_config(self) -> None:
        if not self.endpoint:
            raise AzureDocumentIntelligenceConfigError("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT is not configured.")
        if self.key in PLACEHOLDER_KEYS:
            raise AzureDocumentIntelligenceConfigError("AZURE_DOCUMENT_INTELLIGENCE_KEY is not configured.")

    def client(self) -> Any:
        self.validate_config()
        if self._client is not None:
            return self._client
        if self._client_factory is not None:
            self._client = self._client_factory(
                endpoint=self.endpoint,
                key=self.key,
                max_retries=self.max_retries,
            )
            return self._client
        from azure.ai.documentintelligence import DocumentIntelligenceClient
        from azure.core.credentials import AzureKeyCredential

        self._client = DocumentIntelligenceClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.key),
            retry_total=self.max_retries,
        )
        return self._client

    def analyze_pdf_path(self, pdf_path: str | Path, pages: str | None = None) -> dict[str, Any]:
        self.validate_config()
        path = Path(pdf_path)
        if path.suffix.lower() != ".pdf":
            raise ValueError("Azure Document Intelligence spike accepts PDF input only.")
        selected_pages = pages if pages is not None else self.default_pages
        started = time.monotonic()
        try:
            with path.open("rb") as pdf_file:
                kwargs: dict[str, Any] = {
                    "model_id": self.model_id,
                    "body": pdf_file,
                    "content_type": "application/pdf",
                }
                if selected_pages:
                    kwargs["pages"] = selected_pages
                poller = self.client().begin_analyze_document(**kwargs)
                result = poller.result(timeout=self.timeout_seconds)
            return normalize_azure_document_result(
                result,
                model_id=self.model_id,
                runtime_seconds=time.monotonic() - started,
                source_pdf=str(path),
            )
        except Exception as exc:
            return {
                "ok": False,
                "provider": "azure_document_intelligence",
                "model_id": self.model_id,
                "source_pdf": str(path),
                "runtime_seconds": round(time.monotonic() - started, 3),
                "pages_count": 0,
                "content_length": 0,
                "content": "",
                "pages": [],
                "lines": [],
                "words": [],
                "paragraphs": [],
                "tables": [],
                "table_cells": [],
                "warnings": [],
                "errors": [
                    {
                        "error_type": type(exc).__name__,
                        "message": redact_secret(exc, self.key),
                    }
                ],
                "reference_xml_sent_to_provider": False,
            }


def format_smoke_summary(result: dict[str, Any], *, first_lines: int = 8, first_table_rows: int = 5) -> str:
    lines = [
        f"Model ID: {result.get('model_id')}",
        f"Pages: {result.get('pages_count', 0)}",
        f"Tables: {len(result.get('tables') or [])}",
        f"Characters: {result.get('content_length', 0)}",
        f"Runtime seconds: {result.get('runtime_seconds')}",
    ]
    if result.get("errors"):
        lines.append(f"Errors: {result.get('errors')}")
    lines.extend(["", "First lines:"])
    for line in (result.get("lines") or [])[:first_lines]:
        lines.append(f"- p{line.get('page_number')}: {line.get('content')}")
    tables = result.get("tables") or []
    if tables:
        table = tables[0]
        lines.extend(
            [
                "",
                f"First table: {table.get('row_count', 0)} rows, {table.get('column_count', 0)} columns",
            ]
        )
        grouped: dict[int, dict[int, str]] = {}
        for cell in table.get("cells") or []:
            row = int(cell.get("row_index") or 0)
            col = int(cell.get("column_index") or 0)
            grouped.setdefault(row, {})[col] = str(cell.get("content") or "")
        for row_index in sorted(grouped)[:first_table_rows]:
            row = grouped[row_index]
            values = [row.get(col, "") for col in range(int(table.get("column_count") or 0))]
            lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)
