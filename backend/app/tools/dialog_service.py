"""Native directory picker for local project setup."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

PICK_DIRECTORY_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class PickDirectoryResult:
    path: str | None
    cancelled: bool
    error: str | None = None


def pick_directory(*, prompt: str = "Select a project folder") -> PickDirectoryResult:
    """Open the OS folder picker. Returns path, cancel, or timeout error."""
    try:
        if sys.platform == "darwin":
            path = _pick_directory_macos(prompt)
        else:
            path = _pick_directory_tk(prompt)
    except subprocess.TimeoutExpired:
        return PickDirectoryResult(path=None, cancelled=True, error="timeout")
    return PickDirectoryResult(path=path, cancelled=path is None)


def _pick_directory_macos(prompt: str) -> str | None:
    escaped = prompt.replace("\\", "\\\\").replace('"', '\\"')
    script = (
        f'tell application "System Events" to activate\n'
        f'set folderPath to choose folder with prompt "{escaped}"\n'
        f"return POSIX path of folderPath"
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=PICK_DIRECTORY_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return None
    path = result.stdout.strip()
    return path or None


def _pick_directory_tk(prompt: str) -> str | None:
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    path = filedialog.askdirectory(title=prompt, mustexist=False)
    root.destroy()
    return path or None
