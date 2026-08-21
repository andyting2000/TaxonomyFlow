import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from config import settings
from services.llm_taxonomy_mapping import (
    HuggingFaceQwenMappingClient,
    LLMMappingConfig,
    LLMMappingRateLimitError,
    MockQwenMappingClient,
    build_mapping_prompt,
    build_llm_mapping_row_inputs,
    is_rate_limit_error,
    load_production_fewshot_example_store,
    load_llm_mapping_config,
    retrieve_production_fewshot_examples,
    run_llm_mapping_for_loaded_job,
)


class FakeDB:
    def __init__(self):
        self.added = []
        self.flushed = False
        self.commits = 0

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushed = True

    async def commit(self):
        self.commits += 1


class StaticLLMClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def complete(self, prompt, *, config):
        self.calls.append(prompt)
        if callable(self.response):
            return self.response(prompt)
        return self.response


class RateLimitedLLMClient:
    async def complete(self, prompt, *, config):
        raise RuntimeError("429 Too Many Requests")


class SequentialLLMClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, prompt, *, config):
        self.calls.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            return response(prompt)
        return response


class Provider429Error(RuntimeError):
    status_code = 429

    def __init__(self, retry_after=None):
        super().__init__("429 Too Many Requests")
        self.response = SimpleNamespace(
            status_code=429,
            headers={"Retry-After": retry_after} if retry_after is not None else {},
        )


class FakeChatCompletionClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    async def chat_completion(self, **_kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def first_candidate_response(prompt, *, confidence=0.93, reason=None):
    payload = json.loads(prompt.split("Input:\n", 1)[1])
    candidate = payload["candidate_concepts"][0]
    return {
        "selected_template_field_id": candidate["template_field_id"],
        "confidence": confidence,
        "reason": reason or "The extracted label and statement context align with this provided candidate concept.",
        "ranked_candidates": [
            {
                "template_field_id": candidate["template_field_id"],
                "confidence": confidence,
                "reason": "Candidate label matches the row context.",
            }
        ],
        "requires_human_confirmation": True,
        "rejection_reason": None,
    }


def chat_completion_response(
    prompt,
    *,
    confidence=0.93,
    reason=None,
    fenced=False,
    text_choice=False,
    selected_template_field_id=None,
    null_selection=False,
    rejection_reason=None,
):
    response = first_candidate_response(prompt, confidence=confidence, reason=reason)
    if selected_template_field_id is not None:
        response["selected_template_field_id"] = selected_template_field_id
        response["ranked_candidates"] = []
    if null_selection:
        response["selected_template_field_id"] = None
        response["ranked_candidates"] = []
        response["rejection_reason"] = rejection_reason or "No safe mapping from provided candidates."
    content = json.dumps(response)
    if fenced:
        content = f"```json\n{content}\n```"
    if text_choice:
        return {"choices": [{"text": content}]}
    return {"choices": [{"message": {"content": content}}]}


def make_item(
    item_id,
    label,
    value="1000",
    *,
    statement_type="Statement of Profit or Loss (By Function)",
    template_field_id=None,
    validation_warnings=None,
):
    return SimpleNamespace(
        id=item_id,
        extracted_label=label,
        extracted_value=value,
        value_previous_year=None,
        financial_year=2026,
        financial_year_previous=None,
        statement_type=statement_type,
        template_field_id=template_field_id,
        template_position=None,
        is_required_field=False,
        is_reviewed=bool(template_field_id),
        confirmed_tag_id=None,
        validation_warnings=validation_warnings,
    )


def make_job(items):
    page = SimpleNamespace(id="page-1", page_number=1, extracted_items=items)
    return SimpleNamespace(
        id=31,
        company_name="LLM Mapping Unit",
        status="REVIEW",
        pages=[page],
    )


class LLMTaxonomyMappingTests(unittest.IsolatedAsyncioTestCase):
    async def test_config_defaults_are_candidate_constrained(self):
        config = load_llm_mapping_config(settings)

        self.assertEqual(config.model_id, "Qwen/Qwen3-235B-A22B-Instruct-2507")
        self.assertEqual(config.max_candidates, 8)
        self.assertEqual(config.min_display_confidence, 0.50)
        self.assertEqual(config.min_manual_confidence, 0.0)
        self.assertFalse(config.auto_apply_high_confidence)
        self.assertTrue(config.fewshot_enabled)
        self.assertEqual(config.fewshot_max_examples, 3)
        self.assertEqual(config.fewshot_case_split_mode, "training_only")
        self.assertTrue(config.fewshot_guardrails_enabled)
        self.assertTrue(config.fewshot_fallback_to_base_prompt)
        self.assertEqual(config.provider_rate_limit_max_retries, 2)
        self.assertEqual(config.provider_rate_limit_base_delay_seconds, 4.0)
        self.assertEqual(config.provider_rate_limit_max_delay_seconds, 30.0)
        self.assertEqual(config.provider_request_delay_seconds, 0.5)

    async def test_clear_row_maps_to_provided_valid_candidate_as_suggestion(self):
        item = make_item("item-revenue", "Revenue")
        db = FakeDB()

        report = await run_llm_mapping_for_loaded_job(
            db,
            make_job([item]),
            llm_client=MockQwenMappingClient(),
            persist_suggestions=True,
        )

        row = report["rows"][0]
        suggestion = row["suggestion"]
        self.assertEqual(suggestion["status"], "suggested")
        self.assertEqual(suggestion["selected_template_field_id"], "ifrs-smes:Revenue")
        self.assertGreaterEqual(suggestion["confidence"], 0.88)
        self.assertIsNone(item.template_field_id)
        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].status, "suggested")
        self.assertEqual(suggestion["normalized_response_shape"], "direct_json")

    async def test_chat_completion_message_content_envelope_parses_as_suggestion(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(lambda prompt: chat_completion_response(prompt, confidence=0.93))

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
            apply_high_confidence=False,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "suggested")
        self.assertEqual(suggestion["selected_template_field_id"], "ifrs-smes:Revenue")
        self.assertEqual(suggestion["normalized_response_shape"], "chat_completion_message_content")
        self.assertIn("selected_template_field_id", suggestion["parsed_content_preview"])
        self.assertIn('"choices"', suggestion["raw_response_preview"])
        self.assertIsNone(item.template_field_id)

    async def test_markdown_fenced_json_inside_message_content_parses(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(lambda prompt: chat_completion_response(prompt, confidence=0.93, fenced=True))

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "suggested")
        self.assertEqual(suggestion["normalized_response_shape"], "markdown_json")

    async def test_chat_completion_text_choice_parses_as_suggestion(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(lambda prompt: chat_completion_response(prompt, confidence=0.93, text_choice=True))

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "suggested")
        self.assertEqual(suggestion["normalized_response_shape"], "chat_completion_text")

    async def test_invented_concept_is_rejected(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(
            {
                "selected_template_field_id": "fake:InventedConcept",
                "confidence": 0.99,
                "reason": "This invented concept is not allowed.",
                "ranked_candidates": [],
                "requires_human_confirmation": True,
                "rejection_reason": None,
            }
        )

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
            apply_high_confidence=True,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "rejected")
        self.assertEqual(suggestion["rejection_reason"], "selected_candidate_not_in_candidates")
        self.assertTrue(suggestion["hallucinated_concept"])
        self.assertIsNone(item.template_field_id)

    async def test_invented_concept_inside_envelope_is_rejected(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(
            lambda prompt: chat_completion_response(
                prompt,
                confidence=0.99,
                selected_template_field_id="fake:InventedConcept",
            )
        )

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
            apply_high_confidence=True,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "rejected")
        self.assertEqual(suggestion["rejection_reason"], "selected_candidate_not_in_candidates")
        self.assertTrue(suggestion["hallucinated_concept"])
        self.assertIsNone(item.template_field_id)

    async def test_low_confidence_selected_candidate_inside_envelope_is_stored_as_suggestion(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(lambda prompt: chat_completion_response(prompt, confidence=0.49))

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
            apply_high_confidence=True,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "suggested")
        self.assertIsNone(suggestion["rejection_reason"])
        self.assertEqual(suggestion["warning_level"], "low_confidence")
        self.assertEqual(suggestion["confidence_category"], "low")
        self.assertEqual(suggestion["normalized_response_shape"], "chat_completion_message_content")
        self.assertIsNone(item.template_field_id)

    async def test_null_selected_candidate_with_model_rejection_inside_envelope_is_rejected(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(
            lambda prompt: chat_completion_response(
                prompt,
                confidence=0.0,
                null_selection=True,
                rejection_reason="No provided candidate is safe enough.",
            )
        )

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "rejected")
        self.assertEqual(suggestion["rejection_reason"], "no_safe_mapping_returned_by_model")
        self.assertEqual(suggestion["model_rejection_reason"], "No provided candidate is safe enough.")
        self.assertIsNone(item.template_field_id)

    async def test_medium_confidence_is_stored_as_suggested_and_not_applied(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(lambda prompt: first_candidate_response(prompt, confidence=0.52))

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
            apply_high_confidence=True,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "suggested")
        self.assertIsNone(suggestion["rejection_reason"])
        self.assertTrue(suggestion["requires_human_confirmation"])
        self.assertIsNone(item.template_field_id)
        self.assertFalse(item.is_reviewed)
        self.assertEqual(report["summary"]["display_suggestions_generated"], 1)
        self.assertEqual(report["summary"]["high_confidence_suggestions"], 0)

    async def test_low_confidence_valid_candidate_is_stored_and_not_auto_applied(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(lambda prompt: first_candidate_response(prompt, confidence=0.49))

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
            apply_high_confidence=True,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "suggested")
        self.assertEqual(suggestion["selected_template_field_id"], "ifrs-smes:Revenue")
        self.assertEqual(suggestion["warning_level"], "low_confidence")
        self.assertEqual(suggestion["confidence_category"], "low")
        self.assertTrue(suggestion["requires_human_confirmation"])
        self.assertIsNone(item.template_field_id)
        self.assertEqual(report["summary"]["rejected_low_confidence_rows"], 0)
        self.assertEqual(report["summary"]["low_confidence_suggestions"], 1)

    async def test_below_manual_confidence_is_rejected_and_not_applied(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(lambda prompt: first_candidate_response(prompt, confidence=0.09))
        config = load_llm_mapping_config(settings)
        config = type(config)(
            model_id=config.model_id,
            max_candidates=config.max_candidates,
            timeout_seconds=config.timeout_seconds,
            high_confidence_threshold=config.high_confidence_threshold,
            min_display_confidence=config.min_display_confidence,
            min_manual_confidence=0.10,
            max_rows_per_job=config.max_rows_per_job,
            auto_apply_high_confidence=config.auto_apply_high_confidence,
        )

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
            apply_high_confidence=True,
            config=config,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "rejected")
        self.assertEqual(suggestion["rejection_reason"], "below_manual_confidence")
        self.assertIsNone(item.template_field_id)

    async def test_person_and_company_names_are_rejected_before_llm(self):
        item = make_item(
            "item-company",
            "Example Sdn Bhd",
            statement_type="Statement of Financial Position",
        )
        client = StaticLLMClient(lambda _prompt: self.fail("LLM should not be called"))

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
        )

        self.assertEqual(report["summary"]["rows_sent_to_llm"], 0)
        self.assertEqual(
            report["rows"][0]["suggestion"]["rejection_reason"],
            "rejected_person_or_company_name",
        )

    async def test_note_number_only_rows_are_rejected_before_llm(self):
        item = make_item(
            "item-note",
            "Other receivable",
            "5",
            statement_type="Statement of Financial Position",
            validation_warnings='["note_column_values_ignored"]',
        )

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=MockQwenMappingClient(),
        )

        self.assertEqual(report["summary"]["rows_sent_to_llm"], 0)
        self.assertEqual(
            report["rows"][0]["suggestion"]["rejection_reason"],
            "rejected_note_number_only",
        )

    async def test_ambiguous_summary_labels_are_rejected_before_llm(self):
        item = make_item(
            "item-ambiguous",
            "Trade and other receivables",
            statement_type="Statement of Financial Position",
        )

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=MockQwenMappingClient(),
        )

        self.assertEqual(report["summary"]["rows_sent_to_llm"], 0)
        self.assertEqual(report["rows"][0]["suggestion"]["rejection_reason"], "rejected_ambiguous")

    async def test_candidate_retrieval_returns_candidates_for_bank_overdraft(self):
        item = make_item(
            "item-bank-overdraft",
            "Bank overdraft - unsecured",
            statement_type="Statement of Financial Position",
        )

        entries, _counts = build_llm_mapping_row_inputs(make_job([item]))

        self.assertIsNone(entries[0]["precheck_rejection_reason"])
        candidate_ids = {row["template_field_id"] for row in entries[0]["candidate_concepts"]}
        self.assertIn("ssmt-mpers:UnsecuredBankOverdrafts", candidate_ids)

    async def test_candidate_retrieval_returns_candidates_for_other_payable_and_accruals(self):
        payable = make_item(
            "item-other-payable",
            "Other payable",
            statement_type="Statement of Financial Position",
        )
        accruals = make_item(
            "item-accruals",
            "Accruals",
            statement_type="Statement of Financial Position",
        )

        entries, _counts = build_llm_mapping_row_inputs(make_job([payable, accruals]))
        by_label = {entry["row_context"]["extracted_label"]: entry for entry in entries}
        payable_ids = {row["template_field_id"] for row in by_label["Other payable"]["candidate_concepts"]}
        accrual_ids = {row["template_field_id"] for row in by_label["Accruals"]["candidate_concepts"]}

        self.assertIn("ifrs-smes:TradeAndOtherCurrentPayables", payable_ids)
        self.assertIn("ssmt-mpers:CurrentNontradeAccruals", accrual_ids)

    async def test_candidate_retrieval_returns_candidates_for_contributed_share_capital(self):
        item = make_item(
            "item-share-capital",
            "Contributed share capital",
            statement_type="Statement of Financial Position",
        )

        entries, _counts = build_llm_mapping_row_inputs(make_job([item]))

        candidate_ids = {row["template_field_id"] for row in entries[0]["candidate_concepts"]}
        self.assertIn("ifrs-smes:IssuedCapital", candidate_ids)

    async def test_existing_deterministic_mapped_rows_are_not_overwritten(self):
        item = make_item(
            "item-mapped",
            "Revenue",
            template_field_id="ifrs-smes:Revenue",
        )
        client = StaticLLMClient(lambda _prompt: self.fail("LLM should not be called"))

        report = await run_llm_mapping_for_loaded_job(
            FakeDB(),
            make_job([item]),
            llm_client=client,
            apply_high_confidence=True,
        )

        self.assertEqual(report["summary"]["already_mapped_rows"], 1)
        self.assertEqual(report["summary"]["rows_considered"], 0)
        self.assertEqual(item.template_field_id, "ifrs-smes:Revenue")
        self.assertIsNone(item.confirmed_tag_id)

    async def test_apply_mode_updates_only_valid_high_confidence_suggestion(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(lambda prompt: first_candidate_response(prompt, confidence=0.93))
        db = FakeDB()

        report = await run_llm_mapping_for_loaded_job(
            db,
            make_job([item]),
            llm_client=client,
            apply_high_confidence=True,
        )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["status"], "accepted")
        self.assertEqual(item.template_field_id, "ifrs-smes:Revenue")
        self.assertTrue(item.is_reviewed)
        self.assertIsNone(item.confirmed_tag_id)
        self.assertEqual(report["summary"]["after_mapped_count"], 1)
        self.assertEqual(db.added[0].status, "accepted")

    async def test_report_generation_works_without_live_llm(self):
        item = make_item("item-revenue", "Revenue")

        report = await run_llm_mapping_for_loaded_job(
            None,
            make_job([item]),
            llm_client=None,
            persist_suggestions=False,
        )

        self.assertFalse(report["run_metadata"]["llm_called"])
        self.assertEqual(report["summary"]["rows_sent_to_llm"], 0)
        self.assertEqual(report["summary"]["suggestions_generated"], 0)
        self.assertGreater(len(report["rows"][0]["candidate_concepts"]), 0)
        self.assertIsNone(report["rows"][0]["suggestion"])

    async def test_rate_limit_raises_without_persisting_rejected_rows(self):
        item = make_item("item-1", "Cash and bank balances")
        db = FakeDB()

        with self.assertRaises(LLMMappingRateLimitError):
            await run_llm_mapping_for_loaded_job(
                db,
                make_job([item]),
                llm_client=RateLimitedLLMClient(),
                include_mapped=False,
                apply_high_confidence=False,
                persist_suggestions=True,
            )

        self.assertEqual(db.added, [])
        self.assertFalse(db.flushed)

    async def test_live_qwen_client_retries_429_with_bounded_backoff(self):
        fake_provider = FakeChatCompletionClient(
            [
                Provider429Error(retry_after="7"),
                Provider429Error(),
                {"choices": [{"message": {"content": "{}"}}]},
            ]
        )
        slept = []

        async def sleeper(delay):
            slept.append(delay)

        config = LLMMappingConfig(
            model_id="unit-qwen",
            max_candidates=1,
            timeout_seconds=5,
            high_confidence_threshold=0.88,
            min_display_confidence=0.5,
            min_manual_confidence=0.0,
            max_rows_per_job=1,
            provider_rate_limit_base_delay_seconds=4.0,
            provider_rate_limit_max_delay_seconds=30.0,
            provider_rate_limit_max_retries=2,
        )
        client = HuggingFaceQwenMappingClient(
            token="hf-unit",
            client_factory=lambda **_kwargs: fake_provider,
            sleeper=sleeper,
        )

        response = await client.complete("{}", config=config)

        self.assertEqual(response, {"choices": [{"message": {"content": "{}"}}]})
        self.assertEqual(fake_provider.calls, 3)
        self.assertEqual(slept, [7.0, 8.0])

    async def test_live_qwen_client_raises_provider_rate_limit_after_max_retries(self):
        fake_provider = FakeChatCompletionClient(
            [Provider429Error(retry_after="90"), Provider429Error(), Provider429Error()]
        )
        slept = []

        async def sleeper(delay):
            slept.append(delay)

        config = LLMMappingConfig(
            model_id="unit-qwen",
            max_candidates=1,
            timeout_seconds=5,
            high_confidence_threshold=0.88,
            min_display_confidence=0.5,
            min_manual_confidence=0.0,
            max_rows_per_job=1,
            provider_rate_limit_base_delay_seconds=4.0,
            provider_rate_limit_max_delay_seconds=30.0,
            provider_rate_limit_max_retries=2,
        )
        client = HuggingFaceQwenMappingClient(
            token="hf-unit",
            client_factory=lambda **_kwargs: fake_provider,
            sleeper=sleeper,
        )

        with self.assertRaises(LLMMappingRateLimitError) as caught:
            await client.complete("{}", config=config)

        self.assertEqual(caught.exception.provider_error_type, "provider_rate_limited")
        self.assertEqual(caught.exception.attempt_count, 3)
        self.assertEqual(caught.exception.retry_after_seconds, None)
        self.assertEqual(slept, [30.0, 8.0])

    async def test_partial_successful_suggestions_are_preserved_before_later_rate_limit(self):
        first_item = make_item("item-a-revenue", "Revenue")
        second_item = make_item("item-b-cash", "Cash and bank balances")
        db = FakeDB()
        client = SequentialLLMClient(
            [
                lambda prompt: first_candidate_response(prompt, confidence=0.93),
                RuntimeError("429 Too Many Requests"),
            ]
        )

        with self.assertRaises(LLMMappingRateLimitError) as caught:
            await run_llm_mapping_for_loaded_job(
                db,
                make_job([first_item, second_item]),
                llm_client=client,
                include_mapped=False,
                apply_high_confidence=False,
                persist_suggestions=True,
            )

        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].extracted_data_item_id, "item-a-revenue")
        self.assertEqual(db.added[0].status, "suggested")
        self.assertEqual(db.commits, 1)
        self.assertEqual(caught.exception.saved_suggestions, 1)
        self.assertEqual(caught.exception.processed_rows, 1)
        self.assertEqual(caught.exception.pending_rows, 1)
        self.assertEqual(caught.exception.failed_row_id, "item-b-cash")

    async def test_existing_suggestion_rows_are_skipped_on_resume(self):
        item = make_item("item-revenue", "Revenue")
        item.llm_mapping_suggestions = [
            SimpleNamespace(
                job_id=31,
                extracted_data_item_id="item-revenue",
                status="suggested",
            )
        ]
        db = FakeDB()
        client = StaticLLMClient(lambda prompt: first_candidate_response(prompt, confidence=0.93))

        report = await run_llm_mapping_for_loaded_job(
            db,
            make_job([item]),
            llm_client=client,
            include_mapped=False,
            apply_high_confidence=False,
            persist_suggestions=True,
        )

        self.assertEqual(client.calls, [])
        self.assertEqual(db.added, [])
        self.assertEqual(report["rows"][0]["skip_reason"], "existing_ai_mapping_suggestion")
        self.assertEqual(report["summary"]["existing_suggestion_rows"], 1)
        self.assertEqual(report["summary"]["persisted_suggestion_records"], 0)

    def test_rate_limit_error_detection_handles_provider_status_and_text(self):
        response = SimpleNamespace(status_code=429)

        self.assertTrue(is_rate_limit_error(SimpleNamespace(response=response)))
        self.assertTrue(is_rate_limit_error(RuntimeError("429 Too Many Requests")))
        self.assertTrue(is_rate_limit_error(RuntimeError("provider rate limit exceeded")))
        self.assertFalse(is_rate_limit_error(RuntimeError("temporary json parse issue")))

    async def test_prompt_requires_provided_candidates_only(self):
        prompt = build_mapping_prompt(
            {"extracted_label": "Revenue"},
            [{"template_field_id": "ifrs-smes:Revenue", "label": "Revenue"}],
        )

        self.assertIn("Choose only from candidate_concepts.template_field_id", prompt)
        self.assertIn("Do not invent qnames", prompt)
        self.assertIn("selected_template_field_id", prompt)

    async def test_fewshot_loader_excludes_ambiguous_xml_and_target_labels(self):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "alignment.json"
            path.write_text(
                json.dumps(
                    {
                        "alignments": [
                            {
                                "source_case_id": "case_001",
                                "extracted_row_id": "case_001:row-1",
                                "alignment_status": "strong",
                                "extracted_label": "Revenue",
                                "extracted_value": "100",
                                "statement_type": "Statement of Profit or Loss",
                                "correct_concept_qname": "ifrs-smes:Revenue",
                                "correct_template_field_id": "ifrs-smes:Revenue",
                                "reference_xml": "<secret/>",
                                "candidate_facts": [{"value": "100", "context_ref": "secret"}],
                                "evaluation_label": "correct",
                                "evidence": {"value_match": True, "label_similarity": 1.0},
                            },
                            {
                                "source_case_id": "case_001",
                                "extracted_row_id": "case_001:row-2",
                                "alignment_status": "ambiguous",
                                "extracted_label": "Other income",
                                "correct_concept_qname": "ifrs-smes:OtherIncome",
                            },
                            {
                                "source_case_id": "case_006",
                                "extracted_row_id": "case_006:row-1",
                                "alignment_status": "strong",
                                "extracted_label": "Cash",
                                "correct_concept_qname": "ifrs-smes:CashAndCashEquivalents",
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )

            examples = load_production_fewshot_example_store(path, case_split_mode="training_only")

        self.assertEqual(len(examples), 1)
        payload = json.dumps(examples)
        self.assertIn("Revenue", payload)
        self.assertNotIn("Other income", payload)
        self.assertNotIn("Cash", payload)
        self.assertNotIn("<secret", payload)
        self.assertNotIn("candidate_facts", payload)
        self.assertNotIn("evaluation_label", payload)
        self.assertNotIn("extracted_value", payload)

    async def test_similar_example_retrieval_prefers_same_statement_type_and_filters_generic(self):
        examples = [
            {
                "source_case_id": "case_001",
                "example_id": "generic",
                "extracted_label": "Total liabilities",
                "statement_type": "Statement of Financial Position",
                "correct_template_field_id": "ifrs-smes:Liabilities",
                "correct_concept_qname": "ifrs-smes:Liabilities",
                "concept_family": "liabilities",
                "rationale": "strong local gold alignment",
            },
            {
                "source_case_id": "case_002",
                "example_id": "same-statement",
                "extracted_label": "Other payable",
                "statement_type": "Statement of Financial Position",
                "correct_template_field_id": "ssmt-mpers:CurrentNontradePayables",
                "correct_concept_qname": "ssmt-mpers:CurrentNontradePayables",
                "concept_family": "payables",
                "rationale": "strong local gold alignment",
            },
            {
                "source_case_id": "case_003",
                "example_id": "wrong-statement",
                "extracted_label": "Other payable",
                "statement_type": "Statement of Cash Flows",
                "correct_template_field_id": "ifrs-smes:AdjustmentsForIncreaseDecreaseInOtherOperatingPayables",
                "correct_concept_qname": "ifrs-smes:AdjustmentsForIncreaseDecreaseInOtherOperatingPayables",
                "concept_family": "payables",
                "rationale": "strong local gold alignment",
            },
        ]

        retrieved = retrieve_production_fewshot_examples(
            row_context={
                "extracted_label": "Other payable",
                "statement_type": "Statement of Financial Position",
            },
            example_store=examples,
            limit=2,
        )

        self.assertEqual(retrieved[0]["example_id"], "same-statement")
        self.assertNotIn("generic", {row["example_id"] for row in retrieved})

    async def test_fewshot_prompt_payload_excludes_target_gold_and_xml(self):
        prompt = build_mapping_prompt(
            {
                "extracted_label": "Revenue",
                "statement_type": "Statement of Profit or Loss",
                "correct_concept_qname": "secret:TargetGold",
                "reference_xml": "<secret/>",
                "evaluation_label": "correct",
            },
            [{"template_field_id": "ifrs-smes:Revenue", "label": "Revenue"}],
            fewshot_examples=[
                {
                    "source_case_id": "case_001",
                    "example_id": "case_001:row",
                    "extracted_label": "Revenue",
                    "statement_type": "Statement of Profit or Loss",
                    "correct_template_field_id": "ifrs-smes:Revenue",
                    "correct_concept_qname": "ifrs-smes:Revenue",
                    "rationale": "strong local gold alignment",
                    "candidate_facts": [{"secret": "fact"}],
                    "reference_xml": "<secret/>",
                }
            ],
        )

        self.assertIn("few_shot_examples", prompt)
        self.assertIn("guardrail_context", prompt)
        self.assertIn("Return strict JSON only", prompt)
        self.assertNotIn("secret:TargetGold", prompt)
        self.assertNotIn("<secret", prompt)
        self.assertNotIn("evaluation_label", prompt)
        self.assertNotIn("candidate_facts", prompt)

    async def test_fewshot_loading_failure_falls_back_to_base_prompt(self):
        item = make_item("item-revenue", "Revenue")
        client = StaticLLMClient(lambda prompt: first_candidate_response(prompt, confidence=0.93))
        config = LLMMappingConfig(
            model_id="unit-qwen",
            max_candidates=8,
            timeout_seconds=60,
            high_confidence_threshold=0.88,
            min_display_confidence=0.50,
            min_manual_confidence=0.0,
            max_rows_per_job=50,
            fewshot_enabled=True,
            fewshot_max_examples=3,
            fewshot_fallback_to_base_prompt=True,
        )

        with patch(
            "services.llm_taxonomy_mapping.load_production_fewshot_example_store",
            side_effect=RuntimeError("missing local report"),
        ):
            report = await run_llm_mapping_for_loaded_job(
                FakeDB(),
                make_job([item]),
                llm_client=client,
                config=config,
            )

        self.assertEqual(report["run_metadata"]["fewshot_loader_error"], "missing local report")
        self.assertEqual(report["rows"][0]["prompt_mode"], "base")
        prompt_payload = json.loads(client.calls[0].split("Input:\n", 1)[1])
        self.assertNotIn("few_shot_examples", prompt_payload)
        self.assertEqual(report["rows"][0]["suggestion"]["status"], "suggested")

    async def test_production_fewshot_prompt_mode_diagnostics_are_persisted(self):
        item = make_item("item-revenue", "Revenue")
        db = FakeDB()
        client = StaticLLMClient(lambda prompt: first_candidate_response(prompt, confidence=0.93))
        config = LLMMappingConfig(
            model_id="unit-qwen",
            max_candidates=8,
            timeout_seconds=60,
            high_confidence_threshold=0.88,
            min_display_confidence=0.50,
            min_manual_confidence=0.0,
            max_rows_per_job=50,
            fewshot_enabled=True,
            fewshot_max_examples=3,
        )
        examples = [
            {
                "source_case_id": "case_001",
                "example_id": "case_001:row",
                "extracted_label": "Revenue",
                "statement_type": "Statement of Profit or Loss (By Function)",
                "correct_template_field_id": "ifrs-smes:Revenue",
                "correct_concept_qname": "ifrs-smes:Revenue",
                "concept_family": "other",
                "rationale": "strong local gold alignment",
            }
        ]

        with patch(
            "services.llm_taxonomy_mapping.load_production_fewshot_example_store",
            return_value=examples,
        ):
            report = await run_llm_mapping_for_loaded_job(
                db,
                make_job([item]),
                llm_client=client,
                config=config,
                persist_suggestions=True,
            )

        suggestion = report["rows"][0]["suggestion"]
        self.assertEqual(suggestion["prompt_mode"], "fewshot_guarded")
        self.assertEqual(suggestion["fewshot_examples_count"], 1)
        self.assertEqual(suggestion["candidate_count"], len(report["rows"][0]["candidate_concepts"]))
        self.assertIsNone(item.template_field_id)
        self.assertIsNone(item.confirmed_tag_id)
        diagnostic = json.loads(db.added[0].diagnostic_json)
        self.assertEqual(diagnostic["prompt_mode"], "fewshot_guarded")
        self.assertEqual(diagnostic["fewshot_examples_count"], 1)
        self.assertEqual(diagnostic["selected_template_field_id"], "ifrs-smes:Revenue")

    async def test_schema_migration_and_db_init_registration_exist(self):
        migration = Path("migrations/009_add_llm_mapping_suggestions.sql").read_text(encoding="utf-8")
        status_migration = Path("migrations/011_add_ai_mapping_job_status.sql").read_text(encoding="utf-8")
        db_init_source = Path("db_init.py").read_text(encoding="utf-8")

        self.assertIn("CREATE TABLE IF NOT EXISTS llm_mapping_suggestions", migration)
        self.assertIn("REFERENCES filing_jobs(id) ON DELETE CASCADE", migration)
        self.assertIn("REFERENCES extracted_data_items(id) ON DELETE CASCADE", migration)
        self.assertIn("ai_mapping_status", status_migration)
        self.assertIn("ai_mapping_last_error_message", status_migration)
        self.assertIn('"llm_mapping_suggestions"', db_init_source)
        self.assertIn('"suggested_template_field_id"', db_init_source)
        self.assertIn('"ai_mapping_status"', db_init_source)


if __name__ == "__main__":
    unittest.main()
