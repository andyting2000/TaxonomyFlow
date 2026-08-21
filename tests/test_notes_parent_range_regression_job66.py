import asyncio
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from config import settings
from scripts.report_toc_aware_real_pdf_smoke import (
    build_classification_metrics,
    build_job_report,
)
from services.note_subsection_segmenter import segment_note_subsections
from services.toc_aware_document_structure import analyze_document_structure
from services.toc_aware_template_classification import analyze_template_classification


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "toc_aware"
    / "fixture_l_real_pdf_job66_anchor_range.json"
)


class NotesParentRangeRegressionJob66Tests(unittest.TestCase):
    def test_notes_children_come_from_corrected_parent_range_not_cover(self):
        structure = analyze_document_structure(
            job_id=66,
            azure_result=json.loads(FIXTURE.read_text(encoding="utf-8")),
            normalized_candidates=[],
        )
        notes = next(
            section
            for section in structure.sections
            if section.canonical_section_type == "notes_to_financial_statements"
        )
        subsections, conservation, _warnings = segment_note_subsections(structure)

        self.assertEqual((notes.pdf_page_start, notes.pdf_page_end), (16, 23))
        self.assertGreater(len(subsections), 0)
        self.assertTrue(conservation.passed)
        self.assertEqual(conservation.dropped_items, 0)
        cover_titles = {
            "company no 202201047805 1493502 x",
            "bezlife marketing sdn bhd",
            "directors report and",
            "financial statements",
            "for",
            "the financial year ended",
            "31 december 2024",
        }
        self.assertFalse(
            cover_titles.intersection(
                subsection.normalized_heading for subsection in subsections
            )
        )
        self.assertTrue(
            all(
                notes.pdf_page_start
                <= subsection.pdf_page_start
                <= subsection.pdf_page_end
                <= notes.pdf_page_end
                for subsection in subsections
            )
        )

    def test_19b_output_and_smoke_distribution_stay_inside_notes_parent(self):
        structure = analyze_document_structure(
            job_id=66,
            azure_result=json.loads(FIXTURE.read_text(encoding="utf-8")),
            normalized_candidates=[],
        )
        with patch.object(
            settings,
            "toc_aware_template_classification_live_llm_enabled",
            False,
        ):
            classification = asyncio.run(
                analyze_template_classification(job_id=66, structure=structure)
            )

        metrics = build_classification_metrics(
            classification,
            structure=structure,
        )
        self.assertGreater(metrics["note_subsection_count"], 0)
        self.assertEqual(metrics["notes_children_outside_parent_range_count"], 0)
        self.assertNotIn("0", metrics["notes_child_page_distribution"])
        self.assertTrue(
            set(map(int, metrics["notes_child_page_distribution"]))
            .issubset(set(range(16, 24)))
        )
        with (
            patch(
                "scripts.report_toc_aware_real_pdf_smoke.load_document_structure",
                return_value=structure,
            ),
            patch(
                "scripts.report_toc_aware_real_pdf_smoke.load_template_classification",
                return_value=classification,
            ),
            patch(
                "scripts.report_toc_aware_real_pdf_smoke.load_initial_mapping",
                side_effect=FileNotFoundError("initial mapping not persisted"),
            ),
        ):
            report = build_job_report(66)
        self.assertTrue(report["quality_gate"]["pass"])
        self.assertTrue(all(report["quality_gate"]["hard_gates"].values()))


if __name__ == "__main__":
    unittest.main()
