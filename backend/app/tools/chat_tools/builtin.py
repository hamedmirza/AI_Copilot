from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.core.logging import read_log_lines
from app.db.models import ChatSessionModel, ProjectModel
from app.services.config_service import ConfigService
from app.services.git_service import GitService
from app.services.pipeline_bridge import PipelineBridge, pipeline_bridge
from app.services.file_service import FileService
from app.tools.command_runner import run_command
from app.tools.lint_runner import run_profile_validation


@dataclass
class ToolExecutionContext:
    db: Session
    project: ProjectModel
    session: ChatSessionModel
    pipeline_bridge: PipelineBridge = pipeline_bridge

    @property
    def workspace(self) -> Path:
        return Path(self.project.source_repo_spec)

    @property
    def file_service(self) -> FileService:
        return FileService(self.workspace, self.project.protected_files)

    @property
    def git_service(self) -> GitService:
        return GitService(self.workspace)


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[dict[str, Any], ToolExecutionContext], Any]

    def to_openai(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _read_file(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    return context.file_service.read_file(path)


def _write_file(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    content = str(arguments.get("content") or "")
    return context.file_service.write_file(path, content)


def _list_files(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    rel_path = str(arguments.get("path") or ".")
    return context.file_service.tree(rel_path)


def _search_files(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    rel_path = str(arguments.get("path") or ".").strip() or "."
    limit = max(1, min(int(arguments.get("limit") or 20), 100))
    root = (context.workspace / rel_path).resolve()
    workspace_root = context.workspace.resolve()
    if not str(root).startswith(str(workspace_root)) or not root.exists():
        return {"matches": []}
    ignored = {".git", ".venv", "node_modules", "__pycache__", ".mypy_cache", ".pytest_cache"}
    matches: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        if len(matches) >= limit:
            break
        if any(part in ignored for part in path.parts):
            continue
        if not path.is_file():
            continue
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


def _git_status(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    status = context.git_service.status()
    status["branch"] = context.git_service.current_branch()
    status["has_remote"] = context.git_service.has_remote()
    return status


def _git_diff(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    path = str(arguments.get("path") or "").strip()
    return context.git_service.diff(path)


def _git_commit(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    message = str(arguments.get("message") or "").strip()
    config = ConfigService(context.db).get_all()
    sha = context.git_service.commit(
        message,
        str(config.get("git_author_name", "AI Copilot")),
        str(config.get("git_author_email", "copilot@local.dev")),
    )
    return {"sha": sha}


def _run_command(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    command = str(arguments.get("command") or "").strip()
    timeout = int(arguments.get("timeout") or 300)
    code, stdout, stderr = run_command(command, context.workspace, timeout=timeout)
    return {"exit_code": code, "stdout": stdout[:4000], "stderr": stderr[:4000]}


def _run_lint_profile(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    profile = str(arguments.get("profile") or context.project.validation_profile)
    profiles_json = str(ConfigService(context.db).get_all().get("validation_profiles_json", "{}"))
    return {"results": run_profile_validation(context.workspace, profiles_json, profile)}


def _read_logs(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    limit = max(1, min(int(arguments.get("limit") or 200), 500))
    level = str(arguments.get("level") or "").lower()
    lines = read_log_lines(limit)
    if level:
        lines = [line for line in lines if str(line.get("level") or "").lower() == level]
    return {"lines": lines}


def _spawn_pipeline_task(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    description = str(arguments.get("description") or "").strip()
    validation_profile = arguments.get("validation_profile")
    return context.pipeline_bridge.spawn(
        context.db,
        session_id=context.session.id,
        project_id=context.project.id,
        description=description,
        validation_profile=str(validation_profile) if validation_profile else None,
    )


def _write_artifact(arguments: dict[str, Any], context: ToolExecutionContext, artifact_type: str) -> dict[str, Any]:
    title = str(arguments.get("title") or artifact_type).strip() or artifact_type
    content = str(arguments.get("content") or "").strip()
    slug = title.lower().replace(" ", "-").replace("/", "-")[:80]
    path = f".ai-copilot/{artifact_type}s/{slug}.md"
    markdown = f"# {title}\n\n{content}\n"
    return context.file_service.write_file(path, markdown)


def _write_plan_artifact(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    return _write_artifact(arguments, context, "plan")


def _write_design_artifact(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    return _write_artifact(arguments, context, "design")


BUILTIN_CHAT_TOOLS: dict[str, ToolSpec] = {
    "read_file": ToolSpec(
        name="read_file",
        description="Read a file from the current project workspace.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=_read_file,
    ),
    "write_file": ToolSpec(
        name="write_file",
        description="Write full file contents in the current project workspace.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        handler=_write_file,
    ),
    "list_files": ToolSpec(
        name="list_files",
        description="List files and directories in the current project workspace.",
        parameters={"type": "object", "properties": {"path": {"type": "string"}}},
        handler=_list_files,
    ),
    "search_files": ToolSpec(
        name="search_files",
        description="Search text across files in the current project workspace.",
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
    "git_status": ToolSpec(
        name="git_status",
        description="Get git status for the current project.",
        parameters={"type": "object", "properties": {}},
        handler=_git_status,
    ),
    "git_diff": ToolSpec(
        name="git_diff",
        description="Read the git diff for a file in the current project.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=_git_diff,
    ),
    "git_commit": ToolSpec(
        name="git_commit",
        description="Create a git commit with the given message.",
        parameters={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        handler=_git_commit,
    ),
    "run_command": ToolSpec(
        name="run_command",
        description="Run a safe allowlisted shell command in the project workspace.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer"},
            },
            "required": ["command"],
        },
        handler=_run_command,
    ),
    "run_lint_profile": ToolSpec(
        name="run_lint_profile",
        description="Run the configured validation profile for the project.",
        parameters={"type": "object", "properties": {"profile": {"type": "string"}}},
        handler=_run_lint_profile,
    ),
    "read_logs": ToolSpec(
        name="read_logs",
        description="Read recent backend logs.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer"},
                "level": {"type": "string"},
            },
        },
        handler=_read_logs,
    ),
    "spawn_pipeline_task": ToolSpec(
        name="spawn_pipeline_task",
        description="Spawn the existing multi-agent pipeline for a project task.",
        parameters={
            "type": "object",
            "properties": {
                "description": {"type": "string"},
                "validation_profile": {"type": "string"},
            },
            "required": ["description"],
        },
        handler=_spawn_pipeline_task,
    ),
    "write_plan_artifact": ToolSpec(
        name="write_plan_artifact",
        description="Write a markdown planning artifact into .ai-copilot/plans.",
        parameters={
            "type": "object",
            "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
            "required": ["title", "content"],
        },
        handler=_write_plan_artifact,
    ),
    "write_design_artifact": ToolSpec(
        name="write_design_artifact",
        description="Write a markdown design artifact into .ai-copilot/designs.",
        parameters={
            "type": "object",
            "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
            "required": ["title", "content"],
        },
        handler=_write_design_artifact,
    ),
}
