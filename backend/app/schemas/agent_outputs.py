from pydantic import BaseModel, Field, field_validator

from app.services.dependency_verifier_service import looks_like_package_name


class PlanStep(BaseModel):
    step_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)


class PlannerOutput(BaseModel):
    summary: str = Field(min_length=1)
    steps: list[PlanStep] = Field(min_length=1)
    risks: list[str] = Field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: str | None = None
    change_request_slug: str | None = None
    hypothesis: str | None = None
    repro_steps: str | None = None

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
    clarification_needed: bool = False
    clarification_question: str | None = None

    @field_validator("dependencies", mode="before")
    @classmethod
    def package_names_only(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if looks_like_package_name(str(item))]

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
    file_changes: list[FileChange] = Field(default_factory=list)
    requires_operator_approval: bool = False


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


class VisualCheckStep(BaseModel):
    action: str = Field(min_length=1)
    selector: str | None = None
    value: str | None = None
    timeout_ms: int = Field(default=8000, ge=500, le=60000)


class VisualCheck(BaseModel):
    url: str = Field(min_length=1)
    description: str = Field(min_length=1)
    expected: str = ""
    steps: list[VisualCheckStep] = Field(default_factory=list)


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


class EntitySpec(BaseModel):
    name: str = Field(min_length=1)
    fields: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)


class EndpointSpec(BaseModel):
    path: str = Field(min_length=1)
    method: str = Field(min_length=1)
    description: str = Field(min_length=1)
    auth_required: bool = False


class StackSpec(BaseModel):
    language: str = Field(min_length=1)
    framework: str = Field(min_length=1)
    database: str = ""
    auth_method: str = ""
    ui_framework: str = ""


class AppDesignOutput(BaseModel):
    app_summary: str = Field(min_length=1)
    entities: list[EntitySpec] = Field(default_factory=list)
    api_endpoints: list[EndpointSpec] = Field(default_factory=list)
    stack: StackSpec
    file_structure: list[str] = Field(min_length=1)
    open_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    clarification_needed: bool = False
    question: str = ""


class DocumentationOutput(BaseModel):
    changelog_entry: str = Field(min_length=1)
    readme_updated: bool = False
    readme_changes: list[LineChange] = Field(default_factory=list)
    change_request_resolution: str = Field(min_length=1)
    architecture_delta: str = Field(min_length=1)


class EntitySpec(BaseModel):
    name: str = Field(min_length=1)
    fields: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)


class EndpointSpec(BaseModel):
    path: str = Field(min_length=1)
    method: str = Field(min_length=1)
    description: str = Field(min_length=1)
    auth_required: bool = False


class StackSpec(BaseModel):
    language: str = Field(min_length=1)
    framework: str = Field(min_length=1)
    database: str = ""
    auth_method: str = ""
    ui_framework: str = ""


class AppDesignOutput(BaseModel):
    app_summary: str = Field(min_length=1)
    entities: list[EntitySpec] = Field(default_factory=list)
    api_endpoints: list[EndpointSpec] = Field(default_factory=list)
    stack: StackSpec
    file_structure: list[str] = Field(min_length=1)
    open_questions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    clarification_needed: bool = False
    clarification_question: str | None = None


class DocumentationOutput(BaseModel):
    summary: str = Field(min_length=1)
    changelog_entry: str = Field(min_length=1)
    change_request_status: str = Field(min_length=1)
    readme_updated: bool = False
    architecture_notes: str = ""
    clarification_needed: bool = False
    clarification_question: str | None = None
