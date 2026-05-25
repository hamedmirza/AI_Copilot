from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from app.core.enums import PipelineStage, ProviderStatus
from app.providers.base import BaseProvider
from app.providers.fake import FakeProvider
from app.providers.lmstudio import LMStudioProvider
from app.providers.ollama import OllamaProvider, normalize_ollama_base_url, probe_ollama_endpoints
from app.services.lmstudio_catalog import LMStudioCatalog, SETTINGS_ROLE_KEYS

logger = logging.getLogger(__name__)


@dataclass
class HealthResult:
    status: str
    model_count: int
    error: str | None
    models: list[str]
    resources_pressure: str | None = None
    loaded_size_gb: float | None = None
    recommendations: dict[str, str] | None = None


@dataclass
class ModelsListResult:
    models: list[str]
    catalog: list[dict[str, object]]
    recommendations: dict[str, str]
    resources: dict[str, object]


class ProviderRegistry:
    _instance: Optional["ProviderRegistry"] = None
    _CHAT_MODEL_KEYS = {
        "general": "model_chat",
        "agent": "model_chat_agent",
        "planner": "model_chat_planner",
        "debugger": "model_chat_debugger",
        "architect": "model_chat_architect",
    }
    _AUTO_MODEL_PATTERNS = {
        "general": [
            "qwen2.5-72b-instruct",
            "qwen3",
            "gpt-oss",
            "instruct",
        ],
        "agent": [
            "qwen2.5-coder",
            "qwen3-coder",
            "coder",
        ],
    }

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self.fake_provider: FakeProvider | None = None
        self._lmstudio: LMStudioProvider | None = None
        self._ollama: OllamaProvider | None = None
        self._catalog_cache: LMStudioCatalog | None = None

    @classmethod
    def get(cls) -> "ProviderRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def reload(self, config: dict[str, Any]) -> None:
        self._config = config
        self._lmstudio = None
        self._ollama = None
        self._catalog_cache = None

    def active_provider(self) -> str:
        return "ollama" if self._config.get("ollama_enabled") else "lmstudio"

    def _timeout(self) -> int:
        return int(self._config.get("provider_timeout_seconds", 300))

    def _lmstudio_provider(self) -> LMStudioProvider:
        if self.fake_provider is not None:
            return self.fake_provider  # type: ignore[return-value]
        if self._lmstudio is None:
            self._lmstudio = LMStudioProvider(
                base_url=str(self._config.get("lmstudio_base_url", "http://172.10.1.2:1234/v1")),
                api_key=str(self._config.get("lmstudio_api_key", "lm-studio")),
                model=str(self._config.get("lmstudio_model", "")),
                timeout_seconds=self._timeout(),
            )
        return self._lmstudio

    def _ollama_provider(self) -> OllamaProvider:
        if self._ollama is None:
            self._ollama = OllamaProvider(
                base_url=str(self._config.get("ollama_base_url", "http://172.10.1.2:11434/v1")),
                model=str(self._config.get("ollama_model", "")),
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
            "chat": "model_chat",
            "general": "model_chat",
            "agent": "model_chat_agent",
            "planner_chat": "model_chat_planner",
            "debugger": "model_chat_debugger",
            "architect_chat": "model_chat_architect",
        }
        default_model_key = "ollama_model" if self._config.get("ollama_enabled") else "lmstudio_model"
        selected = model or str(
            self._config.get(model_map.get(stage_key, ""), "")
            or self._config.get(default_model_key, "")
        )
        selected = self._resolve_runnable_model(stage_key, selected)
        if not self._config.get("ollama_enabled"):
            provider = self._provider_for_model(selected)
            if isinstance(provider, LMStudioProvider):
                catalog = self.get_lmstudio_catalog()
                prepared = provider.prepare_model(
                    selected,
                    self._stage_mode(stage_key),
                    catalog=catalog,
                    allow_unload=True,
                )
                if prepared != selected:
                    logger.warning(
                        "Adjusted stage %s model from %r to %r based on LM Studio catalog/load",
                        stage_key,
                        selected,
                        prepared,
                    )
                    return provider.with_overrides(model_name=prepared)
            return provider
        return self._provider_for_model(selected)

    def _stage_mode(self, stage_key: str) -> str:
        return {
            "planner_chat": "planner",
            "debugger": "debugger",
            "architect_chat": "architect",
            "agent": "agent",
            "general": "general",
            "chat": "general",
        }.get(stage_key, stage_key)

    def _resolve_runnable_model(self, stage_key: str, selected: str) -> str:
        selected = str(selected or "").strip()
        if not selected:
            default_key = "ollama_model" if self._config.get("ollama_enabled") else "lmstudio_model"
            selected = str(self._config.get(default_key, "")).strip()
        available = self.list_models()
        if not available or not selected:
            return selected
        if selected in available:
            if not self._config.get("ollama_enabled"):
                catalog = self.get_lmstudio_catalog()
                if catalog is not None:
                    resolved, _unload = catalog.resolve_runnable(selected, self._stage_mode(stage_key))
                    if resolved:
                        return resolved
            return selected
        if self._model_listed(selected, available):
            return selected
        mode = self._stage_mode(stage_key)
        matched = self._first_matching_model(available, self._auto_model_patterns(mode))
        if matched:
            logger.warning(
                "Model %r is not available for stage %s; using %r instead",
                selected,
                stage_key,
                matched,
            )
            return matched
        default_key = "ollama_model" if self._config.get("ollama_enabled") else "lmstudio_model"
        configured_default = str(self._config.get(default_key, "")).strip()
        if configured_default and configured_default in available:
            logger.warning(
                "Model %r is not available for stage %s; using default %r instead",
                selected,
                stage_key,
                configured_default,
            )
            return configured_default
        fallback = available[0]
        logger.warning(
            "Model %r is not available for stage %s; using first catalog model %r instead",
            selected,
            stage_key,
            fallback,
        )
        return fallback

    def get_lmstudio_catalog(self, *, refresh: bool = False) -> LMStudioCatalog | None:
        if self.fake_provider is not None or self._config.get("ollama_enabled"):
            return None
        if self._catalog_cache is not None and not refresh:
            return self._catalog_cache
        catalog = self._lmstudio_provider().fetch_catalog()
        if catalog is not None:
            self._catalog_cache = catalog
        return catalog

    def resolve_chat_provider(self, mode: str, model_override: str | None = None) -> BaseProvider:
        if self.fake_provider is not None:
            return self.fake_provider
        mode_key = str(mode or "general").strip().lower()
        requested = str(model_override or "").strip()
        if not requested or requested.lower() == "auto":
            selected = self.resolve_auto_chat_model(mode_key)
        elif self._config.get("ollama_enabled"):
            selected = requested
            available = self.list_models()
            if available and selected not in available:
                fallback = self.resolve_auto_chat_model(mode_key)
                logger.warning(
                    "Chat model override %r is not available on Ollama; using %r instead",
                    requested,
                    fallback,
                )
                selected = fallback
        else:
            selected = requested
            catalog = self.get_lmstudio_catalog()
            if catalog is not None:
                if selected not in catalog.by_id():
                    fallback = self.resolve_auto_chat_model(mode_key)
                    logger.warning(
                        "Chat model override %r is not in the LM Studio catalog; using %r instead",
                        selected,
                        fallback,
                    )
                    selected = fallback
                else:
                    selected, _unload = catalog.resolve_runnable(selected, mode_key)
            else:
                available = self.list_models()
                if available and selected not in available:
                    selected = self.resolve_auto_chat_model(mode_key)
                    logger.warning(
                        "Chat model override %r is not in the LM Studio catalog; using %r instead",
                        requested,
                        selected,
                    )
        if not self._config.get("ollama_enabled"):
            provider = self._provider_for_model(selected)
            if isinstance(provider, LMStudioProvider):
                catalog = self.get_lmstudio_catalog()
                prepared = provider.prepare_model(
                    selected,
                    mode_key,
                    catalog=catalog,
                    allow_unload=False,
                )
                if prepared != selected:
                    logger.warning(
                        "Adjusted chat model from %r to %r for mode %r based on LM Studio memory heuristics",
                        selected,
                        prepared,
                        mode_key,
                    )
                    return provider.with_overrides(model_name=prepared)
            return provider
        return self._provider_for_model(selected)

    def resolve_auto_chat_model(self, mode: str) -> str:
        mode_key = str(mode or "general").strip().lower()
        if self._config.get("ollama_enabled"):
            available = self.list_models()
            if available:
                matched = self._first_matching_model(available, self._auto_model_patterns(mode_key))
                if matched:
                    return matched
                configured = str(self._config.get("ollama_model", "")).strip()
                if configured and configured in available:
                    return configured
                configured_chat = self._configured_chat_model(mode_key)
                if configured_chat and configured_chat in available:
                    return configured_chat
                return available[0]
            configured = str(self._config.get("ollama_model", "")).strip()
            if configured:
                return configured
            return self._configured_chat_model(mode_key)
        catalog = self.get_lmstudio_catalog()
        if catalog is not None:
            configured = self._configured_chat_model(mode_key)
            selected, _unload = catalog.resolve_runnable(configured or "auto", mode_key)
            if selected:
                return selected
        available = self.list_models()
        if not available and not self._config.get("ollama_enabled"):
            available = self.health_lmstudio().models
        if available:
            matched = self._first_matching_model(available, self._auto_model_patterns(mode_key))
            if matched:
                return matched
            configured = self._configured_chat_model(mode_key)
            if configured and configured in available:
                return configured
            fallback = str(self._config.get("lmstudio_model", "")).strip()
            if fallback and fallback in available:
                return fallback
            return available[0]
        configured = self._configured_chat_model(mode_key)
        if configured:
            return configured
        return str(self._config.get("lmstudio_model", "")).strip()

    def resolve_memory_fallback_model(self, mode: str, current_model: str) -> str | None:
        catalog = self.get_lmstudio_catalog(refresh=True)
        if catalog is None:
            return None
        fallback = catalog.pick_best(str(mode or "general").strip().lower())
        if not fallback or fallback == current_model:
            return None
        return fallback

    def list_models_detailed_for_provider(self, provider: str) -> ModelsListResult:
        saved = dict(self._config)
        temp = {**saved, "ollama_enabled": provider == "ollama"}
        self.reload(temp)
        try:
            return self.list_models_detailed()
        finally:
            self.reload(saved)

    def list_models_detailed(self) -> ModelsListResult:
        if self.fake_provider is not None:
            models = self.fake_provider.list_models()
            return ModelsListResult(
                models=models,
                catalog=[],
                recommendations={},
                resources={"pressure": "ok", "loaded_count": 0, "loaded_size_gb": 0.0},
            )
        if self._config.get("ollama_enabled"):
            return self._list_ollama_models_detailed()
        catalog = self.get_lmstudio_catalog(refresh=True)
        if catalog is None:
            models = self.list_models()
            return ModelsListResult(
                models=models,
                catalog=[],
                recommendations={},
                resources={"pressure": "ok", "loaded_count": 0, "loaded_size_gb": 0.0},
            )
        resources = catalog.resources()
        return ModelsListResult(
            models=catalog.ids(),
            catalog=[
                {
                    "id": item.id,
                    "state": item.state,
                    "loaded": item.is_loaded,
                    "size_gb": item.size_gb,
                    "tool_use": item.tool_use,
                    "params": item.params_string,
                    "quantization": item.quantization,
                    "loaded_instances": item.loaded_instances,
                }
                for item in catalog.models
            ],
            recommendations=catalog.recommendations(),
            resources={
                "pressure": resources.pressure,
                "loaded_count": resources.loaded_count,
                "loaded_size_gb": resources.loaded_size_gb,
                "catalog_count": resources.catalog_count,
            },
        )

    def _provider_for_model(self, selected: str) -> BaseProvider:
        if self._config.get("ollama_enabled"):
            return OllamaProvider(
                base_url=str(self._config.get("ollama_base_url", "http://172.10.1.2:11434/v1")),
                model=selected,
                timeout_seconds=self._timeout(),
            )
        return LMStudioProvider(
            base_url=str(self._config.get("lmstudio_base_url", "http://172.10.1.2:1234/v1")),
            api_key=str(self._config.get("lmstudio_api_key", "lm-studio")),
            model=selected,
            timeout_seconds=self._timeout(),
        )

    def resolve_chat(self, mode: str, model: str | None = None) -> BaseProvider:
        mode_key = (mode or "general").strip().lower()
        stage_key = {
            "general": "general",
            "agent": "agent",
            "planner": "planner_chat",
            "debugger": "debugger",
            "architect": "architect_chat",
        }.get(mode_key, "chat")
        return self.resolve_stage(stage_key, model=model)

    _AGENT_MODEL_KEYS = (
        "model_planner",
        "model_architect",
        "model_ui_designer",
        "model_coder",
        "model_reviewer",
        "model_tester",
        "model_supervisor",
        "model_chat",
        "model_chat_agent",
        "model_chat_planner",
        "model_chat_debugger",
        "model_chat_architect",
    )

    def _configured_agent_models(self) -> list[str]:
        seen: set[str] = set()
        models: list[str] = []
        for key in self._AGENT_MODEL_KEYS:
            value = str(self._config.get(key, "")).strip()
            if value and value not in seen:
                seen.add(value)
                models.append(value)
        return models

    @staticmethod
    def _is_ollama_style_model_id(model: str) -> bool:
        """Ollama tags use name:tag; LM Studio ids typically use slashes or no colon tag."""
        return ":" in model and "/" not in model

    def _model_listed(self, model: str, available: list[str]) -> bool:
        if model in available:
            return True
        lower = model.lower()
        return any(lower in candidate.lower() or candidate.lower() in lower for candidate in available)

    def _agent_models_for_lmstudio_check(
        self,
        available: list[str],
        recommendations: dict[str, str],
    ) -> list[str]:
        configured = self._configured_agent_models()
        scoped = [m for m in configured if not self._is_ollama_style_model_id(m)]
        if scoped:
            return scoped
        rec_values = [str(v).strip() for v in recommendations.values() if str(v).strip()]
        return list(dict.fromkeys(rec_values))

    def _configured_chat_model(self, mode: str) -> str:
        return str(self._config.get(self._CHAT_MODEL_KEYS.get(mode, "model_chat"), "")).strip()

    def _auto_model_patterns(self, mode: str) -> list[str]:
        family = "agent" if mode in {"agent", "debugger"} else "general"
        return self._AUTO_MODEL_PATTERNS[family]

    def _first_matching_model(self, models: list[str], patterns: list[str]) -> str | None:
        normalized = [(model, model.lower()) for model in models]
        for pattern in patterns:
            needle = pattern.lower()
            for model, lowered in normalized:
                if needle in lowered:
                    return model
        return None

    def _list_ollama_models_detailed(self) -> ModelsListResult:
        models = self._ollama_provider().list_models()
        configured = str(self._config.get("ollama_model", "")).strip()
        recommendations: dict[str, str] = {}
        if configured and configured in models:
            for key in SETTINGS_ROLE_KEYS:
                recommendations[key] = configured
        elif models:
            preferred = self._first_matching_model(models, ["qwen2.5-coder", "qwen3-coder", "coder", "qwen3", "llama3"])
            if preferred:
                for key in SETTINGS_ROLE_KEYS:
                    recommendations[key] = preferred
        catalog = [
            {
                "id": model_id,
                "state": "available",
                "loaded": True,
                "size_gb": 0.0,
                "tool_use": True,
                "params": "",
                "quantization": "",
                "loaded_instances": [],
            }
            for model_id in models
        ]
        return ModelsListResult(
            models=models,
            catalog=catalog,
            recommendations=recommendations,
            resources={
                "pressure": "ok",
                "loaded_count": len(models),
                "loaded_size_gb": 0.0,
                "catalog_count": len(models),
            },
        )

    def _agent_models_for_ollama_check(self, available: list[str]) -> list[str]:
        saved = self._config.get("ollama_role_models_json")
        if isinstance(saved, dict):
            values = [str(value).strip() for value in saved.values() if str(value).strip()]
            if values:
                return list(dict.fromkeys(values))
        configured = self._configured_agent_models()
        scoped = [model for model in configured if self._is_ollama_style_model_id(model)]
        if scoped:
            return scoped
        default = str(self._config.get("ollama_model", "")).strip()
        return [default] if default else []

    def health_ollama(self) -> HealthResult:
        if self.fake_provider is not None:
            return HealthResult(status="healthy", model_count=1, error=None, models=["fake-model"])
        configured_base = str(self._config.get("ollama_base_url", "http://127.0.0.1:11434/v1"))
        working_base, _tried = probe_ollama_endpoints(configured_base)
        if working_base is None:
            return HealthResult(
                status=ProviderStatus.UNREACHABLE.value,
                model_count=0,
                error="Ollama unreachable at configured and fallback endpoints.",
                models=[],
                resources_pressure="ok",
                loaded_size_gb=None,
                recommendations=None,
            )
        provider = OllamaProvider(
            working_base,
            model=str(self._config.get("ollama_model", "")),
            timeout_seconds=self._timeout(),
        )
        models = provider.list_models()
        configured = str(self._config.get("ollama_model", "")).strip()
        agent_models = self._agent_models_for_ollama_check(models)
        status = ProviderStatus.HEALTHY
        detail = "Ollama reachable."
        normalized_configured = normalize_ollama_base_url(configured_base)
        if working_base != normalized_configured:
            status = ProviderStatus.DEGRADED
            detail = (
                f"Ollama reachable at {working_base} but configured URL is {normalized_configured}. "
                "Update ollama_base_url in Settings."
            )
        elif models and agent_models and all(self._model_listed(model, models) for model in agent_models):
            status = ProviderStatus.HEALTHY
            detail = "Ollama reachable and configured agent models are available."
        elif models and agent_models:
            missing = [model for model in agent_models if not self._model_listed(model, models)]
            status = ProviderStatus.DEGRADED
            detail = f"Ollama reachable but agent models not found: {', '.join(missing)}"
        elif models and configured and configured in models:
            status = ProviderStatus.HEALTHY
            detail = f"Ollama reachable and configured model '{configured}' is available."
        elif models and configured:
            status = ProviderStatus.DEGRADED
            detail = f"Ollama reachable but configured model '{configured}' not found."
        elif models:
            status = ProviderStatus.DEGRADED
            detail = "Ollama reachable. Select a default model in Settings."
        else:
            status = ProviderStatus.DEGRADED
            detail = "Ollama reachable but no models were returned."
        error = detail if status != ProviderStatus.HEALTHY else None
        recommendations = self._list_ollama_models_detailed().recommendations or None
        return HealthResult(
            status=status.value,
            model_count=len(models),
            error=error,
            models=models,
            resources_pressure="ok",
            loaded_size_gb=None,
            recommendations=recommendations,
        )

    def health_lmstudio(self) -> HealthResult:
        if self.fake_provider is not None:
            return HealthResult(status="healthy", model_count=1, error=None, models=["fake-model"])
        provider = self._lmstudio_provider()
        health = provider.healthcheck()
        catalog = self.get_lmstudio_catalog(refresh=True)
        models = catalog.ids() if catalog is not None else provider.list_models()
        resources = catalog.resources() if catalog is not None else None
        recommendations = catalog.recommendations() if catalog is not None else {}
        status = health.status
        detail = health.detail

        if status != ProviderStatus.UNREACHABLE and models:
            configured = str(self._config.get("lmstudio_model", "")).strip()
            agent_models = self._agent_models_for_lmstudio_check(models, recommendations)
            if configured and self._model_listed(configured, models):
                status = ProviderStatus.HEALTHY
                detail = "LM Studio reachable and configured model is listed."
            elif agent_models and all(self._model_listed(model, models) for model in agent_models):
                status = ProviderStatus.HEALTHY
                detail = "LM Studio reachable and all agent models are available."
            elif agent_models:
                missing = [model for model in agent_models if not self._model_listed(model, models)]
                status = ProviderStatus.DEGRADED
                detail = f"LM Studio reachable but agent models not found: {', '.join(missing)}"
            elif configured:
                status = ProviderStatus.DEGRADED
                detail = f"LM Studio reachable but configured model '{configured}' not listed."
            else:
                status = ProviderStatus.DEGRADED
                detail = "LM Studio reachable. Select agent models in Settings."
            if resources and resources.pressure == "high":
                status = ProviderStatus.DEGRADED
                detail = (
                    f"LM Studio memory pressure is high ({resources.loaded_size_gb} GB loaded across "
                    f"{resources.loaded_count} model(s)). Smaller or fewer loaded models are recommended."
                )

        error = detail if status != ProviderStatus.HEALTHY else None
        return HealthResult(
            status=status.value,
            model_count=len(models),
            error=error,
            models=models,
            resources_pressure=resources.pressure if resources else None,
            loaded_size_gb=resources.loaded_size_gb if resources else None,
            recommendations=recommendations or None,
        )

    def list_models(self) -> list[str]:
        if self.fake_provider is not None:
            return self.fake_provider.list_models()
        if self._config.get("ollama_enabled"):
            return self._ollama_provider().list_models()
        return self._lmstudio_provider().list_models()

    def health_provider_summary(self) -> dict[str, Any]:
        active = self.active_provider()
        lm = self.health_lmstudio()
        ollama = self.health_ollama()
        primary = ollama if active == "ollama" else lm
        configured_ollama = normalize_ollama_base_url(str(self._config.get("ollama_base_url", "")))
        working_ollama, _ = probe_ollama_endpoints(configured_ollama)
        return {
            "active_provider": active,
            "lmstudio": lm.status,
            "ollama": ollama.status,
            "error": primary.error,
            "lmstudio_error": lm.error,
            "ollama_error": ollama.error,
            "suggested_ollama_base_url": (
                working_ollama if working_ollama and working_ollama != configured_ollama else None
            ),
            "model_count": primary.model_count,
            "lmstudio_model_count": lm.model_count,
            "ollama_model_count": ollama.model_count,
            "models": primary.models,
            "lmstudio_models": lm.models,
            "ollama_models": ollama.models,
            "resources_pressure": primary.resources_pressure,
            "loaded_size_gb": primary.loaded_size_gb,
            "recommendations": primary.recommendations or {},
        }


def set_provider_override(provider: BaseProvider | None) -> None:
    registry = ProviderRegistry.get()
    registry.fake_provider = provider if isinstance(provider, FakeProvider) else None


def reload_from_db(db) -> None:
    from app.services.config_service import ConfigService

    ConfigService(db).reload_registry()
