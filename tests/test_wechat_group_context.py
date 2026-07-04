import os
import tempfile
import unittest
import warnings
from unittest.mock import Mock

from bridge.context import ContextType
from channel.wechat_group.protocol import parse_sidecar_event
from channel.wechat_group.wechat_group_archive import WechatGroupArchive
from channel.wechat_group.wechat_group_channel import WechatGroupChannel
from channel.wechat_group.wechat_group_context_service import WechatGroupContextService
from channel.wechat_group.wechat_group_context import build_wechat_group_recent_context_block
from channel.wechat_group.wechat_group_knowledge_service import WechatGroupKnowledgeService
from channel.wechat_group.wechat_group_knowledge_store import WechatGroupKnowledgeStore
from channel.wechat_group.wechat_group_message import WechatGroupMessage
from channel.wechat_group.wechat_group_profile_service import WechatGroupProfileService
from channel.wechat_group.wechat_group_profile_store import WechatGroupProfileStore
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
            "wechat_group_memory_enabled": conf().get("wechat_group_memory_enabled"),
            "wechat_group_member_memory_enabled": conf().get("wechat_group_member_memory_enabled"),
            "wechat_group_knowledge_enabled": conf().get("wechat_group_knowledge_enabled"),
            "wechat_group_profile_enabled": conf().get("wechat_group_profile_enabled"),
            "wechat_group_profile_context_limit": conf().get("wechat_group_profile_context_limit"),
            "wechat_group_group_memory_context_limit": conf().get("wechat_group_group_memory_context_limit"),
        }
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "wechat_group_archive.db")
        self.profile_db_path = os.path.join(self._tmp.name, "profiles.db")
        self.knowledge_db_path = os.path.join(self._tmp.name, "knowledge.db")

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

    def test_archive_get_message_by_id_scopes_to_room(self):
        archive = WechatGroupArchive(self.db_path)
        archive.record_message(
            message_id="quoted-image",
            room_id="room@@a",
            room_name="A群",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            message_type="image",
            text="[图片]",
            media_path="D:/tmp/quoted.jpg",
            created_at=1000,
        )
        archive.record_message(
            message_id="quoted-image",
            room_id="room@@b",
            room_name="B群",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            message_type="image",
            text="[图片]",
            media_path="D:/tmp/other.jpg",
            created_at=1001,
        )

        row = archive.get_message_by_id("room@@a", "quoted-image")

        self.assertIsNotNone(row)
        self.assertEqual("room@@a", row["room_id"])
        self.assertEqual("image", row["message_type"])
        self.assertEqual("D:/tmp/quoted.jpg", row["media_path"])
        self.assertIsNone(archive.get_message_by_id("room@@missing", "quoted-image"))

    def test_archive_lists_members_by_room_and_query(self):
        archive = WechatGroupArchive(self.db_path)
        archive.record_message(
            message_id="room-a-1",
            room_id="room@@a",
            room_name="room a",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            message_type="text",
            text="hello",
            created_at=1000,
        )
        archive.record_message(
            message_id="room-a-2",
            room_id="room@@a",
            room_name="room a",
            sender_id="wxid_alice",
            sender_nickname="Alice New",
            message_type="text",
            text="hello again",
            created_at=1010,
        )
        archive.record_message(
            message_id="room-a-3",
            room_id="room@@a",
            room_name="room a",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            message_type="text",
            text="hello",
            created_at=1005,
        )
        archive.record_message(
            message_id="room-b-1",
            room_id="room@@b",
            room_name="room b",
            sender_id="wxid_alice_other",
            sender_nickname="Alice Other",
            message_type="text",
            text="other room",
            created_at=1020,
        )

        rows = archive.list_members("room@@a", query="alice", limit=10)

        self.assertEqual(1, len(rows))
        self.assertEqual("wxid_alice", rows[0]["sender_id"])
        self.assertEqual("Alice New", rows[0]["sender_nickname"])
        self.assertEqual(2, rows[0]["message_count"])
        self.assertEqual(1010, rows[0]["last_seen_at"])

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

    def test_context_service_builds_wechat_group_knowledge_block(self):
        profile_service = WechatGroupProfileService(WechatGroupProfileStore(self.profile_db_path))
        knowledge_service = WechatGroupKnowledgeService(WechatGroupKnowledgeStore(self.knowledge_db_path))
        knowledge_service.add_group_memory("room@@abc", "发布窗口是周五晚上", ["m1"], "讨论结果", "manual")
        profile_service.upsert_manual_profile(
            sender_id="wxid_alice",
            primary_nickname="Alice",
            speak_style="直接给结论",
            interests=["发布"],
            common_words=["安排"],
            aliases=[],
        )
        profile_service.upsert_manual_profile(
            sender_id="wxid_bob",
            primary_nickname="Bob",
            speak_style="喜欢列清单",
            interests=["测试"],
            common_words=["收到"],
            aliases=[],
        )
        service = WechatGroupContextService(
            profile_service=profile_service,
            knowledge_service=knowledge_service,
        )

        preview = service.preview_context(
            room_id="room@@abc",
            sender_id="wxid_alice",
            query="总结一下",
            mentioned_sender_ids=["wxid_bob"],
        )

        self.assertIn("<wechat-group-knowledge>", preview["content"])
        self.assertIn("[group_memory]", preview["content"])
        self.assertIn('[speaker_profile sender_id="wxid_alice"]', preview["content"])
        self.assertIn('[mentioned_profile sender_id="wxid_bob"]', preview["content"])

    def test_channel_injects_memory_after_recent_context_before_request(self):
        class FakeContextService:
            def preview_context(self, **kwargs):
                return {
                    "content": (
                        "<wechat-group-knowledge>\n"
                        "[group_memory]\n发布窗口是周五晚上\n"
                        '[speaker_profile sender_id="wxid_alice"]\n直接给结论\n'
                        "</wechat-group-knowledge>"
                    ),
                    "filtered_reasons": [],
                }

        conf()["wechat_group_room_ids"] = ["room@@abc"]
        conf()["wechat_group_record_messages"] = True
        conf()["wechat_group_recent_context_enabled"] = True
        conf()["wechat_group_knowledge_enabled"] = True
        conf()["wechat_group_profile_enabled"] = True
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
        channel = WechatGroupChannel(client=Mock(), archive=archive, memory_service=FakeContextService())
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
            "at_list": ["wxid_bot", "wxid_bob"],
            "timestamp": 1010,
        }))

        context = channel._compose_context(ContextType.TEXT, msg.content, isgroup=True, msg=msg)

        recent_index = context.content.index("<recent-wechat-group-transcript>")
        memory_index = context.content.index("<wechat-group-knowledge>")
        request_index = context.content.rindex("总结一下")
        self.assertLess(recent_index, memory_index)
        self.assertLess(memory_index, request_index)
        self.assertIn("发布窗口是周五晚上", context.content)

    def test_channel_omits_memory_block_when_memory_config_disabled(self):
        class FakeContextService:
            def preview_context(self, **kwargs):
                raise AssertionError("context service should not be called")

        conf()["wechat_group_room_ids"] = ["room@@abc"]
        conf()["wechat_group_knowledge_enabled"] = False
        conf()["wechat_group_profile_enabled"] = False
        channel = WechatGroupChannel(client=Mock(), archive=WechatGroupArchive(self.db_path), memory_service=FakeContextService())
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

        self.assertNotIn("<wechat-group-knowledge>", context.content)

    def test_channel_sets_wechat_group_memory_tool_metadata(self):
        conf()["wechat_group_room_ids"] = ["room@@abc"]
        conf()["wechat_group_memory_enabled"] = False
        conf()["wechat_group_member_memory_enabled"] = False
        channel = WechatGroupChannel(client=Mock(), archive=WechatGroupArchive(self.db_path))
        msg = WechatGroupMessage(parse_sidecar_event({
            "type": "message",
            "message_id": "msg-current",
            "room_id": "room@@abc",
            "room_name": "Test Room",
            "sender_id": "wxid_alice",
            "sender_name": "Alice",
            "self_id": "wxid_bot",
            "self_name": "CowBot",
            "text": "@CowBot summarize",
            "is_at": True,
            "at_list": ["wxid_bot"],
            "timestamp": 1010,
        }))

        context = channel._compose_context(ContextType.TEXT, msg.content, isgroup=True, msg=msg)

        self.assertEqual("room@@abc", context.get("wechat_group_room_id"))
        self.assertEqual("wxid_alice", context.get("wechat_group_sender_id"))
        self.assertEqual("wxid_bot", context.get("wechat_group_bot_sender_id"))


if __name__ == "__main__":
    unittest.main()
