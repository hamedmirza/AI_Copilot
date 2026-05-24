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
from app.services.change_guard import is_frontend_code_path, reviewer_guard_issues, summarize_structure
from app.services.config_service import ConfigService
from app.services.file_service import FileService
from app.services.learning_service import LearningService, infer_task_kind
from app.services.project_service import ProjectService
from app.services.run_engine.event_bus import event_bus
from app.services.workspace_service import clone_for_run
from app.core.exceptions import CommandRejectedError, PatchGuardError
from app.tools.command_runner import run_command, validate_command
from app.tools.lint_runner import canonical_frontend_required_commands, get_profile_commands, scope_profile_commands

logger = logging.getLogger(__name__)

_RESUME_STAGE_PRIORITY = {
    PipelineStage.SUPERVISOR.value: 7,
    PipelineStage.TESTER.value: 6,
    PipelineStage.REVIEWER.value: 5,
    PipelineStage.CODER.value: 4,
    PipelineStage.UI_DESIGNER.value: 3,
    PipelineStage.ARCHITECT.value: 2,
    PipelineStage.PLANNER.value: 1,
}


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
    _CODER_FILE_CONTEXT_LIMIT = 2400

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

    def _log_provider(self, db: Session, run_id: str, stage: str, provider) -> None:
        registry = ProviderRegistry.get()
        provider_name = "Ollama" if registry.active_provider() == "ollama" else "LM Studio"
        resolved_model = str(getattr(provider, "model", "") or "auto")
        message = f"Using {provider_name} · {resolved_model}"
        payload = {"provider": provider_name, "model": resolved_model}
        self._record_event(db, run_id, "provider_resolved", stage, "info", message, payload)
        self._emit(run_id, "provider_resolved", stage, message, payload)
        logger.info(
            "run %s stage=%s provider=%s model=%s",
            run_id,
            stage,
            provider_name,
            resolved_model,
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
            db.rollback()
            self._mark_run_failed(db, run_id, "", str(exc))
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
        event_payload = {
            "run_id": run_id,
            "event_type": event_type,
            "stage": stage,
            "severity": severity,
            "message": message,
            "payload_json": json.dumps(payload or {}),
        }
        try:
            db.add(RunEventModel(**event_payload))
            db.commit()
            return
        except Exception:
            db.rollback()
        isolated = SessionLocal()
        try:
            isolated.add(RunEventModel(**event_payload))
            isolated.commit()
        finally:
            isolated.close()

    def _save_artifact(self, db: Session, run_id: str, artifact_type: str, content: dict) -> None:
        artifact_payload = {
            "run_id": run_id,
            "artifact_type": artifact_type,
            "content_json": json.dumps(content),
        }
        try:
            db.add(ArtifactModel(**artifact_payload))
            db.commit()
            return
        except Exception:
            db.rollback()
        isolated = SessionLocal()
        try:
            isolated.add(ArtifactModel(**artifact_payload))
            isolated.commit()
        finally:
            isolated.close()

    def _mark_run_failed(self, db: Session, run_id: str, stage: str, message: str) -> None:
        try:
            run = db.get(RunModel, run_id)
            if run:
                run.status = RunStatus.FAILED.value
                run.error_message = message
                db.commit()
        except Exception:
            db.rollback()
            isolated = SessionLocal()
            try:
                run = isolated.get(RunModel, run_id)
                if run:
                    run.status = RunStatus.FAILED.value
                    run.error_message = message
                    isolated.commit()
            finally:
                isolated.close()
        self._record_event(db, run_id, "run_failed", stage, "error", message)

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
        learner = LearningService(db)
        learner.ensure_run_task_kind(run)
        context_base = self._build_context_base(run, task.description)
        fs = FileService(workspace, project.protected_files)

        ConfigService(db).reload_registry()

        stages: list[tuple[PipelineStage, callable]] = [
            (PipelineStage.PLANNER, lambda ctx: self._stage_planner(db, run_id, ctx)),
            (PipelineStage.ARCHITECT, lambda ctx: self._stage_architect(db, run_id, ctx)),
            (PipelineStage.UI_DESIGNER, lambda ctx: self._stage_ui(db, run_id, ctx)),
            (PipelineStage.CODER, lambda ctx: self._stage_coder(db, run_id, ctx, fs)),
            (PipelineStage.REVIEWER, lambda ctx: self._stage_reviewer_loop(db, run_id, ctx, fs, workspace, source)),
            (PipelineStage.TESTER, lambda ctx: self._stage_tester(db, run_id, ctx, workspace)),
        ]

        start_index = 0
        if run.status == RunStatus.RUNNING.value and run.current_stage:
            for index, (stage, _) in enumerate(stages):
                if stage.value == run.current_stage:
                    start_index = index
                    break

        for stage, fn in stages[start_index:]:
            run = db.get(RunModel, run_id)
            run.current_stage = stage.value
            db.commit()
            self._record_event(db, run_id, f"{stage.value}_started", stage.value, "info", f"{stage.value} started")
            self._emit(run_id, f"{stage.value}_started", stage.value, f"{stage.value} started")
            try:
                stage_context = self._stage_context(db, run, stage.value, context_base)
                result = fn(stage_context)
                if result is False:
                    self._finalize_terminal_state(db, run_id)
                    return
            except Exception as exc:
                db.rollback()
                self._mark_run_failed(db, run_id, stage.value, str(exc))
                self._record_event(db, run_id, f"{stage.value}_failed", stage.value, "error", str(exc))
                self._emit(run_id, f"{stage.value}_failed", stage.value, str(exc))
                if ConfigService(db).get_all().get("stop_on_first_failure", True):
                    self._finalize_terminal_state(db, run_id)
                    return
                continue
            self._record_event(db, run_id, f"{stage.value}_complete", stage.value, "info", f"{stage.value} complete")
            self._emit(run_id, f"{stage.value}_complete", stage.value, f"{stage.value} complete")

        run = db.get(RunModel, run_id)
        if run.status == RunStatus.RUNNING.value:
            run.status = RunStatus.AWAITING_APPROVAL.value
            run.operator_feedback = None
            db.commit()
            self._record_event(
                db,
                run_id,
                "awaiting_approval",
                run.current_stage or "",
                "info",
                "Run awaiting approval",
            )
            self._emit(run_id, "awaiting_approval", "", "Run awaiting approval")
            self._finalize_terminal_state(db, run_id)

    def _build_context_base(self, run: RunModel, task_description: str) -> str:
        task_kind = run.task_kind or infer_task_kind(task_description)
        guidance = [f"Task mode: {task_kind}."]
        if task_kind == "analysis":
            guidance.append(
                "Prefer grounded analysis and report artifacts over speculative code changes unless the task explicitly asks for implementation."
            )
        context_base = task_description + "\n\nExecution guidance:\n- " + "\n- ".join(guidance)
        if run.operator_feedback:
            context_base += "\n\nOperator feedback:\n" + run.operator_feedback
        elif run.error_message and run.status == RunStatus.CHANGES_REQUESTED.value:
            context_base += "\n\nOperator feedback:\n" + run.error_message
        return context_base

    def _stage_context(self, db: Session, run: RunModel, stage: str, context_base: str) -> str:
        learning = LearningService(db).build_learning_context(run, stage, context_base)
        if learning["project_lessons"] or learning["global_skills"]:
            payload = {
                "project_lessons": learning["project_lessons"],
                "global_skills": learning["global_skills"],
                "stage": stage,
                "task_kind": run.task_kind,
            }
            self._record_event(
                db,
                run.id,
                "lessons_applied",
                stage,
                "info",
                f"Applied {len(learning['project_lessons'])} project lesson(s) and {len(learning['global_skills'])} global skill(s)",
                payload,
            )
            self._emit(run.id, "lessons_applied", stage, "Lessons applied", payload)
        return str(learning["context"])

    def _finalize_terminal_state(self, db: Session, run_id: str) -> None:
        run = db.get(RunModel, run_id)
        if not run:
            return
        if run.status in {
            RunStatus.FAILED.value,
            RunStatus.BLOCKED.value,
            RunStatus.CHANGES_REQUESTED.value,
            RunStatus.COMPLETED.value,
            RunStatus.AWAITING_APPROVAL.value,
        }:
            LearningService(db).finalize_terminal_run(run_id)

    def _stage_planner(self, db: Session, run_id: str, context: str):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.PLANNER)
        self._log_provider(db, run_id, "planner", provider)
        agent = PlannerAgent(provider)
        output = agent.plan(context)
        self._save_artifact(db, run_id, "plan", output.model_dump())
        return True

    def _stage_architect(self, db: Session, run_id: str, context: str):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.ARCHITECT)
        self._log_provider(db, run_id, "architect", provider)
        agent = ArchitectAgent(provider)
        output = agent.design(context)
        self._save_artifact(db, run_id, "architect", output.model_dump())
        return True

    def _stage_ui(self, db: Session, run_id: str, context: str):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.UI_DESIGNER)
        self._log_provider(db, run_id, "ui_designer", provider)
        agent = UIDesignerAgent(provider)
        output = agent.design(context)
        if output is None:
            self._record_event(db, run_id, "ui_designer_skipped", "ui_designer", "info", "UI stage skipped")
            return True
        self._save_artifact(db, run_id, "ui_design", output.model_dump())
        return True

    def _stage_coder(self, db: Session, run_id: str, context: str, fs: FileService):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.CODER)
        self._log_provider(db, run_id, "coder", provider)
        agent = CoderAgent(provider)
        run = db.get(RunModel, run_id)
        project = ProjectService(db).get(run.project_id) if run else None
        source_root = Path(project.source_repo_spec) if project else fs.workspace
        attempt_context = self._build_coder_context(db, run_id, context, fs, source_root)
        max_attempts = 2
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            output = agent.code(attempt_context)
            changes = [
                fc if isinstance(fc, dict) else fc.model_dump() for fc in output.file_changes
            ]
            try:
                applied = fs.apply_coder_changes(changes)
                self._run_frontend_patch_check(fs.workspace, applied)
            except PatchGuardError as exc:
                last_exc = exc
                self._record_event(
                    db,
                    run_id,
                    "coder_guard_rejected",
                    "coder",
                    "warning",
                    str(exc),
                    {"attempt": attempt},
                )
                self._emit(run_id, "coder_guard_rejected", "coder", str(exc), {"attempt": attempt})
                if attempt >= max_attempts:
                    raise
                attempt_context = "\n".join(
                    [
                        context,
                        "",
                        "Deterministic patch guard rejected the previous attempt:",
                        str(exc),
                        "",
                        "Revise the patch using line_changes only for existing source files. Preserve all unrelated imports, exports, props, interfaces, and helper functions.",
                        "Place imports only in the import block at the top of the file. Place JSX only inside the existing render tree.",
                        "",
                        self._build_coder_context(db, run_id, "", fs, source_root),
                    ]
                )
                continue
            payload = output.model_dump()
            payload["applied_changes"] = applied
            payload["coder_attempt"] = attempt
            self._save_artifact(db, run_id, "coder", payload)
            self._record_event(db, run_id, "code_patch_applied", "coder", "info", "Patch applied")
            self._emit(run_id, "code_patch_applied", "coder", "Patch applied")
            return True
        if last_exc:
            raise last_exc
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

    def _latest_changed_files(self, db: Session, run_id: str) -> list[str]:
        coder = self._latest_artifact(db, run_id, "coder") or {}
        changed_files: list[str] = []
        for raw_file_change in coder.get("file_changes") or []:
            if not isinstance(raw_file_change, dict):
                continue
            rel_path = str(raw_file_change.get("path") or "").strip()
            if rel_path:
                changed_files.append(rel_path)
        return changed_files

    def _profile_commands_for_changed_files(self, profile: str, commands: list[str], changed_files: list[str]) -> list[str]:
        if not commands or not changed_files:
            return commands
        suffixes = {
            "python": (".py", ".pyi"),
            "react": (".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".html"),
            "fullstack": (".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".html"),
            "node": (".js", ".jsx", ".ts", ".tsx", ".json", ".mjs", ".cjs"),
        }.get(profile)
        if not suffixes:
            return commands
        if any(path.endswith(suffixes) for path in changed_files):
            return commands
        return []

    def _truncate(self, value: object, limit: int) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return f"{text[:limit]}...[truncated]"

    def _with_line_numbers(self, content: str, max_lines: int = 160) -> str:
        lines = content.splitlines()
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines.append("...[truncated]")
        return "\n".join(f"{idx + 1:>4}: {line}" for idx, line in enumerate(lines))

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

    def _build_coder_context(
        self,
        db: Session,
        run_id: str,
        context: str,
        fs: FileService,
        source_root: Path,
    ) -> str:
        architect = self._latest_artifact(db, run_id, "architect") or {}
        sections = [context]
        file_sections: list[str] = []
        for raw_change in (architect.get("file_changes") or [])[: self._REVIEW_FILE_LIMIT]:
            if not isinstance(raw_change, dict):
                continue
            rel_path = str(raw_change.get("path") or "").strip()
            if not rel_path:
                continue
            source_path = source_root / rel_path
            try:
                current_content = fs.read_file(rel_path)["content"]
            except Exception:
                current_content = source_path.read_text(encoding="utf-8") if source_path.is_file() else ""
            file_sections.append(
                "\n".join(
                    [
                        f"TARGET FILE: {rel_path}",
                        f"Rationale: {raw_change.get('rationale') or ''}",
                        "Current file with line numbers:",
                        self._truncate(self._with_line_numbers(current_content), self._CODER_FILE_CONTEXT_LIMIT),
                    ]
                )
            )
        if file_sections:
            sections.extend(
                [
                    "",
                    "Exact edit rules:",
                    "- Use line_changes for existing files.",
                    "- Keep imports only in the import block at the top of the file.",
                    "- Insert JSX only inside the existing returned tree, never after the file end.",
                    "- Preserve unrelated imports, exports, props, interfaces, and helper functions.",
                    "",
                    "\n\n".join(file_sections),
                ]
            )
        return "\n".join(sections)

    def _run_frontend_patch_check(self, workspace: Path, changed_files: list[dict]) -> None:
        if not any(is_frontend_code_path(str(change.get("path") or "")) for change in changed_files):
            return
        frontend_dir = workspace / "frontend"
        node_modules = frontend_dir / "node_modules"
        if not node_modules.exists():
            raise PatchGuardError("frontend/node_modules", "frontend toolchain missing in run workspace")
        code, stdout, stderr = run_command("npm --prefix frontend exec tsc --noEmit --pretty false", workspace)
        if code != 0:
            message = (stderr or stdout or "frontend typecheck failed").strip()
            raise PatchGuardError("frontend", f"frontend patch validation failed: {message}")

    def _build_reviewer_context(
        self,
        db: Session,
        run_id: str,
        context: str,
        fs: FileService,
        source_root: Path,
    ) -> tuple[str, list[str], list[dict]]:
        plan = self._latest_artifact(db, run_id, "plan") or {}
        architect = self._latest_artifact(db, run_id, "architect") or {}
        coder = self._latest_artifact(db, run_id, "coder") or {}

        changed_files: list[str] = []
        file_sections: list[str] = []
        structural_summaries: list[dict] = []
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
            before_path = source_root / rel_path
            before_snapshot = before_path.read_text(encoding="utf-8") if before_path.is_file() else ""
            structural_summary = summarize_structure(
                rel_path,
                before_snapshot,
                file_snapshot if isinstance(file_snapshot, str) else "",
                before_path.exists(),
                bool(raw_file_change.get("full_content") is not None),
            )
            structural_summaries.append(structural_summary)
            file_sections.append(
                "\n".join(
                    [
                        f"FILE: {rel_path}",
                        "Declared coder change:",
                        change_summary,
                        "Original file snapshot:",
                        self._truncate(before_snapshot, self._REVIEW_FILE_CONTENT_LIMIT),
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
        return "\n".join(sections), changed_files, structural_summaries

    def _deterministic_review_issues(self, summaries: list[dict]) -> list[dict]:
        issues: list[dict] = []
        for summary in summaries:
            for message in reviewer_guard_issues(summary):
                issues.append(
                    {
                        "severity": "high",
                        "file_path": summary["path"],
                        "message": message,
                    }
                )
        return issues

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

    def _stage_reviewer_loop(
        self,
        db: Session,
        run_id: str,
        context: str,
        fs: FileService,
        workspace: Path,
        source_root: Path,
    ):
        max_retries = int(ConfigService(db).get_all().get("max_review_retries", 3))
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.REVIEWER)
        self._log_provider(db, run_id, "reviewer", provider)
        agent = ReviewerAgent(provider)
        for attempt in range(1, max_retries + 1):
            run = db.get(RunModel, run_id)
            run.review_attempts = attempt
            db.commit()
            review_context, changed_files, structural_summaries = self._build_reviewer_context(
                db,
                run_id,
                context,
                fs,
                source_root,
            )
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
            deterministic_issues = self._deterministic_review_issues(structural_summaries)
            if deterministic_issues:
                summary = "Deterministic reviewer guard rejected structural regression."
                review_payload = {
                    "approved": False,
                    "summary": summary,
                    "issues": deterministic_issues,
                    "suggestions": [
                        "Preserve the existing file structure and exports.",
                        "Use surgical line_changes for existing source files instead of replacing the whole file.",
                    ],
                }
                self._save_artifact(db, run_id, f"review_{attempt}", review_payload)
                self._record_event(
                    db,
                    run_id,
                    "reviewer_requested_changes",
                    "reviewer",
                    "warning",
                    summary,
                    {"attempt": attempt, "issues": deterministic_issues, "source": "deterministic_guard"},
                )
                self._emit(
                    run_id,
                    "reviewer_requested_changes",
                    "reviewer",
                    summary,
                    {"attempt": attempt, "issues": deterministic_issues, "source": "deterministic_guard"},
                )
                if attempt < max_retries:
                    retry_context = self._build_coder_retry_context(context, review_payload)
                    self._record_event(
                        db,
                        run_id,
                        "reviewer_retrying_coder",
                        "reviewer",
                        "info",
                        f"Retrying coder after reviewer attempt {attempt}",
                        {"attempt": attempt, "summary": summary},
                    )
                    self._emit(
                        run_id,
                        "reviewer_retrying_coder",
                        "reviewer",
                        f"Retrying coder after reviewer attempt {attempt}",
                        {"attempt": attempt, "summary": summary},
                    )
                    self._stage_coder(db, run_id, retry_context, fs)
                    continue
                self._mark_changes_requested(
                    db,
                    run_id,
                    summary,
                    "reviewer_exhausted_retries",
                    {"attempt": attempt, "issues": deterministic_issues, "source": "deterministic_guard"},
                )
                return False
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
        run = db.get(RunModel, run_id)
        task_kind = run.task_kind if run else None
        profiles_json = str(ConfigService(db).get_all().get("validation_profiles_json", "{}"))
        profile = run.task.validation_profile if run and run.task else "python"
        changed_files = self._latest_changed_files(db, run_id)
        profile_commands = scope_profile_commands(
            self._profile_commands_for_changed_files(
                profile,
                get_profile_commands(profiles_json, profile),
                changed_files,
            ),
            changed_files,
        )
        if changed_files and not profile_commands:
            self._record_event(
                db,
                run_id,
                "validation_skipped",
                "tester",
                "info",
                "Validation profile skipped because it does not match the changed file types.",
                {"profile": profile, "changed_files": changed_files},
            )
        llm_commands: list[str] = []

        if task_kind == "validation":
            self._record_event(
                db,
                run_id,
                "tester_llm_skipped",
                "tester",
                "info",
                "Validation task detected; skipping tester LLM planning.",
            )
            self._save_artifact(
                db,
                run_id,
                "test_plan",
                {
                    "passed": True,
                    "summary": "Validation task detected; using deterministic validation commands only.",
                    "commands": [{"command": command, "description": "Validation profile command"} for command in profile_commands],
                    "notes": ["Tester LLM planning skipped for validation-only task."],
                },
            )
        else:
            provider = ProviderRegistry.get().resolve_stage(PipelineStage.TESTER)
            self._log_provider(db, run_id, "tester", provider)
            agent = TesterAgent(provider)
            output = agent.test_plan(context)
            self._save_artifact(db, run_id, "test_plan", output.model_dump())
            llm_commands = [cmd.command for cmd in output.commands]

        required_commands: list[str] = []
        optional_commands: list[str] = []
        seen_required: set[str] = set()
        seen_optional: set[str] = set()
        frontend_build_required = any(is_frontend_code_path(path) for path in changed_files)
        if frontend_build_required:
            profile_commands = canonical_frontend_required_commands(profile_commands, changed_files)
        for command in profile_commands:
            if command not in seen_required:
                seen_required.add(command)
                required_commands.append(command)
        for command in llm_commands:
            if command in seen_required or command in seen_optional:
                continue
            seen_optional.add(command)
            optional_commands.append(command)

        commands: list[tuple[str, bool]] = [(cmd, True) for cmd in required_commands] + [(cmd, False) for cmd in optional_commands]
        required_passed = True
        required_executed = 0
        for command, is_required in commands:
            from_profile = is_required
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
                    {"required": is_required, "from_profile": from_profile},
                )
                self._emit(run_id, "validation_rejected", "tester", str(exc))
                if is_required:
                    required_passed = False
                continue

            self._record_event(db, run_id, "validation_started", "tester", "info", command, {"required": is_required})
            self._emit(run_id, "validation_started", "tester", command, {"required": is_required})
            try:
                code, stdout, stderr = run_command(command, workspace)
                passed = code == 0
                if is_required:
                    required_executed += 1
                    required_passed = required_passed and passed
                self._record_event(
                    db,
                    run_id,
                    "validation_result",
                    "tester",
                    "info" if passed else "error",
                    f"exit={code}",
                    {"stdout": stdout[:2000], "stderr": stderr[:2000], "required": is_required, "from_profile": from_profile},
                )
            except Exception as exc:
                if is_required:
                    required_passed = False
                self._record_event(
                    db,
                    run_id,
                    "validation_rejected",
                    "tester",
                    "error",
                    str(exc),
                    {"required": is_required, "from_profile": from_profile},
                )

        if required_commands and required_executed == 0:
            required_passed = False
            self._record_event(
                db,
                run_id,
                "validation_rejected",
                "tester",
                "error",
                "No required validation commands could be executed",
            )

        if not required_passed:
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


def resume_inflight_runs(db: Session, limit: int | None = None) -> list[str]:
    runs = list(
        db.query(RunModel)
        .filter(RunModel.status.in_([RunStatus.RUNNING.value, RunStatus.PENDING.value]))
        .all()
    )
    runs.sort(
        key=lambda run: (
            _RESUME_STAGE_PRIORITY.get(str(run.current_stage or ""), 0),
            run.updated_at,
            run.created_at,
        ),
        reverse=True,
    )
    resumed_ids: list[str] = []
    selected = runs if limit is None else runs[: max(0, int(limit))]
    for run in selected:
        run_engine.enqueue(run.id)
        resumed_ids.append(run.id)
    return resumed_ids


def create_task_and_run(db: Session, data: dict):
    svc = ProjectService(db)
    project = svc.get(data["project_id"])
    profile = data.get("validation_profile") or project.validation_profile
    task_kind = infer_task_kind(data["description"])
    task = TaskModel(
        project_id=project.id,
        description=data["description"],
        validation_profile=profile,
        task_kind=task_kind,
        use_scout=bool(data.get("use_scout", False)),
    )
    db.add(task)
    db.flush()
    run = RunModel(
        project_id=project.id,
        task_id=task.id,
        status=RunStatus.PENDING.value,
        current_stage=PipelineStage.PLANNER.value,
        task_kind=task_kind,
        recovery_status="none",
    )
    db.add(run)
    db.commit()
    db.refresh(task)
    db.refresh(run)
    run_engine.enqueue(run.id)
    return task, run


run_engine = orchestration_service = OrchestrationService()
