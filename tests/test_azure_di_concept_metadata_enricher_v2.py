import unittest

from services.azure_di_concept_metadata_enricher import normalize_text
from services.azure_di_concept_metadata_enricher_v2 import (
    apply_curated_aliases_v2,
    build_enriched_concept_metadata_v2,
    diagnose_14c_blockers,
    render_enrichment_v2_markdown,
)


def concept(qname, label, **overrides):
    payload = {
        "concept_qname": qname,
        "concept_label": label,
        "concept_type": overrides.pop("concept_type", "numeric"),
        "is_numeric_concept": overrides.pop("is_numeric_concept", True),
        "is_text_block_concept": overrides.pop("is_text_block_concept", False),
        "statement_family": overrides.pop("statement_family", "financial_position"),
        "source": "test_fixture",
    }
    payload.update(overrides)
    return payload


class AzureDIConceptMetadataEnricherV2Tests(unittest.TestCase):
    def build(self, concepts):
        return build_enriched_concept_metadata_v2(local_concepts=concepts, reference_report_path=None)

    def test_enrichment_v2_attaches_alias_only_to_existing_concept_qname(self):
        concepts, report = self.build([concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")])
        self.assertEqual({row["concept_qname"] for row in concepts}, {"ssmt:CashAndBankBalances"})
        aliases = set(concepts[0]["aliases"])
        self.assertIn(normalize_text("cash at bank"), aliases)
        self.assertGreater(report["curated_alias_count"], 0)

    def test_enrichment_v2_records_unresolved_alias_when_target_missing(self):
        _concepts, report = self.build([])
        groups = {row["group"] for row in report["unresolved_aliases"]}
        self.assertIn("ppe_abbreviations_v2", groups)

    def test_british_malaysian_spelling_alias_can_match_existing_concept(self):
        concepts, _report = self.build([concept("ssmt-mpers:AmortisationExpense", "Amortisation expense")])
        aliases = {alias for row in concepts for alias in row["aliases"]}
        self.assertIn(normalize_text("amortization expense"), aliases)

    def test_abbreviation_alias_maps_only_if_ppe_target_exists(self):
        concepts, _report = self.build([concept("ifrs-smes:PropertyPlantAndEquipment", "Property, plant and equipment")])
        self.assertIn(normalize_text("PPE"), set(concepts[0]["aliases"]))
        concepts_without_ppe, report_without_ppe = self.build([concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")])
        self.assertNotIn(normalize_text("PPE"), {alias for row in concepts_without_ppe for alias in row["aliases"]})
        self.assertIn("ppe_abbreviations_v2", {row["group"] for row in report_without_ppe["unresolved_aliases"]})

    def test_directors_report_text_block_alias_improves_narrative_match(self):
        concepts, _report = self.build(
            [
                concept(
                    "ssmt:DisclosureOfDirectorsReportExplanatory",
                    "Disclosure of Director's Report [text block]",
                    concept_type="text_block",
                    is_numeric_concept=False,
                    is_text_block_concept=True,
                    statement_family="directors_report",
                )
            ]
        )
        self.assertIn(normalize_text("no dividend was paid since the end of the previous financial year"), set(concepts[0]["aliases"]))

    def test_cash_and_bank_balances_alias_improves_numeric_concept_match(self):
        concepts, _report = self.build([concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")])
        self.assertIn(normalize_text("cash and cash equivalents at end of year"), set(concepts[0]["aliases"]))

    def test_receivables_payables_plural_alias_improves_match(self):
        concepts, _report = self.build(
            [
                concept("ifrs-smes:TradeAndOtherCurrentReceivables", "Trade and other current receivables"),
                concept("ifrs-smes:TradeAndOtherCurrentPayables", "Trade and other current payables"),
            ]
        )
        aliases_by_qname = {row["concept_qname"]: set(row["aliases"]) for row in concepts}
        self.assertIn(normalize_text("decrease in receivable"), aliases_by_qname["ifrs-smes:TradeAndOtherCurrentReceivables"])
        self.assertIn(normalize_text("decrease in payable"), aliases_by_qname["ifrs-smes:TradeAndOtherCurrentPayables"])

    def test_depreciation_abbreviation_alias_improves_match(self):
        concepts, _report = self.build([concept("ifrs-smes:DepreciationAndAmortisationExpense", "Depreciation and amortisation expense")])
        self.assertIn(normalize_text("deprn"), set(concepts[0]["aliases"]))

    def test_no_fake_concept_qnames_are_created(self):
        source = [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")]
        concepts, _report = self.build(source)
        self.assertEqual({row["concept_qname"] for row in concepts}, {"ssmt:CashAndBankBalances"})

    def test_blocker_diagnosis_groups_14c_nonapproved_decisions(self):
        decisions = {
            "simulated_decisions": [
                {
                    "decision_type": "request_alias_enrichment",
                    "workflow_status": "needs_alias_or_metadata_enrichment",
                    "original_confidence_tier": "low",
                    "row_type": "text_block",
                    "mapping_input_id": "map-1",
                    "xbrl_eligible": False,
                    "xbrl_blockers": ["alias_enrichment_needed"],
                    "source_evidence": {"label": "Directors report", "statement_section": "Directors Report"},
                }
            ]
        }
        diagnosis = diagnose_14c_blockers(decisions_report=decisions)
        self.assertEqual(diagnosis["decision_type_counts"]["request_alias_enrichment"], 1)
        self.assertEqual(diagnosis["top_labels_needing_alias_enrichment"][0]["label"], "Directors report")

    def test_markdown_summary_renders(self):
        _concepts, report = self.build([concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")])
        self.assertIn("## Summary", render_enrichment_v2_markdown(report))


if __name__ == "__main__":
    unittest.main()

