import json

from app.core.enums import PipelineStage, RunStatus
from app.db.models import ProjectModel, RunEventModel, RunModel, TaskModel
from app.db.session import SessionLocal
from app.providers.fake import FakeProvider
from app.providers.registry import ProviderRegistry
from app.services.orchestration_service import (
    CLARIFICATION_GATE_ARCHITECT_NAVIGATION,
    OrchestrationService,
    orchestration_service,
)
from app.services.reconnaissance_service import ReconSnapshot


def _run(**kwargs) -> RunModel:
    defaults = {
        "task_kind": "implementation",
        "deliverable_kind": "frontend",
        "clarification_context_json": "{}",
        "operator_feedback": None,
    }
    defaults.update(kwargs)
    return RunModel(project_id="p1", task_id="t1", **defaults)


def test_architect_navigation_not_repeated_after_resolved_gate():
    run = _run(
        clarification_context_json=json.dumps(
            {
                "answer": "Put it in the settings panel only.",
                "resolved_gates": [CLARIFICATION_GATE_ARCHITECT_NAVIGATION],
            }
        ),
    )
    assert orchestration_service._needs_clarification(
        run, "Implement kanban page", PipelineStage.ARCHITECT.value
    ) is None


def test_architect_navigation_skipped_when_answer_mentions_workbench():
    run = _run(
        clarification_context_json=json.dumps(
            {"answer": "Wire into the workbench center view."},
        ),
    )
    assert orchestration_service._needs_clarification(
        run, "Implement kanban page", PipelineStage.ARCHITECT.value
    ) is None


def test_architect_navigation_still_required_without_answer_or_surface_cue():
    run = _run()
    result = orchestration_service._needs_clarification(
        run, "Implement kanban page", PipelineStage.ARCHITECT.value
    )
    assert result is not None
    assert result[2] == CLARIFICATION_GATE_ARCHITECT_NAVIGATION


def test_architect_agent_clarification_pauses_run_after_architect_stage(client, tmp_path):
    """Architect clarification_needed is evaluated after the architect stage completes."""
    workspace = tmp_path / "architect_clarify_workspace"
    workspace.mkdir()
    (workspace / "main.py").write_text("print('hello')\n")
    (workspace / "pyproject.toml").write_text('[project]\nname="demo"\n', encoding="utf-8")
    (workspace / "tests").mkdir()
    (workspace / "AGENTS.md").write_text("# Demo\n", encoding="utf-8")

    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider(
        invoke_sequence=[
            json.dumps(
                {
                    "summary": "Add structured logging",
                    "steps": [
                        {
                            "step_id": "1",
                            "title": "Logging",
                            "description": "Add logging helper",
                            "acceptance_criteria": ["Logs emit on startup"],
                        }
                    ],
                    "risks": [],
                }
            ),
            json.dumps(
                {
                    "overview": "Add logging to backend service",
                    "modules": ["backend.app.services"],
                    "file_changes": [
                        {
                            "path": "main.py",
                            "action": "modify",
                            "rationale": "Import logging configuration",
                        }
                    ],
                    "dependencies": [],
                    "clarification_needed": True,
                    "clarification_question": "Should logging use structlog or stdlib logging?",
                }
            ),
        ]
    )
    registry.reload({})

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="ArchitectClarify",
            source_repo_spec=str(workspace),
            validation_profile="python",
            protected_files_json="[]",
            repo_mode="existing",
        )
        db.add(project)
        db.flush()
        task = TaskModel(
            project_id=project.id,
            description="Add structured logging to backend/app/services/demo.py",
            validation_profile="python",
            task_kind="implementation",
        )
        db.add(task)
        db.flush()
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status=RunStatus.RUNNING.value,
            workspace_path=str(workspace),
            task_kind="implementation",
            deliverable_kind="backend",
        )
        db.add(run)
        db.commit()
        run_id = run.id

        service = OrchestrationService()
        existing_snapshot = ReconSnapshot(
            repo_mode="existing",
            stack_profile="python",
            payload={"file_tree": ["main.py", "pyproject.toml"]},
        )
        service._prepare_recon = lambda *args, **kwargs: existing_snapshot  # type: ignore[method-assign]
        service._run_preflight = lambda *args, **kwargs: True  # type: ignore[method-assign]
        service._capture_baseline = lambda *args, **kwargs: None  # type: ignore[method-assign]
        service._verify_dependencies = lambda db_arg, run_id_arg, workspace_arg, source_arg: True  # type: ignore[method-assign]
        service._stage_ui = lambda db_arg, run_id_arg, ctx: True  # type: ignore[method-assign]
        service._stage_coder = lambda db_arg, run_id_arg, ctx, fs: True  # type: ignore[method-assign]
        service._stage_reviewer_loop = lambda db_arg, run_id_arg, ctx, fs, ws, src: True  # type: ignore[method-assign]
        service._stage_tester = lambda db_arg, run_id_arg, ctx, ws: True  # type: ignore[method-assign]
        service._stage_documentation = lambda db_arg, run_id_arg, ctx, fs: True  # type: ignore[method-assign]

        service._pipeline(db, run_id)
        db.refresh(run)

        assert run.status == RunStatus.AWAITING_CLARIFICATION.value
        assert run.clarification_stage == PipelineStage.ARCHITECT.value
        assert "structlog" in (run.clarification_question or "").lower()

        events = (
            db.query(RunEventModel)
            .filter(
                RunEventModel.run_id == run_id,
                RunEventModel.event_type == "run_clarification_requested",
            )
            .all()
        )
        assert len(events) == 1
        assert events[0].stage == PipelineStage.ARCHITECT.value

        architect_complete = (
            db.query(RunEventModel)
            .filter(RunEventModel.run_id == run_id, RunEventModel.event_type == "architect_complete")
            .all()
        )
        assert len(architect_complete) == 0
    finally:
        db.close()
