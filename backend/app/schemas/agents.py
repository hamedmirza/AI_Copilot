from pydantic import BaseModel, Field, field_validator


def _as_string_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(v) for v in value]
    return []


class PlanResponse(BaseModel):
    summary: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    assumptions: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)

    @field_validator("steps", "acceptance_criteria", "assumptions", "risks", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _as_string_list(v)


class ModuleSpec(BaseModel):
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


class ArchitectResponse(BaseModel):
    summary: str = Field(min_length=1)
    modules: list[ModuleSpec] = Field(min_length=1)
    files_to_change: list[str] = Field(min_length=1)
    dependencies: list[str] = Field(default_factory=list)

    @field_validator("files_to_change", "dependencies", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _as_string_list(v)


class ComponentSpec(BaseModel):
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)


class UIDesignResponse(BaseModel):
    skip: bool = False
    reason: str | None = None
    components: list[ComponentSpec] = Field(default_factory=list)
    layout_notes: str = ""
    theme_tokens: dict = Field(default_factory=dict)


class FileChange(BaseModel):
    path: str = Field(min_length=1)
    content: str = ""
    operation: str = Field(default="write", pattern="^(write|delete)$")


class LineChange(BaseModel):
    path: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    new_content: str = ""


class CoderResponse(BaseModel):
    summary: str = Field(min_length=1)
    file_changes: list[FileChange] = Field(default_factory=list)
    line_changes: list[LineChange] = Field(default_factory=list)
    requires_operator_approval: bool = False


class ReviewResponse(BaseModel):
    approved: bool
    summary: str = Field(min_length=1)
    issues: list[str] = Field(default_factory=list)
    severity: str = Field(default="low")

    @field_validator("issues", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _as_string_list(v)


class TestResponse(BaseModel):
    passed: bool
    commands: list[str] = Field(min_length=1)
    summary: str = Field(min_length=1)
    failures: list[str] = Field(default_factory=list)

    @field_validator("commands", "failures", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _as_string_list(v)


class SupervisorResponse(BaseModel):
    approved: bool
    summary: str = Field(min_length=1)
    concerns: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)

    @field_validator("concerns", "recommendations", mode="before")
    @classmethod
    def _coerce(cls, v):
        return _as_string_list(v)
