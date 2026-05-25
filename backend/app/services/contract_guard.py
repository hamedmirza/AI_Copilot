"""Frontend fetch paths vs registered FastAPI routes."""

from __future__ import annotations

import re
from pathlib import Path

_FETCH_API = re.compile(
    r"""fetch\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.MULTILINE,
)
_REQUEST_API = re.compile(
    r"""request\s*[<(][^>]*>\s*\(\s*['"`]([^'"`]+)['"`]""",
    re.MULTILINE,
)

# Routes registered in backend (prefix /api from router mount).
_KNOWN_API_ROUTES = frozenset({
    "/api/health",
    "/api/health/provider",
    "/api/settings",
    "/api/settings/reset",
    "/api/settings/models",
    "/api/onboarding/status",
    "/api/dialog/pick-directory",
    "/api/projects",
    "/api/tasks",
    "/api/runs/{run_id}",
    "/api/runs/{run_id}/events",
    "/api/runs/{run_id}/artifacts",
    "/api/runs/{run_id}/postmortem",
    "/api/runs/{run_id}/approve",
    "/api/runs/{run_id}/reject",
    "/api/runs/{run_id}/retry",
    "/api/runs/{run_id}/resume",
    "/api/runs/{run_id}/rollback-workspace",
    "/api/runs/{run_id}/rollback-promote",
    "/api/runs/{run_id}/deployment-readiness",
    "/api/runs/{run_id}/files/{path}",
    "/api/runs/failure-summary",
    "/api/projects/{project_id}",
    "/api/projects/{project_id}/metrics",
    "/api/projects/{project_id}/blockers",
    "/api/projects/{project_id}/release-readiness",
    "/api/projects/{project_id}/lessons",
    "/api/projects/{project_id}/improvements",
    "/api/projects/{project_id}/tree",
    "/api/projects/{project_id}/files/{path}",
    "/api/projects/{project_id}/runs",
    "/api/projects/{project_id}/git/status",
    "/api/chat/modes",
    "/api/chat/sessions",
    "/api/chat/sessions/{session_id}",
    "/api/chat/sessions/{session_id}/messages",
    "/api/chat/sessions/{session_id}/spawn-task",
    "/api/chat/sessions/{session_id}/cancel",
})


def _normalize_path(path: str) -> str:
    p = path.split("?")[0].strip()
    if not p.startswith("/api/"):
        if p.startswith("/"):
            p = f"/api{p}" if not p.startswith("/api") else p
        else:
            p = f"/api/{p.lstrip('/')}"
    segments = p.split("/")
    normalized: list[str] = []
    for seg in segments:
        if seg and (
            seg.startswith("{")
            or (len(seg) == 36 and seg.count("-") >= 4)
            or seg.isdigit()
        ):
            normalized.append("{id}")
        else:
            normalized.append(seg)
    return "/".join(normalized)


def _route_matches(candidate: str, known: str) -> bool:
    if candidate == known:
        return True
    c_parts = candidate.split("/")
    k_parts = known.split("/")
    if len(c_parts) != len(k_parts):
        return False
    for c, k in zip(c_parts, k_parts, strict=True):
        if k in ("{project_id}", "{task_id}", "{run_id}", "{path}", "{session_id}", "{id}"):
            continue
        if c != k:
            return False
    return True


def _extract_api_paths(text: str) -> list[str]:
    paths: list[str] = []
    for pattern in (_FETCH_API, _REQUEST_API):
        for match in pattern.finditer(text):
            raw = match.group(1).strip()
            if raw.startswith("/api") or raw.startswith("/"):
                paths.append(_normalize_path(raw))
    return paths


def contract_issues(workspace: Path, changed_files: list[str]) -> list[dict]:
    """Alias used by deployment_gates and orchestration."""
    return contract_guard_issues(workspace, changed_files)


def contract_guard_issues(workspace: Path, changed_files: list[str]) -> list[dict]:
    issues: list[dict] = []
    for rel in changed_files:
        if not rel.replace("\\", "/").startswith("frontend/"):
            continue
        path = workspace / rel
        if not path.is_file() or path.suffix.lower() not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "api/client" in text or "from '@/api/client'" in text:
            continue
        for api_path in _extract_api_paths(text):
            if not any(_route_matches(api_path, known) for known in _KNOWN_API_ROUTES):
                issues.append(
                    {
                        "severity": "critical",
                        "path": rel,
                        "message": f"Frontend calls unregistered API path: {api_path}",
                    }
                )
    return issues
