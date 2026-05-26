from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.services.git_service import GitService


def test_commit_stages_untracked_and_clears_status(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.txt").write_text("hello")
    gs = GitService(repo)

    sha = gs.commit("initial", "Test", "test@example.com")
    assert sha
    assert gs.status() == {
        "staged": [],
        "unstaged": [],
        "untracked": [],
        "ahead": 0,
        "behind": 0,
    }


def test_commit_rejects_when_clean(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.txt").write_text("hello")
    gs = GitService(repo)
    gs.commit("initial", "Test", "test@example.com")

    with pytest.raises(ValidationError, match="No changes to commit"):
        gs.commit("empty", "Test", "test@example.com")


def test_commit_picks_up_modified_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "f.txt"
    path.write_text("v1")
    gs = GitService(repo)
    gs.commit("v1", "Test", "test@example.com")

    path.write_text("v2")
    gs2 = GitService(repo)
    assert any(f["path"] == "f.txt" for f in gs2.status()["unstaged"] + gs2.status()["untracked"])

    gs2.commit("v2", "Test", "test@example.com")
    st = gs2.status()
    assert st["staged"] == []
    assert st["unstaged"] == []
    assert st["untracked"] == []
