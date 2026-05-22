"""Human-readable labels for pipeline runs."""

from __future__ import annotations

import re
from datetime import datetime

_MAX_NAME_LEN = 80
_TASK_PREFIX = re.compile(r"^\s*\d+\s*[:.)]\s*")


def _first_task_line(description: str) -> str:
    text = (description or "").strip()
    if not text:
        return ""
    line = text.splitlines()[0].strip()
    return _TASK_PREFIX.sub("", line).strip()


def derive_run_display_name(
    task_description: str,
    created_at: datetime,
    *,
    run_number: int | None = None,
) -> str:
    """Build a short title from the task description, with optional disambiguation."""
    line = _first_task_line(task_description)
    if not line:
        base = created_at.strftime("Run %b %d, %H:%M UTC")
    elif len(line) <= _MAX_NAME_LEN:
        base = line
    else:
        base = line[: _MAX_NAME_LEN - 1].rstrip() + "…"

    if run_number is not None and run_number > 1:
        suffix = f" ({run_number})"
        if len(base) + len(suffix) > _MAX_NAME_LEN + 12:
            base = base[: max(20, _MAX_NAME_LEN - len(suffix))].rstrip() + "…"
        base = f"{base}{suffix}"
    return base


def run_numbers_for_task(runs: list) -> dict[str, int]:
    """Map run id -> 1-based attempt index per task (oldest first)."""
    by_task: dict[str, list] = {}
    for run in runs:
        by_task.setdefault(run.task_id, []).append(run)
    numbers: dict[str, int] = {}
    for task_runs in by_task.values():
        ordered = sorted(task_runs, key=lambda r: r.created_at)
        for index, run in enumerate(ordered, start=1):
            numbers[run.id] = index
    return numbers
