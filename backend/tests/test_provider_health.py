from __future__ import annotations

import pytest

from app.providers.registry import HealthResult, ProviderRegistry


def test_resolve_stage_falls_back_when_model_missing_on_ollama(monkeypatch: pytest.MonkeyPatch):
    registry = ProviderRegistry()
    registry.reload(
        {
            "ollama_enabled": True,
            "ollama_base_url": "http://172.10.1.2:11434/v1",
            "model_coder": "qwen3.6-27b",
            "ollama_model": "qwen3.6:latest",
        }
    )
    monkeypatch.setattr(registry, "list_models", lambda: ["qwen3.6:latest", "llama3.1:8b"])

    provider = registry.resolve_stage("coder")
    assert provider.model == "qwen3.6:latest"


def test_health_ollama_degraded_when_agent_models_missing(monkeypatch: pytest.MonkeyPatch):
    registry = ProviderRegistry()
    registry.reload(
        {
            "ollama_enabled": False,
            "ollama_base_url": "http://172.10.1.2:11434/v1",
            "ollama_model": "qwen3.6:latest",
            "ollama_role_models_json": {"model_coder": "qwen3.6:latest", "model_chat": "qwen3.6:latest"},
            "model_coder": "qwen3.6-27b",
        }
    )

    class FakeOllama:
        def list_models(self):
            return ["llama3.1:8b"]

    monkeypatch.setattr(
        "app.providers.registry.probe_ollama_endpoints",
        lambda configured, timeout_seconds=5.0: ("http://172.10.1.2:11434/v1", []),
    )
    monkeypatch.setattr(
        "app.providers.registry.OllamaProvider",
        lambda base_url, model, timeout_seconds=120: FakeOllama(),
    )

    health = registry.health_ollama()
    assert health.status == "degraded"
    assert health.error is not None
    assert "qwen3.6:latest" in health.error


def test_health_provider_summary_includes_suggested_ollama_url(monkeypatch: pytest.MonkeyPatch):
    registry = ProviderRegistry()
    registry.reload(
        {
            "ollama_enabled": False,
            "ollama_base_url": "http://127.0.0.1:11434/v1",
            "lmstudio_base_url": "http://192.168.128.70:1234/v1",
        }
    )
    monkeypatch.setattr(
        registry,
        "health_lmstudio",
        lambda: HealthResult(
            status="healthy",
            model_count=1,
            error=None,
            models=["qwen3.6-27b"],
            resources_pressure="ok",
            loaded_size_gb=1.0,
            recommendations={},
        ),
    )
    monkeypatch.setattr(
        registry,
        "health_ollama",
        lambda: HealthResult(
            status="degraded",
            model_count=7,
            error="wrong url",
            models=["qwen3.6:latest"],
            resources_pressure="ok",
            loaded_size_gb=None,
            recommendations={},
        ),
    )
    monkeypatch.setattr(
        "app.providers.registry.probe_ollama_endpoints",
        lambda configured, timeout_seconds=5.0: ("http://172.10.1.2:11434/v1", []),
    )

    summary = registry.health_provider_summary()
    assert summary["suggested_ollama_base_url"] == "http://172.10.1.2:11434/v1"
