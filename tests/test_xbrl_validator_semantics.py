import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from services.xbrl_validator import XBRLValidator


class DummyScalarResult:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows


class DummyAsyncSession:
    def __init__(self, results):
        self._results = list(results)
        self.execute = AsyncMock(side_effect=self._execute)

    async def _execute(self, _statement):
        if not self._results:
            raise AssertionError("Unexpected database execute call")
        return self._results.pop(0)


def item(
    *,
    template_field_id=None,
    confirmed_tag_id=None,
    value="100.00",
    reviewed=True,
    statement_type="210000",
):
    return SimpleNamespace(
        template_field_id=template_field_id,
        confirmed_tag_id=confirmed_tag_id,
        extracted_value=value,
        is_reviewed=reviewed,
        statement_type=statement_type,
    )


def job_with_items(items):
    return SimpleNamespace(
        company_name="Example Sdn Bhd",
        registration_number="123456-A",
        financial_year_end="2025-12-31",
        pages=[SimpleNamespace(extracted_items=items)],
    )


class XBRLValidatorSemanticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_template_mappings_without_confirmed_tags_are_not_blocking_errors(self):
        validator = XBRLValidator()
        job = job_with_items([
            item(template_field_id="ifrs-smes:Assets"),
            item(template_field_id="ifrs-smes:Liabilities"),
        ])
        db = DummyAsyncSession([
            DummyScalarResult(scalar=job),
            DummyScalarResult(rows=[]),
        ])

        result = await validator.validate_job_for_xbrl(1, db)

        self.assertTrue(result["is_valid"])
        self.assertNotIn("No items have confirmed taxonomy tags", result["errors"])
        self.assertIn(
            "Using template mappings. No manual taxonomy tags confirmed.",
            result["warnings"],
        )
        self.assertEqual(result["statistics"]["items_with_template_mappings"], 2)
        self.assertEqual(result["statistics"]["items_with_mapping_evidence"], 2)
        self.assertEqual(result["statistics"]["reviewed_mappable_items"], 2)

    async def test_template_mapped_reviewed_rows_do_not_report_no_extracted_data(self):
        validator = XBRLValidator()
        visible_item = item(template_field_id="ifrs-smes:Assets", reviewed=True)
        job = SimpleNamespace(
            company_name="Example Sdn Bhd",
            registration_number="123456-A",
            financial_year_end="2025-12-31",
            pages=[],
        )
        db = DummyAsyncSession([
            DummyScalarResult(scalar=job),
            DummyScalarResult(rows=[visible_item]),
            DummyScalarResult(rows=[]),
        ])

        result = await validator.validate_job_for_xbrl(1, db)

        self.assertNotIn("No extracted data items found", result["errors"])
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["statistics"]["total_items"], 1)
        self.assertEqual(result["statistics"]["reviewed_items"], 1)
        self.assertEqual(result["statistics"]["reviewed_mappable_items"], 1)

    async def test_zero_extracted_rows_still_report_clear_error(self):
        validator = XBRLValidator()
        job = job_with_items([])
        db = DummyAsyncSession([
            DummyScalarResult(scalar=job),
            DummyScalarResult(rows=[]),
        ])

        result = await validator.validate_job_for_xbrl(1, db)

        self.assertFalse(result["is_valid"])
        self.assertIn("No extracted data items found", result["errors"])
        self.assertEqual(result["statistics"]["total_items"], 0)
        self.assertEqual(result["statistics"]["reviewed_mappable_items"], 0)

    async def test_unmapped_rows_are_reported_as_warnings(self):
        validator = XBRLValidator()
        job = job_with_items([
            item(template_field_id=None, confirmed_tag_id=None),
            item(template_field_id="ifrs-smes:Assets", confirmed_tag_id=None),
        ])
        db = DummyAsyncSession([
            DummyScalarResult(scalar=job),
            DummyScalarResult(rows=[]),
        ])

        result = await validator.validate_job_for_xbrl(1, db)

        self.assertTrue(result["is_valid"])
        self.assertNotIn("No items have confirmed taxonomy tags", result["errors"])
        self.assertIn(
            "1/2 extracted rows are unmapped and may not be included in generated XBRL.",
            result["warnings"],
        )

    async def test_extracted_rows_without_reviewed_mappable_rows_get_precise_warning(self):
        validator = XBRLValidator()
        job = job_with_items([
            item(template_field_id=None, confirmed_tag_id=None, reviewed=False),
        ])
        db = DummyAsyncSession([
            DummyScalarResult(scalar=job),
            DummyScalarResult(rows=[]),
        ])

        result = await validator.validate_job_for_xbrl(1, db)

        self.assertTrue(result["is_valid"])
        self.assertNotIn("No extracted data items found", result["errors"])
        self.assertIn(
            "Extracted rows exist, but no reviewed mappable rows were found.",
            result["warnings"],
        )
        self.assertEqual(result["statistics"]["reviewed_mappable_items"], 0)


if __name__ == "__main__":
    unittest.main()
