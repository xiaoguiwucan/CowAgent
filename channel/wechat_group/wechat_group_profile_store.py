"""SQLite store for global WeChat group member profiles."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from typing import Any, Dict, List, Optional


def _default_profile_store_path() -> str:
    data_root = os.environ.get("COW_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".cow")
    return os.path.join(os.path.expanduser(data_root), "wechat_group", "wechat_group_profiles.db")


class WechatGroupProfileStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _default_profile_store_path()
        self._lock = threading.Lock()
        parent = os.path.dirname(self.db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._init_schema()

    def upsert_profile(self, sender_id: str, **fields) -> Dict[str, Any]:
        sender_id = _require_text("sender_id", sender_id)
        now = int(time.time())
        existing = self.get_profile(sender_id) or {}
        data = {
            "primary_nickname": fields.get("primary_nickname", existing.get("primary_nickname", "")),
            "speak_style": fields.get("speak_style", existing.get("speak_style", "")),
            "interests": fields.get("interests", existing.get("interests", [])),
            "common_words": fields.get("common_words", existing.get("common_words", [])),
            "activity_score": fields.get("activity_score", existing.get("activity_score", 0)),
            "intimacy_score": fields.get("intimacy_score", existing.get("intimacy_score", 0)),
            "msg_count": fields.get("msg_count", existing.get("msg_count", 0)),
            "last_seen_at": fields.get("last_seen_at", existing.get("last_seen_at", 0)),
            "created_at": existing.get("created_at") or fields.get("created_at") or now,
            "updated_at": fields.get("updated_at") or now,
        }
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO wechat_group_global_profiles (
                        sender_id, primary_nickname, speak_style, interests_json,
                        common_words_json, activity_score, intimacy_score, msg_count,
                        last_seen_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(sender_id) DO UPDATE SET
                        primary_nickname = excluded.primary_nickname,
                        speak_style = excluded.speak_style,
                        interests_json = excluded.interests_json,
                        common_words_json = excluded.common_words_json,
                        activity_score = excluded.activity_score,
                        intimacy_score = excluded.intimacy_score,
                        msg_count = excluded.msg_count,
                        last_seen_at = excluded.last_seen_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        sender_id,
                        str(data["primary_nickname"] or ""),
                        str(data["speak_style"] or ""),
                        _json_dumps(_normalize_list(data["interests"])),
                        _json_dumps(_normalize_list(data["common_words"])),
                        int(data["activity_score"] or 0),
                        int(data["intimacy_score"] or 0),
                        int(data["msg_count"] or 0),
                        int(data["last_seen_at"] or 0),
                        int(data["created_at"] or now),
                        int(data["updated_at"] or now),
                    ),
                )
        return self.get_profile(sender_id) or {}

    def get_profile(self, sender_id: str) -> Optional[Dict[str, Any]]:
        sender_id = str(sender_id or "").strip()
        if not sender_id:
            return None
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT *
                FROM wechat_group_global_profiles
                WHERE sender_id = ?
                LIMIT 1
                """,
                (sender_id,),
            ).fetchone()
        return self._profile_row_to_dict(row) if row else None

    def list_profiles(self, query: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        max_limit = min(max(int(limit or 20), 1), 200)
        q = str(query or "").strip()
        params: List[Any] = []
        where = ""
        if q:
            where = "WHERE sender_id LIKE ? OR primary_nickname LIKE ?"
            like = f"%{q}%"
            params.extend([like, like])
        params.append(max_limit)
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT *
                FROM wechat_group_global_profiles
                {where}
                ORDER BY updated_at DESC, sender_id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._profile_row_to_dict(row) for row in rows]

    def list_all_profiles(self) -> List[Dict[str, Any]]:
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM wechat_group_global_profiles
                ORDER BY updated_at DESC, sender_id ASC
                """
            ).fetchall()
        return [self._profile_row_to_dict(row) for row in rows]

    def upsert_name_record(
        self,
        sender_id: str,
        room_id: str,
        display_name: str,
        room_name: str = "",
        source_kind: str = "message",
        last_seen_at: int = 0,
    ) -> None:
        sender_id = _require_text("sender_id", sender_id)
        room_id = str(room_id or "")
        display_name = _require_text("display_name", display_name)
        now = int(time.time())
        with self._lock, closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    INSERT INTO wechat_group_profile_name_records (
                        sender_id, room_id, room_name, display_name, source_kind,
                        last_seen_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sender_id,
                        room_id,
                        str(room_name or ""),
                        display_name,
                        str(source_kind or "message"),
                        int(last_seen_at or 0),
                        now,
                        now,
                    ),
                )

    def list_name_records(self, sender_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        sender_id = str(sender_id or "").strip()
        if not sender_id:
            return []
        with self._lock, closing(self._connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT *
                FROM wechat_group_profile_name_records
                WHERE sender_id = ?
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (sender_id, min(max(int(limit or 20), 1), 100)),
            ).fetchall()
        return [dict(row) for row in rows]

    def _init_schema(self) -> None:
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS wechat_group_global_profiles (
                        sender_id TEXT PRIMARY KEY,
                        primary_nickname TEXT NOT NULL DEFAULT '',
                        speak_style TEXT NOT NULL DEFAULT '',
                        interests_json TEXT NOT NULL DEFAULT '[]',
                        common_words_json TEXT NOT NULL DEFAULT '[]',
                        activity_score INTEGER NOT NULL DEFAULT 0,
                        intimacy_score INTEGER NOT NULL DEFAULT 0,
                        msg_count INTEGER NOT NULL DEFAULT 0,
                        last_seen_at INTEGER NOT NULL DEFAULT 0,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS wechat_group_profile_name_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        sender_id TEXT NOT NULL,
                        room_id TEXT NOT NULL,
                        room_name TEXT NOT NULL DEFAULT '',
                        display_name TEXT NOT NULL,
                        source_kind TEXT NOT NULL DEFAULT 'message',
                        last_seen_at INTEGER NOT NULL DEFAULT 0,
                        created_at INTEGER NOT NULL,
                        updated_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_wechat_group_profile_name_records_sender
                    ON wechat_group_profile_name_records(sender_id, updated_at, id)
                    """
                )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=10)

    @staticmethod
    def _profile_row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)
        data["interests"] = _loads_json(data.pop("interests_json", "[]"), [])
        data["common_words"] = _loads_json(data.pop("common_words_json", "[]"), [])
        return data


def _require_text(name: str, value: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _normalize_list(value: Any) -> List[str]:
    if value is None:
        items = []
    elif isinstance(value, list):
        items = value
    else:
        items = str(value).replace("\n", ",").split(",")
    result = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads_json(value: Any, default: Any) -> Any:
    if not value:
        return default
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, type(default)) else default
    except Exception:
        return default
