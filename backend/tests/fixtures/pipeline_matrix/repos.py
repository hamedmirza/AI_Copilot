"""Temporary repo factories for pipeline matrix scenarios."""

from __future__ import annotations

from pathlib import Path


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def build_greenfield(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# Greenfield\n", encoding="utf-8")
    return root


def build_partial(root: Path) -> Path:
    backend = root / "backend"
    service_dir = backend / "app" / "services"
    service_dir.mkdir(parents=True)
    (service_dir / "foo.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    (backend / "tests").mkdir(parents=True, exist_ok=True)
    (backend / "tests" / "test_foo.py").write_text("def test_foo():\n    assert True\n", encoding="utf-8")
    venv_bin = backend / ".venv" / "bin"
    _write_executable(venv_bin / "pytest", "#!/bin/sh\nexit 0\n")
    (backend / "pyproject.toml").write_text('[project]\nname="partial"\n', encoding="utf-8")
    (backend / "AGENTS.md").write_text("# Partial\n", encoding="utf-8")
    return root


def build_full(root: Path) -> Path:
    build_partial(root)
    backend = root / "backend"
    frontend = root / "frontend"
    (frontend / "src").mkdir(parents=True, exist_ok=True)
    (frontend / "src" / "App.tsx").write_text("export default function App(){return null}\n", encoding="utf-8")
    (frontend / "package.json").write_text(
        '{"name":"frontend","scripts":{"build":"node -e \\"process.exit(0)\\""}}\n',
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text('[project]\nname="full"\n', encoding="utf-8")
    return root


def build_debug_broken(root: Path) -> Path:
    build_full(root)
    test_path = root / "backend" / "tests" / "test_broken.py"
    test_path.write_text("def test_broken():\n    assert False\n", encoding="utf-8")
    return root
