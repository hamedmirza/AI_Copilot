from pathlib import Path

from app.services.dependency_verifier_service import DependencyVerifierService


def test_dependency_verifier_ok_when_declared(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname="x"\ndependencies = ["fastapi"]\n',
        encoding="utf-8",
    )
    architect = {
        "overview": "import fastapi",
        "modules": ["api"],
        "file_changes": [{"path": "main.py", "action": "modify", "rationale": "use fastapi"}],
        "dependencies": ["fastapi"],
    }
    result = DependencyVerifierService(tmp_path, tmp_path).verify(architect)
    assert result["ok"] is True


def test_dependency_verifier_flags_missing(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\n', encoding="utf-8")
    architect = {
        "overview": "import httpx",
        "modules": ["api"],
        "file_changes": [{"path": "main.py", "action": "modify", "rationale": "use httpx"}],
        "dependencies": ["httpx"],
    }
    result = DependencyVerifierService(tmp_path, tmp_path).verify(architect)
    assert result["ok"] is False
    assert "httpx" in (result.get("missing") or [])


def test_dependency_verifier_ignores_prose_dependencies(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\ndependencies = ["httpx"]\n', encoding="utf-8")
    architect = {
        "overview": "Extend web search service",
        "modules": ["services"],
        "file_changes": [{"path": "backend/app/services/web_search_service.py", "action": "modify", "rationale": "providers"}],
        "dependencies": [
            "web_search_service.py should support Google, X, GitHub, and DuckDuckGo providers",
            "Configuration parameters for specifying search provider type",
        ],
    }
    result = DependencyVerifierService(tmp_path, tmp_path).verify(architect)
    assert result["ok"] is True
    assert result.get("missing") == []
