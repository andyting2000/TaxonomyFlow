import asyncio
import inspect
import json
import subprocess
import sys
import unittest
from pathlib import Path

import main


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_FIELDS = {
    "policy_eligible_count",
    "review_executable_count",
    "remapping_eligible_count",
    "remapping_executable_count",
    "revision_completed_count",
    "mapper_status",
    "is_human_terminal",
    "supervisor_review_executable",
    "batch_review_executable",
    "remapping_eligible",
    "remapping_executable",
}


class RuntimeStartupProvenanceTests(unittest.TestCase):
    def test_importing_main_does_not_start_uvicorn(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "import main; print(type(main.app).__name__)",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "FastAPI")

    def test_python_main_entrypoint_passes_existing_app_object(self):
        source = inspect.getsource(main)
        entrypoint = source.split('if __name__ == "__main__":', 1)[1]
        self.assertIn("uvicorn.run(", entrypoint)
        self.assertIn("        app,", entrypoint)
        self.assertNotIn('"main:app"', entrypoint)
        self.assertIn("reload=False", entrypoint)

    def test_runtime_provenance_resolves_to_current_workspace(self):
        provenance = main.get_runtime_provenance()
        self.assertEqual(provenance["runtime_revision"], "18F-G-D-hotfix-1+")
        for key in (
            "main_module_path",
            "filings_module_path",
            "actionability_module_path",
            "orchestrator_module_path",
        ):
            self.assertTrue(
                Path(provenance[key]).is_relative_to(ROOT),
                f"{key} resolved outside the workspace: {provenance[key]}",
            )
        self.assertEqual(Path(provenance["python_executable"]), Path(sys.executable))

    def test_expected_orchestration_routes_and_openapi_fields_are_registered(self):
        paths = main.app.openapi()["paths"]
        self.assertIn(
            "/api/v1/filings/jobs/{job_id}/supervisor-orchestration/capabilities",
            paths,
        )
        self.assertIn(
            "/api/v1/filings/jobs/{job_id}/supervisor-orchestration/plan",
            paths,
        )
        encoded_openapi = json.dumps(main.app.openapi(), sort_keys=True)
        for field in CANONICAL_FIELDS:
            self.assertIn(field, encoded_openapi)

    def test_health_exposes_non_secret_runtime_revision(self):
        health = asyncio.run(main.health_check())
        self.assertEqual(health["runtime_revision"], "18F-G-D-hotfix-1+")
        self.assertNotIn("cwd", health)
        self.assertNotIn("python_executable", health)
        self.assertNotIn("database_url", health)


if __name__ == "__main__":
    unittest.main()
