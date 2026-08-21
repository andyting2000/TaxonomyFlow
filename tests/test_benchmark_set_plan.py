import json
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class BenchmarkSetPlanTests(unittest.TestCase):
    def load_json(self, relative_path):
        return json.loads((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))

    def test_plan_exists_with_required_sections(self):
        report = self.load_json("reports/benchmark_set_plan_13i.json")
        required = {
            "feature",
            "purpose",
            "user_pdf_context",
            "required_categories",
            "benchmark_vs_few_shot_policy",
            "benchmark_policy",
            "upload_runbook_summary",
            "manifest_schema",
            "few_shot_example_schema",
            "metrics_interpretation",
            "future_ground_truth_design",
            "recommended_next_feature",
        }
        self.assertTrue(required.issubset(report))
        self.assertTrue(report["scope_guard"]["planning_only"])
        self.assertFalse(report["scope_guard"]["production_behavior_changed"])
        self.assertFalse(report["scope_guard"]["database_mutated"])

    def test_all_seven_required_categories_exist(self):
        report = self.load_json("reports/benchmark_set_plan_13i.json")
        categories = {case["category"] for case in report["required_categories"]}
        self.assertEqual(
            categories,
            {
                "standard_text_native",
                "ocr_clean",
                "ocr_poor_quality",
                "complex_table",
                "notes_heavy",
                "customer_like",
                "edge_case",
            },
        )

    def test_job_9_policy_is_smoke_test_only(self):
        report = self.load_json("reports/benchmark_set_plan_13i.json")
        policy = report["user_pdf_context"]["job_9_policy"].lower()
        self.assertIn("smoke-test-only", policy)
        self.assertIn("must not be used as benchmark ground truth", policy)

        local_manifest = self.load_json("benchmark_cases/benchmark_manifest.local.example.json")
        job_9 = next(case for case in local_manifest["cases"] if case["case_id"] == "job_9_smoke")
        self.assertEqual(job_9["uploaded_job_id"], 9)
        self.assertEqual(job_9["job_role"], "smoke_test_only")

    def test_benchmark_few_shot_separation_policy_is_present(self):
        report = self.load_json("reports/benchmark_set_plan_13i.json")
        policy = report["benchmark_vs_few_shot_policy"]
        self.assertIn("benchmark leakage", policy["problem"])
        self.assertIn("strict benchmark-first", policy["recommended_for_user"])
        self.assertTrue(any("excluded from benchmark scoring" in rule for rule in policy["leakage_rules"]))

    def test_manifest_examples_are_parseable_and_private_safe(self):
        manifest = self.load_json("benchmark_cases/benchmark_manifest.example.json")
        local_manifest = self.load_json("benchmark_cases/benchmark_manifest.local.example.json")
        self.assertFalse(manifest["privacy_policy"]["contains_private_pdfs"])
        self.assertFalse(manifest["privacy_policy"]["contains_real_customer_data"])
        self.assertEqual(len([case for case in manifest["cases"] if not case["is_smoke_test"]]), 7)
        self.assertTrue(any(case["uploaded_job_id"] == 11 for case in local_manifest["cases"]))
        self.assertTrue(any(case["uploaded_job_id"] == 9 for case in local_manifest["cases"]))

    def test_few_shot_schema_is_parseable_and_excludes_evaluation(self):
        examples = self.load_json("benchmark_cases/few_shot_examples.example.json")
        self.assertTrue(examples["few_shot_policy"]["manual_verification_required"])
        self.assertTrue(examples["few_shot_policy"]["exclude_prompt_examples_from_evaluation"])
        for example in examples["examples"]:
            self.assertTrue(example["excluded_from_evaluation"])
            self.assertIn("expected_rows", example)
            self.assertTrue(example["expected_rows"][0]["do_not_invent"])

    def test_runbook_contains_required_commands_and_ocr_context(self):
        text = (PROJECT_ROOT / "benchmark_cases/README.md").read_text(encoding="utf-8")
        self.assertIn("seven PDFs", text)
        self.assertIn("OCR/scanned", text)
        self.assertIn("python -B scripts/benchmark_extraction_mapping.py --jobs 11 --markdown", text)
        self.assertIn("--include-job-9", text)
        self.assertIn("Job 9 is smoke-test-only", text)

    def test_no_production_code_files_are_in_allowed_changed_files(self):
        report = self.load_json("reports/benchmark_set_plan_13i.json")
        allowed = set(report["scope_guard"]["allowed_changed_files"])
        forbidden_prefixes = (
            "services/",
            "routers/",
            "frontend/",
            "migrations/",
        )
        forbidden_exact = {
            "database.py",
            "tasks.py",
            "scripts/benchmark_extraction_mapping.py",
        }
        for path in allowed:
            self.assertFalse(path.startswith(forbidden_prefixes), path)
            self.assertNotIn(path, forbidden_exact)

    def test_recommended_next_feature_is_present(self):
        report = self.load_json("reports/benchmark_set_plan_13i.json")
        next_feature = report["recommended_next_feature"]
        self.assertIn("User uploads seven representative PDFs", next_feature["manual_step_first"])
        self.assertIn("Feature #13J", next_feature["next_feature_after_manual_upload"])


if __name__ == "__main__":
    unittest.main()
