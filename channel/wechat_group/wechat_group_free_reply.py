"""Local scoring and runtime state for WeChat group free replies."""

import copy
import re
import time

from config import conf


FREE_REPLY_ACTIVITY_LEVELS = ["quiet", "normal", "active", "crazy"]

DEFAULT_FREE_REPLY_PROFILES = {
    "quiet": {"min_score": 65, "min_interval_seconds": 30, "hourly_limit": 0, "consecutive_limit": 0},
    "normal": {"min_score": 50, "min_interval_seconds": 10, "hourly_limit": 0, "consecutive_limit": 0},
    "active": {"min_score": 35, "min_interval_seconds": 3, "hourly_limit": 0, "consecutive_limit": 0},
    "crazy": {"min_score": 20, "min_interval_seconds": 0, "hourly_limit": 0, "consecutive_limit": 0},
}

POSITIVE_RULES = [
    {"id": "bot_name_match", "score": 45, "label": "Mentions bot name without explicit at"},
    {"id": "group_question", "score": 30, "label": "Open group question or help request"},
    {"id": "unanswered_question", "score": 25, "label": "Question without recent answer"},
    {"id": "bot_capability_match", "score": 25, "label": "Matches assistant capabilities"},
    {"id": "memory_or_transcript", "score": 20, "label": "Needs group memory or recent transcript"},
    {"id": "ai_opinion", "score": 35, "label": "Asks what AI thinks"},
]

NEGATIVE_RULES = [
    {"id": "disabled", "label": "Free reply disabled"},
    {"id": "room_not_enabled", "label": "Room not in free reply scope"},
    {"id": "self_message", "label": "Message sent by bot itself"},
    {"id": "blocked_sender", "label": "Sender is blocked"},
    {"id": "low_information", "label": "Low-information short text"},
    {"id": "media_payload", "label": "Raw media payload should not trigger free reply"},
    {"id": "sensitive_or_dangerous", "label": "Sensitive, private or dangerous request"},
    {"id": "min_interval", "label": "Room cooldown is active"},
    {"id": "hourly_limit", "label": "Hourly limit reached"},
    {"id": "consecutive_limit", "label": "Consecutive reply limit reached"},
    {"id": "below_threshold", "label": "Score below current threshold"},
]


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _as_list(value) -> list:
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[，,;；\n\r\t ]+", str(value or ""))
    return list(dict.fromkeys(str(item or "").strip() for item in raw if str(item or "").strip()))


def _clamp_int(value, default, low, high) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = default
    return min(max(value, low), high)


def _clamp_float(value, default, low, high) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        value = default
    return min(max(value, low), high)


def normalize_wechat_group_free_reply_profiles(raw_profiles=None) -> dict:
    profiles = copy.deepcopy(DEFAULT_FREE_REPLY_PROFILES)
    if not isinstance(raw_profiles, dict):
        return profiles
    for level in FREE_REPLY_ACTIVITY_LEVELS:
        raw = raw_profiles.get(level)
        if not isinstance(raw, dict):
            continue
        profiles[level] = {
            "min_score": _clamp_int(raw.get("min_score"), profiles[level]["min_score"], 0, 100),
            "min_interval_seconds": _clamp_int(raw.get("min_interval_seconds"), profiles[level]["min_interval_seconds"], 0, 3600),
            "hourly_limit": _clamp_int(raw.get("hourly_limit"), profiles[level]["hourly_limit"], 0, 999),
            "consecutive_limit": _clamp_int(raw.get("consecutive_limit"), profiles[level]["consecutive_limit"], 0, 99),
        }
    return profiles


def get_wechat_group_free_reply_config() -> dict:
    level = str(conf().get("wechat_group_free_reply_activity_level", "normal") or "normal").strip()
    if level not in FREE_REPLY_ACTIVITY_LEVELS:
        level = "normal"
    return {
        "enabled": _as_bool(conf().get("wechat_group_free_reply_enabled", False)),
        "room_ids": _as_list(conf().get("wechat_group_free_reply_room_ids", [])),
        "names": _as_list(conf().get("wechat_group_free_reply_names", [])),
        "activity_level": level,
        "queue_ttl_seconds": _clamp_int(conf().get("wechat_group_free_reply_queue_ttl_seconds", 120), 120, 10, 600),
        "worker_max_workers": _clamp_int(conf().get("wechat_group_free_reply_worker_max_workers", 2), 2, 1, 8),
        "worker_queue_size": _clamp_int(conf().get("wechat_group_free_reply_worker_queue_size", 100), 100, 1, 1000),
        "llm_judge_enabled": _as_bool(conf().get("wechat_group_free_reply_llm_judge_enabled", True)),
        "llm_judge_timeout_seconds": _clamp_int(conf().get("wechat_group_free_reply_llm_judge_timeout_seconds", 8), 8, 1, 30),
        "llm_judge_min_confidence": _clamp_float(conf().get("wechat_group_free_reply_llm_judge_min_confidence", 0.6), 0.6, 0.0, 1.0),
        "profiles": normalize_wechat_group_free_reply_profiles(conf().get("wechat_group_free_reply_profiles", {})),
    }


def get_wechat_group_free_reply_rules() -> dict:
    return {
        "positive": copy.deepcopy(POSITIVE_RULES),
        "negative": copy.deepcopy(NEGATIVE_RULES),
    }


def is_free_reply_room_enabled(config, room_id, room_name) -> bool:
    room_ids = config.get("room_ids") or []
    if room_ids:
        return room_id in room_ids
    names = config.get("names") or []
    if names:
        return room_name in names
    return False


def _text_preview(text: str, limit=120) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text[:limit]


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _is_media_payload(text: str, message_type=None) -> bool:
    value = _normalize_text(text)
    msg_type = str(message_type or "").strip().lower() if isinstance(message_type, str) else ""
    if msg_type and msg_type not in ("text", "unknown"):
        return True
    if re.match(r"^<\?xml\b", value, re.IGNORECASE):
        return True
    if re.match(r"^<msg\b", value, re.IGNORECASE):
        return True
    return bool(re.search(r"<(img|emoji|videomsg|appmsg|voicemsg)\b", value, re.IGNORECASE))


def _is_low_information(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    if len(compact) <= 2:
        return True
    lowered = compact.lower()
    if lowered in {"哈哈", "呵呵", "嗯嗯", "好的", "ok", "hi", "hello"}:
        return True
    without_fillers = re.sub(r"[\W_]+", "", lowered, flags=re.UNICODE)
    without_fillers = re.sub(r"(哈|啊|呀|哦|噢|嗯|额|呃|呵|hi|hello|ok)+", "", without_fillers, flags=re.IGNORECASE)
    return len(without_fillers) == 0 and len(compact) <= 8


def _is_sensitive_or_dangerous(text: str) -> bool:
    lower = (text or "").lower()
    patterns = [
        r"\bapi\s*key\b",
        r"\btoken\b",
        r"\bsecret\b",
        r"file://",
        r"[a-zA-Z]:\\",
        r"本机",
        r"桌面",
        r"私钥",
        r"密码",
        r"cookie",
    ]
    return any(re.search(pattern, lower, re.IGNORECASE) for pattern in patterns)


def _score_text(text: str, bot_names=None) -> tuple:
    text = _normalize_text(text)
    score = 0
    reasons = []
    bot_names = [
        name for name in (bot_names or ["CowAgent", "白龙马", "小白龙", "机器人", "AI"])
        if isinstance(name, str) and name
    ]
    if any(name and name in text for name in bot_names):
        score += 45
        reasons.append("bot_name_match")
    if re.search(r"(谁能|谁有|有没有人|大家|帮我|帮忙|求|看看|看下|咋办|怎么办|怎么|如何|为啥|为什么|啥意思|什么意思|哪个|哪位|哪里|哪儿|能不能|可不可以|会不会|吗|嘛|呢|？|\?)", text or ""):
        score += 30
        reasons.append("group_question")
    if re.search(r"(总结|归纳|方案|记录|上下文|刚才|讨论|记忆|群聊|文档|报告|代码|识图|图片|截图|视频|解析|表情包|梗图|斗图|文件|txt|pdf|word|excel|ppt|链接|网页|搜索|查一下)", text or "", re.IGNORECASE):
        score += 25
        reasons.append("bot_capability_match")
    if re.search(r"(记得|群记忆|聊天记录|刚才说|之前|上面|前面|谁说|谁发|谁讲|群里|群友|这个人|他们|她们)", text or ""):
        score += 20
        reasons.append("memory_or_transcript")
    if re.search(r"(AI怎么看|ai怎么看|问问AI|问问ai)", text or ""):
        score += 35
        reasons.append("ai_opinion")
    if re.search(r"(笑死|绷不住|破防|离谱|抽象|逆天|吐槽|哈哈哈|hhh|好家伙|急了|整活|活了|太对了|这也行|烂活|名场面)", text or "", re.IGNORECASE):
        score += 10
        reasons.append("banter_opportunity")
    return score, reasons


def _elapsed_seconds(now, previous) -> float:
    diff = float(now) - float(previous)
    # Some legacy tests and snapshots use compact millisecond-like values.
    if diff > 1000 and float(now) < 1000000:
        return diff / 1000.0
    return diff


def evaluate_wechat_group_free_reply(
    config,
    room_id,
    room_name,
    sender_id,
    sender_name,
    text,
    recent_messages=None,
    state=None,
    now=None,
    is_self=False,
    blocked_sender_ids=None,
    bot_names=None,
    message_type=None,
) -> dict:
    now = time.time() if now is None else now
    state = state or {}
    suppressions = []
    normalized_text = _normalize_text(text or "")
    media_payload = _is_media_payload(normalized_text, message_type=message_type)
    if media_payload:
        score, reasons = 0, []
    else:
        score, reasons = _score_text(normalized_text, bot_names=bot_names)
        if "group_question" in reasons and len(recent_messages or []) >= 2:
            score += 25
            reasons.append("unanswered_question")
    level = config.get("activity_level") or "normal"
    profile = (config.get("profiles") or DEFAULT_FREE_REPLY_PROFILES).get(level, DEFAULT_FREE_REPLY_PROFILES["normal"])
    threshold = int(profile.get("min_score", 50))

    if not config.get("enabled"):
        suppressions.append("disabled")
    if not is_free_reply_room_enabled(config, room_id, room_name):
        suppressions.append("room_not_enabled")
    if is_self:
        suppressions.append("self_message")
    if sender_id and sender_id in (blocked_sender_ids or []):
        suppressions.append("blocked_sender")
    if _is_low_information(text or ""):
        suppressions.append("low_information")
    if media_payload:
        suppressions.append("media_payload")
    if _is_sensitive_or_dangerous(text or ""):
        suppressions.append("sensitive_or_dangerous")

    min_interval = int(profile.get("min_interval_seconds", 0) or 0)
    last_triggered = float(state.get("last_triggered_at") or 0)
    if min_interval and last_triggered and _elapsed_seconds(now, last_triggered) < min_interval:
        suppressions.append("min_interval")

    hourly_limit = int(profile.get("hourly_limit", 0) or 0)
    recent_triggered = [
        float(ts) for ts in (state.get("recent_triggered_at") or [])
        if _elapsed_seconds(now, float(ts)) < 3600
    ]
    if hourly_limit and len(recent_triggered) >= hourly_limit:
        suppressions.append("hourly_limit")

    consecutive_limit = int(profile.get("consecutive_limit", 0) or 0)
    if consecutive_limit and int(state.get("consecutive_triggered") or 0) >= consecutive_limit:
        suppressions.append("consecutive_limit")

    if score < threshold:
        suppressions.append("below_threshold")

    return {
        "triggered": not suppressions,
        "score": score,
        "threshold": threshold,
        "activity_level": level,
        "reasons": reasons,
        "suppressions": suppressions,
        "room_id": room_id or "",
        "room_name": room_name or "",
        "sender_id": sender_id or "",
        "sender_name": sender_name or "",
        "text_preview": _text_preview(text),
        "timestamp": now,
    }


class WechatGroupFreeReplyStateStore:
    def __init__(self):
        self._states = {}
        self._last_decision = {}

    def get(self, room_id) -> dict:
        state = self._states.setdefault(room_id or "", {
            "last_triggered_at": 0,
            "recent_triggered_at": [],
            "consecutive_triggered": 0,
        })
        return state

    def mark_triggered(self, room_id, now=None) -> None:
        now = time.time() if now is None else now
        state = self.get(room_id)
        state["last_triggered_at"] = now
        state["recent_triggered_at"] = [
            ts for ts in state.get("recent_triggered_at", []) if _elapsed_seconds(now, float(ts)) < 3600
        ] + [now]
        state["consecutive_triggered"] = int(state.get("consecutive_triggered") or 0) + 1

    def mark_observed(self, room_id) -> None:
        self.get(room_id)["consecutive_triggered"] = 0

    def remember_decision(self, decision) -> None:
        self._last_decision = copy.deepcopy(decision or {})

    def last_decision(self) -> dict:
        return copy.deepcopy(self._last_decision)
