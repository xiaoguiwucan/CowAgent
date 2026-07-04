"""WeChat group sticker tools for the current Agent turn."""

from __future__ import annotations

from typing import List

from agent.tools.base_tool import BaseTool, ToolResult
from channel.wechat_group.wechat_group_sticker_service import WechatGroupStickerService


class WechatGroupStickerSearchTool(BaseTool):
    name = "wechat_group_sticker_search"
    description = (
        "Search active stickers for the current WeChat group only. Use this when "
        "a sticker reply would fit better than plain text. Query can be empty to "
        "list the most relevant recent stickers in the current group."
    )
    params = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional query for sticker description or file name",
                "default": "",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of stickers to return",
                "default": 5,
            },
        },
        "required": [],
    }

    def __init__(self, service: WechatGroupStickerService, room_id: str):
        super().__init__()
        self.service = service
        self.room_id = room_id

    def execute(self, params: dict) -> ToolResult:
        query = str(params.get("query") or "").strip()
        max_results = _to_int(params.get("max_results"), 5)
        try:
            rows = self.service.search_stickers(self.room_id, query=query, limit=max_results)
        except Exception as e:
            return ToolResult.fail(f"Error searching current group stickers: {e}")
        if not rows:
            return ToolResult.success("No active stickers found in the current group.")
        lines = [f"Found {len(rows)} active stickers in the current group:"]
        for idx, item in enumerate(rows, 1):
            lines.append(
                f"\n{idx}. sticker_id: {item.get('sticker_id', '')}\n"
                f"description: {item.get('description', '')}\n"
                f"use_count: {item.get('use_count', 0)}"
            )
        return ToolResult.success("\n".join(lines))


class WechatGroupStickerSendTool(BaseTool):
    name = "wechat_group_sticker_send"
    description = (
        "Send an active sticker from the current WeChat group by sticker_id. "
        "Always call wechat_group_sticker_search first unless you already know "
        "the exact sticker_id."
    )
    params = {
        "type": "object",
        "properties": {
            "sticker_id": {
                "type": "string",
                "description": "Exact sticker_id returned by wechat_group_sticker_search",
            },
            "message": {
                "type": "string",
                "description": "Optional short message to accompany the sticker",
                "default": "",
            },
        },
        "required": ["sticker_id"],
    }

    def __init__(self, service: WechatGroupStickerService, room_id: str):
        super().__init__()
        self.service = service
        self.room_id = room_id

    def execute(self, params: dict) -> ToolResult:
        sticker_id = str(params.get("sticker_id") or "").strip()
        if not sticker_id:
            return ToolResult.fail("Error: sticker_id parameter is required")
        try:
            payload = self.service.prepare_send_result(
                room_id=self.room_id,
                sticker_id=sticker_id,
                message=str(params.get("message") or "").strip(),
            )
        except Exception as e:
            return ToolResult.fail(f"Error sending current group sticker: {e}")
        return ToolResult.success(payload)


def create_wechat_group_sticker_tools(
    sticker_service: WechatGroupStickerService,
    room_id: str,
) -> List[BaseTool]:
    return [
        WechatGroupStickerSearchTool(sticker_service, room_id=room_id),
        WechatGroupStickerSendTool(sticker_service, room_id=room_id),
    ]


def _to_int(value, fallback: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return fallback
    return max(1, parsed)
