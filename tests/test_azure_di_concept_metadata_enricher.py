import unittest

from services.azure_di_concept_metadata_enricher import (
    build_enriched_concept_metadata,
    normalize_text,
    render_enrichment_markdown,
)


def concept(qname, label, **overrides):
    payload = {
        "concept_qname": qname,
        "concept_label": label,
        "concept_type": overrides.pop("concept_type", "numeric"),
        "is_numeric_concept": overrides.pop("is_numeric_concept", True),
        "is_text_block_concept": overrides.pop("is_text_block_concept", False),
        "statement_family": overrides.pop("statement_family", "unknown"),
        "source": "test_fixture",
    }
    payload.update(overrides)
    return payload


class AzureDIConceptMetadataEnricherTests(unittest.TestCase):
    def test_enricher_builds_concept_metadata_from_local_concept_fixture(self):
        concepts, report = build_enriched_concept_metadata(
            local_concepts=[concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
            reference_report_path=None,
        )
        self.assertEqual(len(concepts), 1)
        self.assertEqual(report["concept_count"], 1)

    def test_alias_attaches_only_to_existing_concept_qname(self):
        concepts, report = build_enriched_concept_metadata(
            local_concepts=[concept("ssmt:DisclosureOfDirectorsReportExplanatory", "Disclosure of Director's Report [text block]")],
            reference_report_path=None,
        )
        qnames = {row["concept_qname"] for row in concepts}
        self.assertEqual(qnames, {"ssmt:DisclosureOfDirectorsReportExplanatory"})
        aliases = {alias for row in concepts for alias in row["aliases"]}
        self.assertIn(normalize_text("Directors' Report"), aliases)
        self.assertGreater(report["unresolved_alias_count"], 0)

    def test_unresolved_aliases_are_reported_not_fabricated(self):
        concepts, report = build_enriched_concept_metadata(local_concepts=[], reference_report_path=None)
        self.assertEqual(concepts, [])
        self.assertGreater(report["unresolved_alias_count"], 0)
        self.assertEqual(report["concept_count"], 0)

    def test_text_block_concept_is_classified_from_metadata(self):
        concepts, _report = build_enriched_concept_metadata(
            local_concepts=[concept("ssmt:DisclosureOfStatementByDirectorsExplanatory", "Disclosure of Statement by Directors [text block]")],
            reference_report_path=None,
        )
        self.assertTrue(concepts[0]["is_text_block_concept"])
        self.assertFalse(concepts[0]["is_numeric_concept"])

    def test_numeric_concept_is_classified_from_metadata(self):
        concepts, _report = build_enriched_concept_metadata(
            local_concepts=[concept("ifrs-smes:AdministrativeExpense", "Administrative expenses")],
            reference_report_path=None,
        )
        self.assertTrue(concepts[0]["is_numeric_concept"])
        self.assertFalse(concepts[0]["is_text_block_concept"])

    def test_directors_report_alias_can_match_local_directors_report_concept(self):
        concepts, _report = build_enriched_concept_metadata(
            local_concepts=[concept("ssmt:DisclosureOfDirectorsReportExplanatory", "Disclosure of Director's Report [text block]")],
            reference_report_path=None,
        )
        aliases = set(concepts[0]["aliases"])
        self.assertIn(normalize_text("directors hereby submit their report"), aliases)

    def test_statement_by_directors_alias_can_match_local_statement_concept(self):
        concepts, _report = build_enriched_concept_metadata(
            local_concepts=[concept("ssmt:DisclosureOfStatementByDirectorsExplanatory", "Disclosure of Statement by Directors [text block]")],
            reference_report_path=None,
        )
        aliases = set(concepts[0]["aliases"])
        self.assertIn(normalize_text("Statement by Directors"), aliases)

    def test_cash_and_bank_balances_alias_can_match_local_cash_concept(self):
        concepts, _report = build_enriched_concept_metadata(
            local_concepts=[concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
            reference_report_path=None,
        )
        aliases = set(concepts[0]["aliases"])
        self.assertIn(normalize_text("Cash and bank balances"), aliases)

    def test_markdown_summary_renders(self):
        _concepts, report = build_enriched_concept_metadata(
            local_concepts=[concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
            reference_report_path=None,
        )
        self.assertIn("## Summary", render_enrichment_markdown(report))


if __name__ == "__main__":
    unittest.main()
