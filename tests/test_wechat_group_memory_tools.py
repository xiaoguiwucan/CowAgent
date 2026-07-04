import os
import tempfile
import unittest

from channel.wechat_group.wechat_group_knowledge_service import WechatGroupKnowledgeService
from channel.wechat_group.wechat_group_knowledge_store import WechatGroupKnowledgeStore
from channel.wechat_group.wechat_group_memory_tools import (
    WechatGroupMemorySearchTool,
    WechatGroupProfileGetTool,
    create_wechat_group_memory_tools,
)
from channel.wechat_group.wechat_group_profile_service import WechatGroupProfileService
from channel.wechat_group.wechat_group_profile_store import WechatGroupProfileStore


class WechatGroupMemoryToolsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.knowledge_service = WechatGroupKnowledgeService(
            WechatGroupKnowledgeStore(os.path.join(self._tmp.name, "knowledge.db"))
        )
        self.profile_service = WechatGroupProfileService(
            WechatGroupProfileStore(os.path.join(self._tmp.name, "profiles.db"))
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_memory_search_tool_is_bound_to_current_room(self):
        self.knowledge_service.add_group_memory("room@@a", "A room release window is Friday night")
        self.knowledge_service.add_group_memory("room@@b", "B room release window is Saturday morning")

        tool = WechatGroupMemorySearchTool(self.knowledge_service, room_id="room@@a")
        result = tool.execute({"query": "release window", "max_results": 5})

        self.assertEqual("success", result.status)
        self.assertIn("A room release window is Friday night", result.result)
        self.assertNotIn("B room release window is Saturday morning", result.result)

    def test_profile_get_tool_reads_global_profile_for_current_sender(self):
        self.profile_service.upsert_manual_profile(
            sender_id="wxid_alice",
            primary_nickname="Alice",
            speak_style="wants risk first",
            interests=["release"],
            common_words=["ship it"],
            aliases=["阿狸"],
            room_id="room@@a",
            room_name="A群",
        )

        tool = WechatGroupProfileGetTool(
            self.profile_service,
            sender_id="wxid_alice",
        )
        result = tool.execute({})

        self.assertEqual("success", result.status)
        self.assertIn("Current member profile", result.result)
        self.assertIn("wants risk first", result.result)
        self.assertIn("release", result.result)

    def test_profile_get_tool_can_search_global_profiles(self):
        self.profile_service.upsert_manual_profile(
            sender_id="wxid_bob",
            primary_nickname="Bob",
            speak_style="gives concise answers",
            interests=["frontend", "React dashboards"],
            common_words=["UI"],
            aliases=["前端 Bob"],
        )
        self.profile_service.upsert_manual_profile(
            sender_id="wxid_cross_room",
            primary_nickname="Cross Room Bob",
            speak_style="handles database topics",
            interests=["database"],
            common_words=["SQL"],
            aliases=["后端 Bob"],
        )

        tool = WechatGroupProfileGetTool(
            self.profile_service,
            sender_id="wxid_alice",
        )
        result = tool.execute({"query": "前端 Bob", "max_results": 3})

        self.assertEqual("success", result.status)
        self.assertIn("sender_id: wxid_bob", result.result)
        self.assertIn("frontend, React dashboards", result.result)
        self.assertNotIn("wxid_cross_room", result.result)

    def test_wechat_group_tool_schemas_do_not_accept_room_id(self):
        tools = create_wechat_group_memory_tools(
            knowledge_service=self.knowledge_service,
            profile_service=self.profile_service,
            room_id="room@@a",
            sender_id="wxid_alice",
            bot_sender_id="wxid_bot",
        )

        self.assertEqual(
            ["wechat_group_memory_search", "wechat_group_profile_get"],
            [tool.name for tool in tools],
        )
        for tool in tools:
            self.assertNotIn("room_id", tool.params.get("properties", {}))


if __name__ == "__main__":
    unittest.main()
