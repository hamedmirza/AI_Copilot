from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = ROOT_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_api_token: str = "dev-token"
    db_url: str = "sqlite:///./backend/app.db"
    lmstudio_base_url: str = "http://172.10.1.2:1234/v1"
    lmstudio_api_key: str = "lm-studio"
    lmstudio_model: str = ""
    host: str = "0.0.0.0"
    port: int = 8500
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
