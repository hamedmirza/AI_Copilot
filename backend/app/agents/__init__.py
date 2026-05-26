from app.agents.base import BaseAgent
from app.schemas.agent_outputs import (
    AppDesignOutput,
    ArchitectOutput,
    CoderOutput,
    DocumentationOutput,
    PlannerOutput,
    PlaybookSupervisorOutput,
    ReviewerOutput,
    SupervisorOutput,
    TesterOutput,
    UIDesignerOutput,
)


class AppDesignAgent(BaseAgent):
    prompt_filename = "app_designer.md"
    skill_filename = "app-designer"

    def design_app(self, context: str) -> AppDesignOutput:
        result = self.run(context, AppDesignOutput)
        assert result is not None
        return result


class PlannerAgent(BaseAgent):
    prompt_filename = "planner.md"
    max_tool_rounds = 12

    def plan(self, task_description: str) -> PlannerOutput:
        result = self.run(task_description, PlannerOutput)
        assert result is not None
        return result


class ArchitectAgent(BaseAgent):
    prompt_filename = "architect.md"

    def design(self, context: str) -> ArchitectOutput:
        result = self.run(context, ArchitectOutput)
        assert result is not None
        return result


class UIDesignerAgent(BaseAgent):
    prompt_filename = "ui_designer.md"
    skill_filename = "ui-designer"

    def design(self, context: str) -> UIDesignerOutput:
        result = self.run(context, UIDesignerOutput)
        assert result is not None
        return result


class CoderAgent(BaseAgent):
    prompt_filename = "coder.md"
    max_tool_rounds = 12

    def _provider_output_rules(self) -> str:
        rules = super()._provider_output_rules()
        return (
            f"{rules}"
            "6. Coder requirement: every patch string must be valid inside JSON — escape quotes "
            "and newlines; never paste raw multiline source without \\n escapes.\n"
            "7. Prefer line_changes with narrow start_line/end_line ranges over full_content rewrites.\n"
            "8. If a file is large, emit multiple line_changes instead of one huge string value.\n"
        )

    def code(self, context: str) -> CoderOutput:
        result = self.run(context, CoderOutput)
        assert result is not None
        return result


class ReviewerAgent(BaseAgent):
    prompt_filename = "reviewer.md"

    def review(self, context: str) -> ReviewerOutput:
        result = self.run(context, ReviewerOutput)
        assert result is not None
        return result


class TesterAgent(BaseAgent):
    prompt_filename = "tester.md"

    def test_plan(self, context: str) -> TesterOutput:
        result = self.run(context, TesterOutput)
        assert result is not None
        return result


class SupervisorAgent(BaseAgent):
    prompt_filename = "supervisor.md"

    def attest(self, context: str) -> SupervisorOutput:
        result = self.run(context, SupervisorOutput)
        assert result is not None
        return result


class DocumentationAgent(BaseAgent):
    prompt_filename = "documentation.md"
    skill_filename = "documentation"

    def document(self, context: str) -> DocumentationOutput:
        result = self.run(context, DocumentationOutput)
        assert result is not None
        return result


class PlaybookSupervisorAgent(BaseAgent):
    prompt_filename = "playbook_supervisor.md"
    skill_filename = "playbook-supervisor"

    def supervise_playbook(self, context: str) -> PlaybookSupervisorOutput:
        result = self.run(context, PlaybookSupervisorOutput)
        assert result is not None
        return result
