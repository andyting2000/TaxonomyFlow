import json
import tempfile
import unittest
from pathlib import Path

from services.pdf_xbrl_deterministic_alignment import (
    align_pdf_row_value,
    align_sample,
    build_alignment_reports,
    label_similarity,
    normalize_label,
    normalize_numeric_value,
    pdf_row_values,
    write_alignment_reports,
)
from services.reference_xbrl_parser import parse_reference_xbrl


SIMPLE_XBRL = """<?xml version="1.0" encoding="utf-8"?>
<xbrli:xbrl
  xmlns:xbrli="http://www.xbrl.org/2003/instance"
  xmlns:iso4217="http://www.xbrl.org/2003/iso4217"
  xmlns:ifrs-smes="https://xbrl.ifrs.org/taxonomy/2022-03-24/ifrs-smes">
  <xbrli:context id="instant_2025"><xbrli:entity><xbrli:identifier scheme="local">123</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="instant_2024"><xbrli:entity><xbrli:identifier scheme="local">123</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>2024-12-31</xbrli:instant></xbrli:period></xbrli:context>
  <xbrli:context id="duration_2025"><xbrli:entity><xbrli:identifier scheme="local">123</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2025-01-01</xbrli:startDate><xbrli:endDate>2025-12-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:context id="duration_2024"><xbrli:entity><xbrli:identifier scheme="local">123</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context>
  <xbrli:unit id="MYR"><xbrli:measure>iso4217:MYR</xbrli:measure></xbrli:unit>
  <ifrs-smes:Revenue contextRef="duration_2025" unitRef="MYR" decimals="0">1000</ifrs-smes:Revenue>
  <ifrs-smes:Revenue contextRef="duration_2024" unitRef="MYR" decimals="0">900</ifrs-smes:Revenue>
  <ifrs-smes:Assets contextRef="instant_2025" unitRef="MYR" decimals="0">999</ifrs-smes:Assets>
  <ifrs-smes:Liabilities contextRef="instant_2025" unitRef="MYR" decimals="0">999</ifrs-smes:Liabilities>
  <ifrs-smes:CashAndCashEquivalentsAtEndOfPeriod contextRef="instant_2025" unitRef="MYR" decimals="0">500</ifrs-smes:CashAndCashEquivalentsAtEndOfPeriod>
  <ifrs-smes:IncomeTaxExpense contextRef="duration_2025" unitRef="MYR" decimals="0">-100</ifrs-smes:IncomeTaxExpense>
  <ifrs-smes:Accruals contextRef="instant_2025" unitRef="MYR" decimals="0">777</ifrs-smes:Accruals>
  <ifrs-smes:AccruedExpenses contextRef="instant_2025" unitRef="MYR" decimals="0">777</ifrs-smes:AccruedExpenses>
</xbrli:xbrl>
"""


class PdfXbrlDeterministicAlignmentTests(unittest.TestCase):
    def _facts(self):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "reference.xml"
        path.write_text(SIMPLE_XBRL, encoding="utf-8")
        return parse_reference_xbrl("case_001", path)["facts"]

    def _row_value(self, row):
        return pdf_row_values(
            sample_id="case_001",
            company_name="Example",
            row=row,
            fallback_index=1,
            default_current_year=2025,
        )[0]

    def _dataset(self, rows):
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        root = Path(temp_dir.name)
        case_dir = root / "case_001"
        case_dir.mkdir()
        (case_dir / "source.pdf").write_bytes(b"%PDF-1.4 local")
        (case_dir / "reference.xml").write_text(SIMPLE_XBRL, encoding="utf-8")
        (case_dir / "normalized_extraction.json").write_text(json.dumps({"candidates": rows}), encoding="utf-8")
        return root

    def test_value_normalization_handles_common_financial_formats(self):
        self.assertEqual(normalize_numeric_value("RM 1,234.00"), "1234")
        self.assertEqual(normalize_numeric_value("(1,234)"), "-1234")
        self.assertEqual(normalize_numeric_value("-1234"), "-1234")
        self.assertEqual(normalize_numeric_value("-"), "0")
        self.assertIsNone(normalize_numeric_value(""))

    def test_note_references_are_stripped_from_labels(self):
        self.assertEqual(normalize_label("Trade and other receivables (Note 9)"), "trade and other receivables")
        self.assertEqual(normalize_label("Tax expense NOTE 12"), "tax expense")

    def test_exact_or_alias_label_scores_higher_than_weak_match(self):
        exact = label_similarity("Revenue", "Revenue")
        alias = label_similarity("Turnover", "Revenue")
        weak = label_similarity("Revenue", "Property plant and equipment")
        self.assertGreater(exact["ratio"], weak["ratio"])
        self.assertGreater(alias["ratio"], weak["ratio"])

    def test_value_mismatch_blocks_high_confidence_alignment(self):
        row_value = self._row_value(
            {
                "row_type": "numeric_fact",
                "label": "Revenue",
                "value": "1234",
                "current_year": 2025,
                "statement_section": "Statement of Comprehensive Income",
            }
        )
        alignment = align_pdf_row_value(row_value, self._facts())
        self.assertEqual(alignment["confidence_bucket"], "unmatched")
        self.assertIn("no_xbrl_value_match", alignment["conflict_reasons"])

    def test_statement_family_mismatch_penalizes_alignment(self):
        row_value = self._row_value(
            {
                "row_type": "numeric_fact",
                "label": "Revenue",
                "value": "1000",
                "current_year": 2025,
                "statement_section": "Statement of Financial Position",
            }
        )
        alignment = align_pdf_row_value(row_value, self._facts())
        self.assertNotEqual(alignment["confidence_bucket"], "high")
        self.assertIn("statement_family_mismatch", alignment["conflict_reasons"])

    def test_period_context_mismatch_penalizes_alignment(self):
        row_value = self._row_value(
            {
                "row_type": "numeric_fact",
                "label": "Revenue",
                "value": "900",
                "current_year": 2025,
                "statement_section": "Statement of Comprehensive Income",
            }
        )
        alignment = align_pdf_row_value(row_value, self._facts())
        self.assertNotEqual(alignment["confidence_bucket"], "high")
        self.assertIn("period_year_mismatch", alignment["conflict_reasons"])

    def test_duplicate_same_value_facts_produce_ambiguous_classification(self):
        row_value = self._row_value(
            {
                "row_type": "numeric_fact",
                "label": "Amount",
                "value": "999",
                "statement_section": "Statement of Financial Position",
            }
        )
        alignment = align_pdf_row_value(row_value, self._facts())
        self.assertEqual(alignment["confidence_bucket"], "ambiguous")
        self.assertGreaterEqual(alignment["candidate_count"], 2)

    def test_cash_end_of_year_aligns_to_cash_equivalents_concept(self):
        row_value = self._row_value(
            {
                "row_type": "numeric_fact",
                "label": "Cash and cash equivalents at end of year",
                "value": "500",
                "current_year": 2025,
                "statement_section": "Statement of Cash Flows",
            }
        )
        alignment = align_pdf_row_value(row_value, self._facts())
        self.assertEqual(alignment["confidence_bucket"], "high")
        self.assertEqual(alignment["xbrl_qname"], "ifrs-smes:CashAndCashEquivalentsAtEndOfPeriod")

    def test_tax_expense_aligns_to_income_tax_concept(self):
        row_value = self._row_value(
            {
                "row_type": "numeric_fact",
                "label": "Tax expense",
                "value": "(100)",
                "current_year": 2025,
                "statement_section": "Statement of Comprehensive Income",
            }
        )
        alignment = align_pdf_row_value(row_value, self._facts())
        self.assertEqual(alignment["confidence_bucket"], "high")
        self.assertEqual(alignment["xbrl_qname"], "ifrs-smes:IncomeTaxExpense")

    def test_accruals_ambiguity_is_not_forced_high_when_specificity_conflicts(self):
        row_value = self._row_value(
            {
                "row_type": "numeric_fact",
                "label": "Accruals",
                "value": "777",
                "current_year": 2025,
                "statement_section": "Statement of Financial Position",
            }
        )
        alignment = align_pdf_row_value(row_value, self._facts())
        self.assertEqual(alignment["confidence_bucket"], "ambiguous")

    def test_unmatched_pdf_row_is_reported(self):
        alignments, _rows = align_sample(
            sample_id="case_001",
            company_name="Example",
            rows=[
                {
                    "row_type": "numeric_fact",
                    "label": "Unknown row",
                    "value": "123456",
                    "statement_section": "Statement of Financial Position",
                }
            ],
            facts=self._facts(),
        )
        self.assertEqual(alignments[0]["confidence_bucket"], "unmatched")

    def test_unmatched_xbrl_fact_is_reported(self):
        root = self._dataset(
            [
                {
                    "row_type": "numeric_fact",
                    "label": "Revenue",
                    "value": "1000",
                    "current_year": 2025,
                    "statement_section": "Statement of Comprehensive Income",
                }
            ]
        )
        report = build_alignment_reports(dataset_dir=root)
        self.assertGreater(report["unmatched"]["summary"]["unmatched_xbrl_fact_count"], 0)

    def test_reports_are_valid_json(self):
        root = self._dataset(
            [
                {
                    "row_type": "numeric_fact",
                    "label": "Revenue",
                    "value": "1000",
                    "current_year": 2025,
                    "statement_section": "Statement of Comprehensive Income",
                }
            ]
        )
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        output_dir = Path(temp_dir.name)
        result = write_alignment_reports(dataset_dir=root, output_dir=output_dir)
        for key in ("alignment_json", "summary_json", "ambiguous_json", "unmatched_json"):
            json.loads(Path(result["paths"][key]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
