from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AppConfigModel
from app.schemas.api import SettingsResponse, SettingsUpdate


BOOL_KEYS = {
    "ollama_enabled",
    "auto_resume_enabled",
    "stop_on_first_failure",
    "editor_auto_save",
}
INT_KEYS = {
    "provider_timeout_seconds",
    "worker_count",
    "max_review_retries",
    "editor_font_size",
    "editor_tab_size",
    "editor_auto_save_delay_ms",
}


def _parse_value(key: str, value: str) -> Any:
    if key in BOOL_KEYS:
        return value.lower() in ("true", "1", "yes")
    if key in INT_KEYS:
        return int(value)
    return value


class ConfigService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_all(self) -> dict[str, Any]:
        rows = self.db.query(AppConfigModel).all()
        return {row.key: _parse_value(row.key, row.value) for row in rows}

    _DEFAULTS: dict[str, object] = {
        "lmstudio_base_url": "http://192.168.128.70:1234/v1",
        "lmstudio_api_key": "lm-studio",
        "lmstudio_model": "",
        "ollama_base_url": "http://127.0.0.1:11434/v1",
        "ollama_enabled": False,
        "provider_timeout_seconds": 120,
        "auto_resume_enabled": True,
        "worker_count": 1,
        "max_review_retries": 3,
        "stop_on_first_failure": False,
        "model_planner": "qwen2.5-72b-instruct",
        "model_architect": "qwen2.5-coder-32b-instruct",
        "model_ui_designer": "qwen2.5-coder-32b-instruct",
        "model_coder": "qwen2.5-coder-32b-instruct",
        "model_reviewer": "qwen2.5-72b-instruct",
        "model_tester": "qwen2.5-coder-7b-instruct",
        "model_supervisor": "qwen2.5-72b-instruct",
        "editor_font_size": 14,
        "editor_tab_size": 2,
        "editor_auto_save": False,
        "editor_auto_save_delay_ms": 2000,
        "git_author_name": "AI Copilot",
        "git_author_email": "copilot@local.dev",
        "api_token": "dev-token",
        "validation_profiles_json": "{}",
    }

    def get_settings(self) -> SettingsResponse:
        data = self.get_all()
        merged = {**self._DEFAULTS, **data}
        return SettingsResponse(**{k: merged[k] for k in SettingsResponse.model_fields})

    def update_settings(self, update: SettingsUpdate) -> SettingsResponse:
        payload = update.model_dump(exclude_none=True)
        for key, value in payload.items():
            row = self.db.query(AppConfigModel).filter(AppConfigModel.key == key).first()
            str_value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
            if row:
                row.value = str_value
            else:
                self.db.add(AppConfigModel(key=key, value=str_value))
        self.db.commit()
        return self.reload_registry()

    def reload_registry(self) -> SettingsResponse:
        from app.providers.registry import ProviderRegistry

        config = self.get_all()
        ProviderRegistry.get().reload(config)
        merged = {**self._DEFAULTS, **config}
        return SettingsResponse(**{k: merged[k] for k in SettingsResponse.model_fields})


def get_config_value(db: Session, key: str, default: Any = None) -> Any:
    row = db.query(AppConfigModel).filter(AppConfigModel.key == key).first()
    if row is None:
        return default
    return _parse_value(key, row.value)
