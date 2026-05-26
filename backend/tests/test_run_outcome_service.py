from pathlib import Path

import json

from app.db.models import ArtifactModel, ProjectModel, RunModel, TaskModel
from app.db.session import SessionLocal
from app.services.file_service import FileService
from app.services.run_outcome_service import (
    RunOutcomeKind,
    coder_artifact_exists,
    evaluate_blueprint_satisfaction,
    run_changed_paths,
)


def test_run_changed_paths_uses_coder_only_after_coder_artifact(tmp_path: Path):
    workspace = tmp_path / "workspace"
    source = tmp_path / "source"
    workspace.mkdir()
    source.mkdir()
    (workspace / "stale_only.py").write_text("drift\n", encoding="utf-8")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="OutcomePaths",
            source_repo_spec=str(source),
            validation_profile="python",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="noop test",
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
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="coder",
                content_json=json.dumps({"summary": "noop", "file_changes": []}),
            )
        )
        db.commit()
        assert coder_artifact_exists(db, run.id) is True
        changed = run_changed_paths(db, run.id, workspace, source)
        assert changed == []
    finally:
        db.close()


def test_evaluate_blueprint_satisfaction_already_satisfied(tmp_path: Path):
    backend = tmp_path / "backend"
    service_dir = backend / "app" / "services"
    test_dir = backend / "tests"
    service_dir.mkdir(parents=True)
    test_dir.mkdir(parents=True)
    (service_dir / "foo.py").write_text("ok = True\n", encoding="utf-8")
    (test_dir / "test_foo.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    venv_bin = backend / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    pytest_path = venv_bin / "pytest"
    pytest_path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    pytest_path.chmod(0o755)

    fs = FileService(backend)
    architect = {
        "file_changes": [
            {"path": "app/services/foo.py", "action": "modify", "rationale": "exists"},
            {"path": "tests/test_foo.py", "action": "modify", "rationale": "tests"},
        ]
    }
    result = evaluate_blueprint_satisfaction(architect, fs, backend, backend)
    assert result.kind == RunOutcomeKind.ALREADY_SATISFIED
    assert "no code changes required" in result.message.lower()
