from pathlib import Path

from app.core.enums import RunStatus
from app.db.session import SessionLocal
from app.services.setup_run_service import has_completed_setup, trigger_setup_run


def test_trigger_setup_run_via_api(client, tmp_path: Path, monkeypatch):
    enqueued: list[str] = []
    monkeypatch.setattr(
        "app.services.setup_run_service.run_engine.enqueue",
        lambda run_id: enqueued.append(run_id),
    )
    monkeypatch.setattr(
        "app.api.routes.api.run_engine.enqueue",
        lambda run_id: enqueued.append(run_id),
    )

    r = client.post(
        "/api/projects",
        json={
            "name": "Setup API Project",
            "description": "Scaffold me",
            "source_repo_spec": str(tmp_path),
            "validation_profile": "python",
        },
        headers={"X-Api-Token": "dev-token"},
    )
    assert r.status_code == 200
    project_id = r.json()["id"]
    assert len(enqueued) >= 1

    db = SessionLocal()
    try:
        second = trigger_setup_run(db, project_id)
        assert second is None
    finally:
        db.close()


def test_create_task_triggers_setup_when_incomplete(client, tmp_path: Path, monkeypatch):
    enqueued: list[str] = []
    monkeypatch.setattr(
        "app.services.orchestration_service.run_engine.enqueue",
        lambda run_id: enqueued.append(run_id),
    )
    monkeypatch.setattr(
        "app.services.setup_run_service.run_engine.enqueue",
        lambda run_id: enqueued.append(run_id),
    )

    project_resp = client.post(
        "/api/projects",
        json={
            "name": "No Setup Yet",
            "description": "Project without auto setup",
            "source_repo_spec": str(tmp_path / "no_auto"),
            "validation_profile": "python",
        },
        headers={"X-Api-Token": "dev-token"},
    )
    assert project_resp.status_code == 200
    project_id = project_resp.json()["id"]

    db = SessionLocal()
    try:
        from app.db.models import RunModel, TaskModel

        for run in (
            db.query(RunModel)
            .join(TaskModel, TaskModel.id == RunModel.task_id)
            .filter(TaskModel.project_id == project_id)
            .all()
        ):
            db.delete(run)
        for task in db.query(TaskModel).filter(TaskModel.project_id == project_id).all():
            db.delete(task)
        db.commit()
    finally:
        db.close()

    enqueued.clear()
    task_resp = client.post(
        "/api/tasks",
        json={
            "project_id": project_id,
            "description": "Add a health check endpoint to the API",
        },
        headers={"X-Api-Token": "dev-token"},
    )
    assert task_resp.status_code == 200
    assert len(enqueued) >= 2

    db = SessionLocal()
    try:
        setup_runs = (
            db.query(RunModel)
            .join(TaskModel, TaskModel.id == RunModel.task_id)
            .filter(TaskModel.project_id == project_id, RunModel.task_kind == "setup")
            .all()
        )
        assert len(setup_runs) >= 1
    finally:
        db.close()


def test_has_completed_setup_after_terminal(client, tmp_path: Path):
    r = client.post(
        "/api/projects",
        json={
            "name": "Setup Complete Project",
            "description": "Done",
            "source_repo_spec": str(tmp_path / "b"),
            "validation_profile": "python",
        },
        headers={"X-Api-Token": "dev-token"},
    )
    project_id = r.json()["id"]
    db = SessionLocal()
    try:
        from app.db.models import RunModel, TaskModel

        run = (
            db.query(RunModel)
            .join(TaskModel, TaskModel.id == RunModel.task_id)
            .filter(TaskModel.project_id == project_id, RunModel.task_kind == "setup")
            .first()
        )
        assert run is not None
        run.status = RunStatus.COMPLETED.value
        db.commit()
        assert has_completed_setup(db, project_id) is True
        assert trigger_setup_run(db, project_id) is None
    finally:
        db.close()
