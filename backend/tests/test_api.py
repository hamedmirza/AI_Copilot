from pathlib import Path

import json
import sqlite3
from starlette.websockets import WebSocketDisconnect

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
    assert body["lmstudio_base_url"] == "http://192.168.128.70:1234/v1"
    assert body["worker_count"] == 1


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
        tables = {row[0] for row in check.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        check.close()

    assert {"task_kind", "failure_class", "failure_subclass", "failure_signature", "recovery_status", "superseded_by_run_id"} <= run_columns
    assert "task_kind" in task_columns
    assert "global_skills" in tables


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
        review_context, changed_files = service._build_reviewer_context(
            db,
            run.id,
            "Review the patch",
            FileService(workspace),
        )
    finally:
        db.close()

    assert changed_files == ["main.py"]
    assert "FILE: main.py" in review_context
    assert "Declared coder change:" in review_context
    assert "Current file snapshot:" in review_context
    assert "print('hello reviewer')" in review_context


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


def test_retry_stores_operator_feedback(client, tmp_path):
    import json as _json

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
    from app.db.models import ArtifactModel, ProjectModel, RunModel, TaskModel
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
