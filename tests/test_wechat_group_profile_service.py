import os
import tempfile
import unittest

from channel.wechat_group.wechat_group_archive import WechatGroupArchive
from channel.wechat_group.wechat_group_profile_service import WechatGroupProfileService
from channel.wechat_group.wechat_group_profile_store import WechatGroupProfileStore


class WechatGroupProfileServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = WechatGroupProfileStore(os.path.join(self._tmp.name, "profiles.db"))
        self.archive = WechatGroupArchive(os.path.join(self._tmp.name, "archive.db"))
        self.service = WechatGroupProfileService(self.store, self.archive)

    def tearDown(self):
        self._tmp.cleanup()

    def test_merge_learned_profile_overwrites_style_interest_and_common_words(self):
        self.service.merge_learned_profile(
            sender_id="wxid_alice",
            primary_nickname="Alice",
            aliases=["阿狸"],
            speak_style="短句，偏直接",
            interests=["Python", "自动化"],
            common_words=["收到", "安排"],
            msg_delta=8,
            activity_delta=3,
            intimacy_delta=1,
            room_id="room@@a",
            room_name="A群",
            last_seen_at=100,
        )
        self.service.merge_learned_profile(
            sender_id="wxid_alice",
            primary_nickname="Alice2",
            aliases=["Alice姐"],
            speak_style="更爱列清单",
            interests=["架构"],
            common_words=["结论先说"],
            msg_delta=5,
            activity_delta=2,
            intimacy_delta=2,
            room_id="room@@b",
            room_name="B群",
            last_seen_at=200,
        )

        profile = self.service.get_profile("wxid_alice")

        self.assertEqual("更爱列清单", profile["speak_style"])
        self.assertEqual(["架构"], profile["interests"])
        self.assertEqual(["结论先说"], profile["common_words"])
        self.assertIn("阿狸", profile["aliases"])
        self.assertIn("Alice姐", profile["aliases"])
        self.assertEqual(13, profile["msg_count"])
        self.assertEqual(5, profile["activity_score"])
        self.assertEqual(3, profile["intimacy_score"])
        self.assertEqual(200, profile["last_seen_at"])

    def test_merge_learned_profile_keeps_existing_real_nickname_when_new_value_is_raw_sender_id(self):
        self.service.merge_learned_profile(
            sender_id="@alice_raw_id",
            primary_nickname="Alice",
            aliases=["Alice"],
            speak_style="direct",
            interests=[],
            common_words=[],
            msg_delta=3,
            activity_delta=3,
            intimacy_delta=0,
            room_id="room@@a",
            room_name="Group A",
            last_seen_at=100,
        )

        self.service.merge_learned_profile(
            sender_id="@alice_raw_id",
            primary_nickname="@alice_raw_id",
            aliases=[],
            speak_style="direct",
            interests=[],
            common_words=[],
            msg_delta=2,
            activity_delta=2,
            intimacy_delta=0,
            room_id="room@@a",
            room_name="Group A",
            last_seen_at=200,
        )

        profile = self.service.get_profile("@alice_raw_id")

        self.assertEqual("Alice", profile["primary_nickname"])

    def test_list_profiles_matches_alias_records_without_room_scope(self):
        self.service.upsert_manual_profile(
            sender_id="wxid_alice",
            primary_nickname="Alice",
            speak_style="直接",
            interests=["发布"],
            common_words=["安排"],
            aliases=["阿狸"],
            room_id="room@@a",
            room_name="A群",
        )

        rows = self.service.list_profiles(query="阿狸")

        self.assertEqual(1, len(rows))
        self.assertEqual("wxid_alice", rows[0]["sender_id"])
        self.assertNotIn("room_id", rows[0])

    def test_list_profiles_prefers_room_member_nickname_over_raw_sender_id(self):
        self.service.merge_learned_profile(
            sender_id="@alice_raw_id",
            primary_nickname="@alice_raw_id",
            aliases=[],
            speak_style="direct",
            interests=[],
            common_words=[],
            msg_delta=2,
            activity_delta=2,
            intimacy_delta=0,
            room_id="room@@a",
            room_name="Group A",
            last_seen_at=200,
        )
        self.archive.record_message(
            message_id="m1",
            room_id="room@@a",
            room_name="Group A",
            sender_id="@alice_raw_id",
            sender_nickname="@alice_raw_id",
            text="first",
            created_at=100,
        )
        self.archive.record_message(
            message_id="m2",
            room_id="room@@a",
            room_name="Group A",
            sender_id="@alice_raw_id",
            sender_nickname="Alice",
            text="second",
            created_at=101,
        )

        rows = self.service.list_profiles(limit=20, room_id="room@@a")
        stored = self.store.get_profile("@alice_raw_id")

        self.assertEqual(1, len(rows))
        self.assertEqual("Alice", rows[0]["primary_nickname"])
        self.assertEqual("Alice", stored["primary_nickname"])

    def test_repair_historical_profile_names_updates_existing_profile_from_archive(self):
        self.store.upsert_profile(
            sender_id="@alice_raw_id",
            primary_nickname="@alice_raw_id",
            speak_style="direct",
            interests=[],
            common_words=[],
            msg_count=2,
            activity_score=2,
            intimacy_score=0,
            last_seen_at=200,
        )
        self.archive.record_message(
            message_id="m3",
            room_id="room@@b",
            room_name="Group B",
            sender_id="@alice_raw_id",
            sender_nickname="@alice_raw_id",
            text="raw",
            created_at=200,
        )
        self.archive.record_message(
            message_id="m4",
            room_id="room@@a",
            room_name="Group A",
            sender_id="@alice_raw_id",
            sender_nickname="Alice",
            text="real",
            created_at=101,
        )

        result = self.service.repair_historical_profile_names()
        profile = self.store.get_profile("@alice_raw_id")

        self.assertEqual(1, result["repaired"])
        self.assertEqual("Alice", profile["primary_nickname"])

    def test_list_profiles_can_filter_members_by_room_id(self):
        self.service.upsert_manual_profile(
            sender_id="wxid_alice",
            primary_nickname="Alice",
            speak_style="direct",
            interests=[],
            common_words=[],
            aliases=["alice-a"],
            room_id="room@@a",
            room_name="Group A",
        )
        self.service.upsert_manual_profile(
            sender_id="wxid_bob",
            primary_nickname="Bob",
            speak_style="direct",
            interests=[],
            common_words=[],
            aliases=["bob-b"],
            room_id="room@@b",
            room_name="Group B",
        )

        rows = self.service.list_profiles(limit=20, room_id="room@@a")

        self.assertEqual(["wxid_alice"], [item["sender_id"] for item in rows])
        self.assertEqual("room@@a", rows[0]["room_summaries"][0]["room_id"])
        self.assertEqual("Group A", rows[0]["room_summaries"][0]["room_name"])
        self.assertEqual(rows[0]["last_seen_at"], rows[0]["room_summaries"][0]["last_seen_at"])

    def test_room_summaries_fill_missing_room_name_from_archive(self):
        self.service.upsert_manual_profile(
            sender_id="wxid_alice",
            primary_nickname="Alice",
            speak_style="direct",
            interests=[],
            common_words=[],
            aliases=["Alice A"],
            room_id="@@room_a",
            room_name="",
        )
        self.archive.record_message(
            message_id="m-room-name",
            room_id="@@room_a",
            room_name="Product Launch Group",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            text="hello",
            created_at=300,
        )

        rows = self.service.list_profiles(limit=20)

        self.assertEqual("Product Launch Group", rows[0]["room_summaries"][0]["room_name"])

    def test_resolve_profiles_filters_sender_and_bot_from_mentions(self):
        self.service.upsert_manual_profile(
            sender_id="wxid_alice",
            primary_nickname="Alice",
            speak_style="直接给结论",
            interests=[],
            common_words=[],
            aliases=[],
        )
        self.service.upsert_manual_profile(
            sender_id="wxid_bob",
            primary_nickname="Bob",
            speak_style="喜欢列清单",
            interests=[],
            common_words=[],
            aliases=[],
        )

        result = self.service.resolve_profiles_for_prompt(
            sender_id="wxid_alice",
            mentioned_sender_ids=["wxid_bot", "wxid_alice", "wxid_bob"],
            query="提醒 Bob",
            bot_sender_id="wxid_bot",
        )

        self.assertEqual("wxid_alice", result["speaker_profile"]["sender_id"])
        self.assertEqual(["wxid_bob"], [item["sender_id"] for item in result["mentioned_profiles"]])


    def test_merge_learned_aliases_preserves_existing_profile_fields(self):
        self.service.upsert_manual_profile(
            sender_id="wxid_bob",
            primary_nickname="Bob",
            speak_style="keeps answers concise",
            interests=["release"],
            common_words=["ship"],
            aliases=[],
            room_id="room@@a",
            room_name="Group A",
        )

        profile = self.service.merge_learned_aliases(
            sender_id="wxid_bob",
            aliases=["张总"],
            room_id="room@@a",
            room_name="Group A",
            last_seen_at=300,
        )

        self.assertEqual("keeps answers concise", profile["speak_style"])
        self.assertEqual(["release"], profile["interests"])
        self.assertEqual(["ship"], profile["common_words"])
        self.assertIn("张总", profile["aliases"])
        self.assertEqual(300, profile["last_seen_at"])


if __name__ == "__main__":
    unittest.main()
