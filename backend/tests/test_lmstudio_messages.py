from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx

from app.providers.base import ChatCompletionResult, ChatToolCall, format_openai_tool_calls
from app.providers.lmstudio import LMStudioProvider


def test_normalize_tool_messages_rewrites_role_tool_to_user():
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "test-model")
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "find files"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "search_files", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "call-1", "name": "search_files", "content": '{"matches": []}'},
    ]

    normalized = provider._normalize_messages_for_lmstudio(messages)

    assert all(m.get("role") != "tool" for m in normalized)
    tool_as_user = normalized[-1]
    assert tool_as_user["role"] == "user"
    assert "search_files" in tool_as_user["content"]
    assert "call-1" in tool_as_user["content"]
    assert '{"matches": []}' in tool_as_user["content"]


def test_format_openai_tool_calls_uses_function_wrapper_and_string_arguments():
    formatted = format_openai_tool_calls(
        [ChatToolCall(id="call-1", name="search_files", arguments={"query": "main"})]
    )
    assert formatted == [
        {
            "id": "call-1",
            "type": "function",
            "function": {"name": "search_files", "arguments": '{"query": "main"}'},
        }
    ]


def test_normalize_flattens_legacy_assistant_tool_calls():
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "test-model")
    messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-1", "name": "search_files", "arguments": {"q": "x"}}],
        }
    ]
    normalized = provider._normalize_messages_for_lmstudio(messages)
    function = normalized[0]["tool_calls"][0]["function"]
    assert function["name"] == "search_files"
    assert function["arguments"] == '{"q": "x"}'


def test_invoke_chat_uses_react_after_tool_history_without_posting_native_messages():
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "test-model")
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "task"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": format_openai_tool_calls(
                [ChatToolCall(id="call-1", name="search_files", arguments={})]
            ),
        },
        {"role": "tool", "tool_call_id": "call-1", "name": "search_files", "content": "{}"},
    ]
    react_result = ChatCompletionResult(content='{"content":"done","tool_calls":[]}', finish_reason="stop")

    with patch.object(provider, "_post_chat_completion") as post_chat:
        with patch(
            "app.providers.lmstudio.LMStudioProvider.invoke_chat",
            wraps=provider.invoke_chat,
        ):
            with patch("app.providers.base.BaseProvider.invoke_chat", return_value=react_result) as react_invoke:
                result = provider.invoke_chat(messages, tools=[{"type": "function"}])

    post_chat.assert_not_called()
    react_invoke.assert_called_once()
    assert result.content == '{"content":"done","tool_calls":[]}'


def test_should_fallback_to_react_on_invalid_messages_payload_error():
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "test-model")
    response = MagicMock()
    response.status_code = 400
    response.json.return_value = {
        "error": {
            "message": (
                "Invalid 'messages' in payload. Please check the structure of your "
                "'messages' and try again."
            )
        }
    }
    response.text = ""
    exc = httpx.HTTPStatusError(
        "bad request",
        request=MagicMock(),
        response=response,
    )

    assert provider._should_fallback_to_react(exc) is True
