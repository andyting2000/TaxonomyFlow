import argparse
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from services.openai_provider import (
    OpenAIProviderConfig,
    normalize_embedding_response,
    openai_embeddings,
)
from scripts.generate_openai_embeddings import (
    EmbeddingSourceRecord,
    SOURCE_ALL,
    SOURCE_TEMPLATE_SERVICE_CONCEPTS,
    build_parser,
    embedding_hash,
    fetch_source_records,
    run_generation,
    sha256_text,
    source_record_from_template_concept,
    source_record_from_taxonomy_tag,
)


class FakeEmbeddings:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


class FakeOpenAIClient:
    def __init__(self, response):
        self.embeddings = FakeEmbeddings(response)


class OpenAIEmbeddingGenerationTests(unittest.IsolatedAsyncioTestCase):
    def test_embedding_response_normalization_extracts_dimension(self):
        response = SimpleNamespace(
            data=[
                SimpleNamespace(embedding=[0.1, 0.2, 0.3]),
                SimpleNamespace(embedding=[0.4, 0.5, 0.6]),
            ],
            usage=SimpleNamespace(prompt_tokens=4, total_tokens=4),
        )

        result = normalize_embedding_response(response, model="text-embedding-test")

        self.assertTrue(result["ok"])
        self.assertEqual(result["dimensions"], 3)
        self.assertEqual(result["embedding_count"], 2)
        self.assertEqual(result["usage"]["total_tokens"], 4)

    def test_openai_embeddings_missing_key_is_clear(self):
        result = openai_embeddings(
            "hello",
            config=OpenAIProviderConfig(
                api_key="",
                text_model="gpt-test",
                vision_model="gpt-test",
                embedding_model="text-embedding-test",
            ),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "configuration")
        self.assertEqual(result["model"], "text-embedding-test")

    def test_openai_embeddings_builds_sdk_request(self):
        response = SimpleNamespace(data=[SimpleNamespace(embedding=[1.0, 2.0])])
        client = FakeOpenAIClient(response)
        config = OpenAIProviderConfig(
            api_key="sk-secret",
            text_model="gpt-test",
            vision_model="gpt-test",
            embedding_model="text-embedding-test",
        )

        result = openai_embeddings(["a", "b"], client=client, config=config)

        self.assertTrue(result["ok"])
        self.assertEqual(client.embeddings.calls[0]["model"], "text-embedding-test")
        self.assertEqual(client.embeddings.calls[0]["input"], ["a", "b"])
        self.assertNotIn("sk-secret", str(result))

    def test_hashes_are_stable(self):
        self.assertEqual(sha256_text("abc"), sha256_text("abc"))
        self.assertNotEqual(sha256_text("abc"), sha256_text("abcd"))
        self.assertEqual(embedding_hash([1.0, 2.0]), embedding_hash([1, 2]))

    def test_source_text_includes_taxonomy_fields(self):
        tag = SimpleNamespace(
            id=7,
            label="Cash and bank balances",
            xbrl_tag="mfrs:CashAndBankBalances",
            namespace="mfrs",
            period_type="instant",
        )

        record = source_record_from_taxonomy_tag(tag)

        self.assertEqual(record.source_type, "mbrs_taxonomy_tag")
        self.assertEqual(record.source_id, "7")
        self.assertIn("Cash and bank balances", record.source_text)
        self.assertIn("mfrs:CashAndBankBalances", record.source_text)

    def test_source_text_includes_template_service_concept_fields(self):
        record = source_record_from_template_concept(
            {
                "source_id": "210000:ssmt:CashAndBankBalances",
                "template_code": "210000",
                "statement_description": "Statement of Financial Position",
                "concept_id": "ssmt:CashAndBankBalances",
                "concept_label": "Cash and bank balances",
                "namespace": "ssmt",
                "level": 3,
                "parent": "ssmt:AssetsAbstract",
                "required": False,
                "position": 10,
                "aliases": ["cash at bank"],
            }
        )

        self.assertEqual(record.source_type, "template_service_concept")
        self.assertEqual(record.source_id, "210000:ssmt:CashAndBankBalances")
        self.assertIn("Statement of Financial Position", record.source_text)
        self.assertIn("Cash and bank balances", record.source_text)
        self.assertIn("cash at bank", record.source_text)

    def test_parser_defaults_to_dry_run(self):
        args = build_parser().parse_args([])

        self.assertEqual(args.source, SOURCE_ALL)
        self.assertFalse(args.apply)
        self.assertFalse(args.force)

    async def test_template_service_source_fetch_returns_nonzero_records(self):
        records = await fetch_source_records(SOURCE_TEMPLATE_SERVICE_CONCEPTS, limit=5)

        self.assertGreater(len(records), 0)
        self.assertLessEqual(len(records), 5)
        self.assertTrue(all(record.source_type == "template_service_concept" for record in records))

    async def test_template_service_dry_run_does_not_call_openai(self):
        args = build_parser().parse_args(
            ["--source", "template-service-concepts", "--limit", "3"]
        )

        with patch(
            "scripts.generate_openai_embeddings.existing_embedding_keys",
            new=AsyncMock(return_value=set()),
        ), patch(
            "scripts.generate_openai_embeddings.openai_embeddings",
            new=Mock(side_effect=AssertionError("OpenAI should not be called in dry-run")),
        ):
            report = await run_generation(args)

        self.assertEqual(report["mode"], "dry_run")
        self.assertGreater(report["source_records"], 0)
        self.assertIn("failed", report)
        self.assertIn("dimension_values", report)
        self.assertEqual(
            report["source_records_by_type"],
            {"template_service_concept": report["source_records"]},
        )

    async def test_dry_run_does_not_call_openai(self):
        record = EmbeddingSourceRecord(
            source_type="mbrs_taxonomy_tag",
            source_id="1",
            source_label="Cash",
            source_text="Label: Cash",
            source_text_hash=sha256_text("Label: Cash"),
        )
        args = build_parser().parse_args(["--source", "all", "--limit", "5"])

        with patch(
            "scripts.generate_openai_embeddings.fetch_source_records",
            new=AsyncMock(return_value=[record]),
        ), patch(
            "scripts.generate_openai_embeddings.existing_embedding_keys",
            new=AsyncMock(return_value=set()),
        ), patch(
            "scripts.generate_openai_embeddings.openai_embeddings",
            new=Mock(side_effect=AssertionError("OpenAI should not be called in dry-run")),
        ):
            report = await run_generation(args)

        self.assertEqual(report["mode"], "dry_run")
        self.assertFalse(report["mutates_database"])
        self.assertEqual(report["would_generate"], 1)

    async def test_existing_embeddings_are_skipped_without_force(self):
        record = EmbeddingSourceRecord(
            source_type="template_service_concept",
            source_id="210000:ssmt:CashAndBankBalances",
            source_label="Cash",
            source_text="Label: Cash",
            source_text_hash=sha256_text("Label: Cash"),
        )
        args = build_parser().parse_args(["--source", "template-service-concepts", "--apply"])
        config = OpenAIProviderConfig(
            api_key="sk-test",
            text_model="gpt-test",
            vision_model="gpt-test",
            embedding_model="text-embedding-test",
        )

        with patch(
            "scripts.generate_openai_embeddings.fetch_source_records",
            new=AsyncMock(return_value=[record]),
        ), patch(
            "scripts.generate_openai_embeddings.existing_embedding_keys",
            new=AsyncMock(return_value={(record.source_type, record.source_id, record.source_text_hash)}),
        ), patch(
            "scripts.generate_openai_embeddings.load_openai_config",
            new=Mock(return_value=config),
        ), patch(
            "scripts.generate_openai_embeddings.openai_embeddings",
            new=Mock(side_effect=AssertionError("Existing embeddings should be skipped")),
        ):
            report = await run_generation(args)

        self.assertEqual(report["would_generate"], 0)
        self.assertEqual(report["skipped_existing"], 1)
        self.assertEqual(report["generated"], 0)
        self.assertEqual(report["failed"], 0)

    async def test_apply_reports_failed_batch_source_ids(self):
        record = EmbeddingSourceRecord(
            source_type="template_service_concept",
            source_id="210000:ssmt:CashAndBankBalances",
            source_label="Cash",
            source_text="Label: Cash",
            source_text_hash=sha256_text("Label: Cash"),
        )
        args = build_parser().parse_args(
            ["--source", "template-service-concepts", "--apply", "--max-retries", "0"]
        )
        config = OpenAIProviderConfig(
            api_key="sk-test",
            text_model="gpt-test",
            vision_model="gpt-test",
            embedding_model="text-embedding-test",
        )

        with patch(
            "scripts.generate_openai_embeddings.fetch_source_records",
            new=AsyncMock(return_value=[record]),
        ), patch(
            "scripts.generate_openai_embeddings.existing_embedding_keys",
            new=AsyncMock(return_value=set()),
        ), patch(
            "scripts.generate_openai_embeddings.load_openai_config",
            new=Mock(return_value=config),
        ), patch(
            "scripts.generate_openai_embeddings.openai_embeddings",
            new=Mock(
                return_value={
                    "ok": False,
                    "error_type": "RateLimitError",
                    "error": "rate limited",
                    "model": "text-embedding-test",
                }
            ),
        ):
            report = await run_generation(args)

        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["failed_source_ids"], [record.source_id])
        self.assertEqual(report["failed_batches"], 1)
        self.assertEqual(report["inserted"], 0)
        self.assertEqual(report["errors"][0]["error_type"], "RateLimitError")

    async def test_apply_records_generated_dimension_values(self):
        record = EmbeddingSourceRecord(
            source_type="template_service_concept",
            source_id="210000:ssmt:CashAndBankBalances",
            source_label="Cash",
            source_text="Label: Cash",
            source_text_hash=sha256_text("Label: Cash"),
        )
        args = build_parser().parse_args(["--source", "template-service-concepts", "--apply"])
        config = OpenAIProviderConfig(
            api_key="sk-test",
            text_model="gpt-test",
            vision_model="gpt-test",
            embedding_model="text-embedding-test",
        )

        with patch(
            "scripts.generate_openai_embeddings.fetch_source_records",
            new=AsyncMock(return_value=[record]),
        ), patch(
            "scripts.generate_openai_embeddings.existing_embedding_keys",
            new=AsyncMock(return_value=set()),
        ), patch(
            "scripts.generate_openai_embeddings.load_openai_config",
            new=Mock(return_value=config),
        ), patch(
            "scripts.generate_openai_embeddings.openai_embeddings",
            new=Mock(
                return_value={
                    "ok": True,
                    "embeddings": [[0.1, 0.2, 0.3]],
                    "dimensions": 3,
                    "model": "text-embedding-test",
                }
            ),
        ), patch(
            "scripts.generate_openai_embeddings.upsert_embedding_record",
            new=AsyncMock(return_value="inserted"),
        ):
            report = await run_generation(args)

        self.assertEqual(report["inserted"], 1)
        self.assertEqual(report["generated"], 1)
        self.assertEqual(report["dimension_values"], [3])
        self.assertEqual(report["failed"], 0)

    async def test_apply_requires_configured_openai_key_before_mutation(self):
        record = EmbeddingSourceRecord(
            source_type="mbrs_taxonomy_tag",
            source_id="1",
            source_label="Cash",
            source_text="Label: Cash",
            source_text_hash=sha256_text("Label: Cash"),
        )
        args = build_parser().parse_args(["--source", "all", "--apply"])
        config = OpenAIProviderConfig(
            api_key="",
            text_model="gpt-test",
            vision_model="gpt-test",
            embedding_model="text-embedding-test",
        )

        with patch(
            "scripts.generate_openai_embeddings.fetch_source_records",
            new=AsyncMock(return_value=[record]),
        ), patch(
            "scripts.generate_openai_embeddings.existing_embedding_keys",
            new=AsyncMock(return_value=set()),
        ), patch(
            "scripts.generate_openai_embeddings.load_openai_config",
            new=Mock(return_value=config),
        ), patch(
            "scripts.generate_openai_embeddings.openai_embeddings",
            new=Mock(side_effect=AssertionError("OpenAI should not be called without key")),
        ):
            report = await run_generation(args)

        self.assertEqual(report["mode"], "apply")
        self.assertTrue(report["errors"])
        self.assertIn("OPENAI_API_KEY", report["errors"][0]["error"])
        self.assertEqual(report["generated"], 0)

    def test_apply_flag_is_explicit(self):
        parser = build_parser()
        option_dests = [action.dest for action in parser._actions]

        self.assertIn("apply", option_dests)
        self.assertFalse(parser.parse_args([]).apply)
        self.assertTrue(parser.parse_args(["--apply"]).apply)


if __name__ == "__main__":
    unittest.main()
