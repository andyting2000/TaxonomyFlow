import unittest

from services.section_aware_row_mapping_eligibility import classify_row_mapping_eligibility


class SectionAwareRowEligibilityTests(unittest.TestCase):
    def classify(self, row, outcome="matched", **kwargs):
        return classify_row_mapping_eligibility(
            {"source_row_id": "row-1", **row},
            section_outcome=outcome,
            **kwargs,
        )

    def test_fact_total_heading_empty_narrative_and_container_are_explicit(self):
        cases = [
            ({"label": "Revenue", "current_value": "100", "row_type": "numeric_fact"}, "matched", "fact_candidate", True),
            ({"label": "Total assets", "current_value": "100", "row_type": "subtotal_or_total"}, "matched", "total_candidate", True),
            ({"label": "Current assets", "row_type": "heading"}, "matched", "heading_only", False),
            ({"label": "Receivables", "row_type": "numeric_fact"}, "matched", "empty_value", False),
            ({"label": "Policy narrative", "row_type": "text_block"}, "matched", "narrative_row", False),
            ({"label": "Revenue", "current_value": "100", "row_type": "numeric_fact"}, "container_only", "structural_only", False),
            ({"label": "Revenue", "current_value": "100", "row_type": "numeric_fact"}, "ambiguous", "ambiguous_eligibility", False),
        ]
        for row, section_outcome, expected, eligible in cases:
            with self.subTest(expected=expected):
                result = self.classify(row, section_outcome)
                self.assertEqual(result.outcome, expected)
                self.assertEqual(result.eligible, eligible)
                self.assertTrue(result.reasons)

    def test_later_duplicate_is_retained_and_not_mapped(self):
        result = self.classify(
            {"label": "Revenue", "current_value": "100", "row_type": "numeric_fact"},
            duplicate_group_id="duplicate-1",
            duplicate_rank=1,
            competing_source_row_ids=["row-2"],
        )
        self.assertEqual(result.outcome, "duplicate_row")
        self.assertFalse(result.eligible)
        self.assertEqual(result.duplicate_group_id, "duplicate-1")
        self.assertEqual(result.competing_source_row_ids, ["row-2"])


if __name__ == "__main__":
    unittest.main()
