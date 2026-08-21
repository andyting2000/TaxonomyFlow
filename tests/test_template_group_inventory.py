import unittest

from services.document_section_template_classifier import (
    EXPECTED_REGISTRY_SEMANTIC_HASH,
    load_template_group_cards,
)


class TemplateGroupInventoryClassificationTests(unittest.TestCase):
    def test_canonical_registry_produces_exactly_24_complete_cards(self):
        cards, metadata = load_template_group_cards()
        self.assertEqual(len(cards), 24)
        self.assertEqual(len({card.template_group_id for card in cards}), 24)
        self.assertEqual(len({card.role_uri for card in cards}), 24)
        self.assertEqual(metadata["registry_hash"], EXPECTED_REGISTRY_SEMANTIC_HASH)
        self.assertTrue(all(card.canonical_name for card in cards))
        self.assertTrue(all(card.semantic_hash == metadata["registry_hash"] for card in cards))

    def test_730000_is_a_leaf_and_not_the_structural_notes_parent(self):
        cards, _metadata = load_template_group_cards()
        card = next(item for item in cards if item.code == "730000")
        self.assertEqual(card.canonical_name, "Notes - List of notes")
        self.assertEqual(card.structural_role, "leaf_template")
        self.assertNotEqual(card.template_group_id, "notes_container")
        self.assertIn(
            "Notes to Financial Statements",
            card.legacy_aliases_not_for_classification,
        )

    def test_corrected_note_semantics_are_registry_derived(self):
        cards, _metadata = load_template_group_cards()
        by_code = {card.code: card for card in cards}
        self.assertEqual(by_code["740000"].canonical_name, "Notes - Issued capital")
        self.assertEqual(
            by_code["750000"].canonical_name,
            "Notes - Related party transactions",
        )
        self.assertIn(
            "Notes - Information on Companies",
            by_code["740000"].legacy_aliases_not_for_classification,
        )
        self.assertIn(
            "Notes - Reports",
            by_code["750000"].legacy_aliases_not_for_classification,
        )


if __name__ == "__main__":
    unittest.main()
