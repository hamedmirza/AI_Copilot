from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

import tiktoken

logger = logging.getLogger(__name__)

DEFAULT_ENCODING = "cl100k_base"
# OpenAI chat message framing overhead per message (role markers, separators).
_MESSAGE_OVERHEAD_TOKENS = 4
_MIN_TRUNCATED_TOKENS = 16
_TRUNCATION_SUFFIX = "...[truncated for context budget]"


@lru_cache(maxsize=8)
def get_encoding(model: str | None = None) -> tiktoken.Encoding:
    normalized = (model or "").strip()
    if normalized:
        try:
            return tiktoken.encoding_for_model(normalized)
        except KeyError:
            lowered = normalized.lower()
            if lowered.startswith("gpt-4o") or lowered.startswith("gpt-4.1"):
                return tiktoken.get_encoding("o200k_base")
    return tiktoken.get_encoding(DEFAULT_ENCODING)


@lru_cache(maxsize=4)
def _suffix_token_count(encoding_name: str) -> int:
    encoding = tiktoken.get_encoding(encoding_name)
    return len(encoding.encode(_TRUNCATION_SUFFIX))


def count_text_tokens(text: str, *, model: str | None = None) -> int:
    if not (text or "").strip():
        return 0
    encoding = get_encoding(model)
    return len(encoding.encode(text))


def estimate_tools_tokens(
    tools: list[dict[str, Any]] | None,
    *,
    model: str | None = None,
) -> int:
    if not tools:
        return 0
    try:
        payload = json.dumps(tools, default=str, separators=(",", ":"))
    except (TypeError, ValueError):
        payload = str(tools)
    # Tool schema overhead in the API request beyond raw JSON body.
    return count_text_tokens(payload, model=model) + 12


def _tool_calls_text(message: dict[str, Any]) -> str:
    tool_calls = message.get("tool_calls")
    if not isinstance(tool_calls, list):
        return ""
    parts: list[str] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        function = call.get("function") if isinstance(call.get("function"), dict) else {}
        parts.append(str(function.get("name") or ""))
        parts.append(str(function.get("arguments") or ""))
        if call.get("id"):
            parts.append(str(call["id"]))
    return "\n".join(parts)


def estimate_message_tokens(message: dict[str, Any], *, model: str | None = None) -> int:
    encoding = get_encoding(model)
    tokens = _MESSAGE_OVERHEAD_TOKENS
    role = str(message.get("role") or "")
    if role:
        tokens += len(encoding.encode(role))
    content = message.get("content")
    if content is not None and str(content):
        tokens += len(encoding.encode(str(content)))
    tool_call_id = message.get("tool_call_id")
    if tool_call_id:
        tokens += len(encoding.encode(str(tool_call_id)))
    tool_calls_text = _tool_calls_text(message)
    if tool_calls_text:
        tokens += len(encoding.encode(tool_calls_text))
    return tokens


def count_messages_tokens(messages: list[dict[str, Any]], *, model: str | None = None) -> int:
    return sum(estimate_message_tokens(message, model=model) for message in messages)


def truncate_text_to_tokens(text: str, max_tokens: int, *, model: str | None = None) -> str:
    if max_tokens <= 0:
        return ""
    encoding = get_encoding(model)
    encoded = encoding.encode(text or "")
    if len(encoded) <= max_tokens:
        return text or ""
    suffix_tokens = _suffix_token_count(encoding.name)
    body_budget = max(_MIN_TRUNCATED_TOKENS, max_tokens - suffix_tokens)
    low, high = 0, len(text or "")
    best = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = (text or "")[:mid]
        if len(encoding.encode(candidate)) <= body_budget:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1
    return f"{best}{_TRUNCATION_SUFFIX}"


def truncate_message_for_budget(
    message: dict[str, Any],
    max_tokens: int,
    *,
    model: str | None = None,
) -> dict[str, Any]:
    if max_tokens <= 0:
        return message
    overhead = estimate_message_tokens({**message, "content": ""}, model=model)
    content_budget = max(_MIN_TRUNCATED_TOKENS, max_tokens - overhead)
    content = str(message.get("content") or "")
    if estimate_message_tokens(message, model=model) <= max_tokens:
        return message
    trimmed = truncate_text_to_tokens(content, content_budget, model=model)
    return {**message, "content": trimmed}


def _message_identity(message: dict[str, Any]) -> tuple[str, str, str, str]:
    tool_calls = message.get("tool_calls")
    tool_calls_key = ""
    if isinstance(tool_calls, list):
        try:
            tool_calls_key = json.dumps(tool_calls, sort_keys=True, default=str)
        except (TypeError, ValueError):
            tool_calls_key = str(tool_calls)
    return (
        str(message.get("role") or ""),
        str(message.get("content") or ""),
        str(message.get("tool_call_id") or ""),
        tool_calls_key,
    )


def _contains_message(messages: list[dict[str, Any]], target: dict[str, Any]) -> bool:
    target_key = _message_identity(target)
    return any(_message_identity(message) == target_key for message in messages)


def _prompt_budget(
    max_context_tokens: int,
    reserve_output_tokens: int,
    tools_tokens: int,
) -> int:
    return max(512, int(max_context_tokens) - int(reserve_output_tokens) - tools_tokens)


def fit_messages_to_token_budget(
    messages: list[dict[str, Any]],
    *,
    max_context_tokens: int,
    reserve_output_tokens: int,
    tool_schemas: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """Keep system message + newest history that fits the prompt budget."""
    if not messages:
        return [], 0, 0

    tools_tokens = estimate_tools_tokens(tool_schemas, model=model)
    prompt_budget = _prompt_budget(max_context_tokens, reserve_output_tokens, tools_tokens)

    system = messages[0]
    history = messages[1:]
    last_user = next((item for item in reversed(history) if item.get("role") == "user"), None)

    system_tokens = estimate_message_tokens(system, model=model)
    if system_tokens > prompt_budget:
        system = truncate_message_for_budget(system, prompt_budget, model=model)
        fitted = [system]
        if last_user and not _contains_message(fitted, last_user):
            user_budget = max(
                _MIN_TRUNCATED_TOKENS,
                prompt_budget - estimate_message_tokens(system, model=model),
            )
            if user_budget > 0:
                fitted.append(truncate_message_for_budget(last_user, user_budget, model=model))
        prompt_tokens = count_messages_tokens(fitted, model=model) + tools_tokens
        dropped = max(0, len(history) - max(0, len(fitted) - 1))
        return fitted, prompt_tokens, dropped

    kept: list[dict[str, Any]] = []
    running = system_tokens

    for message in reversed(history):
        candidate = message
        message_tokens = estimate_message_tokens(candidate, model=model)
        if not kept and running + message_tokens > prompt_budget:
            candidate = truncate_message_for_budget(
                candidate,
                prompt_budget - running,
                model=model,
            )
            message_tokens = estimate_message_tokens(candidate, model=model)
        if kept and running + message_tokens > prompt_budget:
            continue
        kept.append(candidate)
        running += message_tokens

    kept.reverse()

    if last_user and not _contains_message(kept, last_user):
        while kept:
            trial = kept[1:]
            trial_tokens = count_messages_tokens([system, *trial, last_user], model=model)
            if trial_tokens <= prompt_budget:
                kept = trial
                break
            kept.pop(0)
        user_budget = max(
            _MIN_TRUNCATED_TOKENS,
            prompt_budget - count_messages_tokens([system, *kept], model=model),
        )
        kept.append(truncate_message_for_budget(last_user, user_budget, model=model))

    while kept:
        fitted = [system, *kept]
        if count_messages_tokens(fitted, model=model) <= prompt_budget:
            break
        kept.pop(0)

    fitted = [system, *kept]
    dropped = max(0, len(history) - len(kept))
    prompt_tokens = count_messages_tokens(fitted, model=model) + tools_tokens

    if prompt_tokens > int(max_context_tokens):
        logger.warning(
            "Fitted prompt still exceeds max_context_tokens (%s > %s); model=%r",
            prompt_tokens,
            max_context_tokens,
            model,
        )

    return fitted, prompt_tokens, dropped
