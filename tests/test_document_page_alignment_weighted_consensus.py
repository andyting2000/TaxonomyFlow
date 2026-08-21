import unittest

from schemas import HeadingAnchor
from services.document_page_alignment import align_document_pages
from services.toc_entry_extractor import extract_toc_entries


def anchor(index, entry, pdf_page_index, *, trusted=True, confidence=0.98, method="exact_normalized_title"):
    return HeadingAnchor(
        anchor_id=f"anchor-{index}",
        toc_entry_id=entry.entry_id,
        source_content_id=f"heading-{index}",
        toc_title=entry.raw_title,
        matched_heading=entry.raw_title if trusted else "TO",
        pdf_page_index=pdf_page_index,
        azure_page_number=pdf_page_index + 1,
        match_score=confidence,
        match_method=method,
        lexical_score=confidence,
        token_coverage=1.0 if trusted else 0.0,
        expected_token_coverage=1.0 if trusted else 0.0,
        candidate_token_coverage=1.0 if trusted else 0.0,
        length_ratio=1.0 if trusted else 0.1,
        heading_quality_score=1.0 if trusted else 0.0,
        trusted=trusted,
        rejection_reason=None if trusted else "candidate_heading_too_short",
        confidence=confidence,
        text_evidence=entry.raw_title if trusted else "TO",
    )


class DocumentPageAlignmentWeightedConsensusTests(unittest.TestCase):
    def test_five_strong_plus_one_anchors_ignore_rejected_noise(self):
        entries = extract_toc_entries(
            [
                {"text": "Statement of Financial Position 11", "pdf_page_index": 0},
                {"text": "Statement of Comprehensive Income 12", "pdf_page_index": 0},
                {"text": "Statement of Changes in Equity 13", "pdf_page_index": 0},
                {"text": "Statement of Cash Flows 14", "pdf_page_index": 0},
                {"text": "Notes to Financial Statements 15-22", "pdf_page_index": 0},
                {"text": "Statement by Directors 5", "pdf_page_index": 0},
                {"text": "Statutory Declaration 6", "pdf_page_index": 0},
            ]
        )
        anchors = [
            anchor(index, entry, entry.printed_page_start + 1)
            for index, entry in enumerate(entries[:5], start=1)
        ]
        anchors.extend(
            [
                anchor(6, entries[5], 25, trusted=False, confidence=0.2, method="rejected"),
                anchor(7, entries[6], 2, trusted=False, confidence=0.2, method="rejected"),
            ]
        )

        result = align_document_pages(entries, anchors, azure_page_numbers=range(1, 25))

        self.assertEqual(result.offset_candidates, {1: 5})
        self.assertEqual(result.trusted_anchor_count, 5)
        self.assertEqual(result.rejected_anchor_count, 2)
        self.assertGreaterEqual(result.confidence, 0.9)
        self.assertFalse(result.requires_human_review)
        self.assertEqual(result.mapping_method, "weighted_heading_anchor_consensus")


if __name__ == "__main__":
    unittest.main()
