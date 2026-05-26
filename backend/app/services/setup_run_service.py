"""Auto-trigger project setup runs."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.enums import PipelineStage, RunStatus
from app.db.models import RunModel, TaskModel
from app.services.orchestration_service import run_engine
from app.services.run_truth_service import persist_run_truth


_SETUP_SKIP_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.PENDING.value,
    RunStatus.RUNNING.value,
    RunStatus.AWAITING_APPROVAL.value,
    RunStatus.AWAITING_CLARIFICATION.value,
    RunStatus.AWAITING_DESIGN_REVIEW.value,
    RunStatus.CHANGES_REQUESTED.value,
    RunStatus.BLOCKED.value,
}


def has_completed_setup(db: Session, project_id: str) -> bool:
    return (
        db.query(RunModel)
        .join(TaskModel, TaskModel.id == RunModel.task_id)
        .filter(
            TaskModel.project_id == project_id,
            RunModel.task_kind == "setup",
            RunModel.status == RunStatus.COMPLETED.value,
        )
        .first()
        is not None
    )


def has_active_setup_run(db: Session, project_id: str) -> bool:
    return (
        db.query(RunModel)
        .join(TaskModel, TaskModel.id == RunModel.task_id)
        .filter(
            TaskModel.project_id == project_id,
            RunModel.task_kind == "setup",
            RunModel.status.in_(_SETUP_SKIP_STATUSES),
        )
        .first()
        is not None
    )


def trigger_setup_run(db: Session, project_id: str, *, description: str | None = None) -> RunModel | None:
    if has_active_setup_run(db, project_id):
        return None
    from app.db.models import ProjectModel

    project = db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
    if not project:
        return None
    task = TaskModel(
        project_id=project_id,
        description=description or f"Initialize project scaffold and governance for {project.name}",
        validation_profile=project.validation_profile,
        task_kind="setup",
        use_scout=False,
    )
    db.add(task)
    db.flush()
    run = RunModel(
        project_id=project_id,
        task_id=task.id,
        status=RunStatus.PENDING.value,
        current_stage=PipelineStage.PLANNER.value,
        task_kind="setup",
        recovery_status="none",
        deliverable_kind="mixed",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    persist_run_truth(db, run.id)
    run_engine.enqueue(run.id)
    return run
