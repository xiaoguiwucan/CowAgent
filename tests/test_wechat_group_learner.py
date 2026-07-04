import os
import tempfile
import unittest

from channel.wechat_group.wechat_group_archive import WechatGroupArchive
from channel.wechat_group.wechat_group_knowledge_service import WechatGroupKnowledgeService
from channel.wechat_group.wechat_group_knowledge_store import WechatGroupKnowledgeStore
from channel.wechat_group.wechat_group_learner import WechatGroupLearner
from channel.wechat_group.wechat_group_profile_service import WechatGroupProfileService
from channel.wechat_group.wechat_group_profile_store import WechatGroupProfileStore


class WechatGroupLearnerTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.archive = WechatGroupArchive(os.path.join(self._tmp.name, "archive.db"))
        self.profile_store = WechatGroupProfileStore(os.path.join(self._tmp.name, "profiles.db"))
        self.knowledge_store = WechatGroupKnowledgeStore(os.path.join(self._tmp.name, "knowledge.db"))
        self.profile_service = WechatGroupProfileService(self.profile_store)
        self.knowledge_service = WechatGroupKnowledgeService(self.knowledge_store)
        self.learner = WechatGroupLearner(
            archive=self.archive,
            profile_service=self.profile_service,
            knowledge_service=self.knowledge_service,
            knowledge_store=self.knowledge_store,
            config_getter=lambda key, default=None: {
                "wechat_group_learning_batch_message_limit": 50,
                "wechat_group_learning_profile_min_messages": 1,
                "wechat_group_learning_profile_sample_limit": 10,
                "wechat_group_learning_group_memory_min_messages": 2,
            }.get(key, default),
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_learner_consumes_only_new_archived_prefix(self):
        self.archive.record_message(message_id="m1", room_id="room@@a", sender_id="wxid_alice", sender_nickname="Alice", text="今天继续发版本", created_at=100)
        self.archive.record_message(message_id="m2", room_id="room@@a", sender_id="wxid_alice", sender_nickname="Alice", text="晚上我再整理发布说明", created_at=101)

        first = self.learner.run_once("room@@a", mode="profile")
        first_cursor = self.knowledge_store.get_cursor("room@@a")["last_archive_row_id"]
        second = self.learner.run_once("room@@a", mode="profile")
        second_cursor = self.knowledge_store.get_cursor("room@@a")["last_archive_row_id"]

        self.assertEqual(2, first["batch_message_count"])
        self.assertEqual(first_cursor, second_cursor)
        self.assertEqual(0, second["batch_message_count"])

    def test_learner_writes_profile_without_candidate_review(self):
        self.archive.record_message(
            message_id="m3",
            room_id="room@@a",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            text="我来补充前端样式",
            created_at=102,
        )

        result = self.learner.run_once("room@@a", mode="profile")
        profile = self.profile_service.get_profile("wxid_bob")

        self.assertEqual(1, result["profile_update_count"])
        self.assertEqual("wxid_bob", profile["sender_id"])
        self.assertNotIn("pending", str(profile))

    def test_learner_prefers_real_nickname_over_raw_sender_id(self):
        self.archive.record_message(
            message_id="m31",
            room_id="room@@a",
            sender_id="@alice_raw_id",
            sender_nickname="Alice",
            text="first",
            created_at=102,
        )
        self.archive.record_message(
            message_id="m32",
            room_id="room@@a",
            sender_id="@alice_raw_id",
            sender_nickname="@alice_raw_id",
            text="second",
            created_at=103,
        )

        self.learner.run_once("room@@a", mode="profile")
        profile = self.profile_service.get_profile("@alice_raw_id")

        self.assertEqual("Alice", profile["primary_nickname"])

    def test_learner_records_group_memory_and_run_status(self):
        self.archive.record_message(
            message_id="m4",
            room_id="room@@a",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            text="本群周六早上统一发版",
            created_at=103,
        )
        self.archive.record_message(
            message_id="m5",
            room_id="room@@a",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            text="确认，本群周六早上统一发版",
            created_at=104,
        )

        result = self.learner.run_once("room@@a", mode="memory")
        memories = self.knowledge_service.list_group_memories("room@@a")
        runs = self.knowledge_store.list_learning_runs("room@@a")

        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["group_memory_upsert_count"])
        self.assertEqual(1, len(memories))
        self.assertIn("发版", memories[0]["content"])
        self.assertEqual("success", runs[0]["status"])


if __name__ == "__main__":
    unittest.main()
