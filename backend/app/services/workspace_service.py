from __future__ import annotations

import shutil
from pathlib import Path

from app.core.exceptions import NotFoundError, ValidationError

_SKIP_NAMES = frozenset({
    "__pycache__",
    "node_modules",
    ".git",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".next",
    ".turbo",
})


def runs_root() -> Path:
    root = Path(__file__).resolve().parents[3] / "runtime" / "workspaces"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _build_ignore(source_root: Path):
    skipped_roots = {
        (source_root / "runtime" / "workspaces").resolve(),
        (source_root / "backend" / "workspaces").resolve(),
    }

    def _ignore(current_dir: str, names: list[str]) -> list[str]:
        ignored = [n for n in names if n in _SKIP_NAMES or n.endswith(".egg-info")]
        current_path = Path(current_dir).resolve()
        for name in names:
            candidate = (current_path / name).resolve()
            if any(candidate == skipped_root or skipped_root in candidate.parents for skipped_root in skipped_roots):
                ignored.append(name)
        return ignored

    return _ignore


def prepare_run_workspace(source_repo: Path, run_id: str) -> Path:
    source = source_repo.resolve()
    if not source.exists():
        raise NotFoundError(f"Source repo not found: {source}")

    workspace = runs_root() / run_id
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    if any(source.iterdir()):
        shutil.copytree(source, workspace, dirs_exist_ok=True, ignore=_build_ignore(source))
    return workspace


def promote_workspace_to_source(workspace: Path, source_repo: Path) -> None:
    workspace = workspace.resolve()
    source = source_repo.resolve()
    if not workspace.exists():
        raise ValidationError(f"Run workspace missing: {workspace}")
    if not source.exists():
        source.mkdir(parents=True, exist_ok=True)

    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(workspace)
        if any(part in _SKIP_NAMES for part in rel.parts):
            continue
        if rel.parts and rel.parts[0].startswith("."):
            continue
        dest = source / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)


def discard_run_workspace(run_id: str) -> None:
    workspace = runs_root() / run_id
    if workspace.exists():
        shutil.rmtree(workspace)


def reset_run_workspace(source_repo: Path, run_id: str) -> Path:
    discard_run_workspace(run_id)
    return prepare_run_workspace(source_repo, run_id)


# Aliases used across the codebase
clone_for_run = prepare_run_workspace
promote_to_source = promote_workspace_to_source
cleanup_run_workspace = discard_run_workspace
