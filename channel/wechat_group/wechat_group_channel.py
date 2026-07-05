"""WeChat group channel backed by a Node.js Wechaty sidecar."""

import re
import time
from pathlib import Path
from types import SimpleNamespace

from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import ChatChannel
from channel.wechat_group.protocol import SidecarEvent, SidecarEventType
from channel.wechat_group.wechat_group_archive import WechatGroupArchive
from channel.wechat_group.wechat_group_client import WechatGroupClient
from channel.wechat_group.wechat_group_context import build_wechat_group_recent_context_block
from channel.wechat_group.wechat_group_context_service import WechatGroupContextService
from channel.wechat_group.wechat_group_emotion_service import WechatGroupEmotionService
from channel.wechat_group.wechat_group_message import WechatGroupMessage
from channel.wechat_group.wechat_group_persona import (
    build_wechat_group_persona_block,
    get_wechat_group_persona_config,
    should_skip_persona_for_message,
)
from channel.wechat_group.wechat_group_style_service import WechatGroupStyleService
from channel.wechat_group.wechat_group_sticker_service import WechatGroupStickerService
from channel.wechat_group.wechat_group_topic_service import WechatGroupTopicService
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
    return bool(re.search(r"(识别|看看|看下|看一下|分析|描述|总结|解释).{0,20}(图|图片|照片|截图|这张|这个)|这张(图|图片|照片|截图)|图里|图上|图片里|图片上|啥意思|什么意思", value))


def _is_archived_image_message(item) -> bool:
    return bool(
        item
        and str(item.get("message_type") or "").lower() == "image"
        and str(item.get("media_path") or "").strip()
    )

def _normalize_quote_message_type(value) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("1", "text", "7"):
        return "text"
    if raw in ("3", "image"):
        return "image"
    if raw in ("43", "video"):
        return "video"
    if raw in ("49", "app", "link", "forward"):
        return "app"
    return raw


def _format_multimodal_sender(name, sender_id) -> str:
    display_name = str(name or "").strip()
    display_id = str(sender_id or "").strip()
    if display_name and display_id and display_name != display_id:
        return "{} ({})".format(display_name, display_id)
    return display_name or display_id


def _trim_multimodal_value(value, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return "{}...".format(text[: max(int(limit or 0) - 3, 0)])


class WechatGroupChannel(ChatChannel):
    channel_type = const.WECHAT_GROUP
    NOT_SUPPORT_REPLYTYPE = []

    STATUS_IDLE = "idle"
    STATUS_STARTING = "starting"
    STATUS_QR_READY = "qr_ready"
    STATUS_LOGGED_IN = "logged_in"
    STATUS_CONNECTED = "connected"
    STATUS_ERROR = "error"

    def __init__(
        self,
        client=None,
        archive=None,
        memory_service=None,
        topic_service=None,
        emotion_service=None,
        style_service=None,
        sticker_service=None,
    ):
        super().__init__()
        self.client = client or WechatGroupClient(event_handler=self.consume_sidecar_event)
        if hasattr(self.client, "event_handler"):
            self.client.event_handler = self.consume_sidecar_event
        self.archive = archive or WechatGroupArchive()
        self.memory_service = memory_service
        self.topic_service = topic_service
        self.emotion_service = emotion_service
        self.style_service = style_service
        self.sticker_service = sticker_service
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
        self._observe_emotion(msg)
        direct_reply = getattr(msg, "is_at", False) is True or getattr(msg, "is_quote_self", False) is True
        if msg.ctype == ContextType.IMAGE:
            if not direct_reply:
                if not conf().get("wechat_group_free_reply_image_understanding_enabled", False):
                    return
                image_text = self._build_free_reply_image_text(msg)
                should_enqueue, decision = self._should_enqueue_free_reply_message(
                    msg,
                    allow_media_payload=True,
                    text_override=image_text,
                )
                if not should_enqueue:
                    return
                self._ensure_free_reply_worker_started()
                submitted = self.free_reply_worker.submit(
                    self._build_free_reply_task(msg, decision, text=image_text)
                )
                if submitted:
                    self.free_reply_state.mark_triggered(msg.other_user_id, now=decision.get("timestamp"))
                    self._log_free_reply_decision(decision, "queued")
                else:
                    self._log_free_reply_decision(decision, "queue_full")
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
        if str(getattr(msg, "message_type", "") or "").lower() == "video" and direct_reply:
            content = self._build_video_understanding_request_content(msg)
            if content:
                context = self._compose_context(
                    ContextType.TEXT,
                    content,
                    isgroup=True,
                    msg=msg,
                    wechat_group_force_reply=True,
                )
                if context:
                    context["wechat_group_video_understanding_triggered"] = True
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
                    wechat_group_skip_multimodal_quote=True,
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

    def _build_image_understanding_content(self, msg: WechatGroupMessage, allow_image_only=False) -> str:
        if not conf().get("wechat_group_image_understanding_enabled", True):
            return ""
        if (
            not getattr(msg, "text", "")
            and not allow_image_only
            and not conf().get("wechat_group_image_understanding_comment_enabled", True)
        ):
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

    @staticmethod
    def _build_video_understanding_request_content(msg: WechatGroupMessage) -> str:
        if not conf().get("wechat_group_video_understanding_enabled", False):
            return ""
        video_path = str(getattr(msg, "media_path", "") or getattr(msg, "content", "") or "").strip()
        if not video_path:
            return ""
        user_text = str(getattr(msg, "text", "") or "").strip()
        return user_text or "请结合上面的多模态上下文理解这个视频并给出简短回复。"

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
        topic_block = self._build_topic_context_block(msg)
        if topic_block:
            blocks.append(topic_block)
            context["wechat_group_topic_injected"] = True
        memory_block = self._build_memory_context_block(msg, context.content)
        if memory_block:
            blocks.append(memory_block)
            context["wechat_group_memory_injected"] = True
        style_block = self._build_style_context_block(msg)
        if style_block:
            blocks.append(style_block)
            context["wechat_group_style_injected"] = True
        emotion_block = self._build_emotion_context_block(msg)
        if emotion_block:
            blocks.append(emotion_block)
            context["wechat_group_emotion_injected"] = True
        multimodal_block = self._build_multimodal_context_block(
            msg,
            include_quote=not context.get("wechat_group_skip_multimodal_quote", False),
        )
        if multimodal_block:
            blocks.append(multimodal_block)
            context["wechat_group_multimodal_injected"] = True
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
            self._simulate_typing_delay_if_needed(reply)
            mention_ids = self._build_reply_mentions(context)
            self.client.send_text(receiver, reply.content, mention_ids=mention_ids)
            self._record_assistant_reply(context, reply, mention_ids)
        elif reply.type in (ReplyType.IMAGE, ReplyType.IMAGE_URL):
            self.client.send_image(receiver, self._normalize_sidecar_media_path(reply.content))
            self._record_assistant_reply(context, reply, [])
        elif reply.type == ReplyType.VOICE:
            self.client.send_audio(receiver, self._normalize_sidecar_media_path(reply.content))
            self._record_assistant_reply(context, reply, [])
        elif reply.type in (ReplyType.FILE, ReplyType.VIDEO):
            self.client.send_file(receiver, self._normalize_sidecar_media_path(reply.content))
            self._record_assistant_reply(context, reply, [])
        else:
            logger.warning("[wechat_group] unsupported reply type: {}".format(reply.type))
            return
        self._record_emotion_reply(context)
        self._record_sticker_reply(reply, context)

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
                metadata={
                    "at_list": getattr(msg, "at_list", []) or [],
                    "quote": getattr(msg, "quote", {}) or {},
                    "forward": getattr(msg, "forward", {}) or {},
                    "raw_app_type": getattr(msg, "raw_app_type", "") or "",
                    "is_quote_self": bool(getattr(msg, "is_quote_self", False)),
                    "self_display_name": getattr(msg, "self_display_name", "") or "",
                },
                created_at=msg.create_time,
            )
            self._collect_sticker_from_message(msg)
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

    def _build_topic_context_block(self, msg: WechatGroupMessage) -> str:
        if not conf().get("wechat_group_topic_enabled", True):
            return ""
        try:
            return self._get_topic_service().build_prompt_block_from_archive(
                self.archive,
                msg.other_user_id,
                now=msg.create_time,
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to build topic context: {}".format(e))
            return ""

    def _build_memory_context_block(self, msg: WechatGroupMessage, query: str) -> str:
        knowledge_enabled = bool(conf().get(
            "wechat_group_knowledge_enabled",
            conf().get("wechat_group_memory_enabled", True),
        ))
        profile_enabled = bool(conf().get(
            "wechat_group_profile_enabled",
            conf().get("wechat_group_member_memory_enabled", True),
        ))
        if not knowledge_enabled and not profile_enabled:
            return ""
        try:
            service = self._get_memory_service()
            preview = service.preview_context(
                room_id=msg.other_user_id,
                sender_id=msg.actual_user_id,
                query=query,
                mentioned_sender_ids=getattr(msg, "at_list", []) or [],
                bot_sender_id=msg.to_user_id,
            )
            content = (preview or {}).get("content")
            return content if isinstance(content, str) else ""
        except Exception as e:
            logger.warning("[wechat_group] failed to build memory context: {}".format(e))
            return ""

    def _build_emotion_context_block(self, msg: WechatGroupMessage) -> str:
        if not conf().get("wechat_group_emotion_enabled", True):
            return ""
        try:
            return self._get_emotion_service().build_prompt_block(msg.other_user_id, now=msg.create_time)
        except Exception as e:
            logger.warning("[wechat_group] failed to build emotion context: {}".format(e))
            return ""

    def _build_style_context_block(self, msg: WechatGroupMessage) -> str:
        if not conf().get("wechat_group_style_enabled", True):
            return ""
        try:
            return self._get_style_service().build_prompt_block_from_archive(
                self.archive,
                msg.other_user_id,
                now=msg.create_time,
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to build style context: {}".format(e))
            return ""

    def _build_multimodal_context_block(self, msg: WechatGroupMessage, include_quote: bool = True) -> str:
        sections = []
        if include_quote:
            quote_section = self._build_quote_multimodal_section(msg)
            if quote_section:
                sections.append(quote_section)
        forward_section = self._build_forward_multimodal_section(msg)
        if forward_section:
            sections.append(forward_section)
        video_section = self._build_video_multimodal_section(msg)
        if video_section:
            sections.append(video_section)
        if not sections:
            return ""
        return "<wechat-group-multimodal>\n{}\n</wechat-group-multimodal>".format("\n\n".join(sections))

    def _build_quote_multimodal_section(self, msg: WechatGroupMessage) -> str:
        if not conf().get("wechat_group_quote_context_enabled", True):
            return ""
        quote = getattr(msg, "quote", {}) or {}
        if not isinstance(quote, dict) or not quote:
            return ""
        quoted_item = None
        quote_message_id = str(quote.get("message_id") or "").strip()
        if quote_message_id:
            getter = getattr(self.archive, "get_message_by_id", None)
            if getter:
                try:
                    quoted_item = getter(msg.other_user_id, quote_message_id)
                except Exception as e:
                    logger.debug("[wechat_group] failed to load quote context: {}".format(e))
        message_type = ""
        sender_id = ""
        sender_name = ""
        content = ""
        media_path = ""
        if quoted_item:
            message_type = str(quoted_item.get("message_type") or "").strip()
            sender_id = str(quoted_item.get("sender_id") or "").strip()
            sender_name = str(quoted_item.get("sender_nickname") or "").strip()
            content = str(quoted_item.get("text") or "").strip()
            media_path = str(quoted_item.get("media_path") or "").strip()
        else:
            message_type = _normalize_quote_message_type(quote.get("type"))
            sender_id = str(quote.get("sender_id") or "").strip()
            sender_name = str(quote.get("sender_name") or "").strip()
            content = str(quote.get("content") or "").strip()
        lines = ["[quoted_message]"]
        if quote_message_id:
            lines.append("message_id: {}".format(quote_message_id))
        sender = _format_multimodal_sender(sender_name, sender_id)
        if sender:
            lines.append("sender: {}".format(sender))
        if message_type:
            lines.append("message_type: {}".format(message_type))
        if content:
            lines.append("content: {}".format(_trim_multimodal_value(content, 320)))
        if media_path:
            lines.append("media_path: {}".format(media_path))
        return "\n".join(lines) if len(lines) > 1 else ""

    @staticmethod
    def _build_forward_multimodal_section(msg: WechatGroupMessage) -> str:
        if not conf().get("wechat_group_forward_preview_enabled", True):
            return ""
        forward = getattr(msg, "forward", {}) or {}
        if not isinstance(forward, dict) or not forward:
            return ""
        title = str(forward.get("title") or "").strip()
        description = str(forward.get("description") or "").strip()
        source = str(forward.get("source") or "").strip()
        record_item = str(forward.get("record_item") or "").strip()
        record_count = int(forward.get("record_count_hint") or 0)
        raw_app_type = str(getattr(msg, "raw_app_type", "") or "").strip()
        if not any([title, description, source, record_item, record_count, raw_app_type]):
            return ""
        lines = ["[forward_preview]"]
        if raw_app_type:
            lines.append("app_type: {}".format(raw_app_type))
        if title:
            lines.append("title: {}".format(_trim_multimodal_value(title, 160)))
        if description:
            lines.append("description: {}".format(_trim_multimodal_value(description, 320)))
        if source:
            lines.append("source: {}".format(_trim_multimodal_value(source, 120)))
        if record_count > 0:
            lines.append("record_count_hint: {}".format(record_count))
        if record_item and not description:
            lines.append("record_item: {}".format(_trim_multimodal_value(record_item, 320)))
        return "\n".join(lines)

    @staticmethod
    def _build_video_multimodal_section(msg: WechatGroupMessage) -> str:
        if not conf().get("wechat_group_video_understanding_enabled", False):
            return ""
        if str(getattr(msg, "message_type", "") or "").lower() != "video":
            return ""
        video_path = str(getattr(msg, "media_path", "") or getattr(msg, "content", "") or "").strip()
        if not video_path:
            return ""
        lines = ["[video_message]"]
        sender = _format_multimodal_sender(
            getattr(msg, "actual_user_nickname", ""),
            getattr(msg, "actual_user_id", ""),
        )
        if sender:
            lines.append("sender: {}".format(sender))
        lines.append("video_file: {}".format(video_path))
        text = str(getattr(msg, "text", "") or "").strip()
        if text:
            lines.append("caption: {}".format(_trim_multimodal_value(text, 200)))
        return "\n".join(lines)

    def _get_memory_service(self):
        if self.memory_service is None:
            self.memory_service = WechatGroupContextService()
            try:
                from agent.memory.manager import MemoryManager
                from agent.memory import create_default_embedding_provider

                self.memory_service.memory_manager = MemoryManager(
                    embedding_provider=create_default_embedding_provider()
                )
            except Exception:
                self.memory_service.memory_manager = None
        return self.memory_service

    def _get_topic_service(self):
        if self.topic_service is None:
            self.topic_service = WechatGroupTopicService()
        return self.topic_service

    def _get_emotion_service(self):
        if self.emotion_service is None:
            self.emotion_service = WechatGroupEmotionService()
        return self.emotion_service

    def _get_style_service(self):
        if self.style_service is None:
            self.style_service = WechatGroupStyleService()
        return self.style_service

    def _get_sticker_service(self):
        if self.sticker_service is None:
            self.sticker_service = WechatGroupStickerService()
        return self.sticker_service

    def _observe_emotion(self, msg: WechatGroupMessage):
        if not conf().get("wechat_group_emotion_enabled", True):
            return
        text = getattr(msg, "text", None) or getattr(msg, "content", "")
        if not str(text or "").strip():
            return
        try:
            self._get_emotion_service().observe_message(
                room_id=getattr(msg, "other_user_id", ""),
                text=text,
                is_at=bool(getattr(msg, "is_at", False)),
                now=getattr(msg, "create_time", None),
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to observe emotion: {}".format(e))

    def _record_emotion_reply(self, context):
        if not conf().get("wechat_group_emotion_enabled", True):
            return
        room_id = context.get("receiver") or context.get("wechat_group_room_id") or ""
        if not room_id:
            return
        msg = context.get("msg")
        try:
            self._get_emotion_service().mark_replied(
                room_id=room_id,
                now=getattr(msg, "create_time", None) if msg else None,
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to record emotion reply: {}".format(e))

    def _collect_sticker_from_message(self, msg: WechatGroupMessage):
        if not conf().get("wechat_group_sticker_enabled", True):
            return
        if not conf().get("wechat_group_sticker_auto_collect_enabled", True):
            return
        if str(getattr(msg, "message_type", "") or "").lower() != "sticker":
            return
        media_path = str(getattr(msg, "media_path", "") or "").strip()
        if not media_path:
            return
        try:
            description = getattr(msg, "text", "") or Path(media_path).stem
            self._get_sticker_service().collect_from_message(
                room_id=getattr(msg, "other_user_id", ""),
                media_path=media_path,
                source_message_id=getattr(msg, "msg_id", ""),
                description=description,
                now=getattr(msg, "create_time", None),
            )
        except Exception as e:
            logger.warning("[wechat_group] failed to collect sticker: {}".format(e))

    def _record_sticker_reply(self, reply, context):
        if not conf().get("wechat_group_sticker_enabled", True):
            return
        sticker_id = str(getattr(reply, "wechat_group_sticker_id", "") or "").strip()
        room_id = str(context.get("receiver") or context.get("wechat_group_room_id") or "").strip()
        if not sticker_id or not room_id:
            return
        try:
            self._get_sticker_service().record_sent(room_id, sticker_id)
        except Exception as e:
            logger.warning("[wechat_group] failed to record sticker reply: {}".format(e))

    @staticmethod
    def _normalize_sidecar_media_path(value):
        text = str(value or "").strip()
        if text.startswith("file://"):
            return text[7:]
        return text

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

    @staticmethod
    def _simulate_typing_delay_if_needed(reply):
        if not conf().get("wechat_group_free_reply_typing_delay_enabled", True):
            return
        content = str(getattr(reply, "content", "") or "")
        if not content:
            return
        try:
            chars_per_second = max(int(conf().get("wechat_group_free_reply_typing_chars_per_second", 7) or 7), 1)
        except Exception:
            chars_per_second = 7
        delay_seconds = min(len(content) / float(chars_per_second), 8.0)
        if delay_seconds > 0:
            time.sleep(delay_seconds)

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

    @staticmethod
    def _build_free_reply_image_text(msg: WechatGroupMessage) -> str:
        image_path = getattr(msg, "media_path", "") or getattr(msg, "content", "")
        return "[图片] {}".format(image_path).strip()

    def _should_enqueue_free_reply_message(self, msg: WechatGroupMessage, allow_media_payload=False, text_override=None):
        cfg = get_wechat_group_free_reply_config()
        text = text_override if text_override is not None else (getattr(msg, "text", None) or msg.content)
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
                "text_preview": text,
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
                text=text,
                recent_messages=recent_messages,
                state=state,
                now=time.time(),
                is_self=getattr(msg, "my_msg", False) is True,
                blocked_sender_ids=conf().get("wechat_group_blocked_sender_ids", []) or [],
                bot_names=[getattr(msg, "self_display_name", ""), getattr(msg, "to_user_nickname", ""), self.name],
                message_type=getattr(msg, "message_type", None),
                allow_media_payload=allow_media_payload,
            )
            if conf().get("wechat_group_emotion_enabled", True):
                try:
                    decision = self._get_emotion_service().adjust_free_reply_decision(
                        decision,
                        room_id=msg.other_user_id,
                        now=getattr(msg, "create_time", None) or time.time(),
                    )
                except Exception as e:
                    logger.warning("[wechat_group] failed to adjust free reply by emotion: {}".format(e))
        self.free_reply_state.remember_decision(decision)
        if not decision.get("triggered"):
            self._log_free_reply_decision(decision, "skipped")
            self.free_reply_state.mark_observed(getattr(msg, "other_user_id", ""))
            return False, decision
        return True, decision

    def _build_free_reply_task(self, msg: WechatGroupMessage, decision: dict, text=None) -> dict:
        task_text = text if text is not None else (getattr(msg, "text", None) or msg.content)
        return {
            "room_id": msg.other_user_id,
            "room_name": msg.other_user_nickname,
            "sender_id": msg.actual_user_id,
            "sender_name": msg.actual_user_nickname,
            "text": task_text,
            "msg": msg,
            "local_decision": decision,
            "queued_at": time.time(),
            "config": get_wechat_group_free_reply_config(),
        }

    def _submit_free_reply_after_judge(self, task, llm_decision):
        msg = task["msg"]
        context_type = msg.ctype
        content = msg.content
        image_understanding_triggered = False
        if msg.ctype == ContextType.IMAGE:
            if not conf().get("wechat_group_free_reply_image_understanding_enabled", False):
                return
            content = self._build_image_understanding_content(msg, allow_image_only=True)
            if not content:
                return
            context_type = ContextType.TEXT
            image_understanding_triggered = True
        context = self._compose_context(
            context_type,
            content,
            isgroup=True,
            msg=msg,
            wechat_group_force_reply=True,
        )
        if not context:
            return
        context["wechat_group_free_reply_triggered"] = True
        context["wechat_group_free_reply_decision"] = task.get("local_decision") or {}
        context["wechat_group_free_reply_llm_decision"] = llm_decision or {}
        if image_understanding_triggered:
            context["wechat_group_image_understanding_triggered"] = True
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
