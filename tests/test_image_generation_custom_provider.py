# encoding:utf-8
import base64
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config as config_module
from config import Config


def set_conf(d):
    config_module.config = Config(d)


def load_generate_module():
    path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "skills",
        "image-generation",
        "scripts",
        "generate.py",
    )
    spec = importlib.util.spec_from_file_location("image_generation_generate_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Response:
    status_code = 200
    text = ""
    reason = "OK"
    url = ""

    def json(self):
        return {
            "data": [
                {"b64_json": base64.b64encode(b"fake-png-bytes").decode("ascii")}
            ]
        }


class TestImageGenerationCustomProvider(unittest.TestCase):
    def setUp(self):
        self.generate = load_generate_module()

    def tearDown(self):
        set_conf({})

    def test_build_providers_uses_explicit_custom_provider(self):
        set_conf({
            "custom_providers": [
                {
                    "id": "img01",
                    "name": "NewAPI Image",
                    "api_key": "sk-custom",
                    "api_base": "https://newapi.example.com/v1",
                    "model": "newapi-image-model",
                }
            ]
        })

        providers = self.generate._build_providers("", provider_id="custom:img01")

        self.assertEqual(len(providers), 1)
        label, provider = providers[0]
        self.assertEqual(label, "Custom:NewAPI Image")
        self.assertIsInstance(provider, self.generate.OpenAIProvider)
        self.assertEqual(provider.api_key, "sk-custom")
        self.assertEqual(provider.api_base, "https://newapi.example.com/v1")
        self.assertEqual(provider.model, "newapi-image-model")

    def test_build_providers_loads_custom_provider_from_config_file_when_conf_is_empty(self):
        set_conf({})
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, "config.json")
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "custom_providers": [
                            {
                                "id": "img01",
                                "name": "NewAPI Image",
                                "api_key": "sk-custom",
                                "api_base": "https://newapi.example.com/v1",
                                "model": "newapi-image-model",
                            }
                        ]
                    },
                    f,
                )

            with patch.dict(os.environ, {"COW_DATA_DIR": tmp}):
                providers = self.generate._build_providers("", provider_id="custom:img01")

        self.assertEqual(len(providers), 1)
        label, provider = providers[0]
        self.assertEqual(label, "Custom:NewAPI Image")
        self.assertEqual(provider.api_key, "sk-custom")
        self.assertEqual(provider.api_base, "https://newapi.example.com/v1")
        self.assertEqual(provider.model, "newapi-image-model")

    def test_custom_provider_generation_hits_custom_images_endpoint(self):
        set_conf({
            "custom_providers": [
                {
                    "id": "img01",
                    "name": "NewAPI Image",
                    "api_key": "sk-custom",
                    "api_base": "https://newapi.example.com/v1",
                    "model": "newapi-image-model",
                }
            ]
        })
        provider = self.generate._build_providers(
            "override-image-model",
            provider_id="custom:img01",
        )[0][1]

        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            resp = _Response()
            resp.url = url
            return resp

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.generate, "requests", types.SimpleNamespace(post=fake_post)):
                paths = provider.generate("draw a cow", output_dir=tmp)

        self.assertEqual(len(paths), 1)
        self.assertEqual(calls[0][0], "https://newapi.example.com/v1/images/generations")
        self.assertEqual(calls[0][1]["headers"]["Authorization"], "Bearer sk-custom")
        self.assertEqual(calls[0][1]["json"]["model"], "override-image-model")
        self.assertEqual(calls[0][1]["json"]["prompt"], "draw a cow")

    def test_custom_provider_requires_api_key_base_and_model(self):
        set_conf({
            "custom_providers": [
                {"id": "no-key", "name": "No Key", "api_base": "https://x/v1", "model": "m"},
                {"id": "no-base", "name": "No Base", "api_key": "sk", "model": "m"},
                {"id": "no-model", "name": "No Model", "api_key": "sk", "api_base": "https://x/v1"},
            ]
        })

        with self.assertRaisesRegex(ValueError, "api_key"):
            self.generate._build_providers("", provider_id="custom:no-key")
        with self.assertRaisesRegex(ValueError, "api_base"):
            self.generate._build_providers("", provider_id="custom:no-base")
        with self.assertRaisesRegex(ValueError, "model"):
            self.generate._build_providers("", provider_id="custom:no-model")
        with self.assertRaisesRegex(ValueError, "unknown custom provider id"):
            self.generate._build_providers("", provider_id="custom:missing")


if __name__ == "__main__":
    unittest.main()
