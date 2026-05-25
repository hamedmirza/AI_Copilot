from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import ptyprocess
from starlette.concurrency import run_in_threadpool
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from app.api.deps import verify_websocket_token
from app.api.routes.chat import router as chat_router
from app.api.routes.kanban_data import router as kanban_router
from app.core.exceptions import (
    NotFoundError,
    PatchGuardError,
    PathTraversalError,
    ValidationError,
)
from app.core.logging import read_log_lines
from app.db.session import get_db
from app.schemas.api import (
    ApproveRequest,
    ClarifyRequest,
    FileCreateRequest,
    FileWriteRequest,
    GitCheckoutRequest,
    GitCommitRequest,
    GitStageRequest,
    ProjectCreate,
    ProjectUpdate,
    RejectRequest,
    RetryRequest,
    TaskCreate,
)
from app.services.config_service import ConfigService
from app.services.file_service import FileService
from app.services.git_service import GitService
from app.services.browser_preview_service import BrowserPreviewError, BrowserPreviewService
from app.services.learning_service import LearningService
from app.services.orchestration_service import create_task_and_run, run_engine
from app.services.run_approval_service import approve_run_sync
from app.services.run_display import derive_run_display_name, run_numbers_for_task
from app.services.run_engine.event_bus import event_bus
from app.services.tree_cache import get_cached_tree, invalidate_tree_cache, store_tree_cache
from app.services.project_service import ProjectService
from app.services.run_cleanup_service import RunCleanupService
from app.services.run_thread_service import RunThreadService
from app.services.run_truth_service import persist_run_truth

router = APIRouter()
router.include_router(chat_router)
router.include_router(kanban_router)


def _project_to_response(p, db: Session) -> dict:
    from app.db.models import RunModel

    run_count = db.query(RunModel).filter(RunModel.project_id == p.id).count()
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description,
        "source_repo_spec": p.source_repo_spec,
        "validation_profile": p.validation_profile,
        "protected_files": p.protected_files,
        "run_count": run_count,
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


def _artifact_to_response(artifact) -> dict:
    return {
        "id": artifact.id,
        "artifact_type": artifact.artifact_type,
        "content": json.loads(artifact.content_json),
        "created_at": artifact.created_at.isoformat(),
    }


def _run_to_response(run, task_description: str, run_number: int | None = None) -> dict:
    promote_snapshot = None
    if run.promote_snapshot_json:
        try:
            promote_snapshot = json.loads(run.promote_snapshot_json)
        except json.JSONDecodeError:
            promote_snapshot = None
    return {
        "id": run.id,
        "display_name": derive_run_display_name(task_description, run.created_at, run_number=run_number),
        "project_id": run.project_id,
        "task_id": run.task_id,
        "status": run.status,
        "current_stage": run.current_stage,
        "workspace_path": run.workspace_path,
        "review_attempts": run.review_attempts,
        "error_message": run.error_message,
        "operator_feedback": run.operator_feedback,
        "promote_snapshot": promote_snapshot,
        "task_kind": getattr(run, "task_kind", None),
        "failure_class": getattr(run, "failure_class", None),
        "failure_subclass": getattr(run, "failure_subclass", None),
        "failure_signature": getattr(run, "failure_signature", None),
        "recovery_status": getattr(run, "recovery_status", None),
        "superseded_by_run_id": getattr(run, "superseded_by_run_id", None),
        "terminal_success": getattr(run, "terminal_success", None),
        "terminal_status": getattr(run, "terminal_status", None),
        "retry_count": getattr(run, "retry_count", None),
        "schema_failure_count": getattr(run, "schema_failure_count", None),
        "reviewer_failure_count": getattr(run, "reviewer_failure_count", None),
        "tester_failure_count": getattr(run, "tester_failure_count", None),
        "operator_feedback_present": getattr(run, "operator_feedback_present", None),
        "approval_reached": getattr(run, "approval_reached", None),
        "promote_rolled_back": getattr(run, "promote_rolled_back", None),
        "primary_failure_class": getattr(run, "primary_failure_class", None),
        "chat_session_id": getattr(run, "chat_session_id", None),
        "deliverable_kind": getattr(run, "deliverable_kind", None),
        "expected_targets": getattr(run, "expected_targets", []),
        "expected_validation_family": getattr(run, "expected_validation_family", None),
        "readiness": getattr(run, "readiness", {}),
        "mismatch_classes": getattr(run, "mismatch_classes", []),
        "approval_override": getattr(run, "approval_override", None),
        "allow_web_search": getattr(run, "allow_web_search", None),
        "clarification_question": getattr(run, "clarification_question", None),
        "clarification_stage": getattr(run, "clarification_stage", None),
        "recommended_assumption": (run.clarification_context or {}).get("recommended_assumption"),
        "created_at": run.created_at.isoformat(),
        "updated_at": run.updated_at.isoformat(),
    }


@router.get("/health")
def health(db: Session = Depends(get_db)):
    import time

    from app.services.run_engine.event_bus import event_bus

    worker_count = 1
    try:
        worker_count = int(ConfigService(db).get_all().get("worker_count", 1))
    except Exception:
        pass
    uptime = max(0, int(time.time() - event_bus.started_at))
    return {
        "status": "ok",
        "version": "0.1.0",
        "uptime_seconds": uptime,
        "worker_count": worker_count,
        "ws_connections": event_bus.ws_connections,
    }


@router.get("/health/provider")
def provider_health(db: Session = Depends(get_db)):
    ConfigService(db).reload_registry()
    from app.providers.registry import ProviderRegistry

    return ProviderRegistry.get().health_provider_summary()


@router.get("/settings")
def get_settings_api(db: Session = Depends(get_db)):
    return ConfigService(db).get_settings()


@router.put("/settings")
def update_settings(body: dict, db: Session = Depends(get_db)):
    from app.schemas.api import SettingsUpdate

    update = SettingsUpdate(**body)
    settings = ConfigService(db).update_settings(update)
    run_engine.configure_workers(settings.worker_count)
    return settings


@router.post("/settings/reset")
def reset_settings(db: Session = Depends(get_db)):
    settings = ConfigService(db).reset_to_defaults()
    run_engine.configure_workers(settings.worker_count)
    return settings


@router.get("/settings/models")
def list_models(provider: str | None = None, db: Session = Depends(get_db)):
    ConfigService(db).reload_registry()
    from app.providers.registry import ProviderRegistry

    registry = ProviderRegistry.get()
    if provider in ("lmstudio", "ollama"):
        detailed = registry.list_models_detailed_for_provider(provider)
    else:
        detailed = registry.list_models_detailed()
    return {
        "provider": provider or registry.active_provider(),
        "models": detailed.models,
        "catalog": detailed.catalog,
        "recommendations": detailed.recommendations,
        "resources": detailed.resources,
    }


@router.get("/onboarding/status")
def onboarding_status(db: Session = Depends(get_db)):
    from app.db.models import ProjectModel

    count = db.query(ProjectModel).count()
    return {"complete": count > 0, "project_count": count}


@router.post("/dialog/pick-directory")
async def pick_directory_dialog(body: dict | None = None):
    from app.tools.dialog_service import PICK_DIRECTORY_TIMEOUT_SECONDS, pick_directory

    prompt = (body or {}).get("prompt") or "Select a project folder"
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: pick_directory(prompt=str(prompt))),
            timeout=PICK_DIRECTORY_TIMEOUT_SECONDS + 5,
        )
    except asyncio.TimeoutError:
        return {"cancelled": True, "path": None, "error": "timeout"}
    return {"cancelled": result.cancelled, "path": result.path, "error": result.error}


@router.get("/browser/preview")
def browser_preview(url: str, project_id: str, db: Session = Depends(get_db)):
    ProjectService(db).get(project_id)
    try:
        preview = BrowserPreviewService().fetch_preview(url)
    except BrowserPreviewError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Preview fetch failed: {exc}") from exc

    if preview.content_type.startswith("text/html"):
        return HTMLResponse(content=preview.body, status_code=preview.status_code)

    return Response(content=preview.body, media_type=preview.content_type, status_code=preview.status_code)


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    svc = ProjectService(db)
    return [_project_to_response(p, db) for p in svc.list_projects()]


@router.post("/projects")
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    svc = ProjectService(db)
    p = svc.create(data)
    return _project_to_response(p, db)


@router.get("/projects/{project_id}")
def get_project(project_id: str, db: Session = Depends(get_db)):
    svc = ProjectService(db)
    return _project_to_response(svc.get(project_id), db)


@router.put("/projects/{project_id}")
def update_project(project_id: str, data: ProjectUpdate, db: Session = Depends(get_db)):
    svc = ProjectService(db)
    return _project_to_response(svc.update(project_id, data), db)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    ProjectService(db).delete(project_id)
    return {"ok": True}


@router.get("/projects/{project_id}/blockers")
def get_blockers(project_id: str, db: Session = Depends(get_db)):
    runs = ProjectService(db).get_blockers(project_id)
    return [{"id": r.id, "status": r.status, "error": r.error_message} for r in runs]


@router.get("/projects/{project_id}/release-readiness")
def release_readiness(project_id: str, db: Session = Depends(get_db)):
    return ProjectService(db).release_readiness(project_id)


@router.get("/projects/{project_id}/lessons")
def project_lessons(project_id: str, db: Session = Depends(get_db)):
    ProjectService(db).get(project_id)
    return LearningService(db).list_project_lessons(project_id)


@router.get("/projects/{project_id}/improvements")
def project_improvements(
    project_id: str,
    status: str | None = None,
    scope: str | None = None,
    db: Session = Depends(get_db),
):
    ProjectService(db).get(project_id)
    return LearningService(db).list_improvements(project_id=project_id, status=status, scope=scope)


@router.post("/projects/{project_id}/lessons/from-run/{run_id}")
def create_project_lesson_from_run(project_id: str, run_id: str, db: Session = Depends(get_db)):
    from app.db.models import RunModel

    run = db.query(RunModel).filter(RunModel.id == run_id, RunModel.project_id == project_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    learner = LearningService(db)
    learner.finalize_terminal_run(run_id)
    lessons = learner.list_project_lessons(project_id)
    for lesson in lessons:
        if lesson.get("run_id") == run_id:
            return lesson
    raise HTTPException(500, "Lesson generation failed")


@router.get("/projects/{project_id}/tree")
def file_tree(project_id: str, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    workspace = __import__("pathlib").Path(project.source_repo_spec)
    cached = get_cached_tree(workspace)
    if cached is not None:
        return {"items": cached}
    fs = FileService(workspace, project.protected_files)
    items = fs.list_tree()
    store_tree_cache(workspace, items)
    return {"items": items}


def _guard_traversal(path: str) -> None:
    decoded = unquote(path)
    if ".." in decoded or decoded.startswith("/"):
        raise HTTPException(400, "Path traversal not allowed")


@router.get("/projects/{project_id}/files/{path:path}")
def read_file(project_id: str, path: str, db: Session = Depends(get_db)):
    _guard_traversal(path)
    project = ProjectService(db).get(project_id)
    fs = FileService(__import__("pathlib").Path(project.source_repo_spec), project.protected_files)
    try:
        return fs.read_file(path)
    except PathTraversalError as exc:
        raise HTTPException(400, str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/projects/{project_id}/files/{path:path}")
def write_file(project_id: str, path: str, body: FileWriteRequest, db: Session = Depends(get_db)):
    _guard_traversal(path)
    project = ProjectService(db).get(project_id)
    fs = FileService(__import__("pathlib").Path(project.source_repo_spec), project.protected_files)
    try:
        result = fs.write_file(path, body.content)
        invalidate_tree_cache(fs.workspace)
        return result
    except (PathTraversalError, PatchGuardError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/projects/{project_id}/files")
def create_file(project_id: str, body: FileCreateRequest, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    fs = FileService(__import__("pathlib").Path(project.source_repo_spec), project.protected_files)
    try:
        result = fs.create(body.path, body.content, body.is_directory)
        invalidate_tree_cache(fs.workspace)
        return result
    except PathTraversalError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/projects/{project_id}/files/{path:path}")
def delete_file(project_id: str, path: str, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    fs = FileService(__import__("pathlib").Path(project.source_repo_spec), project.protected_files)
    try:
        fs.delete(path)
        invalidate_tree_cache(fs.workspace)
        return {"ok": True}
    except (PathTraversalError, PatchGuardError, NotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/projects/{project_id}/files/{path:path}/rename")
def rename_file(project_id: str, path: str, body: dict, db: Session = Depends(get_db)):
    _guard_traversal(path)
    new_path = body.get("new_path", "")
    _guard_traversal(new_path)
    if not new_path:
        raise HTTPException(400, "new_path required")
    project = ProjectService(db).get(project_id)
    fs = FileService(__import__("pathlib").Path(project.source_repo_spec), project.protected_files)
    try:
        result = fs.rename(path, new_path)
        invalidate_tree_cache(fs.workspace)
        return result
    except (PathTraversalError, PatchGuardError, NotFoundError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/tasks")
def create_task(data: TaskCreate, db: Session = Depends(get_db)):
    task, run = create_task_and_run(
        db,
        {
            "project_id": data.project_id,
            "description": data.description,
            "validation_profile": data.validation_profile,
            "use_scout": data.use_scout,
            "allow_web_search": data.allow_web_search,
        },
    )
    chat_session_id = RunThreadService(db).ensure_session(run.id)
    db.refresh(run)
    return {
        "task": {
            "id": task.id,
            "project_id": task.project_id,
            "description": task.description,
            "validation_profile": task.validation_profile,
            "use_scout": task.use_scout,
            "allow_web_search": task.allow_web_search,
            "created_at": task.created_at.isoformat(),
        },
        "run": {
            "id": run.id,
            "status": run.status,
            "display_name": derive_run_display_name(task.description, run.created_at),
            "chat_session_id": chat_session_id,
            "allow_web_search": run.allow_web_search,
        },
    }


@router.get("/runs/failure-summary")
def get_failure_summary(project_id: str | None = None, db: Session = Depends(get_db)):
    return LearningService(db).failure_summary(project_id)


@router.post("/runs/cleanup")
def cleanup_failed_runs(
    project_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Remove terminal failed runs (failed/blocked/changes_requested/cancelled) and their workspaces."""
    if project_id:
        ProjectService(db).get(project_id)
    return RunCleanupService(db).purge_terminal_failed_runs(project_id)


@router.get("/improvements/{improvement_id}")
def get_improvement(improvement_id: str, db: Session = Depends(get_db)):
    try:
        return LearningService(db).get_improvement(improvement_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/improvements/{improvement_id}/exposures")
def list_improvement_exposures(improvement_id: str, db: Session = Depends(get_db)):
    try:
        return LearningService(db).list_improvement_exposures(improvement_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    from app.db.models import RunModel, TaskModel

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    LearningService(db).ensure_run_learning_state(run)
    task = db.get(TaskModel, run.task_id)
    persist_run_truth(db, run.id)
    db.refresh(run)
    task_description = task.description if task else ""
    sibling_runs = (
        db.query(RunModel)
        .filter(RunModel.task_id == run.task_id)
        .order_by(RunModel.created_at.asc())
        .all()
    )
    return _run_to_response(run, task_description, run_numbers_for_task(sibling_runs).get(run.id))


@router.get("/runs/{run_id}/events")
def run_events(run_id: str, db: Session = Depends(get_db)):
    from app.db.models import RunEventModel

    events = (
        db.query(RunEventModel)
        .filter(RunEventModel.run_id == run_id)
        .order_by(RunEventModel.created_at)
        .all()
    )
    return [
        {
            "id": e.id,
            "event_type": e.event_type,
            "stage": e.stage,
            "severity": e.severity,
            "message": e.message,
            "payload": json.loads(e.payload_json),
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]


@router.get("/runs/{run_id}/thread")
def run_thread(run_id: str, db: Session = Depends(get_db)):
    from app.db.models import RunModel

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    return RunThreadService(db).list_entries(run_id)


@router.post("/runs/{run_id}/clarify")
def clarify_run(run_id: str, body: ClarifyRequest, db: Session = Depends(get_db)):
    from app.db.models import RunModel

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status != "awaiting_clarification":
        raise HTTPException(400, "Run is not awaiting clarification")
    question = run.clarification_question or "Clarification requested"
    clarification_context = dict(run.clarification_context or {})
    clarification_context["question"] = question
    clarification_context["answer"] = body.answer.strip()
    pending_gate = str(clarification_context.get("pending_gate") or "").strip()
    if not pending_gate:
        stage_hint = str(run.clarification_stage or run.current_stage or "").strip().lower()
        if stage_hint == "architect":
            pending_gate = "architect_navigation"
        elif stage_hint == "planner":
            pending_gate = "planner_surface"
    if pending_gate:
        resolved = list(clarification_context.get("resolved_gates") or [])
        if pending_gate not in resolved:
            resolved.append(pending_gate)
        clarification_context["resolved_gates"] = resolved
        clarification_context.pop("pending_gate", None)
    run.clarification_context_json = json.dumps(clarification_context)
    run.operator_feedback = "\n\n".join(
        item for item in [run.operator_feedback or "", f"Clarification answer: {body.answer.strip()}"] if item.strip()
    )
    target_stage = run.clarification_stage or run.current_stage or "planner"
    run.status = "running"
    run.current_stage = target_stage
    run.clarification_question = None
    run.clarification_stage = None
    db.commit()
    RunThreadService(db).append_entry(
        run_id,
        entry_type="clarification_answered",
        stage=target_stage,
        severity="info",
        message=f"Clarification answered: {body.answer.strip()}",
        payload={"question": question, "answer": body.answer.strip()},
        role="user",
    )
    run_engine.enqueue(run.id)
    return {"ok": True, "run_id": run.id, "status": run.status, "current_stage": run.current_stage}


@router.get("/runs/{run_id}/artifacts")
def run_artifacts(run_id: str, db: Session = Depends(get_db)):
    from app.db.models import ArtifactModel

    arts = db.query(ArtifactModel).filter(ArtifactModel.run_id == run_id).all()
    return [_artifact_to_response(a) for a in arts]


@router.get("/runs/{run_id}/deployment-readiness")
def get_run_deployment_readiness(run_id: str, db: Session = Depends(get_db)):
    from app.db.models import RunModel
    from app.services.deployment_gates import evaluate_deployment_readiness

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    return evaluate_deployment_readiness(db, run_id)


@router.get("/runs/{run_id}/postmortem")
def get_run_postmortem(run_id: str, db: Session = Depends(get_db)):
    from app.db.models import ArtifactModel, RunModel

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    LearningService(db).ensure_run_learning_state(run)
    artifact = (
        db.query(ArtifactModel)
        .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == "postmortem")
        .order_by(ArtifactModel.id.desc())
        .first()
    )
    if not artifact and run.status in {"failed", "blocked", "changes_requested"}:
        LearningService(db).finalize_terminal_run(run_id)
        artifact = (
            db.query(ArtifactModel)
            .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == "postmortem")
            .order_by(ArtifactModel.id.desc())
            .first()
        )
    if not artifact:
        raise HTTPException(404, "Postmortem not available")
    return _artifact_to_response(artifact)


@router.get("/runs/{run_id}/files/{path:path}")
def read_run_workspace_file(run_id: str, path: str, db: Session = Depends(get_db)):
    from pathlib import Path

    from app.db.models import RunModel

    _guard_traversal(path)
    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    if not run.workspace_path or not Path(run.workspace_path).is_dir():
        raise HTTPException(404, "Run workspace not available")
    project = ProjectService(db).get(run.project_id)
    fs = FileService(Path(run.workspace_path), project.protected_files)
    try:
        return fs.read_file(path)
    except PathTraversalError as exc:
        raise HTTPException(400, str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/projects/{project_id}/runs")
def project_runs(project_id: str, db: Session = Depends(get_db)):
    from app.db.models import RunModel, TaskModel

    runs = (
        db.query(RunModel)
        .filter(RunModel.project_id == project_id)
        .order_by(RunModel.created_at.desc())
        .limit(20)
        .all()
    )
    if not runs:
        return []
    learner = LearningService(db)
    for run in runs:
        learner.ensure_run_learning_state(run)
    task_ids = {r.task_id for r in runs}
    tasks = {t.id: t for t in db.query(TaskModel).filter(TaskModel.id.in_(task_ids)).all()}
    numbers = run_numbers_for_task(runs)
    return [
        {
            "id": r.id,
            "display_name": derive_run_display_name(
                tasks[r.task_id].description if r.task_id in tasks else "",
                r.created_at,
                run_number=numbers.get(r.id),
            ),
            "status": r.status,
            "current_stage": r.current_stage,
            "task_id": r.task_id,
            "task_kind": getattr(r, "task_kind", None),
            "failure_class": getattr(r, "failure_class", None),
            "recovery_status": getattr(r, "recovery_status", None),
            "error_message": (r.error_message or "")[:120] or None,
            "created_at": r.created_at.isoformat(),
        }
        for r in runs
    ]


@router.post("/runs/{run_id}/approve")
async def approve_run(run_id: str, body: ApproveRequest, db: Session = Depends(get_db)):
    try:
        return await run_in_threadpool(approve_run_sync, run_id, body.comment or "")
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/runs/{run_id}/reject")
def reject_run(run_id: str, body: RejectRequest, db: Session = Depends(get_db)):
    from app.core.enums import RunStatus
    from app.db.models import RunModel

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    run.status = RunStatus.CHANGES_REQUESTED
    run.error_message = body.reason
    db.commit()
    RunThreadService(db).append_entry(
        run_id,
        entry_type="run_rejected",
        stage=run.current_stage,
        severity="warning",
        message=body.reason,
        payload={"status": RunStatus.CHANGES_REQUESTED.value},
    )
    persist_run_truth(db, run_id)
    LearningService(db).finalize_terminal_run(run_id)
    return {"ok": True}


@router.post("/runs/{run_id}/retry")
def retry_run(run_id: str, body: RetryRequest | None = None, db: Session = Depends(get_db)):
    from app.core.enums import RunStatus
    from app.db.models import ArtifactModel, RunModel
    from app.services.orchestration_service import claim_run

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status not in (
        RunStatus.BLOCKED.value,
        RunStatus.CHANGES_REQUESTED.value,
        RunStatus.FAILED.value,
    ):
        raise HTTPException(400, "Run not retryable")
    if body and body.feedback:
        run.operator_feedback = body.feedback.strip()
    run.retry_count = int(getattr(run, "retry_count", 0) or 0) + 1
    run.status = RunStatus.PENDING
    run.error_message = None
    run.review_attempts = 0
    run.terminal_success = None
    run.terminal_status = None
    run.schema_failure_count = 0
    run.reviewer_failure_count = 0
    run.tester_failure_count = 0
    run.operator_feedback_present = bool((run.operator_feedback or "").strip())
    run.approval_reached = False
    run.promote_rolled_back = False
    run.approval_override = False
    run.clarification_question = None
    run.clarification_stage = None
    run.clarification_context_json = "{}"
    from app.services.visual_evidence_service import clear_visual_evidence_artifacts

    for artifact_type in ("test_plan", "visual_evidence", "pre_deploy_supervisor"):
        db.query(ArtifactModel).filter(
            ArtifactModel.run_id == run_id,
            ArtifactModel.artifact_type == artifact_type,
        ).delete()
    clear_visual_evidence_artifacts(db, run_id)
    run.primary_failure_class = None
    if hasattr(run, "failure_class"):
        run.failure_class = None
        run.failure_subclass = None
        run.failure_signature = None
        run.recovery_status = "none"
        run.superseded_by_run_id = None
    db.commit()
    RunThreadService(db).append_entry(
        run_id,
        entry_type="run_retried",
        stage=run.current_stage,
        severity="info",
        message="Pipeline retry started" + (f": {body.feedback.strip()}" if body and body.feedback else ""),
        payload={"feedback": body.feedback.strip() if body and body.feedback else ""},
    )
    persist_run_truth(db, run_id)
    if claim_run(db, run.id):
        run_engine.enqueue(run.id)
    return {"ok": True}


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str, db: Session = Depends(get_db)):
    from app.core.enums import RunStatus
    from app.db.models import RunModel

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status not in (RunStatus.RUNNING.value, RunStatus.PENDING.value):
        raise HTTPException(400, "Run is not resumable")
    run_engine.enqueue(run.id)
    return {"ok": True, "run_id": run.id, "status": run.status}


@router.post("/runs/{run_id}/rollback-workspace")
def rollback_run_workspace(run_id: str, db: Session = Depends(get_db)):
    from pathlib import Path

    from app.core.enums import RunStatus
    from app.db.models import RunModel
    from app.services.workspace_service import reset_run_workspace

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    allowed = {
        RunStatus.AWAITING_APPROVAL.value,
        RunStatus.CHANGES_REQUESTED.value,
        RunStatus.BLOCKED.value,
        RunStatus.FAILED.value,
    }
    if run.status not in allowed:
        raise HTTPException(400, "Run workspace cannot be rolled back in current status")
    project = ProjectService(db).get(run.project_id)
    workspace = reset_run_workspace(Path(project.source_repo_spec), run_id)
    run.workspace_path = str(workspace)
    run.operator_feedback = None
    if run.status == RunStatus.AWAITING_APPROVAL.value:
        run.status = RunStatus.CHANGES_REQUESTED.value
        run.error_message = "Workspace reset; re-run pipeline to regenerate changes."
    db.commit()
    LearningService(db).finalize_terminal_run(run_id)
    event_bus.emit(
        run_id,
        {
            "type": "workspace_rolled_back",
            "run_id": run_id,
            "message": "Run workspace reset from project source",
        },
    )
    return {"ok": True, "workspace_path": str(workspace)}


@router.post("/runs/{run_id}/rollback-promote")
def rollback_run_promote(run_id: str, db: Session = Depends(get_db)):
    from pathlib import Path

    from app.core.enums import RunStatus
    from app.db.models import RunModel
    from app.services.snapshot_service import restore_promoted_files

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status != RunStatus.COMPLETED.value:
        raise HTTPException(400, "Only completed runs with a promotion snapshot can be rolled back")
    if not run.promote_snapshot_json:
        raise HTTPException(400, "No promotion snapshot for this run")
    try:
        snapshot_meta = json.loads(run.promote_snapshot_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "Invalid promotion snapshot metadata") from exc
    project = ProjectService(db).get(run.project_id)
    restored = restore_promoted_files(run_id, Path(project.source_repo_spec), snapshot_meta)
    run.promote_snapshot_json = None
    run.status = RunStatus.CHANGES_REQUESTED.value
    run.promote_rolled_back = True
    run.error_message = f"Promoted changes rolled back ({restored} file(s) restored)"
    db.commit()
    LearningService(db).finalize_terminal_run(run_id)
    event_bus.emit(
        run_id,
        {
            "type": "run_changes_requested",
            "run_id": run_id,
            "message": run.error_message,
        },
    )
    return {"ok": True, "restored_files": restored}


@router.post("/lessons/{lesson_id}/promote-global")
def promote_lesson_global(lesson_id: int, db: Session = Depends(get_db)):
    try:
        return LearningService(db).promote_lesson_to_global(lesson_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/improvements/{improvement_id}/override")
def override_improvement(improvement_id: str, body: dict, db: Session = Depends(get_db)):
    status = str(body.get("status") or "").strip()
    scope = str(body.get("scope") or "").strip() or None
    try:
        return LearningService(db).override_improvement_status(improvement_id, status, scope=scope)
    except ValueError as exc:
        raise HTTPException(400 if "Invalid" in str(exc) else 404, str(exc)) from exc


@router.get("/skills/global")
def list_global_skills(db: Session = Depends(get_db)):
    return LearningService(db).list_global_skills()


@router.post("/skills/global/{skill_id}/deprecate")
def deprecate_global_skill(skill_id: str, db: Session = Depends(get_db)):
    try:
        return LearningService(db).deprecate_global_skill(skill_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/projects/{project_id}/git/status")
def git_status(project_id: str, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    gs = GitService(__import__("pathlib").Path(project.source_repo_spec))
    status = gs.status()
    status["branch"] = gs.current_branch()
    status["has_remote"] = gs.has_remote()
    return status


@router.post("/projects/{project_id}/git/stage")
def git_stage(project_id: str, body: GitStageRequest, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    GitService(__import__("pathlib").Path(project.source_repo_spec)).stage(body.paths)
    return {"ok": True}


@router.post("/projects/{project_id}/git/unstage")
def git_unstage(project_id: str, body: GitStageRequest, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    GitService(__import__("pathlib").Path(project.source_repo_spec)).unstage(body.paths)
    return {"ok": True}


@router.post("/projects/{project_id}/git/commit")
def git_commit(project_id: str, body: GitCommitRequest, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    config = ConfigService(db).get_all()
    try:
        sha = GitService(__import__("pathlib").Path(project.source_repo_spec)).commit(
            body.message,
            config.get("git_author_name", "AI Copilot"),
            config.get("git_author_email", "copilot@local.dev"),
        )
        return {"sha": sha}
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/projects/{project_id}/git/log")
def git_log(project_id: str, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    return GitService(__import__("pathlib").Path(project.source_repo_spec)).log()


@router.get("/projects/{project_id}/git/branches")
def git_branches(project_id: str, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    gs = GitService(__import__("pathlib").Path(project.source_repo_spec))
    return {"current": gs.current_branch(), "branches": gs.branches()}


@router.post("/projects/{project_id}/git/checkout")
def git_checkout(project_id: str, body: GitCheckoutRequest, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    GitService(__import__("pathlib").Path(project.source_repo_spec)).checkout(body.branch)
    return {"ok": True}


@router.get("/projects/{project_id}/git/diff/{path:path}")
def git_diff(project_id: str, path: str, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    return GitService(__import__("pathlib").Path(project.source_repo_spec)).diff(path)


@router.post("/projects/{project_id}/git/push")
def git_push(project_id: str, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    try:
        GitService(__import__("pathlib").Path(project.source_repo_spec)).push()
        return {"ok": True}
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/projects/{project_id}/git/pull")
def git_pull(project_id: str, db: Session = Depends(get_db)):
    project = ProjectService(db).get(project_id)
    try:
        GitService(__import__("pathlib").Path(project.source_repo_spec)).pull()
        return {"ok": True}
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/logs")
async def get_logs(
    limit: int = Query(200, ge=1, le=2000),
    level: str | None = None,
    run_id: str | None = None,
    stream: bool = False,
):
    if stream:

        async def event_generator():
            seen = 0
            while True:
                lines = read_log_lines(limit)
                if level:
                    lines = [line for line in lines if line.get("level") == level.lower()]
                if run_id:
                    lines = [line for line in lines if line.get("run_id") == run_id]
                if len(lines) > seen:
                    for line in lines[seen:]:
                        yield {"event": "log", "data": json.dumps(line)}
                    seen = len(lines)
                await asyncio.sleep(1)

        return EventSourceResponse(event_generator())

    lines = read_log_lines(limit)
    if level:
        lines = [line for line in lines if line.get("level") == level.lower()]
    if run_id:
        lines = [line for line in lines if line.get("run_id") == run_id]
    return {"lines": lines}


terminal_sessions: dict[str, Any] = {}


@router.websocket("/ws/terminal/{session_id}")
async def terminal_ws(websocket: WebSocket, session_id: str, project_id: str = Query(...)):
    verify_websocket_token(websocket)
    await websocket.accept()
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        project = ProjectService(db).get(project_id)
        cwd = project.source_repo_spec
    finally:
        db.close()

    shell = os.environ.get("SHELL", "/bin/bash")
    proc = ptyprocess.PtyProcess.spawn([shell], cwd=cwd)
    terminal_sessions[session_id] = proc
    event_bus.ws_connections += 1

    async def read_pty():
        loop = asyncio.get_running_loop()
        while proc.isalive():
            try:
                data = await loop.run_in_executor(None, proc.read, 1024)
                if data:
                    await websocket.send_text(data.decode("utf-8", errors="replace"))
            except Exception:
                break

    read_task = asyncio.create_task(read_pty())

    try:
        while True:
            msg = await websocket.receive_text()
            try:
                payload = json.loads(msg)
                if payload.get("type") == "resize":
                    proc.setwinsize(payload["rows"], payload["cols"])
                elif payload.get("type") == "input":
                    proc.write(payload["data"])
                else:
                    proc.write(msg)
            except json.JSONDecodeError:
                proc.write(msg)
    except WebSocketDisconnect:
        pass
    finally:
        read_task.cancel()
        if proc.isalive():
            proc.terminate(force=True)
        terminal_sessions.pop(session_id, None)
        event_bus.ws_connections -= 1


@router.websocket("/ws/runs/{run_id}")
async def run_ws(websocket: WebSocket, run_id: str):
    verify_websocket_token(websocket)
    await websocket.accept()
    event_bus.ws_connections += 1
    q = event_bus.subscribe_run(run_id)
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30)
                await websocket.send_json(event)
                if event.get("type") in (
                    "run_completed",
                    "run_blocked",
                    "run_failed",
                    "run_changes_requested",
                    "awaiting_approval",
                ):
                    break
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe_run(run_id, q)
        event_bus.ws_connections -= 1


@router.websocket("/ws/events")
async def events_ws(websocket: WebSocket):
    verify_websocket_token(websocket)
    await websocket.accept()
    event_bus.ws_connections += 1
    q = event_bus.subscribe_global()
    try:
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30)
                await websocket.send_json(event)
            except asyncio.TimeoutError:
                await websocket.send_json({"type": "ping", "connections": event_bus.ws_connections})
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe_global(q)
        event_bus.ws_connections -= 1


@router.websocket("/ws/browser")
async def browser_ws(websocket: WebSocket, project_id: str = Query(...)):
    from app.services.browser_control_service import browser_control

    verify_websocket_token(websocket)
    await websocket.accept()
    event_bus.ws_connections += 1
    command_queue = browser_control.register_client(project_id)
    await websocket.send_json({"type": "browser_connected", "project_id": project_id})
    forward_task = None
    try:
        async def forward_commands() -> None:
            while True:
                command = await command_queue.get()
                await websocket.send_json(command)

        forward_task = asyncio.create_task(forward_commands())
        while True:
            message = await websocket.receive_json()
            msg_type = str(message.get("type") or "")
            if msg_type == "browser_ready":
                continue
            if msg_type == "browser_result":
                browser_control.resolve_result(
                    project_id,
                    str(message.get("request_id") or ""),
                    bool(message.get("ok")),
                    message.get("result") if isinstance(message.get("result"), dict) else {},
                    str(message.get("error") or "") or None,
                )
    except WebSocketDisconnect:
        pass
    finally:
        if forward_task is not None:
            forward_task.cancel()
        browser_control.unregister_client(project_id)
        event_bus.ws_connections -= 1


@router.get("/runs/{run_id}/evidence/{filename}")
def run_evidence_file(
    run_id: str,
    filename: str,
    db: Session = Depends(get_db),
    token: str | None = Query(default=None),
):
    from pathlib import Path

    from fastapi.responses import FileResponse

    from app.db.models import RunModel

    from app.api.deps import verify_api_token_value

    verify_api_token_value(token)
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(400, "Invalid filename")
    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run or not run.workspace_path:
        raise HTTPException(404, "Run not found")
    path = Path(run.workspace_path) / ".ai-copilot" / "runs" / run_id / "evidence" / filename
    if not path.is_file():
        raise HTTPException(404, "Evidence file not found")
    media = "image/png" if filename.lower().endswith(".png") else "application/octet-stream"
    return FileResponse(path, media_type=media)


@router.post("/runs/{run_id}/continue-visual")
def continue_visual_verification(run_id: str, db: Session = Depends(get_db)):
    import json
    from pathlib import Path

    from app.core.enums import RunStatus
    from app.db.models import ArtifactModel, RunModel
    from app.services.orchestration_service import orchestration_service
    from app.services.project_service import ProjectService
    from app.services.run_truth_service import persist_run_truth
    from app.services.visual_evidence_service import clear_visual_evidence_artifacts, execute_visual_checks, load_visual_evidence
    from app.services.workspace_service import list_workspace_changed_files
    from app.services.workspace_dev_url import build_default_visual_checks

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status != RunStatus.BLOCKED.value:
        raise HTTPException(400, "Run is not blocked")
    evidence = load_visual_evidence(db, run_id) or {}
    if not evidence.get("browser_client_required") and evidence.get("passed"):
        raise HTTPException(400, "Visual verification already passed")
    workspace = Path(run.workspace_path) if run.workspace_path else None
    if not workspace or not workspace.is_dir():
        raise HTTPException(400, "Run workspace unavailable")
    test_plan_row = (
        db.query(ArtifactModel)
        .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == "test_plan")
        .order_by(ArtifactModel.id.desc())
        .first()
    )
    visual_checks: list[dict] = []
    if test_plan_row:
        try:
            plan = json.loads(test_plan_row.content_json)
            visual_checks = list(plan.get("visual_checks") or [])
        except json.JSONDecodeError:
            visual_checks = []
    if not visual_checks:
        project = ProjectService(db).get(run.project_id)
        changed = list_workspace_changed_files(workspace, Path(project.source_repo_spec))
        visual_checks = build_default_visual_checks(workspace, changed)
    clear_visual_evidence_artifacts(db, run_id)
    result = execute_visual_checks(
        db,
        run_id,
        workspace,
        visual_checks,
        project_id=run.project_id,
    )
    if not result.get("passed"):
        run.error_message = "Visual evidence capture failed"
        db.commit()
        persist_run_truth(db, run_id)
        return {"ok": False, "passed": False, "evidence": result}
    project = ProjectService(db).get(run.project_id)
    source_root = Path(project.source_repo_spec)
    run.status = RunStatus.RUNNING.value
    run.current_stage = "tester"
    run.error_message = None
    db.commit()
    if orchestration_service._finalize_deployment_gates(db, run_id, workspace, source_root):
        run.status = RunStatus.AWAITING_APPROVAL.value
        run.operator_feedback = None
        db.commit()
        orchestration_service._record_event(
            db, run_id, "awaiting_approval", run.current_stage or "", "info", "Run awaiting approval"
        )
        orchestration_service._emit(run_id, "awaiting_approval", "", "Run awaiting approval")
        persist_run_truth(db, run_id)
        return {"ok": True, "passed": True, "evidence": result, "status": run.status}
    run.status = RunStatus.BLOCKED.value
    run.error_message = "Deployment gates failed after visual verification"
    db.commit()
    persist_run_truth(db, run_id)
    return {"ok": False, "passed": False, "evidence": result, "status": run.status}
