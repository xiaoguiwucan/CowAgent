import tempfile
import unittest

from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from channel.wechat_group.wechat_group_memory import WechatGroupMemoryService
from channel.wechat_group.wechat_group_memory_tools import (
    WechatGroupMemorySearchTool,
    WechatGroupProfileGetTool,
    create_wechat_group_memory_tools,
)


class FakeProfileEmbeddingProvider:
    model = "fake-profile-vectors"

    def embed_query(self, text):
        return self._embed(text)

    def embed_batch(self, texts):
        return [self._embed(text) for text in texts]

    @staticmethod
    def _embed(text):
        text = (text or "").lower()
        if any(term in text for term in ("frontend", "react", "dashboard", "ui")):
            return [1.0, 0.0]
        return [0.0, 1.0]


class WechatGroupMemoryToolsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = MemoryManager(MemoryConfig(workspace_root=self._tmp.name))
        self.service = WechatGroupMemoryService(
            memory_manager=self.manager,
            allowed_room_ids=["room@@a", "room@@b"],
        )

    async def asyncTearDown(self):
        self.manager.close()
        self._tmp.cleanup()

    async def test_memory_search_tool_is_bound_to_current_room(self):
        await self.service.add_group_memory("room@@a", "A room release window is Friday night")
        await self.service.add_group_memory("room@@b", "B room release window is Saturday morning")

        tool = WechatGroupMemorySearchTool(self.service, room_id="room@@a")
        result = tool.execute({"query": "release window", "max_results": 5, "min_score": 0})

        self.assertEqual("success", result.status)
        self.assertIn("A room release window is Friday night", result.result)
        self.assertNotIn("B room release window is Saturday morning", result.result)

    async def test_profile_get_tool_reads_only_current_room_profile(self):
        await self.service.upsert_member_profile(
            room_id="room@@a",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            role="release owner",
            preferences="wants risk first",
            evidence="manual admin entry",
        )
        await self.service.upsert_member_profile(
            room_id="room@@b",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            role="budget owner",
            preferences="wants cost first",
            evidence="manual admin entry",
        )

        tool = WechatGroupProfileGetTool(
            self.service,
            room_id="room@@a",
            sender_id="wxid_alice",
        )
        result = tool.execute({})

        self.assertEqual("success", result.status)
        self.assertIn("release owner", result.result)
        self.assertIn("wants risk first", result.result)
        self.assertNotIn("budget owner", result.result)
        self.assertNotIn("wants cost first", result.result)

    async def test_profile_get_tool_can_vector_search_current_room_profiles(self):
        self.manager.embedding_provider = FakeProfileEmbeddingProvider()
        await self.service.upsert_member_profile(
            room_id="room@@a",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            role="UI owner",
            expertise="React dashboards",
            evidence="manual admin entry",
        )
        await self.service.upsert_member_profile(
            room_id="room@@b",
            sender_id="wxid_cross_room",
            sender_nickname="Cross Room Bob",
            role="UI owner",
            expertise="React dashboards",
            evidence="manual admin entry",
        )

        tool = WechatGroupProfileGetTool(
            self.service,
            room_id="room@@a",
            sender_id="wxid_alice",
        )
        result = tool.execute({"query": "frontend specialist", "max_results": 3})

        self.assertEqual("success", result.status)
        self.assertIn("sender_id: wxid_bob", result.result)
        self.assertIn("React dashboards", result.result)
        self.assertNotIn("wxid_cross_room", result.result)

    async def test_wechat_group_tool_schemas_do_not_accept_room_id(self):
        tools = create_wechat_group_memory_tools(
            service=self.service,
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
