from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import file_safety
from config import settings
from services.xbrl_generator import XBRLGenerator, validate_xbrl_content


def make_upload(filename: str, content: bytes, content_type: str = "application/pdf"):
    return SimpleNamespace(
        filename=filename,
        content_type=content_type,
        file=BytesIO(content),
    )


class FileParserSafetyTests(unittest.TestCase):
    def test_pdf_upload_rejects_extension_only_spoof(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            upload = make_upload("statement.pdf", b"not a pdf")
            destination = Path(temp_dir) / "statement.pdf"

            file_safety.validate_pdf_upload_metadata(upload)
            with patch.object(settings, "max_file_size", 1024):
                with self.assertRaises(HTTPException) as raised:
                    file_safety.save_bounded_pdf_upload(upload, destination)

            self.assertEqual(raised.exception.status_code, 400)
            self.assertEqual(raised.exception.detail, "Invalid PDF file")

    def test_pdf_upload_stream_size_is_enforced(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            upload = make_upload("statement.pdf", file_safety.PDF_MAGIC + b"123")
            destination = Path(temp_dir) / "statement.pdf"

            with patch.object(settings, "max_file_size", len(file_safety.PDF_MAGIC) + 1):
                with self.assertRaises(HTTPException) as raised:
                    file_safety.save_bounded_pdf_upload(upload, destination)

            self.assertEqual(raised.exception.status_code, 400)
            self.assertEqual(raised.exception.detail, "File size exceeds maximum limit")

    def test_upload_path_resolver_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            uploads = temp_path / "uploads"
            outside = temp_path / "outside.pdf"
            outside.write_bytes(file_safety.PDF_MAGIC + b"\n")

            with patch.object(settings, "upload_directory", str(uploads)):
                with self.assertRaises(HTTPException) as raised:
                    file_safety.resolve_upload_path(str(outside), "pdfs")

            self.assertEqual(raised.exception.status_code, 404)

    def test_xbrl_validation_rejects_doctype_entity(self):
        xml = """<?xml version="1.0"?>
<!DOCTYPE xbrl [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<xbrl xmlns="http://www.xbrl.org/2003/instance">&xxe;</xbrl>
"""

        result = validate_xbrl_content(xml)

        self.assertIs(result["valid"], False)
        self.assertIn("DOCTYPE", result["error"])

    def test_xbrl_filename_sanitizes_registration_number(self):
        job = SimpleNamespace(
            registration_number="../../evil/name",
            financial_year_end=SimpleNamespace(strftime=lambda fmt: "20260423"),
        )

        filename = XBRLGenerator()._generate_filename(job)

        self.assertEqual(filename, "SSM_FS-MPERS_evil_name_20260423.xbrl")
        self.assertNotIn("/", filename)
        self.assertNotIn("\\", filename)


if __name__ == "__main__":
    unittest.main()
