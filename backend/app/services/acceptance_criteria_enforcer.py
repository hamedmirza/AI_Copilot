"""Deterministic mapping of planner acceptance criteria to gate results."""

from __future__ import annotations

import re


_KEYWORD_GATES = (
    (re.compile(r"\breachable\b|\bvisible\b|\bwired\b|\bmounted\b|\bnavigation\b", re.I), "integration_guard"),
    (re.compile(r"\breporting\b|\bchart\b|\bmetrics\b", re.I), "contract_guard"),
    (re.compile(r"\bapi\b|\bendpoint\b|\bfetch\b", re.I), "contract_guard"),
    (re.compile(r"\bscreenshot\b|\bvisual\b|\bbrowser\b|\bui\b", re.I), "visual_evidence"),
    (re.compile(r"\btest\b|\bbuild\b|\btypecheck\b|\btsc\b", re.I), "test_plan"),
)


def acceptance_criteria_gate_map(criteria_lines: list[str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for line in criteria_lines:
        text = line.strip()
        if not text:
            continue
        for pattern, gate in _KEYWORD_GATES:
            if pattern.search(text):
                mapping.setdefault(gate, []).append(text)
    return mapping


def criteria_gate_issues(
    plan: dict,
    *,
    integration_ok: bool,
    contract_ok: bool,
    visual_ok: bool,
    dry_run_ok: bool,
    pre_deploy_ok: bool,
) -> list[dict]:
    lines: list[str] = []
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for criterion in step.get("acceptance_criteria") or []:
            text = str(criterion or "").strip()
            if text:
                lines.append(text)
    gate_results = {
        "integration_guard": integration_ok,
        "contract_guard": contract_ok,
        "visual_evidence": visual_ok,
        "test_plan": dry_run_ok,
        "pre_deploy_supervisor": pre_deploy_ok,
    }
    return evaluate_acceptance_criteria(lines, gate_results=gate_results)


def evaluate_acceptance_criteria(
    criteria_lines: list[str],
    *,
    gate_results: dict[str, bool],
) -> list[dict]:
    """Return failures when a criterion maps to a gate that did not pass."""
    mapping = acceptance_criteria_gate_map(criteria_lines)
    failures: list[dict] = []
    for gate, criteria in mapping.items():
        if not gate_results.get(gate, True):
            for criterion in criteria:
                failures.append(
                    {
                        "severity": "critical",
                        "gate": gate,
                        "message": f"Acceptance criterion not satisfied ({gate}): {criterion}",
                    }
                )
    return failures
