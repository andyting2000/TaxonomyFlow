import unittest

from services.hybrid_candidate_ranking_mapper import rank_candidates_for_record
from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.taxonomy_concept_metadata import enrich_concept_record


def record(label, *, family, section, role="component"):
    return {
        "sample_id": "case_test",
        "company_name": "Example",
        "pdf_row_id": f"case_test:{canonical_label(label)}:current",
        "pdf_label": label,
        "normalized_label": canonical_label(label),
        "pdf_value": "100",
        "pdf_period": {"value_role": "current", "expected_year": 2024},
        "statement_family": family,
        "section_block": section,
        "row_role": role,
        "confidence_bucket": "no_match",
        "safe_for_auto_apply": False,
        "requires_human_review": True,
    }


def concept(qname, label, *, template_codes=()):
    return enrich_concept_record(
        {
            "qname": qname,
            "concept_label": label,
            "template_codes": list(template_codes),
        }
    )


class TaxonomyLexicalCandidateGenerationTests(unittest.TestCase):
    def test_blocks_income_statement_row_from_balance_sheet_tax_liability(self):
        ranked = rank_candidates_for_record(
            record("Revenue", family="income_statement", section="revenue"),
            concepts=[
                concept(
                    "ifrs-smes:CurrentTaxLiabilitiesCurrent",
                    "Current tax liabilities",
                    template_codes=["210000"],
                )
            ],
            filter_mode="tightened",
        )

        self.assertNotIn("ifrs-smes:CurrentTaxLiabilitiesCurrent", [item["qname"] for item in ranked["candidates"]])

    def test_blocks_financial_position_row_from_profit_loss_expense(self):
        ranked = rank_candidates_for_record(
            record("Current liabilities", family="financial_position", section="current_liabilities", role="total"),
            concepts=[
                concept(
                    "ifrs-smes:OtherExpenseByFunction",
                    "Other expense by function",
                    template_codes=["310000"],
                )
            ],
            filter_mode="tightened",
        )

        self.assertNotIn("ifrs-smes:OtherExpenseByFunction", [item["qname"] for item in ranked["candidates"]])

    def test_exact_curated_alias_recovers_compatible_lexical_candidate(self):
        ranked = rank_candidates_for_record(
            record("Bank charges", family="income_statement", section="administrative_expenses"),
            concepts=[
                concept(
                    "ifrs-smes:OtherExpenseByFunction",
                    "Other expense by function",
                    template_codes=["310000"],
                )
            ],
            filter_mode="tightened",
        )

        self.assertEqual(ranked["candidates"][0]["qname"], "ifrs-smes:OtherExpenseByFunction")
        self.assertIn("taxonomy_lexical", ranked["candidates"][0]["candidate_sources_combined"])
        self.assertEqual(ranked["candidates"][0]["metadata_match"]["matched_label"], "bank charges")

    def test_standalone_taxonomy_lexical_candidate_is_not_candidate_high(self):
        ranked = rank_candidates_for_record(
            record("Bank charges", family="income_statement", section="administrative_expenses"),
            concepts=[
                concept(
                    "ifrs-smes:OtherExpenseByFunction",
                    "Other expense by function",
                    template_codes=["310000"],
                )
            ],
            filter_mode="tightened",
        )

        self.assertEqual(ranked["candidates"][0]["confidence_bucket"], "candidate_low")
        self.assertFalse(ranked["candidates"][0]["safe_for_auto_apply"])
        self.assertTrue(ranked["candidates"][0]["requires_human_review"])

    def test_note_detail_boundary_blocks_main_statement_lexical_candidate(self):
        ranked = rank_candidates_for_record(
            record(
                "Property, plant and equipment",
                family="notes",
                section="notes_ppe",
                role="note_detail",
            ),
            concepts=[
                concept(
                    "ifrs-smes:PropertyPlantAndEquipment",
                    "Property, plant and equipment",
                    template_codes=["210000"],
                )
            ],
            filter_mode="tightened",
        )

        self.assertEqual(ranked["candidate_coverage_status"], "blocked_by_note_boundary")
        self.assertFalse(ranked["candidates"])
        self.assertTrue(ranked["blocked_candidates"])

    def test_main_statement_row_blocks_disclosure_explanatory_concept(self):
        ranked = rank_candidates_for_record(
            record("Trade and other payables", family="financial_position", section="current_liabilities"),
            concepts=[
                concept(
                    "ssmt-mpers:DisclosureOfTradeAndOtherPayablesExplanatory",
                    "Disclosure of trade and other payables explanatory",
                    template_codes=["210000"],
                )
            ],
            filter_mode="tightened",
        )

        self.assertNotIn(
            "ssmt-mpers:DisclosureOfTradeAndOtherPayablesExplanatory",
            [candidate["qname"] for candidate in ranked["candidates"]],
        )

    def test_note_detail_row_does_not_keep_disclosure_lexical_candidate(self):
        ranked = rank_candidates_for_record(
            record("Trade and other payables", family="notes", section="notes_payables", role="note_detail"),
            concepts=[
                concept(
                    "ssmt-mpers:DisclosureOfTradeAndOtherPayablesExplanatory",
                    "Disclosure of trade and other payables explanatory",
                    template_codes=["710000"],
                )
            ],
            filter_mode="tightened",
        )

        self.assertNotIn(
            "ssmt-mpers:DisclosureOfTradeAndOtherPayablesExplanatory",
            [candidate["qname"] for candidate in ranked["candidates"]],
        )


if __name__ == "__main__":
    unittest.main()
