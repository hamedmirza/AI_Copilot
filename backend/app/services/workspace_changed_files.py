"""Workspace-scoped changed file detection vs project source."""

from __future__ import annotations

from pathlib import Path

from app.services.workspace_service import is_promotable_path


def workspace_changed_files(workspace: Path, source_root: Path) -> list[str]:
    if not workspace.is_dir():
        return []
    source = source_root.resolve()
    root = workspace.resolve()
    paths: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if not is_promotable_path(rel):
            continue
        src_file = source / rel
        try:
            if src_file.is_file():
                if path.read_bytes() != src_file.read_bytes():
                    paths.append(str(rel).replace("\\", "/"))
            else:
                paths.append(str(rel).replace("\\", "/"))
        except OSError:
            continue
    return sorted(set(paths))
