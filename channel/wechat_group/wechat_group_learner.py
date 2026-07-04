"""Heuristic learner for WeChat group global profiles and group knowledge."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from channel.wechat_group.wechat_group_archive import WechatGroupArchive
from channel.wechat_group.wechat_group_knowledge_service import WechatGroupKnowledgeService
from channel.wechat_group.wechat_group_knowledge_store import WechatGroupKnowledgeStore
from channel.wechat_group.wechat_group_profile_service import WechatGroupProfileService


class WechatGroupLearner:
    def __init__(
        self,
        archive: WechatGroupArchive,
        profile_service: WechatGroupProfileService,
        knowledge_service: WechatGroupKnowledgeService,
        knowledge_store: Optional[WechatGroupKnowledgeStore] = None,
        config_getter=None,
    ):
        self.archive = archive
        self.profile_service = profile_service
        self.knowledge_service = knowledge_service
        self.knowledge_store = knowledge_store or knowledge_service.store
        self.config_getter = config_getter or (lambda key, default=None: default)

    def run_once(self, room_id: str, mode: str = "all") -> Dict[str, Any]:
        cursor = self.knowledge_store.get_cursor(room_id)
        batch_limit = int(self._cfg("wechat_group_learning_batch_message_limit", 200) or 200)
        batch_start_row_id = int(cursor.get("last_archive_row_id") or 0)
        run_id = self.knowledge_store.create_learning_run(room_id, mode, batch_start_row_id)
        try:
            messages = self.archive.get_messages_after_row_id(room_id, batch_start_row_id, limit=batch_limit)
            if not messages:
                self.knowledge_store.finish_learning_run(
                    run_id=run_id,
                    status="success",
                    batch_end_row_id=batch_start_row_id,
                    batch_message_count=0,
                    profile_update_count=0,
                    group_memory_upsert_count=0,
                )
                return {
                    "status": "success",
                    "run_id": run_id,
                    "batch_message_count": 0,
                    "profile_update_count": 0,
                    "group_memory_upsert_count": 0,
                    "profiles": [],
                    "group_memories": [],
                }

            profiles = self._learn_profiles(room_id, messages) if mode in ("all", "profile") else []
            group_memories = self._learn_group_memories(room_id, messages) if mode in ("all", "memory") else []
            batch_end_row_id = int(messages[-1].get("id") or batch_start_row_id)
            self.knowledge_store.update_cursor(room_id, batch_end_row_id)
            self.knowledge_store.finish_learning_run(
                run_id=run_id,
                status="success",
                batch_end_row_id=batch_end_row_id,
                batch_message_count=len(messages),
                profile_update_count=len(profiles),
                group_memory_upsert_count=len(group_memories),
            )
            return {
                "status": "success",
                "run_id": run_id,
                "batch_message_count": len(messages),
                "profile_update_count": len(profiles),
                "group_memory_upsert_count": len(group_memories),
                "profiles": profiles,
                "group_memories": group_memories,
            }
        except Exception as exc:
            self.knowledge_store.finish_learning_run(
                run_id=run_id,
                status="failed",
                batch_end_row_id=batch_start_row_id,
                batch_message_count=0,
                profile_update_count=0,
                group_memory_upsert_count=0,
                failed_reason=str(exc),
            )
            raise

    def _learn_profiles(self, room_id: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for item in messages:
            sender_id = str(item.get("sender_id") or "").strip()
            if not sender_id or str(item.get("message_type") or "text") != "text":
                continue
            grouped[sender_id].append(item)

        min_messages = max(int(self._cfg("wechat_group_learning_profile_min_messages", 6) or 6), 1)
        sample_limit = max(int(self._cfg("wechat_group_learning_profile_sample_limit", 30) or 30), 1)
        results = []
        for sender_id, rows in grouped.items():
            if len(rows) < min_messages:
                continue
            sample_rows = rows[:sample_limit]
            nickname = _pick_sender_nickname(sender_id, sample_rows)
            text_blob = " ".join(str(row.get("text") or "") for row in sample_rows)
            common_words = _top_terms(text_blob, limit=3)
            interests = _infer_interests(text_blob)
            speak_style = _infer_speak_style(sample_rows)
            profile = self.profile_service.merge_learned_profile(
                sender_id=sender_id,
                primary_nickname=nickname,
                aliases=[nickname] if nickname and nickname != sender_id else [],
                speak_style=speak_style,
                interests=interests,
                common_words=common_words,
                msg_delta=len(sample_rows),
                activity_delta=len(sample_rows),
                intimacy_delta=1 if any((row.get("is_at") or 0) for row in sample_rows) else 0,
                room_id=room_id,
                room_name=str(sample_rows[-1].get("room_name") or ""),
                last_seen_at=int(sample_rows[-1].get("created_at") or 0),
            )
            results.append(profile)
        return results

    def _learn_group_memories(self, room_id: str, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        min_messages = max(int(self._cfg("wechat_group_learning_group_memory_min_messages", 20) or 20), 1)
        keyword_rows = [
            item for item in messages
            if str(item.get("message_type") or "text") == "text"
            and _looks_like_group_memory(str(item.get("text") or ""))
        ]
        if len(keyword_rows) < min_messages:
            return []

        memory_text = _merge_memory_texts([str(item.get("text") or "") for item in keyword_rows])
        existing = self.knowledge_service.search_group_memories(room_id, memory_text, limit=5)
        if any(_normalize_text(item.get("content", "")) == _normalize_text(memory_text) for item in existing):
            return []

        memory = self.knowledge_service.add_group_memory(
            room_id=room_id,
            content=memory_text,
            evidence_message_ids=[str(item.get("message_id") or "") for item in keyword_rows if item.get("message_id")],
            evidence_text=" | ".join(str(item.get("text") or "") for item in keyword_rows[:3]),
            source_kind="learning",
        )
        return [memory]

    def _cfg(self, key: str, default=None):
        return self.config_getter(key, default)


def _infer_speak_style(rows: List[Dict[str, Any]]) -> str:
    texts = [str(row.get("text") or "").strip() for row in rows if str(row.get("text") or "").strip()]
    if not texts:
        return ""
    avg_len = sum(len(text) for text in texts) / len(texts)
    if any(token in "".join(texts) for token in ("1.", "2.", "首先", "其次", "清单")):
        return "更爱列清单"
    if avg_len <= 15:
        return "短句，偏直接"
    return "表达完整，偏说明式"


def _infer_interests(text: str) -> List[str]:
    mapping = {
        "前端": ["前端", "react", "ui", "样式"],
        "发布": ["发布", "发版", "版本"],
        "测试": ["测试", "回归", "qa"],
        "架构": ["架构", "重构"],
    }
    lowered = text.lower()
    result = []
    for label, keywords in mapping.items():
        if any(keyword in lowered for keyword in keywords):
            result.append(label)
    return result


def _top_terms(text: str, limit: int = 3) -> List[str]:
    tokens = re.findall(r"[A-Za-z]{2,}|[\u4e00-\u9fff]{2,}", text or "")
    stopwords = {"今天", "晚上", "一下", "继续", "确认", "本群", "统一"}
    counts: Dict[str, int] = {}
    for token in tokens:
        lowered = token.lower()
        if lowered in stopwords:
            continue
        counts[lowered] = counts.get(lowered, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _ in ordered[:limit]]


def _looks_like_group_memory(text: str) -> bool:
    lowered = _normalize_text(text)
    return any(keyword in lowered for keyword in ("发版", "发布", "固定", "统一", "规则", "约定"))


def _merge_memory_texts(texts: List[str]) -> str:
    if not texts:
        return ""
    normalized = [_normalize_text(text) for text in texts if _normalize_text(text)]
    if not normalized:
        return ""
    first = normalized[0]
    for candidate in normalized[1:]:
        if candidate == first:
            continue
        if first in candidate:
            first = candidate
        elif candidate in first:
            continue
        else:
            return texts[-1].strip()
    return texts[-1].strip()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+|[，。,.!！?？:：]", "", text or "").lower()


def _pick_sender_nickname(sender_id: str, rows: List[Dict[str, Any]]) -> str:
    for row in reversed(rows or []):
        nickname = str(row.get("sender_nickname") or "").strip()
        if nickname and not _looks_like_raw_sender_name(nickname, sender_id):
            return nickname
    return str(sender_id or "").strip()


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
