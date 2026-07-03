"""WeChat group channel backed by a Node.js Wechaty sidecar."""

import time

from bridge.context import ContextType
from bridge.reply import ReplyType
from channel.chat_channel import ChatChannel
from channel.wechat_group.protocol import SidecarEvent, SidecarEventType
from channel.wechat_group.wechat_group_archive import WechatGroupArchive
from channel.wechat_group.wechat_group_client import WechatGroupClient
from channel.wechat_group.wechat_group_context import build_wechat_group_recent_context_block
from channel.wechat_group.wechat_group_memory import (
    WechatGroupMemoryService,
    create_wechat_group_memory_service,
)
from channel.wechat_group.wechat_group_message import WechatGroupMessage
from channel.wechat_group.wechat_group_persona import (
    build_wechat_group_persona_block,
    get_wechat_group_persona_config,
    should_skip_persona_for_message,
)
from channel.wechat_group.wechat_group_free_reply import (
    WechatGroupFreeReplyStateStore,
    evaluate_wechat_group_free_reply,
    get_wechat_group_free_reply_config,
    get_wechat_group_free_reply_rules,
)
from channel.wechat_group.wechat_group_free_reply_judge import WechatGroupFreeReplyJudge
from channel.wechat_group.wechat_group_free_reply_worker import WechatGroupFreeReplyWorkerPool
from common import const
from common.expired_dict import ExpiredDict
from common.log import logger
from config import conf
from agent.protocol.agent_stream import looks_like_scheduler_request


class WechatGroupChannel(ChatChannel):
    channel_type = const.WECHAT_GROUP
    NOT_SUPPORT_REPLYTYPE = []

    STATUS_IDLE = "idle"
    STATUS_STARTING = "starting"
    STATUS_QR_READY = "qr_ready"
    STATUS_LOGGED_IN = "logged_in"
    STATUS_CONNECTED = "connected"
    STATUS_ERROR = "error"

    def __init__(self, client=None, archive=None, memory_service=None):
        super().__init__()
        self.client = client or WechatGroupClient(event_handler=self.consume_sidecar_event)
        if hasattr(self.client, "event_handler"):
            self.client.event_handler = self.consume_sidecar_event
        self.archive = archive or WechatGroupArchive()
        self.memory_service = memory_service
        self.status = self.STATUS_IDLE
        self.qr_code = ""
        self.rooms = []
        self._received_msgs = ExpiredDict(60 * 60 * 8)
        self.free_reply_state = WechatGroupFreeReplyStateStore()
        self.free_reply_judge = WechatGroupFreeReplyJudge()
        self.free_reply_worker = self._create_free_reply_worker()
        self._free_reply_worker_started = False
        if get_wechat_group_free_reply_config()["enabled"]:
            self._ensure_free_reply_worker_started()

    def startup(self):
        self.status = self.STATUS_STARTING
        self.client.start()
        self.report_startup_success()

    def stop(self):
        self.free_reply_worker.stop()
        self._free_reply_worker_started = False
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
        self._record_inbound_message(msg)
        self.handle_text(msg)
        return True

    def handle_text(self, msg: WechatGroupMessage):
        if msg.ctype == ContextType.TEXT and not getattr(msg, "is_at", False):
            should_enqueue, decision = self._should_enqueue_free_reply_message(msg)
            if not should_enqueue:
                return
            self._ensure_free_reply_worker_started()
            submitted = self.free_reply_worker.submit(self._build_free_reply_task(msg, decision))
            if submitted:
                self.free_reply_state.mark_triggered(msg.other_user_id, now=decision.get("timestamp"))
            return
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
        context["wechat_group_room_id"] = msg.other_user_id
        context["wechat_group_sender_id"] = msg.actual_user_id
        context["wechat_group_bot_sender_id"] = msg.to_user_id
        if looks_like_scheduler_request(context.content):
            context["intent_requires_scheduler"] = True
        self._record_inbound_message(msg)
        blocks = []
        if should_skip_persona_for_message(msg):
            context["wechat_group_persona_skipped"] = True
        else:
            persona = get_wechat_group_persona_config()
            block = build_wechat_group_persona_block(persona["prompt"])
            if block:
                context["wechat_group_persona_preset_id"] = persona["preset_id"]
                blocks.append(block)
        recent_block = self._build_recent_context_block(msg)
        if recent_block:
            blocks.append(recent_block)
            context["wechat_group_recent_context_injected"] = True
        memory_block = self._build_memory_context_block(msg, context.content)
        if memory_block:
            blocks.append(memory_block)
            context["wechat_group_memory_injected"] = True
        if blocks:
            context.content = "{}\n\n{}".format("\n\n".join(blocks), context.content).strip()
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
        if reply.type in (ReplyType.TEXT, ReplyType.INFO, ReplyType.ERROR):
            mention_ids = self._build_reply_mentions(context)
            self.client.send_text(receiver, reply.content, mention_ids=mention_ids)
            self._record_assistant_reply(context, reply, mention_ids)
        elif reply.type in (ReplyType.IMAGE, ReplyType.IMAGE_URL):
            self.client.send_image(receiver, reply.content)
            self._record_assistant_reply(context, reply, [])
        elif reply.type == ReplyType.VOICE:
            self.client.send_audio(receiver, reply.content)
            self._record_assistant_reply(context, reply, [])
        elif reply.type in (ReplyType.FILE, ReplyType.VIDEO):
            self.client.send_file(receiver, reply.content)
            self._record_assistant_reply(context, reply, [])
        else:
            logger.warning("[wechat_group] unsupported reply type: {}".format(reply.type))

    def _record_inbound_message(self, msg: WechatGroupMessage):
        if not conf().get("wechat_group_record_messages", True):
            return
        try:
            self.archive.record_message(
                message_id=msg.msg_id,
                room_id=msg.other_user_id,
                room_name=msg.other_user_nickname,
                sender_id=msg.actual_user_id,
                sender_nickname=msg.actual_user_nickname,
                message_type=msg.message_type,
                text=msg.text,
                media_path=msg.media_path,
                is_at=msg.is_at,
                created_at=msg.create_time,
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to archive inbound message: {}".format(e))

    def _record_assistant_reply(self, context, reply, mention_ids):
        if not conf().get("wechat_group_record_messages", True):
            return
        msg = context.get("msg")
        try:
            self.archive.record_assistant_reply(
                room_id=context.get("receiver") or "",
                room_name=getattr(msg, "other_user_nickname", "") if msg else "",
                reply_type=str(reply.type),
                content=reply.content,
                mention_ids=mention_ids,
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to archive assistant reply: {}".format(e))

    def _build_recent_context_block(self, msg: WechatGroupMessage) -> str:
        if not conf().get("wechat_group_recent_context_enabled", True):
            return ""
        try:
            return build_wechat_group_recent_context_block(
                self.archive,
                msg.other_user_id,
                limit=conf().get("wechat_group_recent_context_limit", 20),
                minutes=conf().get("wechat_group_recent_context_minutes", 60),
                now=msg.create_time,
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to build recent context: {}".format(e))
            return ""

    def _build_memory_context_block(self, msg: WechatGroupMessage, query: str) -> str:
        if not conf().get("wechat_group_memory_enabled", True) and not conf().get("wechat_group_member_memory_enabled", True):
            return ""
        try:
            service = self._get_memory_service()
            preview = service.preview_prompt_memories_sync(
                room_id=msg.other_user_id,
                sender_id=msg.actual_user_id,
                query=query,
                mentioned_sender_ids=getattr(msg, "at_list", []) or [],
                bot_sender_id=msg.to_user_id,
            )
            return (preview or {}).get("content") or ""
        except Exception as e:
            logger.warning("[wechat_group] failed to build memory context: {}".format(e))
            return ""

    def _get_memory_service(self):
        if self.memory_service is None:
            self.memory_service = create_wechat_group_memory_service()
        return self.memory_service

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
        if context.get("suppress_mention"):
            return []
        msg = context.get("msg")
        if not msg or not getattr(msg, "is_group", False):
            return []
        actual_user_id = getattr(msg, "actual_user_id", None)
        return [actual_user_id] if actual_user_id else []

    def _create_free_reply_worker(self):
        cfg = get_wechat_group_free_reply_config()
        return WechatGroupFreeReplyWorkerPool(
            judge=self.free_reply_judge,
            submit_callback=self._submit_free_reply_after_judge,
            max_workers=cfg["worker_max_workers"],
            queue_size=cfg["worker_queue_size"],
            ttl_seconds=cfg["queue_ttl_seconds"],
        )

    def _ensure_free_reply_worker_started(self):
        if self._free_reply_worker_started:
            return
        self.free_reply_worker.start()
        self._free_reply_worker_started = True

    def _should_enqueue_free_reply_message(self, msg: WechatGroupMessage):
        cfg = get_wechat_group_free_reply_config()
        if not self._is_selected_room(msg):
            decision = {
                "triggered": False,
                "score": 0,
                "threshold": 0,
                "activity_level": cfg["activity_level"],
                "reasons": [],
                "suppressions": ["room_not_selected"],
                "room_id": getattr(msg, "other_user_id", ""),
                "room_name": getattr(msg, "other_user_nickname", ""),
                "sender_id": getattr(msg, "actual_user_id", ""),
                "sender_name": getattr(msg, "actual_user_nickname", ""),
                "text_preview": getattr(msg, "text", "") or getattr(msg, "content", ""),
                "timestamp": time.time(),
            }
        else:
            state = self.free_reply_state.get(msg.other_user_id)
            decision = evaluate_wechat_group_free_reply(
                cfg,
                room_id=msg.other_user_id,
                room_name=msg.other_user_nickname,
                sender_id=msg.actual_user_id,
                sender_name=msg.actual_user_nickname,
                text=getattr(msg, "text", None) or msg.content,
                state=state,
                now=time.time(),
                is_self=getattr(msg, "my_msg", False) is True,
                blocked_sender_ids=conf().get("wechat_group_blocked_sender_ids", []) or [],
                bot_names=[getattr(msg, "self_display_name", ""), getattr(msg, "to_user_nickname", ""), self.name],
            )
        self.free_reply_state.remember_decision(decision)
        if not decision.get("triggered"):
            self.free_reply_state.mark_observed(getattr(msg, "other_user_id", ""))
            return False, decision
        return True, decision

    def _build_free_reply_task(self, msg: WechatGroupMessage, decision: dict) -> dict:
        return {
            "room_id": msg.other_user_id,
            "room_name": msg.other_user_nickname,
            "sender_id": msg.actual_user_id,
            "sender_name": msg.actual_user_nickname,
            "text": getattr(msg, "text", None) or msg.content,
            "msg": msg,
            "local_decision": decision,
            "queued_at": time.time(),
            "config": get_wechat_group_free_reply_config(),
        }

    def _submit_free_reply_after_judge(self, task, llm_decision):
        msg = task["msg"]
        context = self._compose_context(msg.ctype, msg.content, isgroup=True, msg=msg)
        if not context:
            return
        context["wechat_group_free_reply_triggered"] = True
        context["wechat_group_free_reply_decision"] = task.get("local_decision") or {}
        context["wechat_group_free_reply_llm_decision"] = llm_decision or {}
        context["suppress_mention"] = True
        context["no_need_at"] = True
        self.produce(context)

    def free_reply_status(self):
        cfg = get_wechat_group_free_reply_config()
        return {
            "config": cfg,
            "rules": get_wechat_group_free_reply_rules(),
            "last_decision": self.free_reply_state.last_decision(),
            "worker": self.free_reply_worker.status(),
        }
