from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.enums import RunStatus
from app.core.exceptions import NotFoundError, ValidationError
from app.db.models import ArtifactModel, RunModel
from app.db.session import SessionLocal
from app.services.learning_service import LearningService
from app.services.project_service import ProjectService
from app.services.run_engine.event_bus import event_bus
from app.services.snapshot_service import snapshot_promoted_files
from app.services.deployment_gates import assert_ready_for_approval
from app.services.supervisor_service import run_post_deploy_supervisor
from app.services.workspace_service import list_workspace_changed_files
from app.services.workspace_service import cleanup_run_workspace, promote_to_source
from app.services.run_truth_service import persist_run_truth
from app.services.run_thread_service import RunThreadService


def _record_run_event(
    db: Session,
    run_id: str,
    event_type: str,
    stage: str,
    severity: str,
    message: str,
) -> None:
    from app.db.models import RunEventModel

    db.add(
        RunEventModel(
            run_id=run_id,
            event_type=event_type,
            stage=stage,
            severity=severity,
            message=message,
            payload_json="{}",
        )
    )
    try:
        RunThreadService(db).append_entry(
            run_id,
            entry_type=event_type,
            stage=stage or None,
            severity=severity,
            message=message,
        )
    except Exception:
        pass


def approve_run_sync(run_id: str, comment: str = "") -> dict:
    db = SessionLocal()
    try:
        run = db.query(RunModel).filter(RunModel.id == run_id).first()
        if not run:
            raise NotFoundError(f"Run not found: {run_id}")
        if run.status != RunStatus.AWAITING_APPROVAL.value:
            raise ValidationError("Run not awaiting approval")

        assert_ready_for_approval(db, run_id)

        project = ProjectService(db).get(run.project_id)
        readiness = persist_run_truth(db, run_id)
        warning_list = list(readiness.get("warnings") or [])
        if warning_list:
            run.approval_override = True
            db.commit()
            RunThreadService(db).append_entry(
                run_id,
                entry_type="approval_warning",
                stage=run.current_stage,
                severity="warning",
                message="Approving run with readiness warnings.",
                payload={
                    "warnings": warning_list,
                    "mismatch_classes": readiness.get("mismatch_classes") or [],
                    "approval_override": True,
                },
            )
        source = Path(project.source_repo_spec)
        paths: list[str] = []
        if run.workspace_path:
            workspace = Path(run.workspace_path)
            paths = list_workspace_changed_files(workspace, source)
        if not paths:
            coder = (
                db.query(ArtifactModel)
                .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == "coder")
                .order_by(ArtifactModel.id.desc())
                .first()
            )
            if coder:
                try:
                    content = json.loads(coder.content_json)
                    for change in content.get("file_changes") or []:
                        path = change.get("path") or change.get("file_path")
                        if path:
                            paths.append(str(path))
                except json.JSONDecodeError:
                    paths = []
        if paths:
            snapshot_meta = snapshot_promoted_files(run_id, source, paths)
            run.promote_snapshot_json = json.dumps(snapshot_meta)
        if run.workspace_path:
            promote_to_source(Path(run.workspace_path), source)
        supervisor_payload = None
        if paths:
            try:
                supervisor_payload = run_post_deploy_supervisor(db, run_id, paths)
            except Exception as exc:
                _record_run_event(
                    db,
                    run_id,
                    "supervisor_failed",
                    "supervisor",
                    "warning",
                    f"Post-deploy supervisor failed: {exc}",
                )
                db.commit()
        run.status = RunStatus.COMPLETED.value
        run.operator_feedback = comment or None
        db.commit()
        persist_run_truth(db, run_id)
        if supervisor_payload:
            gaps = supervisor_payload.get("plan_gaps") or []
            _record_run_event(
                db,
                run_id,
                "supervisor_complete",
                "supervisor",
                "info" if supervisor_payload.get("approved") else "warning",
                supervisor_payload.get("summary") or "Supervisor attestation complete",
            )
            if gaps:
                _record_run_event(
                    db,
                    run_id,
                    "supervisor_plan_gaps",
                    "supervisor",
                    "warning",
                    f"{len(gaps)} plan gap(s) recorded after deployment",
                )
            db.commit()
        _record_run_event(db, run_id, "run_completed", "", "info", "Run approved and promoted")
        db.commit()
        RunThreadService(db).append_entry(
            run_id,
            entry_type="approval_completed",
            stage=run.current_stage,
            severity="info",
            message="Run approved and promoted",
            payload={
                "approval_override": bool(run.approval_override),
                "warnings": warning_list,
            },
        )
        LearningService(db).finalize_terminal_run(run_id)
        cleanup_run_workspace(run, project)
        event_bus.emit(run_id, {"type": "run_completed", "run_id": run_id})
        return {"ok": True, "warnings": warning_list, "approval_override": bool(run.approval_override)}
    finally:
        db.close()
