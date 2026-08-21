import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from scripts import run_real_arelle_validation as helper


class FakeGenerationResponse:
    def __init__(self, success=True, file_path=None, error=None):
        self.success = success
        self.file_path = file_path
        self.error = error

    def model_dump(self):
        return {
            "success": self.success,
            "file_path": self.file_path,
            "error": self.error,
        }


class FakeValidationResponse:
    def __init__(self, is_valid=False, errors=None, warnings=None, raw_output="", command_used="arelleCmdLine"):
        self.payload = {
            "is_valid": is_valid,
            "errors": errors or [],
            "warnings": warnings or [],
            "raw_output": raw_output,
            "return_code": 3 if errors else 0,
            "duration_ms": 7,
            "instance_path": "instance.xbrl",
            "taxonomy_entrypoint": "taxonomy.xsd",
            "command_used": command_used,
            "original_instance_path": "original.xbrl",
            "validation_instance_path": "validation-copy.xbrl",
            "schema_ref_remaps": [{"from": "remote", "to": "local"}],
            "validation_mode": "full",
        }

    def to_dict(self):
        return self.payload


class RunRealArelleValidationTests(unittest.IsolatedAsyncioTestCase):
    def test_classify_diagnostics_places_lines_in_expected_categories(self):
        validation = {
            "errors": [
                "schemaRef is not reachable",
                "ContextRef missing_context not found",
                "duplicate fact reported",
                "Namespace prefix ssmt-mpers is not defined",
                "UnitRef MYR is invalid",
                "Calculation inconsistency",
            ],
            "warnings": ["Something else"],
            "raw_output": "",
        }

        categories = helper.classify_diagnostics(validation)

        self.assertIn("schemaRef is not reachable", categories["schemaRef_issues"])
        self.assertIn("ContextRef missing_context not found", categories["missing_contexts"])
        self.assertIn("duplicate fact reported", categories["duplicate_facts"])
        self.assertIn("Namespace prefix ssmt-mpers is not defined", categories["namespace_issues"])
        self.assertIn("UnitRef MYR is invalid", categories["unit_issues"])
        self.assertIn("Calculation inconsistency", categories["calculation_issues"])
        self.assertIn("Something else", categories["other"])

    async def test_run_validation_generates_validates_and_writes_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            xbrl_path = tmp_path / "generated.xbrl"
            xbrl_path.write_text("<xbrl />", encoding="utf-8")

            def fake_validator(
                instance_path,
                taxonomy_entrypoint,
                timeout_seconds,
                schema_ref_remaps=None,
                validation_copy_dir=None,
                extra_args=None,
                validation_mode="full",
            ):
                self.assertIsNotNone(schema_ref_remaps)
                self.assertIn("validation_copies", str(validation_copy_dir))
                return FakeValidationResponse(
                    is_valid=False,
                    errors=["schemaRef is not reachable"],
                    command_used=f"arelleCmdLine --file generated.xbrl {validation_mode}",
                )

            with patch.object(
                helper,
                "describe_job",
                return_value={
                    "id": 9,
                    "company_name": "Example",
                    "status": "REVIEW",
                    "extracted_rows": 3,
                    "template_field_rows": 2,
                },
            ), patch.object(
                helper,
                "generate_for_job",
                new=AsyncMock(return_value=FakeGenerationResponse(success=True, file_path=str(xbrl_path)).model_dump()),
            ):
                report = await helper.run_validation(
                    job_id=9,
                    taxonomy_entrypoint="taxonomy.xsd",
                    report_dir=tmp_path,
                    session_factory=lambda: None,
                    validator=fake_validator,
                )

            report_path = tmp_path / "arelle_validation_report_9.json"
            self.assertTrue(report_path.exists())
            self.assertTrue(report["success"])
            self.assertEqual(report["job"]["id"], 9)
            self.assertEqual(report["generation"]["file_path"], str(xbrl_path))
            self.assertFalse(report["validation"]["is_valid"])
            self.assertIn("schemaRef is not reachable", report["diagnostic_categories"]["schemaRef_issues"])
            self.assertEqual(report["taxonomy_resolution_status"], "failed_or_questionable")
            self.assertTrue((tmp_path / "arelle_validation_modes_report_9.json").exists())
            self.assertTrue((tmp_path / "arelle_validation_baseline_report_9.json").exists())
            self.assertIn("modes_report_path", report)
            self.assertIn("baseline_report_path", report)

    def test_summarize_mode_classifies_taxonomy_noise(self):
        validation = {
            "is_valid": False,
            "return_code": 3,
            "command_used": "arelleCmdLine --formula none",
            "errors": [
                "[err:XPST0003] Parse error in select error - formula_ssmt-fs-mpers_2022-12-31.xml",
                "[xbrlte:abstractRuleNodeNoChildren] Abstract ruleNode has no children - table_ssmt-fs-mpers_2022-12-31_role-210100.xml",
                "ContextRef c1 not found",
            ],
            "warnings": [],
            "raw_output": "",
        }

        summary = helper.summarize_mode(validation)

        self.assertTrue(summary["formula_table_diagnostics_remain"])
        self.assertTrue(summary["generated_instance_defects_visible"])
        self.assertEqual(summary["error_families"]["taxonomy_artifact_compatibility"]["count"], 2)
        self.assertEqual(summary["error_families"]["generated_instance_defect"]["count"], 1)

    def test_baseline_mode_recommendation_selects_clean_structural_mode(self):
        recommendation = helper.baseline_mode_recommendation(
            {
                "skip_formula_table": {
                    "is_valid": False,
                    "taxonomy_resolution_status": "no_taxonomy_resolution_error_detected",
                    "taxonomy_artifact_noise_remains": True,
                    "generated_instance_defects_visible": False,
                },
                "instance_baseline": {
                    "is_valid": True,
                    "taxonomy_resolution_status": "no_taxonomy_resolution_error_detected",
                    "taxonomy_artifact_noise_remains": False,
                    "generated_instance_defects_visible": False,
                },
            }
        )

        self.assertEqual(recommendation["recommended_baseline_mode"], "instance_baseline")
        self.assertTrue(recommendation["can_proceed_to_mapping_fixes"])
        self.assertIn("not full MBRS validation", recommendation["reason"])

    def test_skipped_taxonomy_patterns_for_baseline_mode_are_reportable(self):
        skipped = helper._skipped_taxonomy_patterns_for_mode("instance_baseline")

        self.assertIn("*formula_ssmt-fs-mpers_2022-12-31.xml", skipped)
        self.assertIn("*table_ssmt-fs-mpers_2022-12-31*.xml", skipped)
        self.assertIn("*existence_function_2022-12-31.xml", skipped)

    async def test_run_validation_reports_missing_requested_job_without_generation(self):
        async def fake_generator(job_id, session):
            raise AssertionError("generator should not be called")

        with patch.object(helper, "describe_job", return_value=None):
            report = await helper.run_validation(
                job_id=123,
                taxonomy_entrypoint="taxonomy.xsd",
                report_dir=Path("reports"),
                session_factory=lambda: None,
                generator=fake_generator,
            )

        self.assertFalse(report["success"])
        self.assertIn("Requested job 123", report["error"])


if __name__ == "__main__":
    unittest.main()
