from pathlib import Path

from app.core.exceptions import PatchGuardError


def check_patch_allowed(path: str, protected_files: list[str]) -> None:
    normalized = Path(path).as_posix()
    for protected in protected_files:
        if normalized == protected or normalized.endswith(f"/{protected}"):
            raise PatchGuardError(path, "File is in protected files registry")


def apply_line_changes(content: str, line_changes: list[dict]) -> str:
    lines = content.splitlines(keepends=True)
    if not lines and content:
        lines = [content]
    if not lines:
        lines = [""]

    for change in sorted(line_changes, key=lambda c: c["start_line"], reverse=True):
        start = max(1, int(change["start_line"])) - 1
        end = max(start, int(change["end_line"]) - 1)
        new_content = change.get("new_content", "")
        new_lines = new_content.splitlines(keepends=True)
        if new_lines and not new_content.endswith("\n") and "\n" in content:
            new_lines[-1] = new_lines[-1].rstrip("\n") + "\n"
        lines[start : end + 1] = new_lines

    return "".join(lines)
