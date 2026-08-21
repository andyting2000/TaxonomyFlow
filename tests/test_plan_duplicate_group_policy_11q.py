import unittest
from types import SimpleNamespace

from scripts import plan_duplicate_group_policy_11q as planner


def row(label, value="100.00", concept="ifrs-smes:Assets"):
    return planner.DuplicateSourceRow(
        item_id=f"id-{label}",
        page_id="page-1",
        page_number=1,
        extracted_label=label,
        extracted_value=value,
        generated_value=value.replace(",", ""),
        statement_type="Statement of Financial Position",
        template_field_id=concept,
        confirmed_tag_id=None,
        contextRef="asof_20241231_SeparateMember",
        unitRef="MYR",
        value_year=2025,
        source_value_column="extracted_value",
    )


class DuplicateGroupPolicy11QTests(unittest.TestCase):
    def test_classifies_repeated_detail_rows_as_aggregation_needed_for_receivables(self):
        classification, reason, handling, handling_reason = planner.classify_duplicate_group(
            concept="ifrs-smes:TradeAndOtherCurrentReceivables",
            concept_label_value="Trade and other current receivables",
            source_rows=[
                row("OTHER DEBTOR - IH(I.T)", "100.00", "ifrs-smes:TradeAndOtherCurrentReceivables"),
                row("OTHER DEBTOR - RH", "200.00", "ifrs-smes:TradeAndOtherCurrentReceivables"),
            ],
            generated_fact_count=2,
        )

        self.assertEqual(classification, "likely_detail_rows_need_aggregation_policy")
        self.assertIn("receivable/debtor detail", reason)
        self.assertEqual(handling, "aggregate_before_generation_later")
        self.assertIn("summed", handling_reason)

    def test_classifies_possible_valid_multi_fact_group(self):
        classification, _, handling, _ = planner.classify_duplicate_group(
            concept="ifrs-smes:Assets",
            concept_label_value="Assets",
            source_rows=[row("Assets", "100.00"), row("Assets", "100.00")],
            generated_fact_count=2,
        )

        self.assertEqual(classification, "likely_valid_multi_fact")
        self.assertEqual(handling, "keep_as_is")

    def test_summary_duplicate_recommends_dedup_policy(self):
        classification, _, handling, _ = planner.classify_duplicate_group(
            concept="ifrs-smes:Assets",
            concept_label_value="Assets",
            source_rows=[row("Assets", "100.00"), row("ASSETS", "200.00")],
            generated_fact_count=2,
        )

        self.assertEqual(classification, "likely_summary_duplicate_needs_dedup_policy")
        self.assertEqual(handling, "deduplicate_same_context_summary_later")

    def test_dimension_needed_for_non_receivable_detail_rows(self):
        classification, _, handling, _ = planner.classify_duplicate_group(
            concept="ifrs-smes:OtherAssets",
            concept_label_value="Other assets",
            source_rows=[row("ACME SDN BHD"), row("BETA SDN BHD", "200.00")],
            generated_fact_count=2,
        )

        self.assertEqual(classification, "likely_detail_rows_need_dimension_policy")
        self.assertEqual(handling, "dimension_model_required_later")

    def test_manual_review_when_no_traceable_rows(self):
        classification, reason, handling, _ = planner.classify_duplicate_group(
            concept="ifrs-smes:Assets",
            concept_label_value="Assets",
            source_rows=[],
            generated_fact_count=2,
        )

        self.assertEqual(classification, "not_enough_information")
        self.assertEqual(handling, "needs_more_taxonomy_research")
        self.assertIn("No traceable", reason)

    def test_no_replacement_concept_recommendation_in_group_plan(self):
        audit_report = {
            "generated_facts": {
                "duplicate_concept_context_unit_facts": {
                    "groups": [
                        {
                            "concept": "ifrs-smes:TradeAndOtherCurrentReceivables",
                            "contextRef": "asof_20241231_SeparateMember",
                            "unitRef": "MYR",
                            "count": 2,
                        }
                    ]
                }
            }
        }
        expected = [
            SimpleNamespace(
                item_id="a",
                page_id="p",
                page_number=1,
                extracted_label="OTHER DEBTOR - A",
                extracted_value="100.00",
                statement_type="Statement of Financial Position",
                template_field_id="ifrs-smes:TradeAndOtherCurrentReceivables",
                confirmed_tag_id=None,
                concept="ifrs-smes:TradeAndOtherCurrentReceivables",
                context_ref="asof_20241231_SeparateMember",
                unit_ref="MYR",
                value="100.00",
                value_year=2025,
                source_value_column="extracted_value",
            ),
            SimpleNamespace(
                item_id="b",
                page_id="p",
                page_number=1,
                extracted_label="OTHER DEBTOR - B",
                extracted_value="200.00",
                statement_type="Statement of Financial Position",
                template_field_id="ifrs-smes:TradeAndOtherCurrentReceivables",
                confirmed_tag_id=None,
                concept="ifrs-smes:TradeAndOtherCurrentReceivables",
                context_ref="asof_20241231_SeparateMember",
                unit_ref="MYR",
                value="200.00",
                value_year=2025,
                source_value_column="extracted_value",
            ),
        ]
        generated = [
            {
                "concept": "ifrs-smes:TradeAndOtherCurrentReceivables",
                "contextRef": "asof_20241231_SeparateMember",
                "unitRef": "MYR",
                "value": "100.00",
            },
            {
                "concept": "ifrs-smes:TradeAndOtherCurrentReceivables",
                "contextRef": "asof_20241231_SeparateMember",
                "unitRef": "MYR",
                "value": "200.00",
            },
        ]

        plans = planner.build_group_plans(audit_report, expected, generated)

        self.assertEqual(len(plans), 1)
        self.assertFalse(plans[0].replacement_concept_recommended)
        self.assertTrue(plans[0].sign_policy_deferred)

    def test_script_has_no_apply_or_mutation_path(self):
        parser = planner.parse_args
        self.assertFalse(hasattr(planner, "apply"))
        self.assertFalse(hasattr(planner, "update_rows"))
        self.assertTrue(callable(parser))


if __name__ == "__main__":
    unittest.main()
