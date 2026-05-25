"""Infer workspace dev-server base URL and routes from changed frontend files."""

from __future__ import annotations

import json
import re
from pathlib import Path

_PORT_PATTERNS = (
    re.compile(r"--port[=\s]+(\d+)", re.I),
    re.compile(r"-p\s+(\d+)"),
    re.compile(r":(\d{4,5})\b"),
    re.compile(r"localhost:(\d{4,5})", re.I),
    re.compile(r"127\.0\.0\.1:(\d{4,5})"),
)

_SCRIPT_NAMES = ("dev", "start", "serve", "preview")

_PAGE_ROUTE_HINTS: dict[str, str] = {
    "reportingpage": "/reporting",
    "reporting": "/reporting",
}


def _parse_port_hint(script: str) -> int | None:
    for pattern in _PORT_PATTERNS:
        match = pattern.search(script)
        if match and match.group(1):
            port = int(match.group(1))
            if 0 < port < 65536:
                return port
    if re.search(r"\bvite\b", script, re.I):
        return 5173
    if re.search(r"\bnext dev\b", script, re.I):
        return 3000
    return None


def _read_package_json(workspace: Path, rel: str) -> dict | None:
    path = workspace / rel
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def infer_dev_server_base(workspace: Path) -> str:
    """Return loopback base URL for the workspace frontend dev server."""
    candidates = ("frontend/package.json", "package.json")
    for rel in candidates:
        pkg = _read_package_json(workspace, rel)
        if not pkg:
            continue
        scripts_value = pkg.get("scripts")
        scripts = scripts_value if isinstance(scripts_value, dict) else {}
        script_text = ""
        for name in _SCRIPT_NAMES:
            value = scripts.get(name)
            if isinstance(value, str) and value.strip():
                script_text = value
                break
        if not script_text and scripts:
            first = next(iter(scripts.values()), "")
            script_text = str(first) if first else ""
        port = _parse_port_hint(script_text) if script_text else None
        if port:
            return f"http://localhost:{port}/"
    return "http://localhost:5173/"


def infer_routes_from_changed_files(changed_files: list[str]) -> list[str]:
    routes: list[str] = []
    seen: set[str] = set()
    for raw in changed_files:
        path = raw.replace("\\", "/").lower()
        for token, route in _PAGE_ROUTE_HINTS.items():
            if token in path and route not in seen:
                seen.add(route)
                routes.append(route)
        if "routes/index" in path:
            for route in ("/reporting",):
                if route not in seen:
                    seen.add(route)
                    routes.append(route)
    return routes


def build_default_visual_checks(workspace: Path, changed_files: list[str]) -> list[dict]:
    base = infer_dev_server_base(workspace).rstrip("/")
    routes = infer_routes_from_changed_files(changed_files)
    if not routes:
        routes = ["/"]
    checks: list[dict] = []
    for route in routes:
        url = f"{base}{route.lstrip('/')}" if route != "/" else f"{base}/"
        label = route if route != "/" else "home"
        checks.append(
            {
                "url": url,
                "description": f"Visual check: {label}",
                "expected": "",
                "steps": [],
            }
        )
    return checks


def join_url(base: str, route: str) -> str:
    base_clean = (base or "").rstrip("/") + "/"
    if route in ("", "/"):
        return base_clean
    return base_clean.rstrip("/") + "/" + route.lstrip("/")
