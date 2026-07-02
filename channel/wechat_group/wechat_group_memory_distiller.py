"""Controlled distillation from archived WeChat group chat into scoped memory."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional

from agent.protocol.models import LLMRequest
from bridge.agent_bridge import AgentLLMModel
from bridge.bridge import Bridge
from channel.wechat_group.wechat_group_archive import WechatGroupArchive
from channel.wechat_group.wechat_group_memory import WechatGroupMemoryService
from config import conf


class WechatGroupMemoryDistiller:
    """Generate auditable group memory candidates from archived room messages."""

    def __init__(
        self,
        archive: WechatGroupArchive,
        memory_service: WechatGroupMemoryService,
        llm_client: Optional[Any] = None,
        config_getter: Optional[Any] = None,
    ):
        self.archive = archive
        self.memory_service = memory_service
        self.llm_client = llm_client or _DefaultLlmClient()
        self.config_getter = config_getter or (lambda key, default=None: conf().get(key, default))

    async def run(
        self,
        room_id: str,
        window_minutes: int = 60,
        limit: int = 200,
        force: bool = False,
        now: Optional[int] = None,
    ) -> Dict[str, Any]:
        room_id = self.memory_service._require_room(room_id)
        if not bool(self._cfg("wechat_group_memory_auto_extract", False)):
            return {
                "status": "disabled",
                "run_id": "",
                "auto_applied_count": 0,
                "candidate_count": 0,
                "discarded_reasons": ["wechat_group_memory_auto_extract disabled"],
            }
        until_ts = int(now or time.time())
        minutes = max(int(window_minutes or 60), 1)
        since_ts = until_ts - minutes * 60
        messages = self.archive.get_messages_for_distill(
            room_id=room_id,
            since_ts=since_ts,
            until_ts=until_ts,
            limit=limit,
        )
        run_id = self.archive.create_distill_run(room_id, since_ts, until_ts, len(messages))
        if not messages:
            self.archive.finish_distill_run(run_id, "success")
            return {
                "status": "success",
                "run_id": run_id,
                "auto_applied_count": 0,
                "candidate_count": 0,
                "discarded_reasons": ["no messages in window"],
            }

        raw_output = ""
        auto_applied = 0
        candidate_count = 0
        discarded_reasons: List[str] = []
        try:
            raw_output = self._call_llm(self._build_prompt(room_id, messages))
            parsed = self._parse_output(raw_output)
            message_ids = {str(item["message_id"]) for item in messages}
            verifiable_sender_ids = self._verifiable_sender_ids(messages)
            if not parsed.get("group_memories") and not parsed.get("member_profiles"):
                discarded_reasons.append("LLM returned no memory candidates")

            for item in parsed.get("group_memories", []) or []:
                outcome = await self._handle_group_memory_candidate(
                    run_id=run_id,
                    room_id=room_id,
                    item=item,
                    message_ids=message_ids,
                    discarded_reasons=discarded_reasons,
                )
                auto_applied += 1 if outcome == "auto_applied" else 0
                candidate_count += 1 if outcome in ("auto_applied", "pending") else 0

            for item in parsed.get("member_profiles", []) or []:
                outcome = await self._handle_member_profile_candidate(
                    run_id=run_id,
                    room_id=room_id,
                    item=item,
                    message_ids=message_ids,
                    verifiable_sender_ids=verifiable_sender_ids,
                    discarded_reasons=discarded_reasons,
                )
                auto_applied += 1 if outcome == "auto_applied" else 0
                candidate_count += 1 if outcome in ("auto_applied", "pending") else 0

            self.archive.finish_distill_run(
                run_id,
                "success",
                auto_applied_count=auto_applied,
                candidate_count=candidate_count,
                raw_output_summary=raw_output,
            )
            return {
                "status": "success",
                "run_id": run_id,
                "auto_applied_count": auto_applied,
                "candidate_count": candidate_count,
                "discarded_reasons": discarded_reasons,
            }
        except Exception as exc:
            self.archive.finish_distill_run(
                run_id,
                "failed",
                auto_applied_count=auto_applied,
                candidate_count=candidate_count,
                failed_reason=str(exc),
                raw_output_summary=raw_output,
            )
            raise

    def list_runs(self, room_id: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        room_id = self.memory_service._require_room(room_id)
        return self.archive.list_distill_runs(room_id, limit=limit, offset=offset)

    def list_candidates(
        self,
        room_id: str,
        status: Optional[str] = None,
        candidate_type: Optional[str] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        room_id = self.memory_service._require_room(room_id)
        return self.archive.list_memory_candidates(
            room_id,
            status=status or None,
            candidate_type=candidate_type or None,
            limit=limit,
            offset=offset,
        )

    async def approve_candidate(self, room_id: str, candidate_id: str) -> Dict[str, Any]:
        room_id = self.memory_service._require_room(room_id)
        candidate = self.archive.get_memory_candidate(room_id, candidate_id)
        if not candidate:
            raise ValueError("candidate_id is not found in this room")
        if candidate["status"] not in ("pending", "failed"):
            raise ValueError(f"candidate cannot be approved from status: {candidate['status']}")
        applied_id = await self._apply_candidate(room_id, candidate, created_by="candidate_review")
        return self.archive.update_memory_candidate_status(
            room_id,
            candidate_id,
            "approved",
            applied_memory_id=applied_id,
        )

    def reject_candidate(self, room_id: str, candidate_id: str, review_note: str = "") -> Dict[str, Any]:
        room_id = self.memory_service._require_room(room_id)
        candidate = self.archive.get_memory_candidate(room_id, candidate_id)
        if not candidate:
            raise ValueError("candidate_id is not found in this room")
        if candidate["status"] not in ("pending", "failed"):
            raise ValueError(f"candidate cannot be rejected from status: {candidate['status']}")
        return self.archive.update_memory_candidate_status(
            room_id,
            candidate_id,
            "rejected",
            review_note=review_note,
        )

    def list_candidate_messages(self, room_id: str, candidate_id: str) -> List[Dict[str, Any]]:
        room_id = self.memory_service._require_room(room_id)
        candidate = self.archive.get_memory_candidate(room_id, candidate_id)
        if not candidate:
            raise ValueError("candidate_id is not found in this room")
        rows = []
        wanted = set(candidate.get("evidence_message_ids") or [])
        for item in self.archive.get_messages_for_distill(room_id, 0, int(time.time()), 500):
            if item.get("message_id") in wanted:
                rows.append(item)
        return rows

    async def _handle_group_memory_candidate(
        self,
        run_id: str,
        room_id: str,
        item: Dict[str, Any],
        message_ids: set,
        discarded_reasons: List[str],
    ) -> str:
        candidate = self._normalize_group_memory(item)
        reason = self._validate_common(candidate, message_ids)
        if reason:
            discarded_reasons.append(reason)
            return "discarded"
        confidence = candidate["confidence"]
        if confidence < self._candidate_threshold():
            return "discarded"
        status = "pending"
        applied_id = ""
        if confidence >= self._auto_apply_threshold() and bool(
            self._cfg("wechat_group_memory_auto_apply_group_enabled", True)
        ):
            if await self._is_duplicate_group_memory(room_id, candidate):
                discarded_reasons.append("duplicate group memory")
                return "discarded"
            applied_id = await self._apply_group_memory(room_id, candidate, created_by="auto_distill")
            status = "auto_applied"
        self.archive.insert_memory_candidate(
            run_id=run_id,
            room_id=room_id,
            candidate_type="group_memory",
            content=candidate,
            confidence=confidence,
            evidence_message_ids=candidate["evidence_message_ids"],
            evidence_text=candidate.get("evidence_text", ""),
            status=status,
            applied_memory_id=applied_id,
        )
        return status

    async def _handle_member_profile_candidate(
        self,
        run_id: str,
        room_id: str,
        item: Dict[str, Any],
        message_ids: set,
        verifiable_sender_ids: set,
        discarded_reasons: List[str],
    ) -> str:
        candidate = self._normalize_member_profile(item)
        reason = self._validate_common(candidate, message_ids)
        if reason:
            discarded_reasons.append(reason)
            return "discarded"
        if candidate["target_sender_id"] not in verifiable_sender_ids:
            discarded_reasons.append("target_sender_id is not verifiable in current window")
            return "discarded"
        confidence = candidate["confidence"]
        if confidence < self._candidate_threshold():
            return "discarded"
        status = "pending"
        applied_id = ""
        if confidence >= self._auto_apply_threshold() and bool(
            self._cfg("wechat_group_memory_auto_apply_member_enabled", True)
        ):
            applied_id = await self._apply_member_profile(room_id, candidate, created_by="auto_distill")
            status = "auto_applied"
        self.archive.insert_memory_candidate(
            run_id=run_id,
            room_id=room_id,
            candidate_type="member_profile",
            content=candidate,
            confidence=confidence,
            evidence_message_ids=candidate["evidence_message_ids"],
            evidence_text=candidate.get("evidence_text", ""),
            status=status,
            target_sender_id=candidate["target_sender_id"],
            target_sender_nickname=candidate.get("target_sender_nickname", ""),
            applied_memory_id=applied_id,
        )
        return status

    async def _apply_candidate(self, room_id: str, candidate: Dict[str, Any], created_by: str) -> str:
        if candidate["candidate_type"] == "group_memory":
            return await self._apply_group_memory(room_id, candidate["content"], created_by=created_by)
        if candidate["candidate_type"] == "member_profile":
            return await self._apply_member_profile(room_id, candidate["content"], created_by=created_by)
        raise ValueError(f"unknown candidate_type: {candidate['candidate_type']}")

    async def _apply_group_memory(self, room_id: str, candidate: Dict[str, Any], created_by: str) -> str:
        memory = await self.memory_service.add_group_memory(
            room_id=room_id,
            content=candidate["content"],
            source_message_ids=candidate["evidence_message_ids"],
            source_summary=candidate.get("evidence_text", ""),
            created_by=created_by,
        )
        return str(memory.get("id") or "")

    async def _apply_member_profile(self, room_id: str, candidate: Dict[str, Any], created_by: str) -> str:
        profile = await self.memory_service.upsert_member_profile(
            room_id=room_id,
            sender_id=candidate["target_sender_id"],
            sender_nickname=candidate.get("target_sender_nickname", ""),
            role=candidate.get("role", ""),
            preferences=candidate.get("preferences", ""),
            expertise=candidate.get("expertise", ""),
            interaction_style=candidate.get("interaction_style", ""),
            boundaries=candidate.get("boundaries", ""),
            evidence=candidate.get("evidence_text", ""),
            source_message_ids=candidate["evidence_message_ids"],
            created_by=created_by,
            merge_existing_fields=True,
        )
        return str(profile.get("id") or "")

    async def _is_duplicate_group_memory(self, room_id: str, candidate: Dict[str, Any]) -> bool:
        existing = await self.memory_service.list_group_memories(room_id, limit=100)
        source_ids = set(candidate.get("evidence_message_ids") or [])
        normalized = _compact(candidate["content"])
        for item in existing:
            if source_ids and source_ids == set(item.get("source_message_ids") or []):
                return True
            existing_text = _compact(item.get("content") or "")
            if normalized and (normalized in existing_text or existing_text in normalized):
                return True
        return False

    def _call_llm(self, prompt: str) -> str:
        if hasattr(self.llm_client, "complete"):
            return str(self.llm_client.complete(prompt) or "")
        response = self.llm_client.call(LLMRequest(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            stream=False,
            system=_SYSTEM_PROMPT,
        ))
        return _extract_response_text(response)

    def _build_prompt(self, room_id: str, messages: List[Dict[str, Any]]) -> str:
        payload = []
        for item in messages:
            payload.append({
                "message_id": item.get("message_id"),
                "room_id": item.get("room_id"),
                "sender_id": item.get("sender_id"),
                "sender_nickname": item.get("sender_nickname"),
                "message_type": item.get("message_type"),
                "text": item.get("text"),
                "created_at": item.get("created_at"),
                "at_list": item.get("at_list") or [],
            })
        return (
            "请从以下当前微信群聊天记录中提取稳定长期事实，严格输出 JSON。\n"
            "禁止输出全局记忆；禁止发明 sender_id；证据 message_id 必须来自输入。\n"
            "JSON schema: {\"group_memories\": [{\"content\": string, \"confidence\": number, "
            "\"evidence_message_ids\": string[], \"evidence_text\": string}], "
            "\"member_profiles\": [{\"target_sender_id\": string, \"target_sender_nickname\": string, "
            "\"role\": string, \"preferences\": string, \"expertise\": string, "
            "\"interaction_style\": string, \"boundaries\": string, \"confidence\": number, "
            "\"evidence_message_ids\": string[], \"evidence_text\": string}]}。\n"
            f"room_id: {room_id}\nmessages:\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

    def _parse_output(self, raw_output: str) -> Dict[str, Any]:
        text = (raw_output or "").strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
            text = re.sub(r"```$", "", text).strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("LLM output must be a JSON object")
        parsed.setdefault("group_memories", [])
        parsed.setdefault("member_profiles", [])
        return parsed

    def _normalize_group_memory(self, item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "content": _require_text(item.get("content"), "content"),
            "confidence": _confidence(item.get("confidence")),
            "evidence_message_ids": _string_list(item.get("evidence_message_ids")),
            "evidence_text": str(item.get("evidence_text") or "").strip(),
        }

    def _normalize_member_profile(self, item: Dict[str, Any]) -> Dict[str, Any]:
        candidate = {
            "target_sender_id": _require_text(item.get("target_sender_id"), "target_sender_id"),
            "target_sender_nickname": str(item.get("target_sender_nickname") or "").strip(),
            "role": str(item.get("role") or "").strip(),
            "preferences": str(item.get("preferences") or "").strip(),
            "expertise": str(item.get("expertise") or "").strip(),
            "interaction_style": str(item.get("interaction_style") or "").strip(),
            "boundaries": str(item.get("boundaries") or "").strip(),
            "confidence": _confidence(item.get("confidence")),
            "evidence_message_ids": _string_list(item.get("evidence_message_ids")),
            "evidence_text": str(item.get("evidence_text") or "").strip(),
        }
        if not any(candidate.get(key) for key in (
            "role", "preferences", "expertise", "interaction_style", "boundaries", "evidence_text"
        )):
            raise ValueError("member profile candidate has no content")
        return candidate

    def _validate_common(self, candidate: Dict[str, Any], message_ids: set) -> str:
        evidence_ids = candidate.get("evidence_message_ids") or []
        if not evidence_ids:
            return "evidence_message_ids are required"
        if any(item not in message_ids for item in evidence_ids):
            return "evidence_message_ids are not in current room window"
        return ""

    @staticmethod
    def _verifiable_sender_ids(messages: List[Dict[str, Any]]) -> set:
        result = set()
        for item in messages:
            sender_id = str(item.get("sender_id") or "").strip()
            if sender_id:
                result.add(sender_id)
            for mentioned_id in item.get("at_list") or []:
                mentioned_id = str(mentioned_id or "").strip()
                if mentioned_id:
                    result.add(mentioned_id)
        return result

    def _candidate_threshold(self) -> float:
        return _confidence(self._cfg("wechat_group_memory_candidate_threshold", 0.55))

    def _auto_apply_threshold(self) -> float:
        return _confidence(self._cfg("wechat_group_memory_auto_apply_threshold", 0.85))

    def _cfg(self, key: str, default: Any = None) -> Any:
        return self.config_getter(key, default)


class _DefaultLlmClient:
    def call(self, request: LLMRequest):
        return AgentLLMModel(Bridge()).call(request)


def _extract_response_text(response: Any) -> str:
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        for key in ("content", "text", "message"):
            if response.get(key):
                return str(response.get(key))
        choices = response.get("choices")
        if choices:
            message = choices[0].get("message") or {}
            return str(message.get("content") or choices[0].get("text") or "")
    return str(response)


def _require_text(value: Any, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{name} is required")
    return text


def _confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except Exception as exc:
        raise ValueError("confidence must be a number") from exc
    if confidence < 0 or confidence > 1:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        raise ValueError("evidence_message_ids must be a list")
    return [str(item).strip() for item in value if str(item or "").strip()]


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


_SYSTEM_PROMPT = (
    "你是微信群长期记忆蒸馏器。只输出严格 JSON，不输出解释；"
    "只提取稳定事实、长期偏好、角色职责和群内约定。"
)
