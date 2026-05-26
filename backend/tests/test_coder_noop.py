from pathlib import Path

from app.services.file_service import FileService
from app.services.learning_service import infer_task_kind
from app.services.orchestration_service import OrchestrationService


def test_infer_task_kind_prefers_implementation_for_extend_tasks():
    kind = infer_task_kind(
        "Extend backend/app/services/web_search_service.py to support providers. Update tests in backend/tests/."
    )
    assert kind == "implementation"


def test_coder_noop_when_blueprint_files_and_tests_pass(tmp_path: Path):
    backend = tmp_path / "backend"
    service_dir = backend / "app" / "services"
    test_dir = backend / "tests"
    service_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (service_dir / "web_search_service.py").write_text("providers = True\n", encoding="utf-8")
    (test_dir / "test_web_search_service.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )
    venv_bin = backend / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    pytest_path = venv_bin / "pytest"
    pytest_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pytest_path.chmod(0o755)

    fs = FileService(backend)
    architect = {
        "file_changes": [
            {"path": "app/services/web_search_service.py", "action": "modify", "rationale": "providers"},
            {"path": "tests/test_web_search_service.py", "action": "modify", "rationale": "tests"},
        ]
    }
    svc = OrchestrationService()
    assert svc._blueprint_files_exist(fs, svc._blueprint_paths(architect)) is True
    assert svc._blueprint_tests_pass(
        backend, svc._blueprint_test_paths(svc._blueprint_paths(architect)), source_root=backend
    ) is True

    class DummyDb:
        pass

    def _noop_record(*_args, **_kwargs):
        return None

    svc._record_event = _noop_record  # type: ignore[method-assign]
    svc._emit = _noop_record  # type: ignore[method-assign]
    svc._save_artifact = _noop_record  # type: ignore[method-assign]
    output = svc._try_coder_noop_when_blueprint_satisfied(DummyDb(), "run-1", fs, architect, backend, backend)
    assert output is not None
    assert output.file_changes == []
    assert "no code changes required" in output.summary.lower()


def test_blueprint_satisfied_pipeline_reaches_awaiting_approval(tmp_path: Path):
    from app.core.enums import RunStatus
    from app.db.models import ProjectModel, RunModel, TaskModel
    from app.db.session import SessionLocal

    backend = tmp_path / "backend"
    service_dir = backend / "app" / "services"
    test_dir = backend / "tests"
    service_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (service_dir / "web_search_service.py").write_text("providers = True\n", encoding="utf-8")
    (test_dir / "test_web_search_service.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    venv_bin = backend / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    pytest_path = venv_bin / "pytest"
    pytest_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pytest_path.chmod(0o755)
    (backend / "pyproject.toml").write_text('[project]\nname="demo"\n', encoding="utf-8")
    (backend / "AGENTS.md").write_text("# Demo\n", encoding="utf-8")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="Blueprint Satisfied",
            source_repo_spec=str(backend),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Extend web search providers and update tests",
            validation_profile="python",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.RUNNING.value,
            workspace_path=str(backend),
            task_kind="implementation",
        )
        db.add(run)
        db.commit()
        run_id = run.id
    finally:
        db.close()

    architect = {
        "overview": "Providers already implemented",
        "modules": ["services"],
        "file_changes": [
            {"path": "app/services/web_search_service.py", "action": "modify", "rationale": "providers"},
            {"path": "tests/test_web_search_service.py", "action": "modify", "rationale": "tests"},
        ],
        "dependencies": [],
    }
    plan = {
        "summary": "Done",
        "steps": [
            {
                "step_id": "1",
                "title": "Verify",
                "description": "x",
                "acceptance_criteria": ["tests pass"],
            }
        ],
        "risks": [],
    }

    svc = OrchestrationService()

    def _save_plan(db, rid, ctx, fs):
        svc._save_artifact(db, rid, "plan", plan)
        return True

    def _save_architect(db, rid, ctx):
        svc._save_artifact(db, rid, "architect", architect)
        return True

    svc._stage_planner = _save_plan  # type: ignore[method-assign]
    svc._stage_architect = _save_architect  # type: ignore[method-assign]
    svc._stage_ui = lambda db, rid, ctx: True  # type: ignore[method-assign]
    svc._verify_dependencies = lambda db, rid, workspace, source: True  # type: ignore[method-assign]

    db = SessionLocal()
    try:
        svc._pipeline(db, run_id)
        run = db.get(RunModel, run_id)
        assert run is not None
        assert run.status == RunStatus.AWAITING_APPROVAL.value
        coder = svc._latest_artifact(db, run_id, "coder") or {}
        assert coder.get("file_changes") == []
    finally:
        db.close()
