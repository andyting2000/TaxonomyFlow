import unittest

from scripts import design_summary_duplicate_dedup_policy_11r as designer


def source(label, value, item_id=None, concept="ifrs-smes:Liabilities"):
    return {
        "item_id": item_id or f"id-{label}",
        "page_id": "page-1",
        "page_number": 1,
        "extracted_label": label,
        "extracted_value": value,
        "generated_value": value.replace(",", ""),
        "statement_type": "Statement of Financial Position",
        "template_field_id": concept,
        "confirmed_tag_id": None,
    }


def group(rows, concept="ifrs-smes:Liabilities", concept_label="Liabilities"):
    return {
        "concept": concept,
        "concept_label": concept_label,
        "contextRef": "asof_20241231_SeparateMember",
        "unitRef": "MYR",
        "duplicate_fact_count": len(rows),
        "source_rows": rows,
    }


class SummaryDuplicateDedupPolicy11RTests(unittest.TestCase):
    def test_identical_summary_duplicates_are_safe(self):
        design = designer.build_group_design(
            group([source("Liabilities", "100.00", "a"), source("Liabilities", "100.00", "b")])
        )

        self.assertEqual(design.classification, "safe_identical_summary_duplicate")
        self.assertEqual(design.recommended_future_handling, "deduplicate_keep_one_later")
        self.assertTrue(design.safe_to_deduplicate_later)
        self.assertEqual(design.proposed_keep_item_id, "a")
        self.assertEqual(design.proposed_suppress_item_ids, ["b"])

    def test_conflicting_values_require_manual_review(self):
        design = designer.build_group_design(
            group([source("Liabilities", "100.00", "a"), source("Liabilities", "200.00", "b")])
        )

        self.assertEqual(design.classification, "conflicting_summary_duplicate_requires_manual_review")
        self.assertEqual(design.recommended_future_handling, "require_manual_confirmation_later")
        self.assertFalse(design.safe_to_deduplicate_later)
        self.assertIsNone(design.proposed_keep_item_id)

    def test_subtotal_vs_total_ambiguity_is_not_auto_deduplicated(self):
        design = designer.build_group_design(
            group(
                [
                    source("CURRENT LIABILITIES", "100.00", "a"),
                    source("Total liabilities", "200.00", "b"),
                ]
            )
        )

        self.assertEqual(design.classification, "subtotal_vs_total_ambiguous")
        self.assertEqual(design.recommended_future_handling, "require_manual_confirmation_later")
        self.assertTrue(design.manual_review_required_before_implementation)

    def test_generic_heading_not_preferred_over_explicit_total_label(self):
        rows = designer.build_rows(
            group([source("Liabilities", "100.00", "a"), source("Total liabilities", "100.00", "b")])
        )
        by_id = {row.item_id: row for row in rows}

        self.assertLess(by_id["b"].future_selection_rank, by_id["a"].future_selection_rank)

    def test_no_replacement_aggregation_dimension_or_sign_policy_recommended(self):
        design = designer.build_group_design(
            group([source("Liabilities", "100.00", "a"), source("Liabilities", "100.00", "b")])
        )

        self.assertFalse(design.replacement_concept_recommended)
        self.assertFalse(design.aggregation_recommended)
        self.assertFalse(design.dimension_recommended)
        self.assertFalse(design.sign_normalization_recommended)

    def test_no_apply_or_mutation_path_exists(self):
        self.assertFalse(hasattr(designer, "apply"))
        self.assertFalse(hasattr(designer, "update_rows"))
        self.assertFalse(hasattr(designer, "delete_rows"))
        self.assertTrue(callable(designer.build_report))


if __name__ == "__main__":
    unittest.main()
