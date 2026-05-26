from pathlib import Path

from app.services.integration_guard import integration_guard_issues


def test_integration_guard_skips_when_no_changed_files(tmp_path: Path):
    frontend = tmp_path / "frontend" / "src"
    frontend.mkdir(parents=True)
    (frontend / "App.tsx").write_text("export default function App() { return null; }\n", encoding="utf-8")
    issues = integration_guard_issues(tmp_path, changed_files=[])
    assert issues == []
