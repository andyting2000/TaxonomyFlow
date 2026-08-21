import json
import unittest

from services.pdf_note_detail_boundaries import (
    boundary_blocks_qname,
    build_note_detail_boundary_report,
    classify_note_detail_boundary,
)
from services.pdf_xbrl_deterministic_alignment import canonical_label


def ctx(label, *, family="financial_position", section="current_assets", role="component", main=True, notes=False):
    return {
        "sample_id": "case_test",
        "row_id": f"case_test:{canonical_label(label)}:current",
        "original_label": label,
        "normalized_label": canonical_label(label),
        "statement_family": family,
        "section_block": section,
        "row_role": role,
        "is_main_statement": main,
        "is_notes_context": notes,
        "context_confidence": 0.9,
    }


class PdfNoteDetailBoundaryTests(unittest.TestCase):
    def test_detects_main_statement_row(self):
        boundary = classify_note_detail_boundary(ctx("Property, plant and equipment", section="non_current_assets"))

        self.assertEqual(boundary["note_boundary_type"], "main_statement_row")
        self.assertTrue(boundary["can_map_to_main_statement_concept"])

    def test_detects_note_detail_row(self):
        boundary = classify_note_detail_boundary(
            ctx("Secretarial fee", family="notes", section="notes_detail", role="note_detail", main=False, notes=True)
        )

        self.assertEqual(boundary["note_boundary_type"], "note_detail_row")
        self.assertFalse(boundary["can_map_to_main_statement_concept"])

    def test_detects_ppe_movement_note_row(self):
        boundary = classify_note_detail_boundary(
            ctx("Accumulated depreciation", family="notes", section="notes_ppe", role="note_detail", main=False, notes=True)
        )

        self.assertEqual(boundary["note_boundary_type"], "note_movement_row")
        blocked, reasons = boundary_blocks_qname(boundary, "ifrs-smes:PropertyPlantAndEquipment")
        self.assertTrue(blocked)
        self.assertIn("ppe_movement_note_row_blocks_ppe_balance_concept", reasons)

    def test_detects_tax_reconciliation_note_row(self):
        boundary = classify_note_detail_boundary(
            ctx("Expenses not deductible for tax purposes", family="notes", section="notes_tax", role="note_detail", main=False, notes=True)
        )

        self.assertEqual(boundary["note_boundary_type"], "note_reconciliation_row")
        blocked, reasons = boundary_blocks_qname(boundary, "ifrs-smes:IncomeTaxExpenseContinuingOperations")
        self.assertTrue(blocked)
        self.assertIn("tax_reconciliation_note_row_blocks_profit_loss_tax_expense", reasons)

    def test_detects_receivables_payables_note_breakdown_row(self):
        boundary = classify_note_detail_boundary(
            ctx("Trade and other payables", family="notes", section="notes_payables", role="note_detail", main=False, notes=True)
        )

        self.assertEqual(boundary["note_boundary_type"], "note_detail_row")
        blocked, reasons = boundary_blocks_qname(boundary, "ifrs-smes:TradeAndOtherCurrentPayables")
        self.assertTrue(blocked)
        self.assertIn("receivables_payables_note_breakdown_blocks_main_aggregate", reasons)

    def test_note_detail_row_blocks_main_statement_concept_mapping(self):
        boundary = classify_note_detail_boundary(
            ctx("Loss for the year", family="notes", section="notes_detail", role="note_detail", main=False, notes=True)
        )

        blocked, reasons = boundary_blocks_qname(boundary, "ifrs-smes:ProfitLoss")

        self.assertTrue(blocked)
        self.assertIn("note_detail_row_blocks_main_statement_concept", reasons)

    def test_cash_flow_row_does_not_map_to_balance_sheet_cash(self):
        boundary = classify_note_detail_boundary(
            ctx("Decrease in cash", family="cash_flow", section="cash_flow_operating", role="component", main=True, notes=False)
        )

        blocked, reasons = boundary_blocks_qname(boundary, "ssmt:CashAndBankBalances")

        self.assertTrue(blocked)
        self.assertIn("cash_flow_row_blocks_balance_sheet_cash_bank", reasons)

    def test_reports_serialize_valid_json(self):
        report = build_note_detail_boundary_report(
            records_or_contexts=[
                ctx("Property, plant and equipment", section="non_current_assets"),
                ctx("Depreciation", family="notes", section="notes_ppe", role="note_detail", main=False, notes=True),
            ]
        )

        encoded = json.dumps(report, default=str)
        self.assertIn("note_detail_boundaries", encoded)
        self.assertEqual(report["summary"]["safe_for_auto_apply_count"], 0)


if __name__ == "__main__":
    unittest.main()
