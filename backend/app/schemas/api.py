from pydantic import BaseModel, Field


class SettingsResponse(BaseModel):
    lmstudio_base_url: str
    lmstudio_api_key: str
    lmstudio_model: str
    ollama_base_url: str
    ollama_enabled: bool
    provider_timeout_seconds: int
    auto_resume_enabled: bool
    worker_count: int
    max_review_retries: int
    stop_on_first_failure: bool
    model_planner: str
    model_architect: str
    model_ui_designer: str
    model_coder: str
    model_reviewer: str
    model_tester: str
    model_supervisor: str
    editor_font_size: int
    editor_tab_size: int
    editor_auto_save: bool
    editor_auto_save_delay_ms: int
    git_author_name: str
    git_author_email: str
    api_token: str
    validation_profiles_json: str


class SettingsUpdate(BaseModel):
    lmstudio_base_url: str | None = None
    lmstudio_api_key: str | None = None
    lmstudio_model: str | None = None
    ollama_base_url: str | None = None
    ollama_enabled: bool | None = None
    provider_timeout_seconds: int | None = None
    auto_resume_enabled: bool | None = None
    worker_count: int | None = None
    max_review_retries: int | None = None
    stop_on_first_failure: bool | None = None
    model_planner: str | None = None
    model_architect: str | None = None
    model_ui_designer: str | None = None
    model_coder: str | None = None
    model_reviewer: str | None = None
    model_tester: str | None = None
    model_supervisor: str | None = None
    editor_font_size: int | None = None
    editor_tab_size: int | None = None
    editor_auto_save: bool | None = None
    editor_auto_save_delay_ms: int | None = None
    git_author_name: str | None = None
    git_author_email: str | None = None
    api_token: str | None = None
    validation_profiles_json: str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1)
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
    run_count: int = 0
    created_at: str
    updated_at: str


class TaskCreate(BaseModel):
    project_id: str
    description: str = Field(min_length=10)
    validation_profile: str = "python"
    use_scout: bool = False


class TaskResponse(BaseModel):
    id: str
    project_id: str
    description: str
    validation_profile: str
    use_scout: bool
    created_at: str


class RunResponse(BaseModel):
    id: str
    project_id: str
    task_id: str
    status: str
    current_stage: str | None
    workspace_path: str | None
    review_attempts: int
    error_message: str | None
    created_at: str
    updated_at: str


class RunEventResponse(BaseModel):
    id: int
    event_type: str
    stage: str | None
    severity: str
    message: str
    payload: dict
    created_at: str


class ArtifactResponse(BaseModel):
    id: int
    artifact_type: str
    content: dict
    created_at: str


class ApproveRequest(BaseModel):
    comment: str = ""


class RejectRequest(BaseModel):
    reason: str = Field(min_length=1)


class FileWriteRequest(BaseModel):
    content: str


class FileCreateRequest(BaseModel):
    path: str
    content: str = ""
    is_directory: bool = False


class GitStageRequest(BaseModel):
    paths: list[str]


class GitCommitRequest(BaseModel):
    message: str = Field(min_length=1)


class GitCheckoutRequest(BaseModel):
    branch: str
