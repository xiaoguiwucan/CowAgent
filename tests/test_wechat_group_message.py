import time
import unittest

from bridge.context import ContextType
from channel.wechat_group.wechat_group_message import WechatGroupMessage
from channel.wechat_group.protocol import SidecarEventType, parse_sidecar_event


class WechatGroupMessageTest(unittest.TestCase):
    def test_parse_message_event_to_group_chat_message(self):
        raw = {
            "type": SidecarEventType.MESSAGE,
            "message_id": "msg-1",
            "timestamp": 1710000000,
            "room_id": "room@@abc",
            "room_name": "测试群",
            "sender_id": "wxid_alice",
            "sender_name": "Alice",
            "self_id": "wxid_bot",
            "self_name": "CowBot",
            "text": "@CowBot hello",
            "is_at": True,
            "at_list": ["wxid_bot"],
            "message_type": "text",
        }

        msg = WechatGroupMessage(parse_sidecar_event(raw))

        self.assertEqual("msg-1", msg.msg_id)
        self.assertEqual(ContextType.TEXT, msg.ctype)
        self.assertEqual("@CowBot hello", msg.content)
        self.assertTrue(msg.is_group)
        self.assertTrue(msg.is_at)
        self.assertEqual("room@@abc", msg.from_user_id)
        self.assertEqual("测试群", msg.from_user_nickname)
        self.assertEqual("wxid_bot", msg.to_user_id)
        self.assertEqual("CowBot", msg.to_user_nickname)
        self.assertEqual("room@@abc", msg.other_user_id)
        self.assertEqual("测试群", msg.other_user_nickname)
        self.assertEqual("wxid_alice", msg.actual_user_id)
        self.assertEqual("Alice", msg.actual_user_nickname)
        self.assertEqual(["wxid_bot"], msg.at_list)
        self.assertFalse(msg.my_msg)

    def test_parse_self_message_marks_my_msg(self):
        raw = {
            "type": "message",
            "message_id": "msg-2",
            "timestamp": int(time.time()),
            "room_id": "room@@abc",
            "room_name": "测试群",
            "sender_id": "wxid_bot",
            "sender_name": "CowBot",
            "self_id": "wxid_bot",
            "self_name": "CowBot",
            "text": "self message",
            "message_type": "text",
        }

        msg = WechatGroupMessage(parse_sidecar_event(raw))

        self.assertTrue(msg.my_msg)
        self.assertFalse(msg.is_at)

    def test_parse_quote_self_message_metadata(self):
        raw = {
            "type": "message",
            "message_id": "msg-quote",
            "timestamp": int(time.time()),
            "room_id": "room@@abc",
            "room_name": "Test Room",
            "sender_id": "wxid_alice",
            "sender_name": "Alice",
            "self_id": "@bot",
            "self_name": "CowBot",
            "text": "What about this?",
            "message_type": "text",
            "is_quote_self": True,
            "quote": {
                "sender_id": "@bot",
                "sender_name": "CowBot",
                "message_id": "123456",
                "type": "1",
                "content": "previous answer",
            },
        }

        msg = WechatGroupMessage(parse_sidecar_event(raw))

        self.assertTrue(msg.is_quote_self)
        self.assertEqual("@bot", msg.quote["sender_id"])
        self.assertEqual("previous answer", msg.quote["content"])


if __name__ == "__main__":
    unittest.main()
