from pydantic import BaseModel, Field, field_validator


class PlanStep(BaseModel):
    step_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)


class PlannerOutput(BaseModel):
    summary: str = Field(min_length=1)
    steps: list[PlanStep] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def validate_steps(cls, v: list[PlanStep]) -> list[PlanStep]:
        if not v:
            raise ValueError("At least one step is required")
        return v


class FileBlueprint(BaseModel):
    path: str = Field(min_length=1)
    action: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ArchitectOutput(BaseModel):
    overview: str = Field(min_length=1)
    modules: list[str] = Field(min_length=1)
    file_changes: list[FileBlueprint] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)

    @field_validator("file_changes")
    @classmethod
    def validate_files(cls, v: list[FileBlueprint]) -> list[FileBlueprint]:
        if not v:
            raise ValueError("At least one file change is required")
        return v


class UIComponentSpec(BaseModel):
    name: str = Field(min_length=1)
    component_type: str = Field(min_length=1)
    props: dict[str, str] = Field(default_factory=dict)


class UIDesignerOutput(BaseModel):
    layout_description: str = Field(min_length=1)
    components: list[UIComponentSpec] = Field(min_length=1)
    styling_notes: str = Field(min_length=1)
    accessibility_notes: list[str] = Field(default_factory=list)


class LineChange(BaseModel):
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    new_content: str


class FileChange(BaseModel):
    path: str = Field(min_length=1)
    line_changes: list[LineChange] = Field(default_factory=list)
    full_content: str | None = None


class CoderOutput(BaseModel):
    summary: str = Field(min_length=1)
    file_changes: list[FileChange] = Field(min_length=1)
    requires_operator_approval: bool = False

    @field_validator("file_changes")
    @classmethod
    def validate_changes(cls, v: list[FileChange]) -> list[FileChange]:
        if not v:
            raise ValueError("At least one file change is required")
        return v


class ReviewIssue(BaseModel):
    severity: str = Field(min_length=1)
    file_path: str = Field(min_length=1)
    message: str = Field(min_length=1)


class ReviewerOutput(BaseModel):
    approved: bool
    summary: str = Field(min_length=1)
    issues: list[ReviewIssue] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class TestCommand(BaseModel):
    command: str = Field(min_length=1)
    description: str = Field(min_length=1)


class VisualCheck(BaseModel):
    url: str = Field(min_length=1)
    description: str = Field(min_length=1)
    expected: str = Field(min_length=1)


class TesterOutput(BaseModel):
    passed: bool
    summary: str = Field(min_length=1)
    dry_run_steps: list[TestCommand] = Field(default_factory=list)
    visual_checks: list[VisualCheck] = Field(default_factory=list)
    visual_checks_skip_reason: str | None = None
    commands: list[TestCommand] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @field_validator("commands")
    @classmethod
    def validate_commands(cls, v: list[TestCommand]) -> list[TestCommand]:
        return v


class PlanGap(BaseModel):
    step_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class DocUpdate(BaseModel):
    path: str = Field(min_length=1)
    content: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class SupervisorOutput(BaseModel):
    approved: bool
    summary: str = Field(min_length=1)
    plan_gaps: list[PlanGap] = Field(default_factory=list)
    doc_updates: list[DocUpdate] = Field(default_factory=list)


class PlaybookSupervisorOutput(BaseModel):
    approved: bool
    summary: str = Field(min_length=1)
    safety_concerns: list[str] = Field(default_factory=list)
    required_changes: list[str] = Field(default_factory=list)
