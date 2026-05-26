"""Verify planned dependencies exist in manifest files."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_IMPORT_RE = re.compile(
    r"(?:^|\n)\s*(?:import|from)\s+([a-zA-Z0-9_\.]+)|require\(['\"]([^'\"]+)['\"]\)",
    re.MULTILINE,
)
_PACKAGE_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,63}$")
_PYPI_NAME_MAP = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "httpx": "httpx",
    "pytest": "pytest",
}


class DependencyVerifierService:
    def __init__(self, workspace: Path, source: Path) -> None:
        self.workspace = workspace.resolve()
        self.source = source.resolve()

    def verify(self, architect: dict[str, Any]) -> dict[str, Any]:
        overview = str(architect.get("overview") or "")
        deps_declared = list(architect.get("dependencies") or [])
        text = overview + "\n" + json.dumps(architect.get("file_changes") or [])
        inferred = self._infer_imports(text)
        inferred.extend(name for name in deps_declared if looks_like_package_name(name))
        py_deps = self._read_pyproject_deps(self.workspace) or self._read_pyproject_deps(self.source)
        npm_deps = self._read_package_deps(self.workspace) or self._read_package_deps(self.source)
        missing: list[str] = []
        for name in inferred:
            if not looks_like_package_name(name):
                continue
            key = name.split(".")[0].lower()
            if key in py_deps or key in npm_deps:
                continue
            mapped = _PYPI_NAME_MAP.get(key, key)
            if mapped in py_deps or mapped in npm_deps:
                continue
            if self._is_stdlib(key):
                continue
            missing.append(name)
        return {
            "ok": len(missing) == 0,
            "missing": missing,
            "message": (
                "All planned imports resolve to declared dependencies."
                if not missing
                else f"Missing dependencies: {', '.join(missing)}. Add to pyproject.toml or package.json before coding."
            ),
        }

    def _infer_imports(self, text: str) -> list[str]:
        names: list[str] = []
        for m in _IMPORT_RE.finditer(text):
            name = m.group(1) or m.group(2)
            if name:
                names.append(name.split(".")[0])
        return list(dict.fromkeys(names))

    def _read_pyproject_deps(self, root: Path) -> set[str]:
        for rel in ("pyproject.toml", "backend/pyproject.toml"):
            path = root / rel
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            found: set[str] = set()
            for match in re.finditer(r'["\']([a-zA-Z0-9_.-]+)["\']', text):
                token = match.group(1).split("[")[0].strip()
                if token and token[0].isalpha():
                    found.add(token.lower())
            return found
        return set()

    def _read_package_deps(self, root: Path) -> set[str]:
        for rel in ("package.json", "frontend/package.json"):
            path = root / rel
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            deps = set()
            for section in ("dependencies", "devDependencies"):
                for key in (data.get(section) or {}):
                    deps.add(str(key).lower())
            return deps
        return set()

    @staticmethod
    def _is_stdlib(name: str) -> bool:
        import sys

        return name in sys.stdlib_module_names


def looks_like_package_name(name: str) -> bool:
    text = str(name or "").strip()
    if not text or " " in text:
        return False
    if "/" in text or "\\" in text:
        return False
    if any(token in text for token in (".py", ".ts", ".tsx", ".js", ".jsx", ".md")):
        return False
    token = text.split("[", 1)[0].strip()
    if len(token) > 64:
        return False
    return bool(_PACKAGE_NAME_RE.match(token))
