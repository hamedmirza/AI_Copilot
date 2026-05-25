from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import ProjectModel, RunModel, TaskModel
from app.db.session import get_db
from app.services.project_service import ProjectService
from app.services.run_truth_service import persist_run_truth

router = APIRouter(tags=["kanban"])


KANBAN_COLUMNS: list[tuple[str, str, set[str]]] = [
    ("queued", "Queued", {"pending"}),
    ("active", "In Progress", {"running"}),
    ("clarification", "Need Clarification", {"awaiting_clarification"}),
    ("approval", "Awaiting Approval", {"awaiting_approval"}),
    ("completed", "Completed", {"completed"}),
    ("attention", "Needs Attention", {"blocked", "failed", "changes_requested", "cancelled"}),
]


def _summarize_title(task: TaskModel | None, run: RunModel) -> str:
    if task and task.description.strip():
        text = task.description.strip().replace("\n", " ")
        return text[:96] + ("…" if len(text) > 96 else "")
    return f"Run {run.id[:8]}"


def _run_card(task: TaskModel | None, run: RunModel) -> dict:
    readiness = run.readiness
    warnings = [str(item) for item in readiness.get("warnings") or [] if str(item).strip()]
    return {
        "run_id": run.id,
        "task_id": run.task_id,
        "chat_session_id": run.chat_session_id,
        "title": _summarize_title(task, run),
        "status": run.status,
        "current_stage": run.current_stage,
        "task_kind": run.task_kind or (task.task_kind if task else None),
        "deliverable_kind": run.deliverable_kind,
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
        "failure_class": run.failure_class,
        "failure_subclass": run.failure_subclass,
        "error_message": run.error_message,
        "mismatch_classes": run.mismatch_classes,
        "warnings": warnings,
        "approval_override": bool(run.approval_override),
        "operator_feedback_present": bool(run.operator_feedback_present),
        "retry_count": int(run.retry_count or 0),
        "review_attempts": int(run.review_attempts or 0),
        "summary_changed_files": [str(item) for item in readiness.get("changed_files") or []][:4],
    }


def _success_failure_rates(runs: list[RunModel]) -> tuple[int, int]:
    terminal = [run for run in runs if run.status in {"completed", "failed", "blocked", "changes_requested", "cancelled"}]
    if not terminal:
        return (0, 0)
    success = sum(1 for run in terminal if run.status == "completed")
    failure = len(terminal) - success
    total = len(terminal)
    return (round(success * 100 / total), round(failure * 100 / total))


def _skill_improvement_series(runs: list[RunModel]) -> list[dict]:
    by_day: dict[date, list[RunModel]] = defaultdict(list)
    for run in runs:
        by_day[run.created_at.date()].append(run)
    completed = 0
    total = 0
    series: list[dict] = []
    for day in sorted(by_day):
        for run in by_day[day]:
            if run.status in {"completed", "failed", "blocked", "changes_requested", "cancelled"}:
                total += 1
                if run.status == "completed":
                    completed += 1
        score = round((completed * 100 / total), 1) if total else 0.0
        series.append({"date": day.isoformat(), "score": score})
    return series[-10:]


@router.get("/projects/{project_id}/kanban")
def project_kanban(project_id: str, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    tasks = {
        task.id: task
        for task in db.query(TaskModel)
        .filter(TaskModel.project_id == project_id)
        .all()
    }
    runs = (
        db.query(RunModel)
        .filter(RunModel.project_id == project_id)
        .order_by(RunModel.updated_at.desc(), RunModel.created_at.desc())
        .limit(120)
        .all()
    )
    for run in runs:
        persist_run_truth(db, run.id)
    if runs:
        refreshed_ids = [run.id for run in runs]
        runs = (
            db.query(RunModel)
            .filter(RunModel.id.in_(refreshed_ids))
            .order_by(RunModel.updated_at.desc(), RunModel.created_at.desc())
            .all()
        )

    cards_by_column: dict[str, list[dict]] = {column_id: [] for column_id, _, _ in KANBAN_COLUMNS}
    for run in runs:
        task = tasks.get(run.task_id)
        card = _run_card(task, run)
        column_id = next((column_id for column_id, _, statuses in KANBAN_COLUMNS if run.status in statuses), "attention")
        cards_by_column[column_id].append(card)

    success_rate, failure_rate = _success_failure_rates(runs)
    summary = {
        "total_runs": len(runs),
        "queued_runs": sum(1 for run in runs if run.status == "pending"),
        "active_runs": sum(1 for run in runs if run.status == "running"),
        "clarification_runs": sum(1 for run in runs if run.status == "awaiting_clarification"),
        "approval_runs": sum(1 for run in runs if run.status == "awaiting_approval"),
        "completed_runs": sum(1 for run in runs if run.status == "completed"),
        "attention_runs": sum(1 for run in runs if run.status in {"blocked", "failed", "changes_requested", "cancelled"}),
        "success_rate": success_rate,
        "failure_rate": failure_rate,
    }
    columns = [
        {
            "id": column_id,
            "title": title,
            "count": len(cards_by_column[column_id]),
            "items": cards_by_column[column_id],
        }
        for column_id, title, _ in KANBAN_COLUMNS
    ]

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
        },
        "summary": summary,
        "columns": columns,
        "generated_at": max((run.updated_at for run in runs), default=project.updated_at).isoformat(),
    }


@router.get("/projects/{project_id}/metrics")
def project_metrics(project_id: str, db: Session = Depends(get_db)):
    ProjectService(db).get(project_id)
    runs = (
        db.query(RunModel)
        .filter(RunModel.project_id == project_id)
        .order_by(RunModel.created_at.asc())
        .all()
    )
    success_rate, failure_rate = _success_failure_rates(runs)
    return {
        "successRate": success_rate,
        "failureRate": failure_rate,
        "skillImprovements": _skill_improvement_series(runs),
    }
