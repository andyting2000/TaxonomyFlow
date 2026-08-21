import json
import unittest
from pathlib import Path


class ExtractionMappingArchitectureReportTests(unittest.TestCase):
    def setUp(self):
        self.report_path = Path("reports/extraction_mapping_architecture_audit_13g.json")
        self.report = json.loads(self.report_path.read_text(encoding="utf-8"))

    def test_report_exists_with_required_sections(self):
        required_sections = {
            "current_architecture",
            "instability_findings",
            "keep_replace_decisions",
            "recommended_architecture",
            "openai_api_usage_plan",
            "arelle_position",
            "option_comparison",
            "migration_plan",
            "benchmark_plan",
            "risks",
            "next_feature_recommendation",
        }
        self.assertTrue(self.report_path.exists())
        self.assertTrue(required_sections.issubset(self.report.keys()))

    def test_recommendation_is_present(self):
        recommendation = self.report["next_feature_recommendation"]
        self.assertIn("Feature #13H", recommendation["feature"])
        self.assertIn("benchmark", recommendation["reason"].lower())

    def test_job_9_is_not_primary_benchmark(self):
        benchmark_text = json.dumps(self.report["benchmark_plan"]).lower()
        self.assertIn("job 9 is not the primary benchmark", benchmark_text)
        self.assertIn("smoke-test", benchmark_text)

    def test_arelle_is_not_agentic_auto_fix(self):
        arelle_position = self.report["arelle_position"]
        self.assertFalse(arelle_position["should_llm_call_arelle_directly_now"])
        self.assertTrue(arelle_position["no_agentic_auto_fix_yet"])
        self.assertIn("auto-fix", arelle_position["recommendation"].lower())

    def test_migration_plan_is_phased(self):
        phases = self.report["migration_plan"]["phases"]
        self.assertGreaterEqual(len(phases), 8)
        self.assertEqual(phases[0]["phase"], 0)
        self.assertEqual(phases[-1]["phase"], 8)

    def test_scope_guard_records_no_production_code_change(self):
        scope_guard = self.report["scope_guard"]
        self.assertTrue(scope_guard["no_production_code_changed"])
        changed_files = set(scope_guard["allowed_changed_files"])
        forbidden_prefixes = (
            "services/",
            "routers/",
            "frontend/",
            "tasks.py",
            "database.py",
            "mpers_templates.json",
        )
        for changed_file in changed_files:
            self.assertFalse(changed_file.startswith(forbidden_prefixes), changed_file)


if __name__ == "__main__":
    unittest.main()
