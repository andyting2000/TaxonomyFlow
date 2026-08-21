import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts.discover_embedding_sources import (
    build_parser,
    collect_source_discovery_report,
    render_text_report,
)
from scripts.generate_openai_embeddings import (
    mpers_template_json_source_records,
    template_service_source_records,
)
from services.xbrl_template_service import get_xbrl_template_service


class OpenAIEmbeddingSourceDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_template_service_exports_embedding_source_concepts(self):
        records = get_xbrl_template_service().get_embedding_source_concepts()

        self.assertGreater(len(records), 0)
        first = records[0]
        self.assertEqual(first["source_type"], "template_service_concept")
        self.assertIn(":", first["source_id"])
        self.assertIn("template_code", first)
        self.assertIn("concept_id", first)
        self.assertIn("concept_label", first)

    def test_template_service_source_records_have_stable_text(self):
        records = template_service_source_records()

        self.assertGreater(len(records), 0)
        first = records[0]
        self.assertEqual(first.source_type, "template_service_concept")
        self.assertIn("Statement:", first.source_text)
        self.assertIn("Concept label:", first.source_text)
        self.assertIn("Concept id:", first.source_text)
        self.assertEqual(first.source_text_hash, records[0].source_text_hash)

    def test_mpers_template_json_records_are_available(self):
        records = mpers_template_json_source_records()

        self.assertGreater(len(records), 0)
        self.assertEqual(records[0].source_type, "mpers_template_concept")
        self.assertIn("Template code:", records[0].source_text)

    async def test_source_discovery_report_is_read_only_and_recommends_service_source(self):
        db_summaries = [
            {
                "source_name": "mbrs_taxonomy_tags table",
                "source_type": "mbrs_taxonomy_tag",
                "record_count": 0,
                "sample_records": [],
                "currently_used_by_production": "empty",
                "has_stable_ids": True,
                "has_embedding_suitable_text": False,
                "embedding_suitability": "empty",
            },
            {
                "source_name": "xml_template_fields table",
                "source_type": "xml_template_field",
                "record_count": 0,
                "sample_records": [],
                "currently_used_by_production": "empty",
                "has_stable_ids": True,
                "has_embedding_suitable_text": False,
                "embedding_suitability": "empty",
            },
        ]

        with patch(
            "scripts.discover_embedding_sources._db_table_summary",
            new=AsyncMock(side_effect=db_summaries),
        ):
            report = await collect_source_discovery_report()

        self.assertEqual(report["mode"], "read_only")
        self.assertFalse(report["mutates_database"])
        self.assertEqual(
            report["recommended_source_for_openai_embeddings"],
            "template-service-concepts",
        )
        source_names = {source["source_name"] for source in report["sources"]}
        self.assertIn("mbrs_taxonomy_tags table", source_names)
        self.assertIn("xml_template_fields table", source_names)
        self.assertIn("XBRLTemplateService loaded concepts", source_names)

    async def test_render_text_report_includes_recommended_source(self):
        db_summaries = [
            {
                "source_name": "mbrs_taxonomy_tags table",
                "source_type": "mbrs_taxonomy_tag",
                "record_count": 0,
                "sample_records": [],
                "currently_used_by_production": "empty",
                "has_stable_ids": True,
                "has_embedding_suitable_text": False,
                "embedding_suitability": "empty",
            },
            {
                "source_name": "xml_template_fields table",
                "source_type": "xml_template_field",
                "record_count": 0,
                "sample_records": [],
                "currently_used_by_production": "empty",
                "has_stable_ids": True,
                "has_embedding_suitable_text": False,
                "embedding_suitability": "empty",
            },
        ]
        with patch(
            "scripts.discover_embedding_sources._db_table_summary",
            new=AsyncMock(side_effect=db_summaries),
        ):
            report = await collect_source_discovery_report()

        text = render_text_report(report)

        self.assertIn("Recommended source: template-service-concepts", text)
        self.assertIn("XBRLTemplateService loaded concepts", text)

    def test_source_discovery_parser_defaults(self):
        args = build_parser().parse_args([])

        self.assertEqual(Path(args.output), Path("reports/openai_embedding_source_discovery.json"))
        self.assertFalse(args.json)


if __name__ == "__main__":
    unittest.main()
