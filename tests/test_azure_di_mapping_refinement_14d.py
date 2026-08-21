import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.refine_azure_di_mapping_candidates_14d import run_refinement_14d
from services.azure_di_concept_metadata_enricher import build_enriched_concept_metadata
from services.azure_di_concept_metadata_enricher_v2 import (
    build_enriched_concept_metadata_v2,
    build_refinement_comparison_14d,
    render_refinement_comparison_14d_markdown,
)
from services.azure_di_mapping_candidate_generator import generate_mapping_candidate_reports
from services.azure_di_reviewed_mapping_simulator import build_reviewed_mapping_simulation_reports
from services.azure_di_manual_mapping_review import build_manual_mapping_review_reports


def concept(qname, label, **overrides):
    payload = {
        "concept_qname": qname,
        "concept_label": label,
        "concept_type": overrides.pop("concept_type", "numeric"),
        "statement_family": overrides.pop("statement_family", "financial_position"),
        "is_numeric_concept": overrides.pop("is_numeric_concept", True),
        "is_text_block_concept": overrides.pop("is_text_block_concept", False),
        "source": "test_fixture",
    }
    payload.update(overrides)
    return payload


def item(mapping_input_id="13V-MAP-0001", **overrides):
    payload = {
        "mapping_input_id": mapping_input_id,
        "source_candidate_id": f"source-{mapping_input_id}",
        "case_id": "Shield-Plus",
        "page_number": 7,
        "row_type": "comparative_numeric_fact",
        "label": "Cash and bank balances",
        "value": "100",
        "previous_value": "90",
        "text": "",
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


def empty_confidence():
    return {"status_counts": {}, "confidence_tier_counts": {}}


def empty_gap():
    return {"labels_with_no_safe_suggestion": [], "labels_still_ambiguous": []}


def review_queue_fixture():
    return {
        "run_metadata": {"database_mutated": False},
        "review_queue_count": 1,
        "queue_items": [],
    }


def decisions_fixture():
    return {
        "run_metadata": {"database_mutated": False},
        "simulated_decision_count": 1,
        "xbrl_eligible_count": 0,
        "decision_type_counts": {"request_alias_enrichment": 1},
        "simulated_decisions": [
            {
                "decision_type": "request_alias_enrichment",
                "workflow_status": "needs_alias_or_metadata_enrichment",
                "original_confidence_tier": "low",
                "row_type": "comparative_numeric_fact",
                "mapping_input_id": "13V-MAP-0001",
                "xbrl_eligible": False,
                "xbrl_blockers": ["alias_enrichment_needed"],
                "source_evidence": {"label": "PPE", "statement_section": "Statement of Financial Position"},
            }
        ],
    }


class AzureDIMappingRefinement14DTests(unittest.TestCase):
    def generate_v2(self, items, concepts):
        enriched, report = build_enriched_concept_metadata_v2(local_concepts=concepts, reference_report_path=None)
        return generate_mapping_candidate_reports(
            handoff_report=handoff(items),
            concept_metadata=enriched,
            concept_metadata_limitations=report["metadata_limitations"],
            input_paths={"handoff_report": "memory"},
            run_id="test_14d",
        )

    def test_numeric_candidate_is_not_mapped_to_text_block_concept(self):
        candidates, _confidence, _gap = self.generate_v2(
            [item()],
            [
                concept(
                    "ssmt:DisclosureOfDirectorsReportExplanatory",
                    "Disclosure of Director's Report [text block]",
                    concept_type="text_block",
                    is_numeric_concept=False,
                    is_text_block_concept=True,
                    statement_family="directors_report",
                )
            ],
        )
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "no_safe_suggestion")

    def test_text_block_candidate_is_not_mapped_to_numeric_concept(self):
        candidates, _confidence, _gap = self.generate_v2(
            [
                item(
                    row_type="text_block",
                    label="Directors report",
                    value=None,
                    previous_value=None,
                    text="The directors submit their report.",
                    statement_section="Directors Report",
                )
            ],
            [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents")],
        )
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "no_safe_suggestion")

    def test_exact_alias_and_section_match_can_improve_confidence_against_14a_baseline(self):
        source_item = item(label="PPE", statement_section="Statement of Financial Position")
        source_concept = concept("ifrs-smes:PropertyPlantAndEquipment", "Property, plant and equipment")
        base_concepts, _base_report = build_enriched_concept_metadata(local_concepts=[source_concept], reference_report_path=None)
        baseline, _baseline_confidence, _baseline_gap = generate_mapping_candidate_reports(
            handoff_report=handoff([source_item]),
            concept_metadata=base_concepts,
            input_paths={"handoff_report": "memory"},
            run_id="baseline",
        )
        refined, _confidence, _gap = self.generate_v2([source_item], [source_concept])
        before_score = (baseline["mapping_records"][0]["top_suggestion"] or {}).get("score") or 0
        after_score = (refined["mapping_records"][0]["top_suggestion"] or {}).get("score") or 0
        self.assertGreater(after_score, before_score)
        self.assertGreaterEqual(
            {"low_confidence_suggestion": 1, "medium_confidence_suggestion": 2, "high_confidence_suggestion": 3}.get(
                refined["mapping_records"][0]["mapping_status"], 0
            ),
            {"no_safe_suggestion": 0, "low_confidence_suggestion": 1, "medium_confidence_suggestion": 2, "high_confidence_suggestion": 3}.get(
                baseline["mapping_records"][0]["mapping_status"], 0
            ),
        )

    def test_ambiguous_close_matches_remain_ambiguous(self):
        candidates, _confidence, _gap = self.generate_v2(
            [item(label="Other receivable", statement_section="Statement of Financial Position")],
            [
                concept("ifrs-smes:TradeAndOtherCurrentReceivables", "Trade and other current receivables"),
                concept("ssmt-mpers:OtherCurrentReceivables", "Other current receivables"),
            ],
        )
        self.assertEqual(candidates["mapping_records"][0]["mapping_status"], "ambiguous_multiple_suggestions")

    def test_all_suggestions_remain_suggested_only(self):
        candidates, _confidence, _gap = self.generate_v2(
            [item()],
            [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents", statement_family="cash_flows")],
        )
        for suggestion in candidates["mapping_records"][0]["suggestions"]:
            self.assertEqual(suggestion["mapping_decision_status"], "suggested_only")
        self.assertFalse(candidates["mapping_records"][0]["audit_trail"]["final_mapping_approved"])

    def test_simulated_approvals_remain_simulated_and_not_human_approved(self):
        candidates, confidence, gap = self.generate_v2(
            [item()],
            [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents", statement_family="cash_flows")],
        )
        queue, policy, contract, _summary = build_manual_mapping_review_reports(
            mapping_report=candidates,
            confidence_report=confidence,
            gap_report=gap,
            run_id="test",
            input_paths={"mapping_report": "memory"},
        )
        decisions, handoff_report, _eligibility, _simulation_policy = build_reviewed_mapping_simulation_reports(
            review_queue=queue,
            review_policy=policy,
            handoff_contract=contract,
            run_id="test",
            input_paths={"review_queue": "memory"},
        )
        for decision in decisions["simulated_decisions"]:
            self.assertTrue(decision["simulated_only"])
            self.assertFalse(decision["human_approved"])
        for row in handoff_report["handoff_items"]:
            self.assertTrue(row["simulated_only"])
            self.assertFalse(row["human_approved"])

    def test_no_azure_di_huggingface_openai_or_db_is_required(self):
        with patch("services.azure_document_intelligence_provider.AzureDocumentIntelligenceProvider.analyze_pdf_path") as mocked:
            candidates, confidence, gap = self.generate_v2(
                [item()],
                [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents", statement_family="cash_flows")],
            )
        mocked.assert_not_called()
        for report in [candidates, confidence, gap]:
            self.assertFalse(report["run_metadata"]["database_mutated"])
            self.assertFalse(report["run_metadata"]["live_huggingface_calls_made"])
            self.assertFalse(report["run_metadata"]["live_openai_calls_made"])

    def test_no_xbrl_arelle_or_reference_model_path_is_invoked(self):
        candidates, confidence, gap = self.generate_v2(
            [item()],
            [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents", statement_family="cash_flows")],
        )
        for report in [candidates, confidence, gap]:
            self.assertFalse(report["run_metadata"]["xbrl_generated"])
            self.assertFalse(report["run_metadata"]["arelle_validation_run"])
            self.assertFalse(report["run_metadata"]["reference_xml_sent_to_model"])

    def test_14c_vs_14d_comparison_counts_are_generated(self):
        candidates, confidence, gap = self.generate_v2(
            [item()],
            [concept("ssmt:CashAndBankBalances", "Total cash and cash equivalents", statement_family="cash_flows")],
        )
        queue, policy, contract, _summary = build_manual_mapping_review_reports(
            mapping_report=candidates,
            confidence_report=confidence,
            gap_report=gap,
            run_id="test",
            input_paths={"mapping_report": "memory"},
        )
        decisions, handoff_report, eligibility, _simulation_policy = build_reviewed_mapping_simulation_reports(
            review_queue=queue,
            review_policy=policy,
            handoff_contract=contract,
            run_id="test",
            input_paths={"review_queue": "memory"},
        )
        comparison = build_refinement_comparison_14d(
            baseline_14a_candidates={"status_counts": {}, "mapping_records": []},
            baseline_14c_decisions={"decision_type_counts": {}, "simulated_decision_count": 0, "xbrl_eligible_count": 0},
            baseline_14c_eligibility={"xbrl_eligible_count": 0},
            refined_14d_candidates=candidates,
            refined_14d_queue=queue,
            refined_14d_decisions=decisions,
            refined_14d_eligibility=eligibility,
            enrichment_report={"curated_aliases_by_group": {}},
            input_paths={"mapping_report": "memory"},
            run_id="test",
        )
        self.assertIn("before_14c_xbrl_eligible_count", comparison)
        self.assertIn("after_14d_xbrl_eligible_count", comparison)

    def test_markdown_reports_render_summary_sections(self):
        comparison = build_refinement_comparison_14d(
            baseline_14a_candidates={"status_counts": {}, "mapping_records": []},
            baseline_14c_decisions={"decision_type_counts": {}, "simulated_decision_count": 0, "xbrl_eligible_count": 0},
            baseline_14c_eligibility={"xbrl_eligible_count": 0},
            refined_14d_candidates={"status_counts": {}, "mapping_records": []},
            refined_14d_queue={"workflow_status_distribution": {}, "priority_distribution": {}},
            refined_14d_decisions={"decision_type_counts": {}, "simulated_decision_count": 0, "xbrl_eligible_count": 0},
            refined_14d_eligibility={"xbrl_eligible_count": 0},
            enrichment_report={"curated_aliases_by_group": {}},
            input_paths={},
            run_id="test",
        )
        self.assertIn("## Summary", render_refinement_comparison_14d_markdown(comparison))

    def test_runner_writes_14d_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mapping_path = root / "mapping.json"
            confidence_path = root / "confidence.json"
            gap_path = root / "gap.json"
            review_path = root / "review.json"
            decisions_path = root / "decisions.json"
            handoff_path = root / "handoff.json"
            eligibility_path = root / "eligibility.json"
            mapping_path.write_text(json.dumps({"mapping_records": [], "status_counts": {}, "confidence_tier_counts": {}}), encoding="utf-8")
            confidence_path.write_text(json.dumps(empty_confidence()), encoding="utf-8")
            gap_path.write_text(json.dumps(empty_gap()), encoding="utf-8")
            review_path.write_text(json.dumps(review_queue_fixture()), encoding="utf-8")
            decisions_path.write_text(json.dumps(decisions_fixture()), encoding="utf-8")
            handoff_path.write_text(json.dumps(handoff([item(label="Cash and bank balances", statement_section="Statement of Cash Flows")])), encoding="utf-8")
            eligibility_path.write_text(json.dumps({"xbrl_eligible_count": 0}), encoding="utf-8")
            with patch("scripts.refine_azure_di_mapping_candidates_14d.DEFAULT_14C_ELIGIBILITY", eligibility_path):
                result = run_refinement_14d(
                    mapping_report_path=mapping_path,
                    confidence_report_path=confidence_path,
                    gap_report_path=gap_path,
                    review_queue_path=review_path,
                    decisions_report_path=decisions_path,
                    handoff_report_path=handoff_path,
                    reference_report_path=None,
                    output_prefix=root / "out",
                )
            self.assertTrue(result["paths"].candidates_json.exists())
            self.assertTrue(result["paths"].decisions_json.exists())
            self.assertFalse(result["candidates_report"]["run_metadata"]["database_mutated"])
            for row in result["handoff_report"]["handoff_items"]:
                self.assertTrue(str(row["simulated_decision_id"]).startswith("14D-SIM-"))


if __name__ == "__main__":
    unittest.main()
