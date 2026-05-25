from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.services.workspace_service import prepare_run_workspace
from app.tools.lint_runner import canonical_frontend_required_commands, scope_profile_commands


def test_scope_profile_commands_python():
    commands = scope_profile_commands(
        ["ruff check .", "python3 -m compileall .", "mypy ."],
        ["backend/app/main.py", "frontend/src/App.tsx"],
    )
    assert commands == [
        "ruff check backend/app/main.py",
        "python3 -m compileall -q backend/app/main.py",
        "mypy backend/app/main.py",
    ]


def test_scope_profile_commands_frontend():
    commands = scope_profile_commands(
        ["npm --prefix frontend run lint"],
        ["frontend/src/types/runs.ts", "frontend/src/components/AgentPanel/RunHistoryList.tsx"],
    )
    assert commands == [
        "eslint frontend/src/types/runs.ts frontend/src/components/AgentPanel/RunHistoryList.tsx",
    ]


def test_canonical_frontend_required_commands_scopes_lint():
    commands = canonical_frontend_required_commands(
        ["npm --prefix frontend run lint"],
        ["frontend/src/types/runs.ts"],
    )
    assert commands[0].startswith("eslint frontend/src/types/runs.ts")
    assert "npm --prefix frontend run build" in commands


def test_prepare_run_workspace_ignores_runtime_workspaces(tmp_path: Path):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "app.py").write_text("print('ok')\n", encoding="utf-8")
    archived = source / "runtime" / "workspaces" / "older-run"
    archived.mkdir(parents=True)
    (archived / "artifact.txt").write_text("ignore me\n", encoding="utf-8")
    legacy = source / "backend" / "workspaces" / "legacy-run"
    legacy.mkdir(parents=True)
    (legacy / "artifact.txt").write_text("ignore me too\n", encoding="utf-8")

    workspace = prepare_run_workspace(source, "self-hosted-run")

    assert (workspace / "app.py").exists()
    assert not (workspace / "runtime" / "workspaces").exists()
    assert not (workspace / "backend" / "workspaces").exists()


def test_prepare_run_workspace_rejects_workspace_source(tmp_path: Path):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "main.py").write_text("x = 1\n", encoding="utf-8")
    workspace = prepare_run_workspace(source, "good-run")
    with pytest.raises(ValidationError, match="cannot be inside run workspaces"):
        prepare_run_workspace(workspace, "bad-run")


def test_prepare_run_workspace_clone_from_repo_root(tmp_path: Path, monkeypatch):
    repo = tmp_path / "AI_Copilot"
    repo.mkdir()
    (repo / "README.md").write_text("repo\n", encoding="utf-8")
    nested = repo / "runtime" / "workspaces" / "old-run"
    nested.mkdir(parents=True)
    (nested / "stale.txt").write_text("stale\n", encoding="utf-8")

    monkeypatch.setattr("app.services.workspace_service.runs_root", lambda: tmp_path / "runtime" / "workspaces")

    workspace = prepare_run_workspace(repo, "fresh-run")
    assert (workspace / "README.md").exists()
    assert not (workspace / "runtime" / "workspaces").exists()
