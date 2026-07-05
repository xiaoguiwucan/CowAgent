"""Wechaty sidecar message adapter for CowAgent group chat."""

import time

from bridge.context import ContextType
from channel.chat_message import ChatMessage
from channel.wechat_group.protocol import SidecarEvent


_MESSAGE_TYPE_TO_CONTEXT = {
    "text": ContextType.TEXT,
    "image": ContextType.IMAGE,
    "sticker": ContextType.IMAGE,
    "voice": ContextType.VOICE,
    "audio": ContextType.VOICE,
    "file": ContextType.FILE,
    "video": ContextType.FILE,
}


class WechatGroupMessage(ChatMessage):
    def __init__(self, event: SidecarEvent):
        super().__init__(event.payload)
        payload = event.payload

        message_type = payload.get("message_type") or "text"
        self.message_type = message_type
        self.msg_id = payload.get("message_id") or payload.get("id")
        self.create_time = payload.get("timestamp") or int(time.time())
        self.ctype = _MESSAGE_TYPE_TO_CONTEXT.get(message_type, ContextType.TEXT)
        self.text = payload.get("text") or ""
        self.media_path = payload.get("file_path") or ""
        self.content = self.media_path or self.text

        room_id = payload.get("room_id") or ""
        room_name = payload.get("room_name") or room_id
        self_id = payload.get("self_id") or ""
        self_name = payload.get("self_name") or self_id
        sender_id = payload.get("sender_id") or ""
        sender_name = payload.get("sender_name") or sender_id

        self.from_user_id = room_id
        self.from_user_nickname = room_name
        self.to_user_id = self_id
        self.to_user_nickname = self_name
        self.other_user_id = room_id
        self.other_user_nickname = room_name
        self.actual_user_id = sender_id
        self.actual_user_nickname = sender_name
        self.self_display_name = payload.get("self_display_name") or self_name

        self.is_group = True
        self.is_at = bool(payload.get("is_at", False))
        self.at_list = payload.get("at_list") or []
        self.is_quote_self = bool(payload.get("is_quote_self", False))
        quote = payload.get("quote") or {}
        self.quote = quote if isinstance(quote, dict) else {}
        forward = payload.get("forward") or {}
        self.forward = forward if isinstance(forward, dict) else {}
        self.raw_app_type = str(payload.get("raw_app_type") or "").strip()
        self.my_msg = bool(payload.get("my_msg", False) or (sender_id and sender_id == self_id))
