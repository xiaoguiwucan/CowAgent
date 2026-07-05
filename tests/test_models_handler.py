# encoding:utf-8
import json
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

if "web" not in sys.modules:
    web_stub = types.ModuleType("web")
    web_stub.HTTPError = type("HTTPError", (Exception,), {})
    web_stub.cookies = lambda: {}
    web_stub.header = lambda *args, **kwargs: None
    web_stub.data = lambda: b"{}"
    web_stub.input = lambda **kwargs: types.SimpleNamespace(**kwargs)
    web_stub.setcookie = lambda *args, **kwargs: None
    web_stub.seeother = lambda *args, **kwargs: Exception("seeother")
    web_stub.notfound = lambda *args, **kwargs: Exception("notfound")
    web_stub.badrequest = lambda *args, **kwargs: Exception("badrequest")
    web_stub.application = lambda *args, **kwargs: types.SimpleNamespace(wsgifunc=lambda: None)
    web_stub.httpserver = types.SimpleNamespace(
        LogMiddleware=type("LogMiddleware", (), {"log": lambda *args, **kwargs: None}),
        StaticMiddleware=lambda app: app,
        WSGIServer=lambda *args, **kwargs: types.SimpleNamespace(serve_forever=lambda: None),
    )
    sys.modules["web"] = web_stub


class TestModelsHandler(unittest.TestCase):
    def test_image_capability_exposes_custom_providers(self):
        from config import Config
        import config as config_module
        from channel.web.web_channel import ModelsHandler

        local_config = Config({
            "custom_providers": [
                {
                    "id": "img01",
                    "name": "NewAPI Image",
                    "api_key": "sk-test",
                    "api_base": "https://newapi.example.com/v1",
                    "model": "my-image-model",
                }
            ],
            "skills": {
                "image-generation": {
                    "provider": "custom:img01",
                    "model": "my-image-model",
                }
            },
        })

        with patch.object(config_module, "config", local_config):
            cap = ModelsHandler._image_capability(local_config)

        self.assertIn("custom:img01", cap["providers"])
        self.assertEqual(cap["current_provider"], "custom:img01")
        self.assertEqual(cap["current_model"], "my-image-model")
        self.assertTrue(cap["runtime_active"])
        self.assertNotEqual(cap.get("note"), "router_pending")

    def test_set_image_accepts_custom_provider_and_uses_default_model(self):
        from config import Config
        import config as config_module
        from channel.web.web_channel import ModelsHandler

        local_config = Config({
            "custom_providers": [
                {
                    "id": "img01",
                    "name": "NewAPI Image",
                    "api_key": "sk-test",
                    "api_base": "https://newapi.example.com/v1",
                    "model": "my-image-model",
                }
            ],
        })
        file_config = {
            "custom_providers": [
                {
                    "id": "img01",
                    "name": "NewAPI Image",
                    "api_key": "sk-test",
                    "api_base": "https://newapi.example.com/v1",
                    "model": "my-image-model",
                }
            ],
        }
        handler = ModelsHandler()

        with patch.object(config_module, "config", local_config):
            with patch("channel.web.web_channel.conf", return_value=local_config):
                with patch.object(ModelsHandler, "_read_file_config", return_value=file_config):
                    with patch.object(ModelsHandler, "_write_file_config") as write_file:
                        result = json.loads(handler._handle_set_capability({
                            "capability": "image",
                            "provider_id": "custom:img01",
                            "model": "",
                        }))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider"], "custom:img01")
        self.assertEqual(result["model"], "my-image-model")
        self.assertNotIn("router_pending", result)
        self.assertEqual(
            local_config["skills"]["image-generation"]["provider"],
            "custom:img01",
        )
        self.assertEqual(
            local_config["skills"]["image-generation"]["model"],
            "my-image-model",
        )
        write_file.assert_called_once_with(file_config)

    def test_set_image_strips_invisible_model_chars(self):
        from config import Config
        import config as config_module
        from channel.web.web_channel import ModelsHandler

        local_config = Config({
            "custom_providers": [
                {
                    "id": "img01",
                    "name": "NewAPI Image",
                    "api_key": "sk-test",
                    "api_base": "https://newapi.example.com/v1",
                }
            ],
        })
        file_config = {"custom_providers": list(local_config["custom_providers"])}
        handler = ModelsHandler()

        with patch.object(config_module, "config", local_config):
            with patch("channel.web.web_channel.conf", return_value=local_config):
                with patch.object(ModelsHandler, "_read_file_config", return_value=file_config):
                    with patch.object(ModelsHandler, "_write_file_config"):
                        result = json.loads(handler._handle_set_capability({
                            "capability": "image",
                            "provider_id": "custom:img01\u200c",
                            "model": "gpt-image-2\u200c",
                        }))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider"], "custom:img01")
        self.assertEqual(result["model"], "gpt-image-2")
        self.assertEqual(
            local_config["skills"]["image-generation"]["model"],
            "gpt-image-2",
        )

    def test_set_image_rejects_unknown_custom_provider(self):
        from config import Config
        import config as config_module
        from channel.web.web_channel import ModelsHandler

        local_config = Config({"custom_providers": []})
        handler = ModelsHandler()

        with patch.object(config_module, "config", local_config):
            with patch("channel.web.web_channel.conf", return_value=local_config):
                result = json.loads(handler._handle_set_capability({
                    "capability": "image",
                    "provider_id": "custom:missing",
                    "model": "my-image-model",
                }))

        self.assertEqual(result["status"], "error")
        self.assertIn("unknown custom provider id", result["message"])

    def test_set_asr_capability_persists_provider_and_model(self):
        from channel.web.web_channel import ModelsHandler

        local_config = {}
        file_config = {}
        handler = ModelsHandler()

        with patch("channel.web.web_channel.conf", return_value=local_config):
            with patch.object(ModelsHandler, "_read_file_config", return_value=file_config):
                with patch.object(ModelsHandler, "_write_file_config") as write_file:
                    with patch.object(ModelsHandler, "_refresh_voice_routing") as refresh_voice:
                        result = json.loads(handler._handle_set_capability({
                            "capability": "asr",
                            "provider_id": "dashscope",
                            "model": "qwen3-asr-flash",
                        }))

        self.assertEqual(result["status"], "success")
        self.assertEqual(local_config["voice_to_text"], "dashscope")
        self.assertEqual(local_config["voice_to_text_model"], "qwen3-asr-flash")
        self.assertEqual(file_config["voice_to_text"], "dashscope")
        self.assertEqual(file_config["voice_to_text_model"], "qwen3-asr-flash")
        write_file.assert_called_once_with(file_config)
        refresh_voice.assert_called_once()

    def test_set_asr_empty_model_keeps_existing(self):
        # Switching provider with an empty model must not wipe a user's
        # hand-configured voice_to_text_model.
        from channel.web.web_channel import ModelsHandler

        local_config = {"voice_to_text_model": "qwen3-asr-flash"}
        file_config = {"voice_to_text_model": "qwen3-asr-flash"}
        handler = ModelsHandler()

        with patch("channel.web.web_channel.conf", return_value=local_config):
            with patch.object(ModelsHandler, "_read_file_config", return_value=file_config):
                with patch.object(ModelsHandler, "_write_file_config"):
                    with patch.object(ModelsHandler, "_refresh_voice_routing"):
                        result = json.loads(handler._handle_set_capability({
                            "capability": "asr",
                            "provider_id": "zhipu",
                            "model": "",
                        }))

        self.assertEqual(result["status"], "success")
        self.assertEqual(local_config["voice_to_text"], "zhipu")
        # Existing model preserved, not overwritten with "".
        self.assertEqual(local_config["voice_to_text_model"], "qwen3-asr-flash")
        self.assertEqual(file_config["voice_to_text_model"], "qwen3-asr-flash")
        self.assertEqual(result["model"], "qwen3-asr-flash")

    def test_asr_capability_exposes_provider_models(self):
        from channel.web.web_channel import ModelsHandler

        cap = ModelsHandler._asr_capability({
            "voice_to_text": "dashscope",
            "voice_to_text_model": "qwen3-asr-flash",
        })

        self.assertTrue(cap["editable"])
        self.assertEqual(cap["current_provider"], "dashscope")
        self.assertEqual(cap["current_model"], "qwen3-asr-flash")
        self.assertIn("provider_models", cap)
        self.assertIn("dashscope", cap["provider_models"])

    def test_search_capability_exposes_serper_and_jina_as_dedicated_key_providers(self):
        from channel.web.web_channel import ModelsHandler

        cap = ModelsHandler._search_capability({
            "tools": {
                "web_search": {
                    "serper_api_key": "serper-key",
                    "jina_api_key": "jina-key",
                }
            }
        })

        provider_map = {item["id"]: item for item in cap["providers"]}
        self.assertIn("serper", provider_map)
        self.assertIn("jina", provider_map)
        self.assertTrue(provider_map["serper"]["configured"])
        self.assertTrue(provider_map["jina"]["configured"])
        self.assertTrue(provider_map["serper"]["needs_dedicated_key"])
        self.assertTrue(provider_map["jina"]["needs_dedicated_key"])

    def test_set_search_credential_persists_selected_provider_key(self):
        from channel.web.web_channel import ModelsHandler

        local_config = {"tools": {"web_search": {}}}
        file_config = {"tools": {"web_search": {}}}
        handler = ModelsHandler()

        with patch("channel.web.web_channel.conf", return_value=local_config):
            with patch.object(ModelsHandler, "_read_file_config", return_value=file_config):
                with patch.object(ModelsHandler, "_write_file_config") as write_file:
                    result = json.loads(handler._handle_set_search_credential({
                        "provider": "serper",
                        "api_key": "serper-key",
                    }))

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["provider"], "serper")
        self.assertEqual(local_config["tools"]["web_search"]["serper_api_key"], "serper-key")
        self.assertEqual(file_config["tools"]["web_search"]["serper_api_key"], "serper-key")
        write_file.assert_called_once_with(file_config)


if __name__ == "__main__":
    unittest.main()
