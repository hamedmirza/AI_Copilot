from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.defaults import DEFAULT_VALIDATION_PROFILES
from app.db.models import AppConfigModel
from app.schemas.api import SettingsResponse, SettingsUpdate
from app.services.provider_switch import ROLE_KEYS


BOOL_KEYS = {
    "ollama_enabled",
    "nothink_default",
    "auto_resume_enabled",
    "stop_on_first_failure",
    "editor_auto_save",
    "learning_auto_trial_enabled",
    "learning_auto_promote_enabled",
    "learning_unknown_failure_autopromote_enabled",
}
JSON_DICT_KEYS = {
    "lmstudio_role_models_json",
    "ollama_role_models_json",
}
INT_KEYS = {
    "provider_timeout_seconds",
    "worker_count",
    "max_review_retries",
    "chat_history_limit",
    "chat_max_context_tokens",
    "chat_max_output_tokens",
    "editor_font_size",
    "editor_tab_size",
    "editor_auto_save_delay_ms",
    "learning_min_trial_runs",
}
FLOAT_KEYS = {
    "learning_min_success_rate_delta_pct",
    "learning_max_harmful_rate_pct",
    "learning_min_confidence",
}


def _parse_value(key: str, value: str) -> Any:
    if key in BOOL_KEYS:
        return value.lower() in ("true", "1", "yes")
    if key in INT_KEYS:
        return int(value)
    if key in FLOAT_KEYS:
        return float(value)
    if key in JSON_DICT_KEYS:
        try:
            data = json.loads(value or "{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}
    return value


class ConfigService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_all(self) -> dict[str, Any]:
        rows = self.db.query(AppConfigModel).all()
        return {row.key: _parse_value(row.key, row.value) for row in rows}

    _DEFAULTS: dict[str, object] = {
        "lmstudio_base_url": "http://172.10.1.2:1234/v1",
        "lmstudio_api_key": "lm-studio",
        "lmstudio_model": "",
        "ollama_base_url": "http://172.10.1.2:11434/v1",
        "ollama_model": "qwen3.6:latest",
        "ollama_enabled": False,
        "lmstudio_role_models_json": {},
        "ollama_role_models_json": {},
        "provider_timeout_seconds": 300,
        "auto_resume_enabled": True,
        "worker_count": 1,
        "max_review_retries": 3,
        "chat_history_limit": 50,
        "chat_max_context_tokens": 32768,
        "chat_max_output_tokens": 2048,
        "nothink_default": True,
        "stop_on_first_failure": True,
        "model_planner": "qwen3.6-27b",
        "model_architect": "qwen3.6-27b",
        "model_ui_designer": "qwen3.6-27b",
        "model_coder": "qwen3.6-27b",
        "model_reviewer": "qwen3.6-27b",
        "model_tester": "qwen3.6-27b",
        "model_supervisor": "qwen3.6-27b",
        "model_chat": "qwen3.6-27b",
        "model_chat_agent": "qwen3.6-27b",
        "model_chat_planner": "qwen3.6-27b",
        "model_chat_debugger": "qwen3.6-27b",
        "model_chat_architect": "qwen3.6-27b",
        "chat_modes_json": "[]",
        "editor_font_size": 14,
        "editor_tab_size": 2,
        "editor_auto_save": False,
        "editor_auto_save_delay_ms": 2000,
        "git_author_name": "AI Copilot",
        "git_author_email": "copilot@local.dev",
        "api_token": "dev-token",
        "validation_profiles_json": json.dumps(DEFAULT_VALIDATION_PROFILES),
        "learning_auto_trial_enabled": True,
        "learning_auto_promote_enabled": True,
        "learning_min_trial_runs": 3,
        "learning_min_success_rate_delta_pct": 10.0,
        "learning_max_harmful_rate_pct": 34.0,
        "learning_min_confidence": 0.65,
        "learning_unknown_failure_autopromote_enabled": False,
    }

    def get_settings(self) -> SettingsResponse:
        from app.providers.ollama import normalize_ollama_base_url

        data = self.get_all()
        merged = {**self._DEFAULTS, **data}
        if merged.get("ollama_base_url"):
            merged["ollama_base_url"] = normalize_ollama_base_url(str(merged["ollama_base_url"]))
        for snap_key in JSON_DICT_KEYS:
            if not isinstance(merged.get(snap_key), dict):
                merged[snap_key] = {}
        return SettingsResponse(**{k: merged[k] for k in SettingsResponse.model_fields})

    def update_settings(self, update: SettingsUpdate) -> SettingsResponse:
        payload = update.model_dump(exclude_none=True)
        if "provider_timeout_seconds" in payload:
            payload["provider_timeout_seconds"] = max(
                30,
                min(900, int(payload["provider_timeout_seconds"])),
            )
        if "chat_max_context_tokens" in payload:
            payload["chat_max_context_tokens"] = max(
                2048,
                min(200_000, int(payload["chat_max_context_tokens"])),
            )
        if "chat_max_output_tokens" in payload:
            payload["chat_max_output_tokens"] = max(
                256,
                min(32_768, int(payload["chat_max_output_tokens"])),
            )
        if "chat_history_limit" in payload:
            payload["chat_history_limit"] = max(1, min(500, int(payload["chat_history_limit"])))
        if "learning_min_trial_runs" in payload:
            payload["learning_min_trial_runs"] = max(1, min(100, int(payload["learning_min_trial_runs"])))
        if "learning_min_success_rate_delta_pct" in payload:
            payload["learning_min_success_rate_delta_pct"] = max(
                0.0, min(100.0, float(payload["learning_min_success_rate_delta_pct"]))
            )
        if "learning_max_harmful_rate_pct" in payload:
            payload["learning_max_harmful_rate_pct"] = max(
                0.0, min(100.0, float(payload["learning_max_harmful_rate_pct"]))
            )
        if "learning_min_confidence" in payload:
            payload["learning_min_confidence"] = max(0.0, min(1.0, float(payload["learning_min_confidence"])))
        if "ollama_base_url" in payload and payload["ollama_base_url"] is not None:
            from app.providers.ollama import normalize_ollama_base_url

            payload["ollama_base_url"] = normalize_ollama_base_url(str(payload["ollama_base_url"]))
        sync_role_models = bool(payload.pop("sync_role_models", False))
        if "ollama_enabled" in payload or sync_role_models:
            from app.services.provider_switch import (
                build_provider_switch_updates,
                sync_active_provider_role_models,
            )

            current = self.get_all()
            old_provider = "ollama" if current.get("ollama_enabled") else "lmstudio"
            new_provider = (
                "ollama" if payload["ollama_enabled"] else "lmstudio"
                if "ollama_enabled" in payload
                else old_provider
            )
            if old_provider != new_provider:
                payload.update(build_provider_switch_updates(current, from_provider=old_provider, to_provider=new_provider))
            elif sync_role_models:
                payload.update(sync_active_provider_role_models(current, new_provider))
        role_overrides = {key: str(payload[key]).strip() for key in ROLE_KEYS if key in payload and str(payload[key]).strip()}
        if role_overrides:
            current = self.get_all()
            active_provider = "ollama" if payload.get("ollama_enabled", current.get("ollama_enabled")) else "lmstudio"
            snapshot_key = f"{active_provider}_role_models_json"
            snapshot = current.get(snapshot_key)
            if not isinstance(snapshot, dict):
                snapshot = {}
            payload[snapshot_key] = {**snapshot, **role_overrides}
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
        from app.providers.ollama import normalize_ollama_base_url

        config = self.get_all()
        ProviderRegistry.get().reload(config)
        merged = {**self._DEFAULTS, **config}
        if merged.get("ollama_base_url"):
            merged["ollama_base_url"] = normalize_ollama_base_url(str(merged["ollama_base_url"]))
        for snap_key in JSON_DICT_KEYS:
            if not isinstance(merged.get(snap_key), dict):
                merged[snap_key] = {}
        return SettingsResponse(**{k: merged[k] for k in SettingsResponse.model_fields})

    def reset_to_defaults(self) -> SettingsResponse:
        self.db.query(AppConfigModel).delete()
        self.db.commit()
        for key, value in self._DEFAULTS.items():
            str_value = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
            self.db.add(AppConfigModel(key=key, value=str_value))
        self.db.commit()
        return self.reload_registry()


def get_config_value(db: Session, key: str, default: Any = None) -> Any:
    row = db.query(AppConfigModel).filter(AppConfigModel.key == key).first()
    if row is None:
        return default
    return _parse_value(key, row.value)
