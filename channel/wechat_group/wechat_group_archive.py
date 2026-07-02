"""SQLite archive for WeChat group messages."""

import os
import sqlite3
import threading
import time
from contextlib import closing
from typing import Any, Dict, List, Optional

from config import get_appdata_dir


def _default_archive_path() -> str:
    data_root = os.environ.get("COW_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".cow")
    return os.path.join(os.path.expanduser(data_root), "wechat_group", "wechat_group_archive.db")


class WechatGroupArchive:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _default_archive_path()
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    def record_message(
        self,
        message_id: str,
        room_id: str,
        room_name: str = "",
        sender_id: str = "",
        sender_nickname: str = "",
        message_type: str = "text",
        text: str = "",
        media_path: str = "",
        is_at: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[int] = None,
    ) -> None:
        if not room_id or not message_id:
            return
        ts = _coerce_timestamp(created_at)
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO wechat_group_messages (
                        message_id, room_id, room_name, sender_id, sender_nickname,
                        message_type, text, media_path, is_at, metadata, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(message_id),
                        str(room_id),
                        str(room_name or ""),
                        str(sender_id or ""),
                        str(sender_nickname or ""),
                        str(message_type or "text"),
                        str(text or ""),
                        str(media_path or ""),
                        1 if is_at else 0,
                        str(metadata or {}),
                        ts,
                    ),
                )

    def record_assistant_reply(
        self,
        room_id: str,
        room_name: str = "",
        reply_type: str = "text",
        content: str = "",
        mention_ids: Optional[List[str]] = None,
        created_at: Optional[int] = None,
    ) -> None:
        if not room_id or not content:
            return
        ts = _coerce_timestamp(created_at)
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO wechat_group_assistant_replies (
                        room_id, room_name, reply_type, content, mention_ids, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(room_id),
                        str(room_name or ""),
                        str(reply_type or "text"),
                        str(content or ""),
                        ",".join(mention_ids or []),
                        ts,
                    ),
                )

    def get_recent_messages(
        self,
        room_id: str,
        limit: int = 20,
        minutes: int = 60,
        now: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        if not room_id:
            return []
        max_limit = min(max(int(limit or 20), 1), 300)
        window_minutes = max(int(minutes or 60), 1)
        cutoff = _coerce_timestamp(now) - window_minutes * 60
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, message_id, room_id, room_name, sender_id, sender_nickname,
                       message_type, text, media_path, is_at, created_at
                FROM wechat_group_messages
                WHERE room_id = ? AND created_at >= ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (str(room_id), cutoff, max_limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS wechat_group_messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        message_id TEXT NOT NULL UNIQUE,
                        room_id TEXT NOT NULL,
                        room_name TEXT,
                        sender_id TEXT,
                        sender_nickname TEXT,
                        message_type TEXT NOT NULL DEFAULT 'text',
                        text TEXT,
                        media_path TEXT,
                        is_at INTEGER NOT NULL DEFAULT 0,
                        metadata TEXT,
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_wechat_group_messages_room_time
                    ON wechat_group_messages(room_id, created_at, id)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS wechat_group_assistant_replies (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        room_name TEXT,
                        reply_type TEXT NOT NULL DEFAULT 'text',
                        content TEXT,
                        mention_ids TEXT,
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_wechat_group_replies_room_time
                    ON wechat_group_assistant_replies(room_id, created_at, id)
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)


def _coerce_timestamp(value: Any = None) -> int:
    try:
        return int(value)
    except Exception:
        return int(time.time())
