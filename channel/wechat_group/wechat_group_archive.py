"""SQLite archive for WeChat group messages."""

import ast
import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from typing import Any, Dict, List, Optional
from uuid import uuid4

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
                        json.dumps(metadata or {}, ensure_ascii=False),
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

    def record_image_create_usage(
        self,
        room_id: str,
        sender_id: str = "",
        prompt: str = "",
        status: str = "accepted",
        created_at: Optional[int] = None,
    ) -> None:
        if not room_id:
            return
        ts = _coerce_timestamp(created_at)
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO wechat_group_image_create_usage (
                        room_id, sender_id, prompt, status, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        str(room_id),
                        str(sender_id or ""),
                        str(prompt or "")[:2000],
                        str(status or "accepted"),
                        ts,
                    ),
                )

    def count_image_create_usage(
        self,
        room_id: str,
        window_seconds: int = 3600,
        now: Optional[int] = None,
    ) -> int:
        if not room_id:
            return 0
        cutoff = _coerce_timestamp(now) - max(int(window_seconds or 3600), 1)
        with self._lock, closing(self._connect()) as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM wechat_group_image_create_usage
                WHERE room_id = ?
                  AND status = 'accepted'
                  AND created_at >= ?
                """,
                (str(room_id), cutoff),
            ).fetchone()
        return int(row[0] or 0) if row else 0

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

    def get_message_by_id(self, room_id: str, message_id: str) -> Optional[Dict[str, Any]]:
        if not room_id or not message_id:
            return None
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT id, message_id, room_id, room_name, sender_id, sender_nickname,
                       message_type, text, media_path, is_at, metadata, created_at
                FROM wechat_group_messages
                WHERE room_id = ? AND message_id = ?
                LIMIT 1
                """,
                (str(room_id), str(message_id)),
            ).fetchone()
        return self._message_row_to_dict(row) if row else None

    def get_messages_for_distill(
        self,
        room_id: str,
        since_ts: int,
        until_ts: Optional[int] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        if not room_id:
            return []
        max_limit = min(max(int(limit or 200), 1), 500)
        until = _coerce_timestamp(until_ts)
        since = int(since_ts or 0)
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, message_id, room_id, room_name, sender_id, sender_nickname,
                       message_type, text, media_path, is_at, metadata, created_at
                FROM wechat_group_messages
                WHERE room_id = ?
                  AND created_at >= ?
                  AND created_at <= ?
                ORDER BY created_at ASC, id ASC
                LIMIT ?
                """,
                (str(room_id), since, until, max_limit),
            ).fetchall()
        return [self._message_row_to_dict(row) for row in rows]

    def list_members(
        self,
        room_id: str,
        query: str = "",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        if not room_id:
            return []
        max_limit = min(max(int(limit or 20), 1), 100)
        q = str(query or "").strip().lower()
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT sender_id, sender_nickname, metadata, created_at
                FROM wechat_group_messages
                WHERE room_id = ?
                  AND COALESCE(sender_id, '') != ''
                ORDER BY created_at DESC, id DESC
                """,
                (str(room_id),),
            ).fetchall()

        members: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            sender_id = str(row["sender_id"] or "").strip()
            if not sender_id:
                continue
            nickname = str(row["sender_nickname"] or "").strip()
            metadata = _parse_metadata(row["metadata"])
            wechat_id = str(metadata.get("wechat_id") or metadata.get("wechatId") or "").strip()
            haystack = " ".join([sender_id, nickname, wechat_id]).lower()
            if q and q not in haystack:
                continue
            if sender_id not in members:
                members[sender_id] = {
                    "sender_id": sender_id,
                    "sender_nickname": nickname or sender_id,
                    "wechat_id": wechat_id,
                    "last_seen_at": int(row["created_at"] or 0),
                    "message_count": 0,
                }
            members[sender_id]["message_count"] += 1

        return list(members.values())[:max_limit]

    def create_distill_run(
        self,
        room_id: str,
        since_ts: int,
        until_ts: int,
        message_count: int,
    ) -> str:
        run_id = uuid4().hex
        now = int(time.time())
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO wechat_group_memory_distill_runs (
                        run_id, room_id, since_ts, until_ts, message_count,
                        status, auto_applied_count, candidate_count, started_at
                    ) VALUES (?, ?, ?, ?, ?, 'running', 0, 0, ?)
                    """,
                    (run_id, room_id, since_ts, until_ts, message_count, now),
                )
        return run_id

    def finish_distill_run(
        self,
        run_id: str,
        status: str,
        auto_applied_count: int = 0,
        candidate_count: int = 0,
        failed_reason: str = "",
        raw_output_summary: str = "",
    ) -> None:
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE wechat_group_memory_distill_runs
                    SET status = ?,
                        auto_applied_count = ?,
                        candidate_count = ?,
                        failed_reason = ?,
                        raw_output_summary = ?,
                        finished_at = ?
                    WHERE run_id = ?
                    """,
                    (
                        status,
                        int(auto_applied_count or 0),
                        int(candidate_count or 0),
                        failed_reason,
                        raw_output_summary[:2000],
                        int(time.time()),
                        run_id,
                    ),
                )

    def list_distill_runs(
        self,
        room_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM wechat_group_memory_distill_runs
                WHERE room_id = ?
                ORDER BY started_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (room_id, min(max(int(limit or 20), 1), 100), max(int(offset or 0), 0)),
            ).fetchall()
        return [dict(row) for row in rows]

    def insert_memory_candidate(
        self,
        run_id: str,
        room_id: str,
        candidate_type: str,
        content: Dict[str, Any],
        confidence: float,
        evidence_message_ids: List[str],
        evidence_text: str = "",
        status: str = "pending",
        target_sender_id: str = "",
        target_sender_nickname: str = "",
        applied_memory_id: str = "",
    ) -> Dict[str, Any]:
        candidate_id = uuid4().hex
        now = int(time.time())
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO wechat_group_memory_candidates (
                        candidate_id, run_id, room_id, candidate_type,
                        target_sender_id, target_sender_nickname, content_json,
                        confidence, evidence_message_ids, evidence_text,
                        status, applied_memory_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate_id,
                        run_id,
                        room_id,
                        candidate_type,
                        target_sender_id,
                        target_sender_nickname,
                        json.dumps(content or {}, ensure_ascii=False),
                        float(confidence or 0.0),
                        json.dumps(evidence_message_ids or [], ensure_ascii=False),
                        evidence_text,
                        status,
                        applied_memory_id,
                        now,
                    ),
                )
        return self.get_memory_candidate(room_id, candidate_id) or {}

    def list_memory_candidates(
        self,
        room_id: str,
        status: Optional[str] = None,
        candidate_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        params: List[Any] = [room_id]
        clauses = ["room_id = ?"]
        if status:
            clauses.append("status = ?")
            params.append(status)
        if candidate_type:
            clauses.append("candidate_type = ?")
            params.append(candidate_type)
        params.extend([min(max(int(limit or 20), 1), 100), max(int(offset or 0), 0)])
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM wechat_group_memory_candidates
                WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [self._candidate_row_to_dict(row) for row in rows]

    def get_memory_candidate(self, room_id: str, candidate_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM wechat_group_memory_candidates
                WHERE room_id = ? AND candidate_id = ?
                """,
                (room_id, candidate_id),
            ).fetchone()
        return self._candidate_row_to_dict(row) if row else None

    def update_memory_candidate_status(
        self,
        room_id: str,
        candidate_id: str,
        status: str,
        applied_memory_id: str = "",
        review_note: str = "",
    ) -> Dict[str, Any]:
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    UPDATE wechat_group_memory_candidates
                    SET status = ?,
                        applied_memory_id = COALESCE(NULLIF(?, ''), applied_memory_id),
                        review_note = ?,
                        reviewed_at = ?
                    WHERE room_id = ? AND candidate_id = ?
                    """,
                    (status, applied_memory_id, review_note, int(time.time()), room_id, candidate_id),
                )
        row = self.get_memory_candidate(room_id, candidate_id)
        if not row:
            raise ValueError("candidate_id is not found in this room")
        return row

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
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS wechat_group_image_create_usage (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        room_id TEXT NOT NULL,
                        sender_id TEXT,
                        prompt TEXT,
                        status TEXT NOT NULL,
                        created_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_wechat_group_image_create_usage_room_time
                    ON wechat_group_image_create_usage(room_id, status, created_at)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS wechat_group_memory_distill_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL UNIQUE,
                        room_id TEXT NOT NULL,
                        since_ts INTEGER NOT NULL,
                        until_ts INTEGER NOT NULL,
                        message_count INTEGER NOT NULL DEFAULT 0,
                        status TEXT NOT NULL,
                        auto_applied_count INTEGER NOT NULL DEFAULT 0,
                        candidate_count INTEGER NOT NULL DEFAULT 0,
                        failed_reason TEXT,
                        raw_output_summary TEXT,
                        started_at INTEGER NOT NULL,
                        finished_at INTEGER
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_wechat_group_distill_runs_room_time
                    ON wechat_group_memory_distill_runs(room_id, started_at, id)
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS wechat_group_memory_candidates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        candidate_id TEXT NOT NULL UNIQUE,
                        run_id TEXT NOT NULL,
                        room_id TEXT NOT NULL,
                        candidate_type TEXT NOT NULL,
                        target_sender_id TEXT,
                        target_sender_nickname TEXT,
                        content_json TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        evidence_message_ids TEXT,
                        evidence_text TEXT,
                        status TEXT NOT NULL,
                        applied_memory_id TEXT,
                        review_note TEXT,
                        created_at INTEGER NOT NULL,
                        reviewed_at INTEGER
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_wechat_group_memory_candidates_room_status
                    ON wechat_group_memory_candidates(room_id, status, candidate_type, created_at)
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)

    @staticmethod
    def _message_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        metadata = _parse_metadata(data.get("metadata"))
        data["metadata"] = metadata
        at_list = metadata.get("at_list") if isinstance(metadata, dict) else []
        data["at_list"] = [str(item) for item in at_list or [] if str(item or "").strip()]
        return data

    @staticmethod
    def _candidate_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["content"] = _loads_json(data.pop("content_json", "{}"), {})
        data["evidence_message_ids"] = _loads_json(data.get("evidence_message_ids"), [])
        return data


def _coerce_timestamp(value: Any = None) -> int:
    try:
        return int(value)
    except Exception:
        return int(time.time())


def _parse_metadata(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    text = str(value)
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass
    try:
        parsed = ast.literal_eval(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _loads_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default
