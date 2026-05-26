from pathlib import Path

from app.services.baseline_service import BaselineService


def test_baseline_capture_on_python_repo(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    (tmp_path / "sample.py").write_text("x = 1\n", encoding="utf-8")
    result = BaselineService().capture(tmp_path, "python")
    assert "summary" in result
    assert "results" in result


def test_baseline_context_block():
    block = BaselineService().context_block({"summary": "2/2 passed", "results": [{"command": "x", "passed": True}]})
    assert "Baseline" in block
    assert "2/2" in block
