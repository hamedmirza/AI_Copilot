from pathlib import Path

from app.services.file_service import FileService
from app.services.tree_cache import get_cached_tree, invalidate_tree_cache, store_tree_cache


def test_tree_cache_hit_and_invalidate(tmp_path: Path):
    workspace = tmp_path / "proj"
    workspace.mkdir()
    (workspace / "a.py").write_text("x = 1\n")
    fs = FileService(workspace, [])
    first = fs.list_tree()
    assert get_cached_tree(workspace) == first
    second = fs.list_tree()
    assert second == first
    (workspace / "b.py").write_text("y = 2\n")
    invalidate_tree_cache(workspace)
    third = fs.list_tree()
    assert any(item["path"] == "b.py" for item in third)


def test_store_and_get_cached_tree(tmp_path: Path):
    workspace = tmp_path / "cache"
    workspace.mkdir()
    items = [{"path": "x.py", "type": "file", "size": 1}]
    store_tree_cache(workspace, items)
    assert get_cached_tree(workspace) == items
