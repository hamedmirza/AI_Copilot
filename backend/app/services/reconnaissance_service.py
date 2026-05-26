"""Repository reconnaissance — ground truth from source, not workspace."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.enums import RepoMode
from app.services.architecture_state_service import ArchitectureStateService

SENTINEL_FILES = (
    "AGENTS.md",
    "README.md",
    "pyproject.toml",
    "package.json",
    "frontend/package.json",
    "backend/pyproject.toml",
    ".cursorrules",
    "docs/ARCHITECTURE.md",
)

_CONVENTION_FILES = (
    ("AGENTS.md", 4000),
    ("README.md", 3000),
    ("pyproject.toml", 2500),
    ("package.json", 2000),
    ("frontend/package.json", 2000),
)

_SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__", "dist", "build", ".cursor"}

_STAGE_TIER: dict[str, int] = {
    "app_designer": 1,
    "planner": 1,
    "architect": 2,
    "ui_designer": 2,
    "coder": 3,
    "reviewer": 2,
    "tester": 1,
    "documentation": 1,
}


@dataclass(frozen=True)
class ReconSnapshot:
    repo_mode: str
    stack_profile: str
    payload: dict

    def format_for_stage(self, stage: str, *, use_scout: bool) -> str:
        tier_cap = _STAGE_TIER.get(stage, 1)
        if not use_scout:
            tier_cap = min(tier_cap, 1)
        lines = [
            "Repository reconnaissance (source tree, not workspace patches):",
            f"- repo_mode: {self.repo_mode}",
            f"- stack_profile: {self.stack_profile}",
        ]
        tree = self.payload.get("file_tree") or []
        if tree and tier_cap >= 1:
            lines.append("- file_tree (sample):")
            lines.extend(f"  - {p}" for p in tree[:40])
        conventions = self.payload.get("conventions") or {}
        if conventions and tier_cap >= 1:
            lines.append("- project conventions:")
            for name, excerpt in list(conventions.items())[:4]:
                lines.append(f"  - {name}: {excerpt[:500]}")
        keywords = self.payload.get("expanded_keywords") or []
        if keywords and tier_cap >= 1:
            lines.append(f"- task keywords: {', '.join(keywords[:12])}")
        call_sites = self.payload.get("call_sites") or []
        if call_sites and tier_cap >= 2:
            lines.append("- call-site hints:")
            lines.extend(f"  - {item}" for item in call_sites[:15])
        arch = self.payload.get("architecture_excerpt") or ""
        if arch and tier_cap >= 1:
            lines.append(f"- architecture state:\n{arch[:2000]}")
        greenfield = self.payload.get("greenfield_hints") or []
        if greenfield and self.repo_mode == RepoMode.GREENFIELD.value:
            lines.append("- greenfield hints:")
            lines.extend(f"  - {h}" for h in greenfield)
        return "\n".join(lines)


class ReconnaissanceService:
    def __init__(self) -> None:
        self._arch = ArchitectureStateService()

    def detect_repo_mode(self, source_root: Path) -> str:
        root = Path(source_root)
        if not root.is_dir():
            return RepoMode.GREENFIELD.value
        present = sum(1 for rel in SENTINEL_FILES if (root / rel).is_file())
        if present == 0:
            return RepoMode.GREENFIELD.value
        if present < 3:
            return RepoMode.PARTIAL.value
        return RepoMode.EXISTING.value

    def infer_stack_profile(self, source_root: Path, validation_profile: str) -> str:
        root = Path(source_root)
        has_frontend = (root / "frontend" / "package.json").is_file() or (root / "package.json").is_file()
        has_python = (root / "pyproject.toml").is_file() or any(root.rglob("*.py"))
        if has_frontend and has_python:
            return "fullstack"
        if has_frontend:
            return "react"
        if has_python:
            return "python"
        return validation_profile or "python"

    def build_snapshot(
        self,
        source_root: Path,
        *,
        task_description: str,
        validation_profile: str,
        use_scout: bool,
        stack_profile: str | None = None,
    ) -> ReconSnapshot:
        root = Path(source_root)
        repo_mode = self.detect_repo_mode(root)
        stack = stack_profile or self.infer_stack_profile(root, validation_profile)
        keywords = self._expand_keywords(task_description)
        payload: dict = {
            "repo_mode": repo_mode,
            "stack_profile": stack,
            "file_tree": self._list_files(root, depth=3 if use_scout else 2),
            "conventions": self._read_conventions(root),
            "expanded_keywords": keywords,
            "call_sites": self._find_call_sites(root, keywords) if use_scout else [],
            "sentinel_present": [rel for rel in SENTINEL_FILES if (root / rel).is_file()],
            "architecture_excerpt": self._arch.read(root)[:3000],
            "greenfield_hints": self._greenfield_hints(stack) if repo_mode == RepoMode.GREENFIELD.value else [],
        }
        return ReconSnapshot(repo_mode=repo_mode, stack_profile=stack, payload=payload)

    def snapshot_to_json(self, snapshot: ReconSnapshot) -> str:
        return json.dumps(
            {
                "repo_mode": snapshot.repo_mode,
                "stack_profile": snapshot.stack_profile,
                **snapshot.payload,
            },
            ensure_ascii=True,
        )

    def _expand_keywords(self, text: str) -> list[str]:
        tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", text.lower())
        stop = {"the", "and", "for", "with", "this", "that", "from", "into", "add", "implement"}
        seen: list[str] = []
        for token in tokens:
            if token in stop or token in seen:
                continue
            seen.append(token)
            if len(seen) >= 20:
                break
        return seen

    def _read_conventions(self, root: Path) -> dict[str, str]:
        out: dict[str, str] = {}
        for rel, limit in _CONVENTION_FILES:
            path = root / rel
            if path.is_file():
                out[rel] = path.read_text(encoding="utf-8", errors="replace")[:limit]
        return out

    def _list_files(self, root: Path, *, depth: int) -> list[str]:
        paths: list[str] = []

        def walk(current: Path, level: int) -> None:
            if level > depth or len(paths) >= 80:
                return
            try:
                entries = sorted(current.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except OSError:
                return
            for entry in entries:
                if entry.name in _SKIP_DIRS or entry.name.startswith("."):
                    continue
                rel = entry.relative_to(root).as_posix()
                paths.append(rel + ("/" if entry.is_dir() else ""))
                if entry.is_dir():
                    walk(entry, level + 1)

        walk(root, 0)
        return paths

    def _find_call_sites(self, root: Path, keywords: list[str]) -> list[str]:
        if not keywords:
            return []
        hits: list[str] = []
        patterns = [re.compile(re.escape(k), re.IGNORECASE) for k in keywords[:8]]
        for path in root.rglob("*"):
            if len(hits) >= 20:
                break
            if not path.is_file() or path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for pattern in patterns:
                if pattern.search(text):
                    rel = path.relative_to(root).as_posix()
                    hits.append(rel)
                    break
        return hits

    def _greenfield_hints(self, stack_profile: str) -> list[str]:
        hints = [
            "Use canonical scaffold from AI Copilot templates/scaffold.",
            "Create governance files (AGENTS.md, docs/, .ai-copilot/architecture.md) before feature code.",
        ]
        if stack_profile == "fullstack":
            hints.append("Plan both backend/ and frontend/ entrypoints.")
        elif stack_profile == "react":
            hints.append("Start with frontend/package.json and src/App.tsx.")
        else:
            hints.append("Start with pyproject.toml and backend/app/api/main.py.")
        return hints
