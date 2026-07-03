import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from agent.protocol.models import LLMRequest
from channel.wechat_group.wechat_group_archive import WechatGroupArchive
from channel.wechat_group.wechat_group_memory import WechatGroupMemoryService
from channel.wechat_group.wechat_group_memory_distiller import (
    WechatGroupMemoryDistiller,
    _DefaultLlmClient,
)


class FakeLlmClient:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return json.dumps(self.payload, ensure_ascii=False)


class WechatGroupMemoryDistillerTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.archive = WechatGroupArchive(f"{self._tmp.name}/archive.db")
        self.manager = MemoryManager(MemoryConfig(workspace_root=self._tmp.name))
        self.memory_service = WechatGroupMemoryService(
            memory_manager=self.manager,
            allowed_room_ids=["room@@a", "room@@b"],
        )
        self.archive.record_message(
            message_id="msg-1",
            room_id="room@@a",
            room_name="A群",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            text="本群发布窗口固定在周五晚上。",
            metadata={"at_list": ["wxid_bob"]},
            created_at=1000,
        )
        self.archive.record_message(
            message_id="msg-2",
            room_id="room@@a",
            room_name="A群",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            text="Bob 负责每次发布前的回归测试。",
            created_at=1010,
        )
        self.archive.record_message(
            message_id="msg-3",
            room_id="room@@b",
            room_name="B群",
            sender_id="wxid_other",
            sender_nickname="Other",
            text="B 群内容不能被 A 群蒸馏使用。",
            created_at=1010,
        )

    async def asyncTearDown(self):
        self.manager.close()
        self._tmp.cleanup()

    def _distiller(self, payload, **config):
        defaults = {
            "wechat_group_memory_auto_extract": True,
            "wechat_group_memory_auto_apply_threshold": 0.85,
            "wechat_group_memory_candidate_threshold": 0.55,
            "wechat_group_memory_auto_apply_group_enabled": True,
            "wechat_group_memory_auto_apply_member_enabled": True,
        }
        defaults.update(config)
        return WechatGroupMemoryDistiller(
            archive=self.archive,
            memory_service=self.memory_service,
            llm_client=FakeLlmClient(payload),
            config_getter=lambda key, default=None: defaults.get(key, default),
        )

    async def test_high_confidence_group_memory_is_auto_applied(self):
        distiller = self._distiller({
            "group_memories": [{
                "content": "A 群发布窗口固定在周五晚上",
                "confidence": 0.92,
                "evidence_message_ids": ["msg-1"],
                "evidence_text": "本群发布窗口固定在周五晚上。",
            }],
            "member_profiles": [],
        })

        result = await distiller.run(room_id="room@@a", now=1100, window_minutes=10, limit=20)
        memories = await self.memory_service.list_group_memories("room@@a")
        candidates = distiller.list_candidates("room@@a")

        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["auto_applied_count"])
        self.assertEqual(1, len(memories))
        self.assertIn("周五晚上", memories[0]["content"])
        self.assertEqual("auto_applied", candidates[0]["status"])
        self.assertEqual(memories[0]["id"], candidates[0]["applied_memory_id"])

    async def test_low_confidence_group_memory_becomes_pending_candidate(self):
        distiller = self._distiller({
            "group_memories": [{
                "content": "A 群可能偏好晚上讨论发布",
                "confidence": 0.7,
                "evidence_message_ids": ["msg-1"],
                "evidence_text": "周五晚上",
            }],
            "member_profiles": [],
        })

        result = await distiller.run(room_id="room@@a", now=1100, window_minutes=10, limit=20)
        memories = await self.memory_service.list_group_memories("room@@a")
        candidates = distiller.list_candidates("room@@a", status="pending")

        self.assertEqual("success", result["status"])
        self.assertEqual(0, result["auto_applied_count"])
        self.assertEqual(1, result["candidate_count"])
        self.assertEqual([], memories)
        self.assertEqual("pending", candidates[0]["status"])

    async def test_below_candidate_threshold_is_discarded(self):
        distiller = self._distiller({
            "group_memories": [{
                "content": "不稳定闲聊",
                "confidence": 0.2,
                "evidence_message_ids": ["msg-1"],
                "evidence_text": "闲聊",
            }],
            "member_profiles": [],
        })

        result = await distiller.run(room_id="room@@a", now=1100, window_minutes=10, limit=20)

        self.assertEqual("success", result["status"])
        self.assertEqual(0, result["candidate_count"])
        self.assertEqual([], distiller.list_candidates("room@@a"))

    async def test_empty_llm_candidates_return_diagnostic_reason(self):
        distiller = self._distiller({
            "group_memories": [],
            "member_profiles": [],
        })

        result = await distiller.run(room_id="room@@a", now=1100, window_minutes=10, limit=20)

        self.assertEqual("success", result["status"])
        self.assertEqual(0, result["auto_applied_count"])
        self.assertEqual(0, result["candidate_count"])
        self.assertIn("LLM returned no memory candidates", result["discarded_reasons"])

    async def test_member_profile_aliases_are_auto_applied(self):
        distiller = self._distiller({
            "group_memories": [],
            "member_profiles": [{
                "target_sender_id": "wxid_bob",
                "target_sender_nickname": "Bob",
                "aliases": ["大力", "力佬"],
                "role": "资源协调人",
                "confidence": 0.9,
                "evidence_message_ids": ["msg-1"],
                "evidence_text": "Alice 提到 Bob 负责协调资源",
            }],
        })

        result = await distiller.run(room_id="room@@a", now=1100, window_minutes=10, limit=20)
        profiles = await self.memory_service.list_member_profiles("room@@a", sender_id="wxid_bob")
        preview = await self.memory_service.preview_prompt_memories(
            room_id="room@@a",
            sender_id="wxid_alice",
            query="大力是谁",
            mentioned_sender_ids=["wxid_bot"],
            bot_sender_id="wxid_bot",
        )

        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["auto_applied_count"])
        self.assertEqual(["大力", "力佬"], profiles[0]["metadata"]["profile_fields"]["aliases"])
        self.assertIn('[mentioned_profile sender_id="wxid_bob" matched_by="alias"]', preview["content"])

    async def test_member_profile_target_sender_must_be_verifiable(self):
        distiller = self._distiller({
            "group_memories": [],
            "member_profiles": [{
                "target_sender_id": "wxid_unknown",
                "target_sender_nickname": "Unknown",
                "role": "发布负责人",
                "confidence": 0.9,
                "evidence_message_ids": ["msg-1"],
                "evidence_text": "昵称看起来像 Unknown",
            }],
        })

        result = await distiller.run(room_id="room@@a", now=1100, window_minutes=10, limit=20)
        profiles = await self.memory_service.list_member_profiles("room@@a")

        self.assertEqual("success", result["status"])
        self.assertEqual(0, result["auto_applied_count"])
        self.assertEqual(0, result["candidate_count"])
        self.assertEqual([], profiles)
        self.assertIn("target_sender_id is not verifiable", result["discarded_reasons"][0])

    async def test_rejects_cross_room_evidence_message(self):
        distiller = self._distiller({
            "group_memories": [{
                "content": "跨群污染",
                "confidence": 0.9,
                "evidence_message_ids": ["msg-3"],
                "evidence_text": "B 群内容",
            }],
            "member_profiles": [],
        })

        result = await distiller.run(room_id="room@@a", now=1100, window_minutes=10, limit=20)

        self.assertEqual("success", result["status"])
        self.assertEqual([], distiller.list_candidates("room@@a"))
        self.assertIn("evidence_message_ids are not in current room window", result["discarded_reasons"][0])

    async def test_approve_pending_candidate_writes_scoped_memory(self):
        distiller = self._distiller({
            "group_memories": [{
                "content": "A 群候选记忆",
                "confidence": 0.7,
                "evidence_message_ids": ["msg-1"],
                "evidence_text": "证据",
            }],
            "member_profiles": [],
        })
        await distiller.run(room_id="room@@a", now=1100, window_minutes=10, limit=20)
        candidate = distiller.list_candidates("room@@a", status="pending")[0]

        applied = await distiller.approve_candidate(
            room_id="room@@a",
            candidate_id=candidate["candidate_id"],
        )
        memories = await self.memory_service.list_group_memories("room@@a")

        self.assertEqual("approved", applied["status"])
        self.assertEqual(1, len(memories))
        self.assertEqual(memories[0]["id"], applied["applied_memory_id"])


class DefaultLlmClientTest(unittest.TestCase):
    def test_default_llm_client_uses_agent_llm_model_call(self):
        fake_model = Mock()
        fake_model.call.return_value = {"content": "{\"group_memories\": [], \"member_profiles\": []}"}

        with patch(
            "channel.wechat_group.wechat_group_memory_distiller.AgentLLMModel",
            return_value=fake_model,
        ):
            result = _DefaultLlmClient().call(LLMRequest(
                messages=[{"role": "user", "content": "distill"}],
                stream=False,
            ))

        self.assertEqual({"content": "{\"group_memories\": [], \"member_profiles\": []}"}, result)
        fake_model.call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
