import subprocess
import tempfile
import unittest
from pathlib import Path

from services.arelle_validator import (
    REMOTE_FSM_MPERS_SCHEMAREF,
    build_arelle_command,
    classify_arelle_output,
    create_schema_ref_validation_copy,
    local_schema_ref_remaps,
    validate_with_arelle,
)


class ArelleValidatorTests(unittest.TestCase):
    def test_build_command_uses_cli_import_validate_and_offline_mode(self):
        command = build_arelle_command(
            "uploads/xbrl/example.xbrl",
            "taxonomy/entry_point.xsd",
            arelle_command=["arelleCmdLine"],
        )

        self.assertEqual(command[0], "arelleCmdLine")
        self.assertIn("--file", command)
        self.assertIn("uploads/xbrl/example.xbrl", command)
        self.assertIn("--import", command)
        self.assertIn("taxonomy/entry_point.xsd", command)
        self.assertIn("--validate", command)
        self.assertIn("--validationExitCode", command)
        self.assertIn("--internetConnectivity", command)
        self.assertIn("offline", command)

    def test_build_command_appends_mode_specific_args(self):
        command = build_arelle_command(
            "uploads/xbrl/example.xbrl",
            "taxonomy/entry_point.xsd",
            arelle_command=["arelleCmdLine"],
            extra_args=["--formula", "none"],
        )

        self.assertEqual(command[-2:], ["--formula", "none"])

    def test_build_command_appends_skip_loading_baseline_args(self):
        command = build_arelle_command(
            "uploads/xbrl/example.xbrl",
            "taxonomy/entry_point.xsd",
            arelle_command=["arelleCmdLine"],
            extra_args=[
                "--formula",
                "none",
                "--skipLoading",
                "*formula.xml|*existence_function_2022-12-31.xml",
            ],
        )

        self.assertEqual(command[-4:], ["--formula", "none", "--skipLoading", "*formula.xml|*existence_function_2022-12-31.xml"])

    def test_local_schema_ref_remap_uses_absolute_path_for_taxonomy_entrypoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            taxonomy = Path(tmpdir) / "entry.xsd"
            taxonomy.write_text("<schema />", encoding="utf-8")

            remaps = local_schema_ref_remaps(str(taxonomy))

        self.assertIn(REMOTE_FSM_MPERS_SCHEMAREF, remaps)
        self.assertEqual(remaps[REMOTE_FSM_MPERS_SCHEMAREF], str(taxonomy.resolve()))

    def test_create_schema_ref_validation_copy_rewrites_remote_schema_ref_only_in_copy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "instance.xbrl"
            copy_dir = Path(tmpdir) / "copies"
            local_path = str((Path(tmpdir) / "entry.xsd").resolve())
            source.write_text(
                f"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:schemaRef xlink:type="simple" xlink:href="{REMOTE_FSM_MPERS_SCHEMAREF}" />
</xbrli:xbrl>
""",
                encoding="utf-8",
            )

            copy_path, applied = create_schema_ref_validation_copy(
                str(source),
                str(copy_dir),
                {REMOTE_FSM_MPERS_SCHEMAREF: local_path},
            )

            original_text = source.read_text(encoding="utf-8")
            copy_text = Path(copy_path).read_text(encoding="utf-8")

        self.assertEqual(
            applied,
            [{"from": REMOTE_FSM_MPERS_SCHEMAREF, "to": "../entry.xsd", "local_path": local_path}],
        )
        self.assertIn(REMOTE_FSM_MPERS_SCHEMAREF, original_text)
        self.assertIn("../entry.xsd", copy_text)
        self.assertNotEqual(str(source), copy_path)

    def test_classify_output_separates_errors_and_warnings(self):
        errors, warnings = classify_arelle_output(
            "[xbrl.5.2.5] error: concept is invalid\nwarning: duplicate fact",
            "",
            3,
        )

        self.assertEqual(len(errors), 1)
        self.assertIn("invalid", errors[0])
        self.assertEqual(len(warnings), 1)
        self.assertIn("duplicate fact", warnings[0])

    def test_validate_returns_valid_result_for_clean_zero_exit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            instance = Path(tmpdir) / "instance.xbrl"
            taxonomy = Path(tmpdir) / "entry.xsd"
            instance.write_text("<xbrl />", encoding="utf-8")
            taxonomy.write_text("<schema />", encoding="utf-8")

            def fake_runner(command, capture_output, text, timeout):
                return subprocess.CompletedProcess(command, 0, stdout="loaded\n", stderr="")

            result = validate_with_arelle(
                str(instance),
                str(taxonomy),
                arelle_command=["arelleCmdLine"],
                extra_args=["--formula", "none"],
                validation_mode="no_formula",
                runner=fake_runner,
            )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.return_code, 0)
        self.assertIn("arelleCmdLine", result.command_used)
        self.assertIn("--formula none", result.command_used)
        self.assertEqual(result.validation_mode, "no_formula")

    def test_validate_uses_validation_copy_when_schema_ref_remap_is_supplied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            instance = Path(tmpdir) / "instance.xbrl"
            taxonomy = Path(tmpdir) / "entry.xsd"
            copy_dir = Path(tmpdir) / "copies"
            taxonomy.write_text("<schema />", encoding="utf-8")
            instance.write_text(
                f"""<?xml version="1.0" encoding="UTF-8"?>
<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
            xmlns:link="http://www.xbrl.org/2003/linkbase"
            xmlns:xlink="http://www.w3.org/1999/xlink">
  <link:schemaRef xlink:type="simple" xlink:href="{REMOTE_FSM_MPERS_SCHEMAREF}" />
</xbrli:xbrl>
""",
                encoding="utf-8",
            )

            def fake_runner(command, capture_output, text, timeout):
                self.assertTrue(any(str(part).endswith("instance_local_schemaRef.xbrl") for part in command))
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

            result = validate_with_arelle(
                str(instance),
                str(taxonomy),
                arelle_command=["arelleCmdLine"],
                runner=fake_runner,
                schema_ref_remaps=local_schema_ref_remaps(str(taxonomy)),
                validation_copy_dir=str(copy_dir),
            )

        self.assertTrue(result.is_valid)
        self.assertEqual(result.original_instance_path, str(instance))
        self.assertTrue(result.validation_instance_path.endswith("instance_local_schemaRef.xbrl"))
        self.assertEqual(len(result.schema_ref_remaps), 1)

    def test_validate_returns_invalid_result_for_nonzero_error_output(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            instance = Path(tmpdir) / "instance.xbrl"
            taxonomy = Path(tmpdir) / "entry.xsd"
            instance.write_text("<xbrl />", encoding="utf-8")
            taxonomy.write_text("<schema />", encoding="utf-8")

            def fake_runner(command, capture_output, text, timeout):
                return subprocess.CompletedProcess(
                    command,
                    3,
                    stdout="[xbrl] error: missing context",
                    stderr="",
                )

            result = validate_with_arelle(
                str(instance),
                str(taxonomy),
                arelle_command=["arelleCmdLine"],
                runner=fake_runner,
            )

        self.assertFalse(result.is_valid)
        self.assertEqual(result.return_code, 3)
        self.assertIn("missing context", result.errors[0])
        self.assertIn("missing context", result.raw_output)

    def test_validate_reports_timeout_without_real_arelle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            instance = Path(tmpdir) / "instance.xbrl"
            taxonomy = Path(tmpdir) / "entry.xsd"
            instance.write_text("<xbrl />", encoding="utf-8")
            taxonomy.write_text("<schema />", encoding="utf-8")

            def timeout_runner(command, capture_output, text, timeout):
                raise subprocess.TimeoutExpired(command, timeout)

            result = validate_with_arelle(
                str(instance),
                str(taxonomy),
                timeout_seconds=1,
                arelle_command=["arelleCmdLine"],
                runner=timeout_runner,
            )

        self.assertFalse(result.is_valid)
        self.assertIsNone(result.return_code)
        self.assertIn("timed out", result.errors[0])

    def test_validate_reports_missing_instance_without_running_command(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            taxonomy = Path(tmpdir) / "entry.xsd"
            taxonomy.write_text("<schema />", encoding="utf-8")

            def failing_runner(command, capture_output, text, timeout):
                raise AssertionError("runner should not be called")

            result = validate_with_arelle(
                str(Path(tmpdir) / "missing.xbrl"),
                str(taxonomy),
                arelle_command=["arelleCmdLine"],
                runner=failing_runner,
            )

        self.assertFalse(result.is_valid)
        self.assertIn("does not exist", result.errors[0])


if __name__ == "__main__":
    unittest.main()
