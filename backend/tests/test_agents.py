import json
from pathlib import Path

import pytest

from app.agents import (
    ArchitectAgent,
    CoderAgent,
    PlannerAgent,
    PlaybookSupervisorAgent,
    ReviewerAgent,
    TesterAgent,
    UIDesignerAgent,
)
from app.providers.fake import FakeProvider
from app.schemas.agent_outputs import (
    ArchitectOutput,
    CoderOutput,
    PlannerOutput,
    PlaybookSupervisorOutput,
    ReviewerOutput,
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


def test_architect_agent(provider: FakeProvider):
    agent = ArchitectAgent(provider)
    result = agent.design("Build API")
    assert isinstance(result, ArchitectOutput)
    assert result.overview
    assert len(result.file_changes) >= 1


def test_ui_designer_skips_non_frontend(provider: FakeProvider):
    agent = UIDesignerAgent(provider)
    result = agent.design("Build a CLI tool")
    assert result is None


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


def test_reviewer_agent(provider: FakeProvider):
    agent = ReviewerAgent(provider)
    result = agent.review("Review changes")
    assert isinstance(result, ReviewerOutput)
    assert result.summary


def test_tester_agent(provider: FakeProvider):
    agent = TesterAgent(provider)
    result = agent.test_plan("Validate project")
    assert isinstance(result, TesterOutput)
    assert len(result.commands) >= 1


def test_playbook_supervisor_agent(provider: FakeProvider):
    agent = PlaybookSupervisorAgent(provider)
    result = agent.supervise("Review playbook deployment steps")
    assert isinstance(result, PlaybookSupervisorOutput)
    assert result.summary


def test_command_whitelist_rejects_rm():
    from app.core.exceptions import CommandRejectedError
    from app.tools.command_runner import validate_command

    with pytest.raises(CommandRejectedError):
        validate_command("rm -rf ./")


def test_path_traversal_guard():
    from app.core.exceptions import PathTraversalError
    from app.services.file_service import FileService
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        fs = FileService(Path(tmp))
        with pytest.raises(PathTraversalError):
            fs.read_file("../../../etc/passwd")
