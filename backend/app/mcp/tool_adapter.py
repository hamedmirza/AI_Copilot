from __future__ import annotations

import re
from typing import Any


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip().lower())
    return cleaned.strip("_") or "tool"


def build_tool_name(server_id: str, server_name: str, tool_name: str) -> str:
    return f"mcp__{_slug(server_name)}__{server_id[:8]}__{_slug(tool_name)}"


def mcp_tool_to_openai(
    server_id: str,
    server_name: str,
    tool_name: str,
    description: str,
    input_schema: dict[str, Any] | None,
) -> dict[str, Any]:
    schema = input_schema if isinstance(input_schema, dict) else {"type": "object", "properties": {}}
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return {
        "type": "function",
        "function": {
            "name": build_tool_name(server_id, server_name, tool_name),
            "description": description or f"MCP tool {tool_name} from {server_name}",
            "parameters": schema,
        },
    }
