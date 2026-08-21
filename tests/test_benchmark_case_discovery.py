import tempfile
import unittest
from pathlib import Path

from scripts.discover_benchmark_cases import discover_benchmark_cases


def touch(path: Path, content: str = "x") -> None:
    path.write_text(content, encoding="utf-8")


class BenchmarkCaseDiscoveryTests(unittest.TestCase):
    def discover_one(self, setup):
        with tempfile.TemporaryDirectory() as directory:
            cases_dir = Path(directory) / "benchmark_cases"
            case_dir = cases_dir / "001-case"
            case_dir.mkdir(parents=True)
            setup(case_dir)
            manifest = discover_benchmark_cases(cases_dir)
            return manifest["cases"][0]

    def test_one_pdf_one_xml_is_ready(self):
        case = self.discover_one(lambda folder: (touch(folder / "Any Name.pdf"), touch(folder / "Any Name.xml")))
        self.assertEqual(case["status"], "ready")
        self.assertEqual(case["reference_type"], "xml")
        self.assertFalse(case["metadata_required"])

    def test_one_pdf_one_xbrl_is_ready(self):
        case = self.discover_one(lambda folder: (touch(folder / "report.pdf"), touch(folder / "reference.xbrl")))
        self.assertEqual(case["status"], "ready")
        self.assertEqual(case["reference_type"], "xbrl")

    def test_missing_pdf(self):
        case = self.discover_one(lambda folder: touch(folder / "reference.xml"))
        self.assertEqual(case["status"], "missing_pdf")

    def test_missing_reference(self):
        case = self.discover_one(lambda folder: touch(folder / "source.pdf"))
        self.assertEqual(case["status"], "missing_reference")

    def test_multiple_pdfs(self):
        case = self.discover_one(lambda folder: (touch(folder / "a.pdf"), touch(folder / "b.pdf"), touch(folder / "ref.xml")))
        self.assertEqual(case["status"], "ambiguous_pdf")
        self.assertEqual(len(case["pdf_files"]), 2)

    def test_multiple_references(self):
        case = self.discover_one(lambda folder: (touch(folder / "a.pdf"), touch(folder / "ref.xml"), touch(folder / "ref.xbrl")))
        self.assertEqual(case["status"], "ambiguous_reference")
        self.assertEqual(len(case["reference_files"]), 2)

    def test_metadata_json_not_required(self):
        case = self.discover_one(lambda folder: (touch(folder / "a.pdf"), touch(folder / "ref.xml")))
        self.assertNotIn("metadata.json", [item["name"] for item in case["file_inventory"]])
        self.assertEqual(case["status"], "ready")


if __name__ == "__main__":
    unittest.main()
