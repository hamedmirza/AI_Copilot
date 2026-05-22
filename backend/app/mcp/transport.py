from __future__ import annotations

from typing import Any, Awaitable, Callable, TypeVar

from app.core.exceptions import ValidationError
from app.db.models import MCPServerModel

T = TypeVar("T")


class MCPTransport:
    def __init__(self) -> None:
        self._sdk_error: str | None = None

    def _load_sdk(self):
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:  # pragma: no cover - depends on optional runtime dependency
            self._sdk_error = str(exc)
            raise ValidationError("MCP SDK is not installed") from exc
        return ClientSession, StdioServerParameters, stdio_client

    async def with_session(
        self,
        server: MCPServerModel,
        callback: Callable[[Any], Awaitable[T]],
    ) -> T:
        ClientSession, StdioServerParameters, stdio_client = self._load_sdk()
        params = StdioServerParameters(
            command=server.command,
            args=server.args,
            env=server.env or None,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await callback(session)
