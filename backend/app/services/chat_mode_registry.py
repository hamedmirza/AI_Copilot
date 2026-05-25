import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatModeDefinition:
    key: str
    label: str
    description: str
    system_prompt: str
    allowed_tools: list[str] = field(default_factory=list)
    max_tool_rounds: int = 10
    allow_mcp: bool = False
    model_key: str = "model_chat"
    read_only: bool = True
    skill_key: str | None = None


class ChatModeRegistry:
    _BUILTINS: dict[str, ChatModeDefinition] = {
        "general": ChatModeDefinition(
            key="general",
            label="General",
            description="General-purpose project chat with read-only tools.",
            system_prompt=(
                "You are AI Copilot. Be concise. For LM Studio/Ollama URL or IP questions, use "
                "runtime_settings in context only (no tools). For code questions, read files before claiming."
            ),
            allowed_tools=["read_file", "list_files", "search_files", "web_search"],
            max_tool_rounds=4,
            allow_mcp=False,
            model_key="model_chat",
            read_only=True,
        ),
        "agent": ChatModeDefinition(
            key="agent",
            label="Agent",
            description="Autonomous coding assistant with write and pipeline tools.",
            system_prompt=(
                "You are an autonomous coding assistant working inside the user's project. "
                "Prefer targeted tool use, make the minimum safe change, and explain outcomes clearly."
            ),
            allowed_tools=[
                "read_file",
                "write_file",
                "list_files",
                "search_files",
                "git_status",
                "git_diff",
                "git_commit",
                "run_command",
                "run_lint_profile",
                "read_logs",
                "web_search",
                "spawn_pipeline_task",
                "browser_navigate",
                "browser_snapshot",
                "browser_click",
                "browser_type",
                "browser_screenshot",
                "browser_wait",
            ],
            max_tool_rounds=16,
            allow_mcp=True,
            model_key="model_chat_agent",
            read_only=False,
        ),
        "planner": ChatModeDefinition(
            key="planner",
            label="Planner",
            description="Planning-first mode with plan artifact output.",
            system_prompt=(
                "You are a planning specialist. Produce structured implementation plans and identify "
                "risks before coding."
            ),
            allowed_tools=["read_file", "list_files", "search_files", "web_search", "write_plan_artifact"],
            max_tool_rounds=6,
            allow_mcp=False,
            model_key="model_chat_planner",
            read_only=False,
        ),
        "debugger": ChatModeDefinition(
            key="debugger",
            label="Debugger",
            description="Debugging mode focused on diffs, logs, commands, and validation.",
            system_prompt=(
                "You are a debugging specialist. Form hypotheses, gather evidence, and prefer logs, "
                "diffs, and small validation commands before proposing fixes."
            ),
            allowed_tools=[
                "read_file",
                "search_files",
                "git_diff",
                "run_command",
                "run_lint_profile",
                "read_logs",
                "web_search",
                "browser_navigate",
                "browser_snapshot",
                "browser_click",
                "browser_type",
                "browser_screenshot",
                "browser_wait",
            ],
            max_tool_rounds=12,
            allow_mcp=False,
            model_key="model_chat_debugger",
            read_only=True,
        ),
        "architect": ChatModeDefinition(
            key="architect",
            label="Architect",
            description="High-level design mode with design artifact output.",
            system_prompt=(
                "You are a software architect. Focus on trade-offs, boundaries, and implementation "
                "sequencing rather than code-level detail."
            ),
            allowed_tools=["read_file", "list_files", "search_files", "web_search", "write_design_artifact"],
            max_tool_rounds=6,
            allow_mcp=False,
            model_key="model_chat_architect",
            read_only=False,
        ),
    }

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def list_modes(self) -> list[ChatModeDefinition]:
        custom = self._load_custom_modes()
        merged = {**self._BUILTINS, **custom}
        return list(merged.values())

    def get_mode(self, key: str | None) -> ChatModeDefinition:
        lookup = (key or "general").strip().lower()
        modes = {mode.key: mode for mode in self.list_modes()}
        return modes.get(lookup, self._BUILTINS["general"])

    def _load_custom_modes(self) -> dict[str, ChatModeDefinition]:
        raw = self.config.get("chat_modes_json", "[]")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if not isinstance(data, list):
            return {}
        custom: dict[str, ChatModeDefinition] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or item.get("name") or "").strip().lower()
            if not key:
                continue
            raw_skill_key = str(item.get("skill_key") or "").strip()
            custom[key] = ChatModeDefinition(
                key=key,
                label=str(item.get("label") or key.title()),
                description=str(item.get("description") or "Custom chat mode"),
                system_prompt=str(item.get("system_prompt") or item.get("prompt") or ""),
                allowed_tools=[str(tool) for tool in item.get("allowed_tools", [])],
                max_tool_rounds=int(item.get("max_tool_rounds", 6)),
                allow_mcp=bool(item.get("allow_mcp", False)),
                model_key=str(item.get("model_key") or "model_chat"),
                read_only=bool(item.get("read_only", True)),
                skill_key=raw_skill_key or None,
            )
        return custom
