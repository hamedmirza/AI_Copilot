"""Load static role skill markdown for pipeline agents and chat modes."""

from __future__ import annotations

from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent / "skills"

_BUILTIN_CHAT_MODE_SKILLS = frozenset({"general", "agent", "planner", "debugger", "architect"})

# Prompt filename stem → skill file stem when they differ.
_PROMPT_STEM_TO_SKILL: dict[str, str] = {
    "ui_designer": "ui-designer",
    "playbook_supervisor": "playbook-supervisor",
}


def _load_skill_file(stem: str) -> str:
    path = SKILLS_DIR / f"{stem}.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_role_skill(name: str) -> str:
    """Return trimmed skill markdown for ``name`` (without ``.md``), or empty string."""
    key = (name or "").strip()
    if not key:
        return ""
    if key.endswith(".md"):
        key = key[:-3]
    return _load_skill_file(key)


def load_integrity_charter() -> str:
    """Return universal integrity rules injected into every agent prompt."""
    return _load_skill_file("_integrity")


def load_pipeline_framework() -> str:
    """Return shared pipeline stage contract injected once per agent prompt."""
    return _load_skill_file("pipeline-framework")


def skill_key_from_prompt_filename(prompt_filename: str) -> str:
    """Map a pipeline prompt file name to its role skill stem."""
    stem = Path(prompt_filename or "").stem
    if not stem:
        return ""
    return _PROMPT_STEM_TO_SKILL.get(stem, stem.replace("_", "-"))


def chat_mode_skill_key(mode_key: str, custom_skill_key: str | None = None) -> str:
    """Resolve chat mode to a skill file stem, or empty if no skill applies."""
    custom = (custom_skill_key or "").strip()
    if custom:
        return custom.removesuffix(".md")
    key = (mode_key or "general").strip().lower()
    if key in _BUILTIN_CHAT_MODE_SKILLS:
        return key
    return ""
