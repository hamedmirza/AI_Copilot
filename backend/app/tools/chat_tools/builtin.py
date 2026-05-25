from __future__ import annotations

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
from app.services.web_search_service import WebSearchError, WebSearchService


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
    from app.core.exceptions import PatchGuardError
    from app.services.contract_guard import contract_guard_issues
    from app.services.integration_guard import integration_guard_issues

    path = str(arguments.get("path") or "").strip()
    content = str(arguments.get("content") or "")
    result = context.file_service.write_file(path, content)
    rel = path.replace("\\", "/")
    if rel.startswith("frontend/src/pages/") or rel.startswith("frontend/src/routes/"):
        issues = integration_guard_issues(context.workspace, changed_files=[rel]) + contract_guard_issues(
            context.workspace, [rel]
        )
        critical = [item for item in issues if item.get("severity") == "critical"]
        if critical:
            message = "; ".join(str(item.get("message") or "") for item in critical[:2])
            raise PatchGuardError("chat_write_guard", f"Chat write blocked by deployment gate: {message}")
    return result


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
    allow_web_search = bool(arguments.get("allow_web_search", context.session.allow_web_search))
    return context.pipeline_bridge.spawn(
        context.db,
        session_id=context.session.id,
        project_id=context.project.id,
        description=description,
        validation_profile=str(validation_profile) if validation_profile else None,
        allow_web_search=allow_web_search,
    )


def _web_search(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    if not context.session.allow_web_search:
        raise ValueError("Web search is disabled for this chat session")
    query = str(arguments.get("query") or "").strip()
    limit = max(1, min(int(arguments.get("limit") or 5), 8))
    try:
        return WebSearchService().search_payload(query, limit=limit)
    except WebSearchError as exc:
        raise ValueError(str(exc)) from exc


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


def _browser_tool(action: str, arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    from app.services.browser_control_service import browser_control

    project_id = context.project.id
    args = dict(arguments)
    if action == "navigate":
        url = browser_control.validate_loopback_url(str(args.get("url") or ""))
        args = {"url": url}
    result = browser_control.execute_sync(project_id, action, args)
    if not result.get("ok"):
        error = str(result.get("error") or "browser command failed")
        raise ValueError(error)
    payload = dict(result.get("result") or {})
    if action == "screenshot" and isinstance(payload.get("dataUrl"), str):
        data_url = payload["dataUrl"]
        payload["dataUrl"] = data_url[:120] + "…" if len(data_url) > 120 else data_url
    return payload


def _browser_navigate(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    return _browser_tool("navigate", arguments, context)


def _browser_snapshot(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    return _browser_tool("snapshot", arguments, context)


def _browser_click(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    return _browser_tool("click", arguments, context)


def _browser_type(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    return _browser_tool("type", arguments, context)


def _browser_screenshot(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    return _browser_tool("screenshot", arguments, context)


def _browser_wait(arguments: dict[str, Any], context: ToolExecutionContext) -> dict[str, Any]:
    args = dict(arguments)
    args["timeout_ms"] = int(args.get("timeout_ms") or 8000)
    return _browser_tool("wait_for", args, context)


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
                "allow_web_search": {"type": "boolean"},
            },
            "required": ["description"],
        },
        handler=_spawn_pipeline_task,
    ),
    "web_search": ToolSpec(
        name="web_search",
        description="Search the public web for current external information relevant to the task.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        handler=_web_search,
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
    "browser_navigate": ToolSpec(
        name="browser_navigate",
        description="Navigate the IDE browser panel to a loopback URL and load the page for verification.",
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        handler=_browser_navigate,
    ),
    "browser_snapshot": ToolSpec(
        name="browser_snapshot",
        description="Capture visible text and metadata from the IDE browser preview.",
        parameters={
            "type": "object",
            "properties": {"selector": {"type": "string"}},
        },
        handler=_browser_snapshot,
    ),
    "browser_click": ToolSpec(
        name="browser_click",
        description="Click an element in the IDE browser preview by CSS selector.",
        parameters={
            "type": "object",
            "properties": {"selector": {"type": "string"}},
            "required": ["selector"],
        },
        handler=_browser_click,
    ),
    "browser_type": ToolSpec(
        name="browser_type",
        description="Type text into an input in the IDE browser preview.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "clear": {"type": "boolean"},
            },
            "required": ["selector", "text"],
        },
        handler=_browser_type,
    ),
    "browser_screenshot": ToolSpec(
        name="browser_screenshot",
        description="Capture a screenshot from the IDE browser preview (returns truncated data URL).",
        parameters={
            "type": "object",
            "properties": {"selector": {"type": "string"}},
        },
        handler=_browser_screenshot,
    ),
    "browser_wait": ToolSpec(
        name="browser_wait",
        description="Wait for a selector or visible text in the IDE browser preview.",
        parameters={
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "timeout_ms": {"type": "integer"},
            },
        },
        handler=_browser_wait,
    ),
}
