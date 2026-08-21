import unittest

from services.extraction_v2_quality_analyzer import (
    analyze_candidate_quality_reports,
    detect_candidate_issues,
    is_date_only_label,
    is_year_only_label,
    parse_amount,
    render_mapping_readiness_markdown,
)


def candidate(**overrides):
    base = {
        "case_id": "case-a",
        "source_pdf": "case-a.pdf",
        "page_number": 1,
        "extraction_method": "huggingface_vision_fallback",
        "row_type": "numeric_fact",
        "statement_section": "Statement of Financial Position",
        "label": "Cash and bank balances",
        "value": "1,234",
        "previous_value": "",
        "current_year": 2024,
        "prior_year": 2023,
        "text": "",
        "source_snippet": "Cash and bank balances 1,234",
    }
    base.update(overrides)
    return base


def report_with_candidates(candidates):
    return {
        "run_metadata": {"database_mutated": False},
        "case_reports": [
            {
                "case_id": "case-a",
                "candidate_count": len(candidates),
                "candidates": candidates,
            }
        ],
    }


def reference_report():
    return {
        "run_metadata": {"database_mutated": False},
        "case_reports": [
            {
                "case_id": "case-a",
                "total_facts": 3,
                "numeric_fact_count": 2,
                "text_block_count": 1,
                "facts": [
                    {"qname": "ifrs-smes:CashAndBankBalances", "local_name": "CashAndBankBalances", "is_numeric": True},
                    {"qname": "ifrs-smes:Revenue", "local_name": "Revenue", "is_numeric": True},
                    {"qname": "ssmt:DisclosureOfAccountingPolicies", "local_name": "DisclosureOfAccountingPolicies", "is_text_block": True},
                ],
            }
        ],
    }


def comparison_report():
    return {
        "aggregate_metrics": {
            "missing_text_block_cases": [],
            "rough_label_concept_overlap_count": 1,
        },
        "per_case": [
            {
                "case_id": "case-a",
                "reference_total_facts": 3,
                "reference_numeric_facts": 2,
                "reference_text_blocks": 1,
            }
        ],
        "top_reference_concepts_not_represented_in_v2": [
            {"concept": "ifrs-smes:Revenue", "count": 1},
            {"concept": "ssmt:DisclosureOfAccountingPolicies", "count": 1},
        ],
        "top_v2_candidates_not_found_in_reference": [],
    }


class ExtractionV2CandidateQualityTests(unittest.TestCase):
    def issue_codes(self, item):
        return {issue["code"] for issue in detect_candidate_issues(item)}

    def analyze(self, candidates):
        return analyze_candidate_quality_reports(
            v2_report=report_with_candidates(candidates),
            comparison_report=comparison_report(),
            reference_report=reference_report(),
            input_paths={"v2_report": "memory"},
        )

    def test_date_only_labels_are_flagged_as_label_pollution(self):
        self.assertTrue(is_date_only_label("As at 31/12/2023"))
        self.assertIn("date_only_label", self.issue_codes(candidate(label="As at 31/12/2023")))

    def test_pure_year_labels_are_flagged_as_label_pollution(self):
        self.assertTrue(is_year_only_label("2024"))
        self.assertIn("year_only_label", self.issue_codes(candidate(label="2024")))

    def test_enumeration_only_labels_are_flagged_as_weak_labels(self):
        self.assertIn("enumeration_only_label", self.issue_codes(candidate(label="(c)")))

    def test_heading_like_rows_classified_as_numeric_facts_are_flagged(self):
        issues = self.issue_codes(candidate(label="Statement of Financial Position", value="123"))
        self.assertIn("heading_like_numeric_fact", issues)

    def test_numeric_candidate_with_non_numeric_value_is_flagged(self):
        self.assertIn("non_numeric_value", self.issue_codes(candidate(value="not available")))

    def test_current_prior_year_like_values_are_not_treated_as_amounts(self):
        self.assertIsNone(parse_amount("2024"))
        self.assertIn("date_or_year_value_as_amount", self.issue_codes(candidate(value="2024")))

    def test_duplicate_label_with_conflicting_values_is_flagged(self):
        quality, _readiness = self.analyze(
            [
                candidate(label="Revenue", value="100"),
                candidate(label="Revenue", value="200"),
            ]
        )
        self.assertGreater(quality["quality_issue_counts"].get("duplicate_label_conflicting_values", 0), 0)

    def test_duplicate_label_value_on_same_page_is_flagged(self):
        quality, _readiness = self.analyze(
            [
                candidate(label="Revenue", value="100"),
                candidate(label="Revenue", value="100"),
            ]
        )
        self.assertGreater(quality["quality_issue_counts"].get("exact_duplicate_same_page", 0), 0)

    def test_short_text_block_is_flagged(self):
        text_block = candidate(row_type="text_block", label="Policy", value="", text="Revenue policy")
        self.assertIn("short_text_block", self.issue_codes(text_block))

    def test_repeated_text_block_is_flagged(self):
        repeated = candidate(
            row_type="text_block",
            label="Accounting policy",
            value="",
            text="Revenue is recognised when control of goods is transferred to the customer.",
        )
        quality, _readiness = self.analyze([repeated, dict(repeated)])
        self.assertGreater(quality["quality_issue_counts"].get("exact_duplicate_same_page", 0), 0)

    def test_missing_statement_section_lowers_readiness(self):
        quality, _readiness = self.analyze([candidate(statement_section=None)])
        self.assertIn("missing_statement_section", quality["quality_issue_counts"])
        self.assertNotEqual(quality["aggregate_candidate_counts"]["readiness_distribution"].get("high", 0), 1)

    def test_clean_numeric_candidate_with_strong_label_and_section_is_high_readiness(self):
        quality, _readiness = self.analyze([candidate(label="Cash and bank balances", value="1234")])
        self.assertEqual(quality["aggregate_candidate_counts"]["readiness_distribution"].get("high"), 1)

    def test_weak_label_numeric_candidate_is_low_readiness(self):
        quality, _readiness = self.analyze([candidate(label="As at 31/12/2023", value="1234")])
        self.assertEqual(quality["aggregate_candidate_counts"]["readiness_distribution"].get("low"), 1)

    def test_text_block_with_sufficient_narrative_content_is_medium_or_high_readiness(self):
        quality, _readiness = self.analyze(
            [
                candidate(
                    row_type="text_block",
                    label="Accounting policy",
                    value="",
                    text="Revenue is recognised when control of the promised goods has transferred to the customer and the amount can be measured reliably.",
                    statement_section="Notes to the Financial Statements",
                )
            ]
        )
        distribution = quality["aggregate_candidate_counts"]["readiness_distribution"]
        self.assertGreater(distribution.get("high", 0) + distribution.get("medium", 0), 0)

    def test_per_case_readiness_classification_works(self):
        _quality, readiness = self.analyze([candidate(label="As at 31/12/2023", value="1234")])
        classification = readiness["per_case_readiness"][0]["ready_for_mapping_prototype"]
        self.assertIn(classification, {"needs_candidate_cleanup_first", "needs_numeric_cleanup_first"})

    def test_aggregate_report_counts_are_stable(self):
        quality, _readiness = self.analyze(
            [
                candidate(row_type="numeric_fact"),
                candidate(row_type="text_block", label="Policy", value="", text="A long enough accounting policy disclosure that should count as narrative text."),
            ]
        )
        self.assertEqual(quality["aggregate_candidate_counts"]["total_candidates"], 2)
        self.assertEqual(quality["aggregate_candidate_counts"]["candidate_type_distribution"]["numeric_fact"], 1)
        self.assertEqual(quality["aggregate_candidate_counts"]["candidate_type_distribution"]["text_block"], 1)

    def test_mapping_readiness_gates_render_into_markdown(self):
        _quality, readiness = self.analyze([candidate()])
        markdown = render_mapping_readiness_markdown(readiness)
        self.assertIn("Candidate Validity Gate", markdown)
        self.assertIn("Duplicate Conflict Gate", markdown)
        self.assertIn("Recommended Next Feature", markdown)

    def test_no_db_mutation_metadata_is_false(self):
        quality, readiness = self.analyze([candidate()])
        self.assertFalse(quality["run_metadata"]["database_mutated"])
        self.assertFalse(readiness["run_metadata"]["database_mutated"])

    def test_no_live_huggingface_or_openai_calls_are_required(self):
        quality, readiness = self.analyze([candidate()])
        self.assertFalse(quality["run_metadata"]["live_huggingface_calls_made"])
        self.assertFalse(quality["run_metadata"]["live_openai_calls_made"])
        self.assertFalse(readiness["run_metadata"]["live_huggingface_calls_made"])
        self.assertFalse(readiness["run_metadata"]["live_openai_calls_made"])

    def test_reference_xml_is_not_sent_to_any_model(self):
        quality, readiness = self.analyze([candidate()])
        self.assertFalse(quality["run_metadata"]["reference_xml_sent_to_model"])
        self.assertFalse(readiness["run_metadata"]["reference_xml_sent_to_model"])


if __name__ == "__main__":
    unittest.main()
