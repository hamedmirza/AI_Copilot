"""Map common LLM JSON aliases to agent output schemas before Pydantic validation."""

import json
import re
from typing import Any

_SMART_QUOTE_MAP = str.maketrans({
    "\u201c": '"',
    "\u201d": '"',
    "\u2018": "'",
    "\u2019": "'",
})


def strip_markdown_json_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if not lines:
        return stripped
    first = lines[0].strip("`").strip().lower()
    body = lines[1:] if first in {"", "json"} else lines
    if body and body[-1].strip() == "```":
        body = body[:-1]
    return "\n".join(body).strip()


def _extract_outer_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _remove_trailing_commas(text: str) -> str:
    return re.sub(r",(\s*[}\]])", r"\1", text)


def _escape_control_chars_inside_json_strings(text: str) -> str:
    """Turn literal newlines/tabs inside JSON strings into escapes (common LLM mistake)."""
    out: list[str] = []
    in_string = False
    escape = False
    for char in text:
        if not in_string:
            out.append(char)
            if char == '"':
                in_string = True
                escape = False
            continue
        if escape:
            out.append(char)
            escape = False
            continue
        if char == "\\":
            out.append(char)
            escape = True
            continue
        if char == '"':
            out.append(char)
            in_string = False
            continue
        if char == "\n":
            out.append("\\n")
            continue
        if char == "\r":
            out.append("\\r")
            continue
        if char == "\t":
            out.append("\\t")
            continue
        if ord(char) < 0x20:
            out.append(f"\\u{ord(char):04x}")
            continue
        out.append(char)
    return "".join(out)


def repair_agent_json_text(text: str) -> str:
    """Best-effort repair for malformed agent JSON before ``json.loads``."""
    repaired = strip_markdown_json_fence(text.strip())
    repaired = repaired.translate(_SMART_QUOTE_MAP)
    extracted = _extract_outer_json_object(repaired)
    if extracted:
        repaired = extracted
    repaired = _escape_control_chars_inside_json_strings(repaired)
    repaired = _remove_trailing_commas(repaired)
    return repaired.strip()


def preprocess_agent_json_text(text: str) -> str:
    return repair_agent_json_text(text)


def loads_agent_json(text: str):
    last_exc: json.JSONDecodeError | None = None
    seen: set[str] = set()
    for candidate in (text.strip(), preprocess_agent_json_text(text)):
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_exc = exc
            msg = str(exc).lower()
            if "control character" in msg or "invalid \\escape" in msg:
                try:
                    return json.loads(candidate, strict=False)
                except json.JSONDecodeError as strict_exc:
                    last_exc = strict_exc
    if last_exc is not None:
        raise last_exc
    raise json.JSONDecodeError("Empty JSON payload", text, 0)


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


def _normalize_line_changes(change: dict[str, Any]) -> dict[str, Any]:
    line_changes = change.get("line_changes")
    if not isinstance(line_changes, list):
        return change
    normalized: list[dict[str, Any]] = []
    for item in line_changes:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if "new_content" in row and row["new_content"] is not None:
            row["new_content"] = str(row["new_content"])
        normalized.append(row)
    change["line_changes"] = normalized
    return change


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
                    normalized_changes.append(_normalize_line_changes(change))
                out["file_changes"] = normalized_changes
                break
    else:
        file_changes = out.get("file_changes")
        if isinstance(file_changes, list):
            out["file_changes"] = [
                _normalize_line_changes(dict(item))
                for item in file_changes
                if isinstance(item, dict)
            ]
    if "requires_operator_approval" not in out:
        out["requires_operator_approval"] = False
    return out
