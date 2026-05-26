from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable
from uuid import uuid4

from app.schemas.provider import ProviderHealthResponse


@dataclass
class ChatToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


def format_openai_tool_calls(tool_calls: list[ChatToolCall]) -> list[dict[str, Any]]:
    """OpenAI chat completions expect type=function and arguments as a JSON string."""
    formatted: list[dict[str, Any]] = []
    for call in tool_calls:
        args = call.arguments
        if isinstance(args, str):
            args_str = args
        else:
            args_str = json.dumps(args if isinstance(args, dict) else {})
        formatted.append(
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": args_str},
            }
        )
    return formatted


@dataclass
class ChatCompletionResult:
    content: str = ""
    tool_calls: list[ChatToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class ChatStreamChunk:
    delta: str = ""
    tool_calls: list[ChatToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    done: bool = False


class BaseProvider(ABC):
    _MAX_REACT_MESSAGES = 12
    _MAX_REACT_MESSAGE_TEXT = 1200
    _MAX_REACT_TOOL_COUNT = 8
    _MAX_REACT_TOOL_PROPS = 12

    @abstractmethod
    def invoke_json(self, system_prompt: str, user_prompt: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def healthcheck(self) -> ProviderHealthResponse:
        raise NotImplementedError

    def chat_completion(self, system_prompt: str, user_prompt: str) -> str:
        return self.invoke_json(system_prompt, user_prompt)

    def invoke_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        max_tokens: int | None = None,
    ) -> ChatCompletionResult:
        system_prompt, user_prompt = self._build_react_prompt(messages, tools or [])
        raw = self.invoke_json(system_prompt, user_prompt)
        parsed = self._parse_chat_json(raw)
        return ChatCompletionResult(
            content=parsed.get("content", ""),
            tool_calls=[
                ChatToolCall(
                    id=str(call.get("id") or f"tool_{uuid4().hex[:8]}"),
                    name=str(call.get("name") or ""),
                    arguments=call.get("arguments") or {},
                )
                for call in parsed.get("tool_calls", [])
                if call.get("name")
            ],
            finish_reason=str(parsed.get("finish_reason") or "stop"),
            raw={"fallback": True, "text": raw},
        )

    def invoke_chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> Iterable[ChatStreamChunk]:
        result = self.invoke_chat(messages, tools=tools, stream=False)
        if result.content:
            yield ChatStreamChunk(delta=result.content, finish_reason=result.finish_reason)
        elif result.tool_calls:
            yield ChatStreamChunk(tool_calls=result.tool_calls, finish_reason=result.finish_reason)
        yield ChatStreamChunk(done=True, finish_reason=result.finish_reason or "stop")

    def list_models(self) -> list[str]:
        return []

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def _build_react_prompt(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> tuple[str, str]:
        system_parts: list[str] = []
        transcript: list[str] = []
        for message in messages:
            role = str(message.get("role") or "user")
            content = self._truncate_text(message.get("content") or "", self._MAX_REACT_MESSAGE_TEXT)
            if role == "assistant" and isinstance(message.get("tool_calls"), list):
                summarized_calls = []
                for call in message.get("tool_calls") or []:
                    if not isinstance(call, dict):
                        continue
                    summarized_calls.append(
                        {
                            "id": call.get("id"),
                            "name": call.get("name"),
                            "arguments": call.get("arguments"),
                        }
                    )
                if summarized_calls:
                    content = (
                        f"{content}\nTOOL_CALLS:\n"
                        f"{self._truncate_text(json.dumps(summarized_calls, default=str), self._MAX_REACT_MESSAGE_TEXT)}"
                    ).strip()
            if role == "tool":
                tool_name = str(message.get("name") or "tool")
                tool_call_id = str(message.get("tool_call_id") or "")
                prefix = f"TOOL_RESULT {tool_name}"
                if tool_call_id:
                    prefix += f" ({tool_call_id})"
                content = f"{prefix}:\n{content}"
            if role == "system":
                system_parts.append(str(content))
                continue
            transcript.append(f"{role.upper()}:\n{content}")
        schema = {
            "content": "assistant final response text",
            "tool_calls": [
                {"id": "tool_call_id", "name": "tool_name", "arguments": {"key": "value"}}
            ],
            "finish_reason": "tool_calls or stop",
        }
        if tools:
            tool_text = json.dumps(self._summarize_tools(tools), indent=2)
            instruction = (
                "You are in a ReAct tool-calling loop. Return valid JSON only. "
                "If a tool is needed, set tool_calls and leave content empty. "
                "If responding to the user, set content and an empty tool_calls array."
            )
        else:
            tool_text = "[]"
            instruction = (
                "Return valid JSON only with a final assistant response in content and an empty tool_calls array."
            )
        system_prompt = "\n\n".join(
            part for part in [*system_parts, instruction, f"Available tools:\n{tool_text}"] if part
        )
        user_prompt = (
            "Conversation so far:\n"
            + "\n\n".join(transcript[-self._MAX_REACT_MESSAGES :])
            + "\n\nReturn JSON matching this schema exactly:\n"
            + json.dumps(schema, indent=2)
        )
        return system_prompt, user_prompt

    def _truncate_text(self, value: Any, limit: int) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return f"{text[:limit]}...[truncated]"

    def _summarize_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summarized: list[dict[str, Any]] = []
        for tool in tools[: self._MAX_REACT_TOOL_COUNT]:
            function = tool.get("function") or {}
            parameters = function.get("parameters") or {}
            properties = parameters.get("properties") if isinstance(parameters, dict) else {}
            summarized_props: dict[str, Any] = {}
            if isinstance(properties, dict):
                for name, spec in list(properties.items())[: self._MAX_REACT_TOOL_PROPS]:
                    if isinstance(spec, dict):
                        summarized_props[str(name)] = {
                            "type": spec.get("type"),
                            "description": self._truncate_text(spec.get("description") or "", 120),
                        }
                    else:
                        summarized_props[str(name)] = {"type": str(spec)}
            summarized.append(
                {
                    "type": tool.get("type", "function"),
                    "function": {
                        "name": function.get("name"),
                        "description": self._truncate_text(function.get("description") or "", 240),
                        "parameters": {
                            "type": parameters.get("type", "object") if isinstance(parameters, dict) else "object",
                            "properties": summarized_props,
                            "required": list((parameters.get("required") or [])[: self._MAX_REACT_TOOL_PROPS])
                            if isinstance(parameters, dict)
                            else [],
                        },
                    },
                }
            )
        return summarized

    def _parse_chat_json(self, raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if "\n" in text:
                text = text.split("\n", 1)[1]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {"content": text, "tool_calls": [], "finish_reason": "stop"}
        if not isinstance(data, dict):
            return {"content": text, "tool_calls": [], "finish_reason": "stop"}
        has_content_field = "content" in data
        has_tool_calls_field = "tool_calls" in data
        if not isinstance(data.get("tool_calls"), list):
            data["tool_calls"] = []
        if not has_content_field and not has_tool_calls_field:
            data["content"] = text
            return data
        if "content" not in data:
            data["content"] = ""
        return data
