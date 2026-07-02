import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WechatGroupMemoryUiTest(unittest.TestCase):
    def test_groups_page_exposes_memory_management_section(self):
        console_js = (ROOT / "channel/web/static/js/console.js").read_text(encoding="utf-8")

        self.assertIn("groups_nav_memory", console_js)
        self.assertIn("buildGroupsMemoryPanel", console_js)
        self.assertIn("groups-memory-room-list", console_js)
        self.assertIn("groups-memory-group-content", console_js)
        self.assertIn("groups-memory-profile-sender-id", console_js)
        self.assertIn("groups-memory-preview-content", console_js)
        self.assertIn("groups-memory-search", console_js)
        self.assertIn("disableGroupsGroupMemory", console_js)
        self.assertIn("disableGroupsMemberProfile", console_js)
        self.assertIn("groups-memory-profile-revisions", console_js)
        self.assertIn("/api/wechat-group/memories/summary", console_js)
        self.assertIn("/api/wechat-group/memories/disable", console_js)
        self.assertIn("/api/wechat-group/memories/profiles/revisions", console_js)
        self.assertIn("/api/wechat-group/memories/group", console_js)
        self.assertIn("/api/wechat-group/memories/profiles", console_js)
        self.assertIn("/api/wechat-group/memories/preview", console_js)

    def test_groups_page_cache_buster_changes_for_memory_ui(self):
        chat_html = (ROOT / "channel/web/chat.html").read_text(encoding="utf-8")

        self.assertIn("console.js?v=20260702-groups-memory", chat_html)


if __name__ == "__main__":
    unittest.main()
