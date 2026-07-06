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

    def test_learner_filters_markup_noise_from_common_words(self):
        noisy_text = (
            "<msg biztype='1' size='123' bizid='x'><emoji cd='df' ecd='fa' duration='2' /></msg> "
            "<revokemsg>撤回消息</revokemsg> "
            "今天继续聊 NAS、API 和 Docker 部署，NAS 方案继续确认，API 接口继续确认。 "
            "&amp;nbsp; fffcab dd ef"
        )
        self.archive.record_message(
            message_id="m-noise",
            room_id="room@@a",
            sender_id="wxid_noise",
            sender_nickname="Noise",
            text=noisy_text,
            created_at=105,
        )

        self.learner.run_once("room@@a", mode="profile")
        profile = self.profile_service.get_profile("wxid_noise")

        self.assertIsNotNone(profile)
        self.assertNotIn("amp", profile["common_words"])
        self.assertNotIn("size", profile["common_words"])
        self.assertNotIn("biztype", profile["common_words"])
        self.assertNotIn("df", profile["common_words"])
        self.assertNotIn("ecd", profile["common_words"])
        self.assertNotIn("bizid", profile["common_words"])
        self.assertNotIn("duration", profile["common_words"])
        self.assertNotIn("revokemsg", profile["common_words"])
        self.assertTrue(set(profile["common_words"]).issubset({"nas", "api", "docker", "接口"}))

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


    def test_learner_learns_alias_from_single_explicit_member_mention(self):
        self.archive.record_message(
            message_id="m-alias-1",
            room_id="room@@a",
            room_name="Group A",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            text="@CowBot\u2005请@张总\u2005看下发布安排",
            metadata={
                "at_list": ["wxid_bot", "wxid_bob"],
                "self_id": "wxid_bot",
                "self_display_name": "CowBot",
            },
            created_at=110,
        )

        result = self.learner.run_once("room@@a", mode="profile")
        profile = self.profile_service.get_profile("wxid_bob")
        speaker = self.profile_service.get_profile("wxid_alice")

        self.assertEqual(2, result["profile_update_count"])
        self.assertIsNotNone(profile)
        learned_names = [profile.get("primary_nickname", "")] + list(profile.get("aliases") or [])
        self.assertIn("张总", learned_names)
        self.assertNotIn("张总", [speaker.get("primary_nickname", "")] + list(speaker.get("aliases") or []))

    def test_learner_skips_alias_learning_for_multiple_non_bot_mentions(self):
        self.archive.record_message(
            message_id="m-alias-2",
            room_id="room@@a",
            room_name="Group A",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            text="@CowBot\u2005请@老王\u2005和@小李\u2005一起看下",
            metadata={
                "at_list": ["wxid_bot", "wxid_bob", "wxid_cindy"],
                "self_id": "wxid_bot",
                "self_display_name": "CowBot",
            },
            created_at=111,
        )

        result = self.learner.run_once("room@@a", mode="profile")

        self.assertEqual(1, result["profile_update_count"])
        self.assertIsNone(self.profile_service.get_profile("wxid_bob"))
        self.assertIsNone(self.profile_service.get_profile("wxid_cindy"))


if __name__ == "__main__":
    unittest.main()
