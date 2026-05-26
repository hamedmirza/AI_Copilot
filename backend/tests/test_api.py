from pathlib import Path

import json
import sqlite3
import pytest
from starlette.websockets import WebSocketDisconnect

from app.db.session import SessionLocal

HEADERS = {"X-Api-Token": "dev-token"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "uptime_seconds" in body
    assert "worker_count" in body
    assert "ws_connections" in body


def test_settings(client):
    r = client.get("/api/settings", headers=HEADERS)
    assert r.status_code == 200
    assert "lmstudio_base_url" in r.json()


def test_settings_reset(client):
    client.put(
        "/api/settings",
        json={"lmstudio_base_url": "http://10.0.0.1:1234/v1", "worker_count": 4},
        headers=HEADERS,
    )
    r = client.post("/api/settings/reset", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["lmstudio_base_url"] == "http://172.10.1.2:1234/v1"
    assert body["worker_count"] == 1
    assert body["stop_on_first_failure"] is True
    assert body["ollama_enabled"] is False
    assert body["model_planner"] == "qwen3.6-27b"
    assert body["model_chat_debugger"] == "qwen3.6-27b"


def test_settings_reset_restores_validation_profiles(client):
    client.put(
        "/api/settings",
        json={"validation_profiles_json": json.dumps({"python": ["python3 -m compileall ."]})},
        headers=HEADERS,
    )
    body = client.post("/api/settings/reset", headers=HEADERS).json()
    profiles = json.loads(body["validation_profiles_json"])
    assert "python" in profiles
    assert profiles["python"] == ["ruff check .", "mypy .", "pytest -q"]


def test_settings_update_syncs_active_provider_role_snapshot(client):
    body = client.put(
        "/api/settings",
        json={
            "ollama_enabled": False,
            "model_planner": "qwen3.6-27b",
            "model_chat_debugger": "qwen3.6-27b",
        },
        headers=HEADERS,
    ).json()
    snapshot = body["lmstudio_role_models_json"]
    assert snapshot["model_planner"] == "qwen3.6-27b"
    assert snapshot["model_chat_debugger"] == "qwen3.6-27b"


def test_onboarding_status_empty(client):
    r = client.get("/api/onboarding/status", headers=HEADERS)
    assert r.status_code == 200
    # Module-scoped client may already have projects from other tests.
    assert "complete" in r.json()
    assert "project_count" in r.json()


def test_projects_endpoint_migrates_old_schema_db(tmp_path):
    from fastapi.testclient import TestClient

    from app.api.main import app
    from app.db.session import reconfigure_engine

    legacy_db = tmp_path / "legacy_projects.db"
    conn = sqlite3.connect(legacy_db)
    try:
        conn.executescript(
            """
            CREATE TABLE projects (
                id VARCHAR(36) PRIMARY KEY NOT NULL,
                name VARCHAR(255),
                description TEXT DEFAULT '',
                source_repo_spec TEXT,
                validation_profile VARCHAR(64) DEFAULT 'python',
                protected_files_json TEXT DEFAULT '[]',
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            );
            CREATE TABLE tasks (
                id VARCHAR(36) PRIMARY KEY NOT NULL,
                project_id VARCHAR(36) NOT NULL,
                description TEXT NOT NULL,
                validation_profile VARCHAR(64) NOT NULL,
                use_scout BOOLEAN NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE runs (
                id VARCHAR(36) PRIMARY KEY NOT NULL,
                project_id VARCHAR(36) NOT NULL,
                task_id VARCHAR(36) NOT NULL,
                status VARCHAR(64) NOT NULL,
                current_stage VARCHAR(64),
                workspace_path TEXT,
                review_attempts INTEGER NOT NULL,
                error_message TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                operator_feedback TEXT,
                promote_snapshot_json TEXT
            );
            INSERT INTO projects (id, name, description, source_repo_spec, validation_profile, protected_files_json, created_at, updated_at)
            VALUES ('legacy-project', 'Legacy Project', '', '/tmp/legacy-project', 'python', '[]', '2026-05-22T00:00:00+00:00', '2026-05-22T00:00:00+00:00');
            """
        )
        conn.commit()
    finally:
        conn.close()

    reconfigure_engine(f"sqlite:///{legacy_db}")
    with TestClient(app) as local_client:
        response = local_client.get("/api/projects", headers=HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body[0]["id"] == "legacy-project"

    check = sqlite3.connect(legacy_db)
    try:
        run_columns = {row[1] for row in check.execute("PRAGMA table_info(runs)").fetchall()}
        task_columns = {row[1] for row in check.execute("PRAGMA table_info(tasks)").fetchall()}
        project_columns = {row[1] for row in check.execute("PRAGMA table_info(projects)").fetchall()}
        tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        check.close()

    assert {
        "task_kind",
        "failure_class",
        "failure_subclass",
        "failure_signature",
        "recovery_status",
        "superseded_by_run_id",
        "terminal_success",
        "terminal_status",
        "retry_count",
        "schema_failure_count",
        "reviewer_failure_count",
        "tester_failure_count",
        "operator_feedback_present",
        "approval_reached",
        "promote_rolled_back",
        "primary_failure_class",
        "allow_web_search",
    } <= run_columns
    assert {"task_kind", "allow_web_search"} <= task_columns
    assert {"repo_mode", "stack_profile"} <= project_columns
    assert "global_skills" in tables
    assert "improvements" in tables
    assert "improvement_exposures" in tables


def test_run_workspace_isolation(client, tmp_path):
    from app.providers.fake import FakeProvider
    from app.providers.registry import ProviderRegistry
    import time

    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()
    (proj_a / "main.py").write_text("x = 1\n")
    (proj_a / "secret.txt").write_text("project-a\n")
    (proj_b / "secret.txt").write_text("project-b\n")

    pa = client.post(
        "/api/projects",
        json={"name": "A", "source_repo_spec": str(proj_a), "validation_profile": "python"},
        headers=HEADERS,
    ).json()["id"]
    client.post(
        "/api/projects",
        json={"name": "B", "source_repo_spec": str(proj_b), "validation_profile": "python"},
        headers=HEADERS,
    )

    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider()
    registry.reload({})

    task = client.post(
        "/api/tasks",
        json={"project_id": pa, "description": "Add marker file for isolation test run"},
        headers=HEADERS,
    )
    assert task.status_code == 200
    run_id = task.json()["run"]["id"]

    workspace = None
    for _ in range(100):
        run = client.get(f"/api/runs/{run_id}", headers=HEADERS).json()
        workspace = run.get("workspace_path")
        if workspace:
            break
        time.sleep(0.05)

    assert workspace
    assert Path(workspace).resolve() != proj_a.resolve()
    assert "/backend/workspaces/" not in str(Path(workspace).resolve())
    assert str(Path(workspace).resolve()).endswith(run_id)
    assert (proj_a / "secret.txt").read_text() == "project-a\n"


def test_task_creation_persists_web_search_flag(client, tmp_path):
    project_id = client.post(
        "/api/projects",
        json={
            "name": "Web Search Task Project",
            "source_repo_spec": str(tmp_path),
            "validation_profile": "python",
        },
        headers=HEADERS,
    ).json()["id"]

    created = client.post(
        "/api/tasks",
        json={
            "project_id": project_id,
            "description": "Research the latest upstream API behavior and implement the required adapter change",
            "validation_profile": "python",
            "allow_web_search": True,
        },
        headers=HEADERS,
    )
    assert created.status_code == 200
    payload = created.json()
    assert payload["task"]["allow_web_search"] is True
    assert payload["run"]["allow_web_search"] is True

    run = client.get(f"/api/runs/{payload['run']['id']}", headers=HEADERS)
    assert run.status_code == 200
    assert run.json()["allow_web_search"] is True


def test_task_creation_infers_allow_web_search_from_description(client, tmp_path):
    project_id = client.post(
        "/api/projects",
        json={
            "name": "Web Search Infer Project",
            "source_repo_spec": str(tmp_path),
            "validation_profile": "python",
        },
        headers=HEADERS,
    ).json()["id"]

    created = client.post(
        "/api/tasks",
        json={
            "project_id": project_id,
            "description": "Extend backend/app/services/web_search_service.py with configurable providers",
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert created.status_code == 200
    assert created.json()["task"]["allow_web_search"] is True
    assert created.json()["run"]["allow_web_search"] is True


def test_build_context_base_includes_web_search_findings(client, tmp_path, monkeypatch):
    from app.db.models import RunModel, TaskModel
    from app.services.orchestration_service import OrchestrationService

    project_id = client.post(
        "/api/projects",
        json={
            "name": "Web Search Context Project",
            "source_repo_spec": str(tmp_path),
            "validation_profile": "python",
        },
        headers=HEADERS,
    ).json()["id"]

    created = client.post(
        "/api/tasks",
        json={
            "project_id": project_id,
            "description": "Check the latest provider docs and adjust the integration plan",
            "validation_profile": "python",
            "allow_web_search": True,
        },
        headers=HEADERS,
    )
    assert created.status_code == 200
    run_id = created.json()["run"]["id"]

    monkeypatch.setattr(
        "app.services.orchestration_service.WebSearchService.build_context_block",
        lambda self, query, limit=5: f"Web search findings for: {query}",
    )

    db = SessionLocal()
    try:
        run = db.get(RunModel, run_id)
        task = db.get(TaskModel, run.task_id) if run else None
        assert run is not None
        assert task is not None
        context = OrchestrationService()._build_context_base(db, run.id, run, task.description)
    finally:
        db.close()

    assert "Web search findings for:" in context


def test_run_workspace_excludes_runtime_db_files(tmp_path):
    from app.services.workspace_service import prepare_run_workspace

    source = tmp_path / "source"
    (source / "backend").mkdir(parents=True)
    (source / "backend" / "app.db").write_text("live-db")
    (source / "backend" / "app.db-wal").write_text("live-wal")
    (source / "backend" / "app.db-shm").write_text("live-shm")
    (source / "backend" / "test_app.db").write_text("pytest-db")
    (source / "backend" / "test_app.db-wal").write_text("pytest-wal")
    (source / "backend" / "test_app.db-shm").write_text("pytest-shm")
    (source / "frontend").mkdir()
    (source / "frontend" / "index.ts").write_text("export const ok = true;\n")

    workspace = prepare_run_workspace(source, "exclude-db-files")

    assert not (workspace / "backend" / "app.db").exists()
    assert not (workspace / "backend" / "app.db-wal").exists()
    assert not (workspace / "backend" / "app.db-shm").exists()
    assert not (workspace / "backend" / "test_app.db").exists()
    assert not (workspace / "backend" / "test_app.db-wal").exists()
    assert not (workspace / "backend" / "test_app.db-shm").exists()
    assert (workspace / "frontend" / "index.ts").exists()


def test_project_kanban_returns_real_run_columns(client, tmp_path):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal

    project_root = tmp_path / "kanban_project"
    project_root.mkdir()
    (project_root / "main.py").write_text("print('kanban')\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="Kanban Project",
            source_repo_spec=str(project_root),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()

        task_active = TaskModel(project_id=project.id, description="Implement execution timeline", validation_profile="python")
        task_done = TaskModel(project_id=project.id, description="Ship approval safety UI", validation_profile="python")
        db.add_all([task_active, task_done])
        db.flush()

        active_run = RunModel(project_id=project.id, task_id=task_active.id, status="running", current_stage="coder")
        done_run = RunModel(project_id=project.id, task_id=task_done.id, status="completed", current_stage="tester")
        db.add_all([active_run, done_run])
        db.commit()
        project_id = project.id
    finally:
        db.close()

    response = client.get(f"/api/projects/{project_id}/kanban", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["project"]["id"] == project_id
    assert body["summary"]["total_runs"] == 2
    columns = {column["id"]: column for column in body["columns"]}
    assert any(card["status"] == "running" for card in columns["active"]["items"])
    assert any(card["status"] == "completed" for card in columns["completed"]["items"])
    assert columns["active"]["items"][0]["title"].startswith("Implement execution timeline")


def test_record_event_survives_poisoned_session(tmp_path):
    from sqlalchemy.exc import IntegrityError

    from app.db.models import ProjectModel, RunEventModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "poisoned_session_workspace"
    workspace.mkdir()

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="PoisonedSession",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Keep run row intact after event fallback",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.commit()
        run_id = run.id

        db.add(
            RunEventModel(
                run_id="missing-run-id",
                event_type="broken",
                stage="planner",
                severity="error",
                message="break the session",
                payload_json="{}",
            )
        )
        try:
            db.commit()
        except IntegrityError:
            pass

        service = OrchestrationService()
        service._record_event(db, run_id, "planner_started", "planner", "info", "planner started")

        fresh = SessionLocal()
        try:
            persisted_run = fresh.get(RunModel, run_id)
            events = (
                fresh.query(RunEventModel)
                .filter(RunEventModel.run_id == run_id, RunEventModel.event_type == "planner_started")
                .all()
            )
        finally:
            fresh.close()
    finally:
        db.close()

    assert persisted_run is not None
    assert len(events) == 1


def test_awaiting_approval_event_is_persisted(client, tmp_path):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import OrchestrationService

    project_root = tmp_path / "awaiting_approval_project"
    project_root.mkdir()
    (project_root / "app.py").write_text("print('ready')\n")
    (project_root / "pyproject.toml").write_text('[project]\nname="demo"\n', encoding="utf-8")
    (project_root / "tests").mkdir()
    (project_root / "AGENTS.md").write_text("# Demo\n", encoding="utf-8")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="Awaiting Approval",
            source_repo_spec=str(project_root),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Simple implementation task",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="running",
            workspace_path=str(project_root),
        )
        db.add(run)
        db.commit()

        from tests.conftest import seed_pipeline_gate_artifacts

        seed_pipeline_gate_artifacts(db, run.id)

        service = OrchestrationService()
        service._stage_planner = lambda db_arg, run_id, ctx, fs: True  # type: ignore[method-assign]
        service._stage_architect = lambda db_arg, run_id, ctx: True  # type: ignore[method-assign]
        service._stage_ui = lambda db_arg, run_id, ctx: True  # type: ignore[method-assign]
        service._stage_coder = lambda db_arg, run_id, ctx, fs: True  # type: ignore[method-assign]
        service._stage_reviewer_loop = lambda db_arg, run_id, ctx, fs, workspace, source: True  # type: ignore[method-assign]
        service._stage_tester = lambda db_arg, run_id, ctx, workspace: True  # type: ignore[method-assign]
        service._stage_documentation = lambda db_arg, run_id, ctx, fs: True  # type: ignore[method-assign]
        service._verify_dependencies = lambda db_arg, run_id, workspace, source: True  # type: ignore[method-assign]
        service._finalize_deployment_gates = lambda db_arg, run_id_arg, workspace_arg, source_arg: True  # type: ignore[method-assign]

        service._pipeline(db, run.id)
        db.refresh(run)
        assert run.status == "awaiting_approval"

        events = client.get(f"/api/runs/{run.id}/events", headers=HEADERS).json()
    finally:
        db.close()

    assert any(str(event["event_type"]) == "awaiting_approval" for event in events)


def test_run_thread_endpoint_returns_persisted_entries(client, tmp_path):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.run_thread_service import RunThreadService

    project_root = tmp_path / "thread_project"
    project_root.mkdir()
    (project_root / "main.py").write_text("print('thread')\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="Thread Project",
            source_repo_spec=str(project_root),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Track run thread", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="running",
            current_stage="planner",
            workspace_path=str(project_root),
        )
        db.add(run)
        db.flush()
        run_id = run.id
        db.commit()

        thread_service = RunThreadService(db)
        session_id = thread_service.ensure_session(run_id)
        thread_service.append_entry(
            run_id,
            entry_type="planner_started",
            stage="planner",
            severity="info",
            message="Planner started",
            payload={"step": "planner"},
        )
    finally:
        db.close()

    response = client.get(f"/api/runs/{run_id}/thread", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body
    assert body[-1]["entry_type"] == "planner_started"
    assert body[-1]["message"] == "Planner started"
    assert body[-1]["session_id"] == session_id


def test_clarify_run_resumes_pipeline_and_records_answer(client, tmp_path, monkeypatch):
    import json as _json

    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.chat_orchestrator import chat_orchestrator
    from app.services.orchestration_service import run_engine
    from app.services.run_thread_service import RunThreadService

    run_engine.wait_for_idle()
    chat_orchestrator.wait_for_idle()

    project_root = tmp_path / "clarify_project"
    project_root.mkdir()
    (project_root / "main.py").write_text("print('clarify')\n")

    captured: list[str] = []
    monkeypatch.setattr(run_engine, "enqueue", lambda run_id: captured.append(run_id))

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="Clarify Project",
            source_repo_spec=str(project_root),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Implement kanban page", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="awaiting_clarification",
            current_stage="architect",
            clarification_question="Where should the page be wired?",
            clarification_stage="architect",
            clarification_context_json=_json.dumps({"question": "Where should the page be wired?"}),
            workspace_path=str(project_root),
        )
        db.add(run)
        db.flush()
        run_id = run.id
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/api/runs/{run_id}/clarify",
        json={"answer": "Wire it into the main chat surface."},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["current_stage"] == "architect"
    assert captured == [run_id]

    db = SessionLocal()
    try:
        run = db.get(RunModel, run_id)
        assert run is not None
        assert run.status == "running"
        assert run.clarification_question is None
        assert run.clarification_stage is None
        assert "Clarification answer: Wire it into the main chat surface." in (run.operator_feedback or "")
        assert run.clarification_context["answer"] == "Wire it into the main chat surface."
        assert "architect_navigation" in (run.clarification_context.get("resolved_gates") or [])

        entries = RunThreadService(db).list_entries(run_id)
    finally:
        db.close()

    assert any(entry["entry_type"] == "clarification_answered" for entry in entries)

    thread_response = client.get(f"/api/runs/{run_id}/thread", headers=HEADERS)
    assert thread_response.status_code == 200
    thread_entries = thread_response.json()
    assert any(entry["entry_type"] == "clarification_answered" for entry in thread_entries)


def test_worker_count_update_reconfigures_run_engine(client):
    from app.services.orchestration_service import run_engine

    response = client.put(
        "/api/settings",
        json={"worker_count": 3},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["worker_count"] == 3
    assert run_engine._max_workers == 3


def test_resume_inflight_runs_enqueues_running_and_pending(client):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import resume_inflight_runs, run_engine

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ResumeInflight",
            source_repo_spec="/tmp/resume-inflight",
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Resume inflight runs",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        pending_run = RunModel(project_id=project.id, task_id=task.id, status="pending")
        running_run = RunModel(project_id=project.id, task_id=task.id, status="running")
        completed_run = RunModel(project_id=project.id, task_id=task.id, status="completed")
        db.add_all([pending_run, running_run, completed_run])
        db.commit()

        captured: list[str] = []
        original_enqueue = run_engine.enqueue
        run_engine.enqueue = lambda run_id: captured.append(run_id)  # type: ignore[assignment]
        try:
            resumed = resume_inflight_runs(db)
        finally:
            run_engine.enqueue = original_enqueue  # type: ignore[assignment]
    finally:
        db.close()

    assert set(resumed) == {pending_run.id, running_run.id}
    assert set(captured) == {pending_run.id, running_run.id}


def test_resume_inflight_runs_prioritizes_later_stage_runs(client):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import resume_inflight_runs, run_engine
    from datetime import UTC, datetime, timedelta

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ResumePriority",
            source_repo_spec="/tmp/resume-priority",
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Resume priority ordering",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        older = datetime.now(UTC) - timedelta(minutes=2)
        newer = datetime.now(UTC) - timedelta(minutes=1)
        planner_run = RunModel(project_id=project.id, task_id=task.id, status="running", current_stage="planner")
        reviewer_run = RunModel(project_id=project.id, task_id=task.id, status="running", current_stage="reviewer")
        tester_run = RunModel(project_id=project.id, task_id=task.id, status="pending", current_stage="tester")
        db.add_all([planner_run, reviewer_run, tester_run])
        db.flush()
        planner_run.updated_at = older
        reviewer_run.updated_at = newer
        tester_run.updated_at = older
        db.commit()
        planner_run_id = planner_run.id
        reviewer_run_id = reviewer_run.id
        tester_run_id = tester_run.id

        captured: list[str] = []
        original_enqueue = run_engine.enqueue
        run_engine.enqueue = lambda run_id: captured.append(run_id)  # type: ignore[assignment]
        try:
            resume_inflight_runs(db, limit=3)
        finally:
            run_engine.enqueue = original_enqueue  # type: ignore[assignment]
    finally:
        db.close()

    assert captured[:3] == [tester_run_id, reviewer_run_id, planner_run_id]


def test_resume_inflight_runs_can_limit_batch_size(client):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import resume_inflight_runs, run_engine

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ResumeLimit",
            source_repo_spec="/tmp/resume-limit",
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Resume batch limit",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        runs = [
            RunModel(project_id=project.id, task_id=task.id, status="running", current_stage="planner"),
            RunModel(project_id=project.id, task_id=task.id, status="running", current_stage="reviewer"),
        ]
        db.add_all(runs)
        db.commit()

        captured: list[str] = []
        original_enqueue = run_engine.enqueue
        run_engine.enqueue = lambda run_id: captured.append(run_id)  # type: ignore[assignment]
        try:
            resumed = resume_inflight_runs(db, limit=1)
        finally:
            run_engine.enqueue = original_enqueue  # type: ignore[assignment]
    finally:
        db.close()

    assert len(resumed) == 1
    assert captured == resumed


def test_resume_run_endpoint_enqueues_resumable_run(client):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import run_engine

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ResumeEndpoint",
            source_repo_spec="/tmp/resume-endpoint",
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Resume endpoint task",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", current_stage="reviewer")
        db.add(run)
        db.commit()

        captured: list[str] = []
        original_enqueue = run_engine.enqueue
        run_engine.enqueue = lambda run_id: captured.append(run_id)  # type: ignore[assignment]
        try:
            response = client.post(f"/api/runs/{run.id}/resume", headers=HEADERS)
        finally:
            run_engine.enqueue = original_enqueue  # type: ignore[assignment]
    finally:
        db.close()

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured == [run.id]


def test_resume_run_endpoint_rejects_non_resumable_run(client):
    from app.core.enums import RunStatus
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ResumeReject",
            source_repo_spec="/tmp/resume-reject",
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Resume reject task",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        runs = [
            RunModel(project_id=project.id, task_id=task.id, status=RunStatus.COMPLETED.value),
            RunModel(project_id=project.id, task_id=task.id, status=RunStatus.BLOCKED.value),
            RunModel(project_id=project.id, task_id=task.id, status=RunStatus.CHANGES_REQUESTED.value),
        ]
        db.add_all(runs)
        db.commit()
        run_ids = [run.id for run in runs]
    finally:
        db.close()

    for run_id in run_ids:
        response = client.post(f"/api/runs/{run_id}/resume", headers=HEADERS)
        assert response.status_code == 400


def test_resume_inflight_runs_finalizes_stale_running_run(client, tmp_path):
    from datetime import UTC, datetime, timedelta

    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import resume_inflight_runs, run_engine

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ResumeStale",
            source_repo_spec=str(tmp_path),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Resume stale run", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", current_stage="coder")
        db.add(run)
        db.flush()
        run.updated_at = datetime.now(UTC) - timedelta(minutes=10)
        db.commit()

        captured: list[str] = []
        original_enqueue = run_engine.enqueue
        run_engine.enqueue = lambda run_id: captured.append(run_id)  # type: ignore[assignment]
        try:
            resumed = resume_inflight_runs(db)
        finally:
            run_engine.enqueue = original_enqueue  # type: ignore[assignment]
        db.refresh(run)
    finally:
        db.close()

    assert resumed == []
    assert captured == []
    assert run.status == "failed"
    assert "stalled" in (run.error_message or "").lower()


def test_resume_run_endpoint_rejects_stale_running_run(client, tmp_path):
    from datetime import UTC, datetime, timedelta

    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal

    project_dir = tmp_path / "resume_stale_endpoint"
    project_dir.mkdir()

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ResumeEndpointStale",
            source_repo_spec=str(project_dir),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Resume stale endpoint task", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", current_stage="reviewer")
        db.add(run)
        db.flush()
        run.updated_at = datetime.now(UTC) - timedelta(minutes=10)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    response = client.post(f"/api/runs/{run_id}/resume", headers=HEADERS)
    assert response.status_code == 400
    assert "stale" in response.json()["detail"].lower()


def test_lifespan_auto_resume_enabled_enqueues_one_inflight_run(monkeypatch):
    from fastapi.testclient import TestClient

    import app.api.main as main_module
    from app.db.session import SessionLocal
    from app.schemas.api import SettingsUpdate
    from app.services.config_service import ConfigService

    db = SessionLocal()
    try:
        ConfigService(db).update_settings(SettingsUpdate(auto_resume_enabled=True))
    finally:
        db.close()

    captured: list[int] = []

    def fake_resume_inflight_runs(db, limit=1):  # type: ignore[no-untyped-def]
        captured.append(limit)
        return []

    monkeypatch.setattr(main_module, "resume_inflight_runs", fake_resume_inflight_runs)

    with TestClient(main_module.app):
        pass

    assert captured == [1]


def test_lifespan_auto_resume_disabled_skips_resume(monkeypatch):
    from fastapi.testclient import TestClient

    import app.api.main as main_module
    from app.db.session import SessionLocal
    from app.schemas.api import SettingsUpdate
    from app.services.config_service import ConfigService

    db = SessionLocal()
    try:
        ConfigService(db).update_settings(SettingsUpdate(auto_resume_enabled=False))
    finally:
        db.close()

    captured: list[int] = []

    def fake_resume_inflight_runs(db, limit=1):  # type: ignore[no-untyped-def]
        captured.append(limit)
        return []

    monkeypatch.setattr(main_module, "resume_inflight_runs", fake_resume_inflight_runs)

    with TestClient(main_module.app):
        pass

    assert captured == []


def test_reviewer_context_includes_changed_file_snapshot(client, tmp_path):
    import json as _json

    from app.db.models import ArtifactModel, ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.file_service import FileService
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "review_workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('hello reviewer')\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ReviewerContext",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Review the patch", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="plan",
                content_json=_json.dumps(
                    {
                        "summary": "Update main",
                        "steps": [
                            {
                                "step_id": "1",
                                "title": "Update main.py",
                                "description": "Change greeting",
                                "acceptance_criteria": ["main.py prints hello reviewer"],
                            }
                        ],
                        "risks": [],
                    }
                ),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="architect",
                content_json=_json.dumps(
                    {
                        "overview": "Touch main.py",
                        "file_changes": [{"path": "main.py", "action": "modify", "rationale": "Update print"}],
                        "modules": [],
                        "dependencies": [],
                    }
                ),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="coder",
                content_json=_json.dumps(
                    {
                        "summary": "Updated main.py",
                        "file_changes": [
                            {
                                "path": "main.py",
                                "line_changes": [
                                    {"start_line": 1, "end_line": 1, "new_content": "print('hello reviewer')\n"}
                                ],
                            }
                        ],
                        "requires_operator_approval": False,
                    }
                ),
            )
        )
        db.commit()

        service = OrchestrationService()
        review_context, changed_files, structural_summaries, file_details = service._build_reviewer_context(
            db,
            run.id,
            "Review the patch",
            FileService(workspace),
            workspace,
        )
    finally:
        db.close()

    assert changed_files == ["main.py"]
    assert "Planner acceptance criteria:" in review_context
    assert "main.py prints hello reviewer" in review_context
    assert "Architect blueprint paths:" in review_context
    assert "FILE: main.py" in review_context
    assert "Declared coder change:" in review_context
    assert "Original file snapshot:" in review_context
    assert "Current file snapshot:" in review_context
    assert "print('hello reviewer')" in review_context
    assert len(structural_summaries) == 1
    assert len(file_details) == 1


def test_coder_context_includes_acceptance_criteria_and_blueprint(client, tmp_path):
    import json as _json

    from app.db.models import ArtifactModel, ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.file_service import FileService
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "coder_context_workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('hello')\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="CoderContext",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json='["secret.txt"]',
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Implement change", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="plan",
                content_json=_json.dumps(
                    {
                        "summary": "Plan",
                        "steps": [
                            {
                                "step_id": "1",
                                "title": "Update",
                                "description": "Change main",
                                "acceptance_criteria": ["main.py updated"],
                            }
                        ],
                        "risks": [],
                    }
                ),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="architect",
                content_json=_json.dumps(
                    {
                        "overview": "Modify main.py",
                        "file_changes": [{"path": "main.py", "action": "modify", "rationale": "Task requirement"}],
                        "modules": [],
                        "dependencies": [],
                    }
                ),
            )
        )
        db.commit()

        context = OrchestrationService()._build_coder_context(
            db,
            run.id,
            "Implement change",
            FileService(workspace, project.protected_files),
            workspace,
        )
    finally:
        db.close()

    assert "Acceptance criteria checklist:" in context
    assert "main.py updated" in context
    assert "Architect blueprint paths:" in context
    assert "Protected files (never patch):" in context
    assert "secret.txt" in context


def test_stage_context_includes_protected_files_for_planner_and_architect(client, tmp_path):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "stage_context_protected"
    workspace.mkdir()

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="StageContextProtected",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json='["secret.txt", "config/locked.json"]',
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Plan and design around protected assets",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="running",
            workspace_path=str(workspace),
        )
        db.add(run)
        db.commit()

        service = OrchestrationService()
        context_base = service._build_context_base(run, task.description)
        for stage in ("planner", "architect"):
            stage_context = service._stage_context(db, run, stage, context_base)
            assert "Protected files (never patch):" in stage_context
            assert "- secret.txt" in stage_context
            assert "- config/locked.json" in stage_context
    finally:
        db.close()


def test_coder_guard_rejects_destructive_full_file_replacement(tmp_path):
    from app.core.exceptions import PatchGuardError
    from app.services.file_service import FileService

    workspace = tmp_path / "coder_guard"
    workspace.mkdir()
    target = workspace / "frontend/src/components/RunHistoryList.tsx"
    target.parent.mkdir(parents=True)
    target.write_text(
        "\n".join(
            [
                "import React from 'react'",
                "import { Button } from '@/components/ui/primitives'",
                "import { runStatusLabel } from '@/types/runs'",
                "",
                "interface RunHistoryListProps {",
                "  runs: string[]",
                "  currentRunId: string | null",
                "}",
                "",
                "export function RunHistoryList({ runs, currentRunId }: RunHistoryListProps) {",
                "  return <div>{runs.join(currentRunId ?? '')}</div>",
                "}",
            ]
            + [f"export const marker{i} = {i}" for i in range(15)]
        )
        + "\n"
    )

    fs = FileService(workspace)
    try:
        fs.apply_coder_changes(
            [
                {
                    "path": "frontend/src/components/RunHistoryList.tsx",
                    "full_content": "export const RunHistoryList = () => <div>toy</div>\n",
                }
            ]
        )
    except PatchGuardError as exc:
        assert "destructive full-file replacement" in str(exc) or "removed exported or declared symbols" in str(exc)
    else:
        raise AssertionError("expected PatchGuardError")


def test_reviewer_guard_detects_structural_regression():
    from app.db.session import SessionLocal
    from app.services.change_guard import summarize_structure
    from app.services.orchestration_service import OrchestrationService

    before = "\n".join(
        [
            "import React from 'react'",
            "import { Button } from '@/components/ui/primitives'",
            "interface RunHistoryListProps {",
            "  runs: string[]",
            "  currentRunId: string | null",
            "}",
            "export function RunHistoryList({ runs, currentRunId }: RunHistoryListProps) {",
            "  return <div>{runs.join(currentRunId ?? '')}</div>",
            "}",
        ]
        + [f"export const marker{i} = {i}" for i in range(15)]
    )
    after = "export const RunHistoryList = () => <div>toy</div>\n"
    summary = summarize_structure(
        "frontend/src/components/RunHistoryList.tsx",
        before,
        after,
        True,
        True,
    )

    issues = OrchestrationService()._deterministic_review_issues(
        SessionLocal(),
        "run-test",
        [summary],
        [{"path": summary["path"], "before": before, "after": after}],
        [summary["path"]],
        "implementation",
    )
    assert issues
    assert any("Structural regression" in issue["message"] for issue in issues)
    assert issues[0]["severity"] in {"important", "critical"}


def test_tester_enforces_frontend_build_for_frontend_changes(client, tmp_path, monkeypatch):
    import json as _json

    import app.services.orchestration_service as orchestration_module
    from app.db.models import ArtifactModel, ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "frontend_validation_workspace"
    workspace.mkdir()
    (workspace / "frontend/src").mkdir(parents=True)
    (workspace / "frontend/src/App.tsx").write_text("export const App = () => null\n")
    (workspace / "frontend/package.json").write_text('{"name":"frontend","scripts":{"build":"vite build"}}\n')
    (workspace / "pyproject.toml").write_text('[project]\nname="demo"\n', encoding="utf-8")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="FrontendValidation",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Frontend implementation task",
            validation_profile="python",
            task_kind="validation",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="running",
            current_stage="tester",
            workspace_path=str(workspace),
            task_kind="validation",
        )
        db.add(run)
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="coder",
                content_json=_json.dumps(
                    {
                        "summary": "Updated frontend file",
                        "file_changes": [{"path": "frontend/src/App.tsx", "line_changes": []}],
                        "requires_operator_approval": False,
                    }
                ),
            )
        )
        db.commit()

        executed: list[str] = []

        monkeypatch.setattr(orchestration_module, "validate_command", lambda command: None)
        monkeypatch.setattr(
            orchestration_module,
            "run_command",
            lambda command, workspace_path: (executed.append(command) or (0, "ok", "")),
        )
        monkeypatch.setattr(
            orchestration_module,
            "execute_visual_checks",
            lambda *args, **kwargs: {"passed": True, "checks": []},
        )

        service = OrchestrationService()
        assert service._stage_tester(db, run.id, "Validate frontend change", workspace) is True
    finally:
        db.close()

    assert "npm --prefix frontend run build" in executed


def test_prepare_run_workspace_links_frontend_node_modules(tmp_path):
    from app.services.workspace_service import prepare_run_workspace

    source = tmp_path / "source_repo"
    (source / "frontend/node_modules/.bin").mkdir(parents=True)
    (source / "frontend/node_modules/.bin/tsc").write_text("tsc\n")
    (source / "frontend/package.json").write_text('{"name":"frontend"}\n')

    workspace = prepare_run_workspace(source, "workspace-link-test")
    linked = workspace / "frontend/node_modules"
    assert linked.exists()
    assert linked.is_symlink()
    assert linked.resolve() == (source / "frontend/node_modules").resolve()


def test_retry_run_fails_immediately_for_git_only_source(client, tmp_path):
    from app.core.enums import RunStatus
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal

    source = tmp_path / "git_only_source"
    source.mkdir()
    (source / ".git").mkdir()

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="GitOnlySource",
            source_repo_spec=str(source),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Initialize project scaffold and governance for GitOnlySource",
            validation_profile="python",
            task_kind="setup",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.FAILED.value,
            current_stage="coder",
            task_kind="setup",
            error_message="previous failure",
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    response = client.post(f"/api/runs/{run_id}/retry", headers=HEADERS)
    assert response.status_code == 400
    assert "no usable files" in response.json()["detail"].lower()


def test_run_command_prepends_workspace_node_modules_bin(tmp_path):
    from app.tools.command_runner import run_command

    workspace = tmp_path / "cmd_workspace"
    (workspace / "frontend/node_modules/.bin").mkdir(parents=True)
    shim = workspace / "frontend/node_modules/.bin/tsc"
    shim.write_text("#!/bin/sh\necho local-tsc\n", encoding="utf-8")
    shim.chmod(0o755)

    code, stdout, stderr = run_command("tsc", workspace)
    assert code == 0
    assert "local-tsc" in stdout
    assert stderr == ""


def test_stage_coder_retries_after_guard_rejection(client, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import app.services.orchestration_service as orchestration_module
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.file_service import FileService
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "coder_retry_workspace"
    workspace.mkdir()
    target = workspace / "frontend/src/types/runs.ts"
    target.parent.mkdir(parents=True)
    (workspace / "frontend/node_modules/.bin").mkdir(parents=True)
    tsc_shim = workspace / "frontend/node_modules/.bin/tsc"
    tsc_shim.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tsc_shim.chmod(0o755)
    tsc_lib = workspace / "frontend/node_modules/typescript/lib"
    tsc_lib.mkdir(parents=True)
    (tsc_lib / "tsc.js").write_text("// stub\n", encoding="utf-8")
    target.write_text(
        "\n".join(
            [
                "export interface RunSummary {",
                "  id: string",
                "  status: string",
                "  failure_class?: string | null",
                "  recovery_status?: string | null",
                "}",
            ]
            + [f"export const item{i} = {i}" for i in range(20)]
        )
        + "\n"
    )

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="CoderRetry",
            source_repo_spec=str(workspace),
            validation_profile="react",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Retry coder on guard rejection", validation_profile="react")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.commit()

        calls = {"count": 0}

        class FakeRegistry:
            def active_provider(self):
                return "ollama"

            def resolve_stage(self, stage):
                return object()

        class FakeCoderAgent:
            def __init__(self, provider):
                self.provider = provider

            def code(self, context):
                calls["count"] += 1
                if calls["count"] == 1:
                    return SimpleNamespace(
                        file_changes=[
                            {
                                "path": "frontend/src/types/runs.ts",
                                "full_content": "export const RunHistoryList = () => null\n",
                            }
                        ],
                        model_dump=lambda: {
                            "summary": "bad patch",
                            "file_changes": [
                                {
                                    "path": "frontend/src/types/runs.ts",
                                    "full_content": "export const RunHistoryList = () => null\n",
                                }
                            ],
                            "requires_operator_approval": False,
                        },
                    )
                return SimpleNamespace(
                    file_changes=[
                        {
                            "path": "frontend/src/types/runs.ts",
                            "line_changes": [
                                {
                                    "start_line": 6,
                                    "end_line": 6,
                                    "new_content": "}\n\nexport function hasRecoveryMetadata(run: RunSummary): boolean {\n  return Boolean(run.failure_class || run.recovery_status)\n}\n",
                                }
                            ],
                        }
                    ],
                    model_dump=lambda: {
                        "summary": "good patch",
                        "file_changes": [
                            {
                                "path": "frontend/src/types/runs.ts",
                                "line_changes": [
                                    {
                                        "start_line": 6,
                                        "end_line": 6,
                                        "new_content": "}\n\nexport function hasRecoveryMetadata(run: RunSummary): boolean {\n  return Boolean(run.failure_class || run.recovery_status)\n}\n",
                                    }
                                ],
                            }
                        ],
                        "requires_operator_approval": False,
                    },
                )

        monkeypatch.setattr(orchestration_module.ProviderRegistry, "get", staticmethod(lambda: FakeRegistry()))
        monkeypatch.setattr(orchestration_module, "CoderAgent", FakeCoderAgent)

        service = OrchestrationService()
        assert service._stage_coder(db, run.id, "Apply a minimal patch", FileService(workspace)) is True
    finally:
        db.close()

    content = target.read_text()
    assert calls["count"] == 2
    assert "hasRecoveryMetadata" in content
    assert "item19" in content


def test_stage_coder_rejects_non_blueprint_setup_dependency_path(client, tmp_path, monkeypatch):
    from types import SimpleNamespace

    import app.services.orchestration_service as orchestration_module
    from app.db.models import ArtifactModel, ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.file_service import FileService
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "setup_scope_workspace"
    workspace.mkdir()
    (workspace / "AGENTS.md").write_text("existing\n")
    (workspace / ".ai-copilot").mkdir()

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="SetupScope",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Initialize project scaffold and governance for SetupScope",
            validation_profile="python",
            task_kind="setup",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="running",
            task_kind="setup",
            workspace_path=str(workspace),
        )
        db.add(run)
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="architect",
                content_json=json.dumps(
                    {
                        "overview": "setup",
                        "modules": ["governance"],
                        "file_changes": [
                            {"path": "AGENTS.md", "action": "create", "rationale": "governance"},
                            {
                                "path": ".ai-copilot/architecture.md",
                                "action": "create",
                                "rationale": "architecture",
                            },
                        ],
                    }
                ),
            )
        )
        db.commit()

        class FakeRegistry:
            def active_provider(self):
                return "ollama"

            def resolve_stage(self, stage):
                return object()

        class FakeCoderAgent:
            def __init__(self, provider, tool_runtime=None):
                self.provider = provider

            def code(self, context):
                return SimpleNamespace(
                    file_changes=[{"path": "frontend/node_modules/typescript/lib/tsc.js", "full_content": "// bad\n"}],
                    model_dump=lambda: {
                        "summary": "bad setup drift",
                        "file_changes": [
                            {"path": "frontend/node_modules/typescript/lib/tsc.js", "full_content": "// bad\n"}
                        ],
                        "requires_operator_approval": False,
                    },
                )

        monkeypatch.setattr(orchestration_module.ProviderRegistry, "get", staticmethod(lambda: FakeRegistry()))
        monkeypatch.setattr(orchestration_module, "CoderAgent", FakeCoderAgent)

        service = OrchestrationService()
        with pytest.raises(orchestration_module.PatchGuardError, match="dependency path during setup"):
            service._stage_coder(db, run.id, "Patch blueprint files only", FileService(workspace))
    finally:
        db.close()


def test_pipeline_block_protect_resolve_learning_events(client, tmp_path, monkeypatch):
    """Protected-path coder guard → block_recorded → retry → code_patch_applied → block_resolved + lesson."""
    from types import SimpleNamespace

    import app.services.orchestration_service as orchestration_module
    from app.db.models import ImprovementModel, LessonModel, ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.file_service import FileService
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "block_resolve_workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('before')\n")
    (workspace / "secret.txt").write_text("protected\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="BlockResolve",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json='["secret.txt"]',
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Avoid protected secret.txt",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.commit()
        run_id = run.id

        calls = {"count": 0}

        class FakeRegistry:
            def active_provider(self):
                return "ollama"

            def resolve_stage(self, stage):
                return object()

        class FakeCoderAgent:
            def __init__(self, provider):
                self.provider = provider

            def code(self, context):
                calls["count"] += 1
                if calls["count"] == 1:
                    return SimpleNamespace(
                        file_changes=[{"path": "secret.txt", "full_content": "tampered\n"}],
                        model_dump=lambda: {
                            "summary": "bad protected patch",
                            "file_changes": [{"path": "secret.txt", "full_content": "tampered\n"}],
                            "requires_operator_approval": False,
                        },
                    )
                return SimpleNamespace(
                    file_changes=[
                        {
                            "path": "main.py",
                            "line_changes": [
                                {"start_line": 1, "end_line": 1, "new_content": "print('after')\n"}
                            ],
                        }
                    ],
                    model_dump=lambda: {
                        "summary": "good patch",
                        "file_changes": [
                            {
                                "path": "main.py",
                                "line_changes": [
                                    {"start_line": 1, "end_line": 1, "new_content": "print('after')\n"}
                                ],
                            }
                        ],
                        "requires_operator_approval": False,
                    },
                )

        monkeypatch.setattr(orchestration_module.ProviderRegistry, "get", staticmethod(lambda: FakeRegistry()))
        monkeypatch.setattr(orchestration_module, "CoderAgent", FakeCoderAgent)

        service = OrchestrationService()
        fs = FileService(workspace, project.protected_files)
        assert service._stage_coder(db, run_id, "Patch main.py only", fs) is True

        events = client.get(f"/api/runs/{run_id}/events", headers=HEADERS).json()
        event_types = [event["event_type"] for event in events]

        assert "block_recorded" in event_types
        assert "code_patch_applied" in event_types
        assert "block_resolved" in event_types
        assert event_types.index("block_recorded") < event_types.index("block_resolved")
        assert event_types.index("block_resolved") < event_types.index("code_patch_applied")

        lesson = db.query(LessonModel).filter(LessonModel.run_id == run_id).first()
        improvement = (
            db.query(ImprovementModel)
            .filter(ImprovementModel.source_run_id == run_id)
            .order_by(ImprovementModel.id.desc())
            .first()
        )
        assert lesson is not None
        assert improvement is not None
        assert improvement.title == "Avoid repeat repository safety block"
    finally:
        db.close()

    assert calls["count"] == 2
    assert (workspace / "main.py").read_text() == "print('after')\n"
    assert (workspace / "secret.txt").read_text() == "protected\n"


def test_running_run_resumes_from_current_stage(client, tmp_path):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "resume_stage_workspace"
    workspace.mkdir()
    (workspace / "seed.txt").write_text("ok\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ResumeStage",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Resume from reviewer",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="running",
            current_stage="reviewer",
            workspace_path=str(workspace),
        )
        db.add(run)
        db.commit()

        from tests.conftest import seed_pipeline_gate_artifacts

        seed_pipeline_gate_artifacts(db, run.id)

        service = OrchestrationService()
        called: list[str] = []
        service._stage_planner = lambda db_arg, run_id, ctx, fs: called.append("planner") or True  # type: ignore[method-assign]
        service._stage_architect = lambda db_arg, run_id, ctx: called.append("architect") or True  # type: ignore[method-assign]
        service._stage_ui = lambda db_arg, run_id, ctx: called.append("ui_designer") or True  # type: ignore[method-assign]
        service._stage_coder = lambda db_arg, run_id, ctx, fs: called.append("coder") or True  # type: ignore[method-assign]
        service._stage_reviewer_loop = lambda db_arg, run_id, ctx, fs, workspace_arg, source_arg: called.append("reviewer") or True  # type: ignore[method-assign]
        service._stage_tester = lambda db_arg, run_id, ctx, workspace_arg: called.append("tester") or True  # type: ignore[method-assign]
        service._stage_documentation = lambda db_arg, run_id, ctx, fs: True  # type: ignore[method-assign]
        service._verify_dependencies = lambda db_arg, run_id, workspace_arg, source_arg: True  # type: ignore[method-assign]
        service._prepare_recon = lambda *args, **kwargs: __import__(  # type: ignore[method-assign]
            "app.services.reconnaissance_service", fromlist=["ReconSnapshot"]
        ).ReconSnapshot(repo_mode="existing", stack_profile="python", payload={})
        service._run_preflight = lambda *args, **kwargs: True  # type: ignore[method-assign]
        service._capture_baseline = lambda *args, **kwargs: None  # type: ignore[method-assign]

        service._pipeline(db, run.id)
    finally:
        db.close()

    assert called == ["reviewer", "tester"]


def test_validation_task_tester_skips_llm_planning(client, tmp_path):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "validation_tester_workspace"
    workspace.mkdir()
    (workspace / "seed.txt").write_text("seed\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ValidationTester",
            source_repo_spec=str(workspace),
            validation_profile="custom",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Validation-only task",
            validation_profile="custom",
            task_kind="validation",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="running",
            current_stage="tester",
            workspace_path=str(workspace),
            task_kind="validation",
        )
        db.add(run)
        db.commit()

        service = OrchestrationService()
        service._log_provider = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("tester LLM should be skipped"))  # type: ignore[method-assign]

        service._stage_tester(db, run.id, "validate this", workspace)

        events = client.get(f"/api/runs/{run.id}/events", headers=HEADERS).json()
        artifacts = client.get(f"/api/runs/{run.id}/artifacts", headers=HEADERS).json()
    finally:
        db.close()

    assert any(event["event_type"] == "tester_llm_skipped" for event in events)
    assert any(artifact["artifact_type"] == "test_plan" for artifact in artifacts)


def test_profile_commands_are_skipped_for_non_matching_changed_files(client):
    from app.services.orchestration_service import OrchestrationService

    service = OrchestrationService()
    commands = ["ruff check .", "mypy .", "pytest -q"]
    filtered = service._profile_commands_for_changed_files("python", commands, ["notes.txt"])
    assert filtered == []
    kept = service._profile_commands_for_changed_files("python", commands, ["module.py"])
    assert kept == commands


def test_stage_architect_retries_on_empty_file_changes(client, tmp_path, monkeypatch):
    import json as _json

    from app.db.models import ArtifactModel, ProjectModel, RunEventModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.providers.fake import FakeProvider
    from app.providers.registry import ProviderRegistry
    from app.services.orchestration_service import OrchestrationService

    emitted: list[dict] = []

    def _capture_emit(_run_id: str, event: dict) -> None:
        emitted.append(event)

    monkeypatch.setattr(
        "app.services.orchestration_service.event_bus.emit",
        _capture_emit,
    )

    workspace = tmp_path / "architect_retry"
    workspace.mkdir()

    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider(
        invoke_sequence=[
            _json.dumps(
                {
                    "overview": "Design only",
                    "modules": ["core"],
                    "file_changes": [],
                    "dependencies": [],
                }
            ),
            _json.dumps(
                {
                    "overview": "Architecture",
                    "modules": ["core"],
                    "file_changes": [
                        {
                            "path": ".ai-copilot/reports/analysis.md",
                            "action": "create",
                            "rationale": "Capture analysis findings",
                        }
                    ],
                    "dependencies": [],
                }
            ),
        ]
    )
    registry.reload({})

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ArchitectRetry",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Analyze repository structure",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="running",
            workspace_path=str(workspace),
            task_kind="analysis",
        )
        db.add(run)
        db.commit()
        run_id = run.id

        service = OrchestrationService()
        context = service._build_context_base(db, run, run, task.description)
        stage_context = service._stage_context(db, run, "architect", context)
        assert service._stage_architect(db, run_id, stage_context) is True

        artifact = (
            db.query(ArtifactModel)
            .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == "architect")
            .one()
        )
        payload = _json.loads(artifact.content_json)
        assert len(payload.get("file_changes") or []) == 1

        reject_events = (
            db.query(RunEventModel)
            .filter(
                RunEventModel.run_id == run_id,
                RunEventModel.event_type == "architect_schema_rejected",
            )
            .all()
        )
        assert len(reject_events) == 1
        schema_emits = [event for event in emitted if event.get("type") == "architect_schema_rejected"]
        assert len(schema_emits) == 1
        assert schema_emits[0].get("severity") == "warning"
        assert schema_emits[0].get("message")
    finally:
        db.close()


def test_reviewer_missing_context_fails_fast(client, tmp_path):
    import json as _json

    from app.db.models import ArtifactModel, ProjectModel, RunEventModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.providers.fake import FakeProvider
    from app.providers.registry import ProviderRegistry
    from app.services.file_service import FileService
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "review_fail_fast"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('review me')\n")

    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider(
        responses={
            "reviewer": _json.dumps(
                {
                    "approved": False,
                    "summary": "Code diff not provided; unable to verify changes.",
                    "issues": [
                        {"severity": "warn", "file_path": "main.py", "message": "Need visible patch context"}
                    ],
                    "suggestions": [],
                }
            )
        }
    )
    registry.reload({})

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ReviewerFailFast",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Review the patch", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="coder",
                content_json=_json.dumps(
                    {
                        "summary": "Updated main.py",
                        "file_changes": [
                            {
                                "path": "main.py",
                                "line_changes": [
                                    {"start_line": 1, "end_line": 1, "new_content": "print('review me')\n"}
                                ],
                            }
                        ],
                        "requires_operator_approval": False,
                    }
                ),
            )
        )
        db.commit()

        service = OrchestrationService()
        result = service._stage_reviewer_loop(
            db,
            run.id,
            "Review the patch",
            FileService(workspace),
            workspace,
            workspace,
        )
        db.refresh(run)
        events = (
            db.query(RunEventModel)
            .filter(RunEventModel.run_id == run.id)
            .order_by(RunEventModel.id.asc())
            .all()
        )
    finally:
        db.close()

    assert result is False
    assert run.status == "changes_requested"
    assert "Reviewer could not validate the patch with the available context" in (run.error_message or "")
    event_types = [event.event_type for event in events]
    assert "reviewer_attempt_started" in event_types
    assert "reviewer_requested_changes" in event_types
    assert "reviewer_failed_fast" in event_types
    assert "run_changes_requested" in event_types
    assert "reviewer_retrying_coder" not in event_types


def test_stage_tester_runs_profile_and_skips_forbidden_llm_commands(client, tmp_path):
    import json as _json

    from app.db.models import AppConfigModel, ProjectModel, RunEventModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.providers.fake import FakeProvider
    from app.providers.registry import ProviderRegistry
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "tester_workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('ok')\n")

    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider(
        responses={
            "tester": _json.dumps(
                {
                    "passed": True,
                    "summary": "Mixed validation plan",
                    "commands": [
                        {
                            "command": "curl -X POST http://localhost:8000/api/health",
                            "description": "Should be skipped",
                        },
                        {"command": "python3 -c \"print(1)\"", "description": "Allowed extra check"},
                    ],
                    "notes": [],
                }
            )
        }
    )
    registry.reload({})

    db = SessionLocal()
    try:
        profiles_row = (
            db.query(AppConfigModel).filter(AppConfigModel.key == "validation_profiles_json").first()
        )
        if profiles_row:
            profiles_row.value = _json.dumps({"python": ["python3 -m compileall ."]})
        else:
            db.add(
                AppConfigModel(
                    key="validation_profiles_json",
                    value=_json.dumps({"python": ["python3 -m compileall ."]}),
                )
            )
        db.commit()

        project = ProjectModel(
            name="TesterProfile",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Validate", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.commit()

        service = OrchestrationService()
        result = service._stage_tester(db, run.id, "Validate", workspace)
        db.refresh(run)
        events = (
            db.query(RunEventModel)
            .filter(RunEventModel.run_id == run.id)
            .order_by(RunEventModel.id.asc())
            .all()
        )
    finally:
        db.close()

    assert result is True
    event_types = [event.event_type for event in events]
    assert "validation_started" in event_types
    assert "validation_result" in event_types
    assert "validation_rejected" in event_types
    rejected = [event for event in events if event.event_type == "validation_rejected"]
    assert any("forbidden pattern" in event.message for event in rejected)
    assert run.status == "running"


def test_stage_tester_blocks_frontend_scaffold_missing(client, tmp_path):
    import json as _json

    from app.db.models import AppConfigModel, ProjectModel, RunEventModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.providers.fake import FakeProvider
    from app.providers.registry import ProviderRegistry
    from app.services.orchestration_service import OrchestrationService
    from app.tools.lint_runner import FRONTEND_SCAFFOLD_MESSAGE

    workspace = tmp_path / "scaffold_workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('ok')\n", encoding="utf-8")

    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider(
        responses={
            "tester": _json.dumps(
                {
                    "passed": True,
                    "summary": "Fullstack plan",
                    "dry_run_steps": [
                        {
                            "command": "npm --prefix frontend run build",
                            "description": "Frontend build",
                        }
                    ],
                    "visual_checks": [],
                    "visual_checks_skip_reason": "No UI implemented yet",
                    "commands": [],
                    "notes": [],
                }
            )
        }
    )
    registry.reload({})

    db = SessionLocal()
    try:
        profiles_row = (
            db.query(AppConfigModel).filter(AppConfigModel.key == "validation_profiles_json").first()
        )
        profile_payload = _json.dumps(
            {
                "fullstack": [
                    "ruff check .",
                    "npm --prefix frontend run build",
                ]
            }
        )
        if profiles_row:
            profiles_row.value = profile_payload
        else:
            db.add(AppConfigModel(key="validation_profiles_json", value=profile_payload))
        db.commit()

        project = ProjectModel(
            name="ScaffoldTester",
            source_repo_spec=str(workspace),
            validation_profile="fullstack",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Validate backend change",
            validation_profile="fullstack",
        )
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.commit()

        service = OrchestrationService()
        result = service._stage_tester(db, run.id, "Validate", workspace)
        db.refresh(run)
        events = (
            db.query(RunEventModel)
            .filter(RunEventModel.run_id == run.id)
            .order_by(RunEventModel.id.asc())
            .all()
        )
    finally:
        db.close()

    assert result is False
    assert run.status == "blocked"
    assert run.error_message == FRONTEND_SCAFFOLD_MESSAGE
    event_types = [event.event_type for event in events]
    assert "frontend_scaffold_missing" in event_types
    assert "block_recorded" in event_types
    scaffold_events = [event for event in events if event.event_type == "frontend_scaffold_missing"]
    assert scaffold_events
    assert "ENOENT" not in (scaffold_events[0].message or "")


def test_stage_tester_blocks_frontend_without_visual_plan(client, tmp_path):
    import json as _json

    from app.db.models import ArtifactModel, ProjectModel, RunEventModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.providers.fake import FakeProvider
    from app.providers.registry import ProviderRegistry
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "tester_visual_workspace"
    workspace.mkdir()
    frontend_dir = workspace / "frontend" / "src"
    frontend_dir.mkdir(parents=True)
    (frontend_dir / "App.tsx").write_text("export default function App(){return null}\n")

    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider(
        responses={
            "tester": _json.dumps(
                {
                    "passed": True,
                    "summary": "Missing visual plan",
                    "dry_run_steps": [],
                    "visual_checks": [],
                    "commands": [],
                    "notes": [],
                }
            )
        }
    )
    registry.reload({})

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="TesterVisual",
            source_repo_spec=str(workspace),
            validation_profile="react",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="UI tweak", validation_profile="react")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="coder",
                content_json=_json.dumps(
                    {
                        "summary": "Updated App.tsx",
                        "file_changes": [{"path": "frontend/src/App.tsx", "line_changes": []}],
                        "requires_operator_approval": False,
                    }
                ),
            )
        )
        db.commit()

        service = OrchestrationService()
        result = service._stage_tester(db, run.id, "Validate UI", workspace)
        db.refresh(run)
        events = (
            db.query(RunEventModel)
            .filter(RunEventModel.run_id == run.id)
            .order_by(RunEventModel.id.asc())
            .all()
        )
    finally:
        db.close()

    assert result is False
    assert run.status == "blocked"
    assert "visual_checks" in (run.error_message or "").lower()
    assert "visual_checks_missing" in [event.event_type for event in events]


def test_stage_tester_accepts_visual_skip_reason_for_frontend(client, tmp_path):
    import json as _json

    from app.db.models import ArtifactModel, ProjectModel, RunEventModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.providers.fake import FakeProvider
    from app.providers.registry import ProviderRegistry
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "tester_visual_skip_workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('ok')\n")

    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider(
        responses={
            "validate ui": _json.dumps(
                {
                    "passed": True,
                    "summary": "Deferred visual plan",
                    "dry_run_steps": [],
                    "visual_checks": [],
                    "visual_checks_skip_reason": "Headless CI — operator will verify in IDE browser panel",
                    "commands": [],
                    "notes": [],
                }
            )
        }
    )
    registry.reload({})

    db = SessionLocal()
    try:
        from app.db.models import AppConfigModel

        profiles_row = (
            db.query(AppConfigModel).filter(AppConfigModel.key == "validation_profiles_json").first()
        )
        if profiles_row:
            profiles_row.value = _json.dumps({"python": ["python3 -m compileall ."]})
        else:
            db.add(
                AppConfigModel(
                    key="validation_profiles_json",
                    value=_json.dumps({"python": ["python3 -m compileall ."]}),
                )
            )
        db.commit()

        project = ProjectModel(
            name="TesterVisualSkip",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="UI tweak", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="ui_design",
                content_json=_json.dumps(
                    {
                        "layout_description": "Dashboard",
                        "components": [{"name": "App", "component_type": "page", "props": {}}],
                        "styling_notes": "tailwind",
                        "accessibility_notes": [],
                    }
                ),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="coder",
                content_json=_json.dumps(
                    {
                        "summary": "Updated main.py",
                        "file_changes": [{"path": "main.py", "line_changes": []}],
                        "requires_operator_approval": False,
                    }
                ),
            )
        )
        db.commit()

        service = OrchestrationService()
        result = service._stage_tester(db, run.id, "Validate UI", workspace)
        db.refresh(run)
        events = (
            db.query(RunEventModel)
            .filter(RunEventModel.run_id == run.id)
            .order_by(RunEventModel.id.asc())
            .all()
        )
    finally:
        db.close()

    assert result is True
    assert run.status == "running"
    assert "visual_checks_skipped" in [event.event_type for event in events]


def test_stage_tester_optional_command_failure_does_not_block(client, tmp_path, monkeypatch):
    import json as _json

    from app.db.models import ArtifactModel, ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "tester_optional_workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('ok')\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="TesterOptional",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Validate", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="running", workspace_path=str(workspace))
        db.add(run)
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="coder",
                content_json=_json.dumps(
                    {
                        "summary": "Updated main.py",
                        "file_changes": [{"path": "main.py", "line_changes": []}],
                    }
                ),
            )
        )
        db.commit()

        monkeypatch.setattr("app.services.orchestration_service.validate_command", lambda command: None)
        monkeypatch.setattr(
            "app.services.orchestration_service.get_profile_commands",
            lambda profiles_json, profile: ["python3 -m compileall ."],
        )
        calls: list[str] = []

        def fake_run_command(command: str, cwd):
            calls.append(command)
            if command.startswith("python3 -m compileall"):
                return 0, "ok", ""
            return 127, "", "missing"

        monkeypatch.setattr("app.services.orchestration_service.run_command", fake_run_command)
        service = OrchestrationService()
        service._save_artifact = lambda *args, **kwargs: None  # type: ignore[method-assign]
        service._log_provider = lambda *args, **kwargs: None  # type: ignore[method-assign]

        class FakePlan:
            commands = [type("Cmd", (), {"command": "rg missing_symbol main.py"})()]
            dry_run_steps = []
            visual_checks = []

            def model_dump(self):
                return {"passed": True, "summary": "plan", "commands": [], "dry_run_steps": [], "notes": []}

        monkeypatch.setattr(
            "app.services.orchestration_service.TesterAgent",
            lambda provider: type("Agent", (), {"test_plan": lambda self, ctx: FakePlan()})(),
        )

        result = service._stage_tester(db, run.id, "Validate", workspace)
        db.refresh(run)
    finally:
        db.close()

    assert result is True
    assert run.status == "running"
    assert any(cmd.startswith("python3 -m compileall -q main.py") for cmd in calls)
    assert any(cmd.startswith("rg ") for cmd in calls)


def test_websocket_requires_token(client, tmp_path):
    project_dir = tmp_path / "ws_project"
    project_dir.mkdir()
    (project_dir / "main.py").write_text("print('hi')\n")
    project_id = client.post(
        "/api/projects",
        json={
            "name": "WsProject",
            "source_repo_spec": str(project_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    ).json()["id"]

    session_id = client.post(
        "/api/chat/sessions",
        json={"project_id": project_id, "title": "WS", "mode": "general"},
        headers=HEADERS,
    ).json()["id"]

    for path in (
        "/api/ws/events",
        "/api/ws/runs/example-run",
        f"/api/ws/chat/{session_id}",
        f"/api/ws/terminal/term-1?project_id={project_id}",
    ):
        try:
            with client.websocket_connect(path):
                raise AssertionError(f"unauthenticated websocket unexpectedly connected: {path}")
        except WebSocketDisconnect as exc:
            assert exc.code == 1008


def test_pick_directory(client, monkeypatch):
    from app.tools.dialog_service import PickDirectoryResult

    monkeypatch.setattr(
        "app.tools.dialog_service.pick_directory",
        lambda **_: PickDirectoryResult(path="/tmp/selected-project", cancelled=False),
    )
    r = client.post("/api/dialog/pick-directory", json={}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["cancelled"] is False
    assert body["path"] == "/tmp/selected-project"
    assert body["error"] is None

    monkeypatch.setattr(
        "app.tools.dialog_service.pick_directory",
        lambda **_: PickDirectoryResult(path=None, cancelled=True),
    )
    r = client.post("/api/dialog/pick-directory", json={"prompt": "Pick one"}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {"cancelled": True, "path": None, "error": None}

    monkeypatch.setattr(
        "app.tools.dialog_service.pick_directory",
        lambda **_: PickDirectoryResult(path=None, cancelled=True, error="timeout"),
    )
    r = client.post("/api/dialog/pick-directory", json={}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {"cancelled": True, "path": None, "error": "timeout"}


def test_path_traversal(client, tmp_path):
    # Create project
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    (proj_dir / "main.py").write_text("x=1\n")
    r = client.post(
        "/api/projects",
        json={
            "name": "Test",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    pid = r.json()["id"]
    # Use encoded traversal segments so the raw path contains ..
    r = client.put(
        f"/api/projects/{pid}/files/%2E%2E%2F%2E%2E%2F%2E%2E%2Fetc%2Fpasswd",
        json={"content": "hack"},
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_project_delete_with_improvements(client, tmp_path):
    from app.db.models import ImprovementModel, ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.learning_service import LearningService

    workspace = tmp_path / "delete_with_improvements"
    workspace.mkdir()

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="DeleteWithImprovements",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Fix validation issue",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="blocked",
            current_stage="tester",
            error_message="Validation failed",
            workspace_path=str(workspace),
        )
        db.add(run)
        db.commit()
        LearningService(db).finalize_terminal_run(run.id)
        project_id = project.id
        assert (
            db.query(ImprovementModel)
            .filter(ImprovementModel.project_id == project_id)
            .count()
            >= 1
        )
    finally:
        db.close()

    response = client.delete(f"/api/projects/{project_id}", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() == {"ok": True}

    db = SessionLocal()
    try:
        assert db.query(ProjectModel).filter(ProjectModel.id == project_id).first() is None
        assert (
            db.query(ImprovementModel)
            .filter(ImprovementModel.project_id == project_id)
            .count()
            == 0
        )
    finally:
        db.close()


def test_create_project_triggers_setup_run(client, tmp_path, monkeypatch):
    enqueued: list[str] = []
    monkeypatch.setattr(
        "app.services.setup_run_service.run_engine.enqueue",
        lambda run_id: enqueued.append(run_id),
    )
    proj_dir = tmp_path / "setup_trigger_proj"
    proj_dir.mkdir()
    r = client.post(
        "/api/projects",
        json={
            "name": "SetupTrigger",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert r.status_code == 200
    project_id = r.json()["id"]
    assert enqueued
    db = SessionLocal()
    try:
        from app.db.models import RunModel, TaskModel

        setup_run = (
            db.query(RunModel)
            .join(TaskModel, TaskModel.id == RunModel.task_id)
            .filter(TaskModel.project_id == project_id, RunModel.task_kind == "setup")
            .first()
        )
        assert setup_run is not None
        assert setup_run.status in ("pending", "running")
    finally:
        db.close()


def test_create_project_rejects_missing_source_path(client, tmp_path):
    missing = tmp_path / "does_not_exist"
    response = client.post(
        "/api/projects",
        json={
            "name": "MissingSource",
            "source_repo_spec": str(missing),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]


def test_create_project_rejects_run_workspace_path(client, tmp_path):
    from app.services.workspace_service import runs_root

    workspace_like = runs_root() / "fake-project-source"
    workspace_like.mkdir(parents=True, exist_ok=True)
    response = client.post(
        "/api/projects",
        json={
            "name": "WorkspaceSource",
            "source_repo_spec": str(workspace_like),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert response.status_code == 400
    assert "inside run workspaces" in response.json()["detail"]


def test_project_update(client, tmp_path):
    proj_dir = tmp_path / "update_proj"
    proj_dir.mkdir()
    (proj_dir / "main.py").write_text("x=1\n")
    r = client.post(
        "/api/projects",
        json={
            "name": "UpdateTest",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert r.status_code == 200
    pid = r.json()["id"]

    new_dir = tmp_path / "updated_proj"
    new_dir.mkdir()
    r = client.put(
        f"/api/projects/{pid}",
        json={
            "name": "UpdatedName",
            "description": "Updated description",
            "source_repo_spec": str(new_dir),
            "validation_profile": "react",
        },
        headers=HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "UpdatedName"
    assert body["description"] == "Updated description"
    assert body["validation_profile"] == "react"
    assert body["source_repo_spec"] == str(new_dir.resolve())


def test_project_update_rejects_missing_source_path_and_preserves_existing(client, tmp_path):
    proj_dir = tmp_path / "update_missing_proj"
    proj_dir.mkdir()
    response = client.post(
        "/api/projects",
        json={
            "name": "UpdateMissingPath",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert response.status_code == 200
    project_id = response.json()["id"]

    missing = tmp_path / "typo_missing_path"
    update = client.put(
        f"/api/projects/{project_id}",
        json={"source_repo_spec": str(missing)},
        headers=HEADERS,
    )
    assert update.status_code == 400

    fetched = client.get(f"/api/projects/{project_id}", headers=HEADERS)
    assert fetched.status_code == 200
    assert fetched.json()["source_repo_spec"] == str(proj_dir.resolve())


def test_file_rename(client, tmp_path):
    proj_dir = tmp_path / "rename_proj"
    proj_dir.mkdir()
    (proj_dir / "old.py").write_text("x=1\n")
    r = client.post(
        "/api/projects",
        json={
            "name": "RenameTest",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    pid = r.json()["id"]
    r = client.post(
        f"/api/projects/{pid}/files/old.py/rename",
        json={"new_path": "new.py"},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["path"] == "new.py"
    tree = client.get(f"/api/projects/{pid}/tree", headers=HEADERS).json()
    paths = [i["path"] for i in tree["items"]]
    assert "new.py" in paths
    assert "old.py" not in paths


def test_file_tree_skips_noise_dirs(client, tmp_path):
    proj_dir = tmp_path / "clean_tree"
    proj_dir.mkdir()
    (proj_dir / "src").mkdir()
    (proj_dir / "src" / "main.py").write_text("x = 1\n")
    (proj_dir / "node_modules").mkdir()
    (proj_dir / "node_modules" / "pkg").mkdir()
    (proj_dir / "node_modules" / "pkg" / "index.js").write_text("")
    (proj_dir / "__pycache__").mkdir()
    (proj_dir / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"")
    r = client.post(
        "/api/projects",
        json={
            "name": "CleanTree",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    pid = r.json()["id"]
    paths = [i["path"] for i in client.get(f"/api/projects/{pid}/tree", headers=HEADERS).json()["items"]]
    assert "src/main.py" in paths
    assert not any("node_modules" in p for p in paths)
    assert not any("__pycache__" in p for p in paths)


def test_file_tree_nested_paths(client, tmp_path):
    proj_dir = tmp_path / "nested_tree"
    proj_dir.mkdir()
    (proj_dir / "backend").mkdir()
    (proj_dir / "backend" / "app").mkdir()
    (proj_dir / "backend" / "app" / "main.py").write_text("print('hi')\n")
    (proj_dir / "README.md").write_text("# test\n")
    r = client.post(
        "/api/projects",
        json={
            "name": "NestedTree",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    pid = r.json()["id"]
    tree = client.get(f"/api/projects/{pid}/tree", headers=HEADERS).json()
    paths = [i["path"] for i in tree["items"]]
    assert "backend" in paths
    assert "backend/app" in paths
    assert "backend/app/main.py" in paths
    assert "README.md" in paths
    assert all("children" not in i for i in tree["items"])


def test_git_status_empty_repo(client, tmp_path):
    proj_dir = tmp_path / "git_proj"
    proj_dir.mkdir()
    (proj_dir / "main.py").write_text("x=1\n")
    r = client.post(
        "/api/projects",
        json={
            "name": "GitTest",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert r.status_code == 200
    pid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}/git/status", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "staged" in body
    assert "unstaged" in body
    assert "untracked" in body
    assert any(f["path"] == "main.py" for f in body["untracked"])


def test_git_commit_stages_untracked_and_clears_status(client, tmp_path):
    proj_dir = tmp_path / "git_commit_proj"
    proj_dir.mkdir()
    (proj_dir / "main.py").write_text("x=1\n")
    r = client.post(
        "/api/projects",
        json={
            "name": "GitCommitTest",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    pid = r.json()["id"]
    r = client.post(
        f"/api/projects/{pid}/git/commit",
        json={"message": "track main"},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json().get("sha")
    r = client.get(f"/api/projects/{pid}/git/status", headers=HEADERS)
    body = r.json()
    assert body["staged"] == []
    assert body["unstaged"] == []
    assert body["untracked"] == []
    r = client.post(
        f"/api/projects/{pid}/git/commit",
        json={"message": "nothing to commit"},
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_retry_stores_operator_feedback(client, tmp_path):

    from app.core.enums import RunStatus
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.orchestration_service import OrchestrationService

    workspace = tmp_path / "retry_feedback"
    workspace.mkdir()
    (workspace / "main.py").write_text("x = 1\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="RetryFeedback",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Fix the implementation",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.CHANGES_REQUESTED.value,
            workspace_path=str(workspace),
            error_message="Needs fixes",
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    response = client.post(
        f"/api/runs/{run_id}/retry",
        json={"feedback": "Address reviewer notes on main.py"},
        headers=HEADERS,
    )
    assert response.status_code == 200

    db = SessionLocal()
    try:
        run = db.get(RunModel, run_id)
        assert run is not None
        assert run.operator_feedback == "Address reviewer notes on main.py"
        context = OrchestrationService()._build_context_base(run, run.task.description)
        assert "Operator feedback:" in context
        assert "Address reviewer notes on main.py" in context
    finally:
        db.close()


def test_retry_failed_run(client, tmp_path):
    from app.core.enums import RunStatus
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal

    source = tmp_path / "retry_failed_source"
    source.mkdir()
    (source / "main.py").write_text("print('source')\n", encoding="utf-8")
    workspace = tmp_path / "retry_failed_workspace"
    workspace.mkdir()
    (workspace / "stale.py").write_text("stale drift\n", encoding="utf-8")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="RetryFailed",
            source_repo_spec=str(source),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Extend backend/app/services/web_search_service.py. Update tests.",
            validation_profile="python",
            task_kind="validation",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.FAILED.value,
            workspace_path=str(workspace),
            error_message="Provider timeout",
            task_kind="validation",
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    response = client.post(f"/api/runs/{run_id}/retry", json={}, headers=HEADERS)
    assert response.status_code == 200

    db = SessionLocal()
    try:
        run = db.get(RunModel, run_id)
        task = db.get(TaskModel, run.task_id)
        assert run is not None
        assert task is not None
        assert run.status in (RunStatus.PENDING.value, RunStatus.RUNNING.value)
        assert run.error_message is None
        assert run.task_kind == "implementation"
        assert task.task_kind == "implementation"
        assert run.workspace_path != str(workspace)
        assert Path(run.workspace_path).is_dir()
        assert not (Path(run.workspace_path) / "stale.py").exists()
        assert (Path(run.workspace_path) / "main.py").exists()
    finally:
        db.close()


def test_cleanup_failed_runs(client, tmp_path):
    from app.core.enums import RunStatus
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal

    workspace = tmp_path / "cleanup_failed"
    workspace.mkdir()

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="CleanupFailed",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Ship feature",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        failed = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.FAILED.value,
            error_message="boom",
        )
        completed = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.COMPLETED.value,
        )
        db.add_all([failed, completed])
        db.commit()
        failed_id = failed.id
        completed_id = completed.id
        project_id = project.id
    finally:
        db.close()

    response = client.post("/api/runs/cleanup", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["deleted_count"] == 1
    assert failed_id in body["deleted_run_ids"]
    assert completed_id not in body["deleted_run_ids"]

    db = SessionLocal()
    try:
        assert db.get(RunModel, failed_id) is None
        assert db.get(RunModel, completed_id) is not None
        scoped = client.post(f"/api/runs/cleanup?project_id={project_id}", headers=HEADERS)
        assert scoped.status_code == 200
        assert scoped.json()["deleted_count"] == 0
    finally:
        db.close()


def test_learning_settings_round_trip(client):
    response = client.put(
        "/api/settings",
        json={
            "learning_auto_trial_enabled": False,
            "learning_min_trial_runs": 5,
            "learning_min_success_rate_delta_pct": 12.5,
            "learning_max_harmful_rate_pct": 20.0,
            "learning_min_confidence": 0.7,
        },
        headers=HEADERS,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["learning_auto_trial_enabled"] is False
    assert body["learning_min_trial_runs"] == 5
    assert body["learning_min_success_rate_delta_pct"] == 12.5
    assert body["learning_max_harmful_rate_pct"] == 20.0
    assert body["learning_min_confidence"] == 0.7


def test_project_improvements_endpoint_and_override(client, tmp_path):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.learning_service import LearningService

    workspace = tmp_path / "improvements_api"
    workspace.mkdir()

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ImprovementsAPI",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Fix validation issue",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="blocked",
            current_stage="tester",
            error_message="Validation failed",
            workspace_path=str(workspace),
        )
        db.add(run)
        db.commit()
        LearningService(db).finalize_terminal_run(run.id)
        project_id = project.id
    finally:
        db.close()

    improvements = client.get(f"/api/projects/{project_id}/improvements", headers=HEADERS)
    assert improvements.status_code == 200
    body = improvements.json()
    assert len(body) == 1
    improvement_id = body[0]["id"]
    assert body[0]["status"] in {"candidate", "trialing"}

    detail = client.get(f"/api/improvements/{improvement_id}", headers=HEADERS)
    assert detail.status_code == 200

    override = client.post(
        f"/api/improvements/{improvement_id}/override",
        json={"status": "approved", "scope": "global"},
        headers=HEADERS,
    )
    assert override.status_code == 200
    assert override.json()["status"] == "approved"
    assert override.json()["scope"] == "global"


def test_rollback_workspace_recreates_from_source(client, tmp_path):
    from app.core.enums import RunStatus
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.workspace_service import runs_root

    source = tmp_path / "rollback_source"
    source.mkdir()
    (source / "main.py").write_text("source version\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="RollbackWorkspace",
            source_repo_spec=str(source),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Test rollback workspace", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.CHANGES_REQUESTED.value,
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    workspace = runs_root() / run_id
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "main.py").write_text("mutated workspace\n")

    db = SessionLocal()
    try:
        run = db.get(RunModel, run_id)
        run.workspace_path = str(workspace)
        db.commit()
    finally:
        db.close()

    response = client.post(f"/api/runs/{run_id}/rollback-workspace", headers=HEADERS)
    assert response.status_code == 200
    assert (workspace / "main.py").read_text() == "source version\n"


def test_approve_snapshot_and_rollback_promote(client, tmp_path):
    import json as _json

    from app.core.enums import RunStatus
    from app.db.models import ArtifactModel, ProjectModel, RunEventModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.snapshot_service import SNAPSHOTS_ROOT
    from app.services.workspace_service import runs_root

    source = tmp_path / "promote_source"
    source.mkdir()
    (source / "main.py").write_text("original source\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="PromoteRollback",
            source_repo_spec=str(source),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Promote test", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.AWAITING_APPROVAL.value,
        )
        db.add(run)
        db.flush()
        workspace = runs_root() / run.id
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "main.py").write_text("promoted content\n")
        run.workspace_path = str(workspace)
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="coder",
                content_json=_json.dumps(
                    {
                        "summary": "Change main.py",
                        "file_changes": [{"path": "main.py", "line_changes": []}],
                        "requires_operator_approval": False,
                    }
                ),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="test_plan",
                content_json=_json.dumps({"passed": True, "summary": "ok", "dry_run_steps": []}),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="pre_deploy_supervisor",
                content_json=_json.dumps({"approved": True, "summary": "ok", "plan_gaps": []}),
            )
        )
        db.add(
            RunEventModel(
                run_id=run.id,
                event_type="dry_run_result",
                stage="tester",
                severity="info",
                message="exit=0",
                payload_json="{}",
            )
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    approve = client.post(f"/api/runs/{run_id}/approve", json={"comment": ""}, headers=HEADERS)
    assert approve.status_code == 200
    assert (source / "main.py").read_text() == "promoted content\n"
    assert (SNAPSHOTS_ROOT / run_id / "main.py").read_text() == "original source\n"

    (source / "main.py").write_text("after promote edit\n")

    rollback = client.post(f"/api/runs/{run_id}/rollback-promote", headers=HEADERS)
    assert rollback.status_code == 200
    assert rollback.json()["restored_files"] == 1
    assert (source / "main.py").read_text() == "original source\n"

    run_body = client.get(f"/api/runs/{run_id}", headers=HEADERS).json()
    assert run_body["status"] == RunStatus.CHANGES_REQUESTED.value
    assert run_body["promote_snapshot"] is None


def test_approve_runs_supervisor_and_writes_docs(client, tmp_path):
    import json as _json

    from app.core.enums import RunStatus
    from app.db.models import ArtifactModel, ProjectModel, RunEventModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.providers.fake import FakeProvider
    from app.providers.registry import ProviderRegistry
    from app.services.workspace_service import runs_root

    source = tmp_path / "supervisor_source"
    source.mkdir()
    (source / "main.py").write_text("original\n")

    doc_path = ".ai-copilot/plans/deployed.md"
    doc_content = "# Deployed\n\nSynced after promotion.\n"

    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider(
        default_response='{"content":"ok","tool_calls":[],"finish_reason":"stop"}',
        responses={
            "post-deployment": _json.dumps(
                {
                    "approved": True,
                    "summary": "Plan reconciled with deployment",
                    "plan_gaps": [],
                    "doc_updates": [
                        {
                            "path": doc_path,
                            "content": doc_content,
                            "rationale": "Keep plan artifact aligned with promoted code",
                        }
                    ],
                }
            )
        },
    )
    registry.reload({})

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="SupervisorApprove",
            source_repo_spec=str(source),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Ship feature", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.AWAITING_APPROVAL.value,
            task_kind="implementation",
        )
        db.add(run)
        db.flush()
        workspace = runs_root() / run.id
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "main.py").write_text("promoted content\n")
        run.workspace_path = str(workspace)
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="plan",
                content_json=_json.dumps(
                    {
                        "summary": "Plan",
                        "steps": [
                            {
                                "step_id": "1",
                                "title": "Ship",
                                "description": "Update main.py",
                                "acceptance_criteria": ["main.py updated"],
                            }
                        ],
                        "risks": [],
                    }
                ),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="coder",
                content_json=_json.dumps(
                    {
                        "summary": "Change main.py",
                        "file_changes": [{"path": "main.py", "line_changes": []}],
                        "requires_operator_approval": False,
                    }
                ),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="test_plan",
                content_json=_json.dumps({"passed": True, "summary": "ok", "dry_run_steps": []}),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="pre_deploy_supervisor",
                content_json=_json.dumps({"approved": True, "summary": "ok", "plan_gaps": []}),
            )
        )
        db.add(
            RunEventModel(
                run_id=run.id,
                event_type="dry_run_result",
                stage="tester",
                severity="info",
                message="exit=0",
                payload_json="{}",
            )
        )
        db.commit()
        run_id = run.id
    finally:
        db.close()

    approve = client.post(f"/api/runs/{run_id}/approve", json={"comment": "ship it"}, headers=HEADERS)
    assert approve.status_code == 200
    assert (source / "main.py").read_text() == "promoted content\n"
    assert (source / doc_path).read_text() == doc_content

    db = SessionLocal()
    try:
        supervisor = (
            db.query(ArtifactModel)
            .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == "supervisor")
            .one()
        )
        payload = _json.loads(supervisor.content_json)
        assert payload["approved"] is True
        assert doc_path in payload.get("written_paths", [])

        events = (
            db.query(RunEventModel)
            .filter(RunEventModel.run_id == run_id, RunEventModel.event_type == "supervisor_complete")
            .all()
        )
        assert events
    finally:
        db.close()


def test_approve_run_returns_warnings_for_report_substitution(client, tmp_path):
    import json as _json

    from app.core.enums import RunStatus
    from app.db.models import ArtifactModel, ProjectModel, RunEventModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.services.workspace_service import runs_root

    source = tmp_path / "warning_source"
    source.mkdir()
    (source / "main.py").write_text("original\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="Warning Approval",
            source_repo_spec=str(source),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Create a nice and professional Kanban page.",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.AWAITING_APPROVAL.value,
            task_kind="implementation",
        )
        db.add(run)
        db.flush()
        run_id = run.id
        workspace = runs_root() / run.id
        (workspace / ".ai-copilot" / "reports").mkdir(parents=True, exist_ok=True)
        (workspace / ".ai-copilot" / "reports" / "kanban-implementation.md").write_text("# Report only\n")
        run.workspace_path = str(workspace)
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="coder",
                content_json=_json.dumps(
                    {
                        "summary": "Wrote report only",
                        "file_changes": [{"path": ".ai-copilot/reports/kanban-implementation.md", "line_changes": []}],
                        "requires_operator_approval": False,
                    }
                ),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="test_plan",
                content_json=_json.dumps({"passed": True, "summary": "ok", "dry_run_steps": []}),
            )
        )
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="pre_deploy_supervisor",
                content_json=_json.dumps({"approved": True, "summary": "ok", "plan_gaps": []}),
            )
        )
        db.add(
            RunEventModel(
                run_id=run.id,
                event_type="dry_run_result",
                stage="tester",
                severity="info",
                message="exit=0",
                payload_json="{}",
            )
        )
        db.commit()
    finally:
        db.close()

    response = client.post(f"/api/runs/{run_id}/approve", json={"comment": "override"}, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["approval_override"] is True
    assert any("report or documentation" in item.lower() for item in body["warnings"])

    run_body = client.get(f"/api/runs/{run_id}", headers=HEADERS).json()
    assert run_body["approval_override"] is True
    assert "report_substitution" in (run_body.get("mismatch_classes") or [])

    thread = client.get(f"/api/runs/{run_id}/thread", headers=HEADERS).json()
    assert any(entry["entry_type"] == "approval_warning" for entry in thread)


def test_read_run_workspace_file(client, tmp_path):
    from app.core.enums import RunStatus
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal

    source = tmp_path / "source"
    source.mkdir()
    (source / "package.json").write_text('{"name":"demo"}\n')

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "package.json").write_text('{"name":"run-workspace"}\n')
    (workspace / ".npmrc").write_text("legacy-peer-deps=true\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="WorkspaceRead",
            source_repo_spec=str(source),
            validation_profile="react",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Read workspace files",
            validation_profile="react",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.AWAITING_APPROVAL.value,
            workspace_path=str(workspace),
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    workspace_file = client.get(
        f"/api/runs/{run_id}/files/package.json",
        headers=HEADERS,
    )
    assert workspace_file.status_code == 200
    assert workspace_file.json()["content"] == '{"name":"run-workspace"}\n'

    dotfile = client.get(
        f"/api/runs/{run_id}/files/.npmrc",
        headers=HEADERS,
    )
    assert dotfile.status_code == 200
    assert dotfile.json()["content"] == "legacy-peer-deps=true\n"

    missing = client.get(
        f"/api/runs/{run_id}/files/missing.txt",
        headers=HEADERS,
    )
    assert missing.status_code == 404


def test_deployment_readiness_endpoint(client, tmp_path):
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal
    from app.core.enums import RunStatus

    root = tmp_path / "deploy_ready"
    root.mkdir()
    (root / "app.py").write_text("x=1\n", encoding="utf-8")
    db = SessionLocal()
    try:
        project = ProjectModel(
            name="Deploy",
            source_repo_spec=str(root),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="t", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.AWAITING_APPROVAL.value,
            workspace_path=str(root),
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    resp = client.get(f"/api/runs/{run_id}/deployment-readiness", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert "gates" in body
    assert "ready" in body


def test_project_metrics_stub(client, tmp_path):
    from app.db.models import ProjectModel
    from app.db.session import SessionLocal

    root = tmp_path / "kanban_api"
    root.mkdir()
    db = SessionLocal()
    try:
        project = ProjectModel(
            name="Kanban API",
            source_repo_spec=str(root),
            validation_profile="react",
            protected_files_json="[]",
        )
        db.add(project)
        db.commit()
        pid = project.id
    finally:
        db.close()

    metrics = client.get(f"/api/projects/{pid}/metrics", headers=HEADERS)
    assert metrics.status_code == 200
    assert "successRate" in metrics.json()
