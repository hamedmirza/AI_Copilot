"""Tests for post-deploy supervisor service."""

import json

from app.agents import SupervisorAgent
from app.db.models import ArtifactModel, ProjectModel, RunModel, TaskModel
from app.db.session import SessionLocal
from app.schemas.agent_outputs import SupervisorOutput
from app.services.file_service import FileService
from app.services.supervisor_service import apply_doc_updates, build_post_deploy_context, run_post_deploy_supervisor


def test_build_post_deploy_context_includes_artifacts(tmp_path):
    db = SessionLocal()
    try:
        project = ProjectModel(name="P", source_repo_spec=str(tmp_path))
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Add feature", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="completed", task_kind="implementation")
        db.add(run)
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="plan",
                content_json=json.dumps(
                    {
                        "summary": "Plan",
                        "steps": [
                            {
                                "step_id": "1",
                                "title": "Step",
                                "description": "Do it",
                                "acceptance_criteria": ["Done"],
                            }
                        ],
                        "risks": [],
                    }
                ),
            )
        )
        db.commit()

        context = build_post_deploy_context(db, run, ["main.py"])
        assert "Planner artifact" in context
        assert "main.py" in context
        assert '"step_id": "1"' in context

        empty_context = build_post_deploy_context(db, run, [])
        assert "- (none)" in empty_context
    finally:
        db.close()


def test_apply_doc_updates_writes_files(tmp_path):
    fs = FileService(tmp_path, protected_files=[])
    written = apply_doc_updates(
        fs,
        [{"path": ".ai-copilot/plans/deployed.md", "content": "# Deployed\n", "rationale": "Sync plan"}],
    )
    assert written == [".ai-copilot/plans/deployed.md"]
    assert (tmp_path / ".ai-copilot/plans/deployed.md").read_text(encoding="utf-8").startswith("# Deployed")


def test_run_post_deploy_supervisor_persists_artifact(tmp_path, monkeypatch):
    db = SessionLocal()
    try:
        project = ProjectModel(name="P", source_repo_spec=str(tmp_path))
        db.add(project)
        db.flush()
        task = TaskModel(project_id=project.id, description="Ship it", validation_profile="python")
        db.add(task)
        db.flush()
        run = RunModel(project_id=project.id, task_id=task.id, status="awaiting_approval", task_kind="implementation")
        db.add(run)
        db.flush()
        db.add(
            ArtifactModel(
                run_id=run.id,
                artifact_type="plan",
                content_json=json.dumps({"summary": "Plan", "steps": [], "risks": []}),
            )
        )
        db.commit()

        def fake_attest(_self, _context: str) -> SupervisorOutput:
            return SupervisorOutput(approved=True, summary="Aligned", plan_gaps=[], doc_updates=[])

        monkeypatch.setattr(SupervisorAgent, "attest", fake_attest)

        payload = run_post_deploy_supervisor(db, run.id, ["main.py"])
        assert payload is not None
        artifact = (
            db.query(ArtifactModel)
            .filter(ArtifactModel.run_id == run.id, ArtifactModel.artifact_type == "supervisor")
            .first()
        )
        assert artifact is not None
    finally:
        db.close()
