import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from config import settings
from services.section_aware_initial_mapping import (
    ARTIFACT_FILENAME,
    MAPPING_VERSION,
    InitialMappingArtifactPersistenceError,
    InitialMappingStageError,
    build_document_initial_mapping,
    initial_mapping_artifact_path,
    load_initial_mapping,
    persist_initial_mapping,
)
from services.section_aware_initial_mapping_llm import InitialMappingLLMConfig
from services.toc_aware_document_structure import (
    document_structure_artifact_path,
    persist_document_structure,
)
from services.toc_aware_template_classification import (
    document_structure_hash,
    persist_template_classification,
    template_classification_artifact_path,
)
from tests.section_aware_mapping_test_support import persist_mapping_sources


class InitialMappingArtifactTests(unittest.TestCase):
    def test_current_semantic_contract_is_explicitly_versioned(self):
        self.assertEqual(MAPPING_VERSION, "19C-v2")
        self.assertEqual(ARTIFACT_FILENAME, "initial_mapping_19c_v2.json")

    def build(self, source_rows):
        return asyncio.run(
            build_document_initial_mapping(
                job_id=101,
                filing_id=101,
                source_rows=source_rows,
                llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
            )
        )

    def test_atomic_round_trip_binds_every_authoritative_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                _structure, _classification, rows = persist_mapping_sources()
                result = self.build(rows)
                first = persist_initial_mapping(result)
                second = persist_initial_mapping(result)
                loaded = load_initial_mapping(101)
                temp_files = list(Path(temp_dir).rglob("*.tmp"))
        self.assertEqual(first, second)
        self.assertEqual(loaded.source_structure_hash, result.source_structure_hash)
        self.assertEqual(loaded.source_classification_hash, result.source_classification_hash)
        self.assertEqual(loaded.registry_hash, "16de7eaeafcdf760c7f4869072a6b0a3925088f6bc260672389b5c502015b7d4")
        self.assertEqual(loaded.concept_inventory_hash, result.concept_inventory_hash)
        self.assertEqual(loaded.llm_calls, 0)
        self.assertEqual(temp_files, [])
        self.assertEqual(loaded.safety_summary["source_rows_dropped"], 0)
        self.assertEqual(loaded.safety_summary["confirmed_tag_id_mutations"], 0)
        self.assertEqual(loaded.safety_summary["final_mapping_mutations"], 0)

    def test_changed_structure_and_tampered_concept_hash_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                structure, _classification, rows = persist_mapping_sources()
                result = self.build(rows)
                persist_initial_mapping(result)
                changed = structure.model_copy(deep=True)
                changed.warnings.append("changed")
                persist_document_structure(changed)
                with self.assertRaisesRegex(ValueError, "stale or invalid"):
                    load_initial_mapping(101)

                # Restore authoritative sources, then tamper only the #19C hash.
                structure, _classification, rows = persist_mapping_sources()
                result = self.build(rows)
                result.concept_inventory_hash = "0" * 64
                path = initial_mapping_artifact_path(101)
                valid = self.build(rows)
                persist_initial_mapping(valid)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["concept_inventory_hash"] = "0" * 64
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "concept_inventory_hash"):
                    load_initial_mapping(101)

    def test_tampered_classification_and_registry_hashes_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                _structure, _classification, rows = persist_mapping_sources()
                result = self.build(rows)
                persist_initial_mapping(result)
                path = initial_mapping_artifact_path(101)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["source_classification_hash"] = "1" * 64
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "classification_hash"):
                    load_initial_mapping(101)

                result = self.build(rows)
                persist_initial_mapping(result)
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["registry_hash"] = "2" * 64
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "registry_hash"):
                    load_initial_mapping(101)

    def test_duplicates_conflicts_and_all_rows_are_retained(self):
        candidates = [
            {"original_candidate_id": "a", "row_type": "numeric_fact", "label": "Revenue", "value": "100", "page_number": 2},
            {"original_candidate_id": "b", "row_type": "numeric_fact", "label": "Revenue", "value": "100", "page_number": 2},
            {"original_candidate_id": "c", "row_type": "numeric_fact", "label": "Revenue", "value": "90", "page_number": 3},
            {"original_candidate_id": "d", "row_type": "heading", "label": "Revenue note", "page_number": 3},
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                _structure, _classification, rows = persist_mapping_sources(group_ids=("310000",), candidates=candidates)
                result = self.build(rows)
        self.assertEqual(result.total_rows, 4)
        self.assertEqual(len(result.mappings), 4)
        self.assertTrue(any(item["conflict_type"] == "exact_duplicate" for item in result.conflicts))
        self.assertTrue(any(item["conflict_type"] == "competing_source_rows" for item in result.conflicts))
        self.assertEqual(sum(item.row_eligibility.outcome == "duplicate_row" for item in result.mappings), 1)

    def test_writer_lifecycle_success_and_exact_failure_reasons(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                _structure, _classification, rows = persist_mapping_sources()
                result = self.build(rows)
                events = []
                persist_initial_mapping(result, lifecycle_callback=events.append)
                self.assertEqual(
                    events,
                    [
                        "writer_invoked",
                        "serialization_completed",
                        "atomic_temp_write_completed",
                        "rename_completed",
                        "post_write_validation_completed",
                    ],
                )

                failure_cases = (
                    (
                        "services.section_aware_initial_mapping._serialize_initial_mapping",
                        "artifact_serialization_failed",
                    ),
                    (
                        "services.section_aware_initial_mapping._write_initial_mapping_temp",
                        "artifact_write_failed",
                    ),
                    (
                        "services.section_aware_initial_mapping._replace_initial_mapping_artifact",
                        "artifact_write_failed",
                    ),
                    (
                        "services.section_aware_initial_mapping._validate_published_initial_mapping",
                        "artifact_validation_failed",
                    ),
                )
                for target, reason in failure_cases:
                    with self.subTest(reason=reason, target=target):
                        if initial_mapping_artifact_path(101).exists():
                            initial_mapping_artifact_path(101).unlink()
                        events = []
                        with patch(target, side_effect=OSError("synthetic secret-bearing failure")):
                            with self.assertRaises(InitialMappingArtifactPersistenceError) as raised:
                                persist_initial_mapping(
                                    result,
                                    lifecycle_callback=events.append,
                                )
                        self.assertEqual(raised.exception.reason_code, reason)
                        self.assertEqual(events[0], "writer_invoked")
                        self.assertFalse(initial_mapping_artifact_path(101).exists())

    def test_candidate_failures_are_row_local_and_mapping_failures_are_stage_specific(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                _structure, _classification, rows = persist_mapping_sources()
                events = []
                with patch(
                    "services.section_aware_initial_mapping.retrieve_section_aware_candidates",
                    side_effect=RuntimeError("candidate failure"),
                ):
                    retrieval_result = asyncio.run(
                        build_document_initial_mapping(
                            job_id=101,
                            filing_id=101,
                            source_rows=rows,
                            llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
                            stage_callback=lambda stage, status, detail: events.append(
                                (stage, status, detail.get("reason_code"))
                            ),
                        )
                    )
                self.assertEqual(retrieval_result.failed_rows, 1)
                self.assertEqual(
                    retrieval_result.mappings[0].decision,
                    "retrieval_failed",
                )
                self.assertIn(
                    ("19C_candidate_retrieval", "completed", None),
                    events,
                )

                events = []
                with patch(
                    "services.section_aware_initial_mapping.run_bounded_initial_mapping_llm",
                    new=AsyncMock(side_effect=RuntimeError("mapping failure")),
                ):
                    with self.assertRaises(InitialMappingStageError) as mapping_error:
                        asyncio.run(
                            build_document_initial_mapping(
                                job_id=101,
                                filing_id=101,
                                source_rows=rows,
                                llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
                                stage_callback=lambda stage, status, detail: events.append(
                                    (stage, status, detail.get("reason_code"))
                                ),
                            )
                        )
                self.assertEqual(mapping_error.exception.reason_code, "mapping_build_failed")
                self.assertIn(("19C_candidate_retrieval", "completed", None), events)
                self.assertIn(("19C_mapping_build", "failed", "mapping_build_failed"), events)

    def test_zero_eligible_rows_is_explicit_and_still_publishes_advisory_artifact(self):
        candidates = [
            {
                "original_candidate_id": "heading-only",
                "row_type": "heading",
                "label": "Statement heading",
                "page_number": 2,
            }
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                _structure, _classification, rows = persist_mapping_sources(candidates=candidates)
                events = []
                result = asyncio.run(
                    build_document_initial_mapping(
                        job_id=101,
                        filing_id=101,
                        source_rows=rows,
                        llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
                        stage_callback=lambda stage, status, detail: events.append(
                            (stage, status, detail.get("reason_code"))
                        ),
                    )
                )
                persist_initial_mapping(result)
                loaded = load_initial_mapping(101)

        self.assertEqual(loaded.eligible_rows, 0)
        self.assertIn(
            ("19C_candidate_retrieval", "completed", "zero_eligible_rows"),
            events,
        )

    def test_stale_sources_get_stage_specific_reasons(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                _structure, _classification, rows = persist_mapping_sources()
                structure_path = document_structure_artifact_path(101)
                structure_payload = json.loads(structure_path.read_text(encoding="utf-8"))
                structure_payload["feature_version"] = "19A-stale"
                structure_path.write_text(json.dumps(structure_payload), encoding="utf-8")
                with self.assertRaises(InitialMappingStageError) as stale_structure:
                    self.build(rows)
                self.assertEqual(
                    stale_structure.exception.reason_code,
                    "upstream_structure_invalid",
                )

                _structure, _classification, rows = persist_mapping_sources()
                template_classification_artifact_path(101).unlink()
                with self.assertRaises(InitialMappingStageError) as missing_classification:
                    self.build(rows)
                self.assertEqual(
                    missing_classification.exception.reason_code,
                    "upstream_classification_missing",
                )

                _structure, _classification, rows = persist_mapping_sources()
                classification_path = template_classification_artifact_path(101)
                classification_payload = json.loads(
                    classification_path.read_text(encoding="utf-8")
                )
                classification_payload["source_structure_hash"] = "0" * 64
                classification_path.write_text(
                    json.dumps(classification_payload),
                    encoding="utf-8",
                )
                with self.assertRaises(InitialMappingStageError) as stale_classification:
                    self.build(rows)
                self.assertEqual(
                    stale_classification.exception.reason_code,
                    "upstream_hash_mismatch",
                )

                _structure, _classification, rows = persist_mapping_sources()
                classification_path = template_classification_artifact_path(101)
                classification_payload = json.loads(
                    classification_path.read_text(encoding="utf-8")
                )
                classification_payload["canonical_registry_hash"] = "1" * 64
                classification_path.write_text(
                    json.dumps(classification_payload),
                    encoding="utf-8",
                )
                with self.assertRaises(InitialMappingStageError) as stale_registry:
                    self.build(rows)
                self.assertEqual(
                    stale_registry.exception.reason_code,
                    "registry_hash_mismatch",
                )

    def test_upstream_review_is_advisory_and_does_not_gate_19c(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                structure, classification, rows = persist_mapping_sources()
                structure.sections[0].requires_human_review = True
                structure.sections[0].warnings.append(
                    "section_range_conflicts_with_page_mapping"
                )
                persist_document_structure(structure)
                classification.source_structure_hash = document_structure_hash(structure)
                classification.outcomes[0].requires_human_review = True
                persist_template_classification(
                    classification,
                    structure=structure,
                )
                result = self.build(rows)
                persist_initial_mapping(result)

        self.assertEqual(result.total_rows, len(rows))
        self.assertTrue(
            all(
                "section_assignment_requires_human_review" in mapping.warnings
                for mapping in result.mappings
            )
        )


if __name__ == "__main__":
    unittest.main()
