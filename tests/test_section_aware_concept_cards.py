import unittest

from services.section_aware_taxonomy_concept_cards import (
    build_taxonomy_concept_inventory,
    cards_for_template_groups,
    concept_inventory_hash,
)


class SectionAwareConceptCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards, cls.metadata = build_taxonomy_concept_inventory()

    def test_inventory_is_deterministic_local_and_registry_bound(self):
        second, metadata = build_taxonomy_concept_inventory()
        self.assertEqual([card.qname for card in self.cards], sorted(card.qname for card in self.cards))
        self.assertEqual(concept_inventory_hash(self.cards), self.metadata["concept_inventory_hash"])
        self.assertEqual(metadata, self.metadata)
        self.assertEqual(self.metadata["registry_hash"], "16de7eaeafcdf760c7f4869072a6b0a3925088f6bc260672389b5c502015b7d4")
        self.assertEqual(self.metadata["provider_calls"], 0)
        self.assertFalse(self.metadata["benchmark_answers_used"])
        self.assertEqual([item.model_dump() for item in second], [item.model_dump() for item in self.cards])

    def test_cards_include_local_schema_metadata_and_exact_membership(self):
        cash = next(card for card in self.cards if card.qname == "ssmt:CashAndBankBalances")
        self.assertEqual(cash.period_type, "instant")
        self.assertIn("monetaryItemType", cash.datatype)
        self.assertFalse(cash.abstract)
        self.assertIn("210000", cash.template_group_ids)
        self.assertNotIn("310000", cash.template_group_ids)
        allowed = cards_for_template_groups(["310000"], cards=self.cards)
        self.assertTrue(allowed)
        self.assertTrue(all("310000" in card.template_group_ids for card in allowed))
        self.assertNotIn(cash.qname, {card.qname for card in allowed})

    def test_notes_codes_are_canonical_and_container_is_not_a_concept_group(self):
        groups = {group for card in self.cards for group in card.template_group_ids}
        self.assertTrue({"730000", "740000", "750000"}.issubset(groups))
        self.assertNotIn("notes_container", groups)
        with self.assertRaisesRegex(ValueError, "Unknown or non-mapping"):
            cards_for_template_groups(["notes_container"], cards=self.cards)

    def test_runtime_cards_contain_no_evaluation_answers(self):
        encoded = str([card.model_dump() for card in self.cards[:20]]).lower()
        for forbidden in ("correct_qname", "expected_qname", "benchmark_gold", "evaluation_label"):
            self.assertNotIn(forbidden, encoded)


if __name__ == "__main__":
    unittest.main()
