import unittest

from schemas import DocumentContentEvidence
from services.document_section_template_classifier import (
    classify_primary_section,
    load_template_group_cards,
)
from tests.template_classification_test_support import fixtures, section


def context_evidence(values):
    return [
        DocumentContentEvidence(
            content_id=f"context-{index}",
            content_type="text_block",
            text_evidence=value,
            pdf_page_indexes=[1],
            azure_page_numbers=[2],
        )
        for index, value in enumerate(values)
    ]


class PrimarySectionTemplateClassifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards, _metadata = load_template_group_cards()
        cls.data = fixtures()

    def classify(self, canonical_type, title, context):
        item = section(canonical_section_type=canonical_type, title=title)
        rows = context_evidence(context)
        item.text_block_ids = [row.content_id for row in rows]
        return classify_primary_section(
            item,
            cards=self.cards,
            content_evidence=rows,
        )

    def test_obvious_primary_fixtures_route_to_expected_canonical_codes(self):
        for case in self.data["A"]["cases"]:
            with self.subTest(case=case):
                outcome = self.classify(
                    case["canonical_section_type"],
                    case["title"],
                    case["context"],
                )
                self.assertEqual(outcome.outcome.value, "matched")
                self.assertEqual(outcome.assignments[0].template_code, case["expected_code"])

    def test_narrative_sections_receive_zero_template_assignments(self):
        for canonical_type in self.data["B"]["canonical_section_types"]:
            with self.subTest(canonical_type=canonical_type):
                outcome = self.classify(canonical_type, canonical_type, [])
                self.assertEqual(outcome.outcome.value, "narrative_only")
                self.assertEqual(outcome.assignments, [])

    def test_unqualified_mutually_exclusive_primary_variant_is_ambiguous(self):
        outcome = self.classify(
            "statement_of_financial_position",
            "Statement of Financial Position",
            [],
        )
        self.assertEqual(outcome.outcome.value, "ambiguous")
        self.assertEqual(
            set(outcome.alternative_template_group_ids),
            {"210000", "220000"},
        )
        self.assertTrue(outcome.warnings)

    def test_method_and_tax_qualifiers_select_the_correct_variants(self):
        for key in ("K", "L"):
            case = self.data[key]
            with self.subTest(fixture=key):
                outcome = self.classify(
                    case["canonical_section_type"],
                    case["title"],
                    case["context"],
                )
                self.assertEqual(outcome.outcome.value, "matched")
                self.assertEqual(outcome.assignments[0].template_code, case["expected_code"])

    def test_notes_parent_is_code_less_container_only(self):
        outcome = self.classify(
            "notes_to_financial_statements",
            "Notes to the Financial Statements",
            [],
        )
        self.assertEqual(outcome.section_id, "notes_container")
        self.assertEqual(outcome.outcome.value, "container_only")
        self.assertEqual(outcome.assignments, [])
        self.assertNotIn("730000", outcome.alternative_template_group_ids)


if __name__ == "__main__":
    unittest.main()
