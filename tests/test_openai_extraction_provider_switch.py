import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import services.stage1_classifier as stage1_module
import services.smart_ai_processor as smart_module
from services.openai_provider import (
    OpenAIProviderConfig,
    extraction_items_schema,
    openai_text_json_response,
)


class FakeResponses:
    def __init__(self, output_text):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type("Response", (), {"output_text": self.output_text})()


class FakeOpenAIClient:
    def __init__(self, output_text='{"items":[]}'):
        self.responses = FakeResponses(output_text)


class OpenAIExtractionProviderSwitchTests(unittest.IsolatedAsyncioTestCase):
    def test_text_json_response_uses_openai_structured_schema_without_secret(self):
        client = FakeOpenAIClient('{"items":[]}')
        config = OpenAIProviderConfig(
            api_key="sk-secret-test",
            text_model="gpt-text-test",
            vision_model="gpt-vision-test",
            embedding_model="text-embedding-test",
        )

        result = openai_text_json_response(
            "extract visible values",
            client=client,
            config=config,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(client.responses.calls[0]["model"], "gpt-text-test")
        self.assertEqual(
            client.responses.calls[0]["text"]["format"]["schema"],
            extraction_items_schema(),
        )
        self.assertNotIn("sk-secret-test", str(result))

    def test_smart_ai_processor_openai_mode_is_deprecated_and_creates_hugging_face_clients(self):
        fake_client = object()
        with patch.object(smart_module.settings, "model_provider", "openai"):
            with patch.object(
                smart_module,
                "AsyncInferenceClient",
                return_value=fake_client,
            ):
                processor = smart_module.SmartAIProcessor()

        self.assertIs(processor.text_client, fake_client)
        self.assertIs(processor.vlm_client, fake_client)

    async def test_text_extraction_routes_to_huggingface_when_openai_is_deprecated(self):
        processor = smart_module.SmartAIProcessor()
        processor.text_client = SimpleNamespace(
            chat_completion=AsyncMock(
                return_value=SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"items":[{"label":"Cash","value":"1,000"}]}'))]
                )
            )
        )

        with patch.object(smart_module.settings, "model_provider", "openai"):
            with patch.object(
                smart_module,
                "async_openai_text_json_response",
                new=AsyncMock(side_effect=AssertionError("OpenAI should not be called")),
                create=True,
            ):
                extracted = await processor._call_text_extraction_model(
                    extraction_prompt="Return JSON.",
                    source_text="Cash 1,000",
                    source_name="native_pdf",
                )

        self.assertEqual(extracted["items"][0]["label"], "Cash")

    def test_smart_ai_processor_parses_raw_structured_json_with_multiple_items(self):
        processor = smart_module.SmartAIProcessor()

        parsed = processor._extract_json_from_response(
            '{"items":[{"label":"Cash","value":"1,000"},{"label":"Total assets","value":"1,000"}]}'
        )

        self.assertEqual(len(parsed["items"]), 2)

    async def test_vision_extraction_routes_to_huggingface_when_openai_is_deprecated(self):
        processor = smart_module.SmartAIProcessor()
        processor.vlm_client = SimpleNamespace(
            chat_completion=AsyncMock(
                return_value=SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"items":[{"label":"Revenue","value":"2,000"}]}'))]
                )
            )
        )

        with patch.object(smart_module.settings, "model_provider", "openai"):
            with patch.object(
                smart_module,
                "async_openai_vision_json_response_from_base64",
                new=AsyncMock(side_effect=AssertionError("OpenAI should not be called")),
                create=True,
            ):
                extracted = await processor._call_ai_model_with_prompt(
                    image_base64="ZmFrZS1pbWFnZQ==",
                    prompt="Return JSON.",
                )

        self.assertEqual(extracted["items"][0]["label"], "Revenue")

    async def test_stage1_classifier_routes_to_huggingface_when_openai_is_deprecated(self):
        fake_client = SimpleNamespace(
            chat_completion=AsyncMock(
                return_value=SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=(
                                    '{"classifications":[{"code":"210000","confidence":0.91,'
                                    '"section_location":"full","reasoning":"balance sheet heading"}]}'
                                )
                            )
                        )
                    ]
                )
            )
        )
        with patch.object(stage1_module.settings, "model_provider", "openai"):
            with patch.object(
                stage1_module,
                "AsyncInferenceClient",
                return_value=fake_client,
            ):
                classifier = stage1_module.StatementClassifier()

            with patch.object(
                stage1_module,
                "async_openai_vision_json_response_from_base64",
                new=AsyncMock(side_effect=AssertionError("OpenAI should not be called")),
                create=True,
            ):
                classifications = await classifier.classify_page(
                    image_base64="ZmFrZS1pbWFnZQ==",
                    page_number=1,
                    page_context="Statement of financial position",
                )

        self.assertEqual(classifications[0]["code"], "210000")
        self.assertEqual(classifier.client, fake_client)

    async def test_missing_openai_key_fails_clearly_before_model_call(self):
        config = OpenAIProviderConfig(
            api_key="",
            text_model="gpt-text-test",
            vision_model="gpt-vision-test",
            embedding_model="text-embedding-test",
        )

        result = openai_text_json_response("extract", config=config)

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "configuration")
        self.assertIn("OPENAI_API_KEY", result["error"])


if __name__ == "__main__":
    unittest.main()
