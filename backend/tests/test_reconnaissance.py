from pathlib import Path

from app.core.enums import RepoMode
from app.services.reconnaissance_service import ReconnaissanceService


def test_detect_greenfield_empty_dir(tmp_path: Path):
    assert ReconnaissanceService().detect_repo_mode(tmp_path) == RepoMode.GREENFIELD.value


def test_detect_existing_with_sentinels(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Agents", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Readme", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ARCHITECTURE.md").write_text("# Arch", encoding="utf-8")
    assert ReconnaissanceService().detect_repo_mode(tmp_path) == RepoMode.EXISTING.value


def test_build_snapshot_includes_keywords(tmp_path: Path):
    (tmp_path / "main.py").write_text("def search_web():\n    pass\n", encoding="utf-8")
    snap = ReconnaissanceService().build_snapshot(
        tmp_path,
        task_description="Add web search to the API",
        validation_profile="python",
        use_scout=True,
    )
    assert snap.repo_mode in {RepoMode.GREENFIELD.value, RepoMode.PARTIAL.value}
    assert "search" in (snap.payload.get("expanded_keywords") or [])
