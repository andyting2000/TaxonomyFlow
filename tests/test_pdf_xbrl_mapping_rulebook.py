import json
import tempfile
import unittest
from pathlib import Path

from services.pdf_xbrl_mapping_rulebook import build_rulebook_entries, build_rulebook_reports, write_rulebook_reports


def alignment(
    label,
    qname,
    *,
    bucket="high",
    score=95,
    sample="case_001",
    family="financial_position",
    value="100",
    reasons=None,
    conflicts=None,
    period_type="instant",
):
    statement = {
        "financial_position": "Statement of Financial Position",
        "income_statement": "Statement of Comprehensive Income",
        "cash_flow": "Statement of Cash Flows",
    }.get(family, "")
    return {
        "sample_id": sample,
        "company_name": "Example Sdn. Bhd.",
        "pdf_row_id": f"{sample}:{label}:{value}",
        "pdf_label": label,
        "pdf_value": value,
        "pdf_value_role": "current",
        "pdf_expected_year": 2025,
        "pdf_statement_type": statement,
        "pdf_statement_family": family,
        "xbrl_fact_id": f"{sample}:fact:{qname}:{value}",
        "xbrl_qname": qname,
        "xbrl_label": qname.split(":")[-1],
        "xbrl_value": value,
        "xbrl_context_id": f"{sample}_ctx",
        "xbrl_period": (
            {"type": "instant", "instant": "2025-12-31"}
            if period_type == "instant"
            else {"type": "duration", "start": "2025-01-01", "end": "2025-12-31"}
        ),
        "xbrl_unit": "MYR",
        "score": score,
        "score_breakdown": {},
        "confidence_bucket": bucket,
        "match_reasons": reasons or ["value_exact", "exact_normalized_label", "statement_family_match"],
        "conflict_reasons": conflicts or [],
        "competing_candidates": [],
        "candidate_count": 1,
    }


class PdfXbrlMappingRulebookTests(unittest.TestCase):
    def _entry(self, entries, pattern, qname):
        for entry in entries:
            if entry["normalized_label_pattern"] == pattern and entry["target_qname"] == qname:
                return entry
        self.fail(f"Missing rulebook entry for {pattern} -> {qname}")

    def test_repeated_high_confidence_alignment_becomes_strong_active_rule(self):
        entries = build_rulebook_entries(
            [
                alignment("Total current assets", "ifrs-smes:CurrentAssets", sample="case_001"),
                alignment("Total current assets", "ifrs-smes:CurrentAssets", sample="case_002", value="200"),
            ]
        )

        entry = self._entry(entries, "total current assets", "ifrs-smes:CurrentAssets")
        self.assertEqual(entry["rule_status"], "active")
        self.assertEqual(entry["confidence_tier"], "strong")
        self.assertEqual(entry["sample_support_count"], 2)

    def test_single_high_confidence_exact_label_can_be_strong_active_rule(self):
        entries = build_rulebook_entries([alignment("Revenue", "ifrs-smes:Revenue", family="income_statement", period_type="duration")])

        entry = self._entry(entries, "revenue", "ifrs-smes:Revenue")
        self.assertEqual(entry["rule_status"], "active")
        self.assertIn(entry["confidence_tier"], {"strong", "usable"})

    def test_repeated_medium_consistent_alignment_becomes_usable_active_rule(self):
        entries = build_rulebook_entries(
            [
                alignment("Other payables", "ssmt-mpers:OtherCurrentNontradePayables", bucket="medium", score=82, sample="case_001"),
                alignment("Other payables", "ssmt-mpers:OtherCurrentNontradePayables", bucket="medium", score=84, sample="case_002"),
            ]
        )

        entry = self._entry(entries, "trade and other payables", "ssmt-mpers:OtherCurrentNontradePayables")
        self.assertEqual(entry["rule_status"], "active")
        self.assertEqual(entry["confidence_tier"], "usable")

    def test_conflicting_qnames_for_same_label_and_statement_are_excluded(self):
        entries = build_rulebook_entries(
            [
                alignment("Accruals", "ifrs-smes:Accruals"),
                alignment("Accruals", "ifrs-smes:AccruedExpenses", sample="case_002", value="200"),
            ]
        )

        first = self._entry(entries, "accruals", "ifrs-smes:Accruals")
        second = self._entry(entries, "accruals", "ifrs-smes:AccruedExpenses")
        self.assertEqual(first["rule_status"], "excluded")
        self.assertEqual(second["rule_status"], "excluded")
        self.assertIn("label_statement_maps_to_multiple_qnames", first["conflict_reasons"])
        self.assertEqual(first["exclusion_reason"], "conflicting_qnames")

    def test_zero_only_evidence_is_excluded(self):
        entries = build_rulebook_entries(
            [
                alignment("Deferred tax assets", "ifrs-smes:DeferredTaxAssets", value="0"),
                alignment("Deferred tax assets", "ifrs-smes:DeferredTaxAssets", sample="case_002", value="0.00"),
            ]
        )

        entry = self._entry(entries, "deferred tax assets", "ifrs-smes:DeferredTaxAssets")
        self.assertEqual(entry["rule_status"], "excluded")
        self.assertIn("zero_only_evidence", entry["conflict_reasons"])

    def test_generic_label_without_statement_context_is_excluded(self):
        entries = build_rulebook_entries(
            [
                alignment("Total", "ifrs-smes:Assets", family=None),
            ]
        )

        entry = self._entry(entries, "total", "ifrs-smes:Assets")
        self.assertEqual(entry["rule_status"], "excluded")
        self.assertIn("generic_label_without_statement_context", entry["conflict_reasons"])

    def test_statement_family_conflict_requires_review(self):
        entries = build_rulebook_entries(
            [
                alignment("Revenue", "ifrs-smes:Revenue", family="income_statement", period_type="duration"),
                alignment("Revenue", "ifrs-smes:Revenue", sample="case_002", family="financial_position"),
            ]
        )

        families = {entry["statement_family"]: entry for entry in entries}
        self.assertEqual(families["income_statement"]["rule_status"], "review_required")
        self.assertIn("statement_family_conflict", families["income_statement"]["conflict_reasons"])

    def test_target_qname_from_many_label_patterns_is_reported(self):
        entries = build_rulebook_entries(
            [
                alignment("Rental income", "ifrs-smes:OtherIncome", family="income_statement", period_type="duration"),
                alignment("Commission income", "ifrs-smes:OtherIncome", sample="case_002", family="income_statement", period_type="duration"),
                alignment("Dividend income", "ifrs-smes:OtherIncome", sample="case_003", family="income_statement", period_type="duration"),
                alignment("Sundry income", "ifrs-smes:OtherIncome", sample="case_004", family="income_statement", period_type="duration"),
            ]
        )

        entry = self._entry(entries, "rental income", "ifrs-smes:OtherIncome")
        self.assertIn("target_qname_maps_from_many_label_patterns", entry["conflict_reasons"])
        self.assertIn("commission income", entry["competing_label_patterns"])

    def test_observed_aliases_are_preserved(self):
        entries = build_rulebook_entries(
            [
                alignment("Trade and other receivables", "ifrs-smes:TradeAndOtherCurrentReceivables"),
            ]
        )

        entry = self._entry(entries, "trade and other receivables", "ifrs-smes:TradeAndOtherCurrentReceivables")
        self.assertIn("Trade and other receivables", entry["observed_labels"])
        self.assertIn("trade and other receivables", entry["aliases"])

    def test_ambiguous_alignment_does_not_become_active_rule(self):
        entries = build_rulebook_entries(
            [
                alignment("Amount", "ifrs-smes:Assets", bucket="ambiguous", score=65),
            ]
        )

        entry = self._entry(entries, "amount", "ifrs-smes:Assets")
        self.assertEqual(entry["rule_status"], "excluded")
        self.assertIn("ambiguous_alignment_only", entry["exclusion_reason"])

    def test_rulebook_payload_serializes_to_json(self):
        reports = build_rulebook_reports(
            alignment_report={
                "alignments": [
                    alignment("Revenue", "ifrs-smes:Revenue", family="income_statement", period_type="duration"),
                ]
            }
        )

        encoded = json.dumps(reports, default=str)
        self.assertIn("ifrs-smes:Revenue", encoded)

    def test_write_reports_creates_valid_json_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            alignment_report = root / "alignment.json"
            summary_report = root / "summary.json"
            ambiguous_report = root / "ambiguous.json"
            output_dir = root / "reports"
            alignment_report.write_text(
                json.dumps(
                    {
                        "alignments": [
                            alignment("Revenue", "ifrs-smes:Revenue", family="income_statement", period_type="duration"),
                            alignment(
                                "Other payables",
                                "ssmt-mpers:OtherCurrentNontradePayables",
                                bucket="medium",
                                score=84,
                            ),
                            alignment(
                                "Other payables",
                                "ssmt-mpers:OtherCurrentNontradePayables",
                                bucket="medium",
                                score=85,
                                sample="case_002",
                                value="200",
                            ),
                        ]
                    }
                ),
                encoding="utf-8",
            )
            summary_report.write_text(json.dumps({"summary": {}}), encoding="utf-8")
            ambiguous_report.write_text(json.dumps({"ambiguous_alignments": []}), encoding="utf-8")

            result = write_rulebook_reports(
                alignment_report_path=alignment_report,
                summary_report_path=summary_report,
                ambiguous_report_path=ambiguous_report,
                output_dir=output_dir,
            )

            for key in ("rulebook_json", "summary_json", "conflicts_json", "excluded_json"):
                payload = json.loads(Path(result["paths"][key]).read_text(encoding="utf-8"))
                self.assertEqual(payload["run_metadata"]["feature"], "18B")


if __name__ == "__main__":
    unittest.main()
