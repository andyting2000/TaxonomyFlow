import json
from pathlib import Path
import unittest

from schemas import NoteSubsection
from services.document_section_template_classifier import (
    classify_note_subsection,
    load_template_group_cards,
)
from services.note_subsection_segmenter import (
    parse_note_heading,
    segment_note_subsections,
)
from tests.template_classification_test_support import evidence, fixtures, section, structure


class NoteSubsectionSegmenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards, _metadata = load_template_group_cards()
        cls.data = fixtures()

    def notes_structure(self, rows, *, page_start=10, page_end=16):
        ids = [row.content_id for row in rows]
        note_section = section(
            canonical_section_type="notes_to_financial_statements",
            title="Notes to the Financial Statements",
            page_start=page_start,
            page_end=page_end,
            references=ids,
            candidate_note_heading_ids=[
                row.content_id
                for row in rows
                if row.content_type == "heading"
            ],
        )
        return structure(sections=[note_section], content_evidence=rows)

    def test_numbering_styles_split_lines_same_page_and_repeated_headings(self):
        rows = [
            evidence("h1", "I. CORPORATE INFORMATION", page=10, top=10),
            evidence("p1", "Principal activities", page=10, top=20, content_type="paragraph"),
            evidence("h2", "2.1 SIGNIFICANT ACCOUNTING POLICIES", page=10, top=40),
            evidence("h3", "3(a) ISSUED CAPITAL", page=11, top=10),
            evidence("h4n", "4.", page=12, top=10),
            evidence("h4t", "RELATED PARTY TRANSACTIONS", page=12, top=15),
            evidence("h5", "5. ISSUED CAPITAL", page=13, top=10),
        ]
        subsections, conservation, _warnings = segment_note_subsections(
            self.notes_structure(rows, page_end=13)
        )
        self.assertEqual(len(subsections), 5)
        self.assertEqual(
            [item.note_number for item in subsections],
            ["I", "2.1", "3(a)", "4", "5"],
        )
        self.assertEqual(
            subsections[3].heading_evidence,
            ["h4n", "h4t"],
        )
        self.assertIn("repeated_note_heading", subsections[4].warnings)
        self.assertTrue(conservation.passed)
        self.assertEqual(conservation.dropped_items, 0)
        self.assertEqual(
            conservation.total_notes_evidence_items,
            conservation.assigned_items
            + conservation.ambiguous_items
            + conservation.unassigned_items,
        )

    def test_one_note_spans_pages_and_multiple_notes_share_a_page(self):
        rows = [
            evidence("h1", "4. ISSUED CAPITAL", page=10, top=10),
            evidence("p10", "Narrative", page=10, top=20, content_type="paragraph"),
            evidence("p11", "continued", page=11, top=20, content_type="paragraph"),
            evidence("h2", "5. RELATED PARTY TRANSACTIONS", page=12, top=10),
            evidence("p12a", "Related parties", page=12, top=20, content_type="paragraph"),
            evidence("h3", "6. LIST OF NOTES", page=12, top=60),
            evidence("p12b", "Other disclosures", page=12, top=70, content_type="paragraph"),
        ]
        subsections, conservation, _warnings = segment_note_subsections(
            self.notes_structure(rows, page_end=12)
        )
        self.assertEqual(len(subsections), 3)
        self.assertEqual((subsections[0].pdf_page_start, subsections[0].pdf_page_end), (10, 11))
        self.assertIn("p12a", subsections[1].paragraph_references)
        self.assertIn("p12b", subsections[2].paragraph_references)
        self.assertTrue(conservation.passed)

    def test_table_continuation_before_later_heading_stays_with_prior_note(self):
        table = evidence(
            "table-1",
            "",
            page=15,
            top=20,
            content_type="table",
            pages=[15, 16],
        )
        table.bounding_evidence.append(
            {
                "page_number": 17,
                "polygon": [{"x": 0, "y": 20}, {"x": 1, "y": 20}],
            }
        )
        rows = [
            evidence("h1", "11. ISSUED CAPITAL", page=15, top=10),
            table,
            evidence("h2", "12. RELATED PARTY TRANSACTIONS", page=16, top=80),
        ]
        subsections, conservation, _warnings = segment_note_subsections(
            self.notes_structure(rows, page_start=15, page_end=16)
        )
        self.assertIn("table-1", subsections[0].table_references)
        self.assertNotIn("table-1", conservation.ambiguous_evidence_ids)
        self.assertEqual(conservation.dropped_items, 0)

    def test_ocr_noisy_and_unnumbered_heading_support(self):
        parsed = parse_note_heading(self.data["I"]["heading"])
        self.assertEqual(parsed[0], "10")
        rows = [
            evidence("h1", self.data["I"]["heading"], page=10, top=10),
            evidence("h2", "Related Party Transactions", page=11, top=10),
        ]
        subsections, conservation, _warnings = segment_note_subsections(
            self.notes_structure(rows, page_end=11)
        )
        self.assertEqual(len(subsections), 2)
        self.assertIsNone(subsections[1].note_number)
        self.assertTrue(conservation.passed)

    def note_outcome(self, heading, context=()):
        parsed = parse_note_heading(heading)
        subsection = NoteSubsection(
            child_section_id="notes:child",
            raw_heading=heading,
            normalized_heading=parsed[2],
            note_number=parsed[0],
            note_label=parsed[1],
            confidence=0.9,
        )
        return classify_note_subsection(
            subsection,
            cards=self.cards,
            context_fragments=context,
        )

    def test_730_740_750_and_many_to_many_semantics(self):
        for key in ("R", "S", "T"):
            case = self.data[key]
            with self.subTest(fixture=key):
                outcome = self.note_outcome(case["heading"])
                self.assertEqual(outcome.outcome.value, "matched")
                self.assertEqual(outcome.assignments[0].template_code, case["expected_code"])
        combined = self.note_outcome(self.data["F"]["heading"])
        self.assertEqual(combined.outcome.value, "multiple_templates")
        self.assertEqual(
            {item.template_code for item in combined.assignments},
            set(self.data["F"]["expected_codes"]),
        )

    def test_generic_context_unknown_and_wrong_legacy_labels(self):
        contextual = self.note_outcome(
            self.data["G"]["heading"],
            self.data["G"]["context"],
        )
        self.assertEqual(contextual.assignments[0].template_code, "750000")
        unknown = self.note_outcome(self.data["H"]["heading"])
        self.assertEqual(unknown.outcome.value, "unassigned")
        for legacy in ("Notes - Information on Companies", "Notes - Reports"):
            with self.subTest(legacy=legacy):
                self.assertEqual(
                    self.note_outcome(legacy).outcome.value,
                    "unassigned",
                )

    def job69_quality_structure(self, *, extra_boilerplate=False):
        fixture_path = (
            Path(__file__).parent
            / "fixtures"
            / "toc_aware"
            / "fixture_o_job69_notes_segmentation.json"
        )
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        rows = []
        for item in payload["rows"]:
            provenance = {}
            if item.get("section_heading"):
                provenance["role"] = "ParagraphRole.SECTION_HEADING"
            if item.get("table_member"):
                provenance["table_member"] = True
            rows.append(
                evidence(
                    item["id"],
                    item["text"],
                    page=item["page"],
                    top=item["top"],
                    content_type=item["type"],
                    provenance=provenance,
                )
            )
        if extra_boilerplate:
            rows.append(
                evidence(
                    "inserted-draft-noise",
                    "DRA",
                    page=20,
                    top=1.0,
                )
            )
        rows.sort(key=lambda item: (item.pdf_page_indexes[0], item.bounding_evidence[0]["polygon"][0]["y"], item.content_id))
        return payload, self.notes_structure(
            rows,
            page_start=payload["notes_pdf_page_start"],
            page_end=payload["notes_pdf_page_end"],
        )

    def test_job69_heading_quality_fixture_collapses_noise_and_continuations(self):
        payload, source = self.job69_quality_structure()
        subsections, conservation, _warnings = segment_note_subsections(source)

        self.assertEqual(
            [item.note_number for item in subsections],
            payload["expected_note_numbers"],
        )
        boundary_text = {item.raw_heading for item in subsections}
        for rejected in (
            "RM",
            "TO",
            "DRAFT",
            "DRAF",
            "17 17",
            "22 22",
            "100 100",
            "700 1,398",
            "465 Expenses not deductible for tax purposes",
            "897 EPF Contribution",
            "2. The financial statements have been prepared in accordance with the applicable reporting standard.",
            "c) After initial recognition, the Company measures all financial liabilities at amortised cost.",
        ):
            self.assertNotIn(rejected, boundary_text)
        self.assertEqual(conservation.assigned_items, len(source.content_evidence))
        self.assertEqual(conservation.ambiguous_items, 0)
        self.assertEqual(conservation.unassigned_items, 0)
        self.assertEqual(conservation.dropped_items, 0)
        self.assertTrue(conservation.passed)

        metrics = conservation.segmentation_metrics
        self.assertEqual(metrics.accepted_logical_subsection_count, len(subsections))
        self.assertGreater(metrics.duplicate_headings_merged, 0)
        self.assertEqual(metrics.continuation_headings_merged, 2)
        self.assertGreater(metrics.boilerplate_lines_suppressed, 0)
        self.assertGreater(metrics.table_value_fragments_suppressed, 0)
        self.assertGreater(metrics.invalid_numeric_note_numbers_rejected, 0)
        self.assertGreater(metrics.prose_candidates_rejected, 0)
        self.assertEqual(metrics.extracted_rows_attached, 1)
        self.assertEqual(metrics.child_sections_with_zero_meaningful_content, 0)

    def test_job69_share_capital_fact_attaches_to_logical_heading_not_rm(self):
        _payload, source = self.job69_quality_structure()
        subsections, _conservation, _warnings = segment_note_subsections(source)
        share_capital = next(item for item in subsections if item.note_number == "4")
        self.assertEqual(share_capital.raw_heading, "4. SHARE CAPITAL")
        self.assertIn("share-capital-row", share_capital.extracted_row_references)
        outcome = classify_note_subsection(
            share_capital,
            cards=self.cards,
            context_fragments=["ordinary shares issued and fully paid"],
        )
        self.assertEqual(outcome.assignments[0].template_code, "740000")
        self.assertNotIn("RM", {item.raw_heading for item in subsections})

    def test_logical_ids_ignore_inserted_boilerplate_and_keep_same_title_notes_distinct(self):
        _payload, original = self.job69_quality_structure()
        _payload, with_noise = self.job69_quality_structure(extra_boilerplate=True)
        original_children, _conservation, _warnings = segment_note_subsections(original)
        noisy_children, _conservation, _warnings = segment_note_subsections(with_noise)
        self.assertEqual(
            [item.child_section_id for item in original_children],
            [item.child_section_id for item in noisy_children],
        )
        director_notes = [
            item
            for item in original_children
            if item.normalized_heading == "amount due to director"
        ]
        self.assertEqual([item.note_number for item in director_notes], ["6", "7"])
        self.assertEqual(len({item.child_section_id for item in director_notes}), 2)


if __name__ == "__main__":
    unittest.main()
