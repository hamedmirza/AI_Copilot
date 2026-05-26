import json
import time
from pathlib import Path

from app.db.models import AppConfigModel, RunModel, TaskModel
from app.db.session import SessionLocal
from app.services.chat_service import ChatService
from app.services.pipeline_bridge import pipeline_bridge
from app.services.project_service import ProjectService
from app.tools.chat_tools import ToolExecutionContext
from app.tools.tool_registry import ToolRegistry

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


def test_chat_session_timestamps_include_utc_suffix(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-timestamp-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "Timestamp Chat", "mode": "general"},
        headers=HEADERS,
    )
    assert created.status_code == 200
    payload = created.json()
    for field in ("created_at", "updated_at"):
        assert payload[field].endswith("Z"), payload[field]


def test_chat_session_crud(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-session-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "Backend Chat", "mode": "general"},
        headers=HEADERS,
    )
    assert created.status_code == 200
    session_id = created.json()["id"]

    listed = client.get(f"/api/chat/sessions?project_id={project_id}", headers=HEADERS)
    assert listed.status_code == 200
    assert any(item["id"] == session_id for item in listed.json())

    fetched = client.get(f"/api/chat/sessions/{session_id}", headers=HEADERS)
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Backend Chat"

    updated = client.put(
        f"/api/chat/sessions/{session_id}",
        json={"title": "Renamed Chat", "mode": "debugger"},
        headers=HEADERS,
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Renamed Chat"
    assert updated.json()["mode"] == "debugger"

    deleted = client.delete(f"/api/chat/sessions/{session_id}", headers=HEADERS)
    assert deleted.status_code == 200
    missing = client.get(f"/api/chat/sessions/{session_id}", headers=HEADERS)
    assert missing.status_code == 404


def test_chat_message_persists_assistant_reply(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-message-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "Message Chat", "mode": "general"},
        headers=HEADERS,
    )
    session_id = created.json()["id"]

    posted = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": "Explain this project", "context": {"open_files": ["main.py"]}},
        headers=HEADERS,
    )
    assert posted.status_code == 200

    assistant_messages = []
    for _ in range(30):
        history = client.get(f"/api/chat/sessions/{session_id}/messages", headers=HEADERS)
        assert history.status_code == 200
        assistant_messages = [item for item in history.json() if item["role"] == "assistant"]
        if assistant_messages:
            break
        time.sleep(0.1)

    assert assistant_messages
    assert assistant_messages[-1]["content"] == "Fake assistant reply"
    duration_ms = assistant_messages[-1].get("metadata", {}).get("duration_ms")
    assert isinstance(duration_ms, int)
    assert duration_ms >= 0


def test_chat_tool_git_status_basics(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-tool-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "Tool Chat", "mode": "agent"},
        headers=HEADERS,
    )
    session_id = created.json()["id"]

    db = SessionLocal()
    try:
        session = ChatService(db).get_session(session_id)
        project = ProjectService(db).get(project_id)
        tool_registry = ToolRegistry(db)
        tools = tool_registry.resolve_tools(
            __import__("app.services.chat_mode_registry", fromlist=["ChatModeRegistry"]).ChatModeRegistry().get_mode("agent")
        )
        output = tool_registry.execute_tool(
            "git_status",
            {},
            ToolExecutionContext(db=db, project=project, session=session),
            tools,
        )
    finally:
        db.close()

    parsed = json.loads(output)
    assert "untracked" in parsed
    assert any(item["path"] == "main.py" for item in parsed["untracked"])


def test_tool_registry_hides_web_search_unless_session_enabled(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-web-tool-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "Tool Chat", "mode": "agent"},
        headers=HEADERS,
    )
    assert created.status_code == 200
    session_id = created.json()["id"]

    db = SessionLocal()
    try:
        session = ChatService(db).get_session(session_id)
        mode = __import__("app.services.chat_mode_registry", fromlist=["ChatModeRegistry"]).ChatModeRegistry().get_mode(
            "agent"
        )
        tool_registry = ToolRegistry(db)
        tools = tool_registry.resolve_tools(mode, session=session)
        assert "web_search" not in tools

        session.allow_web_search = True
        db.commit()
        db.refresh(session)
        tools = tool_registry.resolve_tools(mode, session=session)
        assert "web_search" in tools
    finally:
        db.close()


def test_chat_modes_endpoint_lists_builtin_modes(client):
    response = client.get("/api/chat/modes", headers=HEADERS)
    assert response.status_code == 200

    keys = {item["key"] for item in response.json()}
    assert {"general", "agent", "planner", "debugger", "architect"}.issubset(keys)


def test_send_message_updates_session_preferences(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-message-mode-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "Preferences Chat", "mode": "general"},
        headers=HEADERS,
    )
    assert created.status_code == 200
    session_id = created.json()["id"]

    posted = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={
            "content": "Use debugger mode for this message",
            "mode": "debugger",
            "model_override": "manual-debug-model",
            "context": {},
        },
        headers=HEADERS,
    )
    assert posted.status_code == 200

    session = client.get(f"/api/chat/sessions/{session_id}", headers=HEADERS)
    assert session.status_code == 200
    assert session.json()["mode"] == "debugger"
    assert session.json()["model_override"] == "manual-debug-model"


def test_chat_history_metadata_and_search(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-history-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "mode": "general", "title": "New chat"},
        headers=HEADERS,
    )
    assert created.status_code == 200
    session_id = created.json()["id"]

    first_message = "Outline the refactor plan for the dashboard history sidebar"
    posted = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": first_message, "context": {}},
        headers=HEADERS,
    )
    assert posted.status_code == 200
    payload = posted.json()
    assert payload["message_id"]
    assert payload["user_message"]["role"] == "user"
    assert payload["user_message"]["content"] == first_message
    assert payload["session"]["title"] == first_message[:60]
    assert payload["session"]["message_count"] == 1
    assert payload["session"]["last_message_preview"] == first_message
    assert payload["session"]["last_message_at"] is not None

    assistant_history = []
    for _ in range(30):
        history = client.get(f"/api/chat/sessions/{session_id}/messages", headers=HEADERS)
        assert history.status_code == 200
        assistant_history = [item for item in history.json() if item["role"] == "assistant"]
        if assistant_history:
            break
        time.sleep(0.1)

    assert assistant_history

    db = SessionLocal()
    try:
        service = ChatService(db)
        service.append_message(session_id, role="tool", content="Tool output should not become the preview")
        service.append_message(
            session_id,
            role="assistant",
            content="Assistant recap about history search keyword zebra and recent changes",
        )
    finally:
        db.close()

    listed = client.get(f"/api/chat/sessions?project_id={project_id}", headers=HEADERS)
    assert listed.status_code == 200
    history_items = {item["id"]: item for item in listed.json()}
    assert session_id in history_items

    session = history_items[session_id]
    # user POST + async assistant reply + tool + manual assistant
    assert session["message_count"] == 4
    assert session["last_message_preview"] == "Assistant recap about history search keyword zebra and recent changes"
    assert session["last_message_at"] is not None

    title_search = client.get(
        f"/api/chat/sessions?project_id={project_id}&q=dashboard",
        headers=HEADERS,
    )
    assert title_search.status_code == 200
    assert any(item["id"] == session_id for item in title_search.json())

    content_search = client.get(
        f"/api/chat/sessions?project_id={project_id}&q=zebra",
        headers=HEADERS,
    )
    assert content_search.status_code == 200
    assert any(item["id"] == session_id for item in content_search.json())


def test_chat_modes_endpoint_uses_latest_db_config(client):
    db = SessionLocal()
    try:
        row = db.query(AppConfigModel).filter(AppConfigModel.key == "chat_modes_json").first()
        assert row is not None
        row.value = json.dumps(
            [
                {
                    "key": "custom-review",
                    "label": "Custom Review",
                    "description": "Review mode from DB config",
                    "system_prompt": "Review carefully",
                    "allowed_tools": ["read_file"],
                }
            ]
        )
        db.commit()
    finally:
        db.close()

    response = client.get("/api/chat/modes", headers=HEADERS)
    assert response.status_code == 200
    assert any(item["key"] == "custom-review" for item in response.json())


def test_pipeline_bridge_appends_run_completion_summary(client, tmp_path: Path):
    project_id = _create_project(client, tmp_path, "chat-run-summary-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "Run Summary Chat", "mode": "agent"},
        headers=HEADERS,
    )
    assert created.status_code == 200
    session_id = created.json()["id"]

    db = SessionLocal()
    try:
        task = TaskModel(project_id=project_id, description="Ship the fix", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project_id,
            task_id=task.id,
            status="completed",
            current_stage="tester",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    summary = pipeline_bridge._create_summary_message(
        session_id,
        run_id,
        {"type": "run_completed", "message": "Run completed"},
    )
    assert summary is not None

    history = client.get(f"/api/chat/sessions/{session_id}/messages", headers=HEADERS)
    assert history.status_code == 200
    summaries = [
        item
        for item in history.json()
        if item["metadata"].get("type") == "run_summary" and item["metadata"].get("run_id") == run_id
    ]

    assert summaries
    assert "Pipeline run completed." in summaries[-1]["content"]
    assert "Last stage: tester." in summaries[-1]["content"]


def test_chat_cancel_mid_stream(client, tmp_path: Path):
    import threading

    from app.providers.base import ChatStreamChunk
    from app.providers.fake import FakeProvider
    from app.providers.registry import ProviderRegistry
    from app.services.chat_orchestrator import chat_orchestrator

    stream_chunks = ["part", "ial", " stream"]
    first_chunk_sent = threading.Event()

    def slow_stream(self, messages, tools=None, max_tokens=None, tool_choice=None):
        for index, piece in enumerate(stream_chunks):
            if index > 0:
                time.sleep(0.05)
            yield ChatStreamChunk(delta=piece)
            if index == 0:
                first_chunk_sent.set()
        yield ChatStreamChunk(done=True, finish_reason="stop")

    registry = ProviderRegistry.get()
    assert registry.fake_provider is not None
    registry.fake_provider.invoke_chat_stream = slow_stream.__get__(
        registry.fake_provider,
        FakeProvider,
    )

    project_id = _create_project(client, tmp_path, "chat-cancel-project")
    created = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "Cancel Chat", "mode": "general"},
        headers=HEADERS,
    )
    assert created.status_code == 200
    session_id = created.json()["id"]

    posted = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"content": "Start streaming"},
        headers=HEADERS,
    )
    assert posted.status_code == 200

    assert first_chunk_sent.wait(timeout=2.0)

    cancelled = client.post(f"/api/chat/sessions/{session_id}/cancel", headers=HEADERS)
    assert cancelled.status_code == 200
    assert cancelled.json()["ok"] is True
    assert cancelled.json()["cancelled"] is True

    chat_orchestrator.wait_for_idle(timeout=10.0)

    history = client.get(f"/api/chat/sessions/{session_id}/messages", headers=HEADERS)
    assert history.status_code == 200
    assistant_messages = [item for item in history.json() if item["role"] == "assistant"]
    assert assistant_messages
    last_assistant = assistant_messages[-1]
    assert last_assistant["metadata"].get("cancelled") is True
    assert last_assistant["content"].startswith("part")

    idle_cancel = client.post(f"/api/chat/sessions/{session_id}/cancel", headers=HEADERS)
    assert idle_cancel.status_code == 200
    assert idle_cancel.json()["cancelled"] is False
