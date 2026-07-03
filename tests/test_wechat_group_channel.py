import tempfile
import unittest
from unittest.mock import Mock

from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.channel_factory import create_channel
from channel.wechat_group.protocol import SidecarEventType, parse_sidecar_event
from channel.wechat_group.wechat_group_client import WechatGroupClient
from channel.wechat_group.wechat_group_channel import WechatGroupChannel
from common import const
from config import conf


class FakeClient:
    def __init__(self):
        self.commands = []
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def send_text(self, room_id, text, mention_ids=None):
        self.commands.append(("send_text", room_id, text, mention_ids or []))

    def send_file(self, room_id, path):
        self.commands.append(("send_file", room_id, path))

    def send_image(self, room_id, path):
        self.commands.append(("send_image", room_id, path))

    def send_audio(self, room_id, path):
        self.commands.append(("send_audio", room_id, path))

    def list_rooms(self):
        self.commands.append(("list_rooms",))


class CapturingClient(WechatGroupClient):
    def __init__(self):
        super().__init__()
        self.sent = []

    def send_command(self, command):
        self.sent.append(command.to_json())


class WechatGroupChannelTest(unittest.TestCase):
    def setUp(self):
        self._original_config = {
            "wechat_group_room_ids": conf().get("wechat_group_room_ids"),
            "wechat_group_names": conf().get("wechat_group_names"),
            "group_name_white_list": conf().get("group_name_white_list"),
            "wechat_group_free_reply_enabled": conf().get("wechat_group_free_reply_enabled"),
            "wechat_group_free_reply_room_ids": conf().get("wechat_group_free_reply_room_ids"),
            "wechat_group_free_reply_names": conf().get("wechat_group_free_reply_names"),
            "wechat_group_free_reply_activity_level": conf().get("wechat_group_free_reply_activity_level"),
        }

    def tearDown(self):
        for key, value in self._original_config.items():
            if value is None:
                conf().pop(key, None)
            else:
                conf()[key] = value

    def test_factory_creates_wechat_group_channel(self):
        channel = create_channel(const.WECHAT_GROUP)

        self.assertIsInstance(channel, WechatGroupChannel)
        self.assertEqual(const.WECHAT_GROUP, channel.channel_type)

    def test_duplicate_and_self_messages_are_ignored(self):
        channel = WechatGroupChannel(client=FakeClient())
        channel.handle_text = Mock()
        event = parse_sidecar_event({
            "type": SidecarEventType.MESSAGE,
            "message_id": "msg-1",
            "room_id": "room@@abc",
            "room_name": "测试群",
            "sender_id": "wxid_alice",
            "sender_name": "Alice",
            "self_id": "wxid_bot",
            "self_name": "CowBot",
            "text": "@CowBot hello",
            "is_at": True,
            "at_list": ["wxid_bot"],
        })

        self.assertTrue(channel.consume_sidecar_event(event))
        self.assertFalse(channel.consume_sidecar_event(event))

        self_msg = parse_sidecar_event({
            "type": "message",
            "message_id": "msg-2",
            "room_id": "room@@abc",
            "room_name": "测试群",
            "sender_id": "wxid_bot",
            "sender_name": "CowBot",
            "self_id": "wxid_bot",
            "self_name": "CowBot",
            "text": "self",
        })
        self.assertFalse(channel.consume_sidecar_event(self_msg))
        self.assertEqual(1, channel.handle_text.call_count)

    def test_unselected_room_id_is_ignored_before_group_name_matching(self):
        conf()["wechat_group_room_ids"] = ["room@@allowed"]
        conf()["wechat_group_names"] = []
        channel = WechatGroupChannel(client=FakeClient())
        channel.handle_text = Mock()

        ignored = parse_sidecar_event({
            "type": "message",
            "message_id": "msg-3",
            "room_id": "room@@blocked",
            "room_name": "测试群",
            "sender_id": "wxid_alice",
            "sender_name": "Alice",
            "self_id": "wxid_bot",
            "self_name": "CowBot",
            "text": "@CowBot hello",
            "is_at": True,
            "at_list": ["wxid_bot"],
        })
        allowed = parse_sidecar_event({
            "type": "message",
            "message_id": "msg-4",
            "room_id": "room@@allowed",
            "room_name": "测试群",
            "sender_id": "wxid_alice",
            "sender_name": "Alice",
            "self_id": "wxid_bot",
            "self_name": "CowBot",
            "text": "@CowBot hello",
            "is_at": True,
            "at_list": ["wxid_bot"],
        })

        self.assertFalse(channel.consume_sidecar_event(ignored))
        self.assertTrue(channel.consume_sidecar_event(allowed))
        self.assertEqual(1, channel.handle_text.call_count)

    def test_selected_room_name_is_used_when_room_ids_are_empty(self):
        conf()["wechat_group_room_ids"] = []
        conf()["wechat_group_names"] = ["测试群"]
        channel = WechatGroupChannel(client=FakeClient())
        channel.handle_text = Mock()

        ignored = parse_sidecar_event({
            "type": "message",
            "message_id": "msg-5",
            "room_id": "room@@other",
            "room_name": "其他群",
            "sender_id": "wxid_alice",
            "sender_name": "Alice",
            "self_id": "wxid_bot",
            "self_name": "CowBot",
            "text": "@CowBot hello",
            "is_at": True,
            "at_list": ["wxid_bot"],
        })
        allowed = parse_sidecar_event({
            "type": "message",
            "message_id": "msg-6",
            "room_id": "room@@name",
            "room_name": "测试群",
            "sender_id": "wxid_alice",
            "sender_name": "Alice",
            "self_id": "wxid_bot",
            "self_name": "CowBot",
            "text": "@CowBot hello",
            "is_at": True,
            "at_list": ["wxid_bot"],
        })

        self.assertFalse(channel.consume_sidecar_event(ignored))
        self.assertTrue(channel.consume_sidecar_event(allowed))
        self.assertEqual(1, channel.handle_text.call_count)

    def test_selected_room_id_enters_group_context_without_group_name_whitelist(self):
        conf()["wechat_group_room_ids"] = ["room@@allowed"]
        conf()["group_name_white_list"] = []
        channel = WechatGroupChannel(client=FakeClient())
        msg = Mock(
            ctype=ContextType.TEXT,
            content="@CowBot hello",
            from_user_id="room@@allowed",
            other_user_id="room@@allowed",
            other_user_nickname="Not In Whitelist",
            actual_user_id="wxid_alice",
            actual_user_nickname="Alice",
            to_user_id="wxid_bot",
            is_at=True,
            at_list=["wxid_bot"],
            self_display_name="CowBot",
        )

        context = channel._compose_context(
            ContextType.TEXT,
            msg.content,
            isgroup=True,
            msg=msg,
        )

        self.assertIsNotNone(context)
        self.assertEqual("room@@allowed", context["receiver"])

    def test_wechat_group_scheduler_request_sets_scheduler_intent(self):
        conf()["wechat_group_room_ids"] = ["room@@allowed"]
        conf()["group_name_white_list"] = []
        channel = WechatGroupChannel(client=FakeClient())
        msg = Mock(
            ctype=ContextType.TEXT,
            content="@CowBot 每天12点在本群里面播报世界杯比赛结果",
            from_user_id="room@@allowed",
            other_user_id="room@@allowed",
            other_user_nickname="Not In Whitelist",
            actual_user_id="wxid_alice",
            actual_user_nickname="Alice",
            to_user_id="wxid_bot",
            is_at=True,
            at_list=["wxid_bot"],
            self_display_name="CowBot",
        )

        context = channel._compose_context(
            ContextType.TEXT,
            msg.content,
            isgroup=True,
            msg=msg,
        )

        self.assertIsNotNone(context)
        self.assertTrue(context["intent_requires_scheduler"])

    def test_send_text_reply_to_original_room_with_sender_mention(self):
        client = FakeClient()
        channel = WechatGroupChannel(client=client)
        context = {
            "type": ContextType.TEXT,
            "receiver": "room@@abc",
            "msg": Mock(
                is_group=True,
                actual_user_id="wxid_alice",
                actual_user_nickname="Alice",
            ),
        }

        channel.send(Reply(ReplyType.TEXT, "hello"), context)

        self.assertEqual(
            [("send_text", "room@@abc", "hello", ["wxid_alice"])],
            client.commands,
        )

    def test_send_error_reply_to_original_room_with_sender_mention(self):
        client = FakeClient()
        channel = WechatGroupChannel(client=client)
        context = {
            "type": ContextType.TEXT,
            "receiver": "room@@abc",
            "msg": Mock(
                is_group=True,
                actual_user_id="wxid_alice",
                actual_user_nickname="Alice",
            ),
        }

        channel.send(Reply(ReplyType.ERROR, "Agent error"), context)

        self.assertEqual(
            [("send_text", "room@@abc", "Agent error", ["wxid_alice"])],
            client.commands,
        )

    def test_decorated_group_reply_does_not_prefix_plain_text_at(self):
        client = FakeClient()
        channel = WechatGroupChannel(client=client)
        context = {
            "isgroup": True,
            "receiver": "room@@abc",
            "msg": Mock(
                is_group=True,
                actual_user_id="wxid_alice",
                actual_user_nickname="Alice",
            ),
        }

        reply = channel._decorate_reply(context, Reply(ReplyType.TEXT, "hello"))
        channel.send(reply, context)

        self.assertEqual(
            [("send_text", "room@@abc", "hello", ["wxid_alice"])],
            client.commands,
        )

    def test_client_builds_media_send_commands(self):
        client = CapturingClient()

        client.send_image("room@@abc", "D:/tmp/a.png")
        client.send_file("room@@abc", "D:/tmp/a.txt")
        client.send_audio("room@@abc", "D:/tmp/a.mp3")

        self.assertEqual(
            [
                {"type": "send_image", "room_id": "room@@abc", "path": "D:/tmp/a.png"},
                {"type": "send_file", "room_id": "room@@abc", "path": "D:/tmp/a.txt"},
                {"type": "send_audio", "room_id": "room@@abc", "path": "D:/tmp/a.mp3"},
            ],
            client.sent,
        )

    def test_send_voice_reply_uses_audio_command(self):
        client = FakeClient()
        channel = WechatGroupChannel(client=client)
        context = {
            "type": ContextType.TEXT,
            "receiver": "room@@abc",
            "msg": Mock(is_group=True, actual_user_id="wxid_alice"),
        }

        channel.send(Reply(ReplyType.VOICE, "D:/tmp/a.mp3"), context)

        self.assertEqual(
            [("send_audio", "room@@abc", "D:/tmp/a.mp3")],
            client.commands,
        )

    def test_non_at_message_without_free_reply_enabled_is_ignored(self):
        conf()["wechat_group_free_reply_enabled"] = False
        channel = WechatGroupChannel(client=FakeClient())
        channel.produce = Mock()
        channel.free_reply_worker = Mock()
        msg = Mock(
            ctype=ContextType.TEXT,
            content="谁能帮我总结一下刚才群里讨论的方案？",
            text="谁能帮我总结一下刚才群里讨论的方案？",
            other_user_id="room@@abc",
            other_user_nickname="测试群",
            actual_user_id="wxid_alice",
            actual_user_nickname="Alice",
            is_at=False,
        )

        channel.handle_text(msg)

        channel.produce.assert_not_called()
        channel.free_reply_worker.submit.assert_not_called()

    def test_non_at_message_logs_inbound_message_and_free_reply_decision(self):
        conf()["wechat_group_free_reply_enabled"] = False
        channel = WechatGroupChannel(client=FakeClient())
        channel.produce = Mock()
        channel.free_reply_worker = Mock()
        msg = Mock(
            ctype=ContextType.TEXT,
            content="Can someone summarize the plan from the group discussion?",
            text="Can someone summarize the plan from the group discussion?",
            message_type="text",
            other_user_id="room@@abc",
            other_user_nickname="Test Room",
            actual_user_id="wxid_alice",
            actual_user_nickname="Alice",
            is_at=False,
        )

        with self.assertLogs("log", level="INFO") as captured:
            channel.handle_text(msg)

        logs = "\n".join(captured.output)
        self.assertIn("[wechat_group] inbound:", logs)
        self.assertIn('room="Test Room"', logs)
        self.assertIn('sender="Alice"', logs)
        self.assertIn("Can someone summarize the plan", logs)
        self.assertIn("[wechat_group] free reply skipped:", logs)
        self.assertIn("score=", logs)
        self.assertIn("threshold=", logs)
        self.assertIn("suppressions=disabled", logs)

    def test_free_reply_scored_message_is_enqueued_not_produced_directly(self):
        conf()["wechat_group_room_ids"] = ["room@@abc"]
        conf()["wechat_group_free_reply_enabled"] = True
        conf()["wechat_group_free_reply_room_ids"] = ["room@@abc"]
        conf()["wechat_group_free_reply_activity_level"] = "normal"
        channel = WechatGroupChannel(client=FakeClient())
        channel.produce = Mock()
        channel.free_reply_worker = Mock()
        msg = Mock(
            ctype=ContextType.TEXT,
            content="谁能帮我总结一下刚才群里讨论的方案？",
            text="谁能帮我总结一下刚才群里讨论的方案？",
            other_user_id="room@@abc",
            other_user_nickname="测试群",
            actual_user_id="wxid_alice",
            actual_user_nickname="Alice",
            is_at=False,
        )

        channel.handle_text(msg)

        channel.free_reply_worker.submit.assert_called_once()
        channel.produce.assert_not_called()

    def test_at_message_does_not_enter_free_reply_worker(self):
        channel = WechatGroupChannel(client=FakeClient())
        channel.free_reply_worker = Mock()
        channel.produce = Mock()
        channel._compose_context = Mock(return_value={"receiver": "room@@abc", "msg": Mock()})
        msg = Mock(
            ctype=ContextType.TEXT,
            content="@CowBot hello",
            is_at=True,
        )

        channel.handle_text(msg)

        channel.free_reply_worker.submit.assert_not_called()
        channel.produce.assert_called_once()

    def test_quote_self_message_does_not_enter_free_reply_worker(self):
        channel = WechatGroupChannel(client=FakeClient())
        channel.free_reply_worker = Mock()
        channel.produce = Mock()
        channel._compose_context = Mock(return_value={"receiver": "room@@abc", "msg": Mock()})
        msg = Mock(
            ctype=ContextType.TEXT,
            content="What about this?",
            is_at=False,
            is_quote_self=True,
        )

        channel.handle_text(msg)

        channel.free_reply_worker.submit.assert_not_called()
        channel.produce.assert_called_once()

    def test_quote_self_message_with_refer_text_enters_reply_context(self):
        conf()["wechat_group_room_ids"] = ["room@@abc"]
        conf()["group_name_white_list"] = []
        channel = WechatGroupChannel(
            client=FakeClient(),
            memory_service=Mock(preview_prompt_memories_sync=Mock(return_value={})),
        )
        channel.produce = Mock()
        content = "「CowBot：previous answer」\n- - - - - - - - - - - - - - -\nWhat about this?"
        msg = Mock(
            ctype=ContextType.TEXT,
            content=content,
            text=content,
            from_user_id="room@@abc",
            other_user_id="room@@abc",
            other_user_nickname="Test Room",
            actual_user_id="wxid_alice",
            actual_user_nickname="Alice",
            to_user_id="@bot",
            to_user_nickname="CowBot",
            is_at=False,
            is_quote_self=True,
            is_group=True,
            at_list=[],
            self_display_name="CowBot",
            create_time=100000,
            msg_id="msg-quote-self",
            message_type="text",
            media_path="",
        )

        channel.handle_text(msg)

        channel.produce.assert_called_once()
        context = channel.produce.call_args.args[0]
        self.assertEqual("room@@abc", context["receiver"])
        self.assertTrue(context["wechat_group_quote_self_triggered"])

    def test_worker_approved_task_enters_reply_context(self):
        channel = WechatGroupChannel(client=FakeClient())
        channel.produce = Mock()
        msg = Mock(
            ctype=ContextType.TEXT,
            content="谁能总结一下？",
            other_user_id="room@@abc",
            other_user_nickname="测试群",
            actual_user_id="wxid_alice",
            actual_user_nickname="Alice",
            is_at=False,
        )
        channel._compose_context = Mock(return_value={"receiver": "room@@abc", "msg": msg})
        task = {"msg": msg, "local_decision": {"triggered": True, "score": 55}}

        channel._submit_free_reply_after_judge(task, {"approved": True, "confidence": 0.9})

        context = channel.produce.call_args.args[0]
        self.assertTrue(context["wechat_group_free_reply_triggered"])
        self.assertTrue(context["suppress_mention"])
        self.assertTrue(context["no_need_at"])

    def test_worker_approved_free_reply_bypasses_group_at_filter(self):
        conf()["wechat_group_room_ids"] = ["room@@abc"]
        conf()["wechat_group_free_reply_enabled"] = True
        conf()["wechat_group_free_reply_room_ids"] = ["room@@abc"]
        channel = WechatGroupChannel(client=FakeClient(), memory_service=Mock(preview_prompt_memories_sync=Mock(return_value={})))
        channel.produce = Mock()
        msg = Mock(
            ctype=ContextType.TEXT,
            content="哪里的用户名",
            text="哪里的用户名",
            from_user_id="room@@abc",
            other_user_id="room@@abc",
            other_user_nickname="测试群",
            actual_user_id="wxid_alice",
            actual_user_nickname="Alice",
            to_user_id="wxid_bot",
            to_user_nickname="CowBot",
            is_at=False,
            is_group=True,
            at_list=[],
            self_display_name="CowBot",
            create_time=100000,
            msg_id="msg-free-reply",
            message_type="text",
            media_path="",
        )
        task = {"msg": msg, "local_decision": {"triggered": True, "score": 55}}

        channel._submit_free_reply_after_judge(task, {"approved": True, "confidence": 0.9})

        channel.produce.assert_called_once()
        context = channel.produce.call_args.args[0]
        self.assertEqual("room@@abc", context["receiver"])
        self.assertEqual("room@@abc", context["session_id"])
        self.assertTrue(context.content.endswith("哪里的用户名"))
        self.assertTrue(context["wechat_group_free_reply_triggered"])

    def test_free_reply_does_not_mention_sender(self):
        mentions = WechatGroupChannel._build_reply_mentions({
            "suppress_mention": True,
            "msg": Mock(is_group=True, actual_user_id="wxid_alice"),
        })

        self.assertEqual([], mentions)

    def test_free_reply_status_returns_config_decision_and_worker_status(self):
        channel = WechatGroupChannel(client=FakeClient())
        channel.free_reply_worker = Mock(status=Mock(return_value={"running": False}))

        status = channel.free_reply_status()

        self.assertIn("config", status)
        self.assertIn("last_decision", status)
        self.assertIn("worker", status)

    def test_memory_service_uses_configured_embedding_provider(self):
        from agent.memory.config import MemoryConfig, get_default_memory_config, set_global_memory_config
        from unittest.mock import patch

        original_config = get_default_memory_config()
        provider = object()
        channel = WechatGroupChannel(client=FakeClient())

        with tempfile.TemporaryDirectory() as tmpdir:
            set_global_memory_config(MemoryConfig(workspace_root=tmpdir))
            with patch(
                "channel.wechat_group.wechat_group_memory.create_default_embedding_provider",
                return_value=provider,
                create=True,
            ):
                service = channel._get_memory_service()
            try:
                self.assertIs(service.memory_manager.embedding_provider, provider)
            finally:
                service.memory_manager.close()
                set_global_memory_config(original_config)


if __name__ == "__main__":
    unittest.main()
