import json
from pathlib import Path
import unittest

from services.document_page_alignment import align_document_pages, detect_heading_anchors
from services.document_section_grouper import build_document_sections
from services.toc_aware_document_structure import build_page_text_evidence
from services.toc_detection import detect_toc_pages
from services.toc_entry_extractor import extract_toc_entries


FIXTURES = Path(__file__).parent / "fixtures" / "toc_aware"


def alignment_for(name):
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    pages = build_page_text_evidence(payload)
    detection = detect_toc_pages(pages)
    lines = [
        line
        for page in pages
        if page["pdf_page_index"] in detection.candidate_page_indexes
        for line in page["lines"]
    ]
    entries = extract_toc_entries(lines)
    anchors = detect_heading_anchors(entries, payload, toc_page_indexes=detection.candidate_page_indexes)
    page_numbers = [page["page_number"] for page in payload["pages"]]
    return payload, entries, anchors, align_document_pages(entries, anchors, azure_page_numbers=page_numbers)


class DocumentPageAlignmentTests(unittest.TestCase):
    def test_heading_anchors_resolve_printed_to_pdf_offset(self):
        _payload, _entries, anchors, alignment = alignment_for("fixture_d_page_offset.json")
        self.assertEqual(alignment.offset_candidates, {2: 3})
        self.assertEqual(alignment.mapping_method, "weighted_heading_anchor_consensus")
        printed_one = next(row for row in alignment.page_mappings if row.printed_page_number == 1)
        self.assertEqual(printed_one.pdf_page_index, 3)
        self.assertEqual(printed_one.azure_page_number, 4)
        self.assertEqual(printed_one.offset, 2)
        self.assertTrue(all(anchor.bounding_evidence for anchor in anchors))

    def test_inconsistent_anchors_do_not_project_ambiguous_page_ranges(self):
        _payload, _entries, _anchors, alignment = alignment_for("fixture_j_inconsistent_anchors.json")
        self.assertTrue(alignment.requires_human_review)
        self.assertIn("page_alignment_ambiguous", alignment.warnings)
        self.assertEqual(alignment.mapping_method, "exact_heading_anchor_only")
        self.assertTrue(
            any(
                row.printed_page_number is None
                and row.mapping_method == "unmapped_ambiguous_alignment"
                for row in alignment.page_mappings
            )
        )

    def test_one_anchor_is_a_review_required_proposal(self):
        payload, entries, anchors, _alignment = alignment_for("fixture_a_explicit_ranges.json")
        one = align_document_pages(
            entries[:1],
            anchors[:1],
            azure_page_numbers=[page["page_number"] for page in payload["pages"]],
        )
        self.assertTrue(one.requires_human_review)
        self.assertIn("single_heading_anchor", one.warnings)
        self.assertLess(one.confidence, anchors[0].match_score)
        sections = build_document_sections(1, entries[:1], anchors[:1], one)
        self.assertEqual(sections[0].pdf_page_start, sections[0].pdf_page_end)
        self.assertEqual(
            sections[0].grouping_method,
            "heading_anchor_only_ambiguous_alignment",
        )

    def test_piecewise_alignment_preserves_roman_and_arabic_labels(self):
        entries = extract_toc_entries(
            [
                {"text": "Company Information i", "pdf_page_index": 0},
                {"text": "Statutory Declaration ii", "pdf_page_index": 0},
                {"text": "Directors Report 1", "pdf_page_index": 0},
                {
                    "text": "Statement of Financial Position 2",
                    "pdf_page_index": 0,
                },
            ]
        )
        headings = {
            2: "COMPANY INFORMATION",
            3: "STATUTORY DECLARATION",
            6: "DIRECTORS REPORT",
            7: "STATEMENT OF FINANCIAL POSITION",
        }
        payload = {
            "pages": [
                {
                    "page_number": page_number,
                    "height": 1000,
                    "lines": (
                        [
                            {
                                "content": headings[page_number],
                                "page_number": page_number,
                                "polygon": [{"x": 1, "y": 50}],
                            }
                        ]
                        if page_number in headings
                        else []
                    ),
                }
                for page_number in range(1, 8)
            ],
            "paragraphs": [],
        }
        anchors = detect_heading_anchors(
            entries,
            payload,
            toc_page_indexes=[0],
        )
        alignment = align_document_pages(
            entries,
            anchors,
            azure_page_numbers=range(1, 8),
        )

        self.assertEqual(alignment.mapping_method, "heading_anchor_piecewise")
        roman_one = next(
            row for row in alignment.page_mappings
            if row.pdf_page_index == 1
        )
        arabic_one = next(
            row for row in alignment.page_mappings
            if row.pdf_page_index == 5
        )
        self.assertEqual(
            (roman_one.printed_page_label, roman_one.numbering_scheme),
            ("i", "roman"),
        )
        self.assertEqual(
            (arabic_one.printed_page_label, arabic_one.numbering_scheme),
            ("1", "arabic"),
        )
        self.assertEqual(alignment.final_numbering_scheme, "arabic")

    def test_anchor_records_page_label_and_table_boundary_signals(self):
        entries = extract_toc_entries(
            [{"text": "Directors Report 1", "pdf_page_index": 0}]
        )
        payload = {
            "pages": [
                {
                    "page_number": 2,
                    "height": 1000,
                    "lines": [
                        {
                            "content": "DIRECTORS REPORT",
                            "page_number": 2,
                            "polygon": [{"x": 1, "y": 50}],
                        },
                        {
                            "content": "1",
                            "page_number": 2,
                            "polygon": [{"x": 1, "y": 900}],
                        },
                    ],
                }
            ],
            "paragraphs": [],
            "tables": [
                {
                    "table_index": 0,
                    "bounding_regions": [
                        {
                            "page_number": 2,
                            "polygon": [{"x": 1, "y": 200}],
                        }
                    ],
                    "cells": [],
                }
            ],
        }

        anchor = detect_heading_anchors(
            entries,
            payload,
            toc_page_indexes=[0],
        )[0]

        self.assertIn("matching_nearby_page_label", anchor.scoring_signals)
        self.assertIn("precedes_table_boundary", anchor.scoring_signals)

    def test_cross_page_heading_ties_fail_safely_after_duplicate_source_collapse(self):
        entries = extract_toc_entries(
            [
                {"text": "Directors Report 1", "pdf_page_index": 0},
                {
                    "text": "Statement of Financial Position 2",
                    "pdf_page_index": 0,
                },
            ]
        )
        pages = [
            {"page_number": page_number, "height": 1000, "lines": []}
            for page_number in range(1, 7)
        ]
        headings = {
            2: "DIRECTORS REPORT",
            3: "STATEMENT OF FINANCIAL POSITION",
            5: "DIRECTORS REPORT",
            6: "STATEMENT OF FINANCIAL POSITION",
        }
        paragraphs = []
        for paragraph_index, (page_number, text) in enumerate(headings.items()):
            polygon = [{"x": 1, "y": 50}]
            pages[page_number - 1]["lines"].append(
                {
                    "content": text,
                    "page_number": page_number,
                    "polygon": polygon,
                }
            )
            paragraphs.append(
                {
                    "paragraph_index": paragraph_index,
                    "content": text,
                    "page_number": page_number,
                    "role": "sectionHeading",
                    "bounding_regions": [
                        {"page_number": page_number, "polygon": polygon}
                    ],
                }
            )
        payload = {"pages": pages, "paragraphs": paragraphs}

        anchors = detect_heading_anchors(entries, payload, toc_page_indexes=[0])
        alignment = align_document_pages(
            entries,
            anchors,
            azure_page_numbers=range(1, 7),
        )

        self.assertTrue(alignment.requires_human_review)
        self.assertIn("page_alignment_ambiguous", alignment.warnings)
        self.assertNotEqual(alignment.mapping_method, "heading_anchor_consensus")
        sections = build_document_sections(1, entries, anchors, alignment)
        self.assertTrue(
            all(
                section.pdf_page_start is None
                and section.pdf_page_end is None
                for section in sections
            )
        )

    def test_coherent_alternate_heading_set_prevents_silent_wrong_consensus(self):
        entries = extract_toc_entries(
            [
                {"text": "Directors Report 1", "pdf_page_index": 2},
                {
                    "text": "Statement of Financial Position 2",
                    "pdf_page_index": 2,
                },
            ]
        )
        pages = [
            {"page_number": page_number, "height": 1000, "lines": []}
            for page_number in range(1, 7)
        ]
        paragraphs = []
        for paragraph_index, (page_number, text) in enumerate(
            {
                1: "DIRECTORS REPORT",
                2: "STATEMENT OF FINANCIAL POSITION",
            }.items()
        ):
            paragraphs.append(
                {
                    "paragraph_index": paragraph_index,
                    "content": text,
                    "page_number": page_number,
                    "role": "title",
                    "bounding_regions": [
                        {
                            "page_number": page_number,
                            "polygon": [{"x": 1, "y": 20}],
                        }
                    ],
                }
            )
        for page_number, text in {
            5: "Directors Report",
            6: "Statement of Financial Position",
        }.items():
            pages[page_number - 1]["lines"].append(
                {
                    "content": text,
                    "page_number": page_number,
                    "polygon": [{"x": 1, "y": 500}],
                }
            )
        payload = {"pages": pages, "paragraphs": paragraphs}

        anchors = detect_heading_anchors(entries, payload, toc_page_indexes=[2])
        alignment = align_document_pages(
            entries,
            anchors,
            azure_page_numbers=range(1, 7),
        )

        self.assertEqual([anchor.pdf_page_index for anchor in anchors], [0, 1])
        self.assertTrue(alignment.requires_human_review)
        self.assertIn("page_alignment_ambiguous", alignment.warnings)
        self.assertNotEqual(alignment.mapping_method, "heading_anchor_consensus")
        self.assertEqual(
            [
                [
                    (
                        candidate["pdf_page_index"],
                        candidate["azure_page_number"],
                        candidate["match_score"],
                        candidate["match_method"],
                    )
                    for candidate in anchor.alternative_candidates
                ]
                for anchor in anchors
            ],
            [
                [(4, 5, 0.9, "exact_normalized_title")],
                [(5, 6, 0.9, "exact_normalized_title")],
            ],
        )

    def test_same_page_spatial_duplicate_is_retained_as_alternative_evidence(self):
        entries = extract_toc_entries(
            [{"text": "Directors Report 1", "pdf_page_index": 0}]
        )
        near_top = [{"x": 1, "y": 50}]
        lower_page = [{"x": 1, "y": 700}]
        payload = {
            "pages": [
                {"page_number": 1, "height": 1000, "lines": []},
                {
                    "page_number": 2,
                    "height": 1000,
                    "lines": [
                        {
                            "content": "DIRECTORS REPORT",
                            "page_number": 2,
                            "polygon": near_top,
                        },
                        {
                            "content": "DIRECTORS REPORT",
                            "page_number": 2,
                            "polygon": lower_page,
                        },
                    ],
                },
            ],
            "paragraphs": [
                {
                    "paragraph_index": 0,
                    "content": "DIRECTORS REPORT",
                    "page_number": 2,
                    "role": "sectionHeading",
                    "bounding_regions": [
                        {"page_number": 2, "polygon": near_top}
                    ],
                }
            ],
        }

        anchors = detect_heading_anchors(entries, payload, toc_page_indexes=[0])

        self.assertEqual(len(anchors), 1)
        self.assertIn("heading_anchor_same_page_near_tie", anchors[0].warnings)
        self.assertNotIn("heading_anchor_near_tie", anchors[0].warnings)
        self.assertEqual(len(anchors[0].alternative_candidates), 1)
        alternative = anchors[0].alternative_candidates[0]
        self.assertEqual(alternative["source_content_id"], "page:2:line:1")
        self.assertEqual(alternative["bounding_evidence"][0]["polygon"], lower_page)


if __name__ == "__main__":
    unittest.main()
