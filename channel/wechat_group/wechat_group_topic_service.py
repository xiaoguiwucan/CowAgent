"""Runtime helpers for WeChat group topic blocks."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from channel.wechat_group.wechat_group_topic_store import WechatGroupTopicStore
from config import conf


def _normalize_participant_display_name(value: Any, sender_id: str = "") -> str:
    text = str(value or "").replace("\u2005", " ").replace("\xa0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return ""
    if text.startswith("@") and not _looks_like_raw_sender_name(text, sender_id):
        text = text[1:].strip()
    if _looks_like_raw_sender_name(text, sender_id):
        return ""
    return text


def _looks_like_raw_sender_name(value: Any, sender_id: str = "") -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    normalized = text.lstrip("@")
    sender_text = str(sender_id or "").strip()
    sender_normalized = sender_text.lstrip("@")
    if sender_text and text == sender_text:
        return True
    if sender_normalized and normalized == sender_normalized:
        return True
    if normalized.startswith("wxid_"):
        return True
    if text.startswith("@") and re.fullmatch(r"[0-9A-Za-z_-]{12,}", normalized):
        return True
    return False


class WechatGroupTopicService:
    def __init__(self, store: Optional[WechatGroupTopicStore] = None):
        self.store = store or WechatGroupTopicStore()

    def list_active_topics(self, room_id: str, limit: Optional[int] = None) -> List[Dict]:
        if limit is None:
            limit = int(conf().get("wechat_group_topic_context_limit", 2) or 2)
        return self.store.list_active_threads(room_id, limit=limit)

    def build_prompt_block_from_archive(self, archive, room_id: str, now=None) -> str:
        self.refresh_active_topic_from_archive(archive, room_id, now=now)
        return self.build_prompt_block(room_id)

    def search_topics(self, room_id: str, query: str = "", limit: int = 20) -> List[Dict]:
        return self.store.search_threads(room_id, query=query, limit=limit)

    def refresh_active_topic_from_archive(self, archive, room_id: str, now=None) -> Optional[Dict]:
        recent_messages = archive.get_recent_messages(
            room_id,
            limit=int(conf().get("wechat_group_topic_recent_message_limit", 30) or 30),
            minutes=max(int(conf().get("wechat_group_recent_context_minutes", 60) or 60), 60),
            now=now,
        )
        messages = [item for item in recent_messages if str(item.get("text") or "").strip()]
        if not messages:
            return None
        latest_row_id = int(messages[-1].get("id") or 0)
        active = self.list_active_topics(room_id, limit=1)
        current = active[0] if active else None
        refresh_gap = max(int(conf().get("wechat_group_topic_summary_refresh_message_gap", 8) or 8), 1)
        if current and latest_row_id and latest_row_id - int(current.get("last_row_id") or 0) < refresh_gap:
            return current
        summary = self._summarize_messages(messages)
        if not summary:
            return current
        thread = self.store.upsert_topic_thread(
            room_id=room_id,
            thread_id=str(current.get("thread_id") or "") if current else "",
            title=summary["title"],
            gist=summary["gist"],
            facts=summary["facts"],
            participants=summary["participants"],
            open_loops=summary["open_loops"],
            last_message_id=str(messages[-1].get("message_id") or ""),
            last_row_id=latest_row_id,
            message_count=len(messages),
            status="active",
            created_at=int(current.get("created_at") or 0) if current else None,
        )
        for item in messages:
            self.store.map_message_to_thread(
                room_id=room_id,
                thread_id=thread["thread_id"],
                message_id=str(item.get("message_id") or ""),
                row_id=int(item.get("id") or 0),
                created_at=int(item.get("created_at") or 0),
            )
        self.store.append_summary_history(
            room_id=room_id,
            thread_id=thread["thread_id"],
            summary_text=summary["gist"],
            snapshot={
                "title": summary["title"],
                "facts": summary["facts"],
                "participants": summary["participants"],
                "open_loops": summary["open_loops"],
                "message_ids": [str(item.get("message_id") or "") for item in messages if str(item.get("message_id") or "").strip()],
            },
            created_at=int(messages[-1].get("created_at") or 0),
        )
        return thread

    def build_prompt_block(self, room_id: str, limit: Optional[int] = None) -> str:
        topics = self.list_active_topics(room_id, limit=limit)
        if not topics:
            return ""
        sections = []
        for topic in topics:
            lines = ["[active_topic]"]
            if topic.get("title"):
                lines.append(f"title: {topic['title']}")
            if topic.get("gist"):
                lines.append(f"gist: {topic['gist']}")
            if topic.get("facts"):
                lines.append("facts: {}".format(", ".join(str(item) for item in topic.get("facts") or [] if str(item).strip())))
            if topic.get("participants"):
                lines.append(
                    "participants: {}".format(
                        ", ".join(str(item) for item in topic.get("participants") or [] if str(item).strip())
                    )
                )
            if topic.get("open_loops"):
                lines.append(
                    "open_loops: {}".format(
                        ", ".join(str(item) for item in topic.get("open_loops") or [] if str(item).strip())
                    )
                )
            if topic.get("message_count"):
                lines.append(f"message_count: {int(topic['message_count'])}")
            sections.append("\n".join(lines))
        return "<wechat-group-topic>\n{}\n</wechat-group-topic>".format("\n\n".join(sections))

    @staticmethod
    def _summarize_messages(messages: List[Dict]) -> Optional[Dict]:
        if not messages:
            return None
        texts = []
        participants = []
        open_loops = []
        for item in messages:
            text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip()
            if not text:
                continue
            texts.append(text)
            sender_id = str(item.get("sender_id") or "").strip()
            participant = _normalize_participant_display_name(item.get("sender_nickname"), sender_id) or sender_id
            if participant and participant not in participants:
                participants.append(participant)
            if WechatGroupTopicService._looks_like_open_loop(text) and text not in open_loops:
                open_loops.append(text[:80])
        if not texts:
            return None
        title = WechatGroupTopicService._build_title(texts[0])
        facts = []
        for text in texts[-2:]:
            clipped = text[:80]
            if clipped not in facts:
                facts.append(clipped)
        gist = " / ".join(text[:40] for text in texts[-3:])
        return {
            "title": title,
            "gist": gist[:160],
            "facts": facts,
            "participants": participants,
            "open_loops": open_loops[:3],
        }

    @staticmethod
    def _build_title(text: str) -> str:
        cleaned = re.sub(r"^@?\S+\s*", "", str(text or "").strip(), count=1)
        candidate = re.split(r"[。！？!?，,；;:：\n]", cleaned, maxsplit=1)[0].strip()
        candidate = candidate or cleaned or "最近群聊话题"
        return candidate[:24]

    @staticmethod
    def _looks_like_open_loop(text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return False
        return value.endswith(("?", "？")) or any(token in value for token in ("是否", "要不要", "可以吗", "行不行", "咋办", "怎么办"))
