from __future__ import annotations

import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

import ptyprocess
from starlette.concurrency import run_in_threadpool
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse
from sqlalchemy.orm import Session

from app.api.deps import verify_websocket_token
from app.api.routes.chat import router as chat_router
from app.core.exceptions import (
    AICopilotError,
    CommandRejectedError,
    NotFoundError,
    PatchGuardError,
    PathTraversalError,
    ValidationError,
)
from app.core.logging import new_request_id, read_log_lines, request_id_var
from app.core.settings import get_settings
from app.db.session import get_db, seed_app_config
from app.schemas.api import (
    ApproveRequest,
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
from app.services.learning_service import LearningService
from app.services.orchestration_service import create_task_and_run, run_engine
from app.services.run_approval_service import approve_run_sync
from app.services.run_display import derive_run_display_name, run_numbers_for_task
from app.services.run_engine.event_bus import event_bus
from app.services.tree_cache import get_cached_tree, invalidate_tree_cache, store_tree_cache
from app.services.project_service import ProjectService

router = APIRouter()
router.include_router(chat_router)


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
        },
    )
    return {
        "task": {
            "id": task.id,
            "project_id": task.project_id,
            "description": task.description,
            "validation_profile": task.validation_profile,
            "use_scout": task.use_scout,
            "created_at": task.created_at.isoformat(),
        },
        "run": {
            "id": run.id,
            "status": run.status,
            "display_name": derive_run_display_name(task.description, run.created_at),
        },
    }


@router.get("/runs/failure-summary")
def get_failure_summary(project_id: str | None = None, db: Session = Depends(get_db)):
    return LearningService(db).failure_summary(project_id)


@router.get("/runs/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    from app.db.models import RunModel, TaskModel

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    task = db.get(TaskModel, run.task_id)
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


@router.get("/runs/{run_id}/artifacts")
def run_artifacts(run_id: str, db: Session = Depends(get_db)):
    from app.db.models import ArtifactModel

    arts = db.query(ArtifactModel).filter(ArtifactModel.run_id == run_id).all()
    return [_artifact_to_response(a) for a in arts]


@router.get("/runs/{run_id}/postmortem")
def get_run_postmortem(run_id: str, db: Session = Depends(get_db)):
    from app.db.models import ArtifactModel, RunModel

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
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
    LearningService(db).finalize_terminal_run(run_id)
    return {"ok": True}


@router.post("/runs/{run_id}/retry")
def retry_run(run_id: str, body: RetryRequest | None = None, db: Session = Depends(get_db)):
    from app.core.enums import RunStatus
    from app.db.models import RunModel
    from app.services.orchestration_service import claim_run

    run = db.query(RunModel).filter(RunModel.id == run_id).first()
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status not in (RunStatus.BLOCKED, RunStatus.CHANGES_REQUESTED):
        raise HTTPException(400, "Run not retryable")
    if body and body.feedback:
        run.operator_feedback = body.feedback.strip()
    run.status = RunStatus.PENDING
    run.error_message = None
    run.review_attempts = 0
    if hasattr(run, "failure_class"):
        run.failure_class = None
        run.failure_subclass = None
        run.failure_signature = None
        run.recovery_status = "none"
        run.superseded_by_run_id = None
    db.commit()
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
                    lines = [l for l in lines if l.get("level") == level.lower()]
                if run_id:
                    lines = [l for l in lines if l.get("run_id") == run_id]
                if len(lines) > seen:
                    for line in lines[seen:]:
                        yield {"event": "log", "data": json.dumps(line)}
                    seen = len(lines)
                await asyncio.sleep(1)

        return EventSourceResponse(event_generator())

    lines = read_log_lines(limit)
    if level:
        lines = [l for l in lines if l.get("level") == level.lower()]
    if run_id:
        lines = [l for l in lines if l.get("run_id") == run_id]
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
