"""Wechat group long-term memory adapter."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from agent.memory.manager import MemoryManager
from agent.memory.scope import MemoryScope
from config import conf


class WechatGroupMemoryService:
    """Scoped memory adapter for WeChat group memories and member profiles."""

    def __init__(
        self,
        memory_manager: MemoryManager,
        allowed_room_ids: Optional[List[str]] = None,
        memory_enabled: Optional[bool] = None,
        member_memory_enabled: Optional[bool] = None,
    ):
        self.memory_manager = memory_manager
        self.allowed_room_ids = allowed_room_ids
        self.memory_enabled = (
            conf().get("wechat_group_memory_enabled", True)
            if memory_enabled is None else memory_enabled
        )
        self.member_memory_enabled = (
            conf().get("wechat_group_member_memory_enabled", True)
            if member_memory_enabled is None else member_memory_enabled
        )
        self.group_memory_limit = int(conf().get("wechat_group_memory_context_limit", 5) or 5)
        self.member_memory_limit = int(conf().get("wechat_group_member_memory_context_limit", 1) or 1)
        self._ensure_revision_table()

    async def add_group_memory(
        self,
        room_id: str,
        content: str,
        source_message_ids: Optional[List[str]] = None,
        source_summary: str = "",
        created_by: str = "ui",
    ) -> Dict:
        room_id = self._require_room(room_id)
        content = self._require_text("content", content)
        metadata = {
            "memory_type": "group_memory",
            "source_summary": source_summary,
            "created_by": created_by,
        }
        await self.memory_manager.add_memory(
            content,
            source="memory",
            metadata=metadata,
            memory_scope=MemoryScope.wechat_group(room_id),
            source_message_ids=source_message_ids,
        )
        rows = await self.list_group_memories(room_id, limit=1)
        return rows[0] if rows else {}

    async def list_group_memories(
        self,
        room_id: str,
        status: str = "active",
        limit: int = 20,
        offset: int = 0,
        query: Optional[str] = None,
    ) -> List[Dict]:
        room_id = self._require_room(room_id)
        rows = await self.memory_manager.list_memory_scope(
            MemoryScope.wechat_group(room_id),
            status=status,
            limit=limit,
            offset=offset,
            query=query,
        )
        return [self._result_to_dict(row) for row in rows]

    async def disable_group_memory(self, room_id: str, memory_id: str) -> bool:
        room_id = self._require_room(room_id)
        memory_id = self._require_text("memory_id", memory_id)
        updated = self.memory_manager.storage.update_chunk_status_by_scope(
            memory_id,
            MemoryScope.wechat_group(room_id),
            "disabled",
        )
        if not updated:
            raise ValueError("memory_id is not active in this room")
        return True

    async def upsert_member_profile(
        self,
        room_id: str,
        sender_id: str,
        sender_nickname: str = "",
        role: str = "",
        preferences: str = "",
        expertise: str = "",
        interaction_style: str = "",
        boundaries: str = "",
        evidence: str = "",
        aliases: Optional[Any] = None,
        source_message_ids: Optional[List[str]] = None,
        created_by: str = "ui",
        merge_existing_fields: bool = False,
    ) -> Dict:
        room_id = self._require_room(room_id)
        sender_id = self._require_text("sender_id", sender_id)
        fields = {
            "role": role.strip(),
            "preferences": preferences.strip(),
            "expertise": expertise.strip(),
            "interaction_style": interaction_style.strip(),
            "boundaries": boundaries.strip(),
            "evidence": evidence.strip(),
            "aliases": self._normalize_aliases(aliases),
        }
        if merge_existing_fields:
            fields = self._merge_existing_profile_fields(room_id, sender_id, fields)
        content = self._format_profile_content(sender_id, sender_nickname, fields)
        metadata = {
            "memory_type": "member_profile",
            "sender_id": sender_id,
            "sender_nickname": sender_nickname,
            "profile_fields": fields,
            "created_by": created_by,
        }
        scope = MemoryScope.wechat_group_member_profile(room_id, sender_id)
        path = (
            "memory/scoped/wechat_group_member_profile/wechat_group/"
            f"{self.memory_manager._safe_path_part(room_id)}/"
            f"{self.memory_manager._safe_path_part(sender_id)}/active_profile.md"
        )
        await self.memory_manager.add_memory(
            content,
            source="memory",
            path=path,
            metadata=metadata,
            memory_scope=scope,
            source_message_ids=source_message_ids,
        )
        self._insert_profile_revision(
            room_id=room_id,
            sender_id=sender_id,
            sender_nickname=sender_nickname,
            fields=fields,
            content=content,
            source_message_ids=source_message_ids,
        )
        profiles = await self.list_member_profiles(room_id, sender_id=sender_id, limit=1)
        return profiles[0] if profiles else {}

    async def list_member_profiles(
        self,
        room_id: str,
        sender_id: Optional[str] = None,
        status: str = "active",
        limit: int = 20,
        offset: int = 0,
        query: Optional[str] = None,
    ) -> List[Dict]:
        room_id = self._require_room(room_id)
        if sender_id:
            rows = await self.memory_manager.list_memory_scope(
                MemoryScope.wechat_group_member_profile(room_id, sender_id),
                status=status,
                limit=limit,
                offset=offset,
                query=query,
            )
        else:
            rows = self.memory_manager.storage.list_chunks_by_scope_type(
                scope_type="wechat_group_member_profile",
                scope_id=room_id,
                channel_type="wechat_group",
                status=status,
                limit=limit,
                offset=offset,
                query=query,
            )
        return [self._result_to_dict(row) for row in rows]

    def list_profile_revisions(
        self,
        room_id: str,
        sender_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict]:
        room_id = self._require_room(room_id)
        sender_id = self._require_text("sender_id", sender_id)
        rows = self.memory_manager.storage.conn.execute("""
            SELECT * FROM wechat_group_member_profile_revisions
            WHERE room_id = ? AND sender_id = ?
            ORDER BY revision_id DESC
            LIMIT ? OFFSET ?
        """, (room_id, sender_id, limit, offset)).fetchall()
        return [
            {
                "revision_id": row["revision_id"],
                "room_id": row["room_id"],
                "sender_id": row["sender_id"],
                "sender_nickname": row["sender_nickname"],
                "profile_fields": json.loads(row["profile_fields"] or "{}"),
                "content": row["content"],
                "source_message_ids": json.loads(row["source_message_ids"] or "[]"),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    async def disable_member_profile(self, room_id: str, sender_id: str) -> bool:
        room_id = self._require_room(room_id)
        sender_id = self._require_text("sender_id", sender_id)
        rows = await self.list_member_profiles(room_id, sender_id=sender_id, limit=1)
        if not rows:
            raise ValueError("sender_id has no active profile in this room")
        updated = self.memory_manager.storage.update_chunk_status_by_scope(
            rows[0]["id"],
            MemoryScope.wechat_group_member_profile(room_id, sender_id),
            "disabled",
        )
        if not updated:
            raise ValueError("profile is not active in this room")
        return True

    def get_summary(self, room_id: Optional[str] = None) -> Dict:
        if room_id:
            room_id = self._require_room(room_id)
        return {
            "room_id": room_id or "",
            "group_memory_count": self._count_chunks("wechat_group", room_id, "active"),
            "member_profile_count": self._count_chunks("wechat_group_member_profile", room_id, "active"),
            "disabled_count": (
                self._count_chunks("wechat_group", room_id, "disabled")
                + self._count_chunks("wechat_group_member_profile", room_id, "disabled")
            ),
            "latest_updated_at": self._latest_updated_at(room_id),
        }

    def list_group_summaries(self, rooms: List[Dict]) -> List[Dict]:
        summaries = []
        for room in rooms or []:
            room_id = str(room.get("id") or room.get("room_id") or "").strip()
            if not room_id:
                continue
            self._require_room(room_id)
            summary = self.get_summary(room_id)
            summary["room_name"] = room.get("name") or room.get("room_name") or room_id
            summaries.append(summary)
        return summaries

    async def preview_prompt_memories(
        self,
        room_id: str,
        sender_id: str,
        query: str,
        mentioned_sender_ids: Optional[List[str]] = None,
        bot_sender_id: Optional[str] = None,
    ) -> Dict:
        room_id = self._require_room(room_id)
        sender_id = self._require_text("sender_id", sender_id)
        filtered_reasons = []
        sections = []
        group_memories = []
        speaker_profile = None
        mentioned_profiles = []

        if not self.memory_enabled and not self.member_memory_enabled:
            return {
                "content": "",
                "group_memories": [],
                "speaker_profile": None,
                "mentioned_profiles": [],
                "filtered_reasons": ["memory disabled"],
            }

        if self.memory_enabled:
            results = await self.memory_manager.search(
                query or "群记忆",
                memory_scope=MemoryScope.wechat_group(room_id),
                max_results=self.group_memory_limit,
                min_score=0.0,
            )
            group_memories = [self._result_to_dict(row) for row in results]
            if not group_memories:
                group_memories = await self.list_group_memories(
                    room_id,
                    limit=self.group_memory_limit,
                )
            for item in group_memories:
                sections.append(f"[group_memory]\n{item['content']}")
        else:
            filtered_reasons.append("group memory disabled")

        if self.member_memory_enabled:
            speaker_rows = await self.list_member_profiles(room_id, sender_id=sender_id, limit=1)
            if speaker_rows:
                speaker_profile = speaker_rows[0]
                sections.append(f"[speaker_profile sender_id=\"{sender_id}\"]\n{speaker_profile['content']}")

            mentioned_ids = self._filtered_mentioned_ids(
                mentioned_sender_ids or [],
                sender_id=sender_id,
                bot_sender_id=bot_sender_id,
            )

            for mentioned_id in mentioned_ids:
                rows = await self.list_member_profiles(room_id, sender_id=mentioned_id, limit=1)
                if rows:
                    profile = rows[0]
                    mentioned_profiles.append(profile)
                    sections.append(f"[mentioned_profile sender_id=\"{mentioned_id}\"]\n{profile['content']}")
                else:
                    filtered_reasons.append(f"no active profile: {mentioned_id}")

            if not mentioned_ids:
                name_matches, nickname_reasons = await self._match_profiles_by_query_nickname(
                    room_id=room_id,
                    query=query,
                    excluded_sender_ids=self._excluded_mentioned_ids(sender_id, bot_sender_id),
                )
                filtered_reasons.extend(nickname_reasons)
                for profile, matched_by in name_matches:
                    mentioned_profiles.append(profile)
                    mentioned_id = profile["subject_id"]
                    sections.append(
                        f"[mentioned_profile sender_id=\"{mentioned_id}\" matched_by=\"{matched_by}\"]\n"
                        f"{profile['content']}"
                    )
        else:
            filtered_reasons.append("member profile memory disabled")

        content = ""
        if sections:
            content = "<wechat-group-memory>\n{}\n</wechat-group-memory>".format(
                "\n\n".join(sections)
            )
        return {
            "content": content,
            "group_memories": group_memories,
            "speaker_profile": speaker_profile,
            "mentioned_profiles": mentioned_profiles,
            "filtered_reasons": filtered_reasons,
        }

    def preview_prompt_memories_sync(self, **kwargs) -> Dict:
        """Synchronous wrapper for the existing ChatChannel compose path."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.preview_prompt_memories(**kwargs))
        raise RuntimeError("preview_prompt_memories_sync cannot run inside an active event loop")

    def _ensure_revision_table(self):
        self.memory_manager.storage.conn.execute("""
            CREATE TABLE IF NOT EXISTS wechat_group_member_profile_revisions (
                revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id TEXT NOT NULL,
                sender_id TEXT NOT NULL,
                sender_nickname TEXT,
                profile_fields TEXT NOT NULL,
                content TEXT NOT NULL,
                source_message_ids TEXT,
                created_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)
        self.memory_manager.storage.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_wechat_group_profile_revisions_scope
            ON wechat_group_member_profile_revisions(room_id, sender_id, revision_id)
        """)
        self.memory_manager.storage.conn.commit()

    def _insert_profile_revision(
        self,
        room_id: str,
        sender_id: str,
        sender_nickname: str,
        fields: Dict[str, str],
        content: str,
        source_message_ids: Optional[List[str]],
    ):
        self.memory_manager.storage.conn.execute("""
            INSERT INTO wechat_group_member_profile_revisions
            (room_id, sender_id, sender_nickname, profile_fields, content, source_message_ids)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            room_id,
            sender_id,
            sender_nickname,
            json.dumps(fields, ensure_ascii=False),
            content,
            json.dumps(source_message_ids or [], ensure_ascii=False),
        ))
        self.memory_manager.storage.conn.commit()

    def _merge_existing_profile_fields(
        self,
        room_id: str,
        sender_id: str,
        fields: Dict[str, str],
    ) -> Dict[str, str]:
        row = self.memory_manager.storage.conn.execute("""
            SELECT metadata
            FROM chunks
            WHERE scope_type = 'wechat_group_member_profile'
              AND scope_id = ?
              AND channel_type = 'wechat_group'
              AND subject_id = ?
              AND status = 'active'
            ORDER BY updated_at DESC
            LIMIT 1
        """, (room_id, sender_id)).fetchone()
        if not row:
            return fields
        try:
            metadata = json.loads(row["metadata"] or "{}")
            existing = metadata.get("profile_fields") or {}
        except Exception:
            existing = {}
        merged = dict(existing)
        for key, value in fields.items():
            if value:
                merged[key] = value
        for key in ("role", "preferences", "expertise", "interaction_style", "boundaries", "evidence"):
            merged.setdefault(key, "")
        merged["aliases"] = WechatGroupMemoryService._normalize_aliases(merged.get("aliases"))
        return merged

    def _count_chunks(self, scope_type: str, room_id: Optional[str], status: str) -> int:
        params = [scope_type, "wechat_group", status]
        room_clause = ""
        if room_id:
            room_clause = " AND scope_id = ?"
            params.append(room_id)
        row = self.memory_manager.storage.conn.execute(f"""
            SELECT COUNT(*) AS c
            FROM chunks
            WHERE scope_type = ?
              AND channel_type = ?
              AND status = ?
              {room_clause}
        """, params).fetchone()
        return int(row["c"] if row else 0)

    def _latest_updated_at(self, room_id: Optional[str]) -> Optional[int]:
        params = ["wechat_group", "wechat_group_member_profile"]
        room_clause = ""
        if room_id:
            room_clause = " AND scope_id = ?"
            params.append(room_id)
        row = self.memory_manager.storage.conn.execute(f"""
            SELECT MAX(updated_at) AS latest
            FROM chunks
            WHERE scope_type IN (?, ?)
              AND channel_type = 'wechat_group'
              {room_clause}
        """, params).fetchone()
        return row["latest"] if row and row["latest"] is not None else None

    def _require_room(self, room_id: str) -> str:
        room_id = self._require_text("room_id", room_id)
        allowed = self.allowed_room_ids
        if allowed is None:
            allowed = conf().get("wechat_group_room_ids", [])
        if allowed and room_id not in allowed:
            raise ValueError(f"room_id is not selected: {room_id}")
        return room_id

    @staticmethod
    def _require_text(name: str, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError(f"{name} is required")
        return value

    @staticmethod
    def _format_profile_content(sender_id: str, sender_nickname: str, fields: Dict[str, str]) -> str:
        aliases = WechatGroupMemoryService._normalize_aliases(fields.get("aliases"))
        lines = [
            f"sender_id: {sender_id}",
            f"sender_nickname: {sender_nickname or sender_id}",
            f"aliases: {', '.join(aliases)}",
            f"role: {fields['role']}",
            f"preferences: {fields['preferences']}",
            f"expertise: {fields['expertise']}",
            f"interaction_style: {fields['interaction_style']}",
            f"boundaries: {fields['boundaries']}",
            f"evidence: {fields['evidence']}",
        ]
        return "\n".join(line for line in lines if not line.endswith(": "))

    @staticmethod
    def _filtered_mentioned_ids(
        mentioned_sender_ids: List[str],
        sender_id: str,
        bot_sender_id: Optional[str],
    ) -> List[str]:
        result = []
        excluded = WechatGroupMemoryService._excluded_mentioned_ids(sender_id, bot_sender_id)
        for item in mentioned_sender_ids:
            item = (item or "").strip()
            if not item or item in excluded or item in result:
                continue
            result.append(item)
        return result

    async def _match_profiles_by_query_nickname(
        self,
        room_id: str,
        query: str,
        excluded_sender_ids: set,
    ) -> Tuple[List[Dict], List[str]]:
        query_text = self._normalize_lookup_text(query)
        if not query_text:
            return [], []
        profiles = await self.list_member_profiles(room_id, limit=200)
        matched_by_name: Dict[Tuple[str, str], List[Dict]] = {}
        for profile in profiles:
            sender_id = (profile.get("subject_id") or "").strip()
            if not sender_id or sender_id in excluded_sender_ids:
                continue
            seen_profile_candidates = set()
            for match_type, name in self._profile_lookup_names(profile):
                name_key = self._normalize_lookup_text(name)
                if len(name_key) < 2 or name_key not in query_text:
                    continue
                match_key = (match_type, name)
                if match_key in seen_profile_candidates:
                    continue
                seen_profile_candidates.add(match_key)
                matched_by_name.setdefault(match_key, []).append(profile)

        matches = []
        reasons = []
        matched_sender_ids = set()
        for (match_type, name), items in matched_by_name.items():
            unique_items = []
            seen_sender_ids = set()
            for item in items:
                item_sender_id = (item.get("subject_id") or "").strip()
                if not item_sender_id or item_sender_id in seen_sender_ids:
                    continue
                seen_sender_ids.add(item_sender_id)
                unique_items.append(item)
            if len(unique_items) == 1:
                sender_id = (unique_items[0].get("subject_id") or "").strip()
                if sender_id not in matched_sender_ids:
                    matched_sender_ids.add(sender_id)
                    matches.append((unique_items[0], match_type))
            else:
                reasons.append(f"{match_type} match ambiguous: {name}")
        if not matches and not reasons:
            reasons.append("nickname match not found")
        return matches, reasons

    @staticmethod
    def _excluded_mentioned_ids(sender_id: str, bot_sender_id: Optional[str]) -> set:
        excluded = {(sender_id or "").strip()}
        if bot_sender_id:
            excluded.add(bot_sender_id.strip())
        return {item for item in excluded if item}

    @staticmethod
    def _profile_nickname(profile: Dict) -> str:
        metadata = profile.get("metadata") or {}
        return str(metadata.get("sender_nickname") or "").strip()

    @staticmethod
    def _profile_aliases(profile: Dict) -> List[str]:
        metadata = profile.get("metadata") or {}
        fields = metadata.get("profile_fields") or {}
        aliases = fields.get("aliases")
        if aliases is None:
            aliases = metadata.get("aliases")
        return WechatGroupMemoryService._normalize_aliases(aliases)

    @staticmethod
    def _profile_lookup_names(profile: Dict) -> List[Tuple[str, str]]:
        result = []
        nickname = WechatGroupMemoryService._profile_nickname(profile)
        if nickname:
            result.append(("nickname", nickname))
        for alias in WechatGroupMemoryService._profile_aliases(profile):
            result.append(("alias", alias))
        return result

    @staticmethod
    def _normalize_aliases(value: Any) -> List[str]:
        if value is None:
            raw_items = []
        elif isinstance(value, list):
            raw_items = value
        else:
            raw_items = str(value).replace("\n", ",").split(",")
        result = []
        for item in raw_items:
            alias = str(item or "").strip()
            if alias and alias not in result:
                result.append(alias)
        return result

    @staticmethod
    def _normalize_lookup_text(value: str) -> str:
        return "".join(str(value or "").strip().lower().split())

    @staticmethod
    def _result_to_dict(result) -> Dict:
        return {
            "id": result.id,
            "content": result.snippet,
            "path": result.path,
            "scope_type": result.scope_type,
            "scope_id": result.scope_id,
            "channel_type": result.channel_type,
            "subject_id": result.subject_id,
            "status": result.status,
            "metadata": result.metadata or {},
            "source_message_ids": result.source_message_ids or [],
        }
