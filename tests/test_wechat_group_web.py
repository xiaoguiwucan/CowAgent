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
            "wechat_group_knowledge_enabled": conf().get("wechat_group_knowledge_enabled"),
            "wechat_group_profile_enabled": conf().get("wechat_group_profile_enabled"),
            "wechat_group_profile_context_limit": conf().get("wechat_group_profile_context_limit"),
            "wechat_group_group_memory_context_limit": conf().get("wechat_group_group_memory_context_limit"),
            "wechat_group_learning_enabled": conf().get("wechat_group_learning_enabled"),
            "wechat_group_learning_batch_message_limit": conf().get("wechat_group_learning_batch_message_limit"),
            "wechat_group_learning_profile_min_messages": conf().get("wechat_group_learning_profile_min_messages"),
            "wechat_group_learning_profile_sample_limit": conf().get("wechat_group_learning_profile_sample_limit"),
            "wechat_group_learning_group_memory_min_messages": conf().get("wechat_group_learning_group_memory_min_messages"),
            "wechat_group_learning_group_memory_window_minutes": conf().get("wechat_group_learning_group_memory_window_minutes"),
            "wechat_group_free_reply_enabled": conf().get("wechat_group_free_reply_enabled"),
            "wechat_group_free_reply_room_ids": conf().get("wechat_group_free_reply_room_ids"),
            "wechat_group_free_reply_names": conf().get("wechat_group_free_reply_names"),
            "wechat_group_free_reply_activity_level": conf().get("wechat_group_free_reply_activity_level"),
            "wechat_group_free_reply_queue_ttl_seconds": conf().get("wechat_group_free_reply_queue_ttl_seconds"),
            "wechat_group_free_reply_worker_max_workers": conf().get("wechat_group_free_reply_worker_max_workers"),
            "wechat_group_free_reply_worker_queue_size": conf().get("wechat_group_free_reply_worker_queue_size"),
            "wechat_group_free_reply_llm_judge_enabled": conf().get("wechat_group_free_reply_llm_judge_enabled"),
            "wechat_group_free_reply_llm_judge_timeout_seconds": conf().get("wechat_group_free_reply_llm_judge_timeout_seconds"),
            "wechat_group_free_reply_llm_judge_min_confidence": conf().get("wechat_group_free_reply_llm_judge_min_confidence"),
            "wechat_group_free_reply_profiles": conf().get("wechat_group_free_reply_profiles"),
            "wechat_group_image_understanding_enabled": conf().get("wechat_group_image_understanding_enabled"),
            "wechat_group_image_understanding_comment_enabled": conf().get("wechat_group_image_understanding_comment_enabled"),
            "wechat_group_image_understanding_prompt": conf().get("wechat_group_image_understanding_prompt"),
            "wechat_group_image_understanding_cache_minutes": conf().get("wechat_group_image_understanding_cache_minutes"),
            "wechat_group_free_reply_image_understanding_enabled": conf().get("wechat_group_free_reply_image_understanding_enabled"),
            "wechat_group_image_create_hourly_limit": conf().get("wechat_group_image_create_hourly_limit"),
            "wechat_group_video_understanding_enabled": conf().get("wechat_group_video_understanding_enabled"),
            "wechat_group_forward_preview_enabled": conf().get("wechat_group_forward_preview_enabled"),
            "wechat_group_quote_context_enabled": conf().get("wechat_group_quote_context_enabled"),
            "wechat_group_topic_enabled": conf().get("wechat_group_topic_enabled"),
            "wechat_group_topic_recent_message_limit": conf().get("wechat_group_topic_recent_message_limit"),
            "wechat_group_topic_active_count_limit": conf().get("wechat_group_topic_active_count_limit"),
            "wechat_group_topic_summary_refresh_message_gap": conf().get("wechat_group_topic_summary_refresh_message_gap"),
            "wechat_group_topic_context_limit": conf().get("wechat_group_topic_context_limit"),
            "wechat_group_topic_archive_recall_limit": conf().get("wechat_group_topic_archive_recall_limit"),
            "wechat_group_style_enabled": conf().get("wechat_group_style_enabled"),
            "wechat_group_style_learning_enabled": conf().get("wechat_group_style_learning_enabled"),
            "wechat_group_style_context_limit": conf().get("wechat_group_style_context_limit"),
            "wechat_group_style_candidate_min_evidence": conf().get("wechat_group_style_candidate_min_evidence"),
            "wechat_group_style_learning_batch_limit": conf().get("wechat_group_style_learning_batch_limit"),
            "wechat_group_style_auto_apply_enabled": conf().get("wechat_group_style_auto_apply_enabled"),
            "wechat_group_emotion_enabled": conf().get("wechat_group_emotion_enabled"),
            "wechat_group_emotion_decay_minutes": conf().get("wechat_group_emotion_decay_minutes"),
            "wechat_group_emotion_default_valence": conf().get("wechat_group_emotion_default_valence"),
            "wechat_group_emotion_default_energy": conf().get("wechat_group_emotion_default_energy"),
            "wechat_group_emotion_default_sociability": conf().get("wechat_group_emotion_default_sociability"),
            "wechat_group_free_reply_time_rules_enabled": conf().get("wechat_group_free_reply_time_rules_enabled"),
            "wechat_group_free_reply_time_rules": conf().get("wechat_group_free_reply_time_rules"),
            "wechat_group_free_reply_typing_delay_enabled": conf().get("wechat_group_free_reply_typing_delay_enabled"),
            "wechat_group_free_reply_typing_chars_per_second": conf().get("wechat_group_free_reply_typing_chars_per_second"),
            "wechat_group_sticker_enabled": conf().get("wechat_group_sticker_enabled"),
            "wechat_group_sticker_auto_collect_enabled": conf().get("wechat_group_sticker_auto_collect_enabled"),
            "wechat_group_sticker_context_limit": conf().get("wechat_group_sticker_context_limit"),
            "wechat_group_sticker_max_size_mb": conf().get("wechat_group_sticker_max_size_mb"),
            "wechat_group_sticker_daily_send_limit": conf().get("wechat_group_sticker_daily_send_limit"),
            "wechat_group_sticker_storage_dir": conf().get("wechat_group_sticker_storage_dir"),
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
        self.assertEqual(
            {
                "knowledge_enabled": True,
                "profile_enabled": True,
                "profile_context_limit": 2,
                "group_memory_context_limit": 5,
                "learning_enabled": False,
                "learning_batch_message_limit": 200,
                "learning_profile_min_messages": 6,
                "learning_profile_sample_limit": 30,
                "learning_group_memory_min_messages": 20,
                "learning_group_memory_window_minutes": 120,
            },
            item["extra"]["memory"],
        )
        self.assertEqual("owner-digital-twin", item["extra"]["persona"]["preset_id"])
        self.assertIn("free_reply", item["extra"])
        self.assertIn("rules", item["extra"]["free_reply"])
        self.assertIn("last_decision", item["extra"]["free_reply"])
        self.assertIn("worker", item["extra"]["free_reply"])
        self.assertEqual(
            {
                "understanding_enabled": True,
                "comment_enabled": True,
                "understanding_prompt": "请简洁描述这张图片中的关键信息，并指出可能需要回复的内容。",
                "cache_minutes": 30,
                "free_reply_understanding_enabled": False,
                "create_hourly_limit": 5,
                "video_understanding_enabled": False,
                "forward_preview_enabled": True,
                "quote_context_enabled": True,
            },
            item["extra"]["image"],
        )

    def test_channels_api_lists_wechat_group_humanization_defaults(self):
        from channel.web.web_channel import ChannelsHandler

        handler = ChannelsHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch("channel.web.web_channel.conf", return_value={"channel_type": "web"}):
            result = json.loads(handler.GET())

        item = next((ch for ch in result["channels"] if ch["name"] == "wechat_group"), None)
        self.assertIsNotNone(item)
        self.assertEqual(
            {
                "enabled": True,
                "recent_message_limit": 30,
                "active_count_limit": 3,
                "summary_refresh_message_gap": 8,
                "context_limit": 2,
                "archive_recall_limit": 2,
            },
            item["extra"]["topic"],
        )
        self.assertEqual(
            {
                "enabled": True,
                "learning_enabled": True,
                "context_limit": 3,
                "candidate_min_evidence": 2,
                "learning_batch_limit": 100,
                "auto_apply_enabled": False,
            },
            item["extra"]["style"],
        )
        self.assertEqual(
            {
                "enabled": True,
                "decay_minutes": 10,
                "default_valence": 0,
                "default_energy": 0.5,
                "default_sociability": 0.45,
                "free_reply_time_rules_enabled": False,
                "free_reply_time_rules": [],
                "free_reply_typing_delay_enabled": True,
                "free_reply_typing_chars_per_second": 7,
            },
            item["extra"]["emotion"],
        )
        self.assertEqual(
            {
                "enabled": True,
                "auto_collect_enabled": True,
                "context_limit": 5,
                "max_size_mb": 2,
                "daily_send_limit": 20,
                "storage_dir": "",
            },
            item["extra"]["sticker"],
        )

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
                "wechat_group_knowledge_enabled": False,
                "wechat_group_profile_enabled": True,
                "wechat_group_profile_context_limit": "3",
                "wechat_group_group_memory_context_limit": "7",
                "wechat_group_learning_enabled": True,
                "wechat_group_learning_batch_message_limit": "150",
                "wechat_group_learning_profile_min_messages": "4",
                "wechat_group_learning_profile_sample_limit": "12",
                "wechat_group_learning_group_memory_min_messages": "9",
                "wechat_group_learning_group_memory_window_minutes": "90",
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
        self.assertFalse(conf()["wechat_group_knowledge_enabled"])
        self.assertTrue(conf()["wechat_group_profile_enabled"])
        self.assertEqual(3, conf()["wechat_group_profile_context_limit"])
        self.assertEqual(7, conf()["wechat_group_group_memory_context_limit"])
        self.assertTrue(conf()["wechat_group_learning_enabled"])
        self.assertEqual(150, conf()["wechat_group_learning_batch_message_limit"])
        self.assertEqual(4, conf()["wechat_group_learning_profile_min_messages"])
        self.assertEqual(12, conf()["wechat_group_learning_profile_sample_limit"])
        self.assertEqual(9, conf()["wechat_group_learning_group_memory_min_messages"])
        self.assertEqual(90, conf()["wechat_group_learning_group_memory_window_minutes"])

    def test_channels_save_wechat_group_free_reply_config(self):
        from channel.web.web_channel import ChannelsHandler
        from config import conf

        handler = ChannelsHandler()
        body = {
            "action": "save",
            "channel": "wechat_group",
            "config": {
                "wechat_group_free_reply_enabled": True,
                "wechat_group_free_reply_room_ids": ["room@@abc"],
                "wechat_group_free_reply_names": ["测试群"],
                "wechat_group_free_reply_activity_level": "active",
                "wechat_group_free_reply_queue_ttl_seconds": "999",
                "wechat_group_free_reply_worker_max_workers": "99",
                "wechat_group_free_reply_worker_queue_size": "9999",
                "wechat_group_free_reply_llm_judge_enabled": False,
                "wechat_group_free_reply_llm_judge_timeout_seconds": "99",
                "wechat_group_free_reply_llm_judge_min_confidence": "2",
                "wechat_group_free_reply_profiles": {
                    "active": {
                        "min_score": "25",
                        "min_interval_seconds": "2",
                        "hourly_limit": "3",
                        "consecutive_limit": "4",
                    }
                },
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch("channel.web.web_channel._require_auth"), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")), \
                patch("channel.web.web_channel.get_data_root", return_value=tmpdir):
            result = json.loads(handler.POST())

        self.assertEqual("success", result["status"])
        self.assertTrue(conf()["wechat_group_free_reply_enabled"])
        self.assertEqual(["room@@abc"], conf()["wechat_group_free_reply_room_ids"])
        self.assertEqual(["测试群"], conf()["wechat_group_free_reply_names"])
        self.assertEqual("active", conf()["wechat_group_free_reply_activity_level"])
        self.assertEqual(600, conf()["wechat_group_free_reply_queue_ttl_seconds"])
        self.assertEqual(8, conf()["wechat_group_free_reply_worker_max_workers"])
        self.assertEqual(1000, conf()["wechat_group_free_reply_worker_queue_size"])
        self.assertFalse(conf()["wechat_group_free_reply_llm_judge_enabled"])
        self.assertEqual(30, conf()["wechat_group_free_reply_llm_judge_timeout_seconds"])
        self.assertEqual(1.0, conf()["wechat_group_free_reply_llm_judge_min_confidence"])
        self.assertEqual(25, conf()["wechat_group_free_reply_profiles"]["active"]["min_score"])

    def test_channels_save_wechat_group_image_config(self):
        from channel.web.web_channel import ChannelsHandler
        from config import conf

        handler = ChannelsHandler()
        body = {
            "action": "save",
            "channel": "wechat_group",
            "config": {
                "wechat_group_image_understanding_enabled": False,
                "wechat_group_image_understanding_comment_enabled": False,
                "wechat_group_image_understanding_prompt": "  describe\nbriefly  ",
                "wechat_group_image_understanding_cache_minutes": "999",
                "wechat_group_free_reply_image_understanding_enabled": True,
                "wechat_group_image_create_hourly_limit": "999",
                "wechat_group_video_understanding_enabled": True,
                "wechat_group_forward_preview_enabled": False,
                "wechat_group_quote_context_enabled": False,
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch("channel.web.web_channel._require_auth"), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")), \
                patch("channel.web.web_channel.get_data_root", return_value=tmpdir):
            result = json.loads(handler.POST())

        self.assertEqual("success", result["status"])
        self.assertFalse(conf()["wechat_group_image_understanding_enabled"])
        self.assertFalse(conf()["wechat_group_image_understanding_comment_enabled"])
        self.assertEqual("describe\nbriefly", conf()["wechat_group_image_understanding_prompt"])
        self.assertEqual(120, conf()["wechat_group_image_understanding_cache_minutes"])
        self.assertTrue(conf()["wechat_group_free_reply_image_understanding_enabled"])
        self.assertEqual(100, conf()["wechat_group_image_create_hourly_limit"])
        self.assertTrue(conf()["wechat_group_video_understanding_enabled"])
        self.assertFalse(conf()["wechat_group_forward_preview_enabled"])
        self.assertFalse(conf()["wechat_group_quote_context_enabled"])

    def test_channels_save_wechat_group_humanization_config(self):
        from channel.web.web_channel import ChannelsHandler
        from config import conf

        handler = ChannelsHandler()
        body = {
            "action": "save",
            "channel": "wechat_group",
            "config": {
                "wechat_group_topic_enabled": False,
                "wechat_group_topic_recent_message_limit": "0",
                "wechat_group_topic_active_count_limit": "4",
                "wechat_group_topic_summary_refresh_message_gap": "0",
                "wechat_group_topic_context_limit": "5",
                "wechat_group_topic_archive_recall_limit": "6",
                "wechat_group_style_enabled": False,
                "wechat_group_style_learning_enabled": False,
                "wechat_group_style_context_limit": "4",
                "wechat_group_style_candidate_min_evidence": "0",
                "wechat_group_style_learning_batch_limit": "88",
                "wechat_group_style_auto_apply_enabled": True,
                "wechat_group_emotion_enabled": False,
                "wechat_group_emotion_decay_minutes": "0",
                "wechat_group_emotion_default_valence": "-2",
                "wechat_group_emotion_default_energy": "2",
                "wechat_group_emotion_default_sociability": "-1",
                "wechat_group_free_reply_time_rules_enabled": True,
                "wechat_group_free_reply_time_rules": [{"start": "09:00", "end": "18:00", "days": ["mon", "fri"]}],
                "wechat_group_free_reply_typing_delay_enabled": False,
                "wechat_group_free_reply_typing_chars_per_second": "0",
                "wechat_group_sticker_enabled": False,
                "wechat_group_sticker_auto_collect_enabled": False,
                "wechat_group_sticker_context_limit": "0",
                "wechat_group_sticker_max_size_mb": "99",
                "wechat_group_sticker_daily_send_limit": "999",
                "wechat_group_sticker_storage_dir": "  stickers/cache  ",
            },
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch("channel.web.web_channel._require_auth"), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")), \
                patch("channel.web.web_channel.get_data_root", return_value=tmpdir):
            result = json.loads(handler.POST())

        self.assertEqual("success", result["status"])
        self.assertFalse(conf()["wechat_group_topic_enabled"])
        self.assertEqual(1, conf()["wechat_group_topic_recent_message_limit"])
        self.assertEqual(4, conf()["wechat_group_topic_active_count_limit"])
        self.assertEqual(1, conf()["wechat_group_topic_summary_refresh_message_gap"])
        self.assertEqual(5, conf()["wechat_group_topic_context_limit"])
        self.assertEqual(6, conf()["wechat_group_topic_archive_recall_limit"])
        self.assertFalse(conf()["wechat_group_style_enabled"])
        self.assertFalse(conf()["wechat_group_style_learning_enabled"])
        self.assertEqual(4, conf()["wechat_group_style_context_limit"])
        self.assertEqual(1, conf()["wechat_group_style_candidate_min_evidence"])
        self.assertEqual(88, conf()["wechat_group_style_learning_batch_limit"])
        self.assertTrue(conf()["wechat_group_style_auto_apply_enabled"])
        self.assertFalse(conf()["wechat_group_emotion_enabled"])
        self.assertEqual(1, conf()["wechat_group_emotion_decay_minutes"])
        self.assertEqual(-1.0, conf()["wechat_group_emotion_default_valence"])
        self.assertEqual(1.0, conf()["wechat_group_emotion_default_energy"])
        self.assertEqual(0.0, conf()["wechat_group_emotion_default_sociability"])
        self.assertTrue(conf()["wechat_group_free_reply_time_rules_enabled"])
        self.assertEqual([{"start": "09:00", "end": "18:00", "days": ["mon", "fri"]}], conf()["wechat_group_free_reply_time_rules"])
        self.assertFalse(conf()["wechat_group_free_reply_typing_delay_enabled"])
        self.assertEqual(1, conf()["wechat_group_free_reply_typing_chars_per_second"])
        self.assertFalse(conf()["wechat_group_sticker_enabled"])
        self.assertFalse(conf()["wechat_group_sticker_auto_collect_enabled"])
        self.assertEqual(1, conf()["wechat_group_sticker_context_limit"])
        self.assertEqual(20, conf()["wechat_group_sticker_max_size_mb"])
        self.assertEqual(200, conf()["wechat_group_sticker_daily_send_limit"])
        self.assertEqual("stickers/cache", conf()["wechat_group_sticker_storage_dir"])

    def test_console_updates_free_reply_profile_fields_when_level_changes(self):
        with open("channel/web/static/js/console.js", "r", encoding="utf-8") as f:
            console_js = f.read()

        self.assertIn("function syncFreeReplyProfileFields", console_js)
        self.assertIn("free-reply-activity-level", console_js)
        self.assertIn("syncFreeReplyProfileFields(extra.free_reply || {})", console_js)

    def test_console_contains_wechat_group_image_settings(self):
        with open("channel/web/static/js/console.js", "r", encoding="utf-8") as f:
            console_js = f.read()

        self.assertIn("function readWechatGroupImageSettings", console_js)
        self.assertIn("groups-image-understanding-enabled", console_js)
        self.assertIn("groups-image-free-reply-understanding-enabled", console_js)
        self.assertIn("groups-image-create-hourly-limit", console_js)
        self.assertIn("wechat_group_free_reply_image_understanding_enabled", console_js)
        self.assertIn("wechat_group_image_create_hourly_limit", console_js)
        self.assertIn("groups-video-understanding-enabled", console_js)
        self.assertIn("groups-forward-preview-enabled", console_js)
        self.assertIn("groups-quote-context-enabled", console_js)
        self.assertIn("wechat_group_video_understanding_enabled", console_js)
        self.assertIn("wechat_group_forward_preview_enabled", console_js)
        self.assertIn("wechat_group_quote_context_enabled", console_js)

    def test_console_labels_profile_common_words_as_common_words(self):
        with open("channel/web/static/js/console.js", "r", encoding="utf-8") as f:
            console_js = f.read()

        self.assertIn("groups_memory_common_words: '常用词'", console_js)
        self.assertIn("groups_memory_common_words: 'Common words'", console_js)
        self.assertIn("groups-profiles-detail-common-words", console_js)
        self.assertNotIn("groups-profiles-detail-expertise", console_js)
        self.assertNotIn("groups_memory_expertise: '专业背景'", console_js)

    def test_wechat_group_extra_returns_running_free_reply_status(self):
        from channel.web.web_channel import ChannelsHandler

        running = Mock(free_reply_status=Mock(return_value={
            "config": {"enabled": True},
            "rules": {"positive": [], "negative": []},
            "last_decision": {"triggered": True},
            "worker": {"running": True},
        }))

        with patch.object(ChannelsHandler, "_get_running_wechat_group_channel", return_value=running):
            extra = ChannelsHandler._wechat_group_extra()

        self.assertIn("free_reply", extra)
        self.assertTrue(extra["free_reply"]["enabled"])
        self.assertEqual({"triggered": True}, extra["free_reply"]["last_decision"])
        self.assertEqual({"running": True}, extra["free_reply"]["worker"])

    def test_wechat_group_emotion_state_api_uses_service_and_running_status(self):
        from channel.web.web_channel import WechatGroupEmotionHandler

        class FakeEmotionService:
            def get_state(self, room_id, now=None):
                self.args = (room_id, now)
                return {
                    "room_id": room_id,
                    "valence": 0.1,
                    "energy": 0.6,
                    "sociability": 0.55,
                    "last_decay_at": 100,
                    "last_reply_at": 90,
                    "reply_count_1h": 2,
                    "updated_at": 100,
                }

            def interpret_state(self, state):
                self.interpreted = state
                return "steady"

        running = Mock(free_reply_status=Mock(return_value={
            "last_decision": {"room_id": "room@@abc", "triggered": False},
            "worker": {"running": True},
        }))
        handler = WechatGroupEmotionHandler()
        fake = FakeEmotionService()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupEmotionHandler, "_get_emotion_service", return_value=fake), \
                patch.object(WechatGroupEmotionHandler, "_get_running_channel", return_value=running), \
                patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(room_id="room@@abc", now="123")):
            result = json.loads(handler.GET("state"))

        self.assertEqual("success", result["status"])
        self.assertEqual("room@@abc", result["state"]["room_id"])
        self.assertEqual("steady", result["state"]["interpreted_state"])
        self.assertEqual({"room_id": "room@@abc", "triggered": False}, result["last_decision"])
        self.assertEqual(("room@@abc", 123), fake.args)

    def test_wechat_group_emotion_reset_api_uses_service(self):
        from channel.web.web_channel import WechatGroupEmotionHandler

        class FakeEmotionService:
            def reset_state(self, room_id, now=None):
                self.args = (room_id, now)
                return {
                    "room_id": room_id,
                    "valence": 0.0,
                    "energy": 0.5,
                    "sociability": 0.45,
                }

            def interpret_state(self, state):
                return "steady"

        body = {"room_id": "room@@abc", "now": 234}
        handler = WechatGroupEmotionHandler()
        fake = FakeEmotionService()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupEmotionHandler, "_get_emotion_service", return_value=fake), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")):
            result = json.loads(handler.POST("reset"))

        self.assertEqual("success", result["status"])
        self.assertEqual("steady", result["state"]["interpreted_state"])
        self.assertEqual(("room@@abc", 234), fake.args)

    def test_wechat_group_emotion_config_api_updates_settings(self):
        from channel.web.web_channel import WechatGroupEmotionHandler
        from config import conf

        handler = WechatGroupEmotionHandler()
        body = {
            "wechat_group_emotion_enabled": False,
            "wechat_group_emotion_decay_minutes": "0",
            "wechat_group_emotion_default_valence": "2",
            "wechat_group_emotion_default_energy": "-1",
            "wechat_group_emotion_default_sociability": "9",
            "wechat_group_free_reply_time_rules_enabled": True,
            "wechat_group_free_reply_time_rules": [
                {"start": "22:00", "end": "23:30", "days": ["sat", "sun"]},
            ],
            "wechat_group_free_reply_typing_delay_enabled": False,
            "wechat_group_free_reply_typing_chars_per_second": "0",
        }
        with tempfile.TemporaryDirectory() as tmpdir, \
                patch("channel.web.web_channel._require_auth"), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")), \
                patch("channel.web.web_channel.get_data_root", return_value=tmpdir):
            result = json.loads(handler.POST("config"))

        self.assertEqual("success", result["status"])
        self.assertFalse(conf()["wechat_group_emotion_enabled"])
        self.assertEqual(1, conf()["wechat_group_emotion_decay_minutes"])
        self.assertEqual(1.0, conf()["wechat_group_emotion_default_valence"])
        self.assertEqual(0.0, conf()["wechat_group_emotion_default_energy"])
        self.assertEqual(1.0, conf()["wechat_group_emotion_default_sociability"])
        self.assertTrue(conf()["wechat_group_free_reply_time_rules_enabled"])
        self.assertEqual([{"start": "22:00", "end": "23:30", "days": ["sat", "sun"]}], conf()["wechat_group_free_reply_time_rules"])
        self.assertFalse(conf()["wechat_group_free_reply_typing_delay_enabled"])
        self.assertEqual(1, conf()["wechat_group_free_reply_typing_chars_per_second"])

    def test_wechat_group_style_candidates_api_uses_service(self):
        from channel.web.web_channel import WechatGroupStylesHandler

        class FakeStyleService:
            def list_candidates(self, room_id, limit=20):
                self.args = (room_id, limit)
                return [{"style_id": "style-1", "status": "candidate"}]

        fake = FakeStyleService()
        handler = WechatGroupStylesHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupStylesHandler, "_get_style_service", return_value=fake), \
                patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(room_id="room@@abc", q="", limit="5")):
            result = json.loads(handler.GET("candidates"))

        self.assertEqual("success", result["status"])
        self.assertEqual("style-1", result["cards"][0]["style_id"])
        self.assertEqual(("room@@abc", 5), fake.args)

    def test_wechat_group_style_review_api_uses_service(self):
        from channel.web.web_channel import WechatGroupStylesHandler

        class FakeStyleService:
            def review_style(self, room_id, style_id, action="approve"):
                self.args = (room_id, style_id, action)
                return {"style_id": style_id, "status": "active"}

        fake = FakeStyleService()
        body = {"room_id": "room@@abc", "style_id": "style-1", "action": "approve"}
        handler = WechatGroupStylesHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupStylesHandler, "_get_style_service", return_value=fake), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")):
            result = json.loads(handler.POST("review"))

        self.assertEqual("success", result["status"])
        self.assertEqual("active", result["card"]["status"])
        self.assertEqual(("room@@abc", "style-1", "approve"), fake.args)

    def test_wechat_group_topics_active_api_uses_service(self):
        from channel.web.web_channel import WechatGroupTopicsHandler

        class FakeTopicService:
            def list_active_topics(self, room_id, limit=None):
                self.args = (room_id, limit)
                return [{"thread_id": "topic-1", "title": "release"}]

        fake = FakeTopicService()
        handler = WechatGroupTopicsHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupTopicsHandler, "_get_topic_service", return_value=fake), \
                patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(room_id="room@@abc", q="", limit="3")):
            result = json.loads(handler.GET("active"))

        self.assertEqual("success", result["status"])
        self.assertEqual("topic-1", result["topics"][0]["thread_id"])
        self.assertEqual(("room@@abc", 3), fake.args)

    def test_wechat_group_topics_archive_api_uses_service(self):
        from channel.web.web_channel import WechatGroupTopicsHandler

        class FakeTopicService:
            def search_topics(self, room_id, query="", limit=20):
                self.args = (room_id, query, limit)
                return [{"thread_id": "topic-2", "title": "release archive"}]

        fake = FakeTopicService()
        handler = WechatGroupTopicsHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupTopicsHandler, "_get_topic_service", return_value=fake), \
                patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(room_id="room@@abc", q="release", limit="4")):
            result = json.loads(handler.GET("archive"))

        self.assertEqual("success", result["status"])
        self.assertEqual("topic-2", result["topics"][0]["thread_id"])
        self.assertEqual(("room@@abc", "release", 4), fake.args)

    def test_wechat_group_stickers_list_api_uses_service(self):
        from channel.web.web_channel import WechatGroupStickersHandler

        class FakeStickerService:
            def list_stickers(self, room_id, query="", limit=20, status=""):
                self.args = (room_id, query, limit, status)
                return [{"sticker_id": "sticker-1", "status": "active"}]

        fake = FakeStickerService()
        handler = WechatGroupStickersHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupStickersHandler, "_get_sticker_service", return_value=fake), \
                patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(room_id="room@@abc", q="cat", limit="6", status="active")):
            result = json.loads(handler.GET("list"))

        self.assertEqual("success", result["status"])
        self.assertEqual("sticker-1", result["stickers"][0]["sticker_id"])
        self.assertEqual(("room@@abc", "cat", 6, "active"), fake.args)

    def test_wechat_group_stickers_disable_api_uses_service(self):
        from channel.web.web_channel import WechatGroupStickersHandler

        class FakeStickerService:
            def disable_sticker(self, room_id, sticker_id):
                self.args = (room_id, sticker_id)
                return {"sticker_id": sticker_id, "status": "disabled"}

        fake = FakeStickerService()
        body = {"room_id": "room@@abc", "sticker_id": "sticker-1"}
        handler = WechatGroupStickersHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupStickersHandler, "_get_sticker_service", return_value=fake), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")):
            result = json.loads(handler.POST("disable"))

        self.assertEqual("success", result["status"])
        self.assertEqual("disabled", result["sticker"]["status"])
        self.assertEqual(("room@@abc", "sticker-1"), fake.args)

    def test_wechat_group_memory_preview_api_uses_service(self):
        from channel.web.web_channel import WechatGroupMemoriesHandler

        class FakeContextService:
            def preview_context(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "content": "<wechat-group-knowledge>\n[group_memory]\n测试记忆\n</wechat-group-knowledge>",
                    "filtered_reasons": [],
                }

        fake = FakeContextService()
        body = {
            "room_id": "room@@abc",
            "sender_id": "wxid_alice",
            "query": "测试",
            "mentioned_sender_ids": ["wxid_bob"],
        }
        handler = WechatGroupMemoriesHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupMemoriesHandler, "_get_context_service", return_value=fake), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")):
            result = json.loads(handler.POST("preview"))

        self.assertEqual("success", result["status"])
        self.assertIn("<wechat-group-knowledge>", result["preview"]["content"])
        self.assertEqual("room@@abc", fake.kwargs["room_id"])

    def test_console_contains_wechat_group_emotion_panel(self):
        with open("channel/web/static/js/console.js", "r", encoding="utf-8") as f:
            console_js = f.read()

        self.assertIn("groups_nav_emotion", console_js)
        self.assertIn("buildGroupsEmotionPanel", console_js)
        self.assertIn("saveGroupsEmotionConfig", console_js)
        self.assertIn("resetGroupsEmotionState", console_js)
        self.assertIn("/api/wechat-group/emotion/state", console_js)
        self.assertIn("/api/wechat-group/emotion/config", console_js)
        self.assertIn("/api/wechat-group/emotion/reset", console_js)

    def test_console_contains_wechat_group_style_panel(self):
        with open("channel/web/static/js/console.js", "r", encoding="utf-8") as f:
            console_js = f.read()

        self.assertIn("groups_nav_style", console_js)
        self.assertIn("buildGroupsStylePanel", console_js)
        self.assertIn("refreshGroupsStyleData", console_js)
        self.assertIn("reviewGroupsStyleCard", console_js)
        self.assertIn("/api/wechat-group/styles/candidates", console_js)
        self.assertIn("/api/wechat-group/styles/active", console_js)
        self.assertIn("/api/wechat-group/styles/review", console_js)

    def test_console_contains_wechat_group_topic_panel(self):
        with open("channel/web/static/js/console.js", "r", encoding="utf-8") as f:
            console_js = f.read()

        self.assertIn("groups_nav_topic", console_js)
        self.assertIn("buildGroupsTopicPanel", console_js)
        self.assertIn("refreshGroupsTopicData", console_js)
        self.assertIn("/api/wechat-group/topics/active", console_js)
        self.assertIn("/api/wechat-group/topics/archive", console_js)

    def test_console_contains_wechat_group_sticker_panel(self):
        with open("channel/web/static/js/console.js", "r", encoding="utf-8") as f:
            console_js = f.read()

        self.assertIn("groups_nav_sticker", console_js)
        self.assertIn("buildGroupsStickerPanel", console_js)
        self.assertIn("refreshGroupsStickerData", console_js)
        self.assertIn("disableGroupsSticker", console_js)
        self.assertIn("/api/wechat-group/stickers/list", console_js)
        self.assertIn("/api/wechat-group/stickers/disable", console_js)

    def test_wechat_group_memory_service_uses_configured_embedding_provider(self):
        from agent.memory.config import MemoryConfig, get_default_memory_config, set_global_memory_config
        from channel.web.web_channel import WechatGroupMemoriesHandler

        original_config = get_default_memory_config()
        provider = object()
        WechatGroupMemoriesHandler._context_service = None

        with tempfile.TemporaryDirectory() as tmpdir:
            set_global_memory_config(MemoryConfig(workspace_root=tmpdir))
            with patch(
                "agent.memory.create_default_embedding_provider",
                return_value=provider,
                create=True,
            ):
                service = WechatGroupMemoriesHandler._get_context_service()
            try:
                self.assertIs(service.memory_manager.embedding_provider, provider)
            finally:
                service.memory_manager.close()
                WechatGroupMemoriesHandler._context_service = None
                set_global_memory_config(original_config)

    def test_wechat_group_memory_group_post_requires_room_id(self):
        from channel.web.web_channel import WechatGroupMemoriesHandler

        handler = WechatGroupMemoriesHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps({"content": "x"}).encode("utf-8")):
            result = json.loads(handler.POST("group"))

        self.assertEqual("error", result["status"])
        self.assertIn("room_id", result["message"])

    def test_wechat_group_memory_profile_api_passes_aliases(self):
        from channel.web.web_channel import WechatGroupMemoriesHandler

        class FakeProfileService:
            def upsert_manual_profile(self, **kwargs):
                self.kwargs = kwargs
                return {"sender_id": kwargs["sender_id"], "aliases": kwargs["aliases"]}

        fake = FakeProfileService()
        body = {
            "sender_id": "wxid_dali",
            "primary_nickname": "Dali Wang",
            "aliases": "大力, 力佬",
            "speak_style": "资源协调人",
        }
        handler = WechatGroupMemoriesHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupMemoriesHandler, "_get_profile_service", return_value=fake), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")):
            result = json.loads(handler.POST("profiles"))

        self.assertEqual("success", result["status"])
        self.assertEqual(["大力", "力佬"], fake.kwargs["aliases"])
        self.assertEqual("wxid_dali", fake.kwargs["sender_id"])

    def test_wechat_group_memory_summary_api_uses_service(self):
        from channel.web.web_channel import WechatGroupMemoriesHandler

        class FakeKnowledgeService:
            def list_group_memories(self, room_id, query="", limit=20):
                self.room_id = room_id
                return [{"memory_id": "m1"}, {"memory_id": "m2"}]

        class FakeProfileService:
            def list_profiles(self, query="", limit=20):
                return [{"sender_id": "wxid_a"}, {"sender_id": "wxid_b"}, {"sender_id": "wxid_c"}]

        fake_knowledge = FakeKnowledgeService()
        fake_profiles = FakeProfileService()
        handler = WechatGroupMemoriesHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupMemoriesHandler, "_get_knowledge_service", return_value=fake_knowledge), \
                patch.object(WechatGroupMemoriesHandler, "_get_profile_service", return_value=fake_profiles), \
                patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(
                    room_id="room@@abc", sender_id="", status="active", limit="20", offset="0", q="",
                )):
            result = json.loads(handler.GET("summary"))

        self.assertEqual("success", result["status"])
        self.assertEqual("room@@abc", fake_knowledge.room_id)
        self.assertEqual(2, result["summary"]["group_memory_count"])
        self.assertEqual(3, result["summary"]["profile_count"])

    def test_profiles_api_lists_global_profiles(self):
        from channel.web.web_channel import WechatGroupMemoriesHandler

        class FakeProfileService:
            def list_profiles(self, query="", limit=20, room_id=""):
                self.args = (query, limit, room_id)
                return [{"sender_id": "wxid_alice", "primary_nickname": "Alice"}]

        fake = FakeProfileService()
        handler = WechatGroupMemoriesHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupMemoriesHandler, "_get_profile_service", return_value=fake), \
                patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(
                    room_id="room@@abc", sender_id="", status="active", limit="5", offset="0", q="alice",
                )):
            result = json.loads(handler.GET("profiles"))

        self.assertEqual("success", result["status"])
        self.assertEqual("wxid_alice", result["profiles"][0]["sender_id"])
        self.assertNotIn("room_id", result["profiles"][0])
        self.assertEqual(("alice", 5, "room@@abc"), fake.args)

    def test_wechat_group_memory_disable_api_uses_service(self):
        from channel.web.web_channel import WechatGroupMemoriesHandler

        class FakeKnowledgeService:
            def disable_group_memory(self, room_id, memory_id):
                self.room_id = room_id
                self.memory_id = memory_id
                return True

        fake = FakeKnowledgeService()
        body = {
            "memory_type": "group",
            "room_id": "room@@abc",
            "memory_id": "chunk-1",
        }
        handler = WechatGroupMemoriesHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupMemoriesHandler, "_get_knowledge_service", return_value=fake), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")):
            result = json.loads(handler.POST("disable"))

        self.assertEqual("success", result["status"])
        self.assertTrue(result["disabled"])
        self.assertEqual("room@@abc", fake.room_id)
        self.assertEqual("chunk-1", fake.memory_id)

    def test_wechat_group_learn_runs_api_uses_room_filter(self):
        from channel.web.web_channel import WechatGroupMemoriesHandler

        class FakeKnowledgeStore:
            def list_learning_runs(self, room_id, limit=20):
                self.args = (room_id, limit)
                return [{"run_id": "run-1", "room_id": room_id, "status": "success"}]

        fake = FakeKnowledgeStore()
        handler = WechatGroupMemoriesHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupMemoriesHandler, "_get_knowledge_store", return_value=fake), \
                patch("channel.web.web_channel.web.input", return_value=types.SimpleNamespace(
                    room_id="room@@abc", sender_id="", status="active", limit="5", offset="0", q="",
                )):
            result = json.loads(handler.GET("learn/runs"))

        self.assertEqual("success", result["status"])
        self.assertEqual("run-1", result["runs"][0]["run_id"])
        self.assertEqual(("room@@abc", 5), fake.args)

    def test_learn_run_api_replaces_candidate_approve_flow(self):
        from channel.web.web_channel import WechatGroupMemoriesHandler

        class FakeLearner:
            def run_once(self, room_id, mode="all"):
                self.args = (room_id, mode)
                return {"status": "success", "run_id": "run-1"}

        body = {"room_id": "room@@abc", "mode": "all"}
        handler = WechatGroupMemoriesHandler()
        with patch("channel.web.web_channel._require_auth"), \
                patch.object(WechatGroupMemoriesHandler, "_get_learner", return_value=FakeLearner()), \
                patch("channel.web.web_channel.web.data", return_value=json.dumps(body).encode("utf-8")):
            result = json.loads(handler.POST("learn/run"))

        self.assertEqual("success", result["status"])
        self.assertEqual("run-1", result["run"]["run_id"])


if __name__ == "__main__":
    unittest.main()
