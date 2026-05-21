"""Native directory picker for local project setup."""

from __future__ import annotations

import subprocess
import sys


def pick_directory(*, prompt: str = "Select a project folder") -> str | None:
    """Open the OS folder picker. Returns absolute path or None if cancelled."""
    if sys.platform == "darwin":
        return _pick_directory_macos(prompt)
    return _pick_directory_tk(prompt)


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
        timeout=600,
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
