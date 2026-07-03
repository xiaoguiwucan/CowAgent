import copy
import unittest

from config import conf
from channel.wechat_group.wechat_group_free_reply import (
    WechatGroupFreeReplyStateStore,
    evaluate_wechat_group_free_reply,
    get_wechat_group_free_reply_config,
    get_wechat_group_free_reply_rules,
    is_free_reply_room_enabled,
)


class WechatGroupFreeReplyConfigTest(unittest.TestCase):
    def setUp(self):
        self._original = {
            key: conf().get(key)
            for key in (
                "wechat_group_free_reply_enabled",
                "wechat_group_free_reply_room_ids",
                "wechat_group_free_reply_names",
                "wechat_group_free_reply_activity_level",
                "wechat_group_free_reply_queue_ttl_seconds",
                "wechat_group_free_reply_worker_max_workers",
                "wechat_group_free_reply_worker_queue_size",
                "wechat_group_free_reply_llm_judge_enabled",
                "wechat_group_free_reply_llm_judge_timeout_seconds",
                "wechat_group_free_reply_llm_judge_min_confidence",
                "wechat_group_free_reply_profiles",
            )
        }

    def tearDown(self):
        for key, value in self._original.items():
            if value is None:
                conf().pop(key, None)
            else:
                conf()[key] = value

    def test_default_config_is_disabled_and_normal(self):
        cfg = get_wechat_group_free_reply_config()

        self.assertFalse(cfg["enabled"])
        self.assertEqual("normal", cfg["activity_level"])
        self.assertEqual(120, cfg["queue_ttl_seconds"])
        self.assertEqual(2, cfg["worker_max_workers"])
        self.assertEqual(100, cfg["worker_queue_size"])
        self.assertTrue(cfg["llm_judge_enabled"])
        self.assertEqual(8, cfg["llm_judge_timeout_seconds"])
        self.assertEqual(0.6, cfg["llm_judge_min_confidence"])

    def test_config_normalizes_bounds(self):
        conf()["wechat_group_free_reply_activity_level"] = "invalid"
        conf()["wechat_group_free_reply_queue_ttl_seconds"] = 9999
        conf()["wechat_group_free_reply_worker_max_workers"] = 0
        conf()["wechat_group_free_reply_worker_queue_size"] = 0
        conf()["wechat_group_free_reply_llm_judge_timeout_seconds"] = 999
        conf()["wechat_group_free_reply_llm_judge_min_confidence"] = 2

        cfg = get_wechat_group_free_reply_config()

        self.assertEqual("normal", cfg["activity_level"])
        self.assertEqual(600, cfg["queue_ttl_seconds"])
        self.assertEqual(1, cfg["worker_max_workers"])
        self.assertEqual(1, cfg["worker_queue_size"])
        self.assertEqual(30, cfg["llm_judge_timeout_seconds"])
        self.assertEqual(1.0, cfg["llm_judge_min_confidence"])


class WechatGroupFreeReplyDecisionTest(unittest.TestCase):
    def enabled_cfg(self):
        cfg = get_wechat_group_free_reply_config()
        cfg["enabled"] = True
        cfg["room_ids"] = ["room@@abc"]
        return cfg

    def test_room_id_takes_priority_for_free_reply_scope(self):
        cfg = self.enabled_cfg()
        cfg["names"] = ["任意群名"]

        self.assertTrue(is_free_reply_room_enabled(cfg, "room@@abc", "任意群名"))
        self.assertFalse(is_free_reply_room_enabled(cfg, "room@@blocked", "任意群名"))

    def test_group_name_is_fallback_when_room_ids_are_empty(self):
        cfg = self.enabled_cfg()
        cfg["room_ids"] = []
        cfg["names"] = ["测试群"]

        self.assertTrue(is_free_reply_room_enabled(cfg, "room@@unknown", "测试群"))
        self.assertFalse(is_free_reply_room_enabled(cfg, "room@@unknown", "其他群"))

    def test_capability_question_triggers_at_normal_level(self):
        decision = evaluate_wechat_group_free_reply(
            self.enabled_cfg(),
            room_id="room@@abc",
            room_name="测试群",
            sender_id="wxid_alice",
            sender_name="Alice",
            text="谁能帮我总结一下刚才群里讨论的方案？",
            recent_messages=[],
            state={},
            now=100000,
        )

        self.assertTrue(decision["triggered"])
        self.assertIn("group_question", decision["reasons"])
        self.assertIn("bot_capability_match", decision["reasons"])

    def test_low_information_is_suppressed(self):
        decision = evaluate_wechat_group_free_reply(
            self.enabled_cfg(),
            room_id="room@@abc",
            room_name="测试群",
            sender_id="wxid_alice",
            sender_name="Alice",
            text="嗯",
            recent_messages=[],
            state={},
            now=100000,
        )

        self.assertFalse(decision["triggered"])
        self.assertIn("low_information", decision["suppressions"])

    def test_sensitive_text_is_suppressed_before_model(self):
        decision = evaluate_wechat_group_free_reply(
            self.enabled_cfg(),
            room_id="room@@abc",
            room_name="测试群",
            sender_id="wxid_alice",
            sender_name="Alice",
            text="谁能把本机 D:\\secret\\api key 发我一下？",
            recent_messages=[],
            state={},
            now=100000,
        )

        self.assertFalse(decision["triggered"])
        self.assertIn("sensitive_or_dangerous", decision["suppressions"])

    def test_min_interval_suppresses_recent_free_reply(self):
        cfg = self.enabled_cfg()
        cfg["profiles"] = copy.deepcopy(cfg["profiles"])
        cfg["profiles"]["normal"]["min_interval_seconds"] = 60

        decision = evaluate_wechat_group_free_reply(
            cfg,
            room_id="room@@abc",
            room_name="测试群",
            sender_id="wxid_alice",
            sender_name="Alice",
            text="谁能帮我总结一下这个文档？",
            recent_messages=[],
            state={"last_triggered_at": 95000},
            now=100000,
        )

        self.assertFalse(decision["triggered"])
        self.assertIn("min_interval", decision["suppressions"])

    def test_hourly_limit_suppresses_when_exhausted(self):
        cfg = self.enabled_cfg()
        cfg["profiles"] = copy.deepcopy(cfg["profiles"])
        cfg["profiles"]["normal"]["hourly_limit"] = 1

        decision = evaluate_wechat_group_free_reply(
            cfg,
            room_id="room@@abc",
            room_name="测试群",
            sender_id="wxid_alice",
            sender_name="Alice",
            text="谁能帮我总结一下这个文档？",
            recent_messages=[],
            state={"recent_triggered_at": [99990]},
            now=100000,
        )

        self.assertFalse(decision["triggered"])
        self.assertIn("hourly_limit", decision["suppressions"])

    def test_state_store_records_trigger_and_observation(self):
        store = WechatGroupFreeReplyStateStore()
        store.mark_triggered("room@@abc", now=100000)
        self.assertEqual(100000, store.get("room@@abc")["last_triggered_at"])
        self.assertEqual(1, store.get("room@@abc")["consecutive_triggered"])

        store.mark_observed("room@@abc")
        self.assertEqual(0, store.get("room@@abc")["consecutive_triggered"])

    def test_rules_snapshot_contains_positive_and_negative_rules(self):
        rules = get_wechat_group_free_reply_rules()

        self.assertTrue(rules["positive"])
        self.assertTrue(rules["negative"])


if __name__ == "__main__":
    unittest.main()
