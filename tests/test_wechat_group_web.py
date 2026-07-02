import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

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


class WechatGroupWebTest(unittest.TestCase):
    def setUp(self):
        from config import conf

        self._original_config = {
            "channel_type": conf().get("channel_type"),
            "wechat_group_room_ids": conf().get("wechat_group_room_ids"),
            "wechat_group_names": conf().get("wechat_group_names"),
            "wechat_group_persona_prompt": conf().get("wechat_group_persona_prompt"),
            "wechat_group_persona_preset_id": conf().get("wechat_group_persona_preset_id"),
            "wechat_group_recent_context_enabled": conf().get("wechat_group_recent_context_enabled"),
            "wechat_group_recent_context_limit": conf().get("wechat_group_recent_context_limit"),
            "wechat_group_recent_context_minutes": conf().get("wechat_group_recent_context_minutes"),
        }

    def tearDown(self):
        from config import conf

        for key, value in self._original_config.items():
            if value is None:
                conf().pop(key, None)
            else:
                conf()[key] = value

    def test_channels_api_lists_wechat_group_as_qr_channel(self):
        from channel.web.web_channel import ChannelsHandler

        handler = ChannelsHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch("channel.web.web_channel.conf", return_value={"channel_type": "web"}):
            result = json.loads(handler.GET())

        item = next((ch for ch in result["channels"] if ch["name"] == "wechat_group"), None)
        self.assertIsNotNone(item)
        self.assertEqual({"zh": "个人微信群", "en": "WeChat Groups"}, item["label"])
        self.assertEqual([], item["fields"])
        self.assertFalse(item["active"])
        self.assertIn("extra", item)
        self.assertIn("persona", item["extra"])
        self.assertIn("persona_presets", item["extra"])
        self.assertEqual(
            {
                "enabled": True,
                "limit": 20,
                "minutes": 60,
            },
            item["extra"]["recent_context"],
        )
        self.assertEqual("owner-digital-twin", item["extra"]["persona"]["preset_id"])

    def test_wechat_group_qr_handler_returns_running_channel_qr(self):
        from channel.web.web_channel import WechatGroupQrHandler

        channel = Mock(
            status="qr_ready",
            qr_code="https://wechaty.js.org/qrcode/test",
            rooms=[{"id": "room@@abc", "name": "测试群"}],
        )
        handler = WechatGroupQrHandler()

        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupQrHandler, "_get_running_channel", return_value=channel), \
                patch.object(WechatGroupQrHandler, "_qr_to_data_uri", return_value="data:image/png;base64,abc"):
            result = json.loads(handler.GET())

        self.assertEqual("success", result["status"])
        self.assertEqual("qr_ready", result["login_status"])
        self.assertEqual("https://wechaty.js.org/qrcode/test", result["qrcode_url"])
        self.assertEqual("data:image/png;base64,abc", result["qr_image"])
        self.assertEqual([{"id": "room@@abc", "name": "测试群"}], result["rooms"])

    def test_channels_save_wechat_group_extra_config(self):
        from channel.web.web_channel import ChannelsHandler
        from config import conf

        handler = ChannelsHandler()
        body = {
            "action": "save",
            "channel": "wechat_group",
            "config": {
                "wechat_group_room_ids": ["room@@abc"],
                "wechat_group_names": ["测试群"],
                "wechat_group_persona_prompt": "  自定义人设\r\n第二行  ",
                "wechat_group_persona_preset_id": "tech-duty",
                "wechat_group_recent_context_enabled": False,
                "wechat_group_recent_context_limit": "12",
                "wechat_group_recent_context_minutes": "45",
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch("channel.web.web_channel._require_auth"), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")), \
                patch("channel.web.web_channel.get_data_root", return_value=tmpdir):
            result = json.loads(handler.POST())

        self.assertEqual("success", result["status"])
        self.assertEqual(["room@@abc"], conf()["wechat_group_room_ids"])
        self.assertEqual(["测试群"], conf()["wechat_group_names"])
        self.assertEqual("自定义人设\n第二行", conf()["wechat_group_persona_prompt"])
        self.assertEqual("custom", conf()["wechat_group_persona_preset_id"])
        self.assertFalse(conf()["wechat_group_recent_context_enabled"])
        self.assertEqual(12, conf()["wechat_group_recent_context_limit"])
        self.assertEqual(45, conf()["wechat_group_recent_context_minutes"])


if __name__ == "__main__":
    unittest.main()
