"""Deterministic integration guard for frontend pages and routes."""

from __future__ import annotations

import re
from pathlib import Path

_ENTRY_SURFACES = (
    "frontend/src/App.tsx",
    "frontend/src/main.tsx",
    "frontend/src/workbench/builtins.tsx",
    "frontend/src/workbench/registry.ts",
)

_PAGE_DIR = Path("frontend/src/pages")
_ROUTES_DIR = Path("frontend/src/routes")
_EXPORT_DEFAULT = re.compile(
    r"export\s+default\s+(?:function\s+)?([A-Za-z_][\w$]*)",
    re.MULTILINE,
)
_NAMED_EXPORT = re.compile(
    r"export\s+(?:function|const)\s+([A-Za-z_][\w$]*)",
    re.MULTILINE,
)
_REGISTER_CONTRIBUTION = re.compile(
    r"registerContribution\s*\(\s*\{([^}]+)\}",
    re.DOTALL,
)
_CENTER_ZONE = re.compile(r"""zone:\s*['"]center['"]""")
_CENTER_ID = re.compile(r"""id:\s*['"]([^'"]+)['"]""")
_CENTER_COMPONENT = re.compile(r"Component:\s*([A-Za-z_][\w$]*)")
_BROWSER_ONLY_MOUNT = "activeCenterView === 'browser' && BrowserComponent"


def _read_text(workspace: Path, rel: str) -> str:
    path = workspace / rel
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _entry_surface_text(workspace: Path) -> str:
    parts: list[str] = []
    for rel in _ENTRY_SURFACES:
        parts.append(_read_text(workspace, rel))
    return "\n".join(parts)


def _page_symbols(workspace: Path, rel_path: str) -> list[str]:
    text = _read_text(workspace, rel_path)
    symbols: list[str] = []
    stem = Path(rel_path).stem
    if stem:
        symbols.append(stem)
    for match in _EXPORT_DEFAULT.finditer(text):
        symbols.append(match.group(1))
    for match in _NAMED_EXPORT.finditer(text):
        symbols.append(match.group(1))
    return list(dict.fromkeys(symbols))


def _is_referenced(symbol: str, entry_text: str, rel_path: str) -> bool:
    if not symbol and not rel_path:
        return False
    if rel_path and rel_path.replace("\\", "/") in entry_text:
        return True
    if symbol and symbol in entry_text:
        return True
    if symbol:
        patterns = (
            f"from '@/pages/{symbol}'",
            f'from "@/pages/{symbol}"',
            f"from '../pages/{symbol}'",
            f'from "../pages/{symbol}"',
            f"from './pages/{symbol}'",
            f"<{symbol}",
            f"component: {symbol}",
            f"id: '{symbol.lower()}'",
            f'id: "{symbol.lower()}"',
        )
        if any(p in entry_text for p in patterns):
            return True
    return False


def _collect_new_or_changed_pages(workspace: Path, changed_files: list[str] | None) -> list[str]:
    pages: list[str] = []
    pages_root = workspace / _PAGE_DIR
    if not pages_root.is_dir():
        return pages
    changed_set = {p.replace("\\", "/") for p in (changed_files or [])}
    for path in sorted(pages_root.rglob("*.tsx")):
        rel = str(path.relative_to(workspace)).replace("\\", "/")
        if changed_set and rel not in changed_set:
            continue
        if path.is_file():
            pages.append(rel)
    if not changed_set:
        for path in sorted(pages_root.rglob("*.tsx")):
            rel = str(path.relative_to(workspace)).replace("\\", "/")
            pages.append(rel)
    return sorted(set(pages))


def _center_contribution_ids(builtins_text: str) -> list[tuple[str, str | None]]:
    """Return (panel_id, component_symbol) for each center workbench contribution."""
    panels: list[tuple[str, str | None]] = []
    for block in _REGISTER_CONTRIBUTION.finditer(builtins_text):
        body = block.group(1)
        if not _CENTER_ZONE.search(body):
            continue
        id_match = _CENTER_ID.search(body)
        if not id_match:
            continue
        comp_match = _CENTER_COMPONENT.search(body)
        panels.append((id_match.group(1), comp_match.group(1) if comp_match else None))
    return panels


def _app_mounts_center_panel(app_text: str, panel_id: str, component: str | None) -> bool:
    literal_patterns = (
        f"getContribution('center', '{panel_id}')",
        f'getContribution("center", "{panel_id}")',
    )
    if any(p in app_text for p in literal_patterns):
        return True
    dynamic_patterns = (
        "getContribution('center', activeCenterView)",
        'getContribution("center", activeCenterView)',
    )
    if any(p in app_text for p in dynamic_patterns):
        return True
    if component and component in app_text:
        return True
    return False


def _center_workbench_mount_issues(workspace: Path, entry_text: str) -> list[dict]:
    """Ensure center workbench panels registered in builtins are mounted from App.tsx."""
    issues: list[dict] = []
    builtins_rel = "frontend/src/workbench/builtins.tsx"
    app_rel = "frontend/src/App.tsx"
    builtins_text = _read_text(workspace, builtins_rel)
    app_text = _read_text(workspace, app_rel)
    if not builtins_text or not app_text:
        return issues

    center_panels = _center_contribution_ids(builtins_text)
    if not center_panels:
        return issues

    has_generic_center = (
        "getContribution('center'" in app_text
        or 'getContribution("center"' in app_text
        or "getContribution('center'" in entry_text
        or 'getContribution("center"' in entry_text
    )
    if _BROWSER_ONLY_MOUNT in app_text:
        issues.append(
            {
                "severity": "critical",
                "path": app_rel,
                "message": (
                    "Center panels must mount via getContribution('center', ...) "
                    "(CenterContent), not browser-only conditional rendering."
                ),
            }
        )
    elif not has_generic_center:
        issues.append(
            {
                "severity": "critical",
                "path": app_rel,
                "message": (
                    "App.tsx must mount center workbench panels via getContribution('center', ...)."
                ),
            }
        )

    for panel_id, component in center_panels:
        if _app_mounts_center_panel(app_text, panel_id, component):
            continue
        label = component or panel_id
        issues.append(
            {
                "severity": "critical",
                "path": app_rel,
                "message": (
                    f"Center panel '{panel_id}' ({label}) is registered in workbench/builtins.tsx "
                    "but not mounted from App.tsx."
                ),
            }
        )
    return issues


def _orphan_routes_layer(workspace: Path, entry_text: str, changed_files: list[str] | None) -> list[dict]:
    issues: list[dict] = []
    routes_index = workspace / _ROUTES_DIR / "index.tsx"
    if not routes_index.is_file():
        return issues
    rel = str(routes_index.relative_to(workspace)).replace("\\", "/")
    changed_set = {p.replace("\\", "/") for p in (changed_files or [])}
    if changed_set and rel not in changed_set:
        return issues
    markers = ("AppRoutes", "routes/index", "react-router", "BrowserRouter")
    if any(m in _read_text(workspace, rel) for m in markers):
        if not any(m in entry_text for m in ("AppRoutes", "routes/index", "BrowserRouter")):
            issues.append(
                {
                    "severity": "critical",
                    "path": rel,
                    "message": (
                        "Standalone routes layer is not mounted from App.tsx, main.tsx, or workbench. "
                        "Register UI in workbench/builtins.tsx and use useProjectStore instead."
                    ),
                }
            )
    return issues


def integration_guard_issues(
    workspace: Path,
    *,
    changed_files: list[str] | None = None,
) -> list[dict]:
    """Return integration issues for pages/routes not wired into app entry surfaces."""
    if changed_files is not None and not changed_files:
        return []

    entry_text = _entry_surface_text(workspace)
    issues: list[dict] = []

    for rel in _collect_new_or_changed_pages(workspace, changed_files):
        symbols = _page_symbols(workspace, rel)
        if not any(_is_referenced(sym, entry_text, rel) for sym in symbols):
            label = symbols[0] if symbols else Path(rel).stem
            issues.append(
                {
                    "severity": "critical",
                    "path": rel,
                    "message": f"{label} is not imported from any app entry (App, main, workbench)",
                }
            )

    issues.extend(_orphan_routes_layer(workspace, entry_text, changed_files))
    if changed_files is None or any(p.replace("\\", "/").startswith("frontend/") for p in changed_files):
        issues.extend(_center_workbench_mount_issues(workspace, entry_text))

    return issues


def integration_issues(workspace: Path, changed_files: list[str]) -> list[dict]:
    """Alias used by deployment_gates and orchestration."""
    return integration_guard_issues(workspace, changed_files=changed_files)


def integration_requires_visual_evidence(changed_files: list[str]) -> bool:
    return any(
        p.replace("\\", "/").startswith("frontend/src/pages/")
        or p.replace("\\", "/").startswith("frontend/src/routes/")
        or p.replace("\\", "/").startswith("frontend/src/components/")
        for p in changed_files
    )
