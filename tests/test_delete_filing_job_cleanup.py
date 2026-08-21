from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from config import settings
from routers.filings import delete_filing_job

TEST_USER = SimpleNamespace(id=1, email="owner@example.com", is_active=True)


class DummyResult:
    def __init__(self, scalar=None):
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class DummyAsyncSession:
    def __init__(self, job):
        self.job = job
        self.execute = AsyncMock(return_value=DummyResult(job))
        self.delete = AsyncMock()
        self.commit = AsyncMock()
        self.rollback = AsyncMock()


def make_item(item_id):
    return SimpleNamespace(id=item_id)


def make_page(page_id, image_path, extracted_items):
    return SimpleNamespace(
        id=page_id,
        image_path=str(image_path) if image_path is not None else None,
        extracted_items=extracted_items,
    )


def make_job(job_id, source_pdf_path, pages, registration_number="ABC/123", status="REVIEW"):
    return SimpleNamespace(
        id=job_id,
        user_id=TEST_USER.id,
        source_pdf_path=str(source_pdf_path) if source_pdf_path is not None else None,
        pages=pages,
        registration_number=registration_number,
        financial_year_end=datetime(2026, 12, 31),
        status=status,
    )


class DeleteFilingJobCleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_delete_job_removes_db_record_children_and_owned_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            page_dir = uploads / "pages"
            xbrl_dir = uploads / "xbrl"
            pdf_dir.mkdir(parents=True)
            page_dir.mkdir(parents=True)
            xbrl_dir.mkdir(parents=True)

            source_pdf = pdf_dir / "source.pdf"
            page_image_1 = page_dir / "job-7-page-1.png"
            page_image_2 = page_dir / "job-7-page-2.png"
            generated_xbrl = xbrl_dir / "SSM_FS-MPERS_ABC_123_20261231.xbrl"
            generated_xml = xbrl_dir / "SSM_FS-MPERS_ABC_123_20261231.xml"
            unrelated_xbrl = xbrl_dir / "SSM_FS-MPERS_OTHER_20261231.xbrl"

            for path in (source_pdf, page_image_1, page_image_2, generated_xbrl, generated_xml, unrelated_xbrl):
                path.write_bytes(b"artifact")

            job = make_job(
                7,
                source_pdf,
                [
                    make_page("page-1", page_image_1, [make_item("item-1"), make_item("item-2")]),
                    make_page("page-2", page_image_2, [make_item("item-3")]),
                ],
            )
            db = DummyAsyncSession(job)

            with patch.object(settings, "upload_directory", str(uploads)):
                response = await delete_filing_job(7, db, TEST_USER)

            self.assertTrue(response["deleted_job"])
            self.assertEqual(response["job_id"], 7)
            self.assertEqual(response["deleted_pages_count"], 2)
            self.assertEqual(response["deleted_extracted_items_count"], 3)
            self.assertEqual(response["deleted_files_count"], 5)
            self.assertFalse(source_pdf.exists())
            self.assertFalse(page_image_1.exists())
            self.assertFalse(page_image_2.exists())
            self.assertFalse(generated_xbrl.exists())
            self.assertFalse(generated_xml.exists())
            self.assertTrue(unrelated_xbrl.exists())
            db.delete.assert_awaited_once_with(job)
            db.commit.assert_awaited_once()
            db.rollback.assert_not_awaited()

    async def test_processing_job_can_be_deleted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            source_pdf = pdf_dir / "processing.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\n")

            job = make_job(17, source_pdf, [], status="PROCESSING")
            db = DummyAsyncSession(job)

            with patch.object(settings, "upload_directory", str(uploads)):
                response = await delete_filing_job(17, db, TEST_USER)

            self.assertTrue(response["deleted_job"])
            self.assertEqual(response["job_id"], 17)
            self.assertFalse(source_pdf.exists())
            db.delete.assert_awaited_once_with(job)
            db.commit.assert_awaited_once()
            db.rollback.assert_not_awaited()

    async def test_delete_response_shape_is_stable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            (uploads / "pdfs").mkdir(parents=True)
            job = make_job(18, None, [])
            db = DummyAsyncSession(job)

            with patch.object(settings, "upload_directory", str(uploads)):
                response = await delete_filing_job(18, db, TEST_USER)

            self.assertEqual(
                set(response.keys()),
                {
                    "deleted_job",
                    "job_id",
                    "deleted_pages_count",
                    "deleted_extracted_items_count",
                    "deleted_files_count",
                    "deleted_files",
                    "skipped_files",
                    "warnings",
                },
            )

    async def test_unsafe_and_missing_files_are_skipped_without_blocking_db_delete(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            uploads = root / "uploads"
            pdf_dir = uploads / "pdfs"
            page_dir = uploads / "pages"
            pdf_dir.mkdir(parents=True)
            page_dir.mkdir(parents=True)

            outside_pdf = root / "outside.pdf"
            outside_image = root / "outside.png"
            missing_page_image = page_dir / "missing-page.png"
            outside_pdf.write_bytes(b"%PDF-1.4\n")
            outside_image.write_bytes(b"image")

            job = make_job(
                8,
                outside_pdf,
                [
                    make_page("page-1", outside_image, [make_item("item-1")]),
                    make_page("page-2", missing_page_image, []),
                ],
                registration_number="UNSAFE",
            )
            db = DummyAsyncSession(job)

            with patch.object(settings, "upload_directory", str(uploads)):
                response = await delete_filing_job(8, db, TEST_USER)

            reasons = [item["reason"] for item in response["skipped_files"]]
            self.assertIn("unsafe_or_not_owned_by_job", reasons)
            self.assertIn("missing", reasons)
            self.assertTrue(outside_pdf.exists())
            self.assertTrue(outside_image.exists())
            self.assertTrue(response["deleted_job"])
            db.delete.assert_awaited_once_with(job)
            db.commit.assert_awaited_once()

    async def test_missing_job_returns_404_and_does_not_delete_files(self):
        db = DummyAsyncSession(None)

        with self.assertRaises(HTTPException) as raised:
            await delete_filing_job(999999, db, TEST_USER)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(raised.exception.detail, "Filing job not found")
        db.delete.assert_not_awaited()
        db.commit.assert_not_awaited()

    async def test_db_failure_prevents_file_deletion_and_rolls_back(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            pdf_dir = uploads / "pdfs"
            pdf_dir.mkdir(parents=True)
            source_pdf = pdf_dir / "source.pdf"
            source_pdf.write_bytes(b"%PDF-1.4\n")

            job = make_job(9, source_pdf, [])
            db = DummyAsyncSession(job)
            db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))

            with patch.object(settings, "upload_directory", str(uploads)):
                with self.assertRaises(HTTPException) as raised:
                    await delete_filing_job(9, db, TEST_USER)

            self.assertEqual(raised.exception.status_code, 500)
            self.assertTrue(source_pdf.exists())
            db.rollback.assert_awaited_once()

    async def test_route_cleanup_scope_does_not_query_unrelated_tables(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            (uploads / "pdfs").mkdir(parents=True)
            job = make_job(10, None, [])
            db = DummyAsyncSession(job)

            with patch.object(settings, "upload_directory", str(uploads)):
                await delete_filing_job(10, db, TEST_USER)

            db.execute.assert_awaited_once()

    async def test_delete_does_not_delete_unrelated_job_object(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            (uploads / "pdfs").mkdir(parents=True)
            target_job = make_job(11, None, [])
            unrelated_job = make_job(12, None, [])
            db = DummyAsyncSession(target_job)

            with patch.object(settings, "upload_directory", str(uploads)):
                await delete_filing_job(11, db, TEST_USER)

            db.delete.assert_awaited_once_with(target_job)
            self.assertNotEqual(db.delete.await_args.args[0], unrelated_job)


if __name__ == "__main__":
    unittest.main()
