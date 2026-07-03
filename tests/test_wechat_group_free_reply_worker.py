import time
import unittest
from unittest.mock import Mock

from channel.wechat_group.wechat_group_free_reply_worker import WechatGroupFreeReplyWorkerPool


def wait_until(predicate, timeout=2.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


class WechatGroupFreeReplyWorkerPoolTest(unittest.TestCase):
    def make_task(self, suffix="a"):
        return {
            "room_id": "room@@abc",
            "room_name": "测试群",
            "sender_id": "wxid_alice",
            "sender_name": "Alice",
            "text": "谁能总结一下？{}".format(suffix),
            "msg": Mock(),
            "local_decision": {"triggered": True, "score": 55},
            "queued_at": time.time(),
        }

    def make_pool(self, judge=None, callback=None, **kwargs):
        if judge is None:
            judge = Mock()
            judge.judge.return_value = {"approved": True, "confidence": 0.9}
        callback = callback or Mock()
        pool = WechatGroupFreeReplyWorkerPool(
            judge=judge,
            submit_callback=callback,
            max_workers=kwargs.get("max_workers", 1),
            queue_size=kwargs.get("queue_size", 10),
            ttl_seconds=kwargs.get("ttl_seconds", 120),
        )
        return pool, judge, callback

    def test_worker_approves_task_and_calls_submit_callback(self):
        pool, judge, callback = self.make_pool()
        pool.start()
        try:
            self.assertTrue(pool.submit(self.make_task()))
            self.assertTrue(wait_until(lambda: pool.status()["approved_total"] == 1))
        finally:
            pool.stop()

        callback.assert_called_once()
        self.assertEqual(1, pool.status()["approved_total"])

    def test_worker_rejects_task_without_callback(self):
        judge = Mock()
        judge.judge.return_value = {"approved": False, "error": "low_confidence"}
        callback = Mock()
        pool, _, _ = self.make_pool(judge=judge, callback=callback)
        pool.start()
        try:
            self.assertTrue(pool.submit(self.make_task()))
            self.assertTrue(wait_until(lambda: pool.status()["rejected_total"] == 1))
        finally:
            pool.stop()

        callback.assert_not_called()
        self.assertEqual(1, pool.status()["rejected_total"])

    def test_worker_logs_llm_rejected_decision(self):
        judge = Mock()
        judge.judge.return_value = {
            "approved": False,
            "confidence": 0.41,
            "error": "low_confidence",
            "reason": "two person thread",
        }
        callback = Mock()
        pool, _, _ = self.make_pool(judge=judge, callback=callback)
        pool.start()
        try:
            with self.assertLogs("log", level="INFO") as captured:
                self.assertTrue(pool.submit(self.make_task()))
                self.assertTrue(wait_until(lambda: pool.status()["rejected_total"] == 1))
        finally:
            pool.stop()

        logs = "\n".join(captured.output)
        self.assertIn("[wechat_group] free reply llm rejected:", logs)
        self.assertIn("confidence=0.41", logs)
        self.assertIn('error="low_confidence"', logs)
        self.assertIn('reason="two person thread"', logs)

    def test_expired_task_is_dropped_before_llm_judge(self):
        pool, judge, callback = self.make_pool(ttl_seconds=1)
        task = self.make_task()
        task["queued_at"] = time.time() - 999
        pool.start()
        try:
            self.assertTrue(pool.submit(task))
            self.assertTrue(wait_until(lambda: pool.status()["expired_total"] == 1))
        finally:
            pool.stop()

        judge.judge.assert_not_called()
        callback.assert_not_called()

    def test_queue_full_drops_task(self):
        pool, _, _ = self.make_pool(queue_size=1)

        self.assertTrue(pool.submit(self.make_task("a")))
        self.assertFalse(pool.submit(self.make_task("b")))
        self.assertEqual(1, pool.status()["dropped_total"])

    def test_status_snapshot_contains_counters(self):
        pool, _, _ = self.make_pool()
        status = pool.status()

        self.assertIn("queue_size", status)
        self.assertIn("submitted_total", status)
        self.assertIn("dropped_total", status)
        self.assertIn("last_error", status)


if __name__ == "__main__":
    unittest.main()
