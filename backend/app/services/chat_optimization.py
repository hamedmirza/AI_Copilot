from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

_WEB_RESEARCH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:latest|current|recent|today'?s?|breaking)\b.{0,40}\b(?:news|headlines|updates?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:news|headlines|updates?)\b.{0,40}\b(?:about|on|in|from)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat(?:'s| is)\b.{0,30}\b(?:happening|going on)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:search|look up|find)\b.{0,30}\b(?:online|on the web|the internet)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bweb\s*search\b", re.IGNORECASE),
    re.compile(r"\bsearch\b.{0,24}\b(?:the\s+)?web\b", re.IGNORECASE),
)

_RUNTIME_SETTINGS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:lm\s*studio|lmstudio)\b.{0,80}\b(?:ip|url|host|address|port|server|connect|endpoint)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ip|url|host|address|port|server)\b.{0,80}\b(?:lm\s*studio|lmstudio)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ollama)\b.{0,80}\b(?:ip|url|host|address|port|server|connect|endpoint)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhat\b.{0,40}\b(?:lm\s*studio|lmstudio|ollama)\b.{0,60}\b(?:ip|url|host|server)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhich\b.{0,30}\b(?:ip|url|host)\b.{0,60}\b(?:lm|studio|ollama|copilot|provider)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:provider|connection)\b.{0,40}\b(?:url|ip|host|endpoint)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\blm\s*studio\s+serve(?:r)?\s+ip\b", re.IGNORECASE),
)


def is_web_research_question(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _WEB_RESEARCH_PATTERNS)


def web_search_tool_choice() -> dict[str, Any]:
    return {"type": "function", "function": {"name": "web_search"}}


def is_runtime_settings_question(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return False
    return any(pattern.search(normalized) for pattern in _RUNTIME_SETTINGS_PATTERNS)


def format_runtime_settings_answer(runtime: dict[str, str]) -> str:
    active = str(runtime.get("active_provider") or "lmstudio").strip().lower()
    lines = ["Live values from **AI Copilot Settings** (not `.env` or code defaults):"]
    if active == "ollama":
        lines.append(f"- **Active provider:** Ollama")
        lines.append(f"- **Base URL:** `{runtime.get('ollama_base_url') or '(not set)'}`")
        if runtime.get("ollama_model_default"):
            lines.append(f"- **Default model:** `{runtime['ollama_model_default']}`")
    else:
        lines.append("- **Active provider:** LM Studio")
        url = str(runtime.get("lmstudio_base_url") or "").strip()
        lines.append(f"- **Base URL:** `{url or '(not set)'}`")
        host = _host_port_from_url(url)
        if host:
            lines.append(f"- **Host:port:** `{host}`")
        if runtime.get("lmstudio_model_default"):
            lines.append(f"- **Default model:** `{runtime['lmstudio_model_default']}`")
        lines.append(f"- *(Ollama URL if switched:* `{runtime.get('ollama_base_url') or '(not set)'}`*)")
    return "\n".join(lines)


def _host_port_from_url(url: str) -> str:
    parsed = urlparse(url if "://" in url else f"http://{url}")
    if parsed.hostname:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return f"{parsed.hostname}:{port}"
    return ""


def effective_max_output_tokens(
    mode_key: str,
    config: dict[str, Any],
    user_text: str,
) -> int:
    configured = max(256, min(int(config.get("chat_max_output_tokens", 4096) or 4096), 32_768))
    if is_runtime_settings_question(user_text):
        return min(configured, 512)
    if mode_key == "general":
        return min(configured, 1536)
    if mode_key in {"planner", "debugger", "architect"}:
        return min(configured, 3072)
    return configured


def should_offer_tools(
    mode_key: str,
    user_text: str,
    *,
    read_only: bool,
) -> bool:
    if not read_only and mode_key == "agent":
        return True
    if mode_key == "general" and is_runtime_settings_question(user_text):
        return False
    return True


def should_force_web_search_tool(
    user_text: str,
    *,
    allow_web_search: bool,
    has_web_search_tool: bool,
    tool_round_index: int,
) -> bool:
    if tool_round_index > 0:
        return False
    if not allow_web_search or not has_web_search_tool:
        return False
    return is_web_research_question(user_text)
