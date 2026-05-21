from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from app.core.enums import PipelineStage, ProviderStatus
from app.providers.base import BaseProvider
from app.providers.fake import FakeProvider
from app.providers.lmstudio import LMStudioProvider
from app.providers.ollama import OllamaProvider


@dataclass
class HealthResult:
    status: str
    model_count: int
    error: str | None
    models: list[str]


class ProviderRegistry:
    _instance: Optional["ProviderRegistry"] = None

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self.fake_provider: FakeProvider | None = None
        self._lmstudio: LMStudioProvider | None = None
        self._ollama: OllamaProvider | None = None

    @classmethod
    def get(cls) -> "ProviderRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def reload(self, config: dict[str, Any]) -> None:
        self._config = config
        self._lmstudio = None
        self._ollama = None

    def _timeout(self) -> int:
        return int(self._config.get("provider_timeout_seconds", 120))

    def _lmstudio_provider(self) -> LMStudioProvider:
        if self.fake_provider is not None:
            return self.fake_provider  # type: ignore[return-value]
        if self._lmstudio is None:
            self._lmstudio = LMStudioProvider(
                base_url=str(self._config.get("lmstudio_base_url", "http://127.0.0.1:1234/v1")),
                api_key=str(self._config.get("lmstudio_api_key", "lm-studio")),
                model=str(self._config.get("lmstudio_model", "")),
                timeout_seconds=self._timeout(),
            )
        return self._lmstudio

    def _ollama_provider(self) -> OllamaProvider:
        if self._ollama is None:
            self._ollama = OllamaProvider(
                base_url=str(self._config.get("ollama_base_url", "http://127.0.0.1:11434/v1")),
                model=str(self._config.get("lmstudio_model", "")),
                timeout_seconds=self._timeout(),
            )
        return self._ollama

    def resolve_stage(self, stage: PipelineStage | str, model: str | None = None) -> BaseProvider:
        if self.fake_provider is not None:
            return self.fake_provider
        stage_key = stage.value if isinstance(stage, PipelineStage) else str(stage)
        model_map = {
            "planner": "model_planner",
            "architect": "model_architect",
            "ui_designer": "model_ui_designer",
            "coder": "model_coder",
            "reviewer": "model_reviewer",
            "tester": "model_tester",
            "supervisor": "model_supervisor",
        }
        selected = model or str(
            self._config.get(model_map.get(stage_key, ""), "")
            or self._config.get("lmstudio_model", "")
        )
        if self._config.get("ollama_enabled"):
            return OllamaProvider(
                base_url=str(self._config.get("ollama_base_url", "http://127.0.0.1:11434/v1")),
                model=selected,
                timeout_seconds=self._timeout(),
            )
        return LMStudioProvider(
            base_url=str(self._config.get("lmstudio_base_url", "http://127.0.0.1:1234/v1")),
            api_key=str(self._config.get("lmstudio_api_key", "lm-studio")),
            model=selected,
            timeout_seconds=self._timeout(),
        )

    _AGENT_MODEL_KEYS = (
        "model_planner",
        "model_architect",
        "model_ui_designer",
        "model_coder",
        "model_reviewer",
        "model_tester",
        "model_supervisor",
    )

    def _configured_agent_models(self) -> list[str]:
        return [
            str(self._config.get(key, "")).strip()
            for key in self._AGENT_MODEL_KEYS
            if str(self._config.get(key, "")).strip()
        ]

    def health_lmstudio(self) -> HealthResult:
        if self.fake_provider is not None:
            return HealthResult(status="healthy", model_count=1, error=None, models=["fake-model"])
        provider = self._lmstudio_provider()
        health = provider.healthcheck()
        models = provider.list_models()
        status = health.status
        detail = health.detail

        if status != ProviderStatus.UNREACHABLE and models:
            configured = str(self._config.get("lmstudio_model", "")).strip()
            agent_models = self._configured_agent_models()
            if configured and configured in models:
                status = ProviderStatus.HEALTHY
                detail = "LM Studio reachable and configured model is listed."
            elif agent_models and all(model in models for model in agent_models):
                status = ProviderStatus.HEALTHY
                detail = "LM Studio reachable and all agent models are available."
            elif agent_models:
                missing = [model for model in agent_models if model not in models]
                status = ProviderStatus.DEGRADED
                detail = f"LM Studio reachable but agent models not found: {', '.join(missing)}"
            elif configured:
                status = ProviderStatus.DEGRADED
                detail = f"LM Studio reachable but configured model '{configured}' not listed."
            else:
                status = ProviderStatus.DEGRADED
                detail = "LM Studio reachable. Select agent models in Settings."

        error = detail if status != ProviderStatus.HEALTHY else None
        return HealthResult(
            status=status.value,
            model_count=len(models),
            error=error,
            models=models,
        )

    def list_models(self) -> list[str]:
        if self.fake_provider is not None:
            return self.fake_provider.list_models()
        if self._config.get("ollama_enabled"):
            return self._ollama_provider().list_models()
        return self._lmstudio_provider().list_models()


def set_provider_override(provider: BaseProvider | None) -> None:
    registry = ProviderRegistry.get()
    registry.fake_provider = provider if isinstance(provider, FakeProvider) else None


def reload_from_db(db) -> None:
    from app.services.config_service import ConfigService

    ConfigService(db).reload_registry()
