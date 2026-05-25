import json

from app.core.enums import PipelineStage
from app.db.models import RunModel
from app.services.orchestration_service import (
    CLARIFICATION_GATE_ARCHITECT_NAVIGATION,
    orchestration_service,
)


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
