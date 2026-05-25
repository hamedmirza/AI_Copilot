"""Tests for static role skills and prompt loading."""

from app.agents import PlannerAgent, UIDesignerAgent, PlaybookSupervisorAgent, SupervisorAgent
from app.agents.skill_loader import (
    SKILLS_DIR,
    chat_mode_skill_key,
    load_integrity_charter,
    load_pipeline_framework,
    load_role_skill,
    skill_key_from_prompt_filename,
)
from app.providers.fake import FakeProvider
from app.services.chat_mode_registry import ChatModeRegistry


EXPECTED_SKILL_FILES = {
    "planner",
    "architect",
    "ui-designer",
    "coder",
    "reviewer",
    "tester",
    "supervisor",
    "playbook-supervisor",
    "general",
    "agent",
    "debugger",
}


def test_all_role_skill_files_exist_and_nonempty():
    for name in EXPECTED_SKILL_FILES:
        path = SKILLS_DIR / f"{name}.md"
        assert path.is_file(), f"missing skill file: {name}.md"
        assert load_role_skill(name), f"empty skill file: {name}.md"


def test_skill_key_from_prompt_filename_mappings():
    assert skill_key_from_prompt_filename("planner.md") == "planner"
    assert skill_key_from_prompt_filename("ui_designer.md") == "ui-designer"
    assert skill_key_from_prompt_filename("playbook_supervisor.md") == "playbook-supervisor"


def test_planner_agent_loads_prompt_and_skill():
    agent = PlannerAgent(FakeProvider())
    prompt = agent.load_system_prompt()
    assert "Planner agent" in prompt or "Planner role skill" in prompt
    assert "Pipeline mode" in prompt
    assert "Chat mode" in prompt


def test_ui_designer_explicit_skill_filename():
    agent = UIDesignerAgent(FakeProvider())
    assert agent.skill_filename == "ui-designer"
    assert "UI Designer role skill" in agent.load_system_prompt()


def test_playbook_supervisor_skill_and_schema_fields():
    agent = PlaybookSupervisorAgent(FakeProvider())
    prompt = agent.load_system_prompt()
    assert "safety_concerns" in prompt
    assert "required_changes" in prompt


def test_chat_mode_skill_key_builtins():
    for mode in ("general", "agent", "planner", "debugger", "architect"):
        assert chat_mode_skill_key(mode) == mode


def test_chat_mode_skill_key_custom():
    assert chat_mode_skill_key("custom", "my-skill.md") == "my-skill"
    assert chat_mode_skill_key("custom", None) == ""


def test_chat_mode_registry_custom_skill_key():
    registry = ChatModeRegistry(
        {
            "chat_modes_json": '[{"key":"custom","label":"Custom","system_prompt":"Hi","skill_key":"general"}]'
        }
    )
    mode = registry.get_mode("custom")
    assert mode.skill_key == "general"


def test_integrity_and_pipeline_framework_load():
    integrity = load_integrity_charter()
    framework = load_pipeline_framework()
    assert "Universal rules" in integrity or "integrity charter" in integrity.lower()
    assert "Precedence" in integrity
    assert "VERIFICATION_RULES" in integrity
    assert "Stage contract" in framework or "Stage | Produces" in framework
    assert "Planner" in framework


def test_each_role_skill_has_integrity_and_handoff_sections():
    for name in EXPECTED_SKILL_FILES:
        content = load_role_skill(name)
        assert "## Integrity rules (mandatory)" in content, f"{name}.md missing Integrity rules section"
        assert "## Pipeline handoff" in content, f"{name}.md missing Pipeline handoff section"
