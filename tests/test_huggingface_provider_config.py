import importlib
import os
import unittest
from unittest.mock import patch

import config as config_module
from services.openai_provider import is_openai_provider


class HuggingFaceProviderConfigTests(unittest.TestCase):
    def tearDown(self):
        importlib.reload(config_module)

    def test_model_provider_default_resolves_to_huggingface(self):
        with patch.dict(os.environ, {"MODEL_PROVIDER": "", "OPENAI_API_KEY": ""}, clear=True):
            reloaded = importlib.reload(config_module)

        self.assertEqual(reloaded.settings.model_provider, "huggingface")

    def test_model_ids_resolve_from_env(self):
        env = {
            "MODEL_PROVIDER": "huggingface",
            "MODEL_API_TOKEN": "hf-test-token",
            "TEXT_MODEL_ID": "text/model",
            "VISION_MODEL_ID": "vision/model",
            "EMBEDDING_MODEL_ID": "embedding/model",
            "EMBEDDING_DIMENSION": "4096",
            "EMBEDDING_NORMALIZE": "false",
        }
        with patch.dict(os.environ, env, clear=True):
            reloaded = importlib.reload(config_module)

        self.assertEqual(reloaded.settings.model_provider, "huggingface")
        self.assertEqual(reloaded.settings.model_api_token, "hf-test-token")
        self.assertEqual(reloaded.settings.ai_text_model_id, "text/model")
        self.assertEqual(reloaded.settings.ai_vlm_model_id, "vision/model")
        self.assertEqual(reloaded.settings.embedding_model_id, "embedding/model")
        self.assertEqual(reloaded.settings.embedding_dimension, 4096)
        self.assertFalse(reloaded.settings.embedding_normalize)

    def test_openai_env_variables_are_not_required_for_startup_config(self):
        env = {
            "MODEL_PROVIDER": "huggingface",
            "MODEL_API_TOKEN": "hf-test-token",
            "OPENAI_API_KEY": "",
        }
        with patch.dict(os.environ, env, clear=True):
            reloaded = importlib.reload(config_module)

        self.assertEqual(reloaded.settings.model_provider, "huggingface")
        self.assertEqual(reloaded.settings.openai_api_key, "")

    def test_openai_provider_request_is_deprecated_and_not_active(self):
        with patch.dict(os.environ, {"MODEL_PROVIDER": "openai", "MODEL_API_TOKEN": "hf-test-token"}, clear=True):
            reloaded = importlib.reload(config_module)

        self.assertEqual(reloaded.settings.configured_model_provider, "openai")
        self.assertEqual(reloaded.settings.deprecated_model_provider, "openai")
        self.assertEqual(reloaded.settings.model_provider, "huggingface")
        self.assertFalse(is_openai_provider(reloaded.settings))


if __name__ == "__main__":
    unittest.main()
