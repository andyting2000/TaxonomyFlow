import json
import unittest
from types import SimpleNamespace

from services.supervisor_mapping_orchestrator import (
    SupervisorOrchestrationConfig,
    build_supervisor_orchestration_plan,
)
from services.suggestion_actionability import (
    is_human_terminal,
    remapping_actionability,
    supervisor_review_actionability,
)


def _config():
    return SupervisorOrchestrationConfig(
        enabled=True,
        default_mode="manual",
        auto_eligibility=True,
        auto_review=False,
        auto_remap=False,
        admin_only=False,
        max_batch_size=10,
        max_remap_retries=1,
        min_risk="medium",
        max_concurrent_live_calls=2,
        confidence_threshold=0.85,
        per_row_timeout_seconds=10,
        review_execution_enabled=True,
        review_execution_admin_only=False,
        remap_execution_enabled=True,
        remap_execution_auto_run=False,
        remap_execution_admin_only=False,
        remap_execution_max_retries=1,
        allowed_user_ids="1",
    )


def _suggestion(
    suggestion_id,
    *,
    status="suggested",
    qname="ifrs-smes:Revenue",
    confidence=0.95,
    label="Revenue",
    statement_type="Statement of Comprehensive Income",
    reason="Candidate matches the row.",
):
    row = SimpleNamespace(
        extracted_label=label,
        statement_type=statement_type,
        confirmed_tag_id=None,
    )
    candidates = [
        {
            "template_field_id": "ifrs-smes:Revenue",
            "concept_qname": "ifrs-smes:Revenue",
            "statement_type": "Statement of Comprehensive Income",
            "confidence": 0.72,
            "reason": reason,
        }
    ]
    return SimpleNamespace(
        id=suggestion_id,
        extracted_data_item_id=f"row-{suggestion_id}",
        extracted_data_item=row,
        suggested_template_field_id=qname,
        confidence=confidence,
        reason=reason,
        ranked_candidates_json=json.dumps(candidates),
        diagnostic_json="{}",
        status=status,
    )


def _review(suggestion_id):
    return SimpleNamespace(
        id=f"review-{suggestion_id}",
        llm_mapping_suggestion_id=suggestion_id,
        review_status="completed",
        supervisor_decision="disagree",
        supervisor_risk_level="high",
        supervisor_recommended_action="request_better_candidate",
        supervisor_issues_json=json.dumps(
            [{"type": "candidate_not_supported", "description": "Use another candidate."}]
        ),
        error_type=None,
        is_latest=True,
        review_attempt=1,
        created_at="2026-07-25T00:00:00+00:00",
        updated_at="2026-07-25T00:00:00+00:00",
    )


def _revision(suggestion_id):
    return SimpleNamespace(
        id=f"revision-{suggestion_id}",
        parent_suggestion_id=suggestion_id,
        status="completed",
        revised_suggested_qname="ifrs-smes:Revenue",
        correction_attempt=1,
        is_latest=True,
        created_at="2026-07-25T00:01:00+00:00",
        updated_at="2026-07-25T00:01:00+00:00",
    )


class SupervisorQueueActionabilityTests(unittest.TestCase):
    def test_only_human_decisions_are_terminal(self):
        self.assertFalse(is_human_terminal("suggested"))
        self.assertFalse(is_human_terminal("rejected"))
        self.assertTrue(is_human_terminal("accepted"))
        self.assertTrue(is_human_terminal("ignored"))

    def test_rejected_mapper_abstention_can_be_review_executable(self):
        suggestion = _suggestion(
            "rejected-risk",
            status="rejected",
            qname=None,
            confidence=0.20,
        )
        action = supervisor_review_actionability(
            suggestion,
            policy_classification="eligible",
            latest_review=None,
            latest_revision=None,
            feature_enabled=True,
            authorized=True,
        )
        self.assertTrue(action.executable)
        self.assertTrue(action.batch_executable)
        self.assertIsNone(action.block_reason)

    def test_option_a_remapping_requires_concrete_original_suggestion(self):
        review = _review("row")
        suggested = _suggestion("suggested")
        rejected = _suggestion("rejected", status="rejected", qname=None)

        allowed = remapping_actionability(
            suggested,
            latest_review=review,
            feedback_eligible=True,
            feedback_reason="eligible_supervisor_disagreement",
            feature_enabled=True,
            authorized=True,
            auto_run=False,
            max_retries=1,
        )
        blocked = remapping_actionability(
            rejected,
            latest_review=review,
            feedback_eligible=True,
            feedback_reason="eligible_supervisor_disagreement",
            feature_enabled=True,
            authorized=True,
            auto_run=False,
            max_retries=1,
        )

        self.assertTrue(allowed.eligible)
        self.assertTrue(allowed.executable)
        self.assertEqual(allowed.state, "remapping_available")
        self.assertFalse(blocked.eligible)
        self.assertFalse(blocked.executable)
        self.assertEqual(blocked.block_reason, "concrete_suggestion_required")

    def test_plan_counts_equal_item_actionability_predicates(self):
        rejected_risk = _suggestion(
            "rejected-risk",
            status="rejected",
            qname=None,
            confidence=0.20,
            label="Other",
            statement_type="Statement of Cash Flows",
            reason="Concept family mismatch and statement family mismatch.",
        )
        reviewed_suggested = _suggestion("reviewed-suggested")
        reviewed_rejected = _suggestion(
            "reviewed-rejected",
            status="rejected",
            qname=None,
        )
        revised = _suggestion("revised")
        accepted = _suggestion("accepted", status="accepted")
        ignored = _suggestion("ignored", status="ignored")
        suggestions = [
            rejected_risk,
            reviewed_suggested,
            reviewed_rejected,
            revised,
            accepted,
            ignored,
        ]
        reviews = [
            _review("reviewed-suggested"),
            _review("reviewed-rejected"),
            _review("revised"),
        ]
        revisions = [_revision("revised")]

        plan = build_supervisor_orchestration_plan(
            job=SimpleNamespace(id=77),
            suggestions=suggestions,
            reviews=reviews,
            revisions=revisions,
            config=_config(),
            user_id=1,
        )
        items = {item["suggestion_id"]: item for item in plan["items"]}

        self.assertEqual(plan["total_suggestions"], 6)
        self.assertEqual(plan["policy_eligible_count"], 1)
        self.assertEqual(plan["review_executable_count"], 1)
        self.assertEqual(plan["batch_review_executable_count"], 1)
        self.assertEqual(plan["high_priority_count"], 1)
        self.assertEqual(plan["medium_priority_count"], 0)
        self.assertEqual(plan["already_reviewed_count"], 3)
        self.assertEqual(plan["not_eligible_count"], 2)
        self.assertEqual(plan["remapping_eligible_count"], 1)
        self.assertEqual(plan["remapping_executable_count"], 1)
        self.assertEqual(plan["revision_completed_count"], 1)

        self.assertTrue(items["rejected-risk"]["supervisor_review_executable"])
        self.assertTrue(items["rejected-risk"]["batch_review_executable"])
        self.assertFalse(items["rejected-risk"]["is_human_terminal"])
        self.assertTrue(items["reviewed-suggested"]["remapping_executable"])
        self.assertFalse(items["reviewed-rejected"]["remapping_eligible"])
        self.assertEqual(
            items["reviewed-rejected"]["remapping_action_block_reason"],
            "concrete_suggestion_required",
        )
        self.assertFalse(items["revised"]["remapping_executable"])
        self.assertEqual(
            items["revised"]["remapping_action_block_reason"],
            "correction_retry_limit_reached",
        )
        for suggestion_id in ("accepted", "ignored"):
            self.assertTrue(items[suggestion_id]["is_human_terminal"])
            self.assertFalse(items[suggestion_id]["supervisor_review_executable"])
            self.assertFalse(items[suggestion_id]["remapping_executable"])
            self.assertEqual(
                items[suggestion_id]["supervisor_action_block_reason"],
                "human_decision_is_terminal",
            )

        self.assertEqual(
            plan["policy_eligible_count"],
            sum(
                item["supervisor_eligibility"] == "eligible"
                and not item["is_human_terminal"]
                for item in plan["items"]
            ),
        )
        self.assertEqual(
            plan["review_executable_count"],
            sum(item["supervisor_review_executable"] for item in plan["items"]),
        )
        self.assertEqual(
            plan["batch_review_executable_count"],
            sum(item["batch_review_executable"] for item in plan["items"]),
        )
        self.assertEqual(
            plan["remapping_executable_count"],
            sum(item["remapping_executable"] for item in plan["items"]),
        )


if __name__ == "__main__":
    unittest.main()
