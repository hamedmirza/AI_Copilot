import re
import shlex
import subprocess
from pathlib import Path

from app.core.exceptions import CommandRejectedError

ALLOWED_EXECUTABLES = frozenset(
    {
        "ruff",
        "mypy",
        "pytest",
        "python3",
        "python",
        "npm",
        "node",
        "eslint",
        "tsc",
        "vitest",
        "npx",
        "git",
        "rg",
        "grep",
    }
)

FORBIDDEN_PATTERNS = [
    r"&&",
    r"\|\|",
    r";",
    r"\|",
    r">",
    r"<",
    r"`",
    r"\$\(",
    r"rm\s",
    r"curl\s",
    r"wget\s",
]


def validate_command(command: str) -> None:
    cmd = command.strip()
    if not cmd:
        raise CommandRejectedError("Empty command")
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, cmd):
            raise CommandRejectedError(f"Command rejected (forbidden pattern): {cmd}")
    parts = shlex.split(cmd)
    if not parts:
        raise CommandRejectedError("Invalid command")
    executable = Path(parts[0]).name
    if executable not in ALLOWED_EXECUTABLES:
        raise CommandRejectedError(f"Executable not whitelisted: {executable}")


def run_command(command: str, cwd: Path, timeout: int = 300) -> tuple[int, str, str]:
    validate_command(command)
    proc = subprocess.run(
        command,
        shell=True,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr
