from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.exceptions import CommandRejectedError, NotFoundError, PathTraversalError
from app.core.logging import read_log_lines
from app.db.models import ProjectModel, RunModel
from app.services.file_service import FileService
from app.services.git_service import GitService
from app.services.web_search_service import WebSearchError, WebSearchService
from app.tools.command_runner import run_command, validate_command


@dataclass
class PipelineToolExecutionContext:
    db: Session
    project: ProjectModel
    run: RunModel
    workspace: Path

    @property
    def file_service(self) -> FileService:
        return FileService(self.workspace, self.project.protected_files)

    @property
    def git_service(self) -> GitService:
        return GitService(self.workspace)


@dataclass
class PipelineToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], PipelineToolExecutionContext], Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _read_file(arguments: dict[str, Any], context: PipelineToolExecutionContext) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    return context.file_service.read_file(path)


def _list_files(arguments: dict[str, Any], context: PipelineToolExecutionContext) -> dict[str, Any]:
    rel_path = str(arguments.get("path") or ".").strip() or "."
    return context.file_service.tree(rel_path)


def _search_files(arguments: dict[str, Any], context: PipelineToolExecutionContext) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    rel_path = str(arguments.get("path") or ".").strip() or "."
    limit = max(1, min(int(arguments.get("limit") or 20), 100))
    root = (context.workspace / rel_path).resolve()
    workspace_root = context.workspace.resolve()
    if not str(root).startswith(str(workspace_root)) or not root.exists():
        return {"matches": []}
    from app.services.workspace_walk import iter_workspace_files

    matches: list[dict[str, Any]] = []
    for path in iter_workspace_files(root):
        if len(matches) >= limit:
            break
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        line_hits = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            if query.lower() in line.lower():
                line_hits.append({"line": line_no, "content": line[:300]})
                if len(line_hits) >= 5:
                    break
        if line_hits:
            matches.append({"path": path.relative_to(context.workspace).as_posix(), "matches": line_hits})
    return {"matches": matches}


def _git_status(_arguments: dict[str, Any], context: PipelineToolExecutionContext) -> dict[str, Any]:
    status = context.git_service.status()
    status["branch"] = context.git_service.current_branch()
    return status


def _git_diff(arguments: dict[str, Any], context: PipelineToolExecutionContext) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    return context.git_service.diff(path)


def _run_command(arguments: dict[str, Any], context: PipelineToolExecutionContext) -> dict[str, Any]:
    command = str(arguments.get("command") or "").strip()
    timeout = int(arguments.get("timeout") or 300)
    validate_command(command)
    code, stdout, stderr = run_command(command, context.workspace, timeout=timeout)
    return {"exit_code": code, "stdout": stdout[:4000], "stderr": stderr[:4000]}


def _read_logs(arguments: dict[str, Any], _context: PipelineToolExecutionContext) -> dict[str, Any]:
    limit = max(1, min(int(arguments.get("limit") or 200), 500))
    level = str(arguments.get("level") or "").lower()
    lines = read_log_lines(limit)
    if level:
        lines = [line for line in lines if str(line.get("level") or "").lower() == level]
    return {"lines": lines}


def _web_search(arguments: dict[str, Any], _context: PipelineToolExecutionContext) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    limit = max(1, min(int(arguments.get("limit") or 5), 8))
    try:
        return WebSearchService().search_payload(query, limit=limit)
    except WebSearchError as exc:
        raise ValueError(str(exc)) from exc


PIPELINE_BASE_TOOLS: dict[str, PipelineToolSpec] = {
    "read_file": PipelineToolSpec(
        name="read_file",
        description=(
            "Read an existing file from the run workspace by relative path. "
            "Use list_files or search_files to discover paths first. "
            "Tool names (e.g. web_search) are not files — call those tools directly."
        ),
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=_read_file,
    ),
    "list_files": PipelineToolSpec(
        name="list_files",
        description="List files and directories in the run workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        handler=_list_files,
    ),
    "search_files": PipelineToolSpec(
        name="search_files",
        description="Search text across files in the run workspace.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        handler=_search_files,
    ),
    "git_status": PipelineToolSpec(
        name="git_status",
        description="Get git status for the run workspace.",
        parameters={"type": "object", "properties": {}},
        handler=_git_status,
    ),
    "git_diff": PipelineToolSpec(
        name="git_diff",
        description="Read the git diff for a file in the run workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        handler=_git_diff,
    ),
    "run_command": PipelineToolSpec(
        name="run_command",
        description="Run a safe allowlisted shell command in the run workspace.",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}},
            "required": ["command"],
        },
        handler=_run_command,
    ),
    "read_logs": PipelineToolSpec(
        name="read_logs",
        description="Read recent backend logs.",
        parameters={"type": "object", "properties": {"limit": {"type": "integer"}, "level": {"type": "string"}}},
        handler=_read_logs,
    ),
}

PIPELINE_WEB_SEARCH_TOOL = PipelineToolSpec(
    name="web_search",
    description=(
        "Search the public web for current external information. "
        "Providers are configured in WEB_SEARCH_PROVIDERS (duckduckgo, github, google, x). "
        "Invoke by tool name — not a workspace file."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["query"],
    },
    handler=_web_search,
)


class PipelineToolRuntime:
    def __init__(
        self,
        context: PipelineToolExecutionContext,
        *,
        allow_web_search: bool,
        on_tool_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.context = context
        self.allow_web_search = allow_web_search
        self.on_tool_event = on_tool_event
        self._tools = dict(PIPELINE_BASE_TOOLS)
        if allow_web_search:
            self._tools[PIPELINE_WEB_SEARCH_TOOL.name] = PIPELINE_WEB_SEARCH_TOOL

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_openai() for tool in self._tools.values()]

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool not found: {tool_name}")
        if self.on_tool_event:
            self.on_tool_event("start", {"tool": tool_name, "arguments": arguments})
        try:
            result = tool.handler(arguments, self.context)
        except (NotFoundError, PathTraversalError, CommandRejectedError, ValueError) as exc:
            if self.on_tool_event:
                self.on_tool_event("error", {"tool": tool_name, "arguments": arguments, "error": str(exc)})
            return json.dumps({"ok": False, "error": str(exc), "tool": tool_name})
        except Exception as exc:
            if self.on_tool_event:
                self.on_tool_event("error", {"tool": tool_name, "arguments": arguments, "error": str(exc)})
            raise
        serialized = result if isinstance(result, str) else json.dumps(result, default=str)
        if self.on_tool_event:
            self.on_tool_event("end", {"tool": tool_name, "arguments": arguments, "result": serialized})
        return serialized
