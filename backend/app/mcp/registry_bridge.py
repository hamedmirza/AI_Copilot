from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import MCPServerModel
from app.mcp.client_manager import MCPClientManager
from app.mcp.tool_adapter import build_tool_name, mcp_tool_to_openai


@dataclass
class MCPResolvedTool:
    name: str
    openai_schema: dict[str, Any]
    server_id: str
    tool_name: str


class MCPRegistryBridge:
    def __init__(self, db: Session, client_manager: MCPClientManager | None = None) -> None:
        self.db = db
        self.client_manager = client_manager or MCPClientManager()

    def resolve_tools(self) -> dict[str, MCPResolvedTool]:
        resolved: dict[str, MCPResolvedTool] = {}
        for server in self._enabled_servers():
            for tool in self._list_server_tools(server):
                source_name = str(tool.get("name") or "tool")
                unique_name = build_tool_name(server.id, server.name, source_name)
                resolved[unique_name] = MCPResolvedTool(
                    name=unique_name,
                    openai_schema=mcp_tool_to_openai(
                        server.id,
                        server.name,
                        source_name,
                        str(tool.get("description") or ""),
                        tool.get("input_schema") if isinstance(tool, dict) else None,
                    ),
                    server_id=server.id,
                    tool_name=source_name,
                )
        return resolved

    def execute_tool(
        self,
        resolved_tool: MCPResolvedTool | None = None,
        arguments: dict[str, Any] | None = None,
        *,
        server_id: str | None = None,
        tool_name: str | None = None,
    ) -> str:
        target_server_id = resolved_tool.server_id if resolved_tool else server_id
        target_tool_name = resolved_tool.tool_name if resolved_tool else tool_name
        if not target_server_id or not target_tool_name:
            raise ValueError("MCP tool target is incomplete")
        server = self.db.get(MCPServerModel, target_server_id)
        if not server:
            raise ValueError(f"MCP server not found: {target_server_id}")
        result = self.client_manager.call_tool(server, target_tool_name, arguments or {})
        if isinstance(result, str):
            return result
        return json.dumps(result, default=str)

    def _enabled_servers(self) -> list[MCPServerModel]:
        return self.db.query(MCPServerModel).filter(MCPServerModel.enabled.is_(True)).all()

    def _list_server_tools(self, server: MCPServerModel) -> list[dict[str, Any]]:
        try:
            return self.client_manager.list_tools(server)
        except Exception:
            return []
