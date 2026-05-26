"""Pre-flight repo structure checks against source."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PreflightResult:
    ok: bool
    message: str
    warnings: list[str]


class RepoHealthService:
    def run_preflight(
        self,
        source: Path,
        validation_profile: str,
        *,
        task_kind: str | None = None,
    ) -> PreflightResult:
        if task_kind == "setup":
            return PreflightResult(ok=True, message="Setup run skips strict preflight", warnings=[])

        warnings: list[str] = []
        profile = (validation_profile or "python").lower()
        root = source.resolve()

        if profile in {"python", "fullstack", "custom"}:
            has_python = (root / "pyproject.toml").is_file() or (root / "setup.py").is_file()
            has_backend = (root / "backend" / "pyproject.toml").is_file()
            if not has_python and not has_backend:
                return PreflightResult(
                    ok=False,
                    message="Pre-flight failed: missing pyproject.toml or setup.py for python profile.",
                    warnings=warnings,
                )
            tests_dir = root / "tests"
            backend_tests = root / "backend" / "tests"
            if not tests_dir.is_dir() and not backend_tests.is_dir():
                warnings.append("No tests/ directory found; tester may have limited commands.")

        if profile in {"react", "fullstack", "node"}:
            pkg = root / "frontend" / "package.json"
            if not pkg.is_file() and not (root / "package.json").is_file():
                return PreflightResult(
                    ok=False,
                    message="Pre-flight failed: missing frontend/package.json or package.json.",
                    warnings=warnings,
                )
            src = root / "frontend" / "src"
            if profile != "node" and not src.is_dir() and not (root / "src").is_dir():
                warnings.append("No frontend/src directory found.")

        agents = root / "AGENTS.md"
        conventions = root / ".ai-copilot" / "conventions.md"
        if not agents.is_file() and not conventions.is_file():
            warnings.append("Missing AGENTS.md and .ai-copilot/conventions.md — agents lack project rules.")

        return PreflightResult(ok=True, message="Pre-flight passed", warnings=warnings)
