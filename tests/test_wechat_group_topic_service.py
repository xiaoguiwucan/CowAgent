import os
import tempfile
import unittest

from config import conf
from channel.wechat_group.wechat_group_archive import WechatGroupArchive


class WechatGroupTopicStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "wechat_group_topics.db")

    def tearDown(self):
        self._tmp.cleanup()

    def test_upsert_topic_thread_persists_active_threads_by_room(self):
        from channel.wechat_group.wechat_group_topic_store import WechatGroupTopicStore

        store = WechatGroupTopicStore(self.db_path)
        created = store.upsert_topic_thread(
            room_id="room@@abc",
            title="发布排期",
            gist="讨论本周五是否上线",
            facts=["需要先过回归"],
            participants=["wxid_alice", "wxid_bob"],
            open_loops=["是否延后到周六"],
            last_message_id="msg-1",
            last_row_id=101,
            message_count=3,
        )
        store.upsert_topic_thread(
            room_id="room@@other",
            title="别的群话题",
            gist="不应该出现在 room@@abc",
        )

        rows = store.list_active_threads("room@@abc", limit=5)

        self.assertEqual(1, len(rows))
        self.assertEqual(created["thread_id"], rows[0]["thread_id"])
        self.assertEqual("发布排期", rows[0]["title"])
        self.assertEqual(["需要先过回归"], rows[0]["facts"])
        self.assertEqual(["wxid_alice", "wxid_bob"], rows[0]["participants"])
        self.assertEqual(["是否延后到周六"], rows[0]["open_loops"])
        self.assertEqual(101, rows[0]["last_row_id"])

    def test_map_message_to_thread_scopes_lookup_to_room(self):
        from channel.wechat_group.wechat_group_topic_store import WechatGroupTopicStore

        store = WechatGroupTopicStore(self.db_path)
        thread = store.upsert_topic_thread(
            room_id="room@@abc",
            title="发布排期",
            gist="讨论本周五是否上线",
        )
        store.map_message_to_thread(
            room_id="room@@abc",
            thread_id=thread["thread_id"],
            message_id="msg-2",
            row_id=102,
        )
        store.map_message_to_thread(
            room_id="room@@other",
            thread_id=thread["thread_id"],
            message_id="msg-2",
            row_id=102,
        )

        match_by_message = store.get_thread_ref(room_id="room@@abc", message_id="msg-2")
        match_by_row = store.get_thread_ref(room_id="room@@abc", row_id=102)

        self.assertIsNotNone(match_by_message)
        self.assertEqual(thread["thread_id"], match_by_message["thread_id"])
        self.assertEqual("room@@abc", match_by_message["room_id"])
        self.assertIsNotNone(match_by_row)
        self.assertEqual("room@@abc", match_by_row["room_id"])
        self.assertIsNone(store.get_thread_ref(room_id="room@@missing", message_id="msg-2"))

    def test_append_summary_history_lists_latest_snapshots(self):
        from channel.wechat_group.wechat_group_topic_store import WechatGroupTopicStore

        store = WechatGroupTopicStore(self.db_path)
        thread = store.upsert_topic_thread(
            room_id="room@@abc",
            title="发布排期",
            gist="讨论本周五是否上线",
        )
        first = store.append_summary_history(
            room_id="room@@abc",
            thread_id=thread["thread_id"],
            summary_text="第一版摘要",
            snapshot={"facts": ["需要先过回归"]},
            created_at=100,
        )
        second = store.append_summary_history(
            room_id="room@@abc",
            thread_id=thread["thread_id"],
            summary_text="第二版摘要",
            snapshot={"facts": ["改到周六"]},
            created_at=200,
        )

        rows = store.list_summary_history("room@@abc", thread["thread_id"], limit=5)

        self.assertEqual([second["summary_id"], first["summary_id"]], [row["summary_id"] for row in rows])
        self.assertEqual({"facts": ["改到周六"]}, rows[0]["snapshot"])


class WechatGroupTopicServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "wechat_group_topics.db")
        self._original_topic_context_limit = conf().get("wechat_group_topic_context_limit")
        self._original_topic_recent_message_limit = conf().get("wechat_group_topic_recent_message_limit")

    def tearDown(self):
        if self._original_topic_context_limit is None:
            conf().pop("wechat_group_topic_context_limit", None)
        else:
            conf()["wechat_group_topic_context_limit"] = self._original_topic_context_limit
        if self._original_topic_recent_message_limit is None:
            conf().pop("wechat_group_topic_recent_message_limit", None)
        else:
            conf()["wechat_group_topic_recent_message_limit"] = self._original_topic_recent_message_limit
        self._tmp.cleanup()

    def test_build_prompt_block_renders_latest_active_topics(self):
        from channel.wechat_group.wechat_group_topic_service import WechatGroupTopicService
        from channel.wechat_group.wechat_group_topic_store import WechatGroupTopicStore

        store = WechatGroupTopicStore(self.db_path)
        store.upsert_topic_thread(
            room_id="room@@abc",
            title="旧话题",
            gist="这个不该进 limit=1",
            updated_at=100,
        )
        store.upsert_topic_thread(
            room_id="room@@abc",
            title="发布排期",
            gist="讨论本周五是否上线",
            facts=["需要先过回归"],
            participants=["wxid_alice", "wxid_bob"],
            open_loops=["是否延后到周六"],
            updated_at=200,
        )
        service = WechatGroupTopicService(store=store)

        block = service.build_prompt_block("room@@abc", limit=1)

        self.assertIn("<wechat-group-topic>", block)
        self.assertIn("[active_topic]", block)
        self.assertIn("title: 发布排期", block)
        self.assertIn("gist: 讨论本周五是否上线", block)
        self.assertIn("facts: 需要先过回归", block)
        self.assertIn("participants: wxid_alice, wxid_bob", block)
        self.assertIn("open_loops: 是否延后到周六", block)
        self.assertNotIn("旧话题", block)

    def test_search_topics_matches_title_and_gist(self):
        from channel.wechat_group.wechat_group_topic_service import WechatGroupTopicService
        from channel.wechat_group.wechat_group_topic_store import WechatGroupTopicStore

        store = WechatGroupTopicStore(self.db_path)
        store.upsert_topic_thread(
            room_id="room@@abc",
            title="发布排期",
            gist="讨论本周五是否上线",
            updated_at=200,
        )
        store.upsert_topic_thread(
            room_id="room@@abc",
            title="团建安排",
            gist="讨论预算和日期",
            updated_at=100,
        )
        service = WechatGroupTopicService(store=store)

        title_hits = service.search_topics("room@@abc", query="发布", limit=5)
        gist_hits = service.search_topics("room@@abc", query="预算", limit=5)

        self.assertEqual(["发布排期"], [item["title"] for item in title_hits])
        self.assertEqual(["团建安排"], [item["title"] for item in gist_hits])

    def test_build_prompt_block_from_archive_refreshes_active_topic(self):
        from channel.wechat_group.wechat_group_topic_service import WechatGroupTopicService
        from channel.wechat_group.wechat_group_topic_store import WechatGroupTopicStore

        conf()["wechat_group_topic_recent_message_limit"] = 6
        archive = WechatGroupArchive(os.path.join(self._tmp.name, "wechat_group_archive.db"))
        archive.record_message(
            message_id="msg-1",
            room_id="room@@abc",
            room_name="测试群",
            sender_id="wxid_alice",
            sender_nickname="Alice",
            message_type="text",
            text="这周五晚上发版可以吗？",
            created_at=100,
        )
        archive.record_message(
            message_id="msg-2",
            room_id="room@@abc",
            room_name="测试群",
            sender_id="wxid_bob",
            sender_nickname="Bob",
            message_type="text",
            text="回归还没过，我建议周六早上。",
            created_at=101,
        )
        store = WechatGroupTopicStore(self.db_path)
        service = WechatGroupTopicService(store=store)

        block = service.build_prompt_block_from_archive(archive, "room@@abc", now=102)
        rows = store.list_active_threads("room@@abc", limit=5)

        self.assertIn("<wechat-group-topic>", block)
        self.assertIn("title:", block)
        self.assertIn("gist:", block)
        self.assertIn("participants: wxid_alice, wxid_bob", block)
        self.assertEqual(1, len(rows))
        self.assertEqual("msg-2", rows[0]["last_message_id"])


if __name__ == "__main__":
    unittest.main()
