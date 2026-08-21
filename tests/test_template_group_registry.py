import unittest
from collections import Counter

from services.template_group_registry import (
    DISCREPANCY_CLASSIFICATIONS,
    TEMPLATE_KINDS,
    load_template_group_registry,
    resolve_template_group_label,
    semantic_inventory_sha256,
    structural_navigation_nodes,
    template_group_display_name_map,
    template_group_statement_family_map,
    validate_registry_structure,
)


class TemplateGroupRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_template_group_registry()
        cls.records = cls.registry["template_groups"]
        cls.by_code = {record["code"]: record for record in cls.records}

    def test_registry_has_exactly_24_unique_durable_codes_and_roles(self):
        self.assertEqual(len(self.records), 24)
        self.assertEqual(len({record["code"] for record in self.records}), 24)
        self.assertEqual(
            len({record["role_uri"] for record in self.records}),
            24,
        )
        self.assertEqual(
            {record["template_group_id"] for record in self.records},
            {record["code"] for record in self.records},
        )
        self.assertEqual(
            self.registry["durable_identity_fields"],
            ["code", "role_uri"],
        )
        self.assertEqual(validate_registry_structure(self.registry), [])

    def test_all_records_expose_required_semantic_and_classification_metadata(self):
        for record in self.records:
            with self.subTest(code=record["code"]):
                self.assertIn(record["template_kind"], TEMPLATE_KINDS)
                self.assertIn(
                    record["discrepancy_classification"],
                    DISCREPANCY_CLASSIFICATIONS,
                )
                self.assertTrue(record["official_role_definition"])
                self.assertTrue(record["canonical_name"])
                self.assertTrue(record["user_display_name"])
                self.assertTrue(record["normalized_name"])
                self.assertIsInstance(record["aliases"], list)
                self.assertIsInstance(record["classification_enabled"], bool)
                self.assertIsInstance(record["mapping_enabled"], bool)
                self.assertIsInstance(
                    record["allows_multiple_source_sections"],
                    bool,
                )
                metadata = record["classification_metadata"]
                self.assertIsInstance(
                    metadata["expected_source_section_types"],
                    list,
                )
                self.assertIsInstance(
                    metadata["positive_title_indicators"],
                    list,
                )
                self.assertIsInstance(
                    metadata["exclusion_indicators"],
                    list,
                )
                self.assertIsInstance(
                    metadata[
                        "primary_deterministic_classification_allowed"
                    ],
                    bool,
                )
                self.assertIsInstance(
                    metadata["note_subsection_classification_allowed"],
                    bool,
                )
                self.assertIsInstance(
                    metadata["multiple_assignments_allowed"],
                    bool,
                )

    def test_complete_discrepancy_classification_reconciles_all_24(self):
        counts = Counter(
            record["discrepancy_classification"] for record in self.records
        )
        self.assertEqual(
            counts,
            {
                "exact_match": 4,
                "wording_difference_only": 5,
                "user_friendly_alias": 10,
                "ambiguous_semantics": 2,
                "structural_container_conflict": 1,
                "materially_incorrect_name": 2,
            },
        )
        self.assertEqual(sum(counts.values()), 24)

    def test_730000_is_official_note_list_and_not_structural_parent(self):
        record = self.by_code["730000"]
        self.assertEqual(record["canonical_name"], "Notes - List of notes")
        self.assertEqual(record["template_kind"], "note_list")
        self.assertEqual(record["structural_role"], "leaf_template")
        self.assertEqual(
            record["concept_membership"]["presentation_root"],
            "ssmt-mpers:DisclosureOfNotesAndOtherExplanatoryInformationAbstract",
        )
        self.assertIn("Notes to Financial Statements", record["aliases"])
        self.assertFalse(
            record["compatibility"]["legacy_alias_classification_eligible"]
        )
        self.assertFalse(
            record["classification_metadata"][
                "primary_deterministic_classification_allowed"
            ]
        )

    def test_notes_container_is_code_less_and_outside_taxonomy_inventory(self):
        nodes = structural_navigation_nodes()
        self.assertEqual(len(nodes), 1)
        node = nodes[0]
        self.assertEqual(node["id"], "notes_container")
        self.assertEqual(node["classification_outcome"], "container_only")
        self.assertFalse(node["taxonomy_template_group"])
        self.assertIsNone(node["template_code"])
        self.assertIsNone(node["role_uri"])
        self.assertNotIn("notes_container", self.by_code)

    def test_740000_and_750000_have_correct_semantics_and_legacy_aliases(self):
        issued_capital = self.by_code["740000"]
        related_parties = self.by_code["750000"]
        self.assertEqual(
            issued_capital["canonical_name"],
            "Notes - Issued capital",
        )
        self.assertEqual(
            issued_capital["user_display_name"],
            "Issued Capital Note",
        )
        self.assertIn(
            "Notes - Information on Companies",
            issued_capital["aliases"],
        )
        self.assertEqual(
            related_parties["canonical_name"],
            "Notes - Related party transactions",
        )
        self.assertEqual(
            related_parties["user_display_name"],
            "Related Party Transactions",
        )
        self.assertIn("Notes - Reports", related_parties["aliases"])

    def test_legacy_labels_resolve_for_grouping_without_changing_code_identity(self):
        self.assertEqual(
            resolve_template_group_label("Notes to Financial Statements"),
            "730000",
        )
        self.assertEqual(
            resolve_template_group_label("Notes - Information on Companies"),
            "740000",
        )
        self.assertEqual(
            resolve_template_group_label("Notes - Reports"),
            "750000",
        )
        self.assertEqual(
            resolve_template_group_label("Issued Capital Note"),
            "740000",
        )

    def test_derived_name_and_family_maps_have_no_competing_code_list(self):
        display_names = template_group_display_name_map()
        families = template_group_statement_family_map()
        self.assertEqual(set(display_names), set(self.by_code))
        self.assertEqual(set(families), set(self.by_code))
        self.assertEqual(display_names["740000"], "Issued Capital Note")
        self.assertEqual(families["750000"], "notes")

    def test_semantic_hash_is_stable_and_present_in_loaded_metadata(self):
        semantic_hash = semantic_inventory_sha256(self.registry)
        self.assertEqual(len(semantic_hash), 64)
        self.assertEqual(
            semantic_hash,
            self.registry["_registry_metadata"][
                "semantic_inventory_sha256"
            ],
        )


if __name__ == "__main__":
    unittest.main()
