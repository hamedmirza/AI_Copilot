from __future__ import annotations

import asyncio
from typing import Any

from app.db.models import MCPServerModel
from app.mcp.transport import MCPTransport


class MCPClientManager:
    def __init__(self, transport: MCPTransport | None = None) -> None:
        self.transport = transport or MCPTransport()

    async def _list_tools_async(self, server: MCPServerModel) -> list[dict[str, Any]]:
        async def _callback(session) -> list[dict[str, Any]]:
            result = await session.list_tools()
            tools: list[dict[str, Any]] = []
            for tool in getattr(result, "tools", []):
                tools.append(
                    {
                        "name": getattr(tool, "name", ""),
                        "description": getattr(tool, "description", "") or "",
                        "input_schema": getattr(tool, "inputSchema", None)
                        or getattr(tool, "input_schema", None)
                        or {"type": "object", "properties": {}},
                    }
                )
            return tools

        return await self.transport.with_session(server, _callback)

    async def _call_tool_async(
        self,
        server: MCPServerModel,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        async def _callback(session) -> dict[str, Any]:
            result = await session.call_tool(tool_name, arguments or {})
            content = []
            for item in getattr(result, "content", []):
                text = getattr(item, "text", None)
                if text is not None:
                    content.append(text)
                else:
                    content.append(str(item))
            return {
                "content": "\n".join(content).strip(),
                "is_error": bool(getattr(result, "isError", False) or getattr(result, "is_error", False)),
            }

        return await self.transport.with_session(server, _callback)

    def list_tools(self, server: MCPServerModel) -> list[dict[str, Any]]:
        return asyncio.run(self._list_tools_async(server))

    def call_tool(
        self,
        server: MCPServerModel,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        return asyncio.run(self._call_tool_async(server, tool_name, arguments))

    def test_server(self, server: MCPServerModel) -> tuple[bool, list[dict[str, Any]], str | None]:
        try:
            tools = self.list_tools(server)
            return True, tools, None
        except Exception as exc:  # pragma: no cover - depends on external process
            return False, [], str(exc)
