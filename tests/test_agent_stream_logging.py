# encoding:utf-8
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestAgentStreamLogging(unittest.TestCase):
    def test_logs_llm_request_sources_and_summary_before_call(self):
        from agent.protocol.agent_stream import AgentStreamExecutor
        from agent.protocol.models import LLMModel

        class StreamingModel(LLMModel):
            def __init__(self):
                super().__init__(model="unit-test-model")

            def call_stream(self, request):
                self.request = request
                yield {
                    "choices": [
                        {
                            "delta": {"content": "ok"},
                            "finish_reason": "stop",
                        }
                    ]
                }

        class Tool:
            name = "read"
            description = "Read file content"
            params = {"type": "object", "properties": {"path": {"type": "string"}}}

            def get_json_schema(self):
                return {
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    }
                }

        long_tail = "TAIL_MARKER_SHOULD_NOT_BE_LOGGED"
        model = StreamingModel()
        executor = AgentStreamExecutor(
            agent=None,
            model=model,
            system_prompt=(
                "# Tools\nread, write\n\n"
                "# Project context\n"
                "## AGENTS.md\nAGENTS_FULL_TEXT_SHOULD_NOT_BE_LOGGED\n\n"
                "## MEMORY.md\nMEMORY_FULL_TEXT_SHOULD_NOT_BE_LOGGED\n"
            ),
            tools=[Tool()],
            messages=[
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "HISTORY_SHOULD_NOT_BE_LOGGED"}],
                },
                {
                    "role": "user",
                    "content": [{"type": "text", "text": ("x" * 600) + long_tail}],
                },
            ],
        )

        with self.assertLogs("log", level="INFO") as captured:
            executor._call_llm_stream(retry_on_empty=False)

        logs = "\n".join(captured.output)
        self.assertIn("[Agent] LLM request summary:", logs)
        self.assertIn("system: chars=", logs)
        self.assertIn("sources=AGENTS.md, MEMORY.md", logs)
        self.assertIn("messages: count=2", logs)
        self.assertIn("assistant=1", logs)
        self.assertIn("user=1", logs)
        self.assertIn("tools: count=1 names=read", logs)
        self.assertNotIn("AGENTS_FULL_TEXT_SHOULD_NOT_BE_LOGGED", logs)
        self.assertNotIn("MEMORY_FULL_TEXT_SHOULD_NOT_BE_LOGGED", logs)
        self.assertNotIn("HISTORY_SHOULD_NOT_BE_LOGGED", logs)
        self.assertNotIn(long_tail, logs)


if __name__ == "__main__":
    unittest.main()
