from pydantic import BaseModel, Field, field_validator


class AppConfigSchema(BaseModel):
    lmstudio_base_url: str
    lmstudio_api_key: str = "lm-studio"
    lmstudio_model: str = ""
    ollama_base_url: str = "http://172.10.1.2:11434/v1"
    ollama_enabled: bool = False
    provider_timeout_seconds: int = 300
    auto_resume_enabled: bool = True
    worker_count: int = 1
    max_review_retries: int = 3
    stop_on_first_failure: bool = True
    model_planner: str = "qwen2.5-72b-instruct"
    model_architect: str = "qwen2.5-coder-32b-instruct"
    model_ui_designer: str = "qwen2.5-coder-32b-instruct"
    model_coder: str = "qwen2.5-coder-32b-instruct"
    model_reviewer: str = "qwen2.5-72b-instruct"
    model_tester: str = "qwen2.5-coder-7b-instruct"
    model_supervisor: str = "qwen2.5-72b-instruct"
    validation_profiles_json: str = "{}"
    git_author_name: str = ""
    git_author_email: str = ""
    api_token: str = "dev-token"
    onboarding_completed: bool = False


class AppConfigUpdate(BaseModel):
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
    validation_profiles_json: str | None = None
    git_author_name: str | None = None
    git_author_email: str | None = None
    api_token: str | None = None
    onboarding_completed: bool | None = None
