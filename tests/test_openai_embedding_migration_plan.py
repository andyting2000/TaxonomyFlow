import unittest
from types import SimpleNamespace

from scripts.inspect_embedding_store import (
    parse_vector_dimension,
    render_text_report,
    summarize_configuration,
)
from scripts.plan_openai_embedding_migration import (
    build_migration_plan,
    build_parser,
)


def sample_inspection_report(database_ok=True):
    return {
        "mode": "read_only",
        "mutates_database": False,
        "configuration": {
            "model_provider": "openai",
            "openai_embedding_model": "text-embedding-test",
            "legacy_hugging_face_embedding_model": "Qwen/Qwen3-Embedding-8B",
            "legacy_hugging_face_embedding_dimension": 1752,
            "live_hugging_face_embedding_calls_enabled": False,
            "openai_mode_embedding_behavior": (
                "live_hugging_face_embeddings_disabled; string/template matching only"
            ),
        },
        "database_access": {
            "ok": database_ok,
            "error": None if database_ok else "connection unavailable",
            "error_type": None if database_ok else "OperationalError",
        },
        "embedding_store": {
            "tables": ["xml_template_fields", "mbrs_taxonomy_tags"],
            "columns": [
                {
                    "table_name": "mbrs_taxonomy_tags",
                    "column_name": "embedding",
                    "data_type": "vector(1752)",
                    "vector_dimension": 1752,
                    "type_modifier": 1756,
                },
                {
                    "table_name": "xml_template_fields",
                    "column_name": "embedding",
                    "data_type": "vector(1752)",
                    "vector_dimension": 1752,
                    "type_modifier": 1756,
                },
            ],
            "counts": [
                {
                    "table_name": "mbrs_taxonomy_tags",
                    "total_rows": 10,
                    "rows_with_embedding": 8,
                    "rows_missing_embedding": 2,
                }
            ],
        },
    }


class OpenAIEmbeddingMigrationPlanTests(unittest.TestCase):
    def test_parse_vector_dimension(self):
        self.assertEqual(parse_vector_dimension("vector(1752)"), 1752)
        self.assertIsNone(parse_vector_dimension("text"))

    def test_configuration_summary_has_no_secret_fields(self):
        settings = SimpleNamespace(
            model_provider="openai",
            openai_embedding_model="text-embedding-test",
            openai_api_key="sk-secret-value",
        )

        summary = summarize_configuration(settings)

        self.assertEqual(summary["model_provider"], "openai")
        self.assertEqual(summary["openai_embedding_model"], "text-embedding-test")
        self.assertTrue(summary["live_hugging_face_embedding_calls_enabled"])
        self.assertNotIn("sk-secret-value", str(summary))
        self.assertNotIn("openai_api_key", summary)

    def test_plan_report_contains_required_sections_and_rollback(self):
        report = build_migration_plan(sample_inspection_report())

        for key in [
            "current_state",
            "hf_legacy_embedding_dimension",
            "openai_embedding_model_configured",
            "schema_change_required",
            "recommended_strategy",
            "rollback_strategy",
            "data_migration_steps",
            "quality_comparison_plan",
            "implementation_slices",
        ]:
            self.assertIn(key, report)

        self.assertEqual(report["mode"], "planning_only")
        self.assertFalse(report["mutates_database"])
        self.assertIn("rollback", " ".join(report["rollback_strategy"]).lower())

    def test_unknown_target_dimension_keeps_schema_requirement_unknown(self):
        report = build_migration_plan(sample_inspection_report(), target_dimension=None)

        self.assertEqual(report["target_dimension"], None)
        self.assertEqual(report["existing_column_dimension_compatibility"], "unknown")
        self.assertTrue(report["schema_change_required"])
        self.assertIn("unknown", report["target_dimension_basis"])

    def test_provider_versioned_table_is_recommended(self):
        report = build_migration_plan(sample_inspection_report(), target_dimension=1536)

        self.assertTrue(report["schema_change_required"])
        self.assertEqual(
            report["recommended_strategy"]["name"],
            "provider_versioned_embedding_table",
        )
        strategy_names = [item["strategy"] for item in report["strategy_evaluation"]]
        self.assertIn("rebuild_existing_vector_column_in_place", strategy_names)

    def test_missing_database_access_is_represented_gracefully(self):
        report = build_migration_plan(sample_inspection_report(database_ok=False))

        self.assertFalse(report["current_state"]["database_access"]["ok"])
        self.assertEqual(
            report["current_state"]["database_access"]["error_type"],
            "OperationalError",
        )

    def test_no_mutating_apply_argument_exists(self):
        parser = build_parser()
        options = [action.dest for action in parser._actions]

        self.assertNotIn("apply", options)
        args = parser.parse_args([])
        self.assertFalse(hasattr(args, "apply"))

    def test_render_text_report_for_db_failure(self):
        report = sample_inspection_report(database_ok=False)

        text_report = render_text_report(report)

        self.assertIn("Mode: read-only", text_report)
        self.assertIn("Database access: unavailable", text_report)


if __name__ == "__main__":
    unittest.main()
