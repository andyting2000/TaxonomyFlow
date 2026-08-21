import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.azure_di_reviewed_mapping_simulator import (
    SimulationPolicy,
    build_reviewed_mapping_simulation_reports,
    render_decisions_markdown,
    render_eligibility_markdown,
    render_handoff_markdown,
    render_policy_markdown,
    run_reviewed_mapping_simulation,
)


def suggestion(qname="ssmt:CashAndBankBalances", label="Cash and bank balances", **overrides):
    payload = {
        "concept_qname": qname,
        "concept_label": label,
        "concept_type": overrides.pop("concept_type", "numeric"),
        "is_numeric_concept": overrides.pop("is_numeric_concept", True),
        "is_text_block_concept": overrides.pop("is_text_block_concept", False),
        "score": overrides.pop("score", 0.92),
        "confidence_tier": overrides.pop("confidence_tier", "high"),
        "evidence": overrides.pop(
            "evidence",
            {"section_match": True, "row_type_match": True, "concept_type_match": True},
        ),
        "warnings": [],
        "mapping_decision_status": "suggested_only",
        "source": "deterministic_local_metadata",
    }
    payload.update(overrides)
    return payload


def queue_item(review_id="14B-REVIEW-0001", **overrides):
    top = overrides.pop("top_suggestion", suggestion())
    payload = {
        "review_mapping_item_id": review_id,
        "mapping_input_id": f"map-{review_id}",
        "source_candidate_id": f"source-{review_id}",
        "case_id": "Shield-Plus",
        "page_number": 7,
        "row_type": "comparative_numeric_fact",
        "label": "Cash and bank balances",
        "value": "100",
        "previous_value": "90",
        "text_preview": "",
        "statement_section": "Statement of Financial Position",
        "gate_status": "auto_mappable_candidate",
        "requires_confirmation": False,
        "mapping_status": "high_confidence_suggestion",
        "workflow_status": "ready_for_review_approval",
        "priority": "medium",
        "top_suggestion": top,
        "suggestions": [top] if top else [],
        "confidence_tier": (top or {}).get("confidence_tier") if top else "none",
        "score": (top or {}).get("score", 0.0) if top else 0.0,
        "review_reasons": [],
        "blockers": [],
        "warnings": [],
        "source_evidence": {
            "label": "Cash and bank balances",
            "value": "100",
            "previous_value": "90",
            "text_preview": "",
            "statement_section": "Statement of Financial Position",
        },
        "provenance": {"mapping_input_id": f"map-{review_id}", "source_candidate_id": f"source-{review_id}"},
        "audit_trail": {"final_mapping_approved": False, "xbrl_eligible": False},
    }
    payload.update(overrides)
    return payload


def review_queue(items):
    return {
        "run_metadata": {"database_mutated": False},
        "review_queue_count": len(items),
        "queue_items": items,
    }


def review_policy():
    return {
        "workflow_status_definitions": {
            "ready_for_review_approval": "ready",
            "needs_human_concept_choice": "ambiguous",
        }
    }


def handoff_contract():
    return {"contract_status": "future_schema_only_no_approved_mappings"}


class AzureDIReviewedMappingSimulatorTests(unittest.TestCase):
    def build(self, items, policy=None):
        return build_reviewed_mapping_simulation_reports(
            review_queue=review_queue(items),
            review_policy=review_policy(),
            handoff_contract=handoff_contract(),
            run_id="test_14c",
            input_paths={"review_queue": "memory"},
            simulation_policy=policy or SimulationPolicy(),
        )

    def test_ready_high_confidence_item_becomes_simulated_approved_and_xbrl_eligible(self):
        decisions, handoff, _eligibility, _policy = self.build([queue_item()])
        decision = decisions["simulated_decisions"][0]
        self.assertEqual(decision["decision_type"], "approve_suggested_concept_simulated")
        self.assertTrue(decision["xbrl_eligible"])
        self.assertEqual(handoff["xbrl_eligible_count"], 1)

    def test_simulated_approval_has_simulated_only_and_human_approved_false(self):
        decisions, handoff, _eligibility, _policy = self.build([queue_item()])
        decision = decisions["simulated_decisions"][0]
        self.assertTrue(decision["simulated_only"])
        self.assertFalse(decision["human_approved"])
        self.assertTrue(handoff["handoff_items"][0]["simulated_only"])
        self.assertFalse(handoff["handoff_items"][0]["human_approved"])

    def test_needs_confirmation_deferred_by_default_unless_enabled(self):
        item = queue_item(
            "confirm",
            workflow_status="needs_confirmation",
            mapping_status="medium_confidence_suggestion",
            requires_confirmation=True,
            top_suggestion=suggestion(score=0.78, confidence_tier="medium"),
        )
        decisions, _handoff, _eligibility, _policy = self.build([item])
        self.assertEqual(decisions["simulated_decisions"][0]["decision_type"], "defer_mapping")
        enabled, _handoff, _eligibility, _policy = self.build(
            [item],
            policy=SimulationPolicy(simulate_confirm_medium=True),
        )
        self.assertEqual(enabled["simulated_decisions"][0]["decision_type"], "approve_suggested_concept_simulated")

    def test_needs_human_concept_choice_is_not_approved_by_default(self):
        item = queue_item("ambiguous", workflow_status="needs_human_concept_choice", mapping_status="ambiguous_multiple_suggestions")
        decisions, _handoff, _eligibility, _policy = self.build([item])
        self.assertEqual(decisions["simulated_decisions"][0]["decision_type"], "require_manual_taxonomy_mapping")
        self.assertFalse(decisions["simulated_decisions"][0]["xbrl_eligible"])

    def test_simulate_choose_top_ambiguous_can_choose_top_but_remains_simulated(self):
        item = queue_item("ambiguous", workflow_status="needs_human_concept_choice", mapping_status="ambiguous_multiple_suggestions")
        decisions, _handoff, _eligibility, _policy = self.build(
            [item],
            policy=SimulationPolicy(simulate_choose_top_ambiguous=True),
        )
        decision = decisions["simulated_decisions"][0]
        self.assertEqual(decision["decision_type"], "approve_suggested_concept_simulated")
        self.assertTrue(decision["simulated_only"])
        self.assertFalse(decision["human_approved"])

    def test_needs_alias_or_metadata_enrichment_requests_enrichment(self):
        item = queue_item(
            "enrich",
            workflow_status="needs_alias_or_metadata_enrichment",
            mapping_status="low_confidence_suggestion",
            blockers=["missing_concept_metadata"],
        )
        decisions, _handoff, _eligibility, _policy = self.build([item])
        self.assertEqual(decisions["simulated_decisions"][0]["decision_type"], "request_concept_metadata_enrichment")
        self.assertFalse(decisions["simulated_decisions"][0]["xbrl_eligible"])

    def test_blocked_from_xbrl_remains_not_eligible(self):
        item = queue_item("blocked", workflow_status="blocked_from_xbrl", blockers=["concept_type_mismatch"])
        decisions, _handoff, _eligibility, _policy = self.build([item])
        self.assertEqual(decisions["simulated_decisions"][0]["decision_type"], "blocked_from_xbrl")
        self.assertFalse(decisions["simulated_decisions"][0]["xbrl_eligible"])

    def test_context_only_remains_not_eligible(self):
        item = queue_item("context", workflow_status="context_only", row_type="text_block")
        decisions, _handoff, _eligibility, _policy = self.build([item])
        self.assertEqual(decisions["simulated_decisions"][0]["decision_type"], "keep_for_context_only")
        self.assertFalse(decisions["simulated_decisions"][0]["xbrl_eligible"])

    def test_no_safe_item_remains_not_eligible(self):
        item = queue_item(
            "no-safe",
            workflow_status="needs_alias_or_metadata_enrichment",
            mapping_status="no_safe_suggestion",
            top_suggestion=None,
            suggestions=[],
            confidence_tier="none",
            score=0.0,
        )
        decisions, _handoff, _eligibility, _policy = self.build([item])
        self.assertFalse(decisions["simulated_decisions"][0]["xbrl_eligible"])

    def test_low_confidence_numeric_item_is_not_approved_in_strict_mode(self):
        item = queue_item(
            "low",
            workflow_status="ready_for_review_approval",
            mapping_status="low_confidence_suggestion",
            confidence_tier="low",
            score=0.42,
            top_suggestion=suggestion(score=0.42, confidence_tier="low"),
        )
        decisions, _handoff, _eligibility, _policy = self.build([item])
        self.assertEqual(decisions["simulated_decisions"][0]["decision_type"], "defer_mapping")
        self.assertFalse(decisions["simulated_decisions"][0]["xbrl_eligible"])

    def test_handoff_package_includes_only_xbrl_eligible_decisions(self):
        decisions, handoff, _eligibility, _policy = self.build(
            [queue_item("ready"), queue_item("blocked", workflow_status="blocked_from_xbrl")]
        )
        self.assertEqual(decisions["simulated_decision_count"], 2)
        self.assertEqual(len(handoff["handoff_items"]), 1)

    def test_handoff_package_contains_no_human_approved_true_items(self):
        _decisions, handoff, _eligibility, _policy = self.build([queue_item()])
        self.assertFalse(any(item["human_approved"] for item in handoff["handoff_items"]))

    def test_handoff_package_contains_no_deferred_or_blocked_decisions(self):
        _decisions, handoff, _eligibility, _policy = self.build(
            [queue_item("ready"), queue_item("blocked", workflow_status="blocked_from_xbrl")]
        )
        self.assertEqual({item["approval_status"] for item in handoff["handoff_items"]}, {"simulated_approved"})

    def test_eligibility_summary_counts_decisions(self):
        items = [
            queue_item("ready"),
            queue_item("defer", workflow_status="needs_confirmation", mapping_status="medium_confidence_suggestion"),
            queue_item("enrich", workflow_status="needs_alias_or_metadata_enrichment"),
            queue_item("blocked", workflow_status="blocked_from_xbrl"),
        ]
        _decisions, _handoff, eligibility, _policy = self.build(items)
        self.assertEqual(eligibility["simulated_approved_count"], 1)
        self.assertEqual(eligibility["deferred_count"], 1)
        self.assertEqual(eligibility["alias_enrichment_needed_count"], 1)
        self.assertEqual(eligibility["xbrl_blocked_count"], 3)

    def test_policy_report_documents_no_xbrl_generation(self):
        _decisions, _handoff, _eligibility, policy = self.build([queue_item()])
        self.assertIn("No XBRL generation", " ".join(policy["blocked_rules"]))

    def test_markdown_reports_render_sections(self):
        decisions, handoff, eligibility, policy = self.build([queue_item()])
        self.assertIn("## Summary", render_decisions_markdown(decisions))
        self.assertIn("## Summary", render_handoff_markdown(handoff))
        self.assertIn("## Why XBRL Generation Is Still Not Allowed", render_eligibility_markdown(eligibility))
        self.assertIn("## Strategy", render_policy_markdown(policy))

    def test_no_azure_di_call_is_required(self):
        with patch("services.azure_document_intelligence_provider.AzureDocumentIntelligenceProvider.analyze_pdf_path") as mocked:
            self.build([queue_item()])
        mocked.assert_not_called()

    def test_no_hugging_face_or_openai_call_is_required(self):
        decisions, handoff, eligibility, policy = self.build([queue_item()])
        for report in [decisions, handoff, eligibility, policy]:
            self.assertFalse(report["run_metadata"]["live_huggingface_calls_made"])
            self.assertFalse(report["run_metadata"]["live_openai_calls_made"])

    def test_no_db_is_required(self):
        decisions, handoff, eligibility, policy = self.build([queue_item()])
        for report in [decisions, handoff, eligibility, policy]:
            self.assertFalse(report["run_metadata"]["database_mutated"])

    def test_no_xbrl_or_arelle_path_is_invoked(self):
        decisions, handoff, eligibility, policy = self.build([queue_item()])
        for report in [decisions, handoff, eligibility, policy]:
            self.assertFalse(report["run_metadata"]["xbrl_generated"])
            self.assertFalse(report["run_metadata"]["arelle_validation_run"])

    def test_reference_xml_is_not_sent_to_any_model(self):
        decisions, handoff, eligibility, policy = self.build([queue_item()])
        for report in [decisions, handoff, eligibility, policy]:
            self.assertFalse(report["run_metadata"]["reference_xml_sent_to_model"])

    def test_no_production_mapping_approval_is_produced(self):
        decisions, handoff, eligibility, policy = self.build([queue_item()])
        for report in [decisions, handoff, eligibility, policy]:
            self.assertFalse(report["run_metadata"]["production_mapping_approval_produced"])
            self.assertFalse(report["run_metadata"]["final_mapping_approved"])

    def test_runner_writes_reports_without_live_or_db_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            queue_path = root / "queue.json"
            policy_path = root / "policy.json"
            contract_path = root / "contract.json"
            queue_path.write_text(json.dumps(review_queue([queue_item()])), encoding="utf-8")
            policy_path.write_text(json.dumps(review_policy()), encoding="utf-8")
            contract_path.write_text(json.dumps(handoff_contract()), encoding="utf-8")
            result = run_reviewed_mapping_simulation(
                review_queue_path=queue_path,
                review_policy_path=policy_path,
                handoff_contract_path=contract_path,
                output_prefix=root / "out",
            )
            self.assertTrue(result["paths"].decisions_json.exists())
            self.assertTrue(result["paths"].handoff_json.exists())
            self.assertFalse(result["decisions_report"]["run_metadata"]["database_mutated"])


if __name__ == "__main__":
    unittest.main()

