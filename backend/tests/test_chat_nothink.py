from __future__ import annotations

from pathlib import Path

from app.services.chat_orchestrator import ChatOrchestrator

HEADERS = {"X-Api-Token": "dev-token"}


def _create_project(client, tmp_path: Path, name: str) -> str:
    response = client.post(
        "/api/projects",
        json={
            "name": name,
            "description": "",
            "source_repo_spec": str(tmp_path),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_resolve_use_nothink_prefers_session_over_global_default():
    assert ChatOrchestrator._resolve_use_nothink(True, {"nothink_default": False}) is True
    assert ChatOrchestrator._resolve_use_nothink(False, {"nothink_default": True}) is False
    assert ChatOrchestrator._resolve_use_nothink(None, {"nothink_default": False}) is False
    assert ChatOrchestrator._resolve_use_nothink(None, {}) is True


def test_build_provider_messages_injects_nothink_when_enabled():
    orchestrator = ChatOrchestrator()
    messages = orchestrator._build_provider_messages(
        [],
        project_path="/tmp/project",
        mode_prompt="You are helpful.",
        context={"open_files": []},
        use_nothink=True,
    )
    assert messages[0]["role"] == "system"
    assert "/nothink" in messages[0]["content"]
    assert "You are helpful." in messages[0]["content"]


def test_build_provider_messages_omits_nothink_when_disabled():
    orchestrator = ChatOrchestrator()
    messages = orchestrator._build_provider_messages(
        [],
        project_path="/tmp/project",
        mode_prompt="You are helpful.",
        context={"open_files": []},
        use_nothink=False,
    )
    assert "/nothink" not in messages[0]["content"]


def test_update_chat_session_nothink_toggle(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-nothink-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "Nothink chat", "mode": "general"},
        headers=HEADERS,
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    assert created.json()["nothink"] is None

    updated = client.put(
        f"/api/chat/sessions/{session_id}",
        json={"nothink": False},
        headers=HEADERS,
    )
    assert updated.status_code == 200
    assert updated.json()["nothink"] is False

    cleared = client.put(
        f"/api/chat/sessions/{session_id}",
        json={"nothink": None},
        headers=HEADERS,
    )
    assert cleared.status_code == 200
    assert cleared.json()["nothink"] is None


def test_settings_nothink_default_round_trip(client):
    updated = client.put(
        "/api/settings",
        json={"nothink_default": False},
        headers=HEADERS,
    )
    assert updated.status_code == 200
    assert updated.json()["nothink_default"] is False

    restored = client.put(
        "/api/settings",
        json={"nothink_default": True},
        headers=HEADERS,
    )
    assert restored.status_code == 200
    assert restored.json()["nothink_default"] is True


def test_update_chat_session_web_search_toggle(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-web-search-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "Web Search Chat", "mode": "general"},
        headers=HEADERS,
    )
    assert created.status_code == 200
    session_id = created.json()["id"]
    assert created.json()["allow_web_search"] is False

    updated = client.put(
        f"/api/chat/sessions/{session_id}",
        json={"allow_web_search": True},
        headers=HEADERS,
    )
    assert updated.status_code == 200
    assert updated.json()["allow_web_search"] is True
