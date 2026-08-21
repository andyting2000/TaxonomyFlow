import json
import tempfile
import unittest
from pathlib import Path

from services.taxonomy_concept_metadata import (
    best_label_match,
    build_metadata_report,
    classify_concept_family,
    load_taxonomy_concept_metadata,
    render_metadata_markdown,
    section_family_match,
    statement_family_compatible,
)


def template_payload():
    return {
        "templates": {
            "310000": {
                "concepts": [
                    {"id": "ifrs-smes:Revenue", "label": "Revenue"},
                    {"id": "ifrs-smes:IncomeTaxExpenseContinuingOperations", "label": "Income Tax Expense"},
                    {"id": "ifrs-smes:OtherExpenseByFunction", "label": "Other expense by function"},
                ]
            },
            "210000": {
                "concepts": [
                    {"id": "ifrs-smes:CurrentTaxLiabilitiesCurrent", "label": "Current tax liabilities"},
                    {"id": "ifrs-smes:TradeAndOtherReceivables", "label": "Trade and other receivables"},
                    {"id": "ifrs-smes:TradeAndOtherPayables", "label": "Trade and other payables"},
                    {"id": "ifrs-smes:PropertyPlantAndEquipment", "label": "Property, plant and equipment"},
                    {"id": "ssmt:CashAndBankBalances", "label": "Cash and bank balances"},
                ]
            },
            "510000": {
                "concepts": [
                    {
                        "id": "ifrs-smes:CashFlowsFromUsedInOperatingActivities",
                        "label": "Cash flows from used in operating activities",
                    }
                ]
            },
        }
    }


class TaxonomyConceptMetadataTests(unittest.TestCase):
    def load_fixture(self):
        tmp = tempfile.TemporaryDirectory()
        path = Path(tmp.name) / "taxonomy.json"
        path.write_text(json.dumps(template_payload()), encoding="utf-8")
        concepts, diagnostics = load_taxonomy_concept_metadata(path, concept_playbook_path=None)
        self.addCleanup(tmp.cleanup)
        return {item["qname"]: item for item in concepts}, diagnostics

    def test_loads_template_metadata_with_safe_aliases_and_families(self):
        concepts, diagnostics = self.load_fixture()

        self.assertEqual(diagnostics["status"], "loaded")
        self.assertEqual(diagnostics["concept_count"], 9)
        self.assertEqual(concepts["ifrs-smes:Revenue"]["concept_family"], "income")
        self.assertIn("revenue", concepts["ifrs-smes:Revenue"]["normalized_labels"])
        self.assertNotIn("total", concepts["ifrs-smes:Revenue"]["aliases"])
        self.assertIn("income_statement", concepts["ifrs-smes:Revenue"]["compatible_statement_families"])

    def test_classifies_tax_balance_sheet_and_cash_flow_concepts(self):
        concepts, _diagnostics = self.load_fixture()

        self.assertEqual(concepts["ifrs-smes:CurrentTaxLiabilitiesCurrent"]["concept_family"], "tax")
        self.assertEqual(concepts["ifrs-smes:CurrentTaxLiabilitiesCurrent"]["balance_type_hint"], "liability")
        self.assertIn("financial_position", concepts["ifrs-smes:CurrentTaxLiabilitiesCurrent"]["compatible_statement_families"])
        self.assertEqual(concepts["ifrs-smes:TradeAndOtherReceivables"]["concept_family"], "receivable")
        self.assertEqual(concepts["ifrs-smes:TradeAndOtherPayables"]["concept_family"], "payable")
        self.assertEqual(concepts["ifrs-smes:PropertyPlantAndEquipment"]["concept_family"], "ppe")
        self.assertEqual(concepts["ifrs-smes:CashFlowsFromUsedInOperatingActivities"]["concept_family"], "cash_flow")

    def test_statement_and_section_compatibility_are_conservative(self):
        concepts, _diagnostics = self.load_fixture()
        tax_payable = concepts["ifrs-smes:CurrentTaxLiabilitiesCurrent"]
        tax_expense = concepts["ifrs-smes:IncomeTaxExpenseContinuingOperations"]

        self.assertFalse(statement_family_compatible("income_statement", tax_payable))
        self.assertTrue(statement_family_compatible("financial_position", tax_payable))
        self.assertTrue(statement_family_compatible("income_statement", tax_expense))
        self.assertFalse(statement_family_compatible("financial_position", tax_expense))
        self.assertTrue(section_family_match("current_liabilities", tax_payable))
        self.assertFalse(section_family_match("current_assets", tax_payable))

    def test_best_label_match_uses_curated_aliases_without_generic_aliases(self):
        concepts, _diagnostics = self.load_fixture()
        other_expense = concepts["ifrs-smes:OtherExpenseByFunction"]

        match = best_label_match("Bank charges", other_expense)

        self.assertEqual(match["ratio"], 1.0)
        self.assertEqual(match["matched_label"], "bank charges")
        self.assertEqual(match["match_source"], "alias")

    def test_missing_metadata_can_be_allowed(self):
        concepts, diagnostics = load_taxonomy_concept_metadata("missing-taxonomy-fixture.json", allow_missing=True)

        self.assertEqual(concepts, [])
        self.assertEqual(diagnostics["status"], "missing_allowed")

    def test_metadata_report_serializes(self):
        concepts, diagnostics = self.load_fixture()
        report = build_metadata_report(list(concepts.values()), diagnostics)
        markdown = render_metadata_markdown(report)

        self.assertEqual(report["summary"]["concept_count"], 9)
        self.assertIn("Taxonomy Concept Metadata", markdown)
        self.assertEqual(classify_concept_family("ifrs-smes:Revenue", "Revenue"), "income")


if __name__ == "__main__":
    unittest.main()
