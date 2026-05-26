from __future__ import annotations

import re
import shutil
from pathlib import Path

from app.core.exceptions import NotFoundError, ValidationError
from app.services.workspace_walk import iter_workspace_files

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
    "app.db",
    "app.db-shm",
    "app.db-wal",
    "test_app.db",
    "test_app.db-shm",
    "test_app.db-wal",
    "logs",
    "runtime",
})
_PROMOTABLE_HIDDEN_ROOTS = {".ai-copilot"}
_LINKABLE_DEP_DIRS = (
    Path("frontend/node_modules"),
    Path("node_modules"),
)


def runs_root() -> Path:
    root = Path(__file__).resolve().parents[3] / "runtime" / "workspaces"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sanitize_workspace_slug(name: str) -> str:
    cleaned = name.strip().replace("/", "-").replace("\\", "-")
    cleaned = re.sub(r"[^\w.\- ]", "-", cleaned, flags=re.ASCII)
    cleaned = re.sub(r"\s+", "-", cleaned).strip(".-")
    return (cleaned[:120] if cleaned else "workspace")


def workspace_slug_for_project(project_name: str, source_repo: Path | str) -> str:
    """Stable folder name under runs_root — matches source repo directory name when possible."""
    source = Path(source_repo).expanduser().resolve()
    base = source.name
    if not base or base in {".", ".."}:
        base = project_name.strip() or "workspace"
    return _sanitize_workspace_slug(base)


def workspace_path_for_project(project_name: str, source_repo: Path | str) -> Path:
    return (runs_root() / workspace_slug_for_project(project_name, source_repo)).resolve()


def active_workspace_dir_names(db_run_rows: list) -> set[str]:
    """Directory names under runs_root that belong to active runs (for orphan purge)."""
    names: set[str] = set()
    for run in db_run_rows:
        if getattr(run, "workspace_path", None):
            path = Path(run.workspace_path).resolve()
            if runs_root().resolve() in path.parents or path.parent == runs_root().resolve():
                names.add(path.name)
        project = getattr(run, "project", None)
        if project is not None:
            names.add(
                workspace_slug_for_project(
                    getattr(project, "name", "") or "",
                    getattr(project, "source_repo_spec", "") or "",
                )
            )
    return names


def _resolve_source_repo(source_repo: Path) -> Path:
    source = source_repo.resolve()
    workspaces_root = runs_root().resolve()
    if workspaces_root in source.parents:
        raise ValidationError(
            f"Project source cannot be inside run workspaces: {source}. "
            "Set source_repo_spec to the repository root, not a runtime workspace copy."
        )
    return source


def _build_ignore(source_root: Path, workspace: Path):
    skipped_roots = {
        (source_root / "runtime" / "workspaces").resolve(),
        (source_root / "backend" / "workspaces").resolve(),
        workspace.resolve(),
    }

    def _ignore(current_dir: str, names: list[str]) -> list[str]:
        ignored = [n for n in names if n in _SKIP_NAMES or n.endswith(".egg-info")]
        current_path = Path(current_dir).resolve()
        for name in names:
            candidate = (current_path / name).resolve()
            if any(
                candidate == skipped_root
                or skipped_root in candidate.parents
                or candidate == workspace.resolve()
                or workspace.resolve() in candidate.parents
                for skipped_root in skipped_roots
            ):
                ignored.append(name)
        return ignored

    return _ignore


def _link_dependency_dirs(source_root: Path, workspace: Path) -> None:
    for rel in _LINKABLE_DEP_DIRS:
        source_dep = source_root / rel
        if not source_dep.exists() or not source_dep.is_dir():
            continue
        workspace_dep = workspace / rel
        if workspace_dep.exists():
            continue
        workspace_dep.parent.mkdir(parents=True, exist_ok=True)
        workspace_dep.symlink_to(source_dep)


def prepare_run_workspace(source_repo: Path, workspace_name: str) -> Path:
    source = _resolve_source_repo(source_repo)
    if not source.exists():
        raise NotFoundError(f"Source repo not found: {source}")

    workspace = (runs_root() / _sanitize_workspace_slug(workspace_name)).resolve()
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    if any(source.iterdir()):
        shutil.copytree(source, workspace, dirs_exist_ok=True, ignore=_build_ignore(source, workspace))
        _link_dependency_dirs(source, workspace)
    return workspace


def workspace_has_promotable_files(workspace: Path) -> bool:
    if not workspace.exists() or not workspace.is_dir():
        return False
    for path in iter_workspace_files(workspace):
        rel = path.relative_to(workspace)
        if is_promotable_path(rel):
            return True
    return False


def validate_run_workspace(
    workspace: Path,
    *,
    source_repo: Path,
    repo_mode: str | None,
    task_kind: str | None,
) -> None:
    if not workspace.exists() or not workspace.is_dir():
        raise ValidationError(f"Run workspace missing: {workspace}")
    has_promotable = workspace_has_promotable_files(workspace)
    if repo_mode == "existing" and not has_promotable:
        raise ValidationError("Workspace reset produced no usable files from project source")
    if task_kind == "setup" and repo_mode != "greenfield" and not has_promotable:
        raise ValidationError("Workspace reset produced no usable files from project source")
    if task_kind == "setup" and not has_promotable and (source_repo / ".git").exists():
        raise ValidationError("Workspace reset produced no usable files from project source")


def is_promotable_path(rel: Path) -> bool:
    parts = rel.parts
    if not parts:
        return False
    for part in parts:
        if part in _SKIP_NAMES:
            return False
    root = parts[0]
    if root.startswith(".") and root not in _PROMOTABLE_HIDDEN_ROOTS:
        return False
    return True


def promote_workspace_to_source(workspace: Path, source_repo: Path) -> None:
    workspace = workspace.resolve()
    source = _resolve_source_repo(source_repo)
    if not workspace.exists():
        raise ValidationError(f"Run workspace missing: {workspace}")
    if not source.exists():
        source.mkdir(parents=True, exist_ok=True)

    for path in iter_workspace_files(workspace):
        rel = path.relative_to(workspace)
        if not is_promotable_path(rel):
            continue
        dest = source / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)


def discard_run_workspace(workspace_name: str) -> None:
    workspace = runs_root() / _sanitize_workspace_slug(workspace_name)
    if workspace.exists():
        shutil.rmtree(workspace)


def discard_run_workspace_path(workspace: Path) -> None:
    path = workspace.resolve()
    root = runs_root().resolve()
    if path.exists() and (path == root or root in path.parents):
        shutil.rmtree(path)


def reset_run_workspace(source_repo: Path, workspace_name: str) -> Path:
    discard_run_workspace(workspace_name)
    return prepare_run_workspace(source_repo, workspace_name)


def cleanup_run_workspace_for_run(
    run,
    *,
    project_name: str,
    source_repo_spec: str,
) -> None:
    if getattr(run, "workspace_path", None):
        path = Path(run.workspace_path)
        if path.exists():
            discard_run_workspace_path(path)
            return
    discard_run_workspace(workspace_slug_for_project(project_name, source_repo_spec))


def list_workspace_changed_files(workspace: Path, source_root: Path) -> list[str]:
    """Paths that differ from source or are new — used for tester/reviewer/deploy gates."""
    workspace = workspace.resolve()
    source_root = _resolve_source_repo(source_root)
    changed: list[str] = []
    if not workspace.exists():
        return changed
    for path in iter_workspace_files(workspace):
        rel = path.relative_to(workspace)
        if not is_promotable_path(rel):
            continue
        src_file = source_root / rel
        if src_file.is_file():
            try:
                if path.read_bytes() != src_file.read_bytes():
                    changed.append(str(rel).replace("\\", "/"))
            except OSError:
                continue
        else:
            changed.append(str(rel).replace("\\", "/"))
    return sorted(changed)


# Aliases used across the codebase
def clone_for_run(source_repo: Path, project_name: str, source_repo_spec: Path | str | None = None) -> Path:
    spec = source_repo_spec if source_repo_spec is not None else source_repo
    slug = workspace_slug_for_project(project_name, spec)
    return prepare_run_workspace(source_repo, slug)


promote_to_source = promote_workspace_to_source


def cleanup_run_workspace(run, project) -> None:
    cleanup_run_workspace_for_run(
        run,
        project_name=project.name,
        source_repo_spec=project.source_repo_spec,
    )
