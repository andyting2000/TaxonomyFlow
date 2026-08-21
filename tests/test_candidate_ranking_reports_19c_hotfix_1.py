import json
from collections import Counter
from pathlib import Path
import unittest


REPORTS = Path(__file__).parents[1] / "reports"
NAMES = (
    "job70_candidate_scope_19c_hotfix_1",
    "job70_candidate_ranking_19c_hotfix_1",
    "template_420000_candidate_audit_19c_hotfix_1",
)


class CandidateRankingReports19CHotfix1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reports = {
            name: json.loads((REPORTS / f"{name}.json").read_text(encoding="utf-8"))
            for name in NAMES
        }

    def test_all_required_json_and_markdown_pairs_are_present_and_pass(self):
        for name, report in self.reports.items():
            with self.subTest(report=name):
                self.assertEqual(report["analysis_status"], "PASS")
                self.assertTrue((REPORTS / f"{name}.md").is_file())
                self.assertTrue(report["read_only"])

    def test_ranking_quality_and_safety_are_explicit(self):
        report = self.reports["job70_candidate_ranking_19c_hotfix_1"]
        metrics = report["quality_metrics"]
        self.assertEqual(metrics["correct_family_top1_rate"], 1.0)
        self.assertEqual(metrics["correct_family_top3_rate"], 1.0)
        self.assertEqual(metrics["correct_family_top5_rate"], 1.0)
        self.assertEqual(metrics["contradictory_family_top1_count"], 0)
        self.assertEqual(metrics["expected_absent_scope_detected_count"], 9)
        self.assertEqual(metrics["safe_abstention_fixture_count"], 9)
        self.assertEqual(report["provider_calls"], 0)
        safety = report["safety_summary"]
        self.assertEqual(safety["template_group_leakage_count"], 0)
        self.assertEqual(safety["abstract_fact_selection_count"], 0)
        self.assertEqual(safety["confirmed_tag_id_mutations"], 0)
        self.assertEqual(safety["final_mapping_mutations"], 0)

    def test_420000_authority_answer_is_fail_closed(self):
        report = self.reports["template_420000_candidate_audit_19c_hotfix_1"]
        first = report["first_answer"]
        self.assertEqual(len(first["A_correct_concept_below_old_top8"]), 1)
        self.assertEqual(first["B_correct_concept_filtered_out"], [])
        self.assertEqual(len(first["C_correct_concept_absent_420000_membership"]), 9)
        self.assertEqual(first["D_correct_concept_absent_inventory"], [])
        classifications = Counter(item["classification"] for item in report["semantic_audit"])
        self.assertEqual(classifications["EXACT_SUPPORTED_CONCEPT"], 1)
        self.assertGreaterEqual(classifications["NO_CONCEPT_IN_TEMPLATE"], 1)
        membership = report["authoritative_membership"]
        self.assertEqual(len(membership), 22)
        self.assertEqual(len({item["qname"] for item in membership}), 21)
        self.assertEqual(
            len({item["qname"] for item in membership if item["selectable"]}),
            17,
        )
        self.assertEqual(
            sum(
                1
                for item in membership
                if item["qname"] == "ifrs-smes:ComprehensiveIncome"
            ),
            2,
        )

    def test_scope_report_serializes_every_complete_pre_top_k_pool(self):
        report = self.reports["job70_candidate_scope_19c_hotfix_1"]
        for row in report["rows"]:
            with self.subTest(label=row["raw_label"]):
                candidates = row["complete_candidate_scope"]
                self.assertEqual(
                    len(candidates),
                    row["candidate_count_before_filter"],
                )
                self.assertEqual(
                    sum(1 for item in candidates if item["selectable"]),
                    row["candidate_count_after_filter"],
                )
                self.assertTrue(
                    all("score" in item and "exclusion_reason" in item for item in candidates)
                )

if __name__ == "__main__":
    unittest.main()
