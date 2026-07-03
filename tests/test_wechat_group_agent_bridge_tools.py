import tempfile
import unittest

from agent.memory.config import MemoryConfig
from agent.memory.manager import MemoryManager
from agent.tools.base_tool import BaseTool, ToolResult
from bridge.agent_bridge import AgentBridge
from bridge.context import Context, ContextType
from bridge.reply import ReplyType


class DummyTool(BaseTool):
    name = "dummy"
    description = "dummy"
    params = {"type": "object", "properties": {}, "required": []}

    def execute(self, params: dict) -> ToolResult:
        return ToolResult.success("dummy")


class FakeAgent:
    def __init__(self, memory_manager):
        self.tools = [DummyTool()]
        self.memory_manager = memory_manager
        self.model = type("FakeModel", (), {})()
        self.extra_system_suffix = ""
        self.seen_tool_names = []
        self.seen_suffix = ""
        self._last_run_new_messages = []

    def run_stream(self, **kwargs):
        self.seen_tool_names = [tool.name for tool in self.tools]
        self.seen_suffix = self.extra_system_suffix
        return "ok"


class HarnessAgentBridge(AgentBridge):
    def __init__(self, agent):
        self._agent = agent

    def get_agent(self, session_id=None):
        return self._agent


class WechatGroupAgentBridgeToolsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.manager = MemoryManager(MemoryConfig(workspace_root=self._tmp.name))

    def tearDown(self):
        self.manager.close()
        self._tmp.cleanup()

    def test_wechat_group_turn_temporarily_attaches_scoped_memory_tools(self):
        agent = FakeAgent(self.manager)
        bridge = HarnessAgentBridge(agent)
        context = Context(ContextType.TEXT, "hello")
        context["channel_type"] = "wechat_group"
        context["wechat_group_room_id"] = "room@@a"
        context["wechat_group_sender_id"] = "wxid_alice"
        context["wechat_group_bot_sender_id"] = "wxid_bot"

        reply = bridge.agent_reply("hello", context=context)

        self.assertEqual(ReplyType.TEXT, reply.type)
        self.assertEqual("ok", reply.content)
        self.assertIn("wechat_group_memory_search", agent.seen_tool_names)
        self.assertIn("wechat_group_profile_get", agent.seen_tool_names)
        self.assertIn("wechat_group_memory_search", agent.seen_suffix)
        self.assertEqual(["dummy"], [tool.name for tool in agent.tools])
        self.assertEqual("", agent.extra_system_suffix)


if __name__ == "__main__":
    unittest.main()
