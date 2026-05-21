from pydantic import BaseModel, Field

from app.core.enums import ProviderStatus


class ProviderHealthResponse(BaseModel):
    provider: str = "lmstudio"
    status: ProviderStatus
    detail: str = ""
    model: str = ""
    model_count: int = 0
    error: str | None = None
    models: list[str] = Field(default_factory=list)
