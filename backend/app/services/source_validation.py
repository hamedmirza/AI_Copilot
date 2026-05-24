from __future__ import annotations

import re
from pathlib import Path


_IMPORT_LINE = re.compile(r"^\s*import\b")
_COMMENT_LINE = re.compile(r"^\s*(//|/\*|\*|\*/)")
_ANY_TOKEN = re.compile(r"(?<![A-Za-z0-9_])any(?![A-Za-z0-9_])")


def validate_line_change_ranges(existing_content: str, line_changes: list[dict] | None) -> list[dict]:
    if not line_changes:
        return []
    issues: list[dict] = []
    max_line = max(1, len(existing_content.splitlines()))
    for index, change in enumerate(line_changes):
        start_line = int(change.get("start_line") or 0)
        end_line = int(change.get("end_line") or 0)
        if start_line < 1:
            issues.append(
                {
                    "kind": "line_range",
                    "message": f"line_changes[{index}] start_line must be >= 1",
                }
            )
        if end_line < start_line:
            issues.append(
                {
                    "kind": "line_range",
                    "message": f"line_changes[{index}] end_line must be >= start_line",
                }
            )
        if start_line > max_line + 1:
            issues.append(
                {
                    "kind": "line_range",
                    "message": f"line_changes[{index}] start_line exceeds file length ({max_line})",
                }
            )
    return issues


def frontend_structure_issues(rel_path: str, before: str, after: str) -> list[dict]:
    path = Path(rel_path)
    if path.suffix.lower() not in {".ts", ".tsx", ".js", ".jsx"}:
        return []
    issues: list[dict] = []
    if _has_import_outside_import_block(after):
        issues.append(
            {
                "kind": "import_block",
                "message": f"{rel_path} contains import statements outside the top import block",
            }
        )
    if _has_any_downgrade(before, after):
        issues.append(
            {
                "kind": "type_downgrade",
                "message": f"{rel_path} introduces additional 'any' usage in a touched typed source file",
            }
        )
    return issues


def _has_import_outside_import_block(content: str) -> bool:
    saw_non_import = False
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or _COMMENT_LINE.match(line):
            continue
        if _IMPORT_LINE.match(line):
            if saw_non_import:
                return True
            continue
        saw_non_import = True
    return False


def _has_any_downgrade(before: str, after: str) -> bool:
    return len(_ANY_TOKEN.findall(after)) > len(_ANY_TOKEN.findall(before))
