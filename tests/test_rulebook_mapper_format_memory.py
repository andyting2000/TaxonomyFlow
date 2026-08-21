import json
import unittest

from scripts.expand_mapper_with_format_memory_18e_b3 import _comparison_report
from services.pdf_note_detail_boundaries import classify_note_detail_boundary
from services.pdf_xbrl_deterministic_alignment import canonical_label
from services.pdf_xbrl_rulebook_mapper import (
    apply_company_format_memory_mapping,
    apply_note_detail_boundary,
)


def context(label, *, family="financial_position", section="non_current_assets", role="component", main=True, notes=False):
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


def base_record(label, *, predicted_qname=None, ctx=None):
    row_context = ctx or context(label)
    return {
        "sample_id": row_context["sample_id"],
        "company_name": "Example",
        "pdf_row_id": row_context["row_id"],
        "pdf_label": label,
        "normalized_label": canonical_label(label),
        "pdf_value": "100",
        "predicted_qname": predicted_qname,
        "predicted_concept_label": predicted_qname.split(":")[-1] if predicted_qname else None,
        "confidence_bucket": "review_required" if predicted_qname else "no_match",
        "confidence_score": 0.5 if predicted_qname else 0.0,
        "safe_for_auto_apply": False,
        "requires_human_review": True,
        "match_reasons": ["fixture"] if predicted_qname else [],
        "blocking_reasons": [],
        "row_context": row_context,
    }


def memory_entry(label, qname, *, family="financial_position", section="non_current_assets", role="component"):
    return {
        "memory_entry_id": f"fixture-{canonical_label(label)}",
        "statement_family": family,
        "section_block": section,
        "expected_row_role": role,
        "normalized_label_pattern": canonical_label(label),
        "label_aliases": [canonical_label(label)],
        "preferred_qname": qname,
        "preferred_concept_label": qname.split(":")[-1],
        "confidence_tier": "format_memory_review_required",
        "source_evidence": {"exact_match_evidence": 2},
        "blocking_conditions": ["format_memory_candidate_requires_review"],
    }


class RulebookMapperFormatMemoryTests(unittest.TestCase):
    def test_ppe_aggregate_main_statement_row_can_map_as_review_required(self):
        ctx = context("Property, plant and equipment", section="non_current_assets", role="component")
        record = base_record("Property, plant and equipment", ctx=ctx)
        boundary = classify_note_detail_boundary(ctx)

        mapped = apply_company_format_memory_mapping(
            record,
            ctx,
            [memory_entry("Property, plant and equipment", "ifrs-smes:PropertyPlantAndEquipment")],
            note_boundary=boundary,
        )

        self.assertEqual(mapped["predicted_qname"], "ifrs-smes:PropertyPlantAndEquipment")
        self.assertEqual(mapped["confidence_bucket"], "review_required")
        self.assertFalse(mapped["safe_for_auto_apply"])

    def test_ppe_movement_note_row_does_not_map_to_ppe_asset_concept(self):
        ctx = context(
            "Depreciation of property, plant and equipment",
            family="notes",
            section="notes_ppe",
            role="note_detail",
            main=False,
            notes=True,
        )
        record = base_record("Depreciation of property, plant and equipment", predicted_qname="ifrs-smes:PropertyPlantAndEquipment", ctx=ctx)

        blocked = apply_note_detail_boundary(record, classify_note_detail_boundary(ctx))

        self.assertIsNone(blocked["predicted_qname"])
        self.assertIn("ppe_movement_note_row_blocks_ppe_balance_concept", blocked["blocking_reasons"])
        self.assertIn("blocked_note_boundary_candidate", blocked)

    def test_tax_note_row_does_not_map_to_profit_loss_tax_expense_without_main_statement_support(self):
        ctx = context(
            "Expenses not deductible for tax purposes",
            family="notes",
            section="notes_tax",
            role="note_detail",
            main=False,
            notes=True,
        )
        record = base_record(
            "Expenses not deductible for tax purposes",
            predicted_qname="ifrs-smes:IncomeTaxExpenseContinuingOperations",
            ctx=ctx,
        )

        blocked = apply_note_detail_boundary(record, classify_note_detail_boundary(ctx))

        self.assertIsNone(blocked["predicted_qname"])
        self.assertIn("tax_reconciliation_note_row_blocks_profit_loss_tax_expense", blocked["blocking_reasons"])

    def test_cash_flow_row_does_not_map_to_balance_sheet_cash(self):
        ctx = context("Cash and cash equivalents at end", family="cash_flow", section="cash_flow_reconciliation", role="component")
        record = base_record("Cash and cash equivalents at end", predicted_qname="ssmt:CashAndBankBalances", ctx=ctx)

        blocked = apply_note_detail_boundary(record, classify_note_detail_boundary(ctx))

        self.assertIsNone(blocked["predicted_qname"])
        self.assertIn("cash_flow_row_blocks_balance_sheet_cash_bank", blocked["blocking_reasons"])

    def test_safe_for_auto_apply_is_always_false(self):
        ctx = context("Total non-current assets", section="non_current_assets", role="total")
        record = base_record("Total non-current assets", ctx=ctx)

        mapped = apply_company_format_memory_mapping(
            record,
            ctx,
            [memory_entry("Total non-current assets", "ifrs-smes:NoncurrentAssets", role="total")],
            note_boundary=classify_note_detail_boundary(ctx),
        )

        self.assertFalse(mapped["safe_for_auto_apply"])
        self.assertTrue(mapped["requires_human_review"])

    def test_blocked_candidates_include_blocking_reasons(self):
        ctx = context("Trade and other payables", family="notes", section="notes_payables", role="note_detail", main=False, notes=True)
        record = base_record("Trade and other payables", predicted_qname="ifrs-smes:TradeAndOtherCurrentPayables", ctx=ctx)

        blocked = apply_note_detail_boundary(record, classify_note_detail_boundary(ctx))

        self.assertIn("blocked_note_boundary_candidate", blocked)
        self.assertTrue(blocked["blocked_note_boundary_candidate"]["blocking_reasons"])

    def test_reports_serialize_valid_json(self):
        baseline = [
            {
                **base_record("Total non-current assets", predicted_qname=None),
                "evaluation_status": "not_evaluable",
            }
        ]
        optimized = [
            {
                **base_record("Total non-current assets", predicted_qname="ifrs-smes:NoncurrentAssets"),
                "evaluation_status": "exact_qname_value_period_match",
                "candidate_generation_method": "company_format_template_memory",
            }
        ]
        report = _comparison_report(
            generated_at="2026-06-23T00:00:00Z",
            baseline_records=baseline,
            optimized_records=optimized,
            memory_report={"summary": {"memory_entry_count": 1}},
            boundary_report={"summary": {"boundary_type_counts": {"main_statement_row": 1}}},
        )

        encoded = json.dumps(report, default=str)
        self.assertIn("new_candidates", encoded)
        self.assertEqual(report["summary"]["new_true_positive_count"], 1)


if __name__ == "__main__":
    unittest.main()
