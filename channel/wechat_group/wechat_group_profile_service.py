"""Service layer for global WeChat group member profiles."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from channel.wechat_group.wechat_group_archive import WechatGroupArchive
from channel.wechat_group.wechat_group_profile_store import WechatGroupProfileStore


class WechatGroupProfileService:
    def __init__(
        self,
        store: Optional[WechatGroupProfileStore] = None,
        archive: Optional[WechatGroupArchive] = None,
    ):
        self.store = store or WechatGroupProfileStore()
        self.archive = archive or WechatGroupArchive()

    def get_profile(self, sender_id: str, room_id: str = "") -> Optional[Dict[str, Any]]:
        profile = self.store.get_profile(sender_id)
        if not profile:
            return None
        room_text = str(room_id or "").strip()
        room_member_names = self._build_room_member_name_map(room_text)
        return self._attach_names_and_content(profile, room_id=room_text, room_member_names=room_member_names)

    def list_profiles(self, query: str = "", limit: int = 20, room_id: str = "") -> List[Dict[str, Any]]:
        max_limit = min(max(int(limit or 20), 1), 200)
        query_text = _normalize_lookup_text(query)
        room_text = str(room_id or "").strip()
        room_member_names = self._build_room_member_name_map(room_text)
        rows = [
            self._attach_names_and_content(row, room_id=room_text, room_member_names=room_member_names)
            for row in self.store.list_profiles(limit=200)
        ]
        if room_text:
            rows = [
                row
                for row in rows
                if str(row.get("sender_id") or "").strip() in room_member_names
                or any(str(item.get("room_id") or "") == room_text for item in row.get("room_summaries") or [])
            ]
        if query_text:
            rows = [row for row in rows if self._matches_profile(row, query_text)]
        rows.sort(key=lambda item: self._profile_sort_key(item, query_text))
        return rows[:max_limit]

    def upsert_manual_profile(
        self,
        sender_id: str,
        primary_nickname: str,
        speak_style: str,
        interests: List[str],
        common_words: List[str],
        aliases: List[str],
        room_id: str = "",
        room_name: str = "",
    ) -> Dict[str, Any]:
        normalized_primary = _normalize_display_name(primary_nickname, sender_id)
        normalized_aliases = _normalize_aliases(aliases, sender_id, normalized_primary)
        profile = self.store.upsert_profile(
            sender_id=sender_id,
            primary_nickname=normalized_primary,
            speak_style=speak_style,
            interests=_normalize_list(interests),
            common_words=_normalize_list(common_words),
        )
        self._record_aliases(
            sender_id=sender_id,
            aliases=normalized_aliases,
            room_id=room_id,
            room_name=room_name,
            last_seen_at=profile.get("last_seen_at", 0),
            source_kind="manual",
        )
        return self.get_profile(sender_id, room_id=room_id) or {}

    def merge_learned_profile(
        self,
        sender_id: str,
        primary_nickname: str,
        aliases: List[str],
        speak_style: str,
        interests: List[str],
        common_words: List[str],
        msg_delta: int,
        activity_delta: int,
        intimacy_delta: int,
        room_id: str,
        room_name: str,
        last_seen_at: int,
    ) -> Dict[str, Any]:
        existing = self.store.get_profile(sender_id) or {}
        existing_primary = str(existing.get("primary_nickname") or "").strip()
        normalized_primary = _choose_primary_nickname(primary_nickname, sender_id, existing_primary, aliases)
        normalized_aliases = _normalize_aliases(aliases, sender_id, normalized_primary)
        profile = self.store.upsert_profile(
            sender_id=sender_id,
            primary_nickname=normalized_primary,
            speak_style=speak_style,
            interests=_normalize_list(interests),
            common_words=_normalize_list(common_words),
            msg_count=int(existing.get("msg_count") or 0) + max(int(msg_delta or 0), 0),
            activity_score=int(existing.get("activity_score") or 0) + max(int(activity_delta or 0), 0),
            intimacy_score=int(existing.get("intimacy_score") or 0) + max(int(intimacy_delta or 0), 0),
            last_seen_at=max(int(existing.get("last_seen_at") or 0), int(last_seen_at or 0)),
        )
        self._record_aliases(
            sender_id=sender_id,
            aliases=normalized_aliases,
            room_id=room_id,
            room_name=room_name,
            last_seen_at=last_seen_at,
            source_kind="learning",
        )
        return self.get_profile(sender_id, room_id=room_id) or profile

    def resolve_profiles_for_prompt(
        self,
        sender_id: str,
        mentioned_sender_ids: List[str],
        query: str,
        bot_sender_id: str = "",
    ) -> Dict[str, Any]:
        speaker_profile = self.get_profile(sender_id)
        excluded = {item for item in [sender_id, bot_sender_id] if item}
        mentioned_profiles = []
        seen = set()
        for mentioned_id in mentioned_sender_ids or []:
            mentioned_id = str(mentioned_id or "").strip()
            if not mentioned_id or mentioned_id in excluded or mentioned_id in seen:
                continue
            profile = self.get_profile(mentioned_id)
            if profile:
                mentioned_profiles.append(profile)
                seen.add(mentioned_id)

        if not mentioned_profiles and query:
            for profile in self.list_profiles(query=query, limit=5):
                candidate_id = profile.get("sender_id") or ""
                if candidate_id and candidate_id not in excluded and candidate_id not in seen:
                    mentioned_profiles.append(profile)
                    seen.add(candidate_id)
                    break

        return {
            "speaker_profile": speaker_profile,
            "mentioned_profiles": mentioned_profiles,
        }

    def repair_historical_profile_names(self) -> Dict[str, int]:
        repaired = 0
        rows = self.store.list_all_profiles()
        for profile in rows:
            sender_id = str(profile.get("sender_id") or "").strip()
            if not sender_id:
                continue
            repaired_primary = self._repair_profile_primary_nickname(profile)
            if repaired_primary:
                repaired += 1
        return {
            "total": len(rows),
            "repaired": repaired,
        }

    def _record_aliases(
        self,
        sender_id: str,
        aliases: List[str],
        room_id: str,
        room_name: str,
        last_seen_at: int,
        source_kind: str,
    ) -> None:
        seen = set()
        for alias in _normalize_list(aliases):
            if alias in seen:
                continue
            seen.add(alias)
            self.store.upsert_name_record(
                sender_id=sender_id,
                room_id=room_id,
                room_name=room_name,
                display_name=alias,
                source_kind=source_kind,
                last_seen_at=last_seen_at,
            )

    def _attach_names_and_content(
        self,
        profile: Dict[str, Any],
        room_id: str = "",
        room_member_names: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        result = dict(profile)
        sender_id = str(result.get("sender_id") or "").strip()
        records = self._sanitize_name_records(sender_id, self.store.list_name_records(sender_id, limit=100))
        room_member_names = room_member_names or {}
        primary = self._pick_display_name(
            sender_id=sender_id,
            primary_nickname=result.get("primary_nickname", ""),
            records=records,
            room_id=room_id,
            room_member_names=room_member_names,
        )
        aliases = []
        for record in records:
            name = str(record.get("display_name") or "").strip()
            if name and name != primary and name not in aliases:
                aliases.append(name)
        room_summaries = self._build_room_summaries(records)
        latest_seen_at = max(
            [int(result.get("last_seen_at") or 0)] + [int(item.get("last_seen_at") or 0) for item in room_summaries]
        )
        room_text = str(room_id or "").strip()
        room_member_name = room_member_names.get(sender_id, "")
        if room_text and room_member_name and not any(str(item.get("room_id") or "") == room_text for item in room_summaries):
            room_summaries.insert(0, {
                "room_id": room_text,
                "room_name": self._resolve_room_name(room_text),
                "display_names": [room_member_name],
                "last_seen_at": latest_seen_at,
                "name_count": 1,
            })
        self._repair_profile_primary_nickname(result, preferred_primary=primary)
        result["primary_nickname"] = primary
        result["aliases"] = aliases
        result["name_records"] = records
        result["room_summaries"] = room_summaries
        result["last_seen_at"] = latest_seen_at
        result["content"] = self._format_profile_content(result)
        return result

    def _build_room_member_name_map(self, room_id: str) -> Dict[str, str]:
        room_text = str(room_id or "").strip()
        if not room_text:
            return {}
        rows = self.archive.list_members(room_text, limit=500)
        result: Dict[str, str] = {}
        for row in rows:
            sender_id = str(row.get("sender_id") or "").strip()
            display_name = _normalize_display_name(row.get("sender_nickname"), sender_id)
            if sender_id and display_name:
                result[sender_id] = display_name
        return result

    def _repair_profile_primary_nickname(
        self,
        profile: Dict[str, Any],
        preferred_primary: str = "",
    ) -> str:
        sender_id = str(profile.get("sender_id") or "").strip()
        if not sender_id:
            return ""
        current_primary = _normalize_display_name(profile.get("primary_nickname"), sender_id)
        if preferred_primary:
            candidate = _normalize_display_name(preferred_primary, sender_id)
        else:
            candidate = _normalize_display_name(self._find_repairable_primary_nickname(profile), sender_id)
        if not candidate or candidate == current_primary:
            return ""
        self.store.upsert_profile(sender_id=sender_id, primary_nickname=candidate)
        return candidate

    def _find_repairable_primary_nickname(self, profile: Dict[str, Any]) -> str:
        sender_id = str(profile.get("sender_id") or "").strip()
        latest = self.archive.find_latest_sender_name(sender_id)
        latest_name = _normalize_display_name((latest or {}).get("sender_nickname"), sender_id)
        if latest_name:
            return latest_name
        records = self._sanitize_name_records(sender_id, self.store.list_name_records(sender_id, limit=100))
        return self._pick_display_name(
            sender_id=sender_id,
            primary_nickname=profile.get("primary_nickname", ""),
            records=records,
            room_id="",
            room_member_names={},
        )

    @staticmethod
    def _sanitize_name_records(sender_id: str, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        cleaned = []
        for record in records:
            item = dict(record)
            item["display_name"] = _normalize_display_name(item.get("display_name"), sender_id)
            if item["display_name"]:
                cleaned.append(item)
        return cleaned

    @staticmethod
    def _pick_display_name(
        sender_id: str,
        primary_nickname: Any,
        records: List[Dict[str, Any]],
        room_id: str,
        room_member_names: Dict[str, str],
    ) -> str:
        room_text = str(room_id or "").strip()
        if room_text:
            room_name = room_member_names.get(sender_id, "")
            if room_name:
                return room_name
        primary = _normalize_display_name(primary_nickname, sender_id)
        if primary:
            return primary
        for record in records:
            room_match = not room_text or str(record.get("room_id") or "").strip() == room_text
            display_name = str(record.get("display_name") or "").strip()
            if room_match and display_name:
                return display_name
        for record in records:
            display_name = str(record.get("display_name") or "").strip()
            if display_name:
                return display_name
        return str(sender_id or "").strip()

    def _build_room_summaries(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for record in records:
            room_id = str(record.get("room_id") or "").strip()
            if not room_id:
                continue
            summary = grouped.setdefault(room_id, {
                "room_id": room_id,
                "room_name": str(record.get("room_name") or "").strip(),
                "display_names": [],
                "last_seen_at": 0,
                "name_count": 0,
            })
            room_name = str(record.get("room_name") or "").strip()
            if room_name and not summary["room_name"]:
                summary["room_name"] = room_name
            display_name = str(record.get("display_name") or "").strip()
            if display_name and display_name not in summary["display_names"]:
                summary["display_names"].append(display_name)
            summary["name_count"] += 1
            summary["last_seen_at"] = max(int(summary["last_seen_at"] or 0), int(record.get("last_seen_at") or 0))
        for summary in grouped.values():
            if not str(summary.get("room_name") or "").strip():
                summary["room_name"] = self._resolve_room_name(summary.get("room_id"))
        return sorted(
            grouped.values(),
            key=lambda item: (-int(item.get("last_seen_at") or 0), item.get("room_id") or ""),
        )

    def _resolve_room_name(self, room_id: Any) -> str:
        try:
            return self.archive.find_room_name(str(room_id or "").strip())
        except Exception:
            return ""

    @staticmethod
    def _format_profile_content(profile: Dict[str, Any]) -> str:
        lines = [
            f"sender_id: {profile.get('sender_id', '')}",
            f"primary_nickname: {profile.get('primary_nickname', '')}",
            f"aliases: {', '.join(profile.get('aliases') or [])}",
            f"speak_style: {profile.get('speak_style', '')}",
            f"interests: {', '.join(profile.get('interests') or [])}",
            f"common_words: {', '.join(profile.get('common_words') or [])}",
            f"msg_count: {profile.get('msg_count', 0)}",
            f"activity_score: {profile.get('activity_score', 0)}",
            f"intimacy_score: {profile.get('intimacy_score', 0)}",
        ]
        return "\n".join(line for line in lines if not line.endswith(": "))

    @staticmethod
    def _matches_profile(profile: Dict[str, Any], query_text: str) -> bool:
        fields = [
            profile.get("sender_id", ""),
            profile.get("primary_nickname", ""),
            " ".join(profile.get("aliases") or []),
        ]
        return query_text in _normalize_lookup_text(" ".join(fields))

    @staticmethod
    def _profile_sort_key(profile: Dict[str, Any], query_text: str):
        sender_id = _normalize_lookup_text(profile.get("sender_id", ""))
        primary = _normalize_lookup_text(profile.get("primary_nickname", ""))
        aliases = [_normalize_lookup_text(item) for item in profile.get("aliases") or []]
        if query_text and sender_id == query_text:
            rank = 0
        elif query_text and primary == query_text:
            rank = 1
        elif query_text and any(query_text in alias for alias in aliases):
            rank = 2
        elif query_text and query_text in sender_id + primary:
            rank = 3
        else:
            rank = 4
        return (rank, -int(profile.get("updated_at") or 0), profile.get("sender_id") or "")


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


def _normalize_lookup_text(value: Any) -> str:
    return "".join(str(value or "").strip().lower().split())


def _normalize_aliases(value: Any, sender_id: str, primary_nickname: str = "") -> List[str]:
    result = []
    primary = str(primary_nickname or "").strip()
    for item in _normalize_list(value):
        alias = _normalize_display_name(item, sender_id)
        if alias and alias != primary and alias not in result:
            result.append(alias)
    return result


def _choose_primary_nickname(primary_nickname: Any, sender_id: str, existing_primary: Any, aliases: Any) -> str:
    incoming = _normalize_display_name(primary_nickname, sender_id)
    if incoming:
        return incoming
    existing = _normalize_display_name(existing_primary, sender_id)
    if existing:
        return existing
    alias_list = _normalize_aliases(aliases, sender_id)
    return alias_list[0] if alias_list else ""


def _normalize_display_name(value: Any, sender_id: str = "") -> str:
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
