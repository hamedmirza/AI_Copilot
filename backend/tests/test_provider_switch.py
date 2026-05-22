from app.services.provider_switch import (
    build_provider_switch_updates,
    sync_active_provider_role_models,
)
from app.providers.registry import ProviderRegistry


def test_ollama_style_model_id():
    assert ProviderRegistry._is_ollama_style_model_id("qwen3.6:latest")
    assert not ProviderRegistry._is_ollama_style_model_id("qwen/qwen3.6-35b-a3b")


def test_build_provider_switch_saves_snapshot_and_restores_recommendations():
    config = {
        "ollama_enabled": True,
        "model_chat": "qwen3.6:latest",
        "model_coder": "qwen3.6:latest",
        "ollama_role_models_json": {},
        "lmstudio_role_models_json": {"model_chat": "qwen3.6-27b", "model_coder": "qwen3.6-27b"},
    }
    updates = build_provider_switch_updates(config, from_provider="ollama", to_provider="lmstudio")
    assert updates["ollama_enabled"] is False
    assert updates["ollama_role_models_json"]["model_chat"] == "qwen3.6:latest"
    assert updates["model_chat"] == "qwen3.6-27b"


def test_sync_active_provider_role_models_uses_snapshot():
    config = {
        "ollama_enabled": False,
        "lmstudio_role_models_json": {"model_chat": "qwen3.6-27b"},
        "model_chat": "qwen3.6:latest",
    }
    updates = sync_active_provider_role_models(config, "lmstudio")
    assert updates["model_chat"] == "qwen3.6-27b"
