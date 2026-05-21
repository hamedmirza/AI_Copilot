"""Validation runner — delegates to command_runner with profile-aware command lists."""

import json
from pathlib import Path

from app.tools.command_runner import run_command, validate_command

DEFAULT_PROFILES = {
    "python": ["ruff check .", "python3 -m compileall ."],
    "react": ["npm --prefix frontend run lint"],
    "fullstack": ["ruff check .", "python3 -m compileall ."],
    "node": ["npm run lint"],
    "custom": [],
}


def get_profile_commands(profiles_json: str, profile: str) -> list[str]:
    try:
        profiles = json.loads(profiles_json)
    except json.JSONDecodeError:
        profiles = DEFAULT_PROFILES
    return profiles.get(profile, DEFAULT_PROFILES.get(profile, []))


def run_profile_validation(workspace: Path, profiles_json: str, profile: str) -> list[dict]:
    results = []
    for command in get_profile_commands(profiles_json, profile):
        validate_command(command)
        code, stdout, stderr = run_command(command, workspace)
        results.append(
            {"command": command, "exit_code": code, "stdout": stdout[:2000], "stderr": stderr[:2000]}
        )
    return results
