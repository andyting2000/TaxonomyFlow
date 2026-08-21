import unittest

from scripts.evaluate_section_aware_initial_mapping_19c import evaluate


class InitialMappingQualityReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports = evaluate(focused_test_count=30, full_test_count=None)

    def test_all_reports_pass_and_quality_is_not_hidden_by_mapping(self):
        self.assertTrue(all(report["status"] == "PASS" for report in self.reports.values()))
        retrieval = self.reports["retrieval"]["summary"]
        mapping = self.reports["mapping"]["summary"]
        self.assertEqual(retrieval["recall_at_1"], 1.0)
        self.assertEqual(retrieval["recall_at_8"], 1.0)
        self.assertEqual(retrieval["mean_reciprocal_rank"], 1.0)
        self.assertEqual(mapping["exact_initial_mapping_accuracy"], 0.8333)
        self.assertTrue(self.reports["quality"]["retrieval_and_mapping_reported_separately"])

    def test_required_safety_gates_are_zero(self):
        safety = self.reports["safety"]
        for key in safety["required_zero_gates"]:
            self.assertEqual(safety["summary"][key], 0, key)
        self.assertEqual(safety["summary"]["maximum_provider_calls_per_eligible_row"], 1)
        self.assertGreaterEqual(safety["summary"]["duplicate_groups_detected"], 1)
        self.assertGreaterEqual(safety["summary"]["competing_groups_detected"], 1)


if __name__ == "__main__":
    unittest.main()
