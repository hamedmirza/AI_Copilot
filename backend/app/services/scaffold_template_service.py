"""Read and render the canonical project scaffold template."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates" / "scaffold"
_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


class ScaffoldTemplateService:
    def __init__(self, template_root: Path | None = None) -> None:
        self.template_root = template_root or _TEMPLATE_ROOT

    def list_template_paths(self) -> list[str]:
        if not self.template_root.is_dir():
            return []
        paths: list[str] = []
        for path in sorted(self.template_root.rglob("*")):
            if path.is_file() and path.name != ".gitkeep":
                paths.append(path.relative_to(self.template_root).as_posix())
        return paths

    def read_template(self, rel_path: str) -> str:
        path = self.template_root / rel_path
        if not path.is_file():
            raise FileNotFoundError(f"Scaffold template not found: {rel_path}")
        return path.read_text(encoding="utf-8")

    def render(self, rel_path: str, variables: dict[str, str]) -> str:
        content = self.read_template(rel_path)
        return _PLACEHOLDER_RE.sub(
            lambda match: variables.get(match.group(1), match.group(0)),
            content,
        )

    def render_all(self, variables: dict[str, str]) -> dict[str, str]:
        return {rel: self.render(rel, variables) for rel in self.list_template_paths()}

    def build_context_block(self, variables: dict[str, str] | None = None) -> str:
        vars_ = variables or default_scaffold_variables("Project", "Project description")
        paths = self.list_template_paths()
        lines = [
            "Canonical scaffold template (reference for setup runs):",
            f"Template root: {len(paths)} files",
        ]
        for rel in paths[:40]:
            lines.append(f"- {rel}")
        if len(paths) > 40:
            lines.append(f"- ... and {len(paths) - 40} more")
        sample = self.render("AGENTS.md", vars_) if "AGENTS.md" in paths else ""
        if sample:
            preview = sample[:1200]
            if len(sample) > 1200:
                preview += "\n... (truncated)"
            lines.extend(["", "AGENTS.md (rendered preview):", preview])
        return "\n".join(lines)


def default_scaffold_variables(
    project_name: str,
    project_description: str,
    *,
    stack: str = "python",
    author: str = "Operator",
) -> dict[str, str]:
    from datetime import UTC, datetime

    year = str(datetime.now(UTC).year)
    return {
        "PROJECT_NAME": project_name,
        "PROJECT_DESCRIPTION": project_description or project_name,
        "STACK": stack,
        "TEST_COMMAND": "pytest -q",
        "DEV_SERVER_COMMAND": "./scripts/server.sh start-all",
        "PRIMARY_LANGUAGE": "python" if stack == "python" else "typescript",
        "AUTHOR": author,
        "YEAR": year,
    }
