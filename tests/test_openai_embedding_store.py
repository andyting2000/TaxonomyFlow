import unittest
from pathlib import Path

from database import SemanticEmbedding
from scripts.inspect_embedding_store import parse_vector_dimension


class OpenAIEmbeddingStoreTests(unittest.TestCase):
    def test_migration_creates_provider_versioned_table(self):
        migration = Path("migrations/003_add_semantic_embeddings.sql").read_text(
            encoding="utf-8"
        )

        self.assertIn("CREATE TABLE IF NOT EXISTS semantic_embeddings", migration)
        self.assertIn("provider VARCHAR(50) NOT NULL", migration)
        self.assertIn("model VARCHAR(200) NOT NULL", migration)
        self.assertIn("dimension INTEGER NOT NULL", migration)
        self.assertIn("embedding vector NOT NULL", migration)
        self.assertIn("source_text_hash VARCHAR(64) NOT NULL", migration)
        self.assertIn(
            "UNIQUE (provider, model, source_type, source_id, source_text_hash)",
            migration,
        )

    def test_migration_does_not_touch_legacy_vector_columns(self):
        migration = Path("migrations/003_add_semantic_embeddings.sql").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("ALTER TABLE mbrs_taxonomy_tags", migration)
        self.assertNotIn("ALTER TABLE xml_template_fields", migration)
        self.assertNotIn("embedding vector(1752)", migration)

    def test_orm_model_targets_shadow_table(self):
        self.assertEqual(SemanticEmbedding.__tablename__, "semantic_embeddings")
        column_names = {column.name for column in SemanticEmbedding.__table__.columns}

        for required in {
            "source_type",
            "source_id",
            "source_text",
            "provider",
            "model",
            "dimension",
            "embedding",
            "source_text_hash",
        }:
            self.assertIn(required, column_names)

    def test_db_init_registers_semantic_embeddings(self):
        db_init_source = Path("db_init.py").read_text(encoding="utf-8")

        self.assertIn('"semantic_embeddings"', db_init_source)
        self.assertIn("Run all idempotent migrations", db_init_source)

    def test_unconstrained_vector_dimension_parser(self):
        self.assertIsNone(parse_vector_dimension("vector"))
        self.assertEqual(parse_vector_dimension("vector(1752)"), 1752)

    def test_production_semantic_matcher_uses_huggingface_not_openai_embeddings(self):
        matcher_source = Path("services/semantic_matcher.py").read_text(encoding="utf-8")

        self.assertIn("settings.embedding_model_id", matcher_source)
        self.assertNotIn("openai_embeddings(", matcher_source)


if __name__ == "__main__":
    unittest.main()
