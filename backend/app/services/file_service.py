import hashlib
import shutil
from pathlib import Path

from app.core.exceptions import NotFoundError, PathTraversalError, PatchGuardError
from app.services.change_guard import coder_guard_issues, summarize_structure
from app.services.tree_cache import get_cached_tree, invalidate_tree_cache, store_tree_cache
from app.tools.patch_guard import apply_line_changes, check_patch_allowed

# Directories omitted from explorer/search tree (still on disk).
_TREE_SKIP_DIRS = frozenset({
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


def _resolve_path(workspace: Path, rel_path: str) -> Path:
    if ".." in rel_path.replace("\\", "/").split("/"):
        raise PathTraversalError("Path traversal not allowed")
    target = (workspace / rel_path).resolve()
    ws = workspace.resolve()
    if not str(target).startswith(str(ws)):
        raise PathTraversalError("Path traversal not allowed")
    return target


def file_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


class FileService:
    def __init__(self, workspace: Path, protected_files: list[str] | None = None) -> None:
        self.workspace = workspace
        self.protected_files = protected_files or []
        self.workspace.mkdir(parents=True, exist_ok=True)

    def read_file(self, rel_path: str) -> dict:
        path = _resolve_path(self.workspace, rel_path)
        if not path.is_file():
            raise NotFoundError(f"File not found: {rel_path}")
        content = path.read_text(encoding="utf-8")
        return {
            "path": rel_path,
            "content": content,
            "line_count": len(content.splitlines()),
            "hash": file_hash(content),
        }

    def write_file(self, rel_path: str, content: str, check_protected: bool = True) -> dict:
        if check_protected:
            check_patch_allowed(rel_path, self.protected_files)
        path = _resolve_path(self.workspace, rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        invalidate_tree_cache(self.workspace)
        return self.read_file(rel_path)

    def create(self, rel_path: str, content: str = "", is_directory: bool = False) -> dict:
        path = _resolve_path(self.workspace, rel_path)
        if path.exists():
            raise ValueError(f"Path already exists: {rel_path}")
        if is_directory:
            path.mkdir(parents=True, exist_ok=True)
            return {"path": rel_path, "type": "directory"}
        return self.write_file(rel_path, content, check_protected=False)

    def delete(self, rel_path: str) -> None:
        check_patch_allowed(rel_path, self.protected_files)
        path = _resolve_path(self.workspace, rel_path)
        if not path.exists():
            raise NotFoundError(f"Path not found: {rel_path}")
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        invalidate_tree_cache(self.workspace)

    def rename(self, rel_path: str, new_path: str) -> dict:
        check_patch_allowed(rel_path, self.protected_files)
        check_patch_allowed(new_path, self.protected_files)
        src = _resolve_path(self.workspace, rel_path)
        dst = _resolve_path(self.workspace, new_path)
        if not src.exists():
            raise NotFoundError(f"Path not found: {rel_path}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        invalidate_tree_cache(self.workspace)
        if dst.is_file():
            return self.read_file(new_path)
        return {"path": new_path, "type": "directory"}

    def preview_coder_changes(self, file_changes: list[dict]) -> list[dict]:
        previews: list[dict] = []
        for fc in file_changes:
            rel = fc["path"]
            check_patch_allowed(rel, self.protected_files)
            path = _resolve_path(self.workspace, rel)
            existed = path.exists()
            existing = path.read_text(encoding="utf-8") if existed and path.is_file() else ""
            used_full_content = fc.get("full_content") is not None
            if used_full_content:
                updated = str(fc["full_content"])
            elif fc.get("line_changes"):
                updated = apply_line_changes(existing, fc["line_changes"])
            else:
                updated = existing
            summary = summarize_structure(rel, existing, updated, existed, used_full_content)
            issues = coder_guard_issues(summary)
            if issues:
                raise PatchGuardError(rel, "; ".join(issues))
            previews.append(
                {
                    "path": rel,
                    "existed": existed,
                    "used_full_content": used_full_content,
                    "before_content": existing,
                    "after_content": updated,
                    "summary": summary,
                }
            )
        return previews

    def apply_coder_changes(self, file_changes: list[dict]) -> list[dict]:
        previews = self.preview_coder_changes(file_changes)
        changed: list[dict] = []
        for fc, preview in zip(file_changes, previews, strict=False):
            rel = fc["path"]
            if fc.get("full_content") is not None:
                self.write_file(rel, fc["full_content"])
            elif fc.get("line_changes"):
                self.write_file(rel, preview["after_content"])
            changed.append(
                {
                    "path": rel,
                    "summary": preview["summary"],
                    "used_full_content": preview["used_full_content"],
                }
            )
        return changed

    def tree(self, rel_path: str = ".") -> dict:
        root = _resolve_path(self.workspace, rel_path)

        def walk(directory: Path, prefix: str) -> list[dict]:
            nodes: list[dict] = []
            try:
                entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except PermissionError:
                return nodes
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.name.startswith(".") and entry.name not in (".env.example",):
                    continue
                if entry.is_dir() and entry.name in _TREE_SKIP_DIRS:
                    continue
                if entry.is_dir() and entry.name.endswith(".egg-info"):
                    continue
                rel = f"{prefix}/{entry.name}" if prefix != "." else entry.name
                if entry.is_dir():
                    nodes.append(
                        {
                            "name": entry.name,
                            "path": rel,
                            "type": "directory",
                            "children": walk(entry, rel),
                        }
                    )
                else:
                    nodes.append(
                        {
                            "name": entry.name,
                            "path": rel,
                            "type": "file",
                            "size": entry.stat().st_size,
                        }
                    )
            return nodes

        return {"path": rel_path, "children": walk(root, rel_path if rel_path != "." else ".")}

    def list_tree(self) -> list[dict]:
        cached = get_cached_tree(self.workspace)
        if cached is not None:
            return cached

        def flatten(nodes: list[dict]) -> list[dict]:
            items: list[dict] = []
            for node in nodes:
                item = {k: v for k, v in node.items() if k != "children"}
                items.append(item)
                children = node.get("children")
                if children:
                    items.extend(flatten(children))
            return items

        items = flatten(self.tree().get("children", []))
        store_tree_cache(self.workspace, items)
        return items
