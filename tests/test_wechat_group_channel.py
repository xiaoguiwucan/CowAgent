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


if __name__ == "__main__":
    unittest.main()
