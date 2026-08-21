import copy
import hashlib
import json
import unittest
from pathlib import Path

from services.template_group_registry import (
    DEFAULT_REGISTRY_PATH,
    DEFAULT_ROLE_XSD_PATH,
    DEFAULT_RUNTIME_INVENTORY_PATH,
    load_official_role_types,
    load_template_group_registry,
    validate_registry_against_sources,
    validate_registry_structure,
)


ROOT = Path(__file__).resolve().parents[1]


class TemplateGroupTaxonomyReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_template_group_registry()
        cls.runtime = json.loads(
            DEFAULT_RUNTIME_INVENTORY_PATH.read_text(encoding="utf-8")
        )
        cls.by_code = {
            record["code"]: record
            for record in cls.registry["template_groups"]
        }

    def test_all_24_roles_and_definitions_match_bundled_official_xsd(self):
        roles = load_official_role_types()
        self.assertEqual(len(self.by_code), 24)
        for code, record in self.by_code.items():
            with self.subTest(code=code):
                role = roles[record["role_uri"]]
                self.assertEqual(role["role_id"], record["role_id"])
                self.assertEqual(
                    role["definition"],
                    record["official_role_definition"],
                )

    def test_registry_runtime_and_linkbase_reconciliation_passes(self):
        result = validate_registry_against_sources(self.registry)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["template_count"], 24)
        self.assertTrue(
            all(check["passed"] for check in result["checks"]),
            [check for check in result["checks"] if not check["passed"]],
        )

    def test_runtime_codes_role_uris_and_concept_counts_are_unchanged(self):
        runtime_templates = self.runtime["templates"]
        self.assertEqual(set(runtime_templates), set(self.by_code))
        for code, template in runtime_templates.items():
            with self.subTest(code=code):
                record = self.by_code[code]
                self.assertEqual(template["role_uri"], record["role_uri"])
                self.assertEqual(
                    template["total_concepts"],
                    record["concept_membership"]["concept_count"],
                )

    def test_validator_fails_on_runtime_role_or_concept_membership_drift(self):
        role_drift = copy.deepcopy(self.runtime)
        role_drift["templates"]["740000"]["role_uri"] = "urn:wrong"
        role_result = validate_registry_against_sources(
            self.registry,
            runtime_inventory=role_drift,
        )
        self.assertFalse(role_result["passed"])
        self.assertTrue(
            any("740000: runtime role URI" in error for error in role_result["errors"])
        )

        concept_drift = copy.deepcopy(self.runtime)
        concept_drift["templates"]["750000"]["concepts"].reverse()
        concept_result = validate_registry_against_sources(
            self.registry,
            runtime_inventory=concept_drift,
        )
        self.assertFalse(concept_result["passed"])
        self.assertTrue(
            any(
                "750000: ordered concept membership hash mismatch" in error
                for error in concept_result["errors"]
            )
        )

    def test_duplicate_code_and_conflicting_role_fail_structure_validation(self):
        duplicate = copy.deepcopy(self.registry)
        duplicate.pop("_registry_metadata", None)
        duplicate["template_groups"][1]["code"] = "020000"
        duplicate["template_groups"][1]["template_group_id"] = "020000"
        duplicate["template_groups"][1]["role_uri"] = duplicate[
            "template_groups"
        ][0]["role_uri"]
        errors = validate_registry_structure(duplicate)
        self.assertTrue(
            any("template code '020000' occurs 2 times" in error for error in errors)
        )
        self.assertTrue(
            any("role URI " in error and "occurs 2 times" in error for error in errors)
        )

    def test_known_source_hashes_prove_runtime_and_taxonomy_are_read_only(self):
        runtime_hash = hashlib.sha256(
            DEFAULT_RUNTIME_INVENTORY_PATH.read_bytes()
        ).hexdigest()
        role_hash = hashlib.sha256(DEFAULT_ROLE_XSD_PATH.read_bytes()).hexdigest()
        self.assertEqual(
            runtime_hash,
            "892024b5869ba983acde86dbf0e940f78dcb35459422455f21e8935da19c6e5a",
        )
        self.assertEqual(
            role_hash,
            "145bf4a40885bf2f6145121b805161ee94fb177150cd2fea200e91d0e825872a",
        )
        self.assertTrue(DEFAULT_REGISTRY_PATH.is_file())


if __name__ == "__main__":
    unittest.main()
