"""Validation runner — delegates to command_runner with profile-aware command lists."""

import json
import shlex
from pathlib import Path

from app.tools.command_runner import run_command, validate_command

DEFAULT_PROFILES = {
    "python": ["ruff check .", "python3 -m compileall ."],
    "react": ["npm --prefix frontend run lint"],
    "fullstack": ["ruff check .", "python3 -m compileall ."],
    "node": ["npm run lint"],
    "custom": [],
}

_FRONTEND_LINT_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".html"}
_PYTHON_SUFFIXES = {".py", ".pyi"}


def get_profile_commands(profiles_json: str, profile: str) -> list[str]:
    try:
        profiles = json.loads(profiles_json)
    except json.JSONDecodeError:
        profiles = DEFAULT_PROFILES
    return profiles.get(profile, DEFAULT_PROFILES.get(profile, []))


def _quoted_paths(paths: list[str]) -> str:
    return " ".join(shlex.quote(path) for path in paths)


def scope_profile_commands(commands: list[str], changed_files: list[str]) -> list[str]:
    if not commands or not changed_files:
        return commands

    python_files = [path for path in changed_files if Path(path).suffix.lower() in _PYTHON_SUFFIXES]
    frontend_files = [
        path
        for path in changed_files
        if path.startswith("frontend/") and Path(path).suffix.lower() in _FRONTEND_LINT_SUFFIXES
    ]

    scoped: list[str] = []
    for command in commands:
        normalized = command.strip()
        if normalized == "ruff check ." and python_files:
            scoped.append(f"ruff check {_quoted_paths(python_files)}")
        elif normalized == "python3 -m compileall ." and python_files:
            scoped.append(f"python3 -m compileall -q {_quoted_paths(python_files)}")
        elif normalized in {"mypy .", "mypy"} and python_files:
            scoped.append(f"mypy {_quoted_paths(python_files)}")
        elif normalized == "npm --prefix frontend run lint" and frontend_files:
            scoped.append(f"eslint {_quoted_paths(frontend_files)}")
        else:
            scoped.append(command)
    return scoped


def canonical_frontend_dry_run_commands(workspace: Path | None = None) -> list[str]:
    _ = workspace
    # Run from repo/workspace root; npm --prefix frontend runs tsc via vite build.
    return ["npm --prefix frontend run build"]


def normalize_tester_dry_run_commands(
    llm_commands: list[str],
    changed_files: list[str],
    workspace: Path | None = None,
) -> list[str]:
    _ = llm_commands
    if not any(path.startswith("frontend/") for path in changed_files):
        return llm_commands
    return canonical_frontend_dry_run_commands(workspace)


def canonical_frontend_required_commands(profile_commands: list[str], changed_files: list[str]) -> list[str]:
    commands = ["npm --prefix frontend run build"]
    wants_lint = "npm --prefix frontend run lint" in profile_commands
    frontend_changed = [
        path
        for path in changed_files
        if path.startswith("frontend/") and Path(path).suffix.lower() in _FRONTEND_LINT_SUFFIXES
    ]
    if wants_lint and frontend_changed:
        commands.insert(0, f"eslint {_quoted_paths(frontend_changed)}")
    elif wants_lint:
        commands.insert(0, "npm --prefix frontend run lint")
    return commands


def run_profile_validation(workspace: Path, profiles_json: str, profile: str) -> list[dict]:
    results = []
    for command in get_profile_commands(profiles_json, profile):
        validate_command(command)
        code, stdout, stderr = run_command(command, workspace)
        results.append(
            {"command": command, "exit_code": code, "stdout": stdout[:2000], "stderr": stderr[:2000]}
        )
    return results
