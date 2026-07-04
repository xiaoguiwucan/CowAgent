import os
import tempfile
import unittest

from config import conf


class WechatGroupStickerServiceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self._tmp.name, "wechat_group_sticker.db")
        self.image_path = os.path.join(self._tmp.name, "happy-cat.png")
        with open(self.image_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\nfake-sticker-data")
        self._original = {
            "wechat_group_sticker_max_size_mb": conf().get("wechat_group_sticker_max_size_mb"),
            "wechat_group_sticker_daily_send_limit": conf().get("wechat_group_sticker_daily_send_limit"),
        }

    def tearDown(self):
        for key, value in self._original.items():
            if value is None:
                conf().pop(key, None)
            else:
                conf()[key] = value
        self._tmp.cleanup()

    def test_collect_from_message_persists_active_sticker(self):
        from channel.wechat_group.wechat_group_sticker_service import WechatGroupStickerService
        from channel.wechat_group.wechat_group_sticker_store import WechatGroupStickerStore

        service = WechatGroupStickerService(store=WechatGroupStickerStore(self.db_path))

        row = service.collect_from_message(
            room_id="room@@abc",
            media_path=self.image_path,
            source_message_id="msg-1",
            description="happy cat reaction",
            now=100,
        )

        self.assertEqual("room@@abc", row["room_id"])
        self.assertEqual("active", row["status"])
        self.assertEqual("happy cat reaction", row["description"])
        self.assertEqual(0, row["use_count"])
        self.assertTrue(row["file_hash"])

    def test_collect_from_message_dedupes_same_file_in_same_room(self):
        from channel.wechat_group.wechat_group_sticker_service import WechatGroupStickerService
        from channel.wechat_group.wechat_group_sticker_store import WechatGroupStickerStore

        service = WechatGroupStickerService(store=WechatGroupStickerStore(self.db_path))
        first = service.collect_from_message(
            room_id="room@@abc",
            media_path=self.image_path,
            source_message_id="msg-1",
            description="happy cat reaction",
            now=100,
        )
        second = service.collect_from_message(
            room_id="room@@abc",
            media_path=self.image_path,
            source_message_id="msg-2",
            description="happy cat reaction",
            now=101,
        )
        rows = service.search_stickers("room@@abc", query="happy", limit=5)

        self.assertEqual(first["sticker_id"], second["sticker_id"])
        self.assertEqual(1, len(rows))

    def test_prepare_send_result_honors_daily_limit_after_record_sent(self):
        from channel.wechat_group.wechat_group_sticker_service import WechatGroupStickerService
        from channel.wechat_group.wechat_group_sticker_store import WechatGroupStickerStore

        conf()["wechat_group_sticker_daily_send_limit"] = 1
        service = WechatGroupStickerService(store=WechatGroupStickerStore(self.db_path))
        row = service.collect_from_message(
            room_id="room@@abc",
            media_path=self.image_path,
            source_message_id="msg-1",
            description="happy cat reaction",
            now=100,
        )

        result = service.prepare_send_result("room@@abc", row["sticker_id"], message="send this", now=100)
        service.record_sent("room@@abc", row["sticker_id"], now=101)

        self.assertEqual("file_to_send", result["type"])
        self.assertEqual(row["sticker_id"], result["sticker_id"])
        self.assertEqual(self.image_path, result["path"])
        with self.assertRaises(ValueError):
            service.prepare_send_result("room@@abc", row["sticker_id"], now=102)

    def test_disable_sticker_excludes_it_from_active_search(self):
        from channel.wechat_group.wechat_group_sticker_service import WechatGroupStickerService
        from channel.wechat_group.wechat_group_sticker_store import WechatGroupStickerStore

        service = WechatGroupStickerService(store=WechatGroupStickerStore(self.db_path))
        row = service.collect_from_message(
            room_id="room@@abc",
            media_path=self.image_path,
            source_message_id="msg-1",
            description="happy cat reaction",
            now=100,
        )

        updated = service.disable_sticker("room@@abc", row["sticker_id"])
        rows = service.search_stickers("room@@abc", query="happy", limit=5)

        self.assertEqual("disabled", updated["status"])
        self.assertEqual([], rows)


if __name__ == "__main__":
    unittest.main()
