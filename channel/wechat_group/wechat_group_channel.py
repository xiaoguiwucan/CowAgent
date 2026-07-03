"""WeChat group channel backed by a Node.js Wechaty sidecar."""

import re
import time
from types import SimpleNamespace

from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
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


def _wechat_group_log_preview(text, limit=120) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(value) <= limit:
        return value
    return "{}...(+{} chars)".format(value[:limit], len(value) - limit)


def _wechat_group_log_value(value) -> str:
    if value is None:
        return ""
    if "unittest.mock" in type(value).__module__:
        return ""
    return str(value)


def _free_reply_rule_label_map() -> dict:
    labels = {}
    for group in (get_wechat_group_free_reply_rules() or {}).values():
        for rule in group or []:
            rule_id = str(rule.get("id") or "")
            if rule_id:
                labels[rule_id] = str(rule.get("label") or rule_id)
    return labels


def _format_free_reply_items(items) -> str:
    values = [str(item) for item in (items or []) if str(item)]
    if not values:
        return "-"
    labels = _free_reply_rule_label_map()
    return ", ".join(
        "{}({})".format(item, labels[item]) if labels.get(item) else item
        for item in values
    )


def _looks_like_image_understanding_request(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return bool(re.search(r"(识别|看看|看下|看一下|分析|描述|总结|解释).{0,20}(图|图片|照片|截图|这张|这个)|这张(图|图片|照片|截图)|图里|图上|图片里|图片上", value))


def _is_archived_image_message(item) -> bool:
    return bool(
        item
        and str(item.get("message_type") or "").lower() == "image"
        and str(item.get("media_path") or "").strip()
    )


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
        self._image_understanding_cache = None
        self._image_understanding_cache_seconds = 0
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
        self._log_inbound_message(msg)
        direct_reply = getattr(msg, "is_at", False) is True or getattr(msg, "is_quote_self", False) is True
        if msg.ctype == ContextType.IMAGE:
            if not direct_reply:
                return
            content = self._build_image_understanding_content(msg)
            if not content:
                return
            context = self._compose_context(
                ContextType.TEXT,
                content,
                isgroup=True,
                msg=msg,
                wechat_group_force_reply=True,
            )
            if context:
                context["wechat_group_image_understanding_triggered"] = True
                self.produce(context)
            return
        if msg.ctype == ContextType.TEXT and not direct_reply:
            should_enqueue, decision = self._should_enqueue_free_reply_message(msg)
            if not should_enqueue:
                return
            self._ensure_free_reply_worker_started()
            submitted = self.free_reply_worker.submit(self._build_free_reply_task(msg, decision))
            if submitted:
                self.free_reply_state.mark_triggered(msg.other_user_id, now=decision.get("timestamp"))
                self._log_free_reply_decision(decision, "queued")
            else:
                self._log_free_reply_decision(decision, "queue_full")
            return
        if msg.ctype == ContextType.TEXT and direct_reply:
            image_content = self._build_recent_image_understanding_content(msg)
            if image_content:
                context = self._compose_context(
                    ContextType.TEXT,
                    image_content,
                    isgroup=True,
                    msg=msg,
                    wechat_group_force_reply=True,
                )
                if context:
                    context["wechat_group_image_understanding_triggered"] = True
                    self.produce(context)
                return
        force_reply = getattr(msg, "is_quote_self", False) is True
        context = self._compose_context(
            msg.ctype,
            msg.content,
            isgroup=True,
            msg=msg,
            wechat_group_force_reply=force_reply,
        )
        if context:
            if force_reply:
                context["wechat_group_quote_self_triggered"] = True
            self.produce(context)

    def _build_recent_image_understanding_content(self, msg: WechatGroupMessage) -> str:
        text = (getattr(msg, "text", "") or getattr(msg, "content", "") or "").strip()
        if not _looks_like_image_understanding_request(text):
            return ""
        quoted_image = self._find_quoted_image_message(msg)
        if quoted_image:
            return self._build_image_understanding_content(self._image_message_from_archive_item(quoted_image, text))
        try:
            recent_messages = self.archive.get_recent_messages(
                msg.other_user_id,
                limit=10,
                minutes=10,
                now=getattr(msg, "create_time", None),
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to load recent image for understanding: {}".format(e))
            return ""
        for item in reversed(recent_messages or []):
            if str(item.get("message_type") or "").lower() != "image":
                continue
            image_path = str(item.get("media_path") or "").strip()
            if not image_path:
                continue
            return self._build_image_understanding_content(self._image_message_from_archive_item(item, text))
        return ""

    def _find_quoted_image_message(self, msg: WechatGroupMessage):
        quote = getattr(msg, "quote", {}) or {}
        if not isinstance(quote, dict):
            return None
        quote_message_id = str(quote.get("message_id") or "").strip()
        if quote_message_id:
            getter = getattr(self.archive, "get_message_by_id", None)
            if getter:
                try:
                    item = getter(msg.other_user_id, quote_message_id)
                    if _is_archived_image_message(item):
                        return item
                except Exception as e:
                    logger.warning("[wechat_group] failed to load quoted image for understanding: {}".format(e))
        quote_sender_id = str(quote.get("sender_id") or "").strip()
        quote_sender_name = str(quote.get("sender_name") or "").strip()
        if not quote_sender_id and not quote_sender_name:
            return None
        try:
            recent_messages = self.archive.get_recent_messages(
                msg.other_user_id,
                limit=20,
                minutes=30,
                now=getattr(msg, "create_time", None),
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to load quoted sender image for understanding: {}".format(e))
            return None
        for item in reversed(recent_messages or []):
            if not _is_archived_image_message(item):
                continue
            sender_id = str(item.get("sender_id") or "").strip()
            sender_name = str(item.get("sender_nickname") or "").strip()
            if (quote_sender_id and sender_id == quote_sender_id) or (quote_sender_name and sender_name == quote_sender_name):
                return item
        return None

    @staticmethod
    def _image_message_from_archive_item(item: dict, text: str):
        image_path = str(item.get("media_path") or "").strip()
        return SimpleNamespace(
            media_path=image_path,
            content=image_path,
            text=text,
            actual_user_nickname=item.get("sender_nickname") or "",
            actual_user_id=item.get("sender_id") or "",
        )

    def _build_image_understanding_content(self, msg: WechatGroupMessage) -> str:
        if not conf().get("wechat_group_image_understanding_enabled", True):
            return ""
        if not getattr(msg, "text", "") and not conf().get("wechat_group_image_understanding_comment_enabled", True):
            return ""
        image_path = getattr(msg, "media_path", "") or getattr(msg, "content", "")
        if not image_path:
            return ""
        question = (
            conf().get("wechat_group_image_understanding_prompt")
            or "请简洁描述这张图片中的关键信息，并指出可能需要回复的内容。"
        )
        cache = self._get_image_understanding_cache()
        cache_key = "{}\n{}".format(image_path, question)
        summary = cache.get(cache_key, "")
        try:
            if not summary:
                from agent.tools.vision.vision import Vision

                result = Vision().execute({
                    "image": image_path,
                    "question": question,
                })
                if getattr(result, "status", "") == "success":
                    payload = getattr(result, "result", None)
                    if isinstance(payload, dict):
                        summary = str(payload.get("content") or "").strip()
                    else:
                        summary = str(payload or "").strip()
                    if summary:
                        cache[cache_key] = summary
                else:
                    summary = "图片理解失败：{}".format(getattr(result, "result", "") or "unknown error")
        except Exception as e:
            logger.warning("[wechat_group] image understanding failed: {}".format(e))
            summary = "图片理解失败：{}".format(e)
        if not summary:
            summary = "图片理解未返回内容。"
        sender = "{} ({})".format(
            getattr(msg, "actual_user_nickname", "") or "",
            getattr(msg, "actual_user_id", "") or "",
        ).strip()
        user_text = (getattr(msg, "text", "") or "").strip()
        fallback_text = "请根据这张图片作出简短回应。"
        return (
            "<wechat-group-image>\n"
            "图片文件: {image_path}\n"
            "发送者: {sender}\n"
            "视觉摘要: {summary}\n"
            "</wechat-group-image>\n\n"
            "{text}"
        ).format(
            image_path=image_path,
            sender=sender,
            summary=summary,
            text=user_text or fallback_text,
        )

    def _get_image_understanding_cache(self):
        try:
            minutes = int(conf().get("wechat_group_image_understanding_cache_minutes", 30))
        except Exception:
            minutes = 30
        seconds = max(60, min(minutes, 120) * 60)
        if self._image_understanding_cache is None or self._image_understanding_cache_seconds != seconds:
            self._image_understanding_cache = ExpiredDict(seconds)
            self._image_understanding_cache_seconds = seconds
        return self._image_understanding_cache

    def _generate_reply(self, context, reply=Reply()):
        if context and context.type == ContextType.IMAGE_CREATE:
            blocked = self._check_image_create_limit(context)
            if blocked:
                return blocked
            reply = super()._generate_reply(context, reply)
            if reply and reply.type in (ReplyType.IMAGE, ReplyType.IMAGE_URL):
                self._record_image_create_usage(context, "accepted")
            return reply
        return super()._generate_reply(context, reply)

    def _check_image_create_limit(self, context) -> Reply:
        try:
            limit = int(conf().get("wechat_group_image_create_hourly_limit", 5))
        except Exception:
            limit = 5
        room_id = context.get("receiver") or context.get("wechat_group_room_id") or ""
        if limit <= 0:
            return Reply(ReplyType.ERROR, "当前微信群生图额度已关闭，请在控制台调整生图额度。")
        try:
            used = self.archive.count_image_create_usage(room_id=room_id, window_seconds=3600)
        except Exception as e:
            logger.warning("[wechat_group] failed to count image create usage: {}".format(e))
            used = 0
        if used >= limit:
            return Reply(ReplyType.ERROR, "当前群本小时生图额度已用完（{}/{}），请稍后再试。".format(used, limit))
        return None

    def _record_image_create_usage(self, context, status: str):
        msg = context.get("msg")
        try:
            self.archive.record_image_create_usage(
                room_id=context.get("receiver") or context.get("wechat_group_room_id") or "",
                sender_id=getattr(msg, "actual_user_id", "") if msg else "",
                prompt=context.content or "",
                status=status,
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to record image create usage: {}".format(e))

    def _log_inbound_message(self, msg: WechatGroupMessage):
        try:
            text = _wechat_group_log_value(getattr(msg, "text", None)) or _wechat_group_log_value(getattr(msg, "content", ""))
            room_name = _wechat_group_log_value(getattr(msg, "other_user_nickname", "")) or _wechat_group_log_value(getattr(msg, "other_user_id", ""))
            sender_name = _wechat_group_log_value(getattr(msg, "actual_user_nickname", "")) or _wechat_group_log_value(getattr(msg, "actual_user_id", ""))
            message_type = _wechat_group_log_value(getattr(msg, "message_type", "")) or _wechat_group_log_value(getattr(msg, "ctype", ""))
            logger.info(
                '[wechat_group] inbound: room="{}" sender="{}" type={} is_at={} text="{}"'.format(
                    room_name,
                    sender_name,
                    message_type,
                    bool(getattr(msg, "is_at", False)),
                    _wechat_group_log_preview(text),
                )
            )
        except Exception as e:
            logger.debug("[wechat_group] inbound log skipped: {}".format(e))

    def _log_free_reply_decision(self, decision: dict, status: str):
        try:
            logger.info(
                '[wechat_group] free reply {}: room="{}" sender="{}" score={} threshold={} level={} '
                'reasons={} suppressions={} text="{}"'.format(
                    status,
                    decision.get("room_name") or decision.get("room_id", ""),
                    decision.get("sender_name") or decision.get("sender_id", ""),
                    decision.get("score", 0),
                    decision.get("threshold", 0),
                    decision.get("activity_level", ""),
                    _format_free_reply_items(decision.get("reasons")),
                    _format_free_reply_items(decision.get("suppressions")),
                    _wechat_group_log_preview(decision.get("text_preview", "")),
                )
            )
        except Exception as e:
            logger.debug("[wechat_group] free reply decision log skipped: {}".format(e))

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
            recent_messages = []
            try:
                recent_messages = self.archive.get_recent_messages(
                    msg.other_user_id,
                    limit=18,
                    minutes=120,
                    now=getattr(msg, "create_time", None),
                )
            except Exception as e:
                logger.debug("[wechat_group] failed to load free reply recent messages: {}".format(e))
            decision = evaluate_wechat_group_free_reply(
                cfg,
                room_id=msg.other_user_id,
                room_name=msg.other_user_nickname,
                sender_id=msg.actual_user_id,
                sender_name=msg.actual_user_nickname,
                text=getattr(msg, "text", None) or msg.content,
                recent_messages=recent_messages,
                state=state,
                now=time.time(),
                is_self=getattr(msg, "my_msg", False) is True,
                blocked_sender_ids=conf().get("wechat_group_blocked_sender_ids", []) or [],
                bot_names=[getattr(msg, "self_display_name", ""), getattr(msg, "to_user_nickname", ""), self.name],
                message_type=getattr(msg, "message_type", None),
            )
        self.free_reply_state.remember_decision(decision)
        if not decision.get("triggered"):
            self._log_free_reply_decision(decision, "skipped")
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
        context = self._compose_context(
            msg.ctype,
            msg.content,
            isgroup=True,
            msg=msg,
            wechat_group_force_reply=True,
        )
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
