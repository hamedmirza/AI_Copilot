"""Lenient scope checks: blueprint paths, tests, and import neighbors are allowed."""

from __future__ import annotations

from pathlib import Path

_TEST_PREFIXES = ("backend/tests/", "tests/")
_TEST_SUFFIXES = (".test.ts", ".test.tsx", ".test.js", ".test.jsx", ".test.mjs")
_PACKAGE_ROOT_MARKERS = (
    "backend/app/",
    "frontend/src/",
    "frontend/public/",
    "scripts/",
    "docs/",
)


def _normalize(path: str) -> str:
    return path.replace("\\", "/").strip().lstrip("./")


def _is_test_path(path: str) -> bool:
    normalized = _normalize(path)
    if any(normalized.startswith(prefix) for prefix in _TEST_PREFIXES):
        return True
    if any(normalized.endswith(suffix) for suffix in _TEST_SUFFIXES):
        return True
    name = Path(normalized).name.lower()
    return "test" in name


def _blueprint_set(blueprint_paths: list[str]) -> set[str]:
    return {_normalize(path) for path in blueprint_paths if path}


def _same_directory_neighbor(blueprint_paths: list[str], path: str) -> bool:
    normalized = _normalize(path)
    target_parent = str(Path(normalized).parent)
    if not target_parent or target_parent == ".":
        return False
    for blueprint in blueprint_paths:
        if str(Path(_normalize(blueprint)).parent) == target_parent:
            return True
    return False


def _package_root(path: str) -> str | None:
    normalized = _normalize(path)
    for marker in _PACKAGE_ROOT_MARKERS:
        if normalized.startswith(marker):
            return marker
    return None


def scope_issues(
    blueprint_paths: list[str],
    coder_paths: list[str],
    task_kind: str | None = None,
) -> list[dict]:
    """Return reviewer-facing scope warnings (lenient) and hard drift issues."""
    if not coder_paths:
        return []

    allowed = _blueprint_set(blueprint_paths)
    issues: list[dict] = []
    for raw_path in coder_paths:
        path = _normalize(raw_path)
        if not path:
            continue
        if path in allowed:
            continue
        if _is_test_path(path):
            continue
        if _same_directory_neighbor(blueprint_paths, path):
            issues.append(
                {
                    "severity": "suggestion",
                    "file_path": path,
                    "message": (
                        f"Scope note: {path} is not in the architect blueprint but is a same-directory neighbor — "
                        "confirm it is required or fold the change into a blueprint path."
                    ),
                    "source": "scope_guard",
                }
            )
            continue

        blueprint_roots = {_package_root(bp) for bp in blueprint_paths if _package_root(bp)}
        path_root = _package_root(path)
        if blueprint_roots and path_root and path_root not in blueprint_roots:
            issues.append(
                {
                    "severity": "important",
                    "file_path": path,
                    "message": (
                        f"Scope drift: {path} is outside blueprint package roots "
                        f"({', '.join(sorted(blueprint_roots))}). "
                        "Remove the change or update the architect blueprint first."
                    ),
                    "source": "scope_guard",
                }
            )
            continue

        if task_kind == "analysis":
            issues.append(
                {
                    "severity": "important",
                    "file_path": path,
                    "message": (
                        f"Analysis task scope: {path} is not in the blueprint — "
                        "prefer report artifacts over code changes unless explicitly requested."
                    ),
                    "source": "scope_guard",
                }
            )
        else:
            issues.append(
                {
                    "severity": "suggestion",
                    "file_path": path,
                    "message": (
                        f"Scope warning: {path} is not listed in architect file_changes. "
                        "Confirm it is required or add it to the blueprint."
                    ),
                    "source": "scope_guard",
                }
            )
    return issues
