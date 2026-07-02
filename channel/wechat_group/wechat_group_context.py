"""Prompt context helpers for the WeChat group channel."""

import time
from typing import Any, Dict, Iterable


def build_wechat_group_recent_context_block(
    archive,
    room_id: str,
    limit: int = 20,
    minutes: int = 60,
    now: int = None,
) -> str:
    rows = archive.get_recent_messages(room_id, limit=limit, minutes=minutes, now=now)
    if not rows:
        return ""
    lines = [_format_recent_context_line(row) for row in rows]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    return "<recent-wechat-group-transcript>\n{}\n</recent-wechat-group-transcript>".format(
        "\n".join(lines)
    )


def _format_recent_context_line(row: Dict[str, Any]) -> str:
    timestamp = _format_timestamp(row.get("created_at"))
    msg_type = str(row.get("message_type") or "text")
    sender = str(row.get("sender_nickname") or row.get("sender_id") or "unknown")
    summary = _summarize_message(row)
    if not summary:
        return ""
    return "{} [{}] {}: {}".format(timestamp, msg_type, sender, summary).strip()


def _format_timestamp(value: Any) -> str:
    try:
        return time.strftime("%m-%d %H:%M", time.localtime(int(value)))
    except Exception:
        return ""


def _summarize_message(row: Dict[str, Any], max_length: int = 160) -> str:
    text = str(row.get("text") or "").replace("\r\n", "\n").replace("\r", "\n")
    text = " ".join(text.split())
    if not text:
        media_path = str(row.get("media_path") or "")
        if media_path:
            text = "[media] {}".format(media_path)
        else:
            text = "[{} message]".format(row.get("message_type") or "unknown")
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "..."
