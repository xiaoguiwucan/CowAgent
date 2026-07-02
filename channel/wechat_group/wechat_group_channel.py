"""WeChat group channel backed by a Node.js Wechaty sidecar."""

from bridge.context import ContextType
from bridge.reply import ReplyType
from channel.chat_channel import ChatChannel
from channel.wechat_group.protocol import SidecarEvent, SidecarEventType
from channel.wechat_group.wechat_group_client import WechatGroupClient
from channel.wechat_group.wechat_group_message import WechatGroupMessage
from channel.wechat_group.wechat_group_persona import (
    build_wechat_group_persona_block,
    get_wechat_group_persona_config,
    should_skip_persona_for_message,
)
from common import const
from common.expired_dict import ExpiredDict
from common.log import logger
from config import conf


class WechatGroupChannel(ChatChannel):
    channel_type = const.WECHAT_GROUP
    NOT_SUPPORT_REPLYTYPE = []

    STATUS_IDLE = "idle"
    STATUS_STARTING = "starting"
    STATUS_QR_READY = "qr_ready"
    STATUS_LOGGED_IN = "logged_in"
    STATUS_CONNECTED = "connected"
    STATUS_ERROR = "error"

    def __init__(self, client=None):
        super().__init__()
        self.client = client or WechatGroupClient(event_handler=self.consume_sidecar_event)
        if hasattr(self.client, "event_handler"):
            self.client.event_handler = self.consume_sidecar_event
        self.status = self.STATUS_IDLE
        self.qr_code = ""
        self.rooms = []
        self._received_msgs = ExpiredDict(60 * 60 * 8)

    def startup(self):
        self.status = self.STATUS_STARTING
        self.client.start()
        self.report_startup_success()

    def stop(self):
        self.client.stop()
        self.status = self.STATUS_IDLE

    def refresh_rooms(self):
        self.client.list_rooms()

    def consume_sidecar_event(self, event: SidecarEvent) -> bool:
        if event.type == SidecarEventType.MESSAGE:
            return self._consume_message(event)
        if event.type == SidecarEventType.QR:
            self.status = self.STATUS_QR_READY
            self.qr_code = event.get("qrcode") or event.get("url") or ""
            qr_url = event.get("url") or self.qr_code
            logger.info("[wechat_group] QR ready, scan URL: {}".format(qr_url))
            return True
        if event.type == SidecarEventType.STATUS:
            self.status = event.get("status") or self.status
            self.name = event.get("self_name") or self.name
            self.user_id = event.get("self_id") or self.user_id
            return True
        if event.type == SidecarEventType.ROOMS:
            self.rooms = event.get("rooms", [])
            return True
        if event.type == SidecarEventType.ERROR:
            self.status = self.STATUS_ERROR
            logger.error("[wechat_group] sidecar error: {}".format(event.payload))
            return True
        return False

    def _consume_message(self, event: SidecarEvent) -> bool:
        msg = WechatGroupMessage(event)
        if not msg.msg_id:
            logger.warning("[wechat_group] message missing id, skipped")
            return False
        if msg.msg_id in self._received_msgs:
            logger.debug("[wechat_group] duplicate message skipped: {}".format(msg.msg_id))
            return False
        self._received_msgs[msg.msg_id] = True
        if msg.my_msg:
            logger.debug("[wechat_group] self message skipped: {}".format(msg.msg_id))
            return False
        if not self._is_selected_room(msg):
            logger.debug("[wechat_group] unselected room skipped: {}".format(msg.other_user_id))
            return False
        self.handle_text(msg)
        return True

    def handle_text(self, msg: WechatGroupMessage):
        context = self._compose_context(
            msg.ctype,
            msg.content,
            isgroup=True,
            msg=msg,
        )
        if context:
            self.produce(context)

    def _compose_context(self, ctype, content, **kwargs):
        context = super()._compose_context(ctype, content, **kwargs)
        if not context or context.type != ContextType.TEXT:
            return context
        msg = context.get("msg")
        if not msg or not getattr(msg, "is_group", False):
            return context
        if should_skip_persona_for_message(msg):
            context["wechat_group_persona_skipped"] = True
            return context
        persona = get_wechat_group_persona_config()
        block = build_wechat_group_persona_block(persona["prompt"])
        if not block:
            return context
        context["wechat_group_persona_preset_id"] = persona["preset_id"]
        context.content = "{}\n\n{}".format(block, context.content).strip()
        return context

    def _decorate_reply(self, context, reply):
        if context.get("isgroup", False):
            context["no_need_at"] = True
        return super()._decorate_reply(context, reply)

    def send(self, reply, context):
        receiver = context.get("receiver")
        if not receiver:
            logger.warning("[wechat_group] missing receiver, skip send")
            return
        if reply.type == ReplyType.TEXT:
            mention_ids = self._build_reply_mentions(context)
            self.client.send_text(receiver, reply.content, mention_ids=mention_ids)
        elif reply.type in (ReplyType.IMAGE, ReplyType.IMAGE_URL):
            self.client.send_image(receiver, reply.content)
        elif reply.type == ReplyType.VOICE:
            self.client.send_audio(receiver, reply.content)
        elif reply.type in (ReplyType.FILE, ReplyType.VIDEO):
            self.client.send_file(receiver, reply.content)
        else:
            logger.warning("[wechat_group] unsupported reply type: {}".format(reply.type))

    @staticmethod
    def _is_selected_room(msg: WechatGroupMessage) -> bool:
        room_ids = conf().get("wechat_group_room_ids", [])
        if room_ids and msg.other_user_id not in room_ids:
            return False
        room_names = conf().get("wechat_group_names", [])
        if not room_ids and room_names and msg.other_user_nickname not in room_names:
            return False
        return True

    @staticmethod
    def _build_reply_mentions(context):
        msg = context.get("msg")
        if not msg or not getattr(msg, "is_group", False):
            return []
        actual_user_id = getattr(msg, "actual_user_id", None)
        return [actual_user_id] if actual_user_id else []
