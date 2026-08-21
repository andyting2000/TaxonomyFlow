import json
import tempfile
import unittest
from pathlib import Path

from services.fs_mpers_concept_playbook import (
    assert_payload_is_leakage_safe,
    build_concept_playbook_from_golden,
    build_rag_evidence_payload,
    build_sample_retrieval_report,
    compress_rag_evidence_for_prompt,
    retrieve_concept_cards_for_row,
    retrieve_fewshot_examples_for_row,
)


def _gold(label, concept, *, statement="Statement of Financial Position", case_id="case_001", value="1000"):
    return {
        "extracted_label": label,
        "extracted_value": value,
        "statement_type": statement,
        "correct_concept_qname": concept,
        "correct_template_field_id": concept,
        "evidence": {
            "value_match": True,
            "label_similarity": 1.0,
            "statement_match": True,
        },
        "reason": "clear_high_evidence_alignment",
        "source_case_id": case_id,
    }


def _fixture_report(path: Path) -> None:
    report = {
        "run_metadata": {"feature": "17A"},
        "metrics": {"strong_gold_examples": 15, "ambiguous_alignments": 2},
        "gold_examples": [
            _gold("Contributed share capital", "ifrs-smes:IssuedCapital", case_id="case_001"),
            _gold("Share capital", "ifrs-smes:IssuedCapital", case_id="case_002"),
            _gold("Bank overdraft", "ssmt-mpers:UnsecuredBankOverdrafts", case_id="case_001"),
            _gold("Unsecured bank overdraft", "ssmt-mpers:UnsecuredBankOverdrafts", case_id="case_002"),
            _gold("Cash and cash equivalents", "ifrs-smes:CashAndCashEquivalents", statement="Statement of Cash Flows", case_id="case_001"),
            _gold("Cash at bank", "ifrs-smes:CashAndCashEquivalents", statement="Statement of Financial Position", case_id="case_002"),
            _gold("Other receivable", "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables", case_id="case_001"),
            _gold("Other payable", "ssmt-mpers:OtherCurrentNontradePayables", case_id="case_001"),
            _gold("Accruals", "ssmt-mpers:CurrentNontradeAccruals", statement="Notes to the Financial Statements", case_id="case_002"),
            _gold("Administrative expenses", "ifrs-smes:OtherExpenseByFunction", statement="Statement of Comprehensive Income", case_id="case_003"),
            _gold("Total current assets", "ifrs-smes:CurrentAssets", case_id="case_004"),
            _gold("Total current liabilities", "ifrs-smes:CurrentLiabilities", case_id="case_004"),
            _gold("Employee benefits expense", "ifrs-smes:EmployeeBenefitsExpense", statement="Statement of Comprehensive Income", case_id="case_004"),
            _gold("Other revenue", "ifrs-smes:OtherRevenue", statement="Statement of Comprehensive Income", case_id="case_004"),
            _gold("Profit / (Loss) before taxation", "ifrs-smes:ProfitLossBeforeTax", statement="Statement of Comprehensive Income", case_id="case_004"),
        ],
        "ambiguous_alignments": [
            {
                "extracted_label": "Capital",
                "alignment_status": "ambiguous",
                "candidate_facts": [
                    {"correct_concept_qname": "ifrs-smes:IssuedCapital", "fact_id": "hidden-1"},
                    {"correct_concept_qname": "ifrs-smes:Equity", "fact_id": "hidden-2"},
                ],
            },
            {
                "extracted_label": "Cash movement",
                "alignment_status": "ambiguous",
                "candidate_facts": [
                    {"correct_concept_qname": "ifrs-smes:CashAndCashEquivalents", "fact_id": "hidden-3"},
                    {"correct_concept_qname": "ifrs-smes:CashFlowsFromUsedInOperatingActivities", "fact_id": "hidden-4"},
                ],
            },
        ],
    }
    path.write_text(json.dumps(report), encoding="utf-8")


class FsMpersConceptPlaybookTests(unittest.TestCase):
    def _playbook(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "alignment.json"
        _fixture_report(path)
        return build_concept_playbook_from_golden(
            golden_dir="benchmark_mbrs_pairs",
            alignment_report_path=path,
        )

    def test_concept_cards_build_only_from_strong_gold_examples(self):
        playbook = self._playbook()
        qnames = {card["concept_qname"] for card in playbook["concept_cards"]}

        self.assertIn("ifrs-smes:IssuedCapital", qnames)
        self.assertIn("ssmt-mpers:UnsecuredBankOverdrafts", qnames)
        self.assertNotIn("ifrs-smes:Equity", qnames)
        self.assertEqual(playbook["summary"]["strong_gold_examples_used"], 15)

    def test_ambiguous_alignments_are_diagnostics_not_positive_examples(self):
        playbook = self._playbook()
        issued = next(card for card in playbook["concept_cards"] if card["concept_qname"] == "ifrs-smes:IssuedCapital")

        self.assertEqual(issued["support_count"], 2)
        self.assertTrue(issued["do_not_confuse_with"])
        self.assertEqual(issued["do_not_confuse_with"][0]["concept_qname"], "ifrs-smes:Equity")
        self.assertNotIn("Capital", issued["common_extracted_labels"])

    def test_concept_card_contains_expected_fields(self):
        playbook = self._playbook()
        card = playbook["concept_cards"][0]

        for field in (
            "concept_qname",
            "template_field_id",
            "canonical_label",
            "statement_families_observed",
            "common_extracted_labels",
            "normalized_label_patterns",
            "accounting_synonyms",
            "semantic_families",
            "typical_value_nature",
            "common_sections",
            "example_mappings",
            "do_not_confuse_with",
            "guardrail_notes",
            "source_case_ids",
            "support_count",
            "quality",
        ):
            self.assertIn(field, card)

    def test_retrieval_prioritizes_candidate_concept_cards(self):
        playbook = self._playbook()
        row = {"label": "Contributed share capital", "statement_type": "Statement of Financial Position"}
        candidates = [
            {"template_field_id": "ifrs-smes:IssuedCapital", "label": "Issued capital"},
            {"template_field_id": "ifrs-smes:CashAndCashEquivalents", "label": "Cash and cash equivalents"},
        ]

        cards = retrieve_concept_cards_for_row(row, candidates, playbook=playbook)

        self.assertEqual(cards[0]["concept_qname"], "ifrs-smes:IssuedCapital")
        self.assertTrue(cards[0]["score_breakdown"]["candidate_exact_match"])

    def test_share_capital_does_not_rank_cash_or_current_assets_above_equity_family(self):
        playbook = self._playbook()
        row = {"label": "contributed share capital", "statement_type": "Statement of Financial Position"}
        candidates = [
            {"template_field_id": "ifrs-smes:CurrentAssets", "label": "Current assets"},
            {"template_field_id": "ifrs-smes:CashAndCashEquivalents", "label": "Cash and cash equivalents"},
            {"template_field_id": "ifrs-smes:IssuedCapital", "label": "Issued capital"},
        ]

        cards = retrieve_concept_cards_for_row(row, candidates, playbook=playbook)
        qnames = [card["concept_qname"] for card in cards]

        self.assertEqual(qnames[0], "ifrs-smes:IssuedCapital")
        self.assertNotIn("ifrs-smes:CurrentAssets", qnames[:2])
        self.assertNotIn("ifrs-smes:CashAndCashEquivalents", qnames[:2])

    def test_retrieval_prefers_same_statement_type(self):
        playbook = self._playbook()
        row = {"label": "Administrative expenses", "statement_type": "Statement of Comprehensive Income"}
        candidates = [
            {"template_field_id": "ifrs-smes:OtherExpenseByFunction", "label": "Other expense by function"},
            {"template_field_id": "ifrs-smes:CashAndCashEquivalents", "label": "Cash and cash equivalents"},
        ]

        cards = retrieve_concept_cards_for_row(row, candidates, playbook=playbook)

        self.assertEqual(cards[0]["concept_qname"], "ifrs-smes:OtherExpenseByFunction")
        self.assertTrue(cards[0]["score_breakdown"]["statement_type_compatible"])

    def test_retrieval_returns_relevant_card_for_contributed_share_capital(self):
        playbook = self._playbook()
        cards = retrieve_concept_cards_for_row(
            {"label": "contributed share capital", "statement_type": "Statement of Financial Position"},
            [{"template_field_id": "ifrs-smes:IssuedCapital", "label": "Issued capital"}],
            playbook=playbook,
        )

        self.assertEqual(cards[0]["concept_qname"], "ifrs-smes:IssuedCapital")

    def test_retrieval_returns_relevant_card_for_bank_overdraft(self):
        playbook = self._playbook()
        cards = retrieve_concept_cards_for_row(
            {"label": "bank overdraft", "statement_type": "Statement of Financial Position"},
            [{"template_field_id": "ssmt-mpers:UnsecuredBankOverdrafts", "label": "Unsecured bank overdrafts"}],
            playbook=playbook,
        )

        self.assertEqual(cards[0]["concept_qname"], "ssmt-mpers:UnsecuredBankOverdrafts")

    def test_retrieval_returns_relevant_card_for_cash_and_cash_equivalents(self):
        playbook = self._playbook()
        cards = retrieve_concept_cards_for_row(
            {"label": "cash and cash equivalents", "statement_type": "Statement of Cash Flows"},
            [{"template_field_id": "ifrs-smes:CashAndCashEquivalents", "label": "Cash and cash equivalents"}],
            playbook=playbook,
        )

        self.assertEqual(cards[0]["concept_qname"], "ifrs-smes:CashAndCashEquivalents")

    def test_cash_ranks_cash_cards_before_cash_flow_and_broad_assets(self):
        playbook = self._playbook()
        cards = retrieve_concept_cards_for_row(
            {"label": "cash and cash equivalents", "statement_type": "Statement of Cash Flows"},
            [
                {"template_field_id": "ifrs-smes:CurrentAssets", "label": "Current assets"},
                {"template_field_id": "ifrs-smes:CashAndCashEquivalents", "label": "Cash and cash equivalents"},
            ],
            playbook=playbook,
        )
        qnames = [card["concept_qname"] for card in cards]

        self.assertEqual(qnames[0], "ifrs-smes:CashAndCashEquivalents")
        self.assertNotIn("ifrs-smes:CurrentAssets", qnames[:2])

    def test_other_receivable_prefers_receivable_over_payable(self):
        playbook = self._playbook()
        cards = retrieve_concept_cards_for_row(
            {"label": "other receivable", "statement_type": "Statement of Financial Position"},
            [
                {"template_field_id": "ssmt-mpers:OtherCurrentNontradePayables", "label": "Other current non-trade payables"},
                {
                    "template_field_id": "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                    "label": "Other current non-trade receivables",
                },
            ],
            playbook=playbook,
        )

        self.assertEqual(cards[0]["concept_qname"], "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables")

    def test_other_payable_prefers_payable_over_receivable(self):
        playbook = self._playbook()
        cards = retrieve_concept_cards_for_row(
            {"label": "other payable", "statement_type": "Statement of Financial Position"},
            [
                {
                    "template_field_id": "ssmt-mpers:OtherCurrentMiscellaneousNontradeReceivables",
                    "label": "Other current non-trade receivables",
                },
                {"template_field_id": "ssmt-mpers:OtherCurrentNontradePayables", "label": "Other current non-trade payables"},
            ],
            playbook=playbook,
        )

        self.assertEqual(cards[0]["concept_qname"], "ssmt-mpers:OtherCurrentNontradePayables")

    def test_accruals_rank_current_nontrade_accruals_first(self):
        playbook = self._playbook()
        cards = retrieve_concept_cards_for_row(
            {"label": "accruals", "statement_type": "Statement of Financial Position"},
            [
                {"template_field_id": "ssmt-mpers:OtherCurrentNontradePayables", "label": "Other current non-trade payables"},
                {"template_field_id": "ssmt-mpers:CurrentNontradeAccruals", "label": "Current non-trade accruals"},
            ],
            playbook=playbook,
        )

        self.assertEqual(cards[0]["concept_qname"], "ssmt-mpers:CurrentNontradeAccruals")

    def test_tax_expense_marks_missing_instead_of_ranking_revenue_or_employee_benefits(self):
        playbook = self._playbook()
        row = {"label": "tax expense", "statement_type": "Statement of Comprehensive Income"}
        candidates = [
            {"template_field_id": "ifrs-smes:EmployeeBenefitsExpense", "label": "Employee benefits expense"},
            {"template_field_id": "ifrs-smes:OtherRevenue", "label": "Other revenue"},
            {"template_field_id": "ifrs-smes:ProfitLossBeforeTax", "label": "Profit before tax"},
        ]

        cards = retrieve_concept_cards_for_row(row, candidates, playbook=playbook)
        qnames = [card["concept_qname"] for card in cards]
        payload = build_rag_evidence_payload(row, candidates, playbook=playbook)

        self.assertNotIn("ifrs-smes:EmployeeBenefitsExpense", qnames)
        self.assertNotIn("ifrs-smes:OtherRevenue", qnames)
        self.assertTrue(payload["retrieval_diagnostics"]["missing_relevant_concept_card"])
        self.assertFalse(payload["retrieval_diagnostics"]["matching_concept_card_available"])

    def test_sample_report_flags_missing_tax_card(self):
        playbook = self._playbook()
        report = build_sample_retrieval_report(playbook)
        tax_sample = next(sample for sample in report["samples"] if sample["sample_label"] == "tax expense")

        self.assertTrue(tax_sample["missing_relevant_concept_card"])
        self.assertEqual(tax_sample["missing_reason"], "no_matching_concept_card_available_in_local_playbook")

    def test_do_not_confuse_penalties_are_represented(self):
        playbook = self._playbook()
        cards = retrieve_concept_cards_for_row(
            {"label": "capital", "statement_type": "Statement of Financial Position"},
            [{"template_field_id": "ifrs-smes:Equity", "label": "Equity"}],
            playbook=playbook,
        )
        issued = next(card for card in cards if card["concept_qname"] == "ifrs-smes:IssuedCapital")

        self.assertGreater(issued["score_breakdown"]["do_not_confuse_penalty"], 0)
        self.assertTrue(issued["do_not_confuse_with"])

    def test_evidence_payload_excludes_auditor_xml_parsed_facts_and_target_answers(self):
        playbook = self._playbook()
        payload = build_rag_evidence_payload(
            {"label": "cash and cash equivalents", "value": "1000", "statement_type": "Statement of Cash Flows"},
            [{"template_field_id": "ifrs-smes:CashAndCashEquivalents", "label": "Cash and cash equivalents"}],
            playbook=playbook,
        )
        text = json.dumps(payload, sort_keys=True).lower()

        assert_payload_is_leakage_safe(payload)
        self.assertNotIn("auditor_xml", text)
        self.assertNotIn("parsed_xml_fact", text)
        self.assertNotIn("correct_concept_qname", text)
        self.assertNotIn("correct_template_field_id", text)
        self.assertNotIn("candidate_facts", text)
        self.assertNotIn("fact_id", text)

    def test_deterministic_compression_respects_max_cards_and_examples(self):
        playbook = self._playbook()
        payload = build_rag_evidence_payload(
            {"label": "cash", "value": "1000", "statement_type": "Statement of Financial Position"},
            [
                {"template_field_id": "ifrs-smes:CashAndCashEquivalents", "label": "Cash"},
                {"template_field_id": "ifrs-smes:IssuedCapital", "label": "Issued capital"},
            ],
            max_cards=5,
            max_examples=5,
            playbook=playbook,
        )
        compressed = compress_rag_evidence_for_prompt(payload)

        self.assertLessEqual(len(compressed["retrieved_concept_cards"]), 3)
        self.assertLessEqual(len(compressed["retrieved_fewshot_examples"]), 3)
        self.assertFalse(compressed["compression"]["external_llm_called"])

    def test_no_external_llm_call_is_required(self):
        playbook = self._playbook()
        examples = retrieve_fewshot_examples_for_row(
            {"label": "other payable", "statement_type": "Statement of Financial Position"},
            playbook=playbook,
        )

        self.assertFalse(playbook["run_metadata"]["external_llm_called"])
        self.assertTrue(examples)


if __name__ == "__main__":
    unittest.main()
