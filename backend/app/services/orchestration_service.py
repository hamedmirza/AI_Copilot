import json
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from app.agents import (
    ArchitectAgent,
    CoderAgent,
    PlannerAgent,
    ReviewerAgent,
    TesterAgent,
    UIDesignerAgent,
)
from app.core.enums import PipelineStage, RunStatus
from app.core.logging import run_id_var, worker_id_var
from app.db.models import ArtifactModel, RunEventModel, RunModel, TaskModel
from app.db.session import SessionLocal
from app.providers.registry import ProviderRegistry
from app.services.config_service import ConfigService
from app.services.file_service import FileService
from app.services.project_service import ProjectService
from app.services.run_engine.event_bus import event_bus
from app.tools.command_runner import run_command

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2)


class OrchestrationService:
    TERMINAL = {
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
        RunStatus.AWAITING_APPROVAL.value,
        RunStatus.BLOCKED.value,
    }

    def __init__(self) -> None:
        self._loop = None

    def set_loop(self, loop) -> None:
        self._loop = loop

    def enqueue_run(self, run_id: str) -> None:
        _executor.submit(self._execute_run, run_id)

    def enqueue(self, run_id: str) -> None:
        self.enqueue_run(run_id)

    def _emit(
        self,
        run_id: str,
        event_type: str,
        stage: str,
        message: str,
        payload: dict | None = None,
    ) -> None:
        event_bus.emit(
            run_id,
            {
                "type": event_type,
                "stage": stage,
                "message": message,
                "payload": payload or {},
            },
        )

    def _execute_run(self, run_id: str) -> None:
        worker_id_var.set("worker-1")
        run_id_var.set(run_id)
        db = SessionLocal()
        try:
            run = db.get(RunModel, run_id)
            if not run:
                return
            if run.status == RunStatus.PENDING.value:
                if not self._claim_run(db, run_id):
                    return
            elif run.status != RunStatus.RUNNING.value:
                return
            self._pipeline(db, run_id)
        except Exception as exc:
            logger.exception("Run %s failed: %s", run_id, exc)
            run = db.get(RunModel, run_id)
            if run:
                run.status = RunStatus.FAILED.value
                run.error_message = str(exc)
                db.commit()
                self._record_event(db, run_id, "run_failed", "", "error", str(exc))
                self._emit(run_id, "run_failed", "", str(exc))
        finally:
            db.close()
            run_id_var.set(None)

    def _claim_run(self, db: Session, run_id: str) -> bool:
        updated = (
            db.query(RunModel)
            .filter(RunModel.id == run_id, RunModel.status == RunStatus.PENDING.value)
            .update({"status": RunStatus.RUNNING.value})
        )
        db.commit()
        return updated == 1

    def _record_event(
        self,
        db: Session,
        run_id: str,
        event_type: str,
        stage: str,
        severity: str,
        message: str,
        payload: dict | None = None,
    ) -> None:
        db.add(
            RunEventModel(
                run_id=run_id,
                event_type=event_type,
                stage=stage,
                severity=severity,
                message=message,
                payload_json=json.dumps(payload or {}),
            )
        )
        db.commit()

    def _save_artifact(self, db: Session, run_id: str, artifact_type: str, content: dict) -> None:
        db.add(
            ArtifactModel(
                run_id=run_id,
                artifact_type=artifact_type,
                content_json=json.dumps(content),
            )
        )
        db.commit()

    def _pipeline(self, db: Session, run_id: str) -> None:
        run = db.get(RunModel, run_id)
        if not run:
            return
        project = ProjectService(db).get(run.project_id)
        workspace = Path(project.source_repo_spec)
        run.workspace_path = str(workspace)
        db.commit()

        task = run.task
        context_base = task.description
        fs = FileService(workspace, project.protected_files)

        ConfigService(db).reload_registry()

        stages: list[tuple[PipelineStage, callable]] = [
            (PipelineStage.PLANNER, lambda: self._stage_planner(db, run_id, context_base)),
            (PipelineStage.ARCHITECT, lambda: self._stage_architect(db, run_id, context_base)),
            (PipelineStage.UI_DESIGNER, lambda: self._stage_ui(db, run_id, context_base)),
            (PipelineStage.CODER, lambda: self._stage_coder(db, run_id, context_base, fs)),
            (PipelineStage.REVIEWER, lambda: self._stage_reviewer_loop(db, run_id, context_base, fs)),
            (PipelineStage.TESTER, lambda: self._stage_tester(db, run_id, context_base, workspace)),
        ]

        for stage, fn in stages:
            run = db.get(RunModel, run_id)
            run.current_stage = stage.value
            db.commit()
            self._record_event(db, run_id, f"{stage.value}_started", stage.value, "info", f"{stage.value} started")
            self._emit(run_id, f"{stage.value}_started", stage.value, f"{stage.value} started")
            try:
                result = fn()
                if result is False:
                    return
            except Exception as exc:
                run = db.get(RunModel, run_id)
                run.status = RunStatus.FAILED.value
                run.error_message = str(exc)
                db.commit()
                self._record_event(db, run_id, f"{stage.value}_failed", stage.value, "error", str(exc))
                self._emit(run_id, f"{stage.value}_failed", stage.value, str(exc))
                if ConfigService(db).get_all().get("stop_on_first_failure", True):
                    return
                continue
            self._record_event(db, run_id, f"{stage.value}_complete", stage.value, "info", f"{stage.value} complete")
            self._emit(run_id, f"{stage.value}_complete", stage.value, f"{stage.value} complete")

        run = db.get(RunModel, run_id)
        if run.status == RunStatus.RUNNING.value:
            run.status = RunStatus.AWAITING_APPROVAL.value
            db.commit()
            self._emit(run_id, "awaiting_approval", "", "Run awaiting approval")

    def _stage_planner(self, db: Session, run_id: str, context: str):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.PLANNER)
        agent = PlannerAgent(provider)
        output = agent.plan(context)
        self._save_artifact(db, run_id, "plan", output.model_dump())
        return True

    def _stage_architect(self, db: Session, run_id: str, context: str):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.ARCHITECT)
        agent = ArchitectAgent(provider)
        output = agent.design(context)
        self._save_artifact(db, run_id, "architect", output.model_dump())
        return True

    def _stage_ui(self, db: Session, run_id: str, context: str):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.UI_DESIGNER)
        agent = UIDesignerAgent(provider)
        output = agent.design(context)
        if output is None:
            self._record_event(db, run_id, "ui_designer_skipped", "ui_designer", "info", "UI stage skipped")
            return True
        self._save_artifact(db, run_id, "ui_design", output.model_dump())
        return True

    def _stage_coder(self, db: Session, run_id: str, context: str, fs: FileService):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.CODER)
        agent = CoderAgent(provider)
        output = agent.code(context)
        changes = [
            fc if isinstance(fc, dict) else fc.model_dump() for fc in output.file_changes
        ]
        fs.apply_coder_changes(changes)
        self._save_artifact(db, run_id, "coder", output.model_dump())
        self._record_event(db, run_id, "code_patch_applied", "coder", "info", "Patch applied")
        self._emit(run_id, "code_patch_applied", "coder", "Patch applied")
        return True

    def _stage_reviewer_loop(self, db: Session, run_id: str, context: str, fs: FileService):
        max_retries = int(ConfigService(db).get_all().get("max_review_retries", 3))
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.REVIEWER)
        agent = ReviewerAgent(provider)
        for attempt in range(1, max_retries + 1):
            run = db.get(RunModel, run_id)
            run.review_attempts = attempt
            db.commit()
            output = agent.review(context)
            self._save_artifact(db, run_id, f"review_{attempt}", output.model_dump())
            if output.approved:
                return True
            if attempt < max_retries:
                self._stage_coder(db, run_id, context, fs)
            else:
                run = db.get(RunModel, run_id)
                run.status = RunStatus.CHANGES_REQUESTED.value
                db.commit()
                return False
        return True

    def _stage_tester(self, db: Session, run_id: str, context: str, workspace):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.TESTER)
        agent = TesterAgent(provider)
        output = agent.test_plan(context)
        self._save_artifact(db, run_id, "test_plan", output.model_dump())

        all_passed = True
        for cmd in output.commands:
            self._record_event(db, run_id, "validation_started", "tester", "info", cmd.command)
            self._emit(run_id, "validation_started", "tester", cmd.command)
            try:
                code, stdout, stderr = run_command(cmd.command, workspace)
                passed = code == 0
                all_passed = all_passed and passed
                self._record_event(
                    db,
                    run_id,
                    "validation_result",
                    "tester",
                    "info" if passed else "error",
                    f"exit={code}",
                    {"stdout": stdout[:2000], "stderr": stderr[:2000]},
                )
            except Exception as exc:
                all_passed = False
                self._record_event(db, run_id, "validation_rejected", "tester", "error", str(exc))

        if not all_passed:
            run = db.get(RunModel, run_id)
            run.status = RunStatus.BLOCKED.value
            run.error_message = "Validation failed"
            db.commit()
            self._emit(run_id, "run_blocked", "tester", "Validation failed")
            return False
        return True


def claim_run(db: Session, run_id: str) -> bool:
    updated = (
        db.query(RunModel)
        .filter(RunModel.id == run_id, RunModel.status == RunStatus.PENDING.value)
        .update({"status": RunStatus.RUNNING.value})
    )
    db.commit()
    return updated == 1


def create_task_and_run(db: Session, data: dict):
    svc = ProjectService(db)
    project = svc.get(data["project_id"])
    profile = data.get("validation_profile") or project.validation_profile
    task = TaskModel(
        project_id=project.id,
        description=data["description"],
        validation_profile=profile,
        use_scout=bool(data.get("use_scout", False)),
    )
    db.add(task)
    db.flush()
    run = RunModel(
        project_id=project.id,
        task_id=task.id,
        status=RunStatus.PENDING.value,
        current_stage=PipelineStage.PLANNER.value,
    )
    db.add(run)
    db.commit()
    db.refresh(task)
    db.refresh(run)
    run_engine.enqueue(run.id)
    return task, run


run_engine = orchestration_service = OrchestrationService()
