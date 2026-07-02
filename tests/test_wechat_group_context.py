import os
import tempfile
import unittest
import warnings
from unittest.mock import Mock

from bridge.context import ContextType
from channel.wechat_group.protocol import parse_sidecar_event
from channel.wechat_group.wechat_group_archive import WechatGroupArchive
from channel.wechat_group.wechat_group_channel import WechatGroupChannel
from channel.wechat_group.wechat_group_context import build_wechat_group_recent_context_block
from channel.wechat_group.wechat_group_message import WechatGroupMessage
from config import conf


class WechatGroupRecentContextTest(unittest.TestCase):
    def setUp(self):
        self._original_config = {
            "wechat_group_room_ids": conf().get("wechat_group_room_ids"),
            "wechat_group_recent_context_enabled": conf().get("wechat_group_recent_context_enabled"),
            "wechat_group_recent_context_limit": conf().get("wechat_group_recent_context_limit"),
            "wechat_group_recent_context_minutes": conf().get("wechat_group_recent_context_minutes"),
            "wechat_group_record_messages": conf().get("wechat_group_record_messages"),
            "wechat_group_persona_prompt": conf().get("wechat_group_persona_prompt"),
            "wechat_group_persona_preset_id": conf().get("wechat_group_persona_preset_id"),
        }
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "wechat_group_archive.db")

    def tearDown(self):
        for key, value in self._original_config.items():
            if value is None:
                conf().pop(key, None)
            else:
                conf()[key] = value
        self._tmp.cleanup()

    def test_archive_queries_recent_messages_by_room_only(self):
        archive = WechatGroupArchive(self.db_path)
        archive.record_message(
            message_id="room-a-1",
            room_id="room@@a",
            room_name="A群",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            message_type="text",
            text="A 群消息",
            is_at=True,
            created_at=1000,
        )
        archive.record_message(
            message_id="room-b-1",
            room_id="room@@b",
            room_name="B群",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            message_type="text",
            text="B 群消息",
            is_at=True,
            created_at=1001,
        )

        rows = archive.get_recent_messages("room@@a", limit=10, minutes=60, now=2000)

        self.assertEqual(1, len(rows))
        self.assertEqual("room@@a", rows[0]["room_id"])
        self.assertEqual("A 群消息", rows[0]["text"])

    def test_wechat_group_channel_import_does_not_require_audio_converter(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            __import__("channel.wechat_group.wechat_group_channel")

        self.assertFalse(
            [item for item in caught if "ffmpeg or avconv" in str(item.message)]
        )

    def test_recent_context_block_is_compact_and_omits_other_rooms(self):
        archive = WechatGroupArchive(self.db_path)
        archive.record_message(
            message_id="msg-old",
            room_id="room@@a",
            room_name="A群",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            message_type="text",
            text="第一条消息需要被摘要",
            created_at=1000,
        )
        archive.record_message(
            message_id="msg-other",
            room_id="room@@b",
            room_name="B群",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            message_type="text",
            text="其他群消息不应该出现",
            created_at=1001,
        )

        block = build_wechat_group_recent_context_block(archive, "room@@a", limit=5, minutes=60, now=2000)

        self.assertIn("<recent-wechat-group-transcript>", block)
        self.assertIn("[text] Alice", block)
        self.assertIn("第一条消息需要被摘要", block)
        self.assertNotIn("其他群消息", block)

    def test_channel_records_message_and_injects_recent_context_before_request(self):
        conf()["wechat_group_room_ids"] = ["room@@abc"]
        conf()["wechat_group_record_messages"] = True
        conf()["wechat_group_recent_context_enabled"] = True
        conf()["wechat_group_recent_context_limit"] = 5
        conf()["wechat_group_recent_context_minutes"] = 60
        conf()["wechat_group_persona_prompt"] = ""
        conf()["wechat_group_persona_preset_id"] = ""
        archive = WechatGroupArchive(self.db_path)
        archive.record_message(
            message_id="msg-prev",
            room_id="room@@abc",
            room_name="测试群",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            message_type="text",
            text="刚才讨论了发布窗口",
            created_at=1000,
        )
        channel = WechatGroupChannel(client=Mock(), archive=archive)
        msg = WechatGroupMessage(parse_sidecar_event({
            "type": "message",
            "message_id": "msg-current",
            "room_id": "room@@abc",
            "room_name": "测试群",
            "sender_id": "wxid_alice",
            "sender_name": "Alice",
            "self_id": "wxid_bot",
            "self_name": "CowBot",
            "text": "@CowBot 总结一下",
            "is_at": True,
            "at_list": ["wxid_bot"],
            "timestamp": 1010,
        }))

        context = channel._compose_context(ContextType.TEXT, msg.content, isgroup=True, msg=msg)

        self.assertIsNotNone(context)
        self.assertIn("<recent-wechat-group-transcript>", context.content)
        self.assertIn("刚才讨论了发布窗口", context.content)
        self.assertIn("Alice", context.content)
        self.assertTrue(context.content.rstrip().endswith("总结一下"))
        rows = archive.get_recent_messages("room@@abc", limit=10, minutes=60, now=1010)
        self.assertEqual(["msg-prev", "msg-current"], [row["message_id"] for row in rows])


if __name__ == "__main__":
    unittest.main()
