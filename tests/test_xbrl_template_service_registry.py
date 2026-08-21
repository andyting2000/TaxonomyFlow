import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path

from routers.xbrl_templates import (
    get_template,
    get_template_group_registry,
    list_templates,
)
from services.xbrl_template_service import (
    XBRLTemplateService,
    get_xbrl_template_service,
)


ROOT = Path(__file__).resolve().parents[1]


class XBRLTemplateServiceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = get_xbrl_template_service()

    def test_default_runtime_service_consumes_validated_registry(self):
        self.assertTrue(self.service.uses_canonical_registry)
        self.assertEqual(len(self.service.get_template_codes()), 24)
        metadata = self.service.get_registry_metadata()
        self.assertEqual(
            metadata["registry_id"],
            "template_group_registry_mpers_2022_v1",
        )
        self.assertEqual(metadata["source_taxonomy_version"], "SSMxT_2022v1.0")
        self.assertEqual(len(metadata["semantic_inventory_sha256"]), 64)

    def test_runtime_exposes_official_display_and_legacy_metadata_separately(self):
        notes = self.service.get_template("730000")
        capital = self.service.get_template("740000")
        related = self.service.get_template("750000")

        self.assertEqual(notes["description"], "Notes - List of Notes")
        self.assertEqual(notes["canonical_name"], "Notes - List of notes")
        self.assertEqual(
            notes["legacy_description"],
            "Notes to Financial Statements",
        )
        self.assertEqual(capital["description"], "Issued Capital Note")
        self.assertEqual(
            capital["official_role_definition"],
            "[740000] Notes - Issued capital",
        )
        self.assertIn("Notes - Information on Companies", capital["aliases"])
        self.assertEqual(
            related["description"],
            "Related Party Transactions",
        )
        self.assertEqual(
            related["official_role_definition"],
            "[750000] Notes - Related party transactions",
        )
        self.assertIn("Notes - Reports", related["aliases"])

    def test_registry_overlay_does_not_mutate_concepts_or_template_field_values(self):
        runtime = json.loads(
            (ROOT / "mpers_templates.json").read_text(encoding="utf-8")
        )
        for code, raw_template in runtime["templates"].items():
            with self.subTest(code=code):
                self.assertEqual(
                    self.service.get_template(code)["concepts"],
                    raw_template["concepts"],
                )
                fields = self.service.get_template_for_data_entry(code)
                self.assertTrue(all(field["value"] is None for field in fields))

    def test_durable_code_and_role_uri_identity_remains_unchanged(self):
        runtime = json.loads(
            (ROOT / "mpers_templates.json").read_text(encoding="utf-8")
        )
        for code, raw_template in runtime["templates"].items():
            with self.subTest(code=code):
                template = self.service.get_template(code)
                self.assertEqual(template["code"], code)
                self.assertEqual(
                    template["role_uri"],
                    raw_template["role_uri"],
                )

    def test_structural_notes_container_is_not_a_template(self):
        nodes = self.service.get_structural_navigation_nodes()
        self.assertEqual(nodes[0]["id"], "notes_container")
        self.assertIsNone(self.service.get_template("notes_container"))
        self.assertNotIn("notes_container", self.service.get_template_codes())

    def test_legacy_name_resolution_is_grouping_only_and_non_mutating(self):
        original = copy.deepcopy(self.service.get_template("740000"))
        self.assertEqual(
            self.service.resolve_legacy_template_label(
                "Notes - Information on Companies"
            ),
            "740000",
        )
        self.assertEqual(self.service.get_template("740000"), original)

    def test_custom_fixture_service_remains_available_for_focused_guardrail_tests(self):
        payload = {
            "_metadata": {},
            "templates": {
                "999999": {
                    "code": "999999",
                    "description": "Test Template",
                    "role_uri": "urn:test",
                    "concepts": [],
                    "required_concepts": [],
                    "total_concepts": 0,
                    "required_count": 0,
                }
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "fixture_templates.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            service = XBRLTemplateService(str(path))
        self.assertFalse(service.uses_canonical_registry)
        self.assertEqual(service.get_template_codes(), ["999999"])
        self.assertEqual(service.get_template_description("999999"), "Test Template")

    def test_template_api_exposes_additive_registry_metadata(self):
        summaries = asyncio.run(list_templates())
        detail = asyncio.run(get_template("740000"))
        registry = asyncio.run(get_template_group_registry())

        self.assertEqual(len(summaries), 24)
        capital = next(item for item in summaries if item.code == "740000")
        self.assertEqual(capital.description, "Issued Capital Note")
        self.assertEqual(capital.canonical_name, "Notes - Issued capital")
        self.assertIn("Notes - Information on Companies", capital.aliases)
        self.assertEqual(detail.role_id, "ssmt-fs-mpers_2022-12-31_role-740000")
        self.assertEqual(detail.template_kind, "note_disclosure")
        self.assertEqual(registry["actual_template_count"], 24)
        self.assertEqual(
            registry["structural_navigation_nodes"][0]["id"],
            "notes_container",
        )

    def test_review_workspace_uses_aliases_for_historical_statement_type_grouping(self):
        source = (
            ROOT / "frontend" / "src" / "review-workspace.jsx"
        ).read_text(encoding="utf-8")
        self.assertIn("template.user_display_name", source)
        self.assertIn("template.canonical_name", source)
        self.assertIn("template.official_role_definition", source)
        self.assertIn("for (const alias of template.aliases || [])", source)

    def test_validation_tool_is_local_and_does_not_import_forbidden_runtimes(self):
        source = (
            ROOT / "scripts" / "validate_template_group_registry.py"
        ).read_text(encoding="utf-8")
        for forbidden_import in (
            "import azure.ai",
            "import huggingface_hub",
            "import openai",
            "from database import",
            "import xbrl_generator",
            "import arelle",
        ):
            with self.subTest(forbidden_import=forbidden_import):
                self.assertNotIn(forbidden_import, source)


if __name__ == "__main__":
    unittest.main()
