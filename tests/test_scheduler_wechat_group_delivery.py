import sys
import types
import unittest
from unittest.mock import patch

from agent.tools.scheduler import integration
from bridge.reply import Reply, ReplyType


class FakeAgentBridge:
    def __init__(self):
        self.remembered = []

    def agent_reply(self, query, context=None, on_event=None, clear_history=False):
        return Reply(ReplyType.TEXT, "scheduled report")

    def remember_scheduled_output(self, session_id, content, channel_type="", task_description=""):
        self.remembered.append({
            "session_id": session_id,
            "content": content,
            "channel_type": channel_type,
            "task_description": task_description,
        })


class RunningWechatGroupChannel:
    def __init__(self):
        self.sent = []

    def send(self, reply, context):
        self.sent.append((reply, context))


class FreshWechatGroupChannel:
    def send(self, reply, context):
        raise RuntimeError("wechat group sidecar is not started")


class FakeChannelManager:
    def __init__(self, channel):
        self.channel = channel

    def get_channel(self, name):
        if name == "wechat_group":
            return self.channel
        return None


class SchedulerWechatGroupDeliveryTest(unittest.TestCase):
    def test_agent_task_uses_running_wechat_group_channel(self):
        running_channel = RunningWechatGroupChannel()
        fake_app = types.SimpleNamespace(
            _channel_mgr=FakeChannelManager(running_channel)
        )
        task = {
            "id": "task-1",
            "action": {
                "type": "agent_task",
                "task_description": "send daily report",
                "receiver": "room@@abc",
                "is_group": True,
                "channel_type": "wechat_group",
                "notify_session_id": "room@@abc",
            },
        }

        with patch.dict(sys.modules, {"app": fake_app}):
            with patch("channel.channel_factory.create_channel", return_value=FreshWechatGroupChannel()):
                ok = integration._execute_agent_task(task, FakeAgentBridge())

        self.assertTrue(ok)
        self.assertEqual(1, len(running_channel.sent))
        reply, context = running_channel.sent[0]
        self.assertEqual("scheduled report", reply.content)
        self.assertEqual("room@@abc", context["receiver"])


if __name__ == "__main__":
    unittest.main()
