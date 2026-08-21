import asyncio
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from config import settings
from services.section_aware_initial_mapping import (
    build_document_initial_mapping,
    load_initial_mapping,
    persist_initial_mapping,
)
from services.section_aware_initial_mapping_llm import InitialMappingLLMConfig
from services.toc_aware_document_structure import (
    ARTIFACT_SUBDIRECTORY,
    ARTIFACT_FILENAME,
    FEATURE_VERSION,
    document_structure_artifact_path,
    load_document_structure,
    persist_document_structure,
)
from services.toc_aware_template_classification import load_template_classification
from tests.section_aware_mapping_test_support import persist_mapping_sources


class TocAwareArtifactStalenessTests(unittest.TestCase):
    def test_v1_v2_and_v3_structure_artifacts_are_not_silently_reused_by_v4(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                legacy = (
                    uploads
                    / ARTIFACT_SUBDIRECTORY
                    / "job_101"
                    / "structure_19a_v1.json"
                )
                legacy.parent.mkdir(parents=True, exist_ok=True)
                legacy.write_text(
                    '{"job_id":101,"feature_version":"19A-v1"}',
                    encoding="utf-8",
                )

                legacy_v2 = (
                    uploads
                    / ARTIFACT_SUBDIRECTORY
                    / "job_101"
                    / "structure_19a_v2.json"
                )
                legacy_v2.write_text(
                    '{"job_id":101,"feature_version":"19A-v2"}',
                    encoding="utf-8",
                )
                legacy_v3 = (
                    uploads
                    / ARTIFACT_SUBDIRECTORY
                    / "job_101"
                    / "structure_19a_v3.json"
                )
                legacy_v3.write_text(
                    '{"job_id":101,"feature_version":"19A-v3"}',
                    encoding="utf-8",
                )
                self.assertEqual(FEATURE_VERSION, "19A-v4")
                self.assertEqual(ARTIFACT_FILENAME, "structure_19a_v4.json")
                self.assertNotEqual(legacy, document_structure_artifact_path(101))
                with self.assertRaises(FileNotFoundError):
                    load_document_structure(101)

    def test_changed_v4_structure_invalidates_19b_and_19c_hashes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            uploads = Path(temp_dir) / "uploads"
            with patch.object(settings, "upload_directory", str(uploads)):
                structure, _classification, rows = persist_mapping_sources()
                mapping = asyncio.run(
                    build_document_initial_mapping(
                        job_id=101,
                        filing_id=101,
                        source_rows=rows,
                        llm_config=InitialMappingLLMConfig(
                            mode="deterministic_only"
                        ),
                    )
                )
                persist_initial_mapping(mapping)
                changed = structure.model_copy(deep=True)
                changed.warnings.append("19a-v4-source-changed")
                persist_document_structure(changed)

                with self.assertRaisesRegex(ValueError, "stale or invalid"):
                    load_template_classification(101)
                with self.assertRaisesRegex(ValueError, "stale or invalid"):
                    load_initial_mapping(101)


if __name__ == "__main__":
    unittest.main()
