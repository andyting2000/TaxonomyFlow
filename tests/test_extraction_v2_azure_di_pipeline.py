import unittest

from services.extraction_v2_azure_di_pipeline import (
    build_azure_di_report,
    convert_azure_di_result_to_candidates,
)


def table_result(rows, *, content="Statement of Financial Position", model_id="prebuilt-layout"):
    cells = []
    for row_index, row in enumerate(rows):
        for col_index, value in enumerate(row):
            cells.append(
                {
                    "content": value,
                    "row_index": row_index,
                    "column_index": col_index,
                    "page_number": 1,
                    "bounding_regions": [{"page_number": 1}],
                }
            )
    return {
        "ok": True,
        "model_id": model_id,
        "content": content,
        "content_length": len(content),
        "pages_count": 1,
        "lines": [{"content": content, "page_number": 1}],
        "paragraphs": [],
        "tables": [{"table_index": 0, "row_count": len(rows), "column_count": len(rows[0]), "page_numbers": [1], "cells": cells}],
        "table_cells": cells,
    }


def paragraph_result(paragraphs):
    return {
        "ok": True,
        "model_id": "prebuilt-layout",
        "content": "\n".join(paragraphs),
        "content_length": sum(len(item) for item in paragraphs),
        "pages_count": 1,
        "lines": [{"content": text, "page_number": 1} for text in paragraphs],
        "paragraphs": [
            {"paragraph_index": idx, "content": text, "page_number": 1, "bounding_regions": [{"page_number": 1}]}
            for idx, text in enumerate(paragraphs)
        ],
        "tables": [],
        "table_cells": [],
    }


class ExtractionV2AzureDIPipelineTests(unittest.TestCase):
    def convert(self, result):
        return convert_azure_di_result_to_candidates(result, case_id="case-a", source_pdf="case-a.pdf")

    def test_table_row_with_label_and_one_amount_becomes_numeric_fact(self):
        rows = [["Description", "2024"], ["Cash and bank balances", "1,234"]]
        candidates = self.convert(table_result(rows))
        self.assertEqual(candidates[0]["row_type"], "numeric_fact")
        self.assertEqual(candidates[0]["value"], "1234")

    def test_table_row_with_label_and_two_year_values_becomes_comparative_numeric_fact(self):
        rows = [["Description", "2024", "2023"], ["Cash", "1,234", "1,000"]]
        candidates = self.convert(table_result(rows))
        self.assertEqual(candidates[0]["row_type"], "comparative_numeric_fact")
        self.assertEqual(candidates[0]["value"], "1234")
        self.assertEqual(candidates[0]["previous_value"], "1000")

    def test_table_of_contents_table_is_not_converted_to_financial_facts(self):
        rows = [["Contents", "Page"], ["Directors' Report", "2"], ["Statement by Directors", "5"]]
        candidates = self.convert(table_result(rows, content="Contents Page"))
        self.assertFalse([item for item in candidates if item["row_type"] in {"numeric_fact", "comparative_numeric_fact"}])

    def test_pure_page_number_index_rows_become_metadata_or_are_skipped(self):
        rows = [["Index", "Page"], ["Notes to the Financial Statements", "12"]]
        candidates = self.convert(table_result(rows, content="Index Page"))
        self.assertTrue(all(item["row_type"] == "metadata" for item in candidates))

    def test_directors_report_paragraph_becomes_text_block(self):
        result = paragraph_result(
            [
                "Directors' Report",
                "The directors hereby submit their report and the audited financial statements for the financial year ended 31 December 2024.",
            ]
        )
        candidates = self.convert(result)
        self.assertTrue(any(item["row_type"] == "text_block" for item in candidates))

    def test_short_heading_only_line_becomes_heading_not_text_block(self):
        result = paragraph_result(["Directors' Report"])
        candidates = self.convert(result)
        self.assertEqual(candidates[0]["row_type"], "heading")

    def test_negative_amounts_are_preserved(self):
        rows = [["Description", "2024"], ["Loss for the year", "(1,234)"]]
        candidates = self.convert(table_result(rows))
        self.assertEqual(candidates[0]["value"], "-1234")

    def test_percent_column_is_not_mistaken_for_prior_year_amount(self):
        rows = [["Description", "2024", "%"], ["Gross profit", "1,234", "25%"]]
        candidates = self.convert(table_result(rows))
        self.assertEqual(candidates[0]["row_type"], "numeric_fact")
        self.assertIsNone(candidates[0]["previous_value"])
        self.assertIn("percent_column_preserved_not_prior_year", candidates[0]["warnings"])

    def test_account_code_column_is_preserved_as_provenance_not_label_pollution(self):
        rows = [["Code", "Description", "2024"], ["AFF-1103", "Cash", "1,234"]]
        candidates = self.convert(table_result(rows))
        self.assertEqual(candidates[0]["label"], "Cash")
        self.assertEqual(candidates[0]["provenance"]["account_code"], "AFF-1103")

    def test_candidate_provenance_includes_page_table_row_cell(self):
        rows = [["Description", "2024"], ["Cash", "1,234"]]
        candidate = self.convert(table_result(rows))[0]
        self.assertEqual(candidate["page_number"], 1)
        self.assertEqual(candidate["provenance"]["table_index"], 0)
        self.assertEqual(candidate["provenance"]["row_index"], 1)
        self.assertIn(1, candidate["provenance"]["cell_indexes"])

    def test_no_db_mutation_metadata_is_false(self):
        report = build_azure_di_report(
            [],
            cases_dir="benchmark_cases",
            output_json="memory.json",
            run_id="test",
            model_id="prebuilt-layout",
        )
        self.assertFalse(report["run_metadata"]["database_mutated"])
        self.assertFalse(report["run_metadata"]["production_behavior_changed"])


if __name__ == "__main__":
    unittest.main()
