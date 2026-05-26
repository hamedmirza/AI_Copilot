"""Capture test baseline from clean source before pipeline changes."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from app.tools.lint_runner import get_profile_commands


class BaselineService:
    def capture(
        self,
        source: Path,
        validation_profile: str,
        *,
        timeout: int = 120,
    ) -> dict[str, Any]:
        commands = get_profile_commands("{}", validation_profile) or ["python3 -m compileall ."]
        results: list[dict[str, Any]] = []
        passed = 0
        failed = 0
        failed_names: list[str] = []

        for cmd in commands[:3]:
            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=str(source),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                ok = proc.returncode == 0
                if ok:
                    passed += 1
                else:
                    failed += 1
                    failed_names.append(cmd)
                results.append(
                    {
                        "command": cmd,
                        "returncode": proc.returncode,
                        "passed": ok,
                        "stderr_tail": (proc.stderr or "")[-500:],
                    }
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                failed += 1
                failed_names.append(cmd)
                results.append({"command": cmd, "passed": False, "error": str(exc)})

        total = passed + failed
        summary = f"{passed}/{total} baseline commands passed before this task."
        if failed == total and total > 0:
            summary += " Warning: all baseline checks failed — project may be broken before this task."

        return {
            "summary": summary,
            "passed": passed,
            "failed": failed,
            "failed_commands": failed_names,
            "results": results,
        }

    def context_block(self, baseline: dict[str, Any]) -> str:
        lines = ["Baseline (pre-change):", baseline.get("summary") or ""]
        for item in baseline.get("results") or []:
            status = "pass" if item.get("passed") else "fail"
            lines.append(f"- [{status}] {item.get('command')}")
        return "\n".join(lines)
