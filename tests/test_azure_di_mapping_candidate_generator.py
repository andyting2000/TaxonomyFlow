import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.azure_di_mapping_candidate_generator import (
    generate_mapping_candidate_reports,
    render_candidates_markdown,
    render_confidence_markdown,
    render_gap_analysis_markdown,
    run_mapping_candidate_generation,
)


def concept(qname, label, **overrides):
    payload = {
        "concept_qname": qname,
        "concept_label": label,
        "concept_type": overrides.pop("concept_type", "numeric"),
        "statement_family": overrides.pop("statement_family", "financial_position"),
        "is_numeric_concept": overrides.pop("is_numeric_concept", True),
        "is_text_block_concept": overrides.pop("is_text_block_concept", False),
        "source": "test_fixture",
        "aliases": overrides.pop("aliases", []),
    }
    payload.update(overrides)
    return payload


def item(mapping_input_id="13Z-MAP-0001", **overrides):
    payload = {
        "mapping_input_id": mapping_input_id,
        "source_candidate_id": f"cand-{mapping_input_id}",
        "case_id": "case-a",
        "page_number": 1,
        "row_type": "numeric_fact",
        "label": "Cash and bank balances",
        "value": "100",
        "previous_value": None,
        "text": None,
        "source_snippet": "Cash and bank balances 100",
        "statement_section": "Statement of Financial Position",
        "gate_status": "auto_mappable_candidate",
        "requires_confirmation": False,
        "readiness_level": "high",
        "warning_flags": [],
        "source_provenance": {"page_number": 1},
        "mapping_allowed": True,
        "audit_trail": {"source": "test"},
    }
    payload.update(overrides)
    return payload


def handoff(items):
    return {
        "run_metadata": {"database_mutated": False},
        "total_handoff_candidates": len(items),
        "handoff_items": items,
    }


class AzureDIMappingCandidateGeneratorTests(unittest.TestCase):
    def generate(self, items, concepts):
        return generate_mapping_candidate_reports(
            handoff_report=handoff(items),
            concept_metadata=concepts,
            concept_metadata_limitations=[],
            input_paths={"handoff_report": "memory"},
            run_id="test",
        )

    def test_exact_label_match_produces_high_confidence_suggestion(self):
        candidates, _confidence, _gap = self.generate(
            [item()],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
        )
        record = candidates["mapping_records"][0]
        self.assertEqual(record["mapping_status"], "high_confidence_suggestion")
        self.assertEqual(record["top_suggestion"]["concept_qname"], "ssmt:CashAndBankBalances")

    def test_strong_token_overlap_produces_medium_or_high_suggestion(self):
        candidates, _confidence, _gap = self.generate(
            [item(label="Cash at bank")],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances", aliases=["cash", "bank balances"])],
        )
        self.assertIn(candidates["mapping_records"][0]["mapping_status"], {"high_confidence_suggestion", "medium_confidence_suggestion"})

    def test_suggest_only_candidate_keeps_requires_confirmation_true(self):
        candidates, _confidence, _gap = self.generate(
            [item(gate_status="suggest_mapping_only", requires_confirmation=True)],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
        )
        record = candidates["mapping_records"][0]
        self.assertTrue(record["requires_confirmation"])
        self.assertEqual(record["mapping_status"], "medium_confidence_suggestion")

    def test_auto_mappable_candidate_keeps_requires_confirmation_false(self):
        candidates, _confidence, _gap = self.generate(
            [item()],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
        )
        self.assertFalse(candidates["mapping_records"][0]["requires_confirmation"])

    def test_generic_label_becomes_low_confidence_or_no_safe_suggestion(self):
        candidates, _confidence, _gap = self.generate(
            [item(label="Other")],
            [concept("ifrs-smes:OtherCurrentAssets", "Other current assets")],
        )
        self.assertIn(candidates["mapping_records"][0]["mapping_status"], {"low_confidence_suggestion", "no_safe_suggestion"})

    def test_multiple_close_matches_become_ambiguous_multiple_suggestions(self):
        candidates, _confidence, _gap = self.generate(
            [item()],
            [
                concept("ssmt:CashAndBankBalances", "Cash and bank balances"),
                concept("ifrs-smes:CashAndBankBalances", "Cash and bank balances"),
            ],
        )
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "ambiguous_multiple_suggestions")

    def test_missing_section_lowers_confidence(self):
        candidates, _confidence, _gap = self.generate(
            [item(statement_section=None)],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
        )
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "medium_confidence_suggestion")
        self.assertIn("missing_statement_section", candidates["mapping_records"][0]["blockers"])

    def test_section_mismatch_lowers_confidence_or_blocks_suggestion(self):
        candidates, _confidence, _gap = self.generate(
            [item(label="Cash at bank", statement_section="Statement of Comprehensive Income")],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
        )
        self.assertIn(candidates["mapping_records"][0]["mapping_status"], {"low_confidence_suggestion", "no_safe_suggestion"})

    def test_numeric_candidate_is_not_mapped_to_text_block_concept(self):
        candidates, _confidence, _gap = self.generate(
            [item()],
            [concept("ssmt:DisclosureOfDirectorsReportExplanatory", "Disclosure of Director's Report [text block]", concept_type="text_block", is_numeric_concept=False, is_text_block_concept=True)],
        )
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "no_safe_suggestion")
        self.assertEqual(candidates["mapping_records"][0]["suggestions"], [])

    def test_text_block_candidate_is_not_mapped_to_numeric_concept(self):
        candidates, _confidence, _gap = self.generate(
            [item(row_type="text_block", label="Directors Report", value=None, text="The directors submit their report.", statement_section="Directors Report")],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
        )
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "no_safe_suggestion")

    def test_text_block_candidate_can_map_to_text_block_concept(self):
        candidates, _confidence, _gap = self.generate(
            [item(row_type="text_block", label="Directors Report", value=None, text="The directors submit their report.", statement_section="Directors Report")],
            [concept("ssmt:DisclosureOfDirectorsReportExplanatory", "Disclosure of Director's Report [text block]", concept_type="text_block", statement_family="directors_report", is_numeric_concept=False, is_text_block_concept=True, aliases=["directors report"])],
        )
        self.assertIn(candidates["mapping_records"][0]["mapping_status"], {"high_confidence_suggestion", "medium_confidence_suggestion"})

    def test_comparative_numeric_candidate_can_map_to_numeric_concept(self):
        candidates, _confidence, _gap = self.generate(
            [item(row_type="comparative_numeric_fact", value="100", previous_value="90")],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
        )
        self.assertIn(candidates["mapping_records"][0]["mapping_status"], {"high_confidence_suggestion", "medium_confidence_suggestion"})

    def test_subtotal_total_candidate_carries_subtotal_warning(self):
        candidates, _confidence, _gap = self.generate(
            [item(row_type="subtotal_or_total", label="Total assets")],
            [concept("ifrs-smes:Assets", "Assets")],
        )
        warnings = candidates["mapping_records"][0]["suggestions"][0]["warnings"]
        self.assertIn("subtotal_or_total_requires_policy_confirmation", warnings)

    def test_no_concept_metadata_returns_no_safe_suggestion(self):
        candidates, _confidence, _gap = self.generate([item()], [])
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "no_safe_suggestion")

    def test_candidate_traceability_from_mapping_input_id_is_preserved(self):
        candidates, _confidence, _gap = self.generate(
            [item("13Z-MAP-0042")],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
        )
        record = candidates["mapping_records"][0]
        self.assertEqual(record["mapping_input_id"], "13Z-MAP-0042")
        self.assertEqual(record["audit_trail"]["mapping_input_id"], "13Z-MAP-0042")

    def test_all_mapping_suggestions_remain_suggested_only(self):
        candidates, _confidence, _gap = self.generate(
            [item()],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
        )
        self.assertEqual(candidates["mapping_records"][0]["top_suggestion"]["mapping_decision_status"], "suggested_only")
        self.assertFalse(candidates["mapping_records"][0]["audit_trail"]["final_mapping_approved"])

    def test_confidence_report_counts_statuses_correctly(self):
        candidates, confidence, _gap = self.generate(
            [
                item("high"),
                item("medium", statement_section=None),
                item("none", label="Other"),
                item("ambiguous"),
            ],
            [
                concept("ssmt:CashAndBankBalances", "Cash and bank balances"),
                concept("ifrs-smes:CashAndBankBalances", "Cash and bank balances"),
            ],
        )
        self.assertEqual(sum(candidates["status_counts"].values()), 4)
        self.assertEqual(sum(confidence["status_counts"].values()), 4)

    def test_gap_analysis_lists_no_safe_labels(self):
        _candidates, _confidence, gap = self.generate(
            [item(label="Other")],
            [],
        )
        self.assertEqual(gap["labels_with_no_safe_suggestion"][0]["label"], "Other")

    def test_markdown_reports_render_summary_sections(self):
        candidates, confidence, gap = self.generate(
            [item()],
            [concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
        )
        self.assertIn("## Summary", render_candidates_markdown(candidates))
        self.assertIn("## Summary", render_confidence_markdown(confidence))
        self.assertIn("## Summary", render_gap_analysis_markdown(gap))

    def test_no_azure_di_call_is_required(self):
        with patch("services.azure_document_intelligence_provider.AzureDocumentIntelligenceProvider.analyze_pdf_path") as mocked:
            self.generate([item()], [concept("ssmt:CashAndBankBalances", "Cash and bank balances")])
        mocked.assert_not_called()

    def test_no_hugging_face_or_openai_call_is_required(self):
        candidates, confidence, gap = self.generate([item()], [concept("ssmt:CashAndBankBalances", "Cash and bank balances")])
        for report in [candidates, confidence, gap]:
            self.assertFalse(report["run_metadata"]["live_huggingface_calls_made"])
            self.assertFalse(report["run_metadata"]["live_openai_calls_made"])

    def test_no_db_is_required(self):
        candidates, confidence, gap = self.generate([item()], [concept("ssmt:CashAndBankBalances", "Cash and bank balances")])
        for report in [candidates, confidence, gap]:
            self.assertFalse(report["run_metadata"]["database_mutated"])

    def test_reference_xml_is_not_sent_to_any_model(self):
        candidates, confidence, gap = self.generate([item()], [concept("ssmt:CashAndBankBalances", "Cash and bank balances")])
        for report in [candidates, confidence, gap]:
            self.assertFalse(report["run_metadata"]["reference_xml_sent_to_model"])

    def test_production_semantic_matcher_path_is_not_called(self):
        candidates, _confidence, _gap = self.generate([item()], [concept("ssmt:CashAndBankBalances", "Cash and bank balances")])
        self.assertFalse(candidates["run_metadata"]["production_semantic_matcher_called"])
        self.assertFalse(candidates["run_metadata"]["semantic_matcher_called"])

    def test_runner_writes_reports_without_live_or_db_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff_path = root / "handoff.json"
            handoff_path.write_text(json.dumps(handoff([item()])), encoding="utf-8")
            result = run_mapping_candidate_generation(
                handoff_report_path=handoff_path,
                output_prefix=root / "out",
                concept_metadata=[concept("ssmt:CashAndBankBalances", "Cash and bank balances")],
            )
            self.assertTrue(result["paths"].candidates_json.exists())
            self.assertFalse(result["candidates_report"]["run_metadata"]["azure_di_live_call_made"])


if __name__ == "__main__":
    unittest.main()
