from __future__ import annotations

import time
from pathlib import Path

_CACHE_TTL_SECONDS = 3.0
_cache: dict[str, tuple[float, float, list[dict]]] = {}


def get_cached_tree(workspace: Path) -> list[dict] | None:
    key = str(workspace.resolve())
    entry = _cache.get(key)
    if not entry:
        return None
    cached_at, dir_mtime, items = entry
    if time.monotonic() - cached_at > _CACHE_TTL_SECONDS:
        _cache.pop(key, None)
        return None
    try:
        current_mtime = workspace.stat().st_mtime
    except OSError:
        return None
    if current_mtime != dir_mtime:
        _cache.pop(key, None)
        return None
    return items


def store_tree_cache(workspace: Path, items: list[dict]) -> None:
    key = str(workspace.resolve())
    try:
        dir_mtime = workspace.stat().st_mtime
    except OSError:
        return
    _cache[key] = (time.monotonic(), dir_mtime, items)


def invalidate_tree_cache(workspace: Path) -> None:
    _cache.pop(str(workspace.resolve()), None)
