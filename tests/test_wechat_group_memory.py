import tempfile
import unittest

from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from channel.wechat_group.wechat_group_memory import WechatGroupMemoryService


class WechatGroupMemoryServiceTest(unittest.IsolatedAsyncioTestCase):
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

    async def test_preview_injects_current_group_memory_only(self):
        await self.service.add_group_memory("room@@a", "A 群发布窗口是周五晚上")
        await self.service.add_group_memory("room@@b", "B 群发布窗口是周六早上")

        preview = await self.service.preview_prompt_memories(
            room_id="room@@a",
            sender_id="wxid_alice",
            query="发布窗口是什么时候",
        )

        self.assertIn("<wechat-group-memory>", preview["content"])
        self.assertIn("A 群发布窗口是周五晚上", preview["content"])
        self.assertNotIn("B 群发布窗口是周六早上", preview["content"])

    async def test_preview_injects_speaker_and_mentioned_profiles(self):
        await self.service.upsert_member_profile(
            room_id="room@@a",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            role="产品负责人",
            preferences="喜欢先看风险",
            expertise="发布管理",
            interaction_style="直接",
            boundaries="不讨论私人信息",
            evidence="管理员手动维护",
        )
        await self.service.upsert_member_profile(
            room_id="room@@a",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            role="测试负责人",
            preferences="关注覆盖率",
            expertise="自动化测试",
            interaction_style="给清单",
            boundaries="",
            evidence="管理员手动维护",
        )

        preview = await self.service.preview_prompt_memories(
            room_id="room@@a",
            sender_id="wxid_alice",
            query="帮我提醒 Bob",
            mentioned_sender_ids=["wxid_bot", "wxid_alice", "wxid_bob"],
            bot_sender_id="wxid_bot",
        )

        self.assertIn('[speaker_profile sender_id="wxid_alice"]', preview["content"])
        self.assertIn("产品负责人", preview["content"])
        self.assertIn('[mentioned_profile sender_id="wxid_bob"]', preview["content"])
        self.assertIn("测试负责人", preview["content"])
        self.assertNotIn('sender_id="wxid_bot"', preview["content"])

    async def test_member_profile_update_records_revision_and_replaces_active_profile(self):
        await self.service.upsert_member_profile(
            room_id="room@@a",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            role="旧角色",
            preferences="旧偏好",
            expertise="",
            interaction_style="",
            boundaries="",
            evidence="初始",
        )
        await self.service.upsert_member_profile(
            room_id="room@@a",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            role="新角色",
            preferences="新偏好",
            expertise="",
            interaction_style="",
            boundaries="",
            evidence="更新",
        )

        profiles = await self.service.list_member_profiles("room@@a")
        revisions = self.service.list_profile_revisions("room@@a", "wxid_alice")

        self.assertEqual(1, len(profiles))
        self.assertIn("新角色", profiles[0]["content"])
        self.assertEqual(2, len(revisions))

    async def test_preview_returns_empty_content_when_disabled_or_no_hits(self):
        self.service.memory_enabled = False
        self.service.member_memory_enabled = False

        preview = await self.service.preview_prompt_memories(
            room_id="room@@a",
            sender_id="wxid_alice",
            query="没有记忆",
        )

        self.assertEqual("", preview["content"])
        self.assertIn("memory disabled", preview["filtered_reasons"])

    async def test_rejects_unselected_room(self):
        with self.assertRaises(ValueError):
            await self.service.add_group_memory("room@@not-allowed", "不允许写入")

    async def test_disable_group_memory_keeps_room_scope_isolation(self):
        memory = await self.service.add_group_memory("room@@a", "A 群只在当前群停用")

        disabled = await self.service.disable_group_memory("room@@a", memory["id"])
        active_rows = await self.service.list_group_memories("room@@a")
        disabled_rows = await self.service.list_group_memories("room@@a", status="disabled")

        self.assertTrue(disabled)
        self.assertEqual([], active_rows)
        self.assertEqual(1, len(disabled_rows))
        self.assertEqual(memory["id"], disabled_rows[0]["id"])
        with self.assertRaises(ValueError):
            await self.service.disable_group_memory("room@@b", memory["id"])

    async def test_summary_and_groups_are_limited_to_selected_rooms(self):
        await self.service.add_group_memory("room@@a", "A 群记忆")
        await self.service.upsert_member_profile(
            room_id="room@@a",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            role="负责人",
            evidence="管理员维护",
        )
        await self.service.add_group_memory("room@@b", "B 群记忆")

        summary = self.service.get_summary("room@@a")
        groups = self.service.list_group_summaries([
            {"id": "room@@a", "name": "A群"},
            {"id": "room@@b", "name": "B群"},
        ])

        self.assertEqual(1, summary["group_memory_count"])
        self.assertEqual(1, summary["member_profile_count"])
        self.assertEqual(
            {
                "room@@a": (1, 1),
                "room@@b": (1, 0),
            },
            {
                item["room_id"]: (item["group_memory_count"], item["member_profile_count"])
                for item in groups
            },
        )


if __name__ == "__main__":
    unittest.main()
