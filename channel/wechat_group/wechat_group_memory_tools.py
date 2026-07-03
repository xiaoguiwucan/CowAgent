"""Scoped WeChat group memory tools for the current Agent turn."""

from __future__ import annotations

import asyncio
import threading
from typing import Callable, List, Optional

from agent.memory.scope import MemoryScope
from agent.tools.base_tool import BaseTool, ToolResult
from channel.wechat_group.wechat_group_memory import WechatGroupMemoryService


class WechatGroupMemorySearchTool(BaseTool):
    name = "wechat_group_memory_search"
    description = (
        "Search long-term memories for the current WeChat group only. "
        "Use this for current group rules, preferences, historical agreements, "
        "project facts, or recurring decisions. The current room is bound by "
        "the server and cannot be changed by tool arguments."
    )
    params = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for current group memory",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of memories to return",
                "default": 5,
            },
            "min_score": {
                "type": "number",
                "description": "Minimum relevance score from 0 to 1",
                "default": 0,
            },
        },
        "required": ["query"],
    }

    def __init__(self, service: WechatGroupMemoryService, room_id: str):
        super().__init__()
        self.service = service
        self.room_id = room_id

    def execute(self, params: dict) -> ToolResult:
        query = str(params.get("query") or "").strip()
        if not query:
            return ToolResult.fail("Error: query parameter is required")
        max_results = _to_int(params.get("max_results"), self.service.group_memory_limit)
        min_score = _to_float(params.get("min_score"), 0.0)

        async def _search():
            results = await self.service.memory_manager.search(
                query=query,
                memory_scope=MemoryScope.wechat_group(self.room_id),
                max_results=max_results,
                min_score=min_score,
            )
            if not results:
                results = await self.service.list_group_memories(
                    self.room_id,
                    limit=max_results,
                )
            else:
                results = [self.service._result_to_dict(row) for row in results]
            return results

        try:
            rows = _run_async_sync(_search)
        except Exception as e:
            return ToolResult.fail(f"Error searching current group memory: {e}")

        if not rows:
            return ToolResult.success("No current group memories found.")
        lines = [f"Found {len(rows)} current group memories:"]
        for idx, item in enumerate(rows, 1):
            lines.append(f"\n{idx}. {item.get('content', '')}")
        return ToolResult.success("\n".join(lines))


class WechatGroupProfileGetTool(BaseTool):
    name = "wechat_group_profile_get"
    description = (
        "Read a member profile from the current WeChat group only. Use this "
        "for member role, preferences, expertise, interaction style, boundaries, "
        "or evidence. Provide sender_id for an exact profile, or query to search "
        "related current-room member profiles."
    )
    params = {
        "type": "object",
        "properties": {
            "sender_id": {
                "type": "string",
                "description": "Optional member sender_id in the current group; omit for current speaker",
            },
            "query": {
                "type": "string",
                "description": "Optional semantic search query for current-room member profiles",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of profiles to return for query search",
                "default": 1,
            },
            "min_score": {
                "type": "number",
                "description": "Minimum relevance score from 0 to 1 for query search",
                "default": 0,
            },
        },
        "required": [],
    }

    def __init__(
        self,
        service: WechatGroupMemoryService,
        room_id: str,
        sender_id: str,
        bot_sender_id: Optional[str] = None,
    ):
        super().__init__()
        self.service = service
        self.room_id = room_id
        self.sender_id = sender_id
        self.bot_sender_id = bot_sender_id or ""

    def execute(self, params: dict) -> ToolResult:
        requested_sender_id = str(params.get("sender_id") or "").strip()
        query = str(params.get("query") or "").strip()
        if query and not requested_sender_id:
            max_results = _to_int(params.get("max_results"), self.service.member_memory_limit)
            min_score = _to_float(params.get("min_score"), 0.0)

            async def _search_profiles():
                return await self.service.search_member_profiles(
                    self.room_id,
                    query=query,
                    limit=max_results,
                    excluded_sender_ids={self.sender_id, self.bot_sender_id},
                    min_score=min_score,
                )

            try:
                rows = _run_async_sync(_search_profiles)
            except Exception as e:
                return ToolResult.fail(f"Error searching current group profiles: {e}")

            if not rows:
                return ToolResult.success("No matching current group member profiles found.")
            lines = [f"Found {len(rows)} current group member profiles:"]
            for idx, profile in enumerate(rows, 1):
                sender_id = profile.get("subject_id") or ""
                lines.append(
                    f"\n{idx}. sender_id: {sender_id}\n"
                    f"{profile.get('content', '')}"
                )
            return ToolResult.success("\n".join(lines))

        requested_sender_id = requested_sender_id or self.sender_id or ""
        if not requested_sender_id:
            return ToolResult.fail("Error: sender_id is required when current speaker is unknown")
        if self.bot_sender_id and requested_sender_id == self.bot_sender_id:
            return ToolResult.success("No member profile returned for the bot itself.")

        async def _get_profile():
            return await self.service.list_member_profiles(
                self.room_id,
                sender_id=requested_sender_id,
                limit=1,
            )

        try:
            rows = _run_async_sync(_get_profile)
        except Exception as e:
            return ToolResult.fail(f"Error reading current group profile: {e}")

        if not rows:
            return ToolResult.success(f"No active profile found for sender_id={requested_sender_id}.")
        profile = rows[0]
        return ToolResult.success(
            "Current group member profile:\n"
            f"sender_id: {requested_sender_id}\n"
            f"{profile.get('content', '')}"
        )


def create_wechat_group_memory_tools(
    service: WechatGroupMemoryService,
    room_id: str,
    sender_id: str,
    bot_sender_id: Optional[str] = None,
) -> List[BaseTool]:
    return [
        WechatGroupMemorySearchTool(service, room_id=room_id),
        WechatGroupProfileGetTool(
            service,
            room_id=room_id,
            sender_id=sender_id,
            bot_sender_id=bot_sender_id,
        ),
    ]


def _run_async_sync(factory: Callable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result = {}

    def _target():
        try:
            result["value"] = asyncio.run(factory())
        except Exception as e:
            result["error"] = e

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in result:
        raise result["error"]
    return result.get("value")


def _to_int(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return fallback
    return max(1, parsed)


def _to_float(value, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback
