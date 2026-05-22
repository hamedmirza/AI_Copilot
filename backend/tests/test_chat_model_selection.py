from __future__ import annotations

from pathlib import Path

import pytest

from app.providers.registry import ProviderRegistry

HEADERS = {"X-Api-Token": "dev-token"}


def _create_project(client, tmp_path: Path, name: str) -> str:
    project_dir = tmp_path / name
    project_dir.mkdir()
    (project_dir / "main.py").write_text("print('hello')\n", encoding="utf-8")
    response = client.post(
        "/api/projects",
        json={
            "name": name,
            "source_repo_spec": str(project_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_resolve_auto_chat_model_prefers_instruct_for_general(monkeypatch: pytest.MonkeyPatch):
    registry = ProviderRegistry()
    registry.reload(
        {
            "model_chat": "custom-general",
            "lmstudio_model": "fallback-general",
        }
    )
    monkeypatch.setattr(
        registry,
        "list_models",
        lambda: ["llama-3", "Qwen2.5-72B-Instruct-GGUF", "qwen2.5-coder-32b-instruct"],
    )

    resolved = registry.resolve_auto_chat_model("general")

    assert resolved == "Qwen2.5-72B-Instruct-GGUF"


def test_resolve_auto_chat_model_prefers_coder_for_agent(monkeypatch: pytest.MonkeyPatch):
    registry = ProviderRegistry()
    registry.reload(
        {
            "model_chat_agent": "custom-agent",
            "lmstudio_model": "fallback-agent",
        }
    )
    monkeypatch.setattr(
        registry,
        "list_models",
        lambda: ["qwen3-32b", "Qwen3-Coder-30B-A3B-Instruct", "gpt-oss-20b"],
    )

    resolved = registry.resolve_auto_chat_model("agent")

    assert resolved == "Qwen3-Coder-30B-A3B-Instruct"


def test_resolve_auto_chat_model_falls_back_to_configured_or_first(monkeypatch: pytest.MonkeyPatch):
    registry = ProviderRegistry()
    registry.reload(
        {
            "model_chat_architect": "manual-architect",
            "lmstudio_model": "fallback-architect",
        }
    )
    monkeypatch.setattr(
        registry,
        "list_models",
        lambda: ["manual-architect", "fallback-architect", "another-model"],
    )
    assert registry.resolve_auto_chat_model("architect") == "manual-architect"

    registry.reload(
        {
            "model_chat_architect": "missing-architect",
            "lmstudio_model": "missing-fallback",
        }
    )
    monkeypatch.setattr(registry, "list_models", lambda: ["first-listed", "second-listed"])
    assert registry.resolve_auto_chat_model("architect") == "first-listed"


def test_resolve_chat_provider_uses_auto_resolution_for_blank_and_auto(monkeypatch: pytest.MonkeyPatch):
    registry = ProviderRegistry()
    registry.reload({"lmstudio_model": "fallback"})
    monkeypatch.setattr(registry, "resolve_auto_chat_model", lambda mode: f"auto::{mode}")

    assert registry.resolve_chat_provider("general").model == "auto::general"
    assert registry.resolve_chat_provider("agent", "").model == "auto::agent"
    assert registry.resolve_chat_provider("planner", "AUTO").model == "auto::planner"
    assert registry.resolve_chat_provider("debugger", "manual-model").model == "manual-model"


def test_update_chat_session_can_clear_model_override(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-model-selection-project")
    created = client.post(
        "/api/chat/sessions",
        json={
            "project_id": project_id,
            "title": "Model selection chat",
            "mode": "general",
            "model_override": "manual-model",
        },
        headers=HEADERS,
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    assert created.json()["model_override"] == "manual-model"

    updated = client.put(
        f"/api/chat/sessions/{session_id}",
        json={"model_override": None},
        headers=HEADERS,
    )
    assert updated.status_code == 200
    assert updated.json()["model_override"] is None
