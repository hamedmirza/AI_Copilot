import json
import logging
import subprocess
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

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
from app.services.workspace_service import clone_for_run
from app.core.exceptions import CommandRejectedError
from app.tools.command_runner import run_command, validate_command
from app.tools.lint_runner import get_profile_commands

logger = logging.getLogger(__name__)


class OrchestrationService:
    TERMINAL = {
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
        RunStatus.AWAITING_APPROVAL.value,
        RunStatus.BLOCKED.value,
        RunStatus.CHANGES_REQUESTED.value,
    }
    _REVIEW_FILE_LIMIT = 6
    _REVIEW_FILE_CONTENT_LIMIT = 3000
    _REVIEW_ARTIFACT_LIMIT = 4000
    _REVIEW_DIFF_LIMIT = 10000

    def __init__(self) -> None:
        self._loop = None
        self._max_workers = 1
        self._executor = ThreadPoolExecutor(max_workers=self._max_workers)
        self._futures: set[Future[None]] = set()
        self._lock = Lock()

    def set_loop(self, loop) -> None:
        self._loop = loop

    def enqueue_run(self, run_id: str) -> None:
        future = self._executor.submit(self._execute_run, run_id)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._discard_future)

    def enqueue(self, run_id: str) -> None:
        self.enqueue_run(run_id)

    def configure_workers(self, count: int) -> None:
        next_count = max(1, int(count))
        if next_count == self._max_workers:
            return
        previous_executor = self._executor
        self._executor = ThreadPoolExecutor(max_workers=next_count)
        self._max_workers = next_count
        previous_executor.shutdown(wait=False, cancel_futures=False)

    def _discard_future(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)

    def wait_for_idle(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                pending = list(self._futures)
            if not pending:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            wait(pending, timeout=remaining)

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
        source = Path(project.source_repo_spec)
        if run.workspace_path and Path(run.workspace_path).is_dir():
            workspace = Path(run.workspace_path)
        else:
            workspace = clone_for_run(source, run_id)
            run.workspace_path = str(workspace)
            db.commit()

        task = run.task
        context_base = self._build_context_base(run, task.description)
        fs = FileService(workspace, project.protected_files)

        ConfigService(db).reload_registry()

        stages: list[tuple[PipelineStage, callable]] = [
            (PipelineStage.PLANNER, lambda: self._stage_planner(db, run_id, context_base)),
            (PipelineStage.ARCHITECT, lambda: self._stage_architect(db, run_id, context_base)),
            (PipelineStage.UI_DESIGNER, lambda: self._stage_ui(db, run_id, context_base)),
            (PipelineStage.CODER, lambda: self._stage_coder(db, run_id, context_base, fs)),
            (PipelineStage.REVIEWER, lambda: self._stage_reviewer_loop(db, run_id, context_base, fs, workspace)),
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
            run.operator_feedback = None
            db.commit()
            self._emit(run_id, "awaiting_approval", "", "Run awaiting approval")

    def _build_context_base(self, run: RunModel, task_description: str) -> str:
        context_base = task_description
        if run.operator_feedback:
            context_base += "\n\nOperator feedback:\n" + run.operator_feedback
        elif run.error_message and run.status == RunStatus.CHANGES_REQUESTED.value:
            context_base += "\n\nOperator feedback:\n" + run.error_message
        return context_base

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

    def _latest_artifact(self, db: Session, run_id: str, artifact_type: str) -> dict | None:
        artifact = (
            db.query(ArtifactModel)
            .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == artifact_type)
            .order_by(ArtifactModel.id.desc())
            .first()
        )
        if not artifact:
            return None
        try:
            parsed = json.loads(artifact.content_json)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _truncate(self, value: object, limit: int) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return f"{text[:limit]}...[truncated]"

    def _workspace_diff(self, workspace: Path) -> str:
        git_dir = workspace / ".git"
        if not git_dir.exists():
            return ""
        try:
            result = subprocess.run(
                ["git", "-C", str(workspace), "diff", "--no-ext-diff", "--unified=3"],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode not in (0, 1):
            return ""
        return self._truncate(result.stdout.strip(), self._REVIEW_DIFF_LIMIT)

    def _build_reviewer_context(self, db: Session, run_id: str, context: str, fs: FileService) -> tuple[str, list[str]]:
        plan = self._latest_artifact(db, run_id, "plan") or {}
        architect = self._latest_artifact(db, run_id, "architect") or {}
        coder = self._latest_artifact(db, run_id, "coder") or {}

        changed_files: list[str] = []
        file_sections: list[str] = []
        for raw_file_change in (coder.get("file_changes") or [])[: self._REVIEW_FILE_LIMIT]:
            if not isinstance(raw_file_change, dict):
                continue
            rel_path = str(raw_file_change.get("path") or "").strip()
            if not rel_path:
                continue
            changed_files.append(rel_path)
            change_summary = self._truncate(
                json.dumps(raw_file_change, indent=2, ensure_ascii=True),
                self._REVIEW_ARTIFACT_LIMIT,
            )
            try:
                file_snapshot = fs.read_file(rel_path)["content"]
            except Exception as exc:
                file_snapshot = f"[unavailable: {exc}]"
            file_sections.append(
                "\n".join(
                    [
                        f"FILE: {rel_path}",
                        "Declared coder change:",
                        change_summary,
                        "Current file snapshot:",
                        self._truncate(file_snapshot, self._REVIEW_FILE_CONTENT_LIMIT),
                    ]
                )
            )

        sections = [
            "Task acceptance context:",
            context,
            "",
            "Planner summary:",
            self._truncate(plan.get("summary") or "", self._REVIEW_ARTIFACT_LIMIT),
            "",
            "Architect overview:",
            self._truncate(architect.get("overview") or "", self._REVIEW_ARTIFACT_LIMIT),
            "",
            "Coder summary:",
            self._truncate(coder.get("summary") or "", self._REVIEW_ARTIFACT_LIMIT),
            "",
            "Changed files:",
            "\n".join(changed_files) if changed_files else "[none recorded]",
        ]
        if file_sections:
            sections.extend(["", "Changed file details:", "\n\n".join(file_sections)])
        return "\n".join(sections), changed_files

    def _review_failed_for_missing_context(self, summary: str, issues: list[dict], changed_files: list[str]) -> bool:
        lower_summary = summary.lower()
        missing_context_markers = (
            "diff not provided",
            "code diff not provided",
            "missing diff",
            "missing code",
            "unable to review",
            "not enough context",
            "no code provided",
        )
        if any(marker in lower_summary for marker in missing_context_markers):
            return True
        issue_paths = {
            str(issue.get("file_path") or "").strip()
            for issue in issues
            if isinstance(issue, dict) and str(issue.get("file_path") or "").strip()
        }
        if not changed_files:
            return True
        return bool(issue_paths) and not any(path in changed_files for path in issue_paths)

    def _build_coder_retry_context(self, context: str, review: dict) -> str:
        feedback_lines = [
            context,
            "",
            "Reviewer feedback to address before the next patch:",
            f"Summary: {review.get('summary') or ''}",
        ]
        for issue in review.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            feedback_lines.append(
                f"- [{issue.get('severity') or 'unknown'}] {issue.get('file_path') or 'unknown file'}: {issue.get('message') or ''}"
            )
        for suggestion in review.get("suggestions") or []:
            feedback_lines.append(f"- Suggestion: {suggestion}")
        return "\n".join(feedback_lines)

    def _mark_changes_requested(
        self,
        db: Session,
        run_id: str,
        summary: str,
        event_type: str,
        payload: dict | None = None,
    ) -> None:
        run = db.get(RunModel, run_id)
        if not run:
            return
        run.status = RunStatus.CHANGES_REQUESTED.value
        run.error_message = summary
        db.commit()
        self._record_event(db, run_id, event_type, "reviewer", "warning", summary, payload)
        self._emit(run_id, event_type, "reviewer", summary, payload)
        self._record_event(db, run_id, "run_changes_requested", "reviewer", "warning", summary, payload)
        self._emit(run_id, "run_changes_requested", "reviewer", summary, payload)

    def _stage_reviewer_loop(self, db: Session, run_id: str, context: str, fs: FileService, workspace: Path):
        max_retries = int(ConfigService(db).get_all().get("max_review_retries", 3))
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.REVIEWER)
        agent = ReviewerAgent(provider)
        for attempt in range(1, max_retries + 1):
            run = db.get(RunModel, run_id)
            run.review_attempts = attempt
            db.commit()
            review_context, changed_files = self._build_reviewer_context(db, run_id, context, fs)
            diff_text = self._workspace_diff(workspace)
            if diff_text:
                review_context = f"{review_context}\n\nGit diff (if available):\n{diff_text}"
            self._record_event(
                db,
                run_id,
                "reviewer_attempt_started",
                "reviewer",
                "info",
                f"Reviewer attempt {attempt}/{max_retries}",
                {"attempt": attempt, "max_retries": max_retries, "changed_files": changed_files},
            )
            self._emit(
                run_id,
                "reviewer_attempt_started",
                "reviewer",
                f"Reviewer attempt {attempt}/{max_retries}",
                {"attempt": attempt, "max_retries": max_retries, "changed_files": changed_files},
            )
            output = agent.review(review_context)
            review_payload = output.model_dump()
            self._save_artifact(db, run_id, f"review_{attempt}", review_payload)
            if output.approved:
                self._record_event(
                    db,
                    run_id,
                    "reviewer_approved",
                    "reviewer",
                    "info",
                    output.summary,
                    {"attempt": attempt, "issues": review_payload.get("issues", [])},
                )
                self._emit(
                    run_id,
                    "reviewer_approved",
                    "reviewer",
                    output.summary,
                    {"attempt": attempt, "issues": review_payload.get("issues", [])},
                )
                return True
            self._record_event(
                db,
                run_id,
                "reviewer_requested_changes",
                "reviewer",
                "warning",
                output.summary,
                {"attempt": attempt, "issues": review_payload.get("issues", [])},
            )
            self._emit(
                run_id,
                "reviewer_requested_changes",
                "reviewer",
                output.summary,
                {"attempt": attempt, "issues": review_payload.get("issues", [])},
            )
            if self._review_failed_for_missing_context(output.summary, review_payload.get("issues", []), changed_files):
                self._mark_changes_requested(
                    db,
                    run_id,
                    f"Reviewer could not validate the patch with the available context: {output.summary}",
                    "reviewer_failed_fast",
                    {"attempt": attempt, "issues": review_payload.get("issues", []), "changed_files": changed_files},
                )
                return False
            if attempt < max_retries:
                retry_context = self._build_coder_retry_context(context, review_payload)
                self._record_event(
                    db,
                    run_id,
                    "reviewer_retrying_coder",
                    "reviewer",
                    "info",
                    f"Retrying coder after reviewer attempt {attempt}",
                    {"attempt": attempt, "summary": output.summary},
                )
                self._emit(
                    run_id,
                    "reviewer_retrying_coder",
                    "reviewer",
                    f"Retrying coder after reviewer attempt {attempt}",
                    {"attempt": attempt, "summary": output.summary},
                )
                self._stage_coder(db, run_id, retry_context, fs)
            else:
                self._mark_changes_requested(
                    db,
                    run_id,
                    output.summary,
                    "reviewer_exhausted_retries",
                    {"attempt": attempt, "issues": review_payload.get("issues", [])},
                )
                return False
        return True

    def _stage_tester(self, db: Session, run_id: str, context: str, workspace):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.TESTER)
        agent = TesterAgent(provider)
        output = agent.test_plan(context)
        self._save_artifact(db, run_id, "test_plan", output.model_dump())

        run = db.get(RunModel, run_id)
        profiles_json = str(ConfigService(db).get_all().get("validation_profiles_json", "{}"))
        profile = run.task.validation_profile if run and run.task else "python"
        profile_commands = get_profile_commands(profiles_json, profile)
        llm_commands = [cmd.command for cmd in output.commands]
        commands: list[str] = []
        seen: set[str] = set()
        for command in [*profile_commands, *llm_commands]:
            if command in seen:
                continue
            seen.add(command)
            commands.append(command)

        all_passed = True
        executed = 0
        for command in commands:
            from_profile = command in profile_commands
            try:
                validate_command(command)
            except CommandRejectedError as exc:
                self._record_event(
                    db,
                    run_id,
                    "validation_rejected",
                    "tester",
                    "warning",
                    str(exc),
                    {"from_profile": from_profile},
                )
                self._emit(run_id, "validation_rejected", "tester", str(exc))
                if from_profile:
                    all_passed = False
                continue

            self._record_event(db, run_id, "validation_started", "tester", "info", command)
            self._emit(run_id, "validation_started", "tester", command)
            try:
                code, stdout, stderr = run_command(command, workspace)
                executed += 1
                passed = code == 0
                all_passed = all_passed and passed
                self._record_event(
                    db,
                    run_id,
                    "validation_result",
                    "tester",
                    "info" if passed else "error",
                    f"exit={code}",
                    {"stdout": stdout[:2000], "stderr": stderr[:2000], "from_profile": from_profile},
                )
            except Exception as exc:
                all_passed = False
                self._record_event(
                    db,
                    run_id,
                    "validation_rejected",
                    "tester",
                    "error",
                    str(exc),
                    {"from_profile": from_profile},
                )

        if executed == 0 and profile_commands:
            all_passed = False
            self._record_event(
                db,
                run_id,
                "validation_rejected",
                "tester",
                "error",
                "No validation commands could be executed",
            )

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
