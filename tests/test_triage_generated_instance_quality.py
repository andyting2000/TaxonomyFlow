import unittest

from scripts.audit_generated_xbrl_instance import ExpectedFact
from scripts.triage_generated_instance_quality import (
    classify_duplicate_group,
    classify_signed_value,
    recommended_next_actions,
    summarize_classifications,
)


def expected_fact(
    item_id="item-1",
    label="Trade debtor",
    value="100.00",
    concept="ifrs-smes:TradeAndOtherCurrentReceivables",
):
    return ExpectedFact(
        item_id=item_id,
        page_id="page-1",
        page_number=1,
        extracted_label=label,
        extracted_value=value,
        statement_type="Statement of Financial Position",
        template_field_id=concept,
        confirmed_tag_id=None,
        concept_source="template_field_id",
        concept=concept,
        context_ref="asof_20241231_SeparateMember",
        unit_ref="MYR",
        value=value.replace(",", ""),
        value_year=2025,
        source_value_column="extracted_value",
        signed_value_suspicious=value.startswith("-"),
    )


class TriageGeneratedInstanceQualityTests(unittest.TestCase):
    def test_duplicate_group_classifies_distinct_rows_as_mapping_too_broad(self):
        facts = [
            expected_fact(item_id="a", label="Debtor A", value="100.00"),
            expected_fact(item_id="b", label="Debtor B", value="200.00"),
        ]
        generated = [{"value": "100.00"}, {"value": "200.00"}]

        self.assertEqual(classify_duplicate_group(facts, generated), "likely_mapping_too_broad")

    def test_duplicate_group_classifies_same_label_value_as_extraction_duplicate(self):
        facts = [
            expected_fact(item_id="a", label="Total profit", value="5032604.00"),
            expected_fact(item_id="b", label="Total profit", value="5032604.00"),
        ]
        generated = [{"value": "5032604.00"}, {"value": "5032604.00"}]

        self.assertEqual(classify_duplicate_group(facts, generated), "likely_extraction_duplicate")

    def test_duplicate_group_classifies_extra_generated_fact_as_generator_duplicate(self):
        facts = [expected_fact(item_id="a", label="Cash", value="100.00")]
        generated = [{"value": "100.00"}, {"value": "100.00"}]

        self.assertEqual(classify_duplicate_group(facts, generated), "likely_generator_duplicate")

    def test_signed_value_classifies_positive_nature_negative_without_label_cue_as_wrong(self):
        fact = expected_fact(label="Cash at bank", value="-100.00", concept="ssmt:CashAndBankBalances")

        classification, _ = classify_signed_value(fact)

        self.assertEqual(classification, "likely_wrong_sign")

    def test_signed_value_classifies_positive_nature_with_loss_cue_as_policy_needed(self):
        fact = expected_fact(label="P&L 2007", value="-100.00", concept="ssmt-mpers:CurrentBiologicalAssets")

        classification, _ = classify_signed_value(fact)

        self.assertEqual(classification, "sign_policy_needed")

    def test_recommended_next_actions_reflect_quality_findings(self):
        summary = summarize_classifications(
            duplicate_groups=[{"classification": "likely_mapping_too_broad"}],
            signed_values=[{"sign_classification": "sign_policy_needed"}],
            identical_duplicates=[{"classification": "likely_extraction_duplicate"}],
        )

        self.assertEqual(
            recommended_next_actions(summary),
            [
                "A. mapping fix",
                "B. extraction duplicate handling",
                "C. sign policy/sign normalization",
                "E. regression pack expansion",
            ],
        )


if __name__ == "__main__":
    unittest.main()
