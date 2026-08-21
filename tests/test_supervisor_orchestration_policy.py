import inspect
import json
import unittest
from datetime import datetime
from types import SimpleNamespace

from services import supervisor_orchestration_policy as policy_module
from services.supervisor_orchestration_policy import (
    SupervisorEligibilityPolicyConfig,
    assess_supervisor_risk,
    derive_orchestration_state,
    evaluate_remapping_eligibility,
    evaluate_supervisor_eligibility,
    is_valid_state_transition,
)


def row(label="Cash and cash equivalents", statement="Statement of Financial Position"):
    return SimpleNamespace(extracted_label=label, statement_type=statement)


def suggestion(
    *,
    status="suggested",
    confidence=0.97,
    qname="ifrs-smes:CashAndCashEquivalents",
    row_value=None,
    candidate_statement="Statement of Financial Position",
    diagnostic=None,
    candidates=None,
):
    item = row_value or row()
    ranked = candidates
    if ranked is None:
        ranked = [
            {
                "template_field_id": qname,
                "statement_type": candidate_statement,
                "confidence": confidence,
                "reason": "exact alias match",
            }
        ]
    return SimpleNamespace(
        id="suggestion-1",
        status=status,
        confidence=confidence,
        suggested_template_field_id=qname,
        extracted_data_item=item,
        reason="local mapping evidence",
        ranked_candidates_json=json.dumps(ranked),
        diagnostic_json=json.dumps(diagnostic or {}),
    )


def review(
    *,
    decision="needs_human_review",
    risk="medium",
    action="keep_for_human_review",
    status="completed",
    issues=None,
):
    return SimpleNamespace(
        id="review-1",
        review_status=status,
        supervisor_decision=decision,
        supervisor_risk_level=risk,
        supervisor_recommended_action=action,
        supervisor_issues_json=json.dumps(
            issues
            if issues is not None
            else [{"type": "statement_family_mismatch"}]
        ),
        review_attempt=1,
        is_latest=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


class SupervisorOrchestrationPolicyTests(unittest.TestCase):
    def test_statement_family_mismatch_is_eligible(self):
        item = row(statement="Statement of Cash Flows")
        decision = evaluate_supervisor_eligibility(
            suggestion(row_value=item, candidate_statement="Statement of Financial Position"),
            row=item,
        )
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.priority, "medium")
        self.assertIn("statement_family_mismatch", decision.eligibility_reasons)

    def test_broad_substitute_is_eligible(self):
        decision = evaluate_supervisor_eligibility(
            suggestion(
                qname=(
                    "ifrs-smes:"
                    "OtherInflowsOutflowsOfCashClassifiedAsInvestingActivities"
                ),
                diagnostic={"issue_type": "broad_substitute"},
                candidates=[
                    {
                        "template_field_id": (
                            "ifrs-smes:"
                            "OtherInflowsOutflowsOfCashClassifiedAsInvestingActivities"
                        ),
                        "confidence": 0.65,
                        "reason": "broad substitute",
                    },
                    {
                        "template_field_id": (
                            "ifrs-smes:"
                            "CashFlowsFromUsedInInvestingActivities"
                        ),
                        "confidence": 0.60,
                        "reason": "closer aggregate alternative",
                    },
                ],
            ),
        )
        self.assertTrue(decision.eligible)
        self.assertIn(
            "broad_substitute_with_concrete_alternative",
            decision.eligibility_reasons,
        )

    def test_low_confidence_confirmation_row_is_eligible(self):
        decision = evaluate_supervisor_eligibility(
            suggestion(
                confidence=0.62,
                diagnostic={"requires_confirmation": True},
            ),
        )
        self.assertTrue(decision.eligible)
        self.assertIn("mapper_confidence_below_threshold", decision.eligibility_reasons)
        self.assertIn("requires_confirmation", decision.eligibility_reasons)
        self.assertEqual(decision.priority, "medium")

    def test_requires_confirmation_alone_is_not_eligible(self):
        decision = evaluate_supervisor_eligibility(
            suggestion(diagnostic={"requires_confirmation": True}),
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.eligibility_score, 1)
        self.assertIn(
            "weak_signals_do_not_independently_enqueue",
            decision.blocking_reasons,
        )

    def test_medium_confidence_alone_is_not_eligible(self):
        decision = evaluate_supervisor_eligibility(
            suggestion(confidence=0.80),
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(
            decision.weak_signals,
            ("mapper_confidence_below_threshold",),
        )

    def test_confidence_only_safe_flag_withholding_is_not_eligible(self):
        confidence_only_review = review(
            decision="agree",
            risk="low",
            action="accept",
            issues=[
                {
                    "type": "other",
                    "description": (
                        "Safe flag withheld by guardrail: mapper confidence "
                        "was below the safe-accept threshold."
                    ),
                }
            ],
        )
        decision = evaluate_supervisor_eligibility(
            suggestion(confidence=0.86),
            reviews=[confidence_only_review],
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.classification, "already_reviewed")
        self.assertEqual(decision.eligibility_score, 0)
        self.assertIn(
            "safe_flag_withheld_due_confidence",
            decision.weak_signals,
        )

    def test_concept_family_mismatch_is_eligible(self):
        decision = evaluate_supervisor_eligibility(
            suggestion(diagnostic={"issue_type": "concept_family_mismatch"}),
        )
        self.assertTrue(decision.eligible)
        self.assertIn(
            "concept_family_mismatch",
            decision.strong_signals,
        )

    def test_no_safe_revised_mapping_is_high_risk_but_not_requeued(self):
        revision = SimpleNamespace(
            id="revision-1",
            status="completed",
            revised_suggested_qname=None,
        )
        risk = assess_supervisor_risk(
            suggestion(),
            row(),
            revisions=[revision],
        )
        decision = evaluate_supervisor_eligibility(
            suggestion(),
            revisions=[revision],
        )
        self.assertTrue(risk.qualifies)
        self.assertEqual(risk.priority, "high")
        self.assertIn("no_safe_revised_mapping", risk.strong_signals)
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.classification, "already_reviewed")

    def test_two_weak_signals_may_create_medium_eligibility(self):
        decision = evaluate_supervisor_eligibility(
            suggestion(
                confidence=0.80,
                diagnostic={"requires_confirmation": True},
            ),
        )
        self.assertTrue(decision.eligible)
        self.assertEqual(decision.priority, "medium")
        self.assertEqual(decision.eligibility_score, 2)

    def test_weak_signals_without_selected_candidate_do_not_enqueue(self):
        decision = evaluate_supervisor_eligibility(
            suggestion(
                status="rejected",
                confidence=0.30,
                qname=None,
                diagnostic={"requires_confirmation": True},
                candidates=[],
            ),
        )
        self.assertFalse(decision.eligible)
        self.assertIn(
            "mapping_no_safe_candidate",
            decision.eligibility_reasons,
        )

    def test_high_confidence_exact_match_without_issues_is_not_eligible(self):
        decision = evaluate_supervisor_eligibility(suggestion())
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.classification, "not_eligible")
        self.assertEqual(
            decision.blocking_reasons,
            ("high_confidence_no_local_risk_issue",),
        )

    def test_accepted_and_human_rejected_suggestions_are_terminal(self):
        accepted = evaluate_supervisor_eligibility(suggestion(status="accepted"))
        rejected = evaluate_supervisor_eligibility(suggestion(status="ignored"))
        self.assertEqual(accepted.classification, "terminal")
        self.assertEqual(rejected.classification, "terminal")
        self.assertIn("human_accepted", accepted.blocking_reasons)
        self.assertIn("human_rejected", rejected.blocking_reasons)

    def test_completed_low_risk_agree_review_is_not_requeued(self):
        decision = evaluate_supervisor_eligibility(
            suggestion(),
            reviews=[review(decision="agree", risk="low", action="accept", issues=[])],
        )
        self.assertFalse(decision.eligible)
        self.assertEqual(decision.classification, "already_reviewed")
        self.assertEqual(decision.recommended_manual_action, "no_action")

    def test_correction_retry_exhausted_blocks_remapping(self):
        revision = SimpleNamespace(
            id="revision-1",
            status="completed",
            revised_suggested_qname="ifrs-smes:Revenue",
        )
        result = evaluate_remapping_eligibility(
            suggestion(),
            reviews=[review()],
            revisions=[revision],
            max_retries=1,
        )
        self.assertFalse(result["available"])
        self.assertEqual(result["state"], "remapping_retry_exhausted")

    def test_state_model_blocks_automatic_or_unsafe_transitions(self):
        self.assertFalse(
            is_valid_state_transition("supervisor_completed", "remapping_running")
        )
        self.assertFalse(
            is_valid_state_transition("revision_created", "human_accepted")
        )
        self.assertTrue(
            is_valid_state_transition(
                "human_review_pending",
                "human_accepted",
                explicit_human_action=True,
            )
        )
        self.assertFalse(
            is_valid_state_transition("human_review_pending", "confirmed_tag_id")
        )

    def test_derived_state_keeps_human_review_pending(self):
        candidate = suggestion()
        decision = evaluate_supervisor_eligibility(candidate)
        state = derive_orchestration_state(
            candidate,
            supervisor_decision=decision,
        )
        self.assertEqual(state["human_workflow"], "human_review_pending")
        self.assertEqual(state["remapping_execution"], "remapping_not_started")

    def test_policy_has_no_external_call_dependency(self):
        source = inspect.getsource(policy_module)
        self.assertNotIn("SupervisorLLMClient", source)
        self.assertNotIn("HuggingFaceQwenMappingClient", source)
        self.assertNotIn("run_supervisor_review_for_suggestion", source)
        self.assertNotIn("run_supervisor_guided_mapping_correction", source)

    def test_explicit_human_request_forces_safe_nonterminal_eligibility(self):
        default_decision = evaluate_supervisor_eligibility(
            suggestion(),
            explicit_human_request=True,
            config=SupervisorEligibilityPolicyConfig(min_priority="medium"),
        )
        self.assertTrue(default_decision.eligible)
        self.assertIn(
            "explicit_human_request",
            default_decision.eligibility_reasons,
        )

        high_threshold_decision = evaluate_supervisor_eligibility(
            suggestion(),
            explicit_human_request=True,
            config=SupervisorEligibilityPolicyConfig(min_priority="high"),
        )
        self.assertTrue(high_threshold_decision.eligible)
        self.assertIn(
            "explicit_human_request",
            high_threshold_decision.strong_signals,
        )

    def test_five_revision_anchor_shapes_remain_risk_eligible(self):
        tax_row = row(
            label="Tax expenses for the year",
            statement="Statement of Cash Flows",
        )
        equity_row = row(
            label="Share capital",
            statement="Statement of Changes in Equity",
        )
        profit_row = row(
            label="Profit / (Loss) before taxation",
            statement="Statement of Cash Flows",
        )
        investing_row = row(
            label="Cash flows from investing activities",
            statement="Statement of Cash Flows (Direct Method)",
        )
        investing_candidates = [
            {
                "template_field_id": (
                    "ifrs-smes:"
                    "OtherInflowsOutflowsOfCashClassifiedAsInvestingActivities"
                ),
                "confidence": 0.65,
                "reason": "specific investing inflows/outflows",
            },
            {
                "template_field_id": (
                    "ifrs-smes:CashFlowsFromUsedInInvestingActivities"
                ),
                "confidence": 0.60,
                "reason": "aggregate investing cash flows",
            },
        ]
        anchors = [
            suggestion(
                row_value=tax_row,
                qname="ifrs-smes:IncomeTaxExpenseContinuingOperations",
            ),
            suggestion(
                row_value=investing_row,
                qname=(
                    "ifrs-smes:"
                    "OtherInflowsOutflowsOfCashClassifiedAsInvestingActivities"
                ),
                confidence=0.65,
                candidates=investing_candidates,
            ),
            suggestion(
                row_value=tax_row,
                qname="ifrs-smes:IncomeTaxExpenseContinuingOperations",
            ),
            suggestion(
                row_value=equity_row,
                qname="ifrs-smes:IssuedCapital",
                diagnostic={"issue_type": "statement_family_mismatch"},
            ),
            suggestion(
                row_value=profit_row,
                qname="ifrs-smes:ProfitLossBeforeTax",
            ),
        ]
        decisions = [
            evaluate_supervisor_eligibility(
                anchor,
                row=anchor.extracted_data_item,
            )
            for anchor in anchors
        ]
        self.assertTrue(all(decision.eligible for decision in decisions))
        self.assertTrue(
            all(decision.strong_signals for decision in decisions)
        )


if __name__ == "__main__":
    unittest.main()
