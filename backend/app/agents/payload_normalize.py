"""Map common LLM JSON aliases to agent output schemas before Pydantic validation."""

from typing import Any


def normalize_agent_payload(schema_name: str, payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    if schema_name == "PlannerOutput":
        return _normalize_planner(payload)
    if schema_name == "ArchitectOutput":
        return _normalize_architect(payload)
    if schema_name == "CoderOutput":
        return _normalize_coder(payload)
    return payload


def _normalize_planner(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if "summary" not in out:
        for key in ("task", "expected_output", "objective", "goal"):
            if key in out and out[key]:
                out["summary"] = str(out.pop(key))
                break
    steps = out.get("steps")
    if not isinstance(steps, list):
        return out
    normalized_steps: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        s = dict(step)
        if "step_id" not in s and "id" in s:
            s["step_id"] = str(s.pop("id"))
        if "title" not in s and "name" in s:
            s["title"] = str(s.pop("name"))
        normalized_steps.append(s)
    out["steps"] = normalized_steps
    if "risks" not in out:
        out["risks"] = []
    return out


def _normalize_architect(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if "overview" not in out:
        for key in ("summary", "status", "objective", "goal"):
            if key in out and out[key]:
                out["overview"] = str(out[key])
                break
    if "modules" not in out:
        for key in ("components", "areas", "packages"):
            value = out.get(key)
            if isinstance(value, list) and value:
                out["modules"] = [str(item) for item in value]
                break
    if "file_changes" not in out:
        for key in ("files", "patches", "blueprint", "blueprints"):
            value = out.get(key)
            if isinstance(value, list):
                normalized_changes: list[dict[str, Any]] = []
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    change = dict(item)
                    if "path" not in change:
                        for path_key in ("file", "file_path"):
                            if path_key in change and change[path_key]:
                                change["path"] = str(change[path_key])
                                break
                    if "action" not in change:
                        for action_key in ("change_type", "type", "operation"):
                            if action_key in change and change[action_key]:
                                change["action"] = str(change[action_key])
                                break
                    if "rationale" not in change:
                        for rationale_key in ("reason", "why", "notes", "description"):
                            if rationale_key in change and change[rationale_key]:
                                change["rationale"] = str(change[rationale_key])
                                break
                    normalized_changes.append(change)
                if normalized_changes:
                    out["file_changes"] = normalized_changes
                    break
    if "dependencies" not in out:
        out["dependencies"] = []
    return out


def _normalize_coder(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if "summary" not in out:
        for key in ("status", "overview", "notes", "description"):
            if key in out and out[key]:
                out["summary"] = str(out[key])
                break
    if "file_changes" not in out:
        for key in ("patches", "changes", "files"):
            value = out.get(key)
            if isinstance(value, list):
                normalized_changes: list[dict[str, Any]] = []
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    change = dict(item)
                    if "path" not in change:
                        for path_key in ("file", "file_path"):
                            if path_key in change and change[path_key]:
                                change["path"] = str(change[path_key])
                                break
                    if "line_changes" not in change and isinstance(change.get("patch"), list):
                        change["line_changes"] = change["patch"]
                    normalized_changes.append(change)
                out["file_changes"] = normalized_changes
                break
    if "requires_operator_approval" not in out:
        out["requires_operator_approval"] = False
    return out
