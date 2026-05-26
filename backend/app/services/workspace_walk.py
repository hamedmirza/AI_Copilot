"""Safe workspace directory iteration — skips heavy dirs and symlinked trees."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

# Keep aligned with workspace_service._SKIP_NAMES and file_service._TREE_SKIP_DIRS.
WALK_SKIP_DIR_NAMES = frozenset({
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

# Dot-directories we still descend into (matches workspace promote rules).
_WALK_ALLOWED_DOT_DIRS = frozenset({".ai-copilot", ".env.example"})


def should_skip_walk_dir(name: str) -> bool:
    if name in WALK_SKIP_DIR_NAMES:
        return True
    if name.endswith(".egg-info"):
        return True
    if name.startswith("."):
        return name not in _WALK_ALLOWED_DOT_DIRS
    return False


def iter_workspace_files(root: Path, *, follow_symlinks: bool = False) -> Iterator[Path]:
    """Yield files under root without descending into skipped or symlinked directories."""
    resolved = root.resolve()
    if not resolved.is_dir():
        return

    stack: list[Path] = [resolved]
    while stack:
        directory = stack.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            if follow_symlinks:
                                path = Path(entry.path)
                                if path.is_dir():
                                    if not should_skip_walk_dir(entry.name):
                                        stack.append(path)
                                elif path.is_file():
                                    yield path
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if should_skip_walk_dir(entry.name):
                                continue
                            stack.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            yield Path(entry.path)
                    except OSError:
                        continue
        except OSError:
            continue
