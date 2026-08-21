import argparse
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from scripts.generate_huggingface_embeddings import (
    HuggingFaceEmbeddingConfig,
    huggingface_embeddings,
    normalize_embedding,
    run_generation,
)
from scripts.generate_openai_embeddings import EmbeddingSourceRecord, sha256_text
from scripts.inspect_embedding_store import render_text_report


class FakeHFClient:
    def __init__(self, vectors):
        self.vectors = list(vectors)
        self.calls = []

    async def feature_extraction(self, text):
        self.calls.append(text)
        return self.vectors.pop(0)


class HuggingFaceEmbeddingGenerationTests(unittest.IsolatedAsyncioTestCase):
    def test_normalize_embedding_flattens_token_embeddings(self):
        vector = normalize_embedding([[1.0, 0.0], [0.0, 1.0]], normalize=False)

        self.assertEqual(vector, [0.5, 0.5])

    async def test_huggingface_embeddings_uses_provider_and_model_without_secret(self):
        config = HuggingFaceEmbeddingConfig(token="hf-secret", model="Qwen/Qwen3-Embedding-8B", expected_dimension=2)
        client = FakeHFClient([[1.0, 2.0]])

        result = await huggingface_embeddings("cash", client=client, config=config)

        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "huggingface")
        self.assertEqual(result["model"], "Qwen/Qwen3-Embedding-8B")
        self.assertEqual(result["dimensions"], 2)
        self.assertNotIn("hf-secret", str(result))

    async def test_dry_run_does_not_mutate_db_or_call_model(self):
        record = EmbeddingSourceRecord(
            source_type="template_service_concept",
            source_id="210000:ssmt:CashAndBankBalances",
            source_label="Cash",
            source_text="Label: Cash",
            source_text_hash=sha256_text("Label: Cash"),
        )
        args = argparse.Namespace(
            source="template-service-concepts",
            limit=1,
            batch_size=20,
            sleep_between_batches=0.0,
            max_retries=0,
            force=False,
            apply=False,
            discover_dimension=False,
        )

        with patch(
            "scripts.generate_huggingface_embeddings.fetch_source_records",
            new=AsyncMock(return_value=[record]),
        ), patch(
            "scripts.generate_huggingface_embeddings.existing_embedding_keys",
            new=AsyncMock(return_value=set()),
        ), patch(
            "scripts.generate_huggingface_embeddings.huggingface_embeddings",
            new=AsyncMock(side_effect=AssertionError("HF should not be called in dry-run")),
        ), patch(
            "scripts.generate_huggingface_embeddings.upsert_embedding_record",
            new=AsyncMock(side_effect=AssertionError("DB should not mutate in dry-run")),
        ):
            report = await run_generation(args)

        self.assertEqual(report["mode"], "dry_run")
        self.assertFalse(report["mutates_database"])
        self.assertEqual(report["provider"], "huggingface")
        self.assertEqual(report["would_generate"], 1)
        self.assertFalse(report["legacy_columns_written"])

    async def test_apply_report_uses_huggingface_provider(self):
        record = EmbeddingSourceRecord(
            source_type="template_service_concept",
            source_id="210000:ssmt:CashAndBankBalances",
            source_label="Cash",
            source_text="Label: Cash",
            source_text_hash=sha256_text("Label: Cash"),
        )
        args = argparse.Namespace(
            source="template-service-concepts",
            limit=1,
            batch_size=20,
            sleep_between_batches=0.0,
            max_retries=0,
            force=False,
            apply=True,
            discover_dimension=False,
        )
        config = HuggingFaceEmbeddingConfig(token="hf-test", model="Qwen/Qwen3-Embedding-8B", expected_dimension=3)

        with patch(
            "scripts.generate_huggingface_embeddings.fetch_source_records",
            new=AsyncMock(return_value=[record]),
        ), patch(
            "scripts.generate_huggingface_embeddings.existing_embedding_keys",
            new=AsyncMock(return_value=set()),
        ), patch(
            "scripts.generate_huggingface_embeddings.load_huggingface_embedding_config",
            new=Mock(return_value=config),
        ), patch(
            "scripts.generate_huggingface_embeddings.huggingface_embeddings",
            new=AsyncMock(return_value={"ok": True, "embeddings": [[0.1, 0.2, 0.3]], "dimensions": 3}),
        ), patch(
            "scripts.generate_huggingface_embeddings.upsert_embedding_record",
            new=AsyncMock(return_value="inserted"),
        ) as upsert:
            report = await run_generation(args)

        self.assertEqual(report["provider"], "huggingface")
        self.assertEqual(report["model"], "Qwen/Qwen3-Embedding-8B")
        self.assertEqual(report["inserted"], 1)
        self.assertEqual(report["dimension_values"], [3])
        self.assertEqual(upsert.await_args.kwargs["provider"], "huggingface")

    def test_inspection_marks_openai_embeddings_inactive_legacy(self):
        text = render_text_report(
            {
                "configuration": {
                    "active_provider": "huggingface",
                    "model_provider": "huggingface",
                    "active_embedding_model": "Qwen/Qwen3-Embedding-8B",
                    "active_expected_dimension": 4096,
                    "openai_embedding_model": "text-embedding-3-large",
                    "live_hugging_face_embedding_calls_enabled": True,
                },
                "database_access": {"ok": True},
                "embedding_store": {"columns": [], "counts": []},
                "provider_versioned_embedding_store": {
                    "table": "semantic_embeddings",
                    "exists": True,
                    "columns": [],
                    "counts_by_provider_model_dimension_source_type": [],
                    "missing_counts_by_source_type": [],
                    "openai_embeddings_exist": True,
                },
                "code_findings": {
                    "production_semantic_matcher_behavior": "Hugging Face active",
                },
            }
        )

        self.assertIn("OpenAI embeddings: present, inactive/legacy", text)


if __name__ == "__main__":
    unittest.main()
