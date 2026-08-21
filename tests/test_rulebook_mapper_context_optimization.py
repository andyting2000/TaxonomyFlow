import json
import unittest
from decimal import Decimal

from services.pdf_xbrl_deterministic_alignment import PdfRowValue, canonical_label
from services.pdf_xbrl_rulebook_mapper import map_row_values_with_context


def row_value(label, *, family="income_statement", value="100"):
    statement = {
        "financial_position": "Statement of Financial Position",
        "income_statement": "Statement of Comprehensive Income",
        "cash_flow": "Statement of Cash Flows",
        "notes": "Notes to the Financial Statements",
    }.get(family)
    return PdfRowValue(
        sample_id="case_test",
        company_name="Example Sdn. Bhd.",
        pdf_row_id=f"case_test:{label}:current",
        source_pdf_row_id=f"case_test:{label}",
        pdf_label=label,
        pdf_value=value,
        numeric_value=Decimal(value),
        value_role="current",
        expected_year=2024,
        pdf_statement_type=statement,
        pdf_statement_family=family,
        pdf_page=1,
        pdf_row_order=1,
        row_type="numeric_fact",
    )


def context(row, **overrides):
    payload = {
        "sample_id": row.sample_id,
        "row_id": row.pdf_row_id,
        "original_label": row.pdf_label,
        "normalized_label": canonical_label(row.pdf_label),
        "statement_family": row.pdf_statement_family,
        "statement_title": row.pdf_statement_type,
        "section_block": "unknown",
        "subsection_block": "unknown",
        "parent_heading": row.pdf_statement_type,
        "nearest_heading": row.pdf_statement_type,
        "row_role": "component",
        "is_main_statement": True,
        "is_notes_context": False,
        "is_cash_flow": row.pdf_statement_family == "cash_flow",
        "is_total": False,
        "is_subtotal": False,
        "context_confidence": 0.92,
        "context_reasons": ["test_context"],
    }
    payload.update(overrides)
    return payload


class RulebookMapperContextOptimizationTests(unittest.TestCase):
    def map_one(self, row, ctx):
        return map_row_values_with_context([row], [], [ctx])[0]

    def test_income_statement_revenue_context_maps_review_required(self):
        row = row_value("Turnover")
        suggestion = self.map_one(row, context(row, section_block="revenue"))

        self.assertEqual(suggestion["predicted_qname"], "ifrs-smes:Revenue")
        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertIn("context_optimized_candidate_requires_review", suggestion["blocking_reasons"])
        self.assertTrue(suggestion["context_optimization_applied"])
        self.assertFalse(suggestion["safe_for_auto_apply"])

    def test_cost_of_sales_does_not_map_to_revenue(self):
        row = row_value("Less : Cost of sales")
        suggestion = self.map_one(row, context(row, normalized_label="revenue", section_block="cost_of_sales"))

        self.assertIsNone(suggestion["predicted_qname"])
        self.assertEqual(suggestion["confidence_bucket"], "no_match")

    def test_low_context_confidence_downgrades_to_review_required(self):
        row = row_value("Revenue")
        suggestion = self.map_one(
            row,
            context(
                row,
                section_block="revenue",
                is_main_statement=False,
                context_confidence=0.5,
            ),
        )

        self.assertEqual(suggestion["predicted_qname"], "ifrs-smes:Revenue")
        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertIn("low_context_confidence_requires_review", suggestion["blocking_reasons"])

    def test_cash_flow_bank_balances_do_not_map_to_balance_sheet_cash(self):
        row = row_value("Bank balances", family="cash_flow")
        suggestion = self.map_one(row, context(row, section_block="cash_flow_reconciliation"))

        self.assertIsNone(suggestion["predicted_qname"])
        self.assertEqual(suggestion["confidence_bucket"], "no_match")

    def test_depreciation_ppe_does_not_map_ppe_asset_concept(self):
        row = row_value("Depreciation of property, plant and equipment", family="cash_flow")
        suggestion = self.map_one(row, context(row, section_block="cash_flow_investing"))

        self.assertIsNone(suggestion["predicted_qname"])

    def test_totals_require_total_semantics_for_advisory(self):
        row = row_value("Total current assets", family="financial_position")
        suggestion = self.map_one(
            row,
            context(
                row,
                section_block="current_assets",
                row_role="component",
                is_total=False,
            ),
        )

        self.assertEqual(suggestion["predicted_qname"], "ifrs-smes:CurrentAssets")
        self.assertEqual(suggestion["confidence_bucket"], "review_required")
        self.assertIn("total_semantics_required", suggestion["blocking_reasons"])

    def test_context_optimized_output_serializes_to_json(self):
        row = row_value("Trade receivables", family="financial_position")
        suggestion = self.map_one(row, context(row, section_block="current_assets"))

        encoded = json.dumps(suggestion, default=str)
        self.assertIn("TradeAndOtherCurrentReceivables", encoded)
        self.assertIn("row_context", encoded)


if __name__ == "__main__":
    unittest.main()
