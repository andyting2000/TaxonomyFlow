import asyncio
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from config import settings
from schemas import RowMappingEligibility
from services.section_aware_initial_mapping import (
    InitialMappingStageError,
    _classification_contexts,
    build_document_initial_mapping,
    load_initial_mapping,
    persist_initial_mapping,
)
from services.section_aware_initial_mapping_llm import InitialMappingLLMConfig
from services.section_aware_taxonomy_candidate_retriever import (
    CandidateRetrievalSystemError,
    retrieve_section_aware_candidates,
    score_taxonomy_candidate,
)
from services.section_aware_taxonomy_concept_cards import (
    build_taxonomy_concept_inventory,
)
from services.template_group_registry import load_template_group_registry
from tests.section_aware_mapping_test_support import persist_mapping_sources


class CandidateRetrievalFailureIsolationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cards, cls.inventory = build_taxonomy_concept_inventory()

    @staticmethod
    def _rows():
        return [
            {
                "original_candidate_id": "fails-locally",
                "row_type": "comparative_numeric_fact",
                "label": "Synthetic scoring failure",
                "value": "1",
                "previous_value": "1",
                "page_number": 2,
            },
            {
                "original_candidate_id": "independent-row",
                "row_type": "comparative_numeric_fact",
                "label": "Revenue",
                "value": "1",
                "previous_value": "1",
                "page_number": 2,
            },
        ]

    def test_scoring_exception_is_row_local_and_other_row_completes(self):
        real_score = score_taxonomy_candidate

        def selective_failure(**kwargs):
            if kwargs["row"].get("label") == "Synthetic scoring failure":
                raise TypeError("synthetic row-only scoring shape")
            return real_score(**kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                _structure, _classification, rows = persist_mapping_sources(
                    group_ids=("420000",),
                    candidates=self._rows(),
                )
                events = []
                provider = AsyncMock()
                with patch(
                    "services.section_aware_taxonomy_candidate_retriever.score_taxonomy_candidate",
                    side_effect=selective_failure,
                ):
                    result = asyncio.run(
                        build_document_initial_mapping(
                            job_id=101,
                            filing_id=101,
                            source_rows=rows,
                            llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
                            llm_client=provider,
                            stage_callback=lambda stage, status, details: events.append(
                                (stage, status, dict(details))
                            ),
                        )
                    )
                persist_initial_mapping(result)
                loaded = load_initial_mapping(101)

        retrieval = next(
            details
            for stage, status, details in events
            if stage == "19C_candidate_retrieval" and status == "completed"
        )
        self.assertEqual(result.total_rows, 2)
        self.assertEqual(result.failed_rows, 1)
        self.assertEqual(result.mappings[0].decision, "retrieval_failed")
        self.assertNotEqual(result.mappings[1].decision, "retrieval_failed")
        self.assertEqual(retrieval["source_rows_received"], 2)
        self.assertEqual(retrieval["rows_eligible"], 2)
        self.assertEqual(retrieval["rows_attempted"], 2)
        self.assertEqual(retrieval["rows_successful"], 1)
        self.assertEqual(retrieval["rows_failed_locally"], 1)
        self.assertEqual(retrieval["stage_fatal_error_count"], 0)
        self.assertEqual(
            retrieval["row_errors"],
            [
                {
                    "row_identifier": "persisted-row-1",
                    "reason_code": "candidate_scoring_failed",
                    "exception_class": "CandidateRetrievalRowError",
                }
            ],
        )
        self.assertEqual(loaded.failed_rows, 1)
        self.assertEqual(loaded.llm_calls, 0)
        provider.assert_not_called()
        self.assertEqual(loaded.safety_summary["confirmed_tag_id_mutations"], 0)
        self.assertEqual(loaded.safety_summary["final_mapping_mutations"], 0)

    def test_too_small_context_boundary_isolated_without_provider(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with (
                patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")),
                patch.object(settings, "toc_aware_initial_mapping_max_context_characters", 500),
            ):
                _structure, _classification, rows = persist_mapping_sources(
                    group_ids=("420000",),
                    candidates=self._rows(),
                )
                provider = AsyncMock()
                result = asyncio.run(
                    build_document_initial_mapping(
                        job_id=101,
                        filing_id=101,
                        source_rows=rows,
                        llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
                        llm_client=provider,
                    )
                )
        self.assertEqual(result.total_rows, 2)
        self.assertTrue(all(item.decision == "retrieval_failed" for item in result.mappings))
        provider.assert_not_called()

    def test_nonmapping_outcomes_are_safe_noneligible_rows(self):
        for outcome in ("unassigned", "ambiguous", "narrative_only", "container_only"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp_dir:
                with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                    _structure, _classification, rows = persist_mapping_sources(
                        outcome=outcome,
                    )
                    result = asyncio.run(
                        build_document_initial_mapping(
                            job_id=101,
                            filing_id=101,
                            source_rows=rows,
                            llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
                        )
                    )
            self.assertEqual(result.eligible_rows, 0)
            self.assertEqual(result.mappings[0].candidate_set.candidate_outcome, "row_not_eligible")
            self.assertEqual(result.llm_calls, 0)

    def test_missing_and_unclassified_section_contexts_are_safe(self):
        registry = load_template_group_registry()
        row = {"source_row_id": "row-1", "page_number": None}
        empty = SimpleNamespace(sections=[])
        classification = SimpleNamespace(outcomes=[], note_subsections=[])
        missing = _classification_contexts(empty, classification, [row], registry=registry)
        self.assertIsNone(missing["row-1"]["section_id"])
        self.assertEqual(missing["row-1"]["classification_outcome"], "unassigned")

        unknown_section = SimpleNamespace(
            sections=[
                SimpleNamespace(
                    section_id="section-without-classification",
                    extracted_row_ids=["row-1"],
                    azure_page_start=2,
                    azure_page_end=2,
                    raw_title="Unclassified",
                )
            ]
        )
        unclassified = _classification_contexts(
            unknown_section,
            classification,
            [row],
            registry=registry,
        )
        self.assertEqual(
            unclassified["row-1"]["section_id"],
            "section-without-classification",
        )
        self.assertEqual(
            unclassified["row-1"]["classification_outcome"],
            "unassigned",
        )

    def test_unknown_group_and_missing_card_metadata_fail_closed(self):
        eligibility = RowMappingEligibility(
            source_row_id="row-1",
            outcome="fact_candidate",
            eligible=True,
        )
        unknown = retrieve_section_aware_candidates(
            row={"source_row_id": "row-1", "label": "Unknown", "current_value": "1"},
            row_eligibility=eligibility,
            section_id="section-1",
            subsection_id=None,
            template_group_ids=["999999"],
            statement_families=[],
            inventory_cards=self.cards,
            concept_inventory_hash=self.inventory["concept_inventory_hash"],
        )
        self.assertEqual(unknown.candidate_outcome, "no_safe_candidate")
        self.assertFalse(unknown.candidates)
        self.assertIn("empty_candidate_scope", unknown.warnings)

        cards = [
            card.model_copy(update={"datatype": None, "period_type": None})
            for card in self.cards
        ]
        missing_metadata = retrieve_section_aware_candidates(
            row={"source_row_id": "row-1", "label": "Revenue", "current_value": "1"},
            row_eligibility=eligibility,
            section_id="section-1",
            subsection_id=None,
            template_group_ids=["420000"],
            statement_families=["comprehensive_income"],
            inventory_cards=cards,
            concept_inventory_hash=self.inventory["concept_inventory_hash"],
        )
        self.assertIn(
            missing_metadata.candidate_outcome,
            {"candidates_available", "no_safe_candidate"},
        )

    def test_malformed_candidate_card_is_systemic(self):
        with self.assertRaises(CandidateRetrievalSystemError) as raised:
            retrieve_section_aware_candidates(
                row={"source_row_id": "row-1", "label": "Revenue", "current_value": "1"},
                row_eligibility=RowMappingEligibility(
                    source_row_id="row-1",
                    outcome="fact_candidate",
                    eligible=True,
                ),
                section_id="section-1",
                subsection_id=None,
                template_group_ids=["420000"],
                statement_families=["comprehensive_income"],
                inventory_cards=[{}],
                concept_inventory_hash="fixture-hash",
            )
        self.assertEqual(raised.exception.reason_code, "candidate_card_invalid")

    def test_registry_and_inventory_load_failures_remain_stage_fatal(self):
        cases = (
            (
                "services.section_aware_initial_mapping.load_template_group_registry",
                "registry_hash_mismatch",
            ),
            (
                "services.section_aware_initial_mapping.build_taxonomy_concept_inventory",
                "concept_inventory_unavailable",
            ),
        )
        for target, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp_dir:
                with patch.object(settings, "upload_directory", str(Path(temp_dir) / "uploads")):
                    _structure, _classification, rows = persist_mapping_sources()
                    with patch(target, side_effect=ValueError("synthetic systemic failure")):
                        with self.assertRaises(InitialMappingStageError) as raised:
                            asyncio.run(
                                build_document_initial_mapping(
                                    job_id=101,
                                    filing_id=101,
                                    source_rows=rows,
                                    llm_config=InitialMappingLLMConfig(mode="deterministic_only"),
                                )
                            )
            self.assertEqual(raised.exception.reason_code, reason)


if __name__ == "__main__":
    unittest.main()
