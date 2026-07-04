"""SQLite store for WeChat group topic threads."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from typing import Any, Dict, List, Optional
from uuid import uuid4


def _default_topic_store_path() -> str:
    data_root = os.environ.get("COW_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".cow")
    return os.path.join(os.path.expanduser(data_root), "wechat_group", "wechat_group_topics.db")


class WechatGroupTopicStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _default_topic_store_path()
        self._lock = threading.Lock()
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    def upsert_topic_thread(
        self,
        room_id: str,
        title: str,
        gist: str = "",
        facts: Optional[List[str]] = None,
        participants: Optional[List[str]] = None,
        open_loops: Optional[List[str]] = None,
        last_message_id: str = "",
        last_row_id: int = 0,
        message_count: int = 0,
        status: str = "active",
        thread_id: str = "",
        created_at: Optional[int] = None,
        updated_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        room_id = _require_text("room_id", room_id)
        title = _require_text("title", title)
        thread_id = str(thread_id or uuid4().hex)
        now = _coerce_timestamp(updated_at)
        created_ts = _coerce_timestamp(created_at) if created_at is not None else now
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO wechat_group_topic_threads (
                        thread_id, room_id, title, gist,
                        facts_json, participants_json, open_loops_json,
                        last_message_id, last_row_id, message_count,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(thread_id) DO UPDATE SET
                        room_id = excluded.room_id,
                        title = excluded.title,
                        gist = excluded.gist,
                        facts_json = excluded.facts_json,
                        participants_json = excluded.participants_json,
                        open_loops_json = excluded.open_loops_json,
                        last_message_id = excluded.last_message_id,
                        last_row_id = excluded.last_row_id,
                        message_count = excluded.message_count,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        thread_id,
                        room_id,
                        title,
                        str(gist or "").strip(),
                        json.dumps(_normalize_list(facts), ensure_ascii=False),
                        json.dumps(_normalize_list(participants), ensure_ascii=False),
                        json.dumps(_normalize_list(open_loops), ensure_ascii=False),
                        str(last_message_id or "").strip(),
                        int(last_row_id or 0),
                        max(int(message_count or 0), 0),
                        str(status or "active"),
                        created_ts,
                        now,
                    ),
                )
        return self.get_thread(room_id, thread_id) or {}

    def get_thread(self, room_id: str, thread_id: str) -> Optional[Dict[str, Any]]:
        room_text = str(room_id or "").strip()
        thread_text = str(thread_id or "").strip()
        if not room_text or not thread_text:
            return None
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM wechat_group_topic_threads
                WHERE room_id = ? AND thread_id = ?
                LIMIT 1
                """,
                (room_text, thread_text),
            ).fetchone()
        return self._thread_row_to_dict(row) if row else None

    def list_active_threads(self, room_id: str, limit: int = 3) -> List[Dict[str, Any]]:
        room_text = str(room_id or "").strip()
        if not room_text:
            return []
        max_limit = min(max(int(limit or 3), 1), 50)
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM wechat_group_topic_threads
                WHERE room_id = ? AND status = 'active'
                ORDER BY updated_at DESC, thread_id DESC
                LIMIT ?
                """,
                (room_text, max_limit),
            ).fetchall()
        return [self._thread_row_to_dict(row) for row in rows]

    def search_threads(
        self,
        room_id: str,
        query: str = "",
        limit: int = 20,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        room_text = str(room_id or "").strip()
        if not room_text:
            return []
        max_limit = min(max(int(limit or 20), 1), 100)
        clauses = ["room_id = ?"]
        params: List[Any] = [room_text]
        status_text = str(status or "").strip()
        if status_text:
            clauses.append("status = ?")
            params.append(status_text)
        query_text = str(query or "").strip()
        if query_text:
            like = f"%{query_text}%"
            clauses.append("(title LIKE ? OR gist LIKE ? OR facts_json LIKE ? OR open_loops_json LIKE ?)")
            params.extend([like, like, like, like])
        params.append(max_limit)
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM wechat_group_topic_threads
                WHERE {' AND '.join(clauses)}
                ORDER BY updated_at DESC, thread_id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._thread_row_to_dict(row) for row in rows]

    def map_message_to_thread(
        self,
        room_id: str,
        thread_id: str,
        message_id: str = "",
        row_id: int = 0,
        created_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        room_text = _require_text("room_id", room_id)
        thread_text = _require_text("thread_id", thread_id)
        message_text = str(message_id or "").strip()
        row_value = int(row_id or 0)
        if not message_text and row_value <= 0:
            raise ValueError("message_id or row_id is required")
        now = _coerce_timestamp(created_at)
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO wechat_group_topic_message_refs (
                        room_id, thread_id, message_id, row_id, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (room_text, thread_text, message_text, row_value, now),
                )
        return self.get_thread_ref(room_id=room_text, message_id=message_text, row_id=row_value) or {}

    def get_thread_ref(
        self,
        room_id: str,
        message_id: str = "",
        row_id: int = 0,
    ) -> Optional[Dict[str, Any]]:
        room_text = str(room_id or "").strip()
        message_text = str(message_id or "").strip()
        row_value = int(row_id or 0)
        if not room_text or (not message_text and row_value <= 0):
            return None
        clauses = ["room_id = ?"]
        params: List[Any] = [room_text]
        if message_text:
            clauses.append("message_id = ?")
            params.append(message_text)
        else:
            clauses.append("row_id = ?")
            params.append(row_value)
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                f"""
                SELECT *
                FROM wechat_group_topic_message_refs
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                params,
            ).fetchone()
        return dict(row) if row else None

    def append_summary_history(
        self,
        room_id: str,
        thread_id: str,
        summary_text: str,
        snapshot: Optional[Dict[str, Any]] = None,
        summary_id: str = "",
        created_at: Optional[int] = None,
    ) -> Dict[str, Any]:
        room_text = _require_text("room_id", room_id)
        thread_text = _require_text("thread_id", thread_id)
        summary = _require_text("summary_text", summary_text)
        summary_id = str(summary_id or uuid4().hex)
        created_ts = _coerce_timestamp(created_at)
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO wechat_group_topic_summary_history (
                        summary_id, room_id, thread_id, summary_text, snapshot_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        summary_id,
                        room_text,
                        thread_text,
                        summary,
                        json.dumps(snapshot or {}, ensure_ascii=False),
                        created_ts,
                    ),
                )
        return self.list_summary_history(room_text, thread_text, limit=1)[0]

    def list_summary_history(self, room_id: str, thread_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        room_text = str(room_id or "").strip()
        thread_text = str(thread_id or "").strip()
        if not room_text or not thread_text:
            return []
        max_limit = min(max(int(limit or 10), 1), 100)
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM wechat_group_topic_summary_history
                WHERE room_id = ? AND thread_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (room_text, thread_text, max_limit),
            ).fetchall()
        return [self._summary_row_to_dict(row) for row in rows]

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS wechat_group_topic_threads (
                        thread_id TEXT PRIMARY KEY,
                        room_id TEXT NOT NULL,
                        title TEXT NOT NULL,
                        gist TEXT NOT NULL DEFAULT '',
                        facts_json TEXT NOT NULL DEFAULT '[]',
                        participants_json TEXT NOT NULL DEFAULT '[]',
                        open_loops_json TEXT NOT NULL DEFAULT '[]',
                        last_message_id TEXT NOT NULL DEFAULT '',
                        last_row_id INTEGER NOT NULL DEFAULT 0,
                        message_count INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL DEFAULT 'active',
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_wechat_group_topic_threads_room_status
                    ON wechat_group_topic_threads(room_id, status, updated_at)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS wechat_group_topic_message_refs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        message_id TEXT NOT NULL DEFAULT '',
                        row_id INTEGER NOT NULL DEFAULT 0,
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_wechat_group_topic_message_refs_room_message
                    ON wechat_group_topic_message_refs(room_id, message_id, row_id)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS wechat_group_topic_summary_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        summary_id TEXT NOT NULL UNIQUE,
                        room_id TEXT NOT NULL,
                        thread_id TEXT NOT NULL,
                        summary_text TEXT NOT NULL,
                        snapshot_json TEXT NOT NULL DEFAULT '{}',
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_wechat_group_topic_summary_history_room_thread
                    ON wechat_group_topic_summary_history(room_id, thread_id, created_at)
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)

    @staticmethod
    def _thread_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["facts"] = _loads_json(data.pop("facts_json", "[]"), [])
        data["participants"] = _loads_json(data.pop("participants_json", "[]"), [])
        data["open_loops"] = _loads_json(data.pop("open_loops_json", "[]"), [])
        return data

    @staticmethod
    def _summary_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["snapshot"] = _loads_json(data.pop("snapshot_json", "{}"), {})
        return data


def _require_text(name: str, value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _normalize_list(value: Any) -> List[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    result = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _loads_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, type(default)) else default
    except Exception:
        return default


def _coerce_timestamp(value: Any = None) -> int:
    try:
        return int(value)
    except Exception:
        return int(time.time())
