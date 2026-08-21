import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.refine_azure_di_mapping_candidates_14a import run_refinement
from services.azure_di_concept_metadata_enricher import (
    build_enriched_concept_metadata,
    build_refinement_comparison_report,
    render_refinement_comparison_markdown,
)
from services.azure_di_mapping_candidate_generator import generate_mapping_candidate_reports


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


def item(mapping_input_id="13V-MAP-0001", **overrides):
    payload = {
        "mapping_input_id": mapping_input_id,
        "source_candidate_id": f"cand-{mapping_input_id}",
        "case_id": "Shield-Plus",
        "page_number": 1,
        "row_type": "comparative_numeric_fact",
        "label": "Cash and bank balances",
        "value": "100",
        "previous_value": "90",
        "text": None,
        "source_snippet": "Cash and bank balances 100 90",
        "statement_section": "Statement of Cash Flows",
        "gate_status": "auto_mappable_candidate",
        "requires_confirmation": False,
        "readiness_level": "high",
        "warning_flags": [],
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


class AzureDIMappingRefinement14ATests(unittest.TestCase):
    def generate(self, items, concepts):
        enriched, enrichment_report = build_enriched_concept_metadata(local_concepts=concepts, reference_report_path=None)
        return generate_mapping_candidate_reports(
            handoff_report=handoff(items),
            concept_metadata=enriched,
            concept_metadata_limitations=enrichment_report["metadata_limitations"],
            input_paths={"handoff_report": "memory"},
            run_id="test_14a",
        )

    def test_numeric_candidate_is_not_mapped_to_text_block_concept(self):
        candidates, _confidence, _gap = self.generate(
            [item()],
            [concept("ssmt:DisclosureOfDirectorsReportExplanatory", "Disclosure of Director's Report [text block]", concept_type="text_block", is_numeric_concept=False, is_text_block_concept=True)],
        )
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "no_safe_suggestion")

    def test_text_block_candidate_is_not_mapped_to_numeric_concept(self):
        candidates, _confidence, _gap = self.generate(
            [item(row_type="text_block", label="Directors Report", value=None, previous_value=None, text="The directors submit their report.", statement_section="Directors Report")],
            [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
        )
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "no_safe_suggestion")

    def test_exact_alias_match_improves_score(self):
        candidates, _confidence, _gap = self.generate(
            [item(row_type="text_block", label="Directors Report", value=None, previous_value=None, text="The directors submit their report.", statement_section="Directors Report")],
            [concept("ssmt:DisclosureOfDirectorsReportExplanatory", "Disclosure of Director's Report [text block]", concept_type="text_block", is_numeric_concept=False, is_text_block_concept=True)],
        )
        record = candidates["mapping_records"][0]
        self.assertIn(record["mapping_status"], {"high_confidence_suggestion", "medium_confidence_suggestion"})
        self.assertTrue(record["top_suggestion"]["evidence"]["alias_match"])

    def test_missing_section_prevents_high_confidence(self):
        candidates, _confidence, _gap = self.generate(
            [item(statement_section=None)],
            [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
        )
        self.assertNotEqual(candidates["mapping_records"][0]["mapping_status"], "high_confidence_suggestion")
        self.assertIn("missing_statement_section", candidates["mapping_records"][0]["blockers"])

    def test_multiple_close_matches_produce_ambiguous_status(self):
        candidates, _confidence, _gap = self.generate(
            [item(label="Cash and bank balances")],
            [
                concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents"),
                concept("ifrs-smes:CashAndCashEquivalents", "Cash and cash equivalents at end of period"),
            ],
        )
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "ambiguous_multiple_suggestions")

    def test_suggest_only_candidate_keeps_requires_confirmation_true(self):
        candidates, _confidence, _gap = self.generate(
            [item(gate_status="suggest_mapping_only", requires_confirmation=True)],
            [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
        )
        record = candidates["mapping_records"][0]
        self.assertTrue(record["requires_confirmation"])
        self.assertIn("requires_confirmation", record["blockers"])

    def test_all_mapping_suggestions_remain_suggested_only(self):
        candidates, _confidence, _gap = self.generate(
            [item()],
            [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
        )
        record = candidates["mapping_records"][0]
        self.assertFalse(record["audit_trail"]["final_mapping_approved"])
        if record["top_suggestion"]:
            self.assertEqual(record["top_suggestion"]["mapping_decision_status"], "suggested_only")

    def test_no_fake_concept_qnames_are_created(self):
        source = [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")]
        enriched, _report = build_enriched_concept_metadata(local_concepts=source, reference_report_path=None)
        self.assertEqual({row["concept_qname"] for row in enriched}, {"ssmt:CashAndBankBalances"})

    def test_no_live_azure_di_call_is_required(self):
        with patch("services.azure_document_intelligence_provider.AzureDocumentIntelligenceProvider.analyze_pdf_path") as mocked:
            self.generate([item()], [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")])
        mocked.assert_not_called()

    def test_no_hugging_face_or_openai_call_is_required(self):
        candidates, confidence, gap = self.generate([item()], [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")])
        for report in [candidates, confidence, gap]:
            self.assertFalse(report["run_metadata"]["live_huggingface_calls_made"])
            self.assertFalse(report["run_metadata"]["live_openai_calls_made"])

    def test_no_db_is_required(self):
        candidates, confidence, gap = self.generate([item()], [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")])
        for report in [candidates, confidence, gap]:
            self.assertFalse(report["run_metadata"]["database_mutated"])

    def test_reference_xml_is_not_sent_to_any_model(self):
        candidates, confidence, gap = self.generate([item()], [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")])
        for report in [candidates, confidence, gap]:
            self.assertFalse(report["run_metadata"]["reference_xml_sent_to_model"])

    def test_production_semantic_matcher_path_is_not_called(self):
        candidates, _confidence, _gap = self.generate([item()], [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")])
        self.assertFalse(candidates["run_metadata"]["production_semantic_matcher_called"])
        self.assertFalse(candidates["run_metadata"]["semantic_matcher_called"])

    def test_refinement_comparison_reports_before_after_counts(self):
        baseline, baseline_confidence, _baseline_gap = generate_mapping_candidate_reports(
            handoff_report=handoff([item(label="Other")]),
            concept_metadata=[],
            input_paths={"handoff_report": "memory"},
            run_id="baseline",
        )
        refined, _confidence, _gap = self.generate(
            [item(label="Cash and bank balances")],
            [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
        )
        _enriched, enrichment = build_enriched_concept_metadata(
            local_concepts=[concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
            reference_report_path=None,
        )
        comparison = build_refinement_comparison_report(
            baseline_candidates_report=baseline,
            baseline_confidence_report=baseline_confidence,
            refined_candidates_report=refined,
            enrichment_report=enrichment,
            input_paths={"handoff_report": "memory"},
            run_id="test",
        )
        self.assertIn("before_13z_status_counts", comparison)
        self.assertIn("after_14a_status_counts", comparison)

    def test_markdown_reports_render_summary_sections(self):
        candidates, confidence, gap = self.generate([item()], [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")])
        _enriched, enrichment = build_enriched_concept_metadata(
            local_concepts=[concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
            reference_report_path=None,
        )
        comparison = build_refinement_comparison_report(
            baseline_candidates_report=candidates,
            baseline_confidence_report=confidence,
            refined_candidates_report=candidates,
            enrichment_report=enrichment,
            input_paths={"handoff_report": "memory"},
            run_id="test",
        )
        self.assertIn("## Summary", render_refinement_comparison_markdown(comparison))
        self.assertIn("labels_with_no_safe_suggestion", gap)

    def test_runner_writes_reports_without_live_or_db_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff_path = root / "handoff.json"
            baseline_mapping = root / "baseline_mapping.json"
            baseline_confidence = root / "baseline_confidence.json"
            handoff_path.write_text(json.dumps(handoff([item()])), encoding="utf-8")
            base_candidates, base_confidence, _gap = generate_mapping_candidate_reports(
                handoff_report=handoff([item(label="Other")]),
                concept_metadata=[],
                input_paths={"handoff_report": "memory"},
                run_id="baseline",
            )
            baseline_mapping.write_text(json.dumps(base_candidates), encoding="utf-8")
            baseline_confidence.write_text(json.dumps(base_confidence), encoding="utf-8")
            result = run_refinement(
                handoff_report_path=handoff_path,
                baseline_mapping_report_path=baseline_mapping,
                baseline_confidence_report_path=baseline_confidence,
                reference_report_path=None,
                output_prefix=root / "out",
            )
            self.assertTrue(result["paths"].candidates_json.exists())
            self.assertFalse(result["candidates_report"]["run_metadata"]["database_mutated"])


if __name__ == "__main__":
    unittest.main()
