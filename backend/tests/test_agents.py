import json
from pathlib import Path

import pytest

from app.agents import (
    ArchitectAgent,
    CoderAgent,
    PlannerAgent,
    PlaybookSupervisorAgent,
    ReviewerAgent,
    SupervisorAgent,
    TesterAgent,
    UIDesignerAgent,
)
from pydantic import ValidationError as PydanticValidationError

from app.providers.fake import FakeProvider
from app.schemas.agent_outputs import (
    ArchitectOutput,
    CoderOutput,
    PlannerOutput,
    PlaybookSupervisorOutput,
    ReviewerOutput,
    SupervisorOutput,
    TesterOutput,
    UIDesignerOutput,
)


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


def test_planner_agent(provider: FakeProvider):
    agent = PlannerAgent(provider)
    result = agent.plan("Build a REST API for todos")
    assert isinstance(result, PlannerOutput)
    assert result.summary
    assert len(result.steps) >= 1


def test_planner_normalizes_llm_field_aliases(provider: FakeProvider):
    provider.set_response_for_keyword(
        "planner",
        {
            "task": "Review the whole codebase",
            "steps": [
                {
                    "id": 1,
                    "name": "Repository scan",
                    "description": "Map structure",
                    "acceptance_criteria": ["Structure documented"],
                }
            ],
        },
    )
    result = PlannerAgent(provider).plan("Review the whole codebase")
    assert result.summary == "Review the whole codebase"
    assert result.steps[0].step_id == "1"
    assert result.steps[0].title == "Repository scan"


def test_architect_normalizes_llm_field_aliases(provider: FakeProvider):
    provider.set_response_for_keyword(
        "architect",
        {
            "status": "Repository constraints still allow a draft blueprint.",
            "components": ["backend", "frontend"],
            "files": [
                {
                    "file": "backend/app/api/routes/api.py",
                    "type": "modify",
                    "reason": "Expose account history reconciliation",
                }
            ],
        },
    )
    result = ArchitectAgent(provider).design("Architect the change")
    assert result.overview == "Repository constraints still allow a draft blueprint."
    assert result.modules == ["backend", "frontend"]
    assert result.file_changes[0].path == "backend/app/api/routes/api.py"
    assert result.file_changes[0].action == "modify"
    assert result.file_changes[0].rationale == "Expose account history reconciliation"


def test_architect_agent(provider: FakeProvider):
    agent = ArchitectAgent(provider)
    result = agent.design("Build API")
    assert isinstance(result, ArchitectOutput)
    assert result.overview
    assert len(result.file_changes) >= 1


def test_architect_rejects_empty_file_changes(provider: FakeProvider):
    provider.set_response_for_keyword(
        "architect",
        {
            "overview": "Design only",
            "modules": ["core"],
            "file_changes": [],
            "dependencies": [],
        },
    )
    with pytest.raises(PydanticValidationError):
        ArchitectAgent(provider).design("Architect the change")


def test_architect_strips_prose_dependencies():
    output = ArchitectOutput(
        overview="Extend web search",
        modules=["services"],
        file_changes=[
            {"path": "backend/app/services/web_search_service.py", "action": "modify", "rationale": "providers"}
        ],
        dependencies=[
            "web_search_service.py should support Google and DuckDuckGo",
            "httpx",
        ],
    )
    assert output.dependencies == ["httpx"]


def test_ui_designer_runs_for_ui_wording(provider: FakeProvider):
    agent = UIDesignerAgent(provider)
    result = agent.design("Build a professional UI for the kanban dashboard")
    assert isinstance(result, UIDesignerOutput)
    assert result.layout_description


def test_ui_designer_runs_for_frontend(provider: FakeProvider):
    agent = UIDesignerAgent(provider)
    result = agent.design("Build a frontend dashboard")
    assert isinstance(result, UIDesignerOutput)
    assert result.layout_description


def test_coder_agent(provider: FakeProvider):
    agent = CoderAgent(provider)
    result = agent.code("Implement feature")
    assert isinstance(result, CoderOutput)
    assert len(result.file_changes) >= 1


def test_coder_repairs_literal_newlines_in_json():
    malformed = (
        '{"summary": "patched", "file_changes": [{"path": "src/a.ts", "line_changes": '
        '[{"start_line": 10, "end_line": 10, "new_content": "const x = 1;\nconst y = 2;"}]}], '
        '"requires_operator_approval": false}'
    )
    provider = FakeProvider(invoke_sequence=[malformed])
    result = CoderAgent(provider).code("Patch src/a.ts")
    assert result.summary == "patched"
    assert "const y = 2" in result.file_changes[0].line_changes[0].new_content


def test_coder_normalizes_llm_field_aliases(provider: FakeProvider):
    provider.set_response_for_keyword(
        "coder",
        {
            "status": "Applied the requested update.",
            "patches": [
                {
                    "file": "backend/app/services/workspace_service.py",
                    "line_changes": [
                        {"start_line": 1, "end_line": 1, "new_content": "# changed\n"}
                    ],
                }
            ],
        },
    )
    result = CoderAgent(provider).code("Implement the update")
    assert result.summary == "Applied the requested update."
    assert result.file_changes[0].path == "backend/app/services/workspace_service.py"


def test_agent_injects_schema_contract(provider: FakeProvider):
    PlannerAgent(provider).plan("Build a REST API for todos")
    _system_prompt, user_prompt = provider.call_log[-1]
    assert "Return JSON matching this schema exactly" in user_prompt
    assert "\"schema_name\": \"PlannerOutput\"" in user_prompt


def test_agent_adds_lmstudio_specific_requirements():
    class FakeLMStudioProvider(FakeProvider):
        pass

    provider = FakeLMStudioProvider()
    PlannerAgent(provider).plan("Build a REST API for todos")
    system_prompt, _user_prompt = provider.call_log[-1]
    assert "LM Studio requirement" in system_prompt


def test_agent_tool_loop_executes_tools_before_final_schema():
    class ToolLoopProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        def invoke_json(self, system_prompt: str, user_prompt: str) -> str:
            self.call_log.append((system_prompt, user_prompt))
            self.calls += 1
            if self.calls == 1:
                return json.dumps(
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "search-1",
                                "name": "web_search",
                                "arguments": {"query": "latest API docs"},
                            }
                        ],
                        "finish_reason": "tool_calls",
                    }
                )
            assert "TOOL_RESULT web_search" in user_prompt
            return json.dumps(
                {
                    "summary": "Grounded plan",
                    "steps": [
                        {
                            "step_id": "1",
                            "title": "Use findings",
                            "description": "Incorporate the fetched documentation context",
                            "acceptance_criteria": ["Plan reflects external docs"],
                        }
                    ],
                    "risks": [],
                }
            )

    class StubToolRuntime:
        def __init__(self) -> None:
            self.executed: list[tuple[str, dict[str, object]]] = []

        def tool_schemas(self) -> list[dict[str, object]]:
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the web",
                        "parameters": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    },
                }
            ]

        def execute(self, tool_name: str, arguments: dict[str, object]) -> str:
            self.executed.append((tool_name, arguments))
            return json.dumps({"results": [{"title": "OpenAI Docs", "url": "https://developers.openai.com/api/docs"}]})

    provider = ToolLoopProvider()
    runtime = StubToolRuntime()
    result = PlannerAgent(provider, tool_runtime=runtime).plan("Research the latest docs before planning")
    assert result.summary == "Grounded plan"
    assert runtime.executed == [("web_search", {"query": "latest API docs"})]


def test_reviewer_agent(provider: FakeProvider):
    agent = ReviewerAgent(provider)
    result = agent.review("Review changes")
    assert isinstance(result, ReviewerOutput)
    assert result.summary


def test_tester_agent(provider: FakeProvider):
    agent = TesterAgent(provider)
    result = agent.test_plan("Validate project")
    assert isinstance(result, TesterOutput)
    assert result.commands or result.dry_run_steps


def test_supervisor_agent(provider: FakeProvider):
    agent = SupervisorAgent(provider)
    result = agent.attest("Reconcile deployment against plan")
    assert isinstance(result, SupervisorOutput)
    assert result.summary


def test_playbook_supervisor_agent(provider: FakeProvider):
    agent = PlaybookSupervisorAgent(provider)
    result = agent.supervise_playbook("Review playbook deployment steps")
    assert isinstance(result, PlaybookSupervisorOutput)
    assert result.summary


def test_command_whitelist_rejects_rm():
    from app.core.exceptions import CommandRejectedError
    from app.tools.command_runner import validate_command

    with pytest.raises(CommandRejectedError):
        validate_command("rm -rf ./")


def test_command_whitelist_allows_git_diff():
    from app.tools.command_runner import validate_command

    validate_command("git diff --stat")


def test_command_whitelist_rejects_curl():
    from app.core.exceptions import CommandRejectedError
    from app.tools.command_runner import validate_command

    with pytest.raises(CommandRejectedError, match="forbidden pattern"):
        validate_command("curl -X POST http://localhost:8000/api/health")


def test_command_whitelist_allows_rg():
    from app.tools.command_runner import validate_command

    validate_command("rg idempotency_key app/")


def test_path_traversal_guard():
    from app.core.exceptions import PathTraversalError
    from app.services.file_service import FileService
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        fs = FileService(Path(tmp))
        with pytest.raises(PathTraversalError):
            fs.read_file("../../../etc/passwd")
