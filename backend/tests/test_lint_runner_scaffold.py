from pathlib import Path

from app.tools.lint_runner import (
    FRONTEND_SCAFFOLD_MESSAGE,
    canonical_frontend_dry_run_commands,
    canonical_frontend_required_commands,
    is_frontend_npm_command,
    partition_frontend_commands,
    workspace_has_frontend_package,
)


def test_is_frontend_npm_command():
    assert is_frontend_npm_command("npm --prefix frontend run build")
    assert not is_frontend_npm_command("pytest -q")


def test_partition_frontend_commands_blocks_without_package_json(tmp_path: Path):
    runnable, blocked = partition_frontend_commands(
        ["ruff check .", "npm --prefix frontend run build"],
        tmp_path,
    )
    assert runnable == ["ruff check ."]
    assert blocked == ["npm --prefix frontend run build"]


def test_partition_frontend_commands_allows_with_package_json(tmp_path: Path):
    pkg = tmp_path / "frontend"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text('{"name":"frontend"}\n', encoding="utf-8")
    runnable, blocked = partition_frontend_commands(
        ["npm --prefix frontend run build"],
        tmp_path,
    )
    assert runnable == ["npm --prefix frontend run build"]
    assert blocked == []


def test_canonical_frontend_helpers_empty_without_scaffold(tmp_path: Path):
    assert canonical_frontend_dry_run_commands(tmp_path) == []
    assert (
        canonical_frontend_required_commands(["npm --prefix frontend run lint"], [], tmp_path)
        == []
    )


def test_frontend_scaffold_message_is_actionable():
    assert "frontend/package.json" in FRONTEND_SCAFFOLD_MESSAGE


def test_workspace_has_frontend_package(tmp_path: Path):
    assert not workspace_has_frontend_package(tmp_path)
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{}", encoding="utf-8")
    assert workspace_has_frontend_package(tmp_path)
