import json
import unittest

from services.hybrid_candidate_ranking_mapper import (
    SAFETY,
    build_reports,
    load_cached_qwen_candidates,
    load_taxonomy_concept_metadata,
    rank_candidates_for_record,
)
from services.pdf_xbrl_deterministic_alignment import canonical_label


def record(label, *, family="financial_position", section="current_assets", role="component", qname=None):
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
        "predicted_qname": qname,
        "predicted_concept_label": qname.split(":")[-1] if qname else None,
        "candidate_generation_method": "statement_template" if qname else None,
        "confidence_bucket": "review_required" if qname else "no_match",
        "safe_for_auto_apply": False,
        "requires_human_review": True,
    }


def concept(qname, label, *, family="financial_position", template=True, concept_family=None):
    return {
        "qname": qname,
        "concept_label": label,
        "normalized_label": canonical_label(label),
        "statement_families": [family] if family else [],
        "template_codes": ["210000"] if template and family == "financial_position" else ["310000"] if template and family == "income_statement" else ["520000"] if template and family == "cash_flow" else ["710000"] if template and family == "notes" else [],
        "concept_family": concept_family or family,
    }


class HybridCandidateFilteringTests(unittest.TestCase):
    def test_taxonomy_lexical_candidate_suppressed_for_generic_label_without_strong_context(self):
        ranked = rank_candidates_for_record(
            record("Assets", family="financial_position", section="assets"),
            concepts=[concept("ifrs-smes:Assets", "Assets", template=False)],
            filter_mode="tightened",
        )

        self.assertFalse(ranked["candidates"])
        self.assertFalse(ranked["filtered_candidates"])
        self.assertEqual(ranked["candidate_coverage_status"], "no_candidate")

    def test_taxonomy_lexical_candidate_allowed_for_exact_label_with_compatible_statement_family(self):
        ranked = rank_candidates_for_record(
            record("Revenue", family="income_statement", section="revenue"),
            concepts=[concept("ifrs-smes:Revenue", "Revenue", family="income_statement", concept_family="profit_loss")],
            filter_mode="tightened",
        )

        self.assertEqual(ranked["candidates"][0]["qname"], "ifrs-smes:Revenue")
        self.assertEqual(ranked["candidates"][0]["candidate_source"], "taxonomy_lexical")

    def test_profit_loss_row_blocks_balance_sheet_asset_concept(self):
        ranked = rank_candidates_for_record(
            record("Revenue", family="income_statement", section="revenue", qname="ifrs-smes:Assets"),
            concepts=[],
            filter_mode="tightened",
        )

        self.assertFalse(ranked["candidates"])
        self.assertIn("profit_loss_row_blocks_balance_sheet_concept", ranked["filtered_candidates"][0]["filter_reasons"])

    def test_financial_position_row_blocks_profit_loss_income_concept(self):
        ranked = rank_candidates_for_record(
            record("Current assets", family="financial_position", section="current_assets", qname="ifrs-smes:Revenue"),
            concepts=[],
            filter_mode="tightened",
        )

        self.assertFalse(ranked["candidates"])
        self.assertIn("financial_position_row_blocks_profit_loss_or_cash_flow_concept", ranked["filtered_candidates"][0]["filter_reasons"])

    def test_cash_flow_row_blocks_balance_sheet_cash_concept_unless_specific_context(self):
        ranked = rank_candidates_for_record(
            record("Bank balances", family="cash_flow", section="cash_flow_operating", qname="ssmt:CashAndBankBalances"),
            concepts=[],
            filter_mode="tightened",
        )

        self.assertFalse(ranked["candidates"])
        self.assertEqual(ranked["candidate_coverage_status"], "blocked_by_note_boundary")
        self.assertIn("cash_flow_row_blocks_balance_sheet_cash_bank", ranked["blocked_candidates"][0]["blocking_reasons"])

    def test_note_detail_row_blocks_main_statement_concept(self):
        ranked = rank_candidates_for_record(
            record("Depreciation of property plant and equipment", family="notes", section="notes_ppe", role="note_detail", qname="ifrs-smes:PropertyPlantAndEquipment"),
            concepts=[],
            filter_mode="tightened",
        )

        self.assertEqual(ranked["candidate_coverage_status"], "blocked_by_note_boundary")
        self.assertTrue(ranked["blocked_candidates"])

    def test_note_detail_suppresses_note_disclosure_lexical_candidate(self):
        ranked = rank_candidates_for_record(
            record("Tax expense", family="notes", section="notes_tax", role="note_detail"),
            concepts=[
                concept(
                    "ifrs-smes:DisclosureOfIncomeTaxExplanatory",
                    "Disclosure of income tax expense [text block]",
                    family="notes",
                    concept_family="notes",
                )
            ],
            filter_mode="tightened",
        )

        self.assertFalse(ranked["candidates"])
        self.assertEqual(ranked["candidate_coverage_status"], "no_candidate")

    def test_cash_flow_adjustment_concept_is_not_blocked_as_balance_sheet_payable(self):
        ranked = rank_candidates_for_record(
            record("Trade and other payables", family="cash_flow", section="cash_flow_other"),
            concepts=[
                concept(
                    "ifrs-smes:AdjustmentsForIncreaseDecreaseInOtherOperatingPayables",
                    "Adjustments for increase (decrease) in other operating payables",
                    family="cash_flow",
                    concept_family="cash_flow",
                )
            ],
            filter_mode="tightened",
        )

        self.assertEqual(ranked["candidates"][0]["qname"], "ifrs-smes:AdjustmentsForIncreaseDecreaseInOtherOperatingPayables")
        self.assertNotIn(
            "cash_flow_row_blocks_balance_sheet_working_capital_concept",
            ranked["candidates"][0].get("blocking_reasons", []),
        )

    def test_high_risk_label_family_requires_stronger_evidence(self):
        ranked = rank_candidates_for_record(
            record("Trade receivables", family="financial_position", section="assets"),
            concepts=[concept("ifrs-smes:TradeAndOtherCurrentReceivables", "Trade receivables", template=False, concept_family="receivables")],
            filter_mode="tightened",
        )

        self.assertFalse(ranked["candidates"])
        self.assertIn("high_risk_label_family_requires_corrob_or_exact_strong_context", ranked["filtered_candidates"][0]["filter_reasons"])

    def test_taxonomy_lexical_candidate_cannot_be_candidate_high_alone(self):
        ranked = rank_candidates_for_record(
            record("Revenue", family="income_statement", section="revenue"),
            concepts=[concept("ifrs-smes:Revenue", "Revenue", family="income_statement", concept_family="profit_loss")],
            filter_mode="tightened",
        )

        self.assertNotEqual(ranked["candidates"][0]["confidence_bucket"], "candidate_high")

    def test_corroborated_candidate_from_multiple_sources_gets_better_score(self):
        standalone = rank_candidates_for_record(
            record("Revenue", family="income_statement", section="revenue"),
            concepts=[concept("ifrs-smes:Revenue", "Revenue", family="income_statement", concept_family="profit_loss")],
            filter_mode="tightened",
        )
        corroborated = rank_candidates_for_record(
            record("Revenue", family="income_statement", section="revenue", qname="ifrs-smes:Revenue"),
            concepts=[concept("ifrs-smes:Revenue", "Revenue", family="income_statement", concept_family="profit_loss")],
            filter_mode="tightened",
        )

        self.assertIn("deterministic_current_mapper", corroborated["candidates"][0]["candidate_sources_combined"])
        self.assertGreater(corroborated["candidates"][0]["score"], standalone["candidates"][0]["score"])

    def test_candidates_below_score_threshold_are_pruned(self):
        ranked = rank_candidates_for_record(
            record("Miscellaneous", family="income_statement", section="income_statement_other"),
            concepts=[concept("ifrs-smes:Revenue", "Revenue", family="income_statement", concept_family="profit_loss")],
            filter_mode="tightened",
        )

        self.assertFalse(ranked["candidates"])

    def test_close_competing_candidates_are_marked_ambiguous(self):
        ranked = rank_candidates_for_record(
            record("Current assets", family="financial_position", section="current_assets"),
            concepts=[
                concept("ifrs-smes:CurrentAssets", "Current assets"),
                concept("ifrs-smes:CurrentAssetTotal", "Current assets"),
            ],
            top_n=2,
            filter_mode="tightened",
        )

        self.assertIn("multiple_competing_candidates_close_in_score", ranked["candidates"][0]["ambiguity_reasons"])

    def test_safe_for_auto_apply_always_false_and_review_required_true(self):
        ranked = rank_candidates_for_record(
            record("Revenue", family="income_statement", section="revenue", qname="ifrs-smes:Revenue"),
            concepts=[concept("ifrs-smes:Revenue", "Revenue", family="income_statement", concept_family="profit_loss")],
            filter_mode="tightened",
        )

        for candidate in ranked["candidates"]:
            self.assertFalse(candidate["safe_for_auto_apply"])
            self.assertTrue(candidate["requires_human_review"])

    def test_missing_taxonomy_and_qwen_inputs_handled_gracefully(self):
        taxonomy, taxonomy_diag = load_taxonomy_concept_metadata("missing-filter-taxonomy.json", allow_missing=True)
        qwen, qwen_diag = load_cached_qwen_candidates("missing-filter-qwen", allow_missing=True)

        self.assertEqual(taxonomy, [])
        self.assertEqual(qwen, {})
        self.assertEqual(taxonomy_diag["status"], "missing_allowed")
        self.assertEqual(qwen_diag["status"], "missing_allowed")

    def test_no_external_calls_are_made(self):
        self.assertFalse(SAFETY["external_llm_called"])
        self.assertFalse(SAFETY["qwen_called"])
        self.assertFalse(SAFETY["supervisor_called"])
        self.assertFalse(SAFETY["database_mutated"])

    def test_reports_serialize_valid_json(self):
        reports = build_reports(
            records=[record("Revenue", family="income_statement", section="revenue")],
            concepts=[concept("ifrs-smes:Revenue", "Revenue", family="income_statement", concept_family="profit_loss")],
            evaluation_report={"records": []},
            qwen_index={},
            row_values=[],
            facts_by_sample={},
            filter_mode="tightened",
        )

        encoded = json.dumps(reports, default=str)
        self.assertIn("filtered_candidate_count", encoded)
        self.assertIn("safe_for_auto_apply_count", encoded)


if __name__ == "__main__":
    unittest.main()
