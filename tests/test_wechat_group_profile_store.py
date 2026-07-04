import os
import tempfile
import unittest

from channel.wechat_group.wechat_group_profile_store import WechatGroupProfileStore


class WechatGroupProfileStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "profiles.db")
        self.store = WechatGroupProfileStore(self.db_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_global_profile_store_keeps_one_row_per_sender_id(self):
        self.store.upsert_profile(sender_id="wxid_alice", primary_nickname="Alice")
        self.store.upsert_profile(sender_id="wxid_alice", primary_nickname="Alice New")

        rows = self.store.list_profiles()

        self.assertEqual(1, len(rows))
        self.assertEqual("Alice New", rows[0]["primary_nickname"])

    def test_profile_name_records_keep_room_source(self):
        self.store.upsert_name_record(
            sender_id="wxid_alice",
            room_id="room@@a",
            room_name="A群",
            display_name="阿狸",
            last_seen_at=100,
        )
        self.store.upsert_name_record(
            sender_id="wxid_alice",
            room_id="room@@b",
            room_name="B群",
            display_name="Alice姐",
            last_seen_at=200,
        )

        names = self.store.list_name_records("wxid_alice")

        self.assertEqual(["Alice姐", "阿狸"], [item["display_name"] for item in names])
        self.assertEqual("room@@b", names[0]["room_id"])


if __name__ == "__main__":
    unittest.main()
