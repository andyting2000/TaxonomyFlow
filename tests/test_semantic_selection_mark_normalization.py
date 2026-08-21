import unittest

from services.section_title_normalization import (
    normalize_section_title,
    normalize_title_text,
)
from services.toc_entry_extractor import extract_toc_entries


class SemanticSelectionMarkNormalizationTests(unittest.TestCase):
    def test_toc_semantic_title_strips_selection_state_but_preserves_source(self):
        source = "Statutory Declaration :unselected 6"
        entry = extract_toc_entries(
            [{"text": source, "pdf_page_index": 1, "source_content_id": "line-1"}]
        )[0]

        self.assertEqual(entry.source_text, source)
        self.assertEqual(entry.raw_title, "Statutory Declaration")
        self.assertEqual(entry.normalized_title, "statutory declaration")
        self.assertEqual(entry.canonical_section_hint, "statutory_declaration")
        self.assertIn("selection_state_marker_removed", entry.parse_warnings)

    def test_semantic_normalizers_strip_marker_variants(self):
        for value in (
            "Statutory Declaration:selected",
            "Statutory Declaration : unselected",
            "Statutory Declaration :unselected,",
        ):
            with self.subTest(value=value):
                self.assertEqual(normalize_title_text(value), "statutory declaration")
                self.assertEqual(
                    normalize_section_title(value).canonical_section_type,
                    "statutory_declaration",
                )


if __name__ == "__main__":
    unittest.main()
