import json
import unittest

from services.pdf_row_context_extraction import extract_row_contexts_for_case


def row(label, *, section, row_type="numeric_fact", value="100", previous_value=None):
    cells = [
        {"column_index": 0, "content": label},
        {"column_index": 1, "content": "Note"},
        {"column_index": 2, "content": str(value)},
    ]
    if previous_value is not None:
        cells.append({"column_index": 3, "content": str(previous_value)})
    return {
        "row_type": row_type,
        "statement_section": section,
        "label": label,
        "value": value,
        "previous_value": previous_value,
        "current_year": 2024,
        "prior_year": 2023,
        "page_number": 5,
        "provenance": {"row_index": 7, "cells": cells},
    }


class PdfRowContextExtractionTests(unittest.TestCase):
    def contexts(self, rows):
        return extract_row_contexts_for_case(
            sample_id="case_test",
            company_name="Example Sdn. Bhd.",
            rows=rows,
            default_current_year=2024,
        )

    def test_financial_position_receivable_gets_current_asset_context(self):
        contexts = self.contexts([row("Trade receivables", section="Statement of Financial Position")])

        self.assertEqual(len(contexts), 1)
        context = contexts[0]
        self.assertEqual(context["section_block"], "current_assets")
        self.assertEqual(context["row_role"], "component")
        self.assertTrue(context["is_main_statement"])
        self.assertTrue(context["is_current_asset"])
        self.assertGreaterEqual(context["context_confidence"], 0.75)

    def test_notes_context_caps_confidence_and_marks_note_detail(self):
        contexts = self.contexts([row("Tax expenses for the year", section="Notes to the Financial Statements")])

        context = contexts[0]
        self.assertEqual(context["section_block"], "notes_tax")
        self.assertEqual(context["row_role"], "note_detail")
        self.assertTrue(context["is_notes_context"])
        self.assertLess(context["context_confidence"], 0.6)

    def test_total_row_role_and_prior_column_index_are_preserved(self):
        contexts = self.contexts(
            [
                row(
                    "Total current assets",
                    section="Statement of Financial Position",
                    row_type="subtotal_or_total",
                    value="200",
                    previous_value="150",
                )
            ]
        )

        self.assertEqual([item["period"]["value_role"] for item in contexts], ["current", "prior"])
        self.assertEqual([item["column_index"] for item in contexts], [2, 3])
        self.assertTrue(all(item["is_total"] for item in contexts))

    def test_cash_flow_bank_balances_stays_cash_flow_context(self):
        contexts = self.contexts([row("Bank balances", section="Statement of Cash Flows", previous_value="50")])

        self.assertTrue(all(item["is_cash_flow"] for item in contexts))
        self.assertTrue(all(item["section_block"] == "cash_flow_reconciliation" for item in contexts))
        self.assertFalse(any(item["is_current_asset"] for item in contexts))

    def test_contexts_serialize_to_json(self):
        contexts = self.contexts([row("Revenue", section="Statement of Comprehensive Income")])

        encoded = json.dumps(contexts, default=str)
        self.assertIn("revenue", encoded.lower())


if __name__ == "__main__":
    unittest.main()
