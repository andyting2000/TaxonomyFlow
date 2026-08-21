import importlib
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import config as config_module
from scripts.openai_provider_smoke import build_parser, main
from services.openai_provider import (
    OpenAIProviderConfig,
    build_vision_input,
    document_classification_schema,
    openai_structured_json_smoke,
    openai_text_smoke,
    openai_vision_smoke,
    parse_structured_json_output,
)


class FakeResponses:
    def __init__(self, output_text):
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


class FakeOpenAIClient:
    def __init__(self, output_text):
        self.responses = FakeResponses(output_text)


class OpenAIProviderTests(unittest.TestCase):
    def test_openai_env_can_exist_without_becoming_active_provider(self):
        env = {
            "MODEL_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test-openai",
            "OPENAI_TEXT_MODEL": "gpt-test-text",
            "OPENAI_VISION_MODEL": "gpt-test-vision",
            "OPENAI_EMBEDDING_MODEL": "text-embedding-test",
            "MODEL_API_TOKEN": "",
            "HUGGING_FACE_TOKEN": "",
        }

        try:
            with patch.dict(os.environ, env, clear=True):
                reloaded = importlib.reload(config_module)

                self.assertEqual(reloaded.settings.configured_model_provider, "openai")
                self.assertEqual(reloaded.settings.model_provider, "huggingface")
                self.assertEqual(reloaded.settings.deprecated_model_provider, "openai")
                self.assertEqual(reloaded.settings.openai_api_key, "sk-test-openai")
                self.assertEqual(reloaded.settings.openai_text_model, "gpt-test-text")
                self.assertEqual(reloaded.settings.openai_vision_model, "gpt-test-vision")
                self.assertEqual(reloaded.settings.openai_embedding_model, "text-embedding-test")
        finally:
            importlib.reload(config_module)

    def test_openai_sdk_is_declared_in_requirements(self):
        requirements = Path("requirements.txt").read_text(encoding="utf-8")

        self.assertIn("openai==2.32.0", requirements)

    def test_missing_api_key_returns_clear_configuration_error(self):
        result = openai_text_smoke(
            "hello",
            config=OpenAIProviderConfig(
                api_key="",
                text_model="gpt-test",
                vision_model="gpt-test",
                embedding_model="text-embedding-test",
            ),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "configuration")
        self.assertIn("OPENAI_API_KEY", result["error"])

    def test_text_smoke_builds_request_without_exposing_secret(self):
        client = FakeOpenAIClient("text smoke ok")
        config = OpenAIProviderConfig(
            api_key="sk-secret-value",
            text_model="gpt-test",
            vision_model="gpt-vision-test",
            embedding_model="text-embedding-test",
        )

        result = openai_text_smoke("hello", client=client, config=config)

        self.assertTrue(result["ok"])
        self.assertEqual(result["output_text"], "text smoke ok")
        self.assertEqual(client.responses.calls[0]["model"], "gpt-test")
        self.assertEqual(client.responses.calls[0]["input"], "hello")
        self.assertNotIn("api_key", client.responses.calls[0])
        self.assertNotIn("sk-secret-value", str(result))

    def test_structured_json_smoke_uses_schema_and_parses_response(self):
        client = FakeOpenAIClient(
            '{"document_type":"financial_statement","confidence":0.91,"notes":"smoke"}'
        )
        config = OpenAIProviderConfig(
            api_key="sk-secret-value",
            text_model="gpt-test",
            vision_model="gpt-vision-test",
            embedding_model="text-embedding-test",
        )

        result = openai_structured_json_smoke("classify", client=client, config=config)

        self.assertTrue(result["ok"])
        self.assertEqual(result["parsed_json"]["document_type"], "financial_statement")
        text_format = client.responses.calls[0]["text"]["format"]
        self.assertEqual(text_format["type"], "json_schema")
        self.assertEqual(text_format["schema"], document_classification_schema())

    def test_structured_response_parser_handles_valid_json(self):
        parsed = parse_structured_json_output(
            '{"document_type":"financial_statement","confidence":0.5,"notes":"ok"}'
        )

        self.assertEqual(parsed["confidence"], 0.5)

    def test_vision_input_encodes_image_as_data_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "page.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

            payload = build_vision_input(str(image_path), "summarize")

        content = payload[0]["content"]
        self.assertEqual(content[0], {"type": "input_text", "text": "summarize"})
        self.assertEqual(content[1]["type"], "input_image")
        self.assertTrue(content[1]["image_url"].startswith("data:image/png;base64,"))
        self.assertEqual(content[1]["detail"], "low")

    def test_vision_smoke_skips_missing_image_without_network(self):
        result = openai_vision_smoke(
            "missing-page.png",
            "summarize",
            config=OpenAIProviderConfig(
                api_key="",
                text_model="gpt-test",
                vision_model="gpt-vision-test",
                embedding_model="text-embedding-test",
            ),
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_type"], "missing_image")
        self.assertIn("skipped", result["error"])

    def test_smoke_script_argument_parsing(self):
        args = build_parser().parse_args(["--text", "--structured-json", "--image", "page.png"])

        self.assertTrue(args.text)
        self.assertTrue(args.structured_json)
        self.assertEqual(args.image, "page.png")

    def test_smoke_script_requires_a_selected_smoke(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main([]), 2)


if __name__ == "__main__":
    unittest.main()
