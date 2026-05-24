from __future__ import annotations

import re
from pathlib import Path

CODE_EXTENSIONS = {
    ".py",
    ".pyi",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".css",
    ".scss",
    ".mjs",
    ".cjs",
}
FRONTEND_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".html"}

_SYMBOL_PATTERNS = [
    re.compile(r"^\s*export\s+(?:default\s+)?(?:async\s+)?function\s+([A-Za-z_][\w$]*)", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][\w$]*)", re.MULTILINE),
    re.compile(r"^\s*export\s+(?:const|let|var|class|interface|type|enum)\s+([A-Za-z_][\w$]*)", re.MULTILINE),
    re.compile(r"^\s*(?:const|let|var|class|interface|type|enum)\s+([A-Za-z_][\w$]*)", re.MULTILINE),
    re.compile(r"^\s*def\s+([A-Za-z_][\w$]*)", re.MULTILINE),
    re.compile(r"^\s*class\s+([A-Za-z_][\w$]*)", re.MULTILINE),
]
_EXPORT_BLOCK = re.compile(r"export\s*\{([^}]+)\}", re.MULTILINE)
_IMPORT_LINE = re.compile(r"^\s*(import\s|from\s+.+\s+import\s)", re.MULTILINE)


def is_code_path(rel_path: str) -> bool:
    return Path(rel_path).suffix.lower() in CODE_EXTENSIONS


def is_frontend_code_path(rel_path: str) -> bool:
    path = Path(rel_path)
    return rel_path.startswith("frontend/") and path.suffix.lower() in FRONTEND_EXTENSIONS


def _line_count(content: str) -> int:
    if not content:
        return 0
    return len(content.splitlines())


def _symbols(content: str) -> set[str]:
    symbols: set[str] = set()
    for pattern in _SYMBOL_PATTERNS:
        symbols.update(match.group(1) for match in pattern.finditer(content))
    for match in _EXPORT_BLOCK.finditer(content):
        for raw_name in match.group(1).split(","):
            part = raw_name.strip()
            if not part:
                continue
            name = part.split(" as ")[0].strip()
            if name:
                symbols.add(name)
    return symbols


def summarize_structure(rel_path: str, before: str, after: str, existed: bool, used_full_content: bool) -> dict:
    before_lines = _line_count(before)
    after_lines = _line_count(after)
    before_symbols = _symbols(before)
    after_symbols = _symbols(after)
    removed_symbols = sorted(before_symbols - after_symbols)
    before_imports = len(_IMPORT_LINE.findall(before))
    after_imports = len(_IMPORT_LINE.findall(after))
    return {
        "path": rel_path,
        "is_code": is_code_path(rel_path),
        "is_frontend": is_frontend_code_path(rel_path),
        "existed": existed,
        "used_full_content": used_full_content,
        "before_lines": before_lines,
        "after_lines": after_lines,
        "before_imports": before_imports,
        "after_imports": after_imports,
        "removed_symbols": removed_symbols,
    }


def coder_guard_issues(summary: dict) -> list[str]:
    if not summary.get("existed") or not summary.get("is_code"):
        return []
    issues: list[str] = []
    before_lines = int(summary.get("before_lines") or 0)
    after_lines = int(summary.get("after_lines") or 0)
    removed_symbols = list(summary.get("removed_symbols") or [])
    before_imports = int(summary.get("before_imports") or 0)
    after_imports = int(summary.get("after_imports") or 0)
    used_full_content = bool(summary.get("used_full_content"))

    if used_full_content and before_lines >= 20 and after_lines < max(8, int(before_lines * 0.6)):
        issues.append(f"destructive full-file replacement shrank {summary['path']} from {before_lines} lines to {after_lines}")
    if used_full_content and removed_symbols:
        issues.append(
            f"full-file replacement removed exported or declared symbols from {summary['path']}: {', '.join(removed_symbols[:8])}"
        )
    if used_full_content and before_imports >= 2 and after_imports == 0:
        issues.append(f"full-file replacement removed all imports from {summary['path']}")
    return issues


def reviewer_guard_issues(summary: dict) -> list[str]:
    if not summary.get("existed") or not summary.get("is_code"):
        return []
    issues: list[str] = []
    before_lines = int(summary.get("before_lines") or 0)
    after_lines = int(summary.get("after_lines") or 0)
    removed_symbols = list(summary.get("removed_symbols") or [])
    before_imports = int(summary.get("before_imports") or 0)
    after_imports = int(summary.get("after_imports") or 0)

    if before_lines >= 20 and after_lines < max(8, int(before_lines * 0.6)):
        issues.append(f"Structural regression: {summary['path']} dropped from {before_lines} lines to {after_lines}")
    if removed_symbols:
        issues.append(f"Structural regression: {summary['path']} removed symbols {', '.join(removed_symbols[:8])}")
    if before_imports >= 2 and after_imports == 0:
        issues.append(f"Structural regression: {summary['path']} lost all imports")
    return issues
