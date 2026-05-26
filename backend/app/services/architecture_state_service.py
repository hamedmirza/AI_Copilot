"""Maintain .ai-copilot/architecture.md in project source."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path


class ArchitectureStateService:
    ARCH_PATH = ".ai-copilot/architecture.md"

    def read(self, root: Path) -> str:
        path = Path(root).resolve() / self.ARCH_PATH
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")

    def append_task_summary(
        self,
        root: Path,
        task_summary: str,
        *,
        architecture_delta: str = "",
        workspace: Path | None = None,
    ) -> str:
        target_root = workspace or Path(root).resolve()
        path = target_root / self.ARCH_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        existing = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        stamp = datetime.now(UTC).strftime("%Y-%m-%d")
        history_line = f"- {stamp}: {task_summary.strip()}"
        parts = [existing.rstrip(), "", "## History", history_line]
        if architecture_delta.strip():
            parts.extend(["", "## Latest change", architecture_delta.strip()])
        content = "\n".join(parts).strip() + "\n"
        path.write_text(content, encoding="utf-8")
        return content

    def initialize_greenfield(self, project_name: str, description: str, workspace: Path) -> None:
        path = workspace / self.ARCH_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            return
        path.write_text(
            f"# Architecture state — {project_name}\n\n{description}\n\n## History\n",
            encoding="utf-8",
        )
