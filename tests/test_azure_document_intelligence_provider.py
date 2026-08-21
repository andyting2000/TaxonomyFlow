import tempfile
import unittest
from pathlib import Path

from services.azure_document_intelligence_provider import (
    AzureDocumentIntelligenceConfigError,
    AzureDocumentIntelligenceProvider,
    format_smoke_summary,
    normalize_azure_document_result,
)


def sample_result():
    return {
        "content": "Directors' Report\nCash 1,000",
        "pages": [
            {
                "page_number": 1,
                "lines": [{"content": "Directors' Report", "polygon": [1, 2, 3, 4]}],
                "words": [{"content": "Directors", "confidence": 0.99}],
            }
        ],
        "paragraphs": [{"content": "Directors' Report", "role": "sectionHeading", "bounding_regions": [{"page_number": 1}]}],
        "tables": [
            {
                "row_count": 1,
                "column_count": 2,
                "cells": [
                    {"content": "Cash", "row_index": 0, "column_index": 0, "bounding_regions": [{"page_number": 1}]},
                    {"content": "1,000", "row_index": 0, "column_index": 1, "bounding_regions": [{"page_number": 1}]},
                ],
            }
        ],
    }


class FakePoller:
    def __init__(self, result):
        self._result = result

    def result(self, timeout=None):
        self.timeout = timeout
        return self._result


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result = result or sample_result()
        self.error = error
        self.calls = []

    def begin_analyze_document(self, **kwargs):
        body = kwargs.get("body")
        payload = body.read()
        body.seek(0)
        self.calls.append({**kwargs, "body_bytes": payload})
        if self.error:
            raise self.error
        return FakePoller(self.result)


class AzureDocumentIntelligenceProviderTests(unittest.TestCase):
    def test_provider_reads_endpoint_key_model_without_exposing_key(self):
        provider = AzureDocumentIntelligenceProvider(
            endpoint="https://example.cognitiveservices.azure.com/",
            key="secret-key",
            model_id="prebuilt-layout",
        )
        self.assertEqual(provider.endpoint, "https://example.cognitiveservices.azure.com/")
        self.assertEqual(provider.model_id, "prebuilt-layout")
        self.assertNotIn("secret-key", repr(provider.__dict__.get("_client")))

    def test_missing_endpoint_or_key_produces_clear_configuration_error(self):
        provider = AzureDocumentIntelligenceProvider(endpoint="", key="", model_id="prebuilt-layout")
        with self.assertRaises(AzureDocumentIntelligenceConfigError):
            provider.validate_config()
        provider = AzureDocumentIntelligenceProvider(
            endpoint="https://example.cognitiveservices.azure.com/",
            key="replace-with-your-azure-document-intelligence-key",
        )
        with self.assertRaises(AzureDocumentIntelligenceConfigError):
            provider.validate_config()

    def test_mocked_azure_result_normalizes_pages_lines_tables_paragraphs(self):
        normalized = normalize_azure_document_result(
            sample_result(),
            model_id="prebuilt-layout",
            runtime_seconds=1.25,
            source_pdf="sample.pdf",
        )
        self.assertTrue(normalized["ok"])
        self.assertEqual(normalized["pages_count"], 1)
        self.assertEqual(len(normalized["lines"]), 1)
        self.assertEqual(len(normalized["tables"]), 1)
        self.assertEqual(len(normalized["table_cells"]), 2)
        self.assertEqual(len(normalized["paragraphs"]), 1)

    def test_azure_errors_are_captured_without_leaking_key(self):
        fake_client = FakeClient(error=RuntimeError("failed with secret-key"))
        provider = AzureDocumentIntelligenceProvider(
            endpoint="https://example.cognitiveservices.azure.com/",
            key="secret-key",
            client_factory=lambda **_kwargs: fake_client,
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(b"%PDF-1.4 fake")
            path = Path(handle.name)
        try:
            result = provider.analyze_pdf_path(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertFalse(result["ok"])
        self.assertNotIn("secret-key", result["errors"][0]["message"])
        self.assertIn("[redacted]", result["errors"][0]["message"])

    def test_smoke_formatter_renders_summary_and_first_table_preview(self):
        normalized = normalize_azure_document_result(sample_result(), model_id="prebuilt-layout", runtime_seconds=1.0)
        text = format_smoke_summary(normalized, first_lines=1, first_table_rows=1)
        self.assertIn("Model ID: prebuilt-layout", text)
        self.assertIn("Pages: 1", text)
        self.assertIn("First table: 1 rows, 2 columns", text)
        self.assertIn("| Cash | 1,000 |", text)

    def test_reference_xml_is_not_sent(self):
        fake_client = FakeClient()
        provider = AzureDocumentIntelligenceProvider(
            endpoint="https://example.cognitiveservices.azure.com/",
            key="secret-key",
            client_factory=lambda **_kwargs: fake_client,
        )
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            handle.write(b"%PDF-1.4 fake")
            path = Path(handle.name)
        try:
            result = provider.analyze_pdf_path(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertTrue(result["reference_xml_sent_to_provider"] is False)
        self.assertEqual(fake_client.calls[0]["content_type"], "application/pdf")
        self.assertNotIn(b"<xbrl", fake_client.calls[0]["body_bytes"].lower())


if __name__ == "__main__":
    unittest.main()
