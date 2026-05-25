from pathlib import Path

from app.services.workspace_changed_files import workspace_changed_files
from app.services.workspace_walk import iter_workspace_files


def test_iter_workspace_files_skips_node_modules(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "src.py").write_text("ok")
    nm = root / "node_modules"
    nm.mkdir()
    (nm / "pkg" / "index.js").parent.mkdir(parents=True)
    (nm / "pkg" / "index.js").write_text("x")

    rels = [p.relative_to(root).as_posix() for p in iter_workspace_files(root)]
    assert rels == ["src.py"]


def test_iter_workspace_files_skips_symlinked_node_modules(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "src.py").write_text("ok")
    huge = tmp_path / "huge_node_modules"
    huge.mkdir()
    (huge / "lodash.js").write_text("x" * 1000)
    (root / "node_modules").symlink_to(huge, target_is_directory=True)

    rels = [p.relative_to(root).as_posix() for p in iter_workspace_files(root)]
    assert rels == ["src.py"]


def test_iter_workspace_files_allows_ai_copilot(tmp_path: Path):
    root = tmp_path / "ws"
    root.mkdir()
    guide = root / ".ai-copilot" / "reports"
    guide.mkdir(parents=True)
    (guide / "note.md").write_text("report")

    rels = [p.relative_to(root).as_posix() for p in iter_workspace_files(root)]
    assert rels == [".ai-copilot/reports/note.md"]


def test_workspace_changed_files_ignores_symlinked_deps(tmp_path: Path):
    source = tmp_path / "source"
    workspace = tmp_path / "workspace"
    source.mkdir()
    workspace.mkdir()
    (source / "app.py").write_text("original")
    (workspace / "app.py").write_text("changed")
    huge = tmp_path / "deps"
    huge.mkdir()
    (huge / "dep.js").write_text("lib")
    (workspace / "node_modules").symlink_to(huge, target_is_directory=True)

    changed = workspace_changed_files(workspace, source)
    assert changed == ["app.py"]
