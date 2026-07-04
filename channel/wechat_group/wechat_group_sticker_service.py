"""Runtime helpers for WeChat group stickers."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

from agent.tools.send.send import Send
from channel.wechat_group.wechat_group_sticker_store import WechatGroupStickerStore
from config import conf


class WechatGroupStickerService:
    def __init__(self, store: Optional[WechatGroupStickerStore] = None):
        self.store = store or WechatGroupStickerStore()

    def collect_from_message(
        self,
        room_id: str,
        media_path: str,
        source_message_id: str = "",
        description: str = "",
        now=None,
    ) -> Dict:
        room_text = str(room_id or "").strip()
        path_text = str(media_path or "").strip()
        if not room_text or not path_text or not os.path.isfile(path_text):
            return {}
        if self._is_too_large(path_text):
            return {}
        return self.store.upsert_sticker(
            room_id=room_text,
            file_hash=_hash_file(path_text),
            media_path=path_text,
            description=_normalize_description(description, path_text),
            source_message_id=str(source_message_id or "").strip(),
            status="active",
            created_at=now,
            updated_at=now,
        )

    def search_stickers(self, room_id: str, query: str = "", limit: int = 20, status: str = "active") -> List[Dict]:
        return self.store.list_stickers(room_id, query=query, status=status, limit=limit)

    def list_stickers(self, room_id: str, query: str = "", limit: int = 20, status: str = "") -> List[Dict]:
        return self.store.list_stickers(room_id, query=query, status=status, limit=limit)

    def disable_sticker(self, room_id: str, sticker_id: str) -> Dict:
        return self.store.update_status(room_id, sticker_id, status="disabled")

    def prepare_send_result(self, room_id: str, sticker_id: str, message: str = "", now=None) -> Dict:
        row = self.store.get_sticker(room_id, sticker_id)
        if not row:
            raise ValueError("sticker_id is not found in this room")
        if str(row.get("status") or "") != "active":
            raise ValueError("sticker is disabled")
        path_text = str(row.get("media_path") or "").strip()
        if not path_text or not os.path.isfile(path_text):
            raise ValueError("sticker file is missing")
        daily_limit = max(int(conf().get("wechat_group_sticker_daily_send_limit", 20) or 20), 1)
        if self.store.count_usage(str(room_id or "").strip(), _start_of_day(now)) >= daily_limit:
            raise ValueError("sticker daily limit reached")
        result = Send().execute({
            "path": path_text,
            "message": message or _default_send_message(path_text),
        })
        if getattr(result, "status", "") != "success":
            raise ValueError(str(getattr(result, "result", "") or "sticker send failed"))
        payload = dict(getattr(result, "result", {}) or {})
        payload["sticker_id"] = row.get("sticker_id") or ""
        payload["room_id"] = row.get("room_id") or ""
        payload["description"] = row.get("description") or ""
        return payload

    def record_sent(self, room_id: str, sticker_id: str, now=None) -> Dict:
        return self.store.record_usage(room_id, sticker_id, created_at=now)

    @staticmethod
    def _is_too_large(path_text: str) -> bool:
        max_mb = max(int(conf().get("wechat_group_sticker_max_size_mb", 2) or 2), 1)
        return os.path.getsize(path_text) > max_mb * 1024 * 1024


def _hash_file(path_text: str) -> str:
    digest = hashlib.sha1()
    with open(path_text, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_description(description: str, path_text: str) -> str:
    value = str(description or "").strip()
    if value:
        return value[:200]
    return Path(path_text).stem[:200]


def _default_send_message(path_text: str) -> str:
    return f"发送表情包 {os.path.basename(path_text)}"


def _start_of_day(now=None) -> int:
    ts = int(now) if now is not None else int(time.time())
    return ts - (ts % 86400)
