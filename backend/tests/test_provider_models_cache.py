"""Provider registry models-list cache for settings UI."""

from __future__ import annotations

import time

import pytest

from app.providers.registry import ModelsListResult, ProviderRegistry


def test_list_models_detailed_for_provider_uses_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ProviderRegistry()
    registry.reload(
        {
            "ollama_enabled": False,
            "lmstudio_base_url": "http://127.0.0.1:1234/v1",
        }
    )
    calls = {"count": 0}

    def fake_detailed(*, refresh: bool = False) -> ModelsListResult:
        calls["count"] += 1
        return ModelsListResult(
            models=["cached-model"],
            catalog=[],
            recommendations={},
            resources={"pressure": "ok", "loaded_count": 0, "loaded_size_gb": 0.0},
        )

    monkeypatch.setattr(registry, "list_models_detailed", fake_detailed)

    first = registry.list_models_detailed_for_provider("lmstudio", refresh=False)
    second = registry.list_models_detailed_for_provider("lmstudio", refresh=False)

    assert first.models == ["cached-model"]
    assert second.models == ["cached-model"]
    assert calls["count"] == 1

    registry.list_models_detailed_for_provider("lmstudio", refresh=True)
    assert calls["count"] == 2


def test_invalidate_models_detailed_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = ProviderRegistry()
    registry.reload({"ollama_enabled": False, "lmstudio_base_url": "http://127.0.0.1:1234/v1"})
    calls = {"count": 0}

    def fake_detailed(*, refresh: bool = False) -> ModelsListResult:
        calls["count"] += 1
        return ModelsListResult(
            models=["m"],
            catalog=[],
            recommendations={},
            resources={"pressure": "ok", "loaded_count": 0, "loaded_size_gb": 0.0},
        )

    monkeypatch.setattr(registry, "list_models_detailed", fake_detailed)
    registry.list_models_detailed_for_provider("lmstudio")
    registry.invalidate_models_detailed_cache()
    registry.list_models_detailed_for_provider("lmstudio")
    assert calls["count"] == 2
