import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import plan_receivables_mapping_guardrail as planner


class ReceivablesMappingGuardrailPlanTests(unittest.TestCase):
    def test_explicit_trade_receivables_label_is_summary(self):
        classification, reason = planner.classify_receivable_label("Trade and other receivables")

        self.assertEqual(classification, "likely_valid_receivable_summary")
        self.assertIn("summary", reason)

    def test_company_like_label_is_detail_needing_policy(self):
        classification, reason = planner.classify_receivable_label("ACME SERVICES SDN BHD")

        self.assertEqual(
            classification,
            "likely_valid_receivable_detail_but_needs_dimension_or_aggregation_policy",
        )
        self.assertIn("aggregation", reason)

    def test_other_debtor_label_is_summary_evidence(self):
        classification, _ = planner.classify_receivable_label("OTHER DEBTOR - IH(I.T)")

        self.assertEqual(classification, "likely_valid_receivable_summary")

    def test_non_receivable_label_is_not_receivable(self):
        classification, reason = planner.classify_receivable_label("TRADE PAYABLES")

        self.assertEqual(classification, "likely_not_receivable")
        self.assertIn("non-receivable", reason)

    def test_weak_label_is_mapping_too_broad(self):
        classification, _ = planner.classify_receivable_label("BALANCE B/F")

        self.assertEqual(classification, "likely_mapping_too_broad")

    def test_proposed_action_does_not_invent_replacement_concept(self):
        action = planner.proposed_action_for_classification(
            "likely_valid_receivable_detail_but_needs_dimension_or_aggregation_policy"
        )

        self.assertFalse(action["assign_replacement_concept"])
        self.assertIsNone(action["replacement_concept_id"])
        self.assertTrue(action["manual_review_required"])
        self.assertTrue(action["preserve_extracted_label"])
        self.assertTrue(action["preserve_extracted_value"])

    def test_build_evidence_rows_filters_target_concept_only(self):
        facts = [
            SimpleNamespace(
                item_id="a",
                page_id="p1",
                page_number=1,
                extracted_label="ACME SDN BHD",
                extracted_value="100.00",
                template_field_id=planner.TARGET_CONCEPT,
                concept=planner.TARGET_CONCEPT,
                statement_type="Statement of Financial Position",
                confirmed_tag_id=None,
                context_ref="asof_20241231_SeparateMember",
                unit_ref="MYR",
                value="100.00",
            ),
            SimpleNamespace(
                item_id="b",
                page_id="p1",
                page_number=1,
                extracted_label="Cash",
                extracted_value="50.00",
                template_field_id="ifrs-smes:CashAndCashEquivalents",
                concept="ifrs-smes:CashAndCashEquivalents",
                statement_type="Statement of Financial Position",
                confirmed_tag_id=None,
                context_ref="asof_20241231_SeparateMember",
                unit_ref="MYR",
                value="50.00",
            ),
        ]
        audit_report = {
            "generated_facts": {
                "duplicate_concept_context_unit_facts": {
                    "groups": [
                        {
                            "concept": planner.TARGET_CONCEPT,
                            "contextRef": "asof_20241231_SeparateMember",
                            "unitRef": "MYR",
                            "count": 2,
                        }
                    ]
                }
            }
        }

        with patch.object(planner, "_concept_label", return_value="Trade and other current receivables"):
            rows = planner.build_evidence_rows(facts, audit_report)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].item_id, "a")
        self.assertEqual(rows[0].duplicate_group_membership["concept"], planner.TARGET_CONCEPT)

    def test_next_scope_recommends_guardrail_for_detail_rows(self):
        rows = [
            SimpleNamespace(
                classification="likely_valid_receivable_detail_but_needs_dimension_or_aggregation_policy"
            )
        ]

        recommendation = planner.decide_next_feature_scope(rows)

        self.assertTrue(recommendation["code_changes_justified_next"])
        self.assertTrue(recommendation["block_automatic_detail_row_mapping"])
        self.assertTrue(recommendation["manual_confirmation_for_company_like_labels"])
        self.assertFalse(recommendation["invent_replacement_concepts"])


if __name__ == "__main__":
    unittest.main()
