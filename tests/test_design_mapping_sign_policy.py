import unittest

from scripts.design_mapping_sign_policy import (
    build_mapping_breadth_problems,
    build_sign_policy,
    first_safe_mapping_candidates,
    recommend_mapping_treatment,
    recommend_sign_policy,
)


class DesignMappingSignPolicyTests(unittest.TestCase):
    def test_biological_asset_without_label_evidence_is_blocked(self):
        treatment = recommend_mapping_treatment(
            "ssmt-mpers:CurrentBiologicalAssets",
            ["SHARE CAPITAL", "INFOHOUSE (I.T) SDN BHD", "P&L 2001"],
            [{"classification": "likely_mapping_too_broad"}],
        )

        self.assertEqual(treatment["recommended_treatment"], "blocked_from_auto_mapping")
        self.assertIn("template mapping data", treatment["implementation_owner"])

    def test_trade_receivables_requires_high_confidence_or_manual_confirmation(self):
        treatment = recommend_mapping_treatment(
            "ifrs-smes:TradeAndOtherCurrentReceivables",
            ["Customer A", "Customer B"],
            [{"classification": "likely_mapping_too_broad"}],
        )

        self.assertEqual(
            treatment["recommended_treatment"],
            "allowed_only_with_high_confidence_or_manual_confirmation",
        )

    def test_mapping_breadth_groups_source_rows_by_concept(self):
        triage = {
            "duplicate_concept_context_unit_groups": [
                {
                    "concept": "ssmt-mpers:CurrentBiologicalAssets",
                    "generated_fact_count": 2,
                    "classification": "likely_mapping_too_broad",
                    "source_rows": [
                        {
                            "item_id": "a",
                            "label": "SHARE CAPITAL",
                            "source_value": "100.00",
                            "generated_value": "100.00",
                            "template_field_id": "ssmt-mpers:CurrentBiologicalAssets",
                            "confirmed_tag_id": None,
                            "statement_type": "Statement of Financial Position",
                            "page_number": 2,
                        },
                        {
                            "item_id": "b",
                            "label": "P&L 2001",
                            "source_value": "-50.00",
                            "generated_value": "-50.00",
                            "template_field_id": "ssmt-mpers:CurrentBiologicalAssets",
                            "confirmed_tag_id": None,
                            "statement_type": "Statement of Financial Position",
                            "page_number": 2,
                        },
                    ],
                }
            ],
            "identical_duplicate_fact_keys": [],
        }

        problems = build_mapping_breadth_problems(triage)

        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["concept"], "ssmt-mpers:CurrentBiologicalAssets")
        self.assertEqual(problems[0]["source_row_count"], 2)
        self.assertEqual(problems[0]["recommended_treatment"], "blocked_from_auto_mapping")

    def test_first_safe_mapping_candidates_prioritizes_biological_asset_guardrail(self):
        problems = [
            {
                "concept": "ifrs-smes:Assets",
                "recommended_treatment": "allowed_only_with_high_confidence_or_manual_confirmation",
                "treatment_reason": "aggregate",
                "source_labels_currently_mapped": ["Assets"],
            },
            {
                "concept": "ssmt-mpers:CurrentBiologicalAssets",
                "recommended_treatment": "blocked_from_auto_mapping",
                "treatment_reason": "no biological evidence",
                "source_labels_currently_mapped": ["SHARE CAPITAL"],
            },
        ]

        candidates = first_safe_mapping_candidates(problems)

        self.assertEqual(candidates[0]["concept"], "ssmt-mpers:CurrentBiologicalAssets")

    def test_sign_policy_preserves_likely_correct_negative(self):
        row = {
            "sign_classification": "likely_correct_sign",
            "concept": "ifrs-smes:Liabilities",
            "label": "Liabilities",
        }

        category, _, should_not_auto = recommend_sign_policy(row)

        self.assertEqual(category, "preserve_negative")
        self.assertIsNone(should_not_auto)

    def test_sign_policy_wrong_sign_is_conversion_candidate_with_guard(self):
        row = {
            "sign_classification": "likely_wrong_sign",
            "concept": "ifrs-smes:Assets",
            "label": "Assets",
        }

        category, _, should_not_auto = recommend_sign_policy(row)

        self.assertEqual(category, "convert_to_positive")
        self.assertIn("Mapping confirmation", should_not_auto)

    def test_sign_policy_for_biological_asset_conflict_requires_manual_review(self):
        row = {
            "sign_classification": "sign_policy_needed",
            "concept": "ssmt-mpers:CurrentBiologicalAssets",
            "label": "P&L 2001",
        }

        category, _, should_not_auto = recommend_sign_policy(row)

        self.assertEqual(category, "manual_review_required")
        self.assertIn("biological-asset", should_not_auto)

    def test_build_sign_policy_counts_categories(self):
        triage = {
            "suspicious_signed_values": [
                {"item_id": "a", "sign_classification": "likely_correct_sign"},
                {"item_id": "b", "sign_classification": "likely_wrong_sign"},
                {
                    "item_id": "c",
                    "sign_classification": "sign_policy_needed",
                    "concept": "ssmt-mpers:CurrentBiologicalAssets",
                    "label": "P&L 2001",
                },
            ]
        }

        policy = build_sign_policy(triage)

        self.assertEqual(
            policy["category_counts"],
            {
                "convert_to_positive": 1,
                "manual_review_required": 1,
                "preserve_negative": 1,
            },
        )


if __name__ == "__main__":
    unittest.main()
