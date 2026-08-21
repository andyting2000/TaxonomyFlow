import asyncio
import json
import unittest

from schemas import RowMappingEligibility
from services.section_aware_initial_mapping_llm import (
    InitialMappingLLMConfig,
    InitialMappingPayloadBoundaryError,
    assert_safe_external_payload,
    run_bounded_initial_mapping_llm,
)
from services.section_aware_taxonomy_candidate_retriever import retrieve_section_aware_candidates
from services.section_aware_taxonomy_concept_cards import build_taxonomy_concept_inventory


class StaticClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.calls = 0

    async def complete(self, prompt, *, config):
        self.calls += 1
        if self.error:
            raise self.error
        return self.response


class SlowClient(StaticClient):
    async def complete(self, prompt, *, config):
        self.calls += 1
        await asyncio.sleep(0.05)
        return self.response


class SectionAwareInitialMappingLLMTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cards, metadata = build_taxonomy_concept_inventory()
        cls.candidate_set = retrieve_section_aware_candidates(
            row={"source_row_id": "r1", "label": "Revenue", "current_value": "100"},
            row_eligibility=RowMappingEligibility(source_row_id="r1", outcome="fact_candidate", eligible=True),
            section_id="s1",
            subsection_id=None,
            template_group_ids=["310000"],
            statement_families=["profit_or_loss"],
            inventory_cards=cards,
            concept_inventory_hash=metadata["concept_inventory_hash"],
        )
        cls.context = {
            "source_row_id": "r1",
            "row_label": "Revenue",
            "current_year_value": "100",
            "candidate_concepts": [
                {"concept_id": item.concept_id, "qname": item.qname, "standard_label": item.concept_card.standard_label}
                for item in cls.candidate_set.candidates
            ],
        }

    async def test_deterministic_only_makes_zero_provider_calls(self):
        client = StaticClient()
        result = await run_bounded_initial_mapping_llm(
            context=self.context,
            candidate_set=self.candidate_set,
            config=InitialMappingLLMConfig(mode="deterministic_only"),
            llm_client=client,
        )
        self.assertEqual(result["decision"], "mapped")
        self.assertEqual(result["selected_qname"], "ifrs-smes:Revenue")
        self.assertEqual(result["provider_calls"], 0)
        self.assertEqual(client.calls, 0)

    async def test_mock_can_select_only_exact_supplied_candidate(self):
        selected = self.candidate_set.candidates[0]
        response = {
            "decision": "mapped",
            "selected_concept_id": selected.concept_id,
            "selected_qname": selected.qname,
            "confidence": 0.8,
            "reason": "The supplied candidate matches the bounded row context.",
            "alternative_concept_ids": [],
            "requires_human_review": True,
        }
        client = StaticClient(response)
        result = await run_bounded_initial_mapping_llm(
            context=self.context,
            candidate_set=self.candidate_set,
            config=InitialMappingLLMConfig(mode="mock_llm"),
            llm_client=client,
        )
        self.assertEqual(result["decision"], "mapped")
        self.assertEqual(result["provider_calls"], 1)
        self.assertEqual(client.calls, 1)

    async def test_unknown_qname_out_of_set_and_invalid_json_fail_closed_once(self):
        selected = self.candidate_set.candidates[0]
        unsafe_responses = [
            {"decision": "mapped", "selected_concept_id": selected.concept_id, "selected_qname": "ssmt:Invented", "confidence": 0.8, "reason": "unsafe", "alternative_concept_ids": [], "requires_human_review": True},
            {"decision": "mapped", "selected_concept_id": "not-supplied", "selected_qname": "ssmt:NotSupplied", "confidence": 0.8, "reason": "unsafe", "alternative_concept_ids": [], "requires_human_review": True},
            "```json\n{}\n```",
        ]
        for response in unsafe_responses:
            with self.subTest(response=str(response)[:30]):
                client = StaticClient(response)
                result = await run_bounded_initial_mapping_llm(
                    context=self.context,
                    candidate_set=self.candidate_set,
                    config=InitialMappingLLMConfig(mode="mock_llm"),
                    llm_client=client,
                )
                self.assertEqual(result["decision"], "validation_failed")
                self.assertEqual(client.calls, 1)
                self.assertIsNone(result["selected_qname"])

    async def test_provider_failure_and_timeout_make_one_call_and_no_retry(self):
        for client, timeout in ((StaticClient(error=RuntimeError("boom")), 1), (SlowClient(response={}), 0.01)):
            with self.subTest(client=type(client).__name__):
                result = await run_bounded_initial_mapping_llm(
                    context=self.context,
                    candidate_set=self.candidate_set,
                    config=InitialMappingLLMConfig(mode="mock_llm", timeout_seconds=timeout),
                    llm_client=client,
                )
                self.assertEqual(result["decision"], "provider_failed")
                self.assertEqual(client.calls, 1)

    def test_payload_boundary_rejects_gold_xml_final_and_confirmed_data_recursively(self):
        for key in ("auditor_xml", "reference_xml", "benchmark_gold_mapping", "correct_qname", "confirmed_tag_id", "final_mapping"):
            with self.subTest(key=key), self.assertRaises(InitialMappingPayloadBoundaryError):
                assert_safe_external_payload({"row": {"nested": [{key: "secret"}]}})
        assert_safe_external_payload(self.context)


if __name__ == "__main__":
    unittest.main()
