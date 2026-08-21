import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import settings
from services.toc_aware_document_structure import persist_document_structure
from services.toc_aware_template_classification import (
    ARTIFACT_FILENAME,
    CLASSIFICATION_VERSION,
    analyze_template_classification,
    load_template_classification,
    persist_template_classification,
    template_classification_artifact_path,
)
from tests.template_classification_test_support import section, structure


def source_structure(job_id=101):
    return structure(
        job_id=job_id,
        sections=[
            section(
                canonical_section_type="statement_of_changes_in_equity",
                title="Statement of Changes in Equity",
            )
        ],
    )


def classification(source):
    return asyncio.run(
        analyze_template_classification(
            job_id=source.job_id,
            structure=source,
        )
    )


class TemplateClassificationArtifactTests(unittest.TestCase):
    def test_atomic_fixed_artifact_round_trip_is_tied_to_source_and_registry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                source = source_structure()
                persist_document_structure(source)
                result = classification(source)
                first = persist_template_classification(result, structure=source)
                second = persist_template_classification(result, structure=source)
                loaded = load_template_classification(101)
                artifact_count = len(
                    list(uploads.rglob(ARTIFACT_FILENAME))
                )
                temporary_count = len(list(uploads.rglob("*.tmp")))
        self.assertEqual(first, second)
        self.assertEqual(first.name, "template_classification_19b_v2.json")
        self.assertEqual(loaded.classification_version, CLASSIFICATION_VERSION)
        self.assertEqual(loaded.source_structure_hash, result.source_structure_hash)
        self.assertEqual(
            loaded.canonical_registry_hash,
            "16de7eaeafcdf760c7f4869072a6b0a3925088f6bc260672389b5c502015b7d4",
        )
        self.assertEqual(artifact_count, 1)
        self.assertEqual(temporary_count, 0)

    def test_changed_source_structure_invalidates_old_artifact(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                source = source_structure()
                persist_document_structure(source)
                persist_template_classification(classification(source), structure=source)
                changed = source.model_copy(deep=True)
                changed.warnings.append("changed-source")
                persist_document_structure(changed)
                with self.assertRaisesRegex(ValueError, "stale or invalid"):
                    load_template_classification(101)

    def test_changed_registry_hash_and_missing_19a_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                source = source_structure()
                result = classification(source)
                stale = result.model_copy(deep=True)
                stale.canonical_registry_hash = "0" * 64
                with self.assertRaisesRegex(ValueError, "stale or invalid"):
                    persist_template_classification(stale, structure=source)

                path = template_classification_artifact_path(101)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(result.model_dump_json(), encoding="utf-8")
                with self.assertRaises(FileNotFoundError):
                    load_template_classification(101)

    def test_v1_artifact_is_stale_after_segmentation_semantics_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                source = source_structure()
                persist_document_structure(source)
                result = classification(source)
                stale_path = template_classification_artifact_path(101).with_name(
                    "template_classification_19b_v1.json"
                )
                stale_path.parent.mkdir(parents=True, exist_ok=True)
                stale_path.write_text(result.model_dump_json(), encoding="utf-8")
                with self.assertRaises(FileNotFoundError):
                    load_template_classification(101)


if __name__ == "__main__":
    unittest.main()
