import json
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    source_repo_spec: str = Field(min_length=1)
    validation_profile: str = "python"
    protected_files: list[str] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    source_repo_spec: str | None = None
    validation_profile: str | None = None
    protected_files: list[str] | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str
    source_repo_spec: str
    validation_profile: str
    protected_files: list[str]
    workspace_path: str | None = None
    created_at: datetime
    updated_at: datetime
    run_count: int = 0


class TaskCreate(BaseModel):
    project_id: str
    description: str = Field(min_length=10)
    validation_profile: str | None = None
    use_scout: bool = False


class TaskResponse(BaseModel):
    id: str
    project_id: str
    description: str
    validation_profile: str
    use_scout: bool
    created_at: datetime


class RunResponse(BaseModel):
    id: str
    project_id: str
    task_id: str
    status: str
    current_stage: str | None
    review_attempts: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    events: list[dict] = Field(default_factory=list)
    artifacts: list[dict] = Field(default_factory=list)


class RunActionRequest(BaseModel):
    reason: str | None = None


class BlockerResponse(BaseModel):
    run_id: str
    status: str
    current_stage: str | None
    error_message: str | None


class ReleaseReadinessResponse(BaseModel):
    ready: bool
    blockers: list[str] = Field(default_factory=list)


class LessonCreate(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)


class LessonResponse(BaseModel):
    id: int
    project_id: str
    title: str
    content: str
    run_id: str | None
    created_at: datetime


class PlaybookCreate(BaseModel):
    name: str = Field(min_length=1)
    content: dict


class PlaybookResponse(BaseModel):
    id: int
    project_id: str
    name: str
    content: dict
    status: str
    created_at: datetime


class OnboardingStatusResponse(BaseModel):
    completed: bool
    has_projects: bool
    project_count: int
