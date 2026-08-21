from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from scripts.report_toc_aware_real_pdf_smoke import build_structure_metrics, main
from services.toc_aware_document_structure import analyze_document_structure


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "toc_aware"
    / "fixture_k_real_pdf_job65_regression.json"
)
JOB66_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "toc_aware"
    / "fixture_l_real_pdf_job66_anchor_range.json"
)


class RealPdfSmokeReportTests(unittest.TestCase):
    def test_structure_metrics_are_read_only_and_surface_quality_gates(self):
        structure = analyze_document_structure(
            job_id=65,
            azure_result=json.loads(FIXTURE.read_text(encoding="utf-8")),
            normalized_candidates=[],
        )

        metrics = build_structure_metrics(structure)

        self.assertEqual(metrics["toc_entry_count"], 9)
        self.assertEqual(metrics["suspicious_toc_entry_count"], 0)
        self.assertEqual(metrics["dominant_offsets"], [1])
        self.assertGreater(metrics["notes_evidence_count"], 0)
        self.assertEqual(metrics["dropped_evidence"], 0)
        self.assertEqual(metrics["quality_warnings"], [])

    def test_job66_metrics_surface_anchor_and_range_hard_gates(self):
        structure = analyze_document_structure(
            job_id=66,
            azure_result=json.loads(JOB66_FIXTURE.read_text(encoding="utf-8")),
            normalized_candidates=[],
        )

        metrics = build_structure_metrics(structure)

        self.assertEqual(
            metrics["selected_anchor_match_counts"],
            {
                "exact": 5,
                "prefix": 4,
                "canonical_alias_or_equivalent": 0,
                "fuzzy": 0,
                "partial": 0,
            },
        )
        self.assertEqual(
            metrics["weaker_selected_while_stronger_alternative_count"], 0
        )
        self.assertEqual(metrics["off_regime_selected_anchor_count"], 0)
        self.assertEqual(metrics["section_page_mapping_conflict_count"], 0)
        self.assertEqual(metrics["explicit_range_projection_success_count"], 3)
        self.assertEqual(metrics["notes_ranges"][0]["pdf_page_start"], 16)
        self.assertEqual(metrics["notes_ranges"][0]["pdf_page_end"], 23)
        self.assertGreater(metrics["assignment_rate_excluding_toc"], 0.75)

    def test_missing_current_artifact_is_reported_as_structured_failure(self):
        output = StringIO()
        with (
            patch(
                "scripts.report_toc_aware_real_pdf_smoke.build_job_report",
                side_effect=FileNotFoundError("structure_19a_v4.json"),
            ),
            patch.object(sys, "argv", ["report_toc_aware_real_pdf_smoke.py", "65"]),
            redirect_stdout(output),
        ):
            exit_code = main()

        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertTrue(payload["read_only"])
        self.assertEqual(payload["provider_calls_made"], 0)
        self.assertFalse(payload["quality_gate"]["pass"])
        self.assertEqual(
            payload["error"]["code"],
            "current_structure_artifact_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
