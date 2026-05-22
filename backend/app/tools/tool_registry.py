from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.mcp.client_manager import MCPClientManager
from app.mcp.registry_bridge import MCPRegistryBridge
from app.services.chat_mode_registry import ChatModeDefinition
from app.tools.chat_tools import BUILTIN_CHAT_TOOLS, ToolExecutionContext, ToolSpec


@dataclass
class ResolvedTool:
    name: str
    openai_schema: dict[str, Any]
    builtin: ToolSpec | None = None
    mcp_server_id: str | None = None
    mcp_tool_name: str | None = None


class ToolRegistry:
    def __init__(self, db: Session, mcp_manager: MCPClientManager | None = None) -> None:
        self.db = db
        self.mcp_manager = mcp_manager or MCPClientManager()
        self.mcp_bridge = MCPRegistryBridge(db, self.mcp_manager)

    def resolve_tools(self, mode: ChatModeDefinition) -> dict[str, ResolvedTool]:
        resolved: dict[str, ResolvedTool] = {}
        for name in mode.allowed_tools:
            builtin = BUILTIN_CHAT_TOOLS.get(name)
            if not builtin:
                continue
            resolved[name] = ResolvedTool(name=name, openai_schema=builtin.to_openai(), builtin=builtin)
        if mode.allow_mcp:
            for tool in self.mcp_bridge.resolve_tools().values():
                resolved[tool.name] = ResolvedTool(
                    name=tool.name,
                    openai_schema=tool.openai_schema,
                    mcp_server_id=tool.server_id,
                    mcp_tool_name=tool.tool_name,
                )
        return resolved

    def execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        context: ToolExecutionContext,
        available_tools: dict[str, ResolvedTool],
    ) -> str:
        resolved = available_tools.get(tool_name)
        if not resolved:
            raise ValueError(f"Tool not found: {tool_name}")
        if resolved.builtin is not None:
            result = resolved.builtin.handler(arguments, context)
            return self._stringify_result(result)
        return self.mcp_bridge.execute_tool(
            arguments=arguments,
            server_id=resolved.mcp_server_id,
            tool_name=resolved.mcp_tool_name or tool_name,
        )

    def _stringify_result(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        return json.dumps(result, default=str)
