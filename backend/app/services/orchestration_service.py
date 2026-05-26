import json
import logging
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path
from threading import Event as ThreadEvent
from threading import Lock, Thread
from typing import Any, Callable, cast

import httpx
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

from app.agents import (
    AppDesignAgent,
    ArchitectAgent,
    CoderAgent,
    DocumentationAgent,
    PlannerAgent,
    PlaybookSupervisorAgent,
    ReviewerAgent,
    TesterAgent,
    UIDesignerAgent,
)
from app.agents.tool_runtime import PipelineToolExecutionContext, PipelineToolRuntime
from app.core.enums import PipelineStage, RepoMode, RunStatus
from app.core.logging import run_id_var, worker_id_var
from app.db.models import ArtifactModel, RunEventModel, RunModel, TaskModel
from app.db.session import SessionLocal
from app.providers.registry import ProviderRegistry
from app.schemas.agent_outputs import CoderOutput
from app.services.change_guard import is_frontend_code_path, reviewer_guard_issues, summarize_structure
from app.services.config_service import ConfigService
from app.services.file_service import FileService
from app.services.learning_service import LearningService, infer_task_kind
from app.services.project_service import ProjectService
from app.services.scope_guard import scope_issues
from app.services.source_validation import frontend_structure_issues
from app.services.run_engine.event_bus import event_bus
from app.services.workspace_service import clone_for_run, validate_run_workspace
from app.core.exceptions import CommandRejectedError, PatchGuardError, ValidationError
from app.tools.command_runner import run_command, validate_command
from app.tools.lint_runner import (
    FRONTEND_SCAFFOLD_MESSAGE,
    canonical_frontend_required_commands,
    get_profile_commands,
    normalize_tester_dry_run_commands,
    partition_frontend_commands,
    scope_profile_commands,
)
from app.services.deployment_gates import effective_changed_files, evaluate_deployment_readiness
from app.services.integration_guard import integration_guard_issues
from app.services.contract_guard import contract_guard_issues
from app.services.integration_guard import integration_requires_visual_evidence
from app.services.visual_evidence_service import execute_visual_checks
from app.services.workspace_dev_url import build_default_visual_checks
from app.services.supervisor_service import run_pre_deploy_supervisor
from app.services.run_truth_service import (
    expected_targets_for_kind,
    expected_validation_family,
    infer_deliverable_kind,
    persist_run_truth,
    should_run_ui_designer,
)
from app.services.run_thread_service import RunThreadService
from app.services.architecture_state_service import ArchitectureStateService
from app.services.baseline_service import BaselineService
from app.services.dependency_verifier_service import DependencyVerifierService
from app.services.reconnaissance_service import ReconnaissanceService, ReconSnapshot
from app.services.repo_health_service import RepoHealthService
from app.services.scaffold_template_service import ScaffoldTemplateService, default_scaffold_variables
from app.services.run_observability_service import (
    RunOutcomeClass,
    enrich_event_payload,
    outcome_class_for_awaiting_approval,
    why_blocked_for_awaiting_satisfied,
)
from app.services.run_outcome_service import (
    RunOutcomeKind,
    blueprint_files_exist,
    blueprint_paths,
    blueprint_test_paths,
    blueprint_tests_pass,
    coder_has_file_changes,
    coder_noop_completed,
    evaluate_blueprint_satisfaction,
)
from app.services.web_search_service import WebSearchError, WebSearchService, infer_allow_web_search
from app.services.task_kind_workflow import (
    RunContext,
    StageSpec,
    WorkflowContext,
    build_pipeline_stages,
    check_stage_gate,
    skips_deployment_gates,
    workflow_stage_specs,
)

logger = logging.getLogger(__name__)

CLARIFICATION_GATE_PLANNER_SURFACE = "planner_surface"
CLARIFICATION_GATE_ARCHITECT_NAVIGATION = "architect_navigation"

_RESUME_STAGE_PRIORITY = {
    PipelineStage.SUPERVISOR.value: 8,
    PipelineStage.DOCUMENTATION.value: 7,
    PipelineStage.TESTER.value: 6,
    PipelineStage.REVIEWER.value: 5,
    PipelineStage.CODER.value: 4,
    PipelineStage.UI_DESIGNER.value: 3,
    PipelineStage.ARCHITECT.value: 2,
    PipelineStage.PLANNER.value: 1,
    PipelineStage.APP_DESIGNER.value: 0,
    PipelineStage.PLAYBOOK_SUPERVISOR.value: 2,
}

_STALE_INFLIGHT_TIMEOUT = timedelta(minutes=3)
_ALLOWED_SETUP_COMPANION_PREFIXES = ("docs/change-requests/",)


class OrchestrationService:
    TERMINAL = {
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
        RunStatus.AWAITING_CLARIFICATION.value,
        RunStatus.AWAITING_DESIGN_REVIEW.value,
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

    def _run_with_stage_heartbeat(self, run_id: str, stage: str, fn: Callable[[], Any]) -> Any:
        stop = ThreadEvent()
        start = time.monotonic()

        def heartbeat() -> None:
            while not stop.wait(20):
                elapsed_s = int(time.monotonic() - start)
                self._emit(
                    run_id,
                    "stage_progress",
                    stage,
                    f"Still working on {stage}… ({elapsed_s}s)",
                    {"elapsed_s": elapsed_s, "stage": stage},
                )

        thread = Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            return fn()
        finally:
            stop.set()
            thread.join(timeout=0.5)

    def _emit(
        self,
        run_id: str,
        event_type: str,
        stage: str,
        message: str,
        payload: dict | None = None,
        *,
        severity: str = "info",
    ) -> None:
        enriched = enrich_event_payload(
            event_type, stage, severity, payload, message=message
        )
        event_bus.emit(
            run_id,
            {
                "type": event_type,
                "event_type": event_type,
                "stage": stage,
                "severity": severity,
                "message": message,
                "payload": enriched,
                "outcome_class": enriched.get("outcome_class"),
                "why_blocked": enriched.get("why_blocked"),
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
            try:
                self._finalize_if_left_running(db, run_id)
            except Exception:
                logger.debug("Failed to finalize inflight run %s", run_id, exc_info=True)
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
        enriched = enrich_event_payload(
            event_type, stage, severity, payload, message=message
        )
        event_payload = {
            "run_id": run_id,
            "event_type": event_type,
            "stage": stage,
            "severity": severity,
            "message": message,
            "payload_json": json.dumps(enriched),
        }
        try:
            db.add(RunEventModel(**event_payload))
            db.commit()
        except Exception:
            transaction = db.get_transaction()
            if transaction is not None and transaction.is_active:
                db.rollback()
            isolated = SessionLocal()
            try:
                isolated.add(RunEventModel(**event_payload))
                isolated.commit()
            finally:
                isolated.close()
        try:
            RunThreadService(db).append_entry(
                run_id,
                entry_type=event_type,
                stage=stage or None,
                severity=severity,
                message=message,
                payload=enriched,
            )
        except Exception:
            logger.debug("Failed to append run thread entry for %s", run_id, exc_info=True)

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
        persist_run_truth(db, run_id)
        self._finalize_terminal_state(db, run_id)

    def _finalize_if_left_running(self, db: Session, run_id: str) -> None:
        run = db.get(RunModel, run_id)
        if not run or run.status != RunStatus.RUNNING.value:
            return
        self._mark_run_failed(
            db,
            run_id,
            run.current_stage or "",
            "Run worker exited before reaching a terminal state",
        )

    def _clarification_probe_text(self, run: RunModel, task_description: str) -> str:
        parts = [task_description or "", run.operator_feedback or ""]
        ctx = run.clarification_context or {}
        answer = str(ctx.get("answer") or "").strip()
        if answer:
            parts.append(answer)
        return "\n".join(part for part in parts if part).lower()

    def _request_clarification(
        self,
        db: Session,
        run_id: str,
        *,
        stage: str,
        question: str,
        recommended_assumption: str,
        gate_id: str,
    ) -> None:
        run = db.get(RunModel, run_id)
        if not run:
            return
        prior = dict(run.clarification_context or {})
        prior.update(
            {
                "question": question,
                "recommended_assumption": recommended_assumption,
                "pending_gate": gate_id,
            }
        )
        prior.pop("answer", None)
        run.status = RunStatus.AWAITING_CLARIFICATION.value
        run.clarification_question = question
        run.clarification_stage = stage
        run.clarification_context_json = json.dumps(prior)
        db.commit()
        self._record_event(
            db,
            run_id,
            "run_clarification_requested",
            stage,
            "warning",
            question,
            {
                "recommended_assumption": recommended_assumption,
                "clarification_pending": True,
            },
        )
        self._emit(
            run_id,
            "run_clarification_requested",
            stage,
            question,
            {
                "recommended_assumption": recommended_assumption,
                "clarification_pending": True,
            },
        )

    def _auto_assume_clarifications_enabled(self, db: Session) -> bool:
        return bool(ConfigService(db).get_all().get("auto_assume_clarifications", False))

    def _apply_clarification_assumption(
        self,
        db: Session,
        run_id: str,
        *,
        gate_id: str,
        assumption: str,
    ) -> bool:
        run = db.get(RunModel, run_id)
        if not run:
            return False
        prior = dict(run.clarification_context or {})
        resolved = list(prior.get("resolved_gates") or [])
        if gate_id not in resolved:
            resolved.append(gate_id)
        prior["resolved_gates"] = resolved
        prior["answer"] = assumption
        prior.pop("pending_gate", None)
        run.clarification_context_json = json.dumps(prior)
        run.status = RunStatus.RUNNING.value
        run.clarification_question = None
        run.clarification_stage = None
        db.commit()
        self._record_event(
            db,
            run_id,
            "clarification_auto_assumed",
            run.current_stage or "",
            "info",
            f"Auto-applied assumption for gate {gate_id}",
            {"gate_id": gate_id, "assumption": assumption},
        )
        self._emit(run_id, "clarification_auto_assumed", run.current_stage or "", assumption, {"gate_id": gate_id})
        return True

    def _needs_clarification(
        self, run: RunModel, task_description: str, stage: str
    ) -> tuple[str, str, str] | None:
        if run.task_kind != "implementation":
            return None
        resolved = set((run.clarification_context or {}).get("resolved_gates") or [])
        text = self._clarification_probe_text(run, task_description)
        ui_cues = ("ui", "page", "screen", "view", "dashboard", "kanban", "workflow", "experience")
        explicit_surface_cues = (
            "frontend",
            "backend",
            "api",
            "service",
            "route",
            "database",
            "report",
            "document",
            "chat",
            "browser",
            "activity bar",
            "workbench",
            "sidebar",
            "settings",
            "navigation",
            "menu",
            "route",
            "tab",
        )
        if (
            stage == PipelineStage.PLANNER.value
            and CLARIFICATION_GATE_PLANNER_SURFACE not in resolved
            and run.deliverable_kind == "mixed"
            and any(token in text for token in ui_cues)
            and not any(token in text for token in explicit_surface_cues)
        ):
            return (
                "This task is not specific enough to determine whether the requested work should target frontend UI, backend logic, or report-only output. Which surface should this run change?",
                "Specify the target product surface before implementation continues.",
                CLARIFICATION_GATE_PLANNER_SURFACE,
            )
        if (
            stage == PipelineStage.ARCHITECT.value
            and CLARIFICATION_GATE_ARCHITECT_NAVIGATION not in resolved
            and run.deliverable_kind == "frontend"
            and any(token in text for token in ("page", "screen", "view", "dashboard", "kanban"))
            and not any(token in text for token in ("chat", "browser", "activity bar", "workbench", "sidebar"))
        ):
            return (
                "This frontend task requests a new page or surface, but it does not clearly state where it should be wired into the product navigation. Should it live in chat, the workbench center view, or another existing surface?",
                "Use an existing primary UI surface unless the operator specifies otherwise.",
                CLARIFICATION_GATE_ARCHITECT_NAVIGATION,
            )
        return None

    def _record_stage_output(self, output: object | None) -> None:
        self._last_stage_output = output

    def _evaluate_agent_clarification_from_output(
        self, stage: str, output: object | None
    ) -> tuple[str, str, str] | None:
        if output is None:
            return None
        needed = bool(getattr(output, "clarification_needed", False))
        question = str(getattr(output, "clarification_question", None) or "").strip()
        if needed and question:
            return (question, "Provide an answer to continue.", f"{stage}_agent_question")
        return None

    def _request_design_review(
        self,
        db: Session,
        run_id: str,
        *,
        stage: str,
        questions: list[str],
    ) -> None:
        run = db.get(RunModel, run_id)
        if not run:
            return
        prior = dict(run.clarification_context or {})
        prior["design_review_questions"] = questions
        prior["pending_gate"] = "design_review"
        run.status = RunStatus.AWAITING_DESIGN_REVIEW.value
        combined = "\n".join(f"- {q}" for q in questions if str(q).strip())
        run.clarification_question = combined or "Design review required"
        run.clarification_stage = stage
        run.clarification_context_json = json.dumps(prior)
        db.commit()
        self._record_event(
            db,
            run_id,
            "run_design_review_requested",
            stage,
            "warning",
            run.clarification_question,
            {"open_questions": questions},
        )
        self._emit(run_id, "run_design_review_requested", stage, run.clarification_question)

    def _slugify(self, text: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
        return slug[:48] or "change"

    def _load_or_build_recon(
        self,
        db: Session,
        run_id: str,
        source: Path,
        task_description: str,
        project,
        *,
        use_scout: bool,
    ) -> dict:
        cached = self._latest_artifact(db, run_id, "recon")
        if cached and cached.get("repo_mode"):
            return cached
        run = db.get(RunModel, run_id)
        if not run:
            return {}
        snapshot = self._prepare_recon(db, run, project, run.task, source)
        return json.loads(ReconnaissanceService().snapshot_to_json(snapshot))

    def _recon_snapshot_from_payload(self, payload: dict, *, use_scout: bool, stage: str) -> str:
        if not payload:
            return ""
        snapshot = ReconSnapshot(
            repo_mode=str(payload.get("repo_mode") or RepoMode.EXISTING.value),
            stack_profile=str(payload.get("stack_profile") or "python"),
            payload={k: v for k, v in payload.items() if k not in {"repo_mode", "stack_profile"}},
        )
        return snapshot.format_for_stage(stage, use_scout=use_scout)

    def _prepare_recon(
        self,
        db: Session,
        run: RunModel,
        project,
        task: TaskModel,
        source: Path,
    ) -> ReconSnapshot:
        cached = self._latest_artifact(db, run.id, "recon")
        if cached and cached.get("repo_mode"):
            return ReconSnapshot(
                repo_mode=str(cached.get("repo_mode")),
                stack_profile=str(cached.get("stack_profile") or project.stack_profile or "python"),
                payload={k: v for k, v in cached.items() if k not in {"repo_mode", "stack_profile"}},
            )
        recon = ReconnaissanceService()
        snapshot = recon.build_snapshot(
            source,
            task_description=task.description,
            validation_profile=project.validation_profile,
            use_scout=bool(task.use_scout),
            stack_profile=project.stack_profile,
        )
        project.repo_mode = snapshot.repo_mode
        project.stack_profile = snapshot.stack_profile
        db.commit()
        self._save_artifact(db, run.id, "recon", json.loads(recon.snapshot_to_json(snapshot)))
        return snapshot

    def _run_preflight(
        self,
        db: Session,
        run_id: str,
        source: Path,
        validation_profile: str,
        *,
        task_kind: str | None,
        repo_mode: str | None,
    ) -> bool:
        if task_kind == "setup" or repo_mode in {RepoMode.GREENFIELD.value, RepoMode.PARTIAL.value, None}:
            return True
        result = RepoHealthService().run_preflight(source, validation_profile)
        if result.ok:
            return True
        message = result.message
        run = db.get(RunModel, run_id)
        if run:
            run.status = RunStatus.BLOCKED.value
            run.error_message = message
            db.commit()
        self._record_event(
            db,
            run_id,
            "repo_preflight_failed",
            "planner",
            "error",
            message,
            {"warnings": getattr(result, "warnings", [])},
        )
        self._emit(run_id, "repo_preflight_failed", "planner", message)
        return False

    def _workflow_context(
        self, db: Session, run_id: str, run: RunModel, snapshot: ReconSnapshot
    ) -> WorkflowContext:
        task = run.task
        description = task.description if task else ""
        return WorkflowContext(
            task_kind=run.task_kind or "implementation",
            repo_mode=snapshot.repo_mode,
            deliverable_kind=run.deliverable_kind,
            description=description,
            has_app_design=bool(self._latest_artifact(db, run_id, "app_design")),
        )

    def _capture_baseline(
        self,
        db: Session,
        run_id: str,
        source: Path,
        *,
        validation_profile: str,
        repo_mode: str | None,
    ) -> None:
        if repo_mode != RepoMode.EXISTING.value:
            return
        baseline = BaselineService().capture(source, validation_profile)
        self._save_artifact(db, run_id, "baseline", baseline)
        self._record_event(
            db,
            run_id,
            "baseline_captured",
            "planner",
            "info" if baseline.get("failed", 0) == 0 else "warning",
            baseline.get("summary") or "Baseline captured",
            baseline,
        )

    def _pipeline_stages(
        self, db: Session, run_id: str, run: RunModel, snapshot: ReconSnapshot, fs: FileService
    ) -> list[tuple[PipelineStage, Callable[[str], object]]]:
        workspace = Path(run.workspace_path or "")
        source = Path(ProjectService(db).get(run.project_id).source_repo_spec)
        wf = self._workflow_context(db, run_id, run, snapshot)
        ctx = RunContext(
            db=db,
            run_id=run_id,
            run=run,
            snapshot=snapshot,
            fs=fs,
            workspace_path=str(workspace),
            source_path=str(source),
        )
        return build_pipeline_stages(self, ctx)

    def _block_stage_gate(
        self,
        db: Session,
        run_id: str,
        *,
        stage: str,
        missing: list[str],
    ) -> None:
        run = db.get(RunModel, run_id)
        if not run:
            return
        message = f"Stage gate failed: missing artifact(s): {', '.join(missing)}"
        run.status = RunStatus.BLOCKED.value
        run.error_message = message
        db.commit()
        payload = {"missing_artifacts": missing, "stage": stage}
        self._record_event(db, run_id, "stage_gate_failed", stage, "error", message, payload)
        self._emit(run_id, "stage_gate_failed", stage, message, payload)
        self._emit(run_id, "run_blocked", stage, message, payload)

    def _validate_debug_planner_output(self, db: Session, run_id: str, stage: str) -> bool:
        plan = self._latest_artifact(db, run_id, "plan") or {}
        hypothesis = str(plan.get("hypothesis") or "").strip()
        raw_repro = plan.get("repro_steps")
        if isinstance(raw_repro, str):
            repro = [raw_repro.strip()] if raw_repro.strip() else []
        else:
            repro = [str(step).strip() for step in (raw_repro or []) if str(step).strip()]
        if hypothesis and repro:
            return True
        missing = []
        if not hypothesis:
            missing.append("hypothesis")
        if not repro:
            missing.append("repro_steps")
        self._block_stage_gate(db, run_id, stage=stage, missing=missing)
        return False

    def _stage_playbook_supervisor(self, db: Session, run_id: str, context: str) -> bool:
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.SUPERVISOR)
        self._log_provider(db, run_id, "playbook_supervisor", provider)
        agent = PlaybookSupervisorAgent(provider)
        output = agent.supervise_playbook(context)
        self._record_stage_output(output)
        payload = output.model_dump()
        self._save_artifact(db, run_id, "playbook_supervisor", payload)
        if output.approved:
            persist_run_truth(db, run_id)
            return True
        run = db.get(RunModel, run_id)
        if not run:
            return False
        summary = output.summary or "Playbook supervisor rejected the procedure"
        run.status = RunStatus.BLOCKED.value
        run.error_message = summary
        db.commit()
        self._record_event(
            db,
            run_id,
            "playbook_supervisor_rejected",
            PipelineStage.PLAYBOOK_SUPERVISOR.value,
            "error",
            summary,
            payload,
        )
        self._emit(run_id, "playbook_supervisor_rejected", PipelineStage.PLAYBOOK_SUPERVISOR.value, summary, payload)
        self._emit(run_id, "run_blocked", PipelineStage.PLAYBOOK_SUPERVISOR.value, summary, payload)
        persist_run_truth(db, run_id)
        return False

    def _verify_dependencies(self, db: Session, run_id: str, workspace: Path, source: Path) -> bool:
        architect = self._latest_artifact(db, run_id, "architect") or {}
        result = DependencyVerifierService(workspace, source).verify(architect)
        self._save_artifact(db, run_id, "dependency_check", result)
        if result.get("ok"):
            return True
        message = str(result.get("message") or "Dependency verification failed")
        run = db.get(RunModel, run_id)
        if run:
            run.status = RunStatus.BLOCKED.value
            run.error_message = message
            db.commit()
        self._record_event(
            db,
            run_id,
            "dependency_verify_failed",
            PipelineStage.ARCHITECT.value,
            "error",
            message,
            {"missing": result.get("missing") or []},
        )
        self._emit(run_id, "dependency_verify_failed", PipelineStage.ARCHITECT.value, message)
        return False

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
        RunThreadService(db).ensure_session(run_id, run.chat_session_id)
        use_scout = bool(getattr(task, "use_scout", False))
        snapshot = self._prepare_recon(db, run, project, task, source)
        try:
            validate_run_workspace(
                workspace,
                source_repo=source,
                repo_mode=snapshot.repo_mode,
                task_kind=run.task_kind,
            )
        except ValidationError as exc:
            self._mark_run_failed(db, run_id, run.current_stage or PipelineStage.PLANNER.value, str(exc))
            self._record_event(
                db,
                run_id,
                f"{run.current_stage or PipelineStage.PLANNER.value}_failed",
                run.current_stage or PipelineStage.PLANNER.value,
                "error",
                str(exc),
            )
            self._emit(run_id, "run_failed", run.current_stage or PipelineStage.PLANNER.value, str(exc))
            self._finalize_terminal_state(db, run_id)
            return
        if not self._run_preflight(
            db,
            run_id,
            source,
            project.validation_profile,
            task_kind=run.task_kind,
            repo_mode=snapshot.repo_mode,
        ):
            self._finalize_terminal_state(db, run_id)
            return
        self._capture_baseline(
            db,
            run_id,
            source,
            validation_profile=project.validation_profile,
            repo_mode=snapshot.repo_mode,
        )
        context_base = self._build_context_base(
            db, run_id, run, task.description, recon_snapshot=snapshot, use_scout=use_scout
        )
        fs = FileService(workspace, project.protected_files)

        ConfigService(db).reload_registry()

        stages = self._pipeline_stages(db, run_id, run, snapshot, fs)
        wf_ctx = self._workflow_context(db, run_id, run, snapshot)
        self._workflow_stage_specs = {spec.stage.value: spec for spec in workflow_stage_specs(wf_ctx)}

        start_index = 0
        if run.status == RunStatus.RUNNING.value and run.current_stage:
            for index, (stage, _) in enumerate(stages):
                if stage.value == run.current_stage:
                    start_index = index
                    break

        self._last_stage_output = None
        for stage, fn in stages[start_index:]:
            run = db.get(RunModel, run_id)
            if not run:
                self._finalize_terminal_state(db, run_id)
                return
            stage_spec = self._workflow_stage_specs.get(stage.value)
            if stage_spec:
                gate_reason = check_stage_gate(
                    db,
                    run_id,
                    run,
                    stage_spec,
                    latest_artifact=self._latest_artifact,
                    workflow_ctx=wf_ctx,
                )
                if gate_reason:
                    run = db.get(RunModel, run_id)
                    if run:
                        run.status = RunStatus.BLOCKED.value
                        run.error_message = gate_reason
                        db.commit()
                    self._record_event(
                        db,
                        run_id,
                        "stage_gate_failed",
                        stage.value,
                        "error",
                        gate_reason,
                        {"why_blocked": gate_reason},
                    )
                    self._emit(run_id, "stage_gate_failed", stage.value, gate_reason, {"why_blocked": gate_reason})
                    self._finalize_terminal_state(db, run_id)
                    return
            proactive = self._needs_clarification(run, task.description, stage.value)
            if proactive:
                question, recommendation, gate_id = proactive
                if self._auto_assume_clarifications_enabled(db):
                    self._apply_clarification_assumption(
                        db, run_id, gate_id=gate_id, assumption=recommendation
                    )
                else:
                    self._request_clarification(
                        db,
                        run_id,
                        stage=stage.value,
                        question=question,
                        recommended_assumption=recommendation,
                        gate_id=gate_id,
                    )
                    return
            run.current_stage = stage.value
            db.commit()
            self._record_event(db, run_id, f"{stage.value}_started", stage.value, "info", f"{stage.value} started")
            self._emit(run_id, f"{stage.value}_started", stage.value, f"{stage.value} started")
            try:
                stage_context = self._stage_context(db, run, stage.value, context_base)
                result = self._run_with_stage_heartbeat(
                    run_id,
                    stage.value,
                    lambda: fn(stage_context),
                )
                if result is False:
                    run = db.get(RunModel, run_id)
                    if run and run.status in {
                        RunStatus.AWAITING_CLARIFICATION.value,
                        RunStatus.AWAITING_DESIGN_REVIEW.value,
                    }:
                        return
                    self._finalize_terminal_state(db, run_id)
                    return
                if stage == PipelineStage.APP_DESIGNER:
                    app_design = self._latest_artifact(db, run_id, "app_design") or {}
                    open_q = [q for q in (app_design.get("open_questions") or []) if str(q).strip()]
                    if open_q:
                        self._request_design_review(db, run_id, stage=stage.value, questions=open_q)
                        return
                agent_clarification = self._evaluate_agent_clarification_from_output(
                    stage.value, getattr(self, "_last_stage_output", None)
                )
                if agent_clarification:
                    question, recommendation, gate_id = agent_clarification
                    if self._auto_assume_clarifications_enabled(db):
                        self._apply_clarification_assumption(
                            db, run_id, gate_id=gate_id, assumption=recommendation
                        )
                    else:
                        self._request_clarification(
                            db,
                            run_id,
                            stage=stage.value,
                            question=question,
                            recommended_assumption=recommendation,
                            gate_id=gate_id,
                        )
                        return
                if stage == PipelineStage.ARCHITECT and not self._verify_dependencies(
                    db, run_id, workspace, source
                ):
                    self._finalize_terminal_state(db, run_id)
                    return
                if stage == PipelineStage.PLANNER and (run.task_kind or "") == "debug":
                    if not self._validate_debug_planner_output(db, run_id, stage.value):
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
            persist_run_truth(db, run_id)

        run = db.get(RunModel, run_id)
        if not run:
            self._finalize_terminal_state(db, run_id)
            return
        if run.status == RunStatus.RUNNING.value:
            if skips_deployment_gates(run.task_kind):
                run.status = RunStatus.AWAITING_APPROVAL.value
                run.operator_feedback = None
                db.commit()
                approval_payload = {
                    "status": RunStatus.AWAITING_APPROVAL.value,
                    "outcome_class": outcome_class_for_awaiting_approval(db, run_id),
                    "playbook_only": True,
                }
                self._record_event(
                    db,
                    run_id,
                    "awaiting_approval",
                    run.current_stage or "",
                    "info",
                    "Playbook run awaiting approval",
                    approval_payload,
                )
                self._emit(
                    run_id,
                    "awaiting_approval",
                    "",
                    "Playbook run awaiting approval",
                    approval_payload,
                )
                persist_run_truth(db, run_id)
                self._finalize_terminal_state(db, run_id)
                return
            if not self._finalize_deployment_gates(db, run_id, workspace, source):
                self._finalize_terminal_state(db, run_id)
                return
            run.status = RunStatus.AWAITING_APPROVAL.value
            run.operator_feedback = None
            db.commit()
            approval_payload: dict = {
                "status": RunStatus.AWAITING_APPROVAL.value,
                "outcome_class": outcome_class_for_awaiting_approval(db, run_id),
            }
            satisfied_reason = why_blocked_for_awaiting_satisfied(db, run_id)
            if satisfied_reason and approval_payload["outcome_class"] == RunOutcomeClass.SATISFIED.value:
                approval_payload["why_satisfied"] = satisfied_reason
            self._record_event(
                db,
                run_id,
                "awaiting_approval",
                run.current_stage or "",
                "info",
                "Run awaiting approval",
                approval_payload,
            )
            self._emit(
                run_id,
                "awaiting_approval",
                "",
                "Run awaiting approval",
                approval_payload,
            )
            persist_run_truth(db, run_id)
            self._finalize_terminal_state(db, run_id)

    def _build_context_base(
        self,
        db_or_run: Session | RunModel,
        run_id_or_task_description: str,
        run: RunModel | None = None,
        task_description: str | None = None,
        *,
        recon_snapshot: ReconSnapshot | None = None,
        use_scout: bool = False,
    ) -> str:
        db: Session | None
        run_id: str
        if isinstance(db_or_run, RunModel):
            db = None
            run = db_or_run
            run_id = run.id
            task_description = run_id_or_task_description
        else:
            db = db_or_run
            if isinstance(run_id_or_task_description, RunModel):
                run = run_id_or_task_description
                run_id = run.id
            else:
                run_id = str(run_id_or_task_description)
        if run is None or task_description is None:
            raise ValueError("run and task_description are required")
        task_kind = run.task_kind or infer_task_kind(task_description)
        guidance = [f"Task mode: {task_kind}."]
        if task_kind == "analysis":
            guidance.append(
                "Prefer grounded analysis and report artifacts over speculative code changes unless the task explicitly asks for implementation."
            )
        context_base = task_description + "\n\nExecution guidance:\n- " + "\n- ".join(guidance)
        if recon_snapshot is not None:
            context_base += "\n\n" + recon_snapshot.format_for_stage("planner", use_scout=use_scout)
        if run.task_kind == "setup" and db is not None:
            project = ProjectService(db).get(run.project_id)
            context_base += "\n\n" + ScaffoldTemplateService().build_context_block(
                default_scaffold_variables(project.name, project.description or task_description)
            )
        baseline = self._latest_artifact(db, run_id, "baseline") if db else None
        if baseline:
            context_base += "\n\n" + BaselineService().context_block(baseline)
        if run.operator_feedback:
            context_base += "\n\nOperator feedback:\n" + run.operator_feedback
        elif run.error_message and run.status == RunStatus.CHANGES_REQUESTED.value:
            context_base += "\n\nOperator feedback:\n" + run.error_message
        if run.clarification_context:
            question = str(run.clarification_context.get("question") or "").strip()
            answer = str(run.clarification_context.get("answer") or "").strip()
            if question and answer:
                context_base += f"\n\nClarification resolved:\nQuestion: {question}\nAnswer: {answer}"
        if run.allow_web_search:
            try:
                search_block = WebSearchService().build_context_block(task_description, limit=5)
                context_base += f"\n\n{search_block}"
                if db is not None:
                    self._record_event(
                        db,
                        run_id,
                        "web_search_context_loaded",
                        "planner",
                        "info",
                        "Loaded public web search context for the task",
                        {"query": task_description},
                    )
            except (WebSearchError, httpx.HTTPError) as exc:
                context_base += f"\n\nWeb search note:\nEnabled, but search results were unavailable: {exc}"
                if db is not None:
                    self._record_event(
                        db,
                        run_id,
                        "web_search_context_failed",
                        "planner",
                        "warning",
                        f"Web search context unavailable: {exc}",
                        {"query": task_description},
                    )
        return context_base

    def _stage_context(self, db: Session, run: RunModel, stage: str, context_base: str) -> str:
        recon_artifact = self._latest_artifact(db, run.id, "recon") or {}
        if recon_artifact.get("repo_mode"):
            snapshot = ReconSnapshot(
                repo_mode=str(recon_artifact.get("repo_mode")),
                stack_profile=str(recon_artifact.get("stack_profile") or "python"),
                payload={k: v for k, v in recon_artifact.items() if k not in {"repo_mode", "stack_profile"}},
            )
            use_scout = bool(run.task.use_scout) if run.task else False
            context_base = context_base + "\n\n" + snapshot.format_for_stage(stage, use_scout=use_scout)
        if run.retry_count > 0 and stage == PipelineStage.CODER.value:
            coder = self._latest_artifact(db, run.id, "coder") or {}
            if coder:
                context_base += "\n\nPrevious coder attempt (retry context):\n" + self._truncate(
                    json.dumps(coder, ensure_ascii=True), self._CODER_FILE_CONTEXT_LIMIT
                )
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
        context = str(learning["context"])
        protected_files = self._protected_files_for_run(db, run.id)
        if protected_files:
            context = "\n".join(
                [
                    context,
                    "",
                    "Protected files (never patch):",
                    "\n".join(f"- {path}" for path in protected_files),
                ]
            )
        if stage == PipelineStage.ARCHITECT.value:
            architect_lines = [
                "",
                "Architect output requirement:",
                "- file_changes must list at least one repo-relative path with path, action, and rationale.",
            ]
            if run.task_kind == "analysis":
                architect_lines.append(
                    "- For analysis, include at least one .ai-copilot/reports/ artifact in file_changes."
                )
            context = context + "\n" + "\n".join(architect_lines)
        if stage == PipelineStage.UI_DESIGNER.value:
            context = self._append_pipeline_artifact_context(
                db,
                run.id,
                context,
                include_ui_design=False,
            )
        return context

    def _append_pipeline_artifact_context(
        self,
        db: Session,
        run_id: str,
        context: str,
        *,
        include_ui_design: bool = False,
    ) -> str:
        plan = self._latest_artifact(db, run_id, "plan") or {}
        architect = self._latest_artifact(db, run_id, "architect") or {}
        sections = [context]
        plan_summary = self._truncate(plan.get("summary") or "", self._REVIEW_ARTIFACT_LIMIT)
        if plan_summary:
            sections.extend(["", "Planner summary:", plan_summary])
        criteria_lines = self._plan_acceptance_criteria_lines(plan)
        if criteria_lines:
            sections.extend(["", "Planner acceptance criteria:", *criteria_lines])
        architect_overview = self._truncate(architect.get("overview") or "", self._REVIEW_ARTIFACT_LIMIT)
        if architect_overview:
            sections.extend(["", "Architect overview:", architect_overview])
        modules = architect.get("modules") or []
        if modules:
            module_lines = [f"- {module}" for module in modules if str(module).strip()]
            if module_lines:
                sections.extend(["", "Architect modules:", *module_lines[:20]])
        blueprint_paths = self._blueprint_paths(architect)
        if blueprint_paths:
            sections.extend(["", "Architect blueprint paths:", "\n".join(f"- {path}" for path in blueprint_paths)])
        if include_ui_design:
            ui_design = self._latest_artifact(db, run_id, "ui_design")
            if ui_design:
                sections.extend(
                    [
                        "",
                        "UI design summary:",
                        self._truncate(ui_design.get("layout_description") or "", self._REVIEW_ARTIFACT_LIMIT),
                        self._truncate(
                            json.dumps(ui_design.get("components") or [], ensure_ascii=True),
                            self._REVIEW_ARTIFACT_LIMIT,
                        ),
                    ]
                )
        return "\n".join(sections)

    def _build_stage_tool_runtime(self, db: Session, run_id: str, stage: str) -> PipelineToolRuntime | None:
        run = db.get(RunModel, run_id)
        if run is None:
            return None
        project = ProjectService(db).get(run.project_id)
        workspace = Path(run.workspace_path or project.source_repo_spec)

        def on_tool_event(event_type: str, payload: dict[str, Any]) -> None:
            tool_name = str(payload.get("tool") or "tool")
            if event_type == "start":
                message = f"Pipeline tool started: {tool_name}"
                severity = "info"
            elif event_type == "end":
                message = f"Pipeline tool completed: {tool_name}"
                severity = "info"
            else:
                message = f"Pipeline tool failed: {tool_name}"
                severity = "warning"
            event_name = f"pipeline_tool_{event_type}"
            self._record_event(db, run_id, event_name, stage, severity, message, payload)
            self._emit(run_id, event_name, stage, message, payload)

        return PipelineToolRuntime(
            PipelineToolExecutionContext(
                db=db,
                project=project,
                run=run,
                workspace=workspace,
            ),
            allow_web_search=bool(run.allow_web_search),
            on_tool_event=on_tool_event,
        )

    def _make_stage_agent(self, agent_cls, provider, tool_runtime: PipelineToolRuntime | None):
        try:
            return agent_cls(provider, tool_runtime=tool_runtime)
        except TypeError:
            return agent_cls(provider)

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

    def _latest_event_timestamp(self, db: Session, run_id: str) -> datetime | None:
        event = (
            db.query(RunEventModel)
            .filter(RunEventModel.run_id == run_id)
            .order_by(RunEventModel.created_at.desc())
            .first()
        )
        return event.created_at if event else None

    def _inflight_stale_reason(self, db: Session, run: RunModel) -> str | None:
        if run.status not in {RunStatus.RUNNING.value, RunStatus.PENDING.value}:
            return None
        latest_event_at = self._latest_event_timestamp(db, run.id)
        if run.status == RunStatus.PENDING.value:
            return None
        reference = latest_event_at or run.updated_at or run.created_at
        if not reference:
            return None
        now = datetime.now(UTC)
        if now - reference <= _STALE_INFLIGHT_TIMEOUT:
            return None
        stage = run.current_stage or "unknown"
        return f"Run stalled in {stage}: no progress recorded for more than {_STALE_INFLIGHT_TIMEOUT.total_seconds() // 60:.0f} minutes"

    def _finalize_stale_inflight_run(self, db: Session, run: RunModel) -> bool:
        reason = self._inflight_stale_reason(db, run)
        if not reason:
            return False
        run_id = run.id
        stage = run.current_stage or ""
        run.failure_class = "worker_stalled"
        run.failure_subclass = "stale_inflight"
        run.failure_signature = f"worker_stalled:{run.current_stage or 'unknown'}:{run_id}"
        run.recovery_status = "none"
        db.commit()
        self._mark_run_failed(db, run_id, stage, reason)
        self._record_event(
            db,
            run_id,
            "run_stalled",
            stage,
            "error",
            reason,
            {"stale_timeout_seconds": int(_STALE_INFLIGHT_TIMEOUT.total_seconds())},
        )
        self._emit(
            run_id,
            "run_stalled",
            stage,
            reason,
            {"stale_timeout_seconds": int(_STALE_INFLIGHT_TIMEOUT.total_seconds())},
            severity="error",
        )
        return True

    def _write_change_request_doc(
        self,
        db: Session,
        run_id: str,
        fs: FileService,
        plan: dict,
        *,
        task_description: str,
        slug: str | None = None,
    ) -> None:
        run = db.get(RunModel, run_id)
        if not run or run.task_kind == "setup":
            date = datetime.now(UTC).strftime("%Y-%m-%d")
            cr_slug = slug or "setup"
            path = f"docs/change-requests/CR-{date}-{cr_slug}.md"
            body = (
                f"# Change Request: {cr_slug}\n\n## What\nProject scaffold and governance setup.\n\n"
                f"## Why\n{task_description}\n\n## STATUS\nPENDING\n"
            )
            fs.write_file(path, body, check_protected=False)
            return
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        cr_slug = slug or self._slugify(task_description)
        path = f"docs/change-requests/CR-{date}-{cr_slug}.md"
        steps = plan.get("steps") or []
        criteria: list[str] = []
        for step in steps:
            criteria.extend(step.get("acceptance_criteria") or [])
        body_lines = [
            f"# Change Request: {cr_slug}",
            "",
            "## What",
            plan.get("summary") or task_description,
            "",
            "## Why",
            task_description,
            "",
            "## How",
            *(f"- {s.get('title')}: {s.get('description')}" for s in steps[:12]),
            "",
            "## Acceptance criteria",
            *(f"- {c}" for c in criteria[:20]),
            "",
            "## STATUS",
            "OPEN",
        ]
        fs.write_file(path, "\n".join(body_lines), check_protected=False)

    def _stage_app_designer(self, db: Session, run_id: str, context: str) -> bool:
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.APP_DESIGNER)
        self._log_provider(db, run_id, "app_designer", provider)
        agent = self._make_stage_agent(
            AppDesignAgent, provider, self._build_stage_tool_runtime(db, run_id, "app_designer")
        )
        output = agent.design_app(context)
        self._record_stage_output(output)
        self._save_artifact(db, run_id, "app_design", output.model_dump())
        persist_run_truth(db, run_id)
        return True

    def _stage_planner(self, db: Session, run_id: str, context: str, fs: FileService):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.PLANNER)
        self._log_provider(db, run_id, "planner", provider)
        agent = self._make_stage_agent(PlannerAgent, provider, self._build_stage_tool_runtime(db, run_id, "planner"))
        output = agent.plan(context)
        self._record_stage_output(output)
        plan_payload = output.model_dump()
        self._save_artifact(db, run_id, "plan", plan_payload)
        run = db.get(RunModel, run_id)
        task_desc = run.task.description if run and run.task else context
        self._write_change_request_doc(
            db, run_id, fs, plan_payload, task_description=task_desc, slug="setup" if run and run.task_kind == "setup" else None
        )
        persist_run_truth(db, run_id)
        return True

    def _stage_documentation(self, db: Session, run_id: str, context: str, fs: FileService) -> bool:
        if self._coder_noop_completed(db, run_id):
            coder = self._latest_artifact(db, run_id, "coder") or {}
            summary = str(coder.get("summary") or "No code changes required.").strip()
            payload = {
                "changelog_entry": summary,
                "architecture_notes": "No architecture changes.",
                "doc_updates": [],
            }
            self._save_artifact(db, run_id, "documentation", payload)
            self._record_event(
                db,
                run_id,
                "documentation_skipped",
                "documentation",
                "info",
                "Documentation skipped because coder produced no file changes.",
                payload,
            )
            persist_run_truth(db, run_id)
            return True
        tester = self._latest_artifact(db, run_id, "tester") or {}
        test_plan = self._latest_artifact(db, run_id, "test_plan") or {}
        if not tester.get("passed", True) and not test_plan.get("passed", True):
            self._record_event(db, run_id, "documentation_skipped", "documentation", "info", "Tester did not pass")
            return True
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.DOCUMENTATION)
        self._log_provider(db, run_id, "documentation", provider)
        agent = self._make_stage_agent(
            DocumentationAgent, provider, self._build_stage_tool_runtime(db, run_id, "documentation")
        )
        output = agent.document(context)
        self._record_stage_output(output)
        self._save_artifact(db, run_id, "documentation", output.model_dump())
        changelog = Path("CHANGELOG.md")
        if changelog.as_posix():
            try:
                existing = fs.read_file("CHANGELOG.md")["content"]
            except Exception:
                existing = "# Changelog\n\n"
            fs.write_file(
                "CHANGELOG.md",
                existing.rstrip() + "\n\n## Unreleased\n\n- " + output.changelog_entry + "\n",
                check_protected=False,
            )
        run = db.get(RunModel, run_id)
        project = ProjectService(db).get(run.project_id) if run else None
        if project:
            ArchitectureStateService().append_task_summary(
                Path(project.source_repo_spec),
                output.changelog_entry,
                architecture_delta=output.architecture_notes,
                workspace=Path(run.workspace_path) if run and run.workspace_path else None,
            )
        persist_run_truth(db, run_id)
        return True

    def _architect_schema_reminder(self, run: RunModel | None) -> str:
        lines = [
            "Architect contract reminder:",
            "- file_changes must contain at least one entry with path, action, and rationale.",
            "- Use exact field names: overview, modules, file_changes, dependencies.",
        ]
        task_kind = (run.task_kind if run else None) or ""
        if task_kind == "analysis":
            lines.append(
                "- For analysis tasks, include at least one .ai-copilot/reports/ path in file_changes (action: create)."
            )
        return "\n".join(lines)

    def _stage_architect(self, db: Session, run_id: str, context: str):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.ARCHITECT)
        self._log_provider(db, run_id, "architect", provider)
        agent = self._make_stage_agent(ArchitectAgent, provider, self._build_stage_tool_runtime(db, run_id, "architect"))
        run = db.get(RunModel, run_id)
        attempt_context = context
        max_attempts = 3
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                output = agent.design(attempt_context)
            except (json.JSONDecodeError, PydanticValidationError) as exc:
                last_exc = exc
                self._record_event(
                    db,
                    run_id,
                    "architect_schema_rejected",
                    "architect",
                    "warning",
                    str(exc),
                    {"attempt": attempt},
                )
                self._emit(
                    run_id,
                    "architect_schema_rejected",
                    "architect",
                    str(exc),
                    {"attempt": attempt},
                    severity="warning",
                )
                if attempt >= max_attempts:
                    raise
                attempt_context = "\n".join(
                    [
                        context,
                        "",
                        "Previous architect output was invalid JSON or schema:",
                        str(exc),
                        "",
                        self._architect_schema_reminder(run),
                    ]
                )
                continue
            self._record_stage_output(output)
            architect_payload = output.model_dump()
            self._save_artifact(db, run_id, "architect", architect_payload)
            run = db.get(RunModel, run_id)
            if run and run.workspace_path:
                project = ProjectService(db).get(run.project_id)
                if project:
                    fs = FileService(Path(run.workspace_path))
                    satisfaction = evaluate_blueprint_satisfaction(
                        architect_payload,
                        fs,
                        fs.workspace,
                        Path(project.source_repo_spec),
                    )
                    self._save_artifact(
                        db,
                        run_id,
                        "run_outcome",
                        {
                            "kind": satisfaction.kind.value,
                            "blueprint_paths": list(satisfaction.blueprint_paths),
                            "test_paths": list(satisfaction.test_paths),
                            "message": satisfaction.message,
                        },
                    )
                    if satisfaction.kind == RunOutcomeKind.ALREADY_SATISFIED:
                        self._record_event(
                            db,
                            run_id,
                            "blueprint_already_satisfied",
                            "architect",
                            "info",
                            satisfaction.message,
                            {"paths": list(satisfaction.blueprint_paths)},
                        )
                        self._emit(
                            run_id,
                            "blueprint_already_satisfied",
                            "architect",
                            satisfaction.message,
                            {"paths": list(satisfaction.blueprint_paths)},
                        )
            persist_run_truth(db, run_id)
            return True
        if last_exc is not None:
            raise last_exc
        return True

    def _stage_ui(self, db: Session, run_id: str, context: str):
        run = db.get(RunModel, run_id)
        task = run.task if run else None
        description = task.description if task else ""
        deliverable_kind = run.deliverable_kind if run else None
        task_kind = run.task_kind if run else None
        if not should_run_ui_designer(description, task_kind, deliverable_kind):
            self._record_event(
                db,
                run_id,
                "ui_designer_skipped",
                "ui_designer",
                "info",
                "UI stage skipped",
                {
                    "reason": "no_ui_surface_detected",
                    "deliverable_kind": deliverable_kind or infer_deliverable_kind(description, task_kind),
                },
            )
            self._record_stage_output(None)
            return True
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.UI_DESIGNER)
        self._log_provider(db, run_id, "ui_designer", provider)
        agent = self._make_stage_agent(UIDesignerAgent, provider, self._build_stage_tool_runtime(db, run_id, "ui_designer"))
        output = agent.design(context)
        self._record_stage_output(output)
        self._save_artifact(db, run_id, "ui_design", output.model_dump())
        persist_run_truth(db, run_id)
        return True

    def _stage_coder(self, db: Session, run_id: str, context: str, fs: FileService):
        provider = ProviderRegistry.get().resolve_stage(PipelineStage.CODER)
        self._log_provider(db, run_id, "coder", provider)
        run = db.get(RunModel, run_id)
        project = ProjectService(db).get(run.project_id) if run else None
        source_root = Path(project.source_repo_spec) if project else fs.workspace
        architect = self._latest_artifact(db, run_id, "architect") or {}
        noop_output = self._try_coder_noop_when_blueprint_satisfied(
            db, run_id, fs, architect, fs.workspace, source_root
        )
        if noop_output is not None:
            self._record_stage_output(noop_output)
            payload = noop_output.model_dump()
            payload["applied_changes"] = []
            payload["coder_attempt"] = 0
            self._save_artifact(db, run_id, "coder", payload)
            self._resolve_pipeline_blocks(db, run_id, resolved_by_stage="coder", stage="coder")
            self._record_event(db, run_id, "code_patch_applied", "coder", "info", "No patch required")
            self._emit(run_id, "code_patch_applied", "coder", "No patch required")
            persist_run_truth(db, run_id)
            return True
        blueprint_paths = self._blueprint_paths(architect)
        files_ready = bool(blueprint_paths and self._blueprint_files_exist(fs, blueprint_paths))
        tool_runtime = None if files_ready else self._build_stage_tool_runtime(db, run_id, "coder")
        agent = self._make_stage_agent(CoderAgent, provider, tool_runtime)
        attempt_context = self._build_coder_context(db, run_id, context, fs, source_root)
        max_attempts = 3
        last_exc: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                output = agent.code(attempt_context)
            except (json.JSONDecodeError, PydanticValidationError) as exc:
                last_exc = exc
                self._record_event(
                    db,
                    run_id,
                    "coder_schema_rejected",
                    "coder",
                    "warning",
                    str(exc),
                    {"attempt": attempt},
                )
                self._emit(
                    run_id,
                    "coder_schema_rejected",
                    "coder",
                    str(exc),
                    {"attempt": attempt},
                    severity="warning",
                )
                if attempt >= max_attempts:
                    raise
                attempt_context = "\n".join(
                    [
                        context,
                        "",
                        "Previous coder output was invalid JSON or schema:",
                        str(exc),
                        "",
                        self._build_coder_context(db, run_id, "", fs, source_root),
                    ]
                )
                continue
            changes = [
                fc if isinstance(fc, dict) else fc.model_dump() for fc in output.file_changes
            ]
            try:
                self._validate_setup_coder_scope(run, fs.workspace, changes, blueprint_paths)
                applied = fs.apply_coder_changes(changes)
                self._run_frontend_patch_check(fs.workspace, applied)
                applied_paths = [str(c.get("path") or "") for c in applied if c.get("path")]
                self._run_deployment_guards_on_changes(db, run_id, fs.workspace, applied_paths)
            except PatchGuardError as exc:
                last_exc = exc
                exc_text = str(exc)
                is_protected = "protected" in exc_text.lower()
                is_frontend_tsc = "frontend patch validation failed" in exc_text.lower()
                is_deployment_gate = "deployment gate failed" in exc_text.lower()
                block_source = (
                    "protected_path"
                    if is_protected
                    else (
                        "frontend_tsc"
                        if is_frontend_tsc
                        else ("integration_guard" if is_deployment_gate else "change_guard")
                    )
                )
                block_type = (
                    "protected_path"
                    if is_protected
                    else (
                        "frontend_tsc"
                        if is_frontend_tsc
                        else ("integration_guard" if is_deployment_gate else "structural_guard")
                    )
                )
                target_stages = ["planner", "architect"] if is_protected else ["coder"]
                self._record_pipeline_block(
                    db,
                    run_id,
                    block_type=block_type,
                    stage="coder",
                    source=block_source,
                    message=exc_text,
                    guidance=(
                        "Do not patch protected files; update planner/architect scope instead."
                        if is_protected
                        else (
                            "Fix TypeScript errors with surgical line_changes; preserve unrelated imports and exports."
                            if is_frontend_tsc
                            else (
                                "Stay within architect blueprint paths for setup runs. Revise using line_changes only; preserve imports, exports, props, and helper functions."
                                if run and run.task_kind == "setup"
                                else "Revise using line_changes only; preserve imports, exports, props, and helper functions."
                            )
                        )
                    ),
                    target_stages=target_stages,
                )
                self._record_event(
                    db,
                    run_id,
                    "coder_guard_rejected",
                    "coder",
                    "warning",
                    exc_text,
                    {"attempt": attempt, "source": block_source},
                )
                self._emit(run_id, "coder_guard_rejected", "coder", exc_text, {"attempt": attempt})
                if attempt >= max_attempts:
                    raise
                attempt_context = "\n".join(
                    [
                        context,
                        "",
                        "Deterministic patch guard rejected the previous attempt:",
                        exc_text,
                        "",
                        "For setup runs, only patch architect blueprint files or existing change-request companion files.",
                        "Revise the patch using line_changes only for existing source files. Preserve all unrelated imports, exports, props, interfaces, and helper functions.",
                        "Place imports only in the import block at the top of the file. Place JSX only inside the existing render tree.",
                        "",
                        self._build_coder_context(db, run_id, "", fs, source_root),
                    ]
                )
                retired_guidance = LearningService(db).get_retired_block_guidance(run_id, max_entries=2)
                if retired_guidance:
                    attempt_context += "\n\nResolved block guidance:\n" + "\n".join(f"- {g}" for g in retired_guidance)
                continue
            self._record_stage_output(output)
            payload = output.model_dump()
            payload["applied_changes"] = applied
            payload["coder_attempt"] = attempt
            self._save_artifact(db, run_id, "coder", payload)
            self._resolve_pipeline_blocks(db, run_id, resolved_by_stage="coder", stage="coder")
            self._record_event(db, run_id, "code_patch_applied", "coder", "info", "Patch applied")
            self._emit(run_id, "code_patch_applied", "coder", "Patch applied")
            persist_run_truth(db, run_id)
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

    def _latest_changed_files(self, db: Session, run_id: str, workspace: Path | None = None) -> list[str]:
        run = db.get(RunModel, run_id)
        if not run:
            return []
        project = ProjectService(db).get(run.project_id)
        source_root = Path(project.source_repo_spec)
        ws = Path(run.workspace_path) if run.workspace_path else (workspace or source_root)
        return effective_changed_files(db, run_id, ws, source_root)

    def _run_deployment_guards_on_changes(
        self,
        db: Session,
        run_id: str,
        workspace: Path,
        changed_paths: list[str],
    ) -> None:
        if not changed_paths:
            return
        issues = integration_guard_issues(workspace, changed_files=changed_paths) + contract_guard_issues(
            workspace, changed_paths
        )
        if not issues:
            return
        message = "; ".join(str(item.get("message") or "") for item in issues[:3])
        raise PatchGuardError("deployment_gates", f"Deployment gate failed: {message}")

    def _finalize_deployment_gates(self, db: Session, run_id: str, workspace: Path, source_root: Path) -> bool:
        run = db.get(RunModel, run_id)
        if not run:
            return False
        if self._coder_noop_completed(db, run_id):
            payload = {
                "approved": True,
                "summary": "No coder changes; pre-deploy supervisor skipped.",
                "plan_gaps": [],
                "deterministic": {"noop_coder": True},
                "llm_plan_gaps": [],
            }
            db.add(
                ArtifactModel(
                    run_id=run_id,
                    artifact_type="pre_deploy_supervisor",
                    content_json=json.dumps(payload),
                )
            )
            db.commit()
            self._record_event(
                db,
                run_id,
                "pre_deploy_skipped",
                "supervisor",
                "info",
                payload["summary"],
                payload,
            )
            self._emit(run_id, "pre_deploy_skipped", "supervisor", payload["summary"], payload)
            return True
        changed = effective_changed_files(db, run_id, workspace, source_root)
        pre = run_pre_deploy_supervisor(db, run_id, changed, workspace)
        if pre and not pre.get("approved", False):
            gaps = pre.get("plan_gaps") or []
            run.status = RunStatus.BLOCKED.value
            run.error_message = f"Pre-deploy supervisor rejected: {len(gaps)} plan gap(s)"
            db.commit()
            self._record_event(
                db,
                run_id,
                "pre_deploy_rejected",
                "supervisor",
                "error",
                run.error_message,
                {"plan_gaps": gaps},
            )
            self._emit(run_id, "run_blocked", "supervisor", run.error_message)
            return False

        readiness = evaluate_deployment_readiness(db, run_id, workspace=workspace)
        if readiness.get("ready"):
            self._record_event(
                db,
                run_id,
                "deployment_gates_passed",
                "tester",
                "info",
                "All deployment gates passed",
                readiness,
            )
            return True

        blocking = ", ".join(readiness.get("blocking") or []) or "deployment gates failed"
        run.status = RunStatus.BLOCKED.value
        run.error_message = blocking
        db.commit()
        self._record_event(
            db,
            run_id,
            "deployment_gates_failed",
            "tester",
            "error",
            blocking,
            readiness,
        )
        self._emit(run_id, "run_blocked", "tester", blocking)
        return False

    def _tester_requires_visual_plan(self, db: Session, run_id: str, changed_files: list[str]) -> bool:
        if any(is_frontend_code_path(path) for path in changed_files):
            return True
        return self._latest_artifact(db, run_id, "ui_design") is not None

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

    def _protected_files_for_run(self, db: Session, run_id: str) -> list[str]:
        run = db.get(RunModel, run_id)
        if not run:
            return []
        project = ProjectService(db).get(run.project_id)
        return list(project.protected_files or [])

    def _plan_acceptance_criteria_lines(self, plan: dict) -> list[str]:
        lines: list[str] = []
        for step in plan.get("steps") or []:
            if not isinstance(step, dict):
                continue
            step_id = str(step.get("step_id") or "").strip()
            title = str(step.get("title") or "").strip()
            for criterion in step.get("acceptance_criteria") or []:
                text = str(criterion or "").strip()
                if text:
                    label = f"Step {step_id}" if step_id else "Step"
                    if title:
                        label = f"{label} ({title})"
                    lines.append(f"- {label}: {text}")
        return lines

    def _blueprint_paths(self, architect: dict) -> list[str]:
        return blueprint_paths(architect)

    def _blueprint_test_paths(self, paths: list[str]) -> list[str]:
        return blueprint_test_paths(paths)

    def _blueprint_files_exist(self, fs: FileService, paths: list[str]) -> bool:
        return blueprint_files_exist(fs, paths)

    def _blueprint_tests_pass(self, workspace: Path, test_paths: list[str], source_root: Path) -> bool:
        return blueprint_tests_pass(workspace, test_paths, source_root=source_root)

    def _try_coder_noop_when_blueprint_satisfied(
        self,
        db: Session,
        run_id: str,
        fs: FileService,
        architect: dict,
        workspace: Path,
        source_root: Path,
    ) -> CoderOutput | None:
        satisfaction = evaluate_blueprint_satisfaction(architect, fs, workspace, source_root)
        if satisfaction.kind != RunOutcomeKind.ALREADY_SATISFIED:
            return None
        paths = list(satisfaction.blueprint_paths)
        test_paths = list(satisfaction.test_paths)
        self._save_artifact(
            db,
            run_id,
            "run_outcome",
            {
                "kind": satisfaction.kind.value,
                "blueprint_paths": paths,
                "test_paths": test_paths,
                "message": satisfaction.message,
            },
        )
        self._record_event(
            db,
            run_id,
            "coder_noop_blueprint_satisfied",
            "coder",
            "info",
            satisfaction.message,
            {"paths": paths, "test_paths": test_paths, "outcome": satisfaction.kind.value},
        )
        self._emit(
            run_id,
            "coder_noop_blueprint_satisfied",
            "coder",
            satisfaction.message,
            {"paths": paths, "outcome": satisfaction.kind.value},
        )
        return CoderOutput(summary=satisfaction.message, file_changes=[], requires_operator_approval=False)

    def _record_pipeline_block(
        self,
        db: Session,
        run_id: str,
        *,
        block_type: str,
        stage: str,
        source: str,
        message: str,
        guidance: str,
        target_stages: list[str],
    ) -> str:
        signature = LearningService(db).record_block(
            run_id,
            block_type=block_type,
            stage=stage,
            source=source,
            message=message,
            guidance=guidance,
            target_stages=target_stages,
        )
        block_payload = enrich_event_payload(
            "block_recorded",
            stage,
            "warning",
            {"signature": signature, "source": source, "block_type": block_type},
            message=message,
        )
        self._record_event(
            db,
            run_id,
            "block_recorded",
            stage,
            "warning",
            message,
            block_payload,
        )
        self._emit(run_id, "block_recorded", stage, message, block_payload, severity="warning")
        return signature

    def _resolve_pipeline_blocks(
        self,
        db: Session,
        run_id: str,
        *,
        resolved_by_stage: str,
        stage: str | None = None,
    ) -> None:
        retired = LearningService(db).retire_pending_blocks(
            run_id,
            resolved_by_stage=resolved_by_stage,
            stage=stage,
        )
        for item in retired:
            self._record_event(
                db,
                run_id,
                "block_resolved",
                resolved_by_stage,
                "info",
                f"Block resolved: {item.get('signature')}",
                item,
            )
            self._emit(run_id, "block_resolved", resolved_by_stage, "Block resolved", item)

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
        run = db.get(RunModel, run_id)
        plan = self._latest_artifact(db, run_id, "plan") or {}
        architect = self._latest_artifact(db, run_id, "architect") or {}
        protected_files = self._protected_files_for_run(db, run_id)
        blueprint_paths = self._blueprint_paths(architect)
        sections = [context]
        criteria_lines = self._plan_acceptance_criteria_lines(plan)
        if criteria_lines:
            sections.extend(["", "Acceptance criteria checklist:", *criteria_lines])
        if blueprint_paths:
            sections.extend(["", "Architect blueprint paths:", "\n".join(f"- {path}" for path in blueprint_paths)])
            if run and run.task_kind == "setup":
                sections.extend(
                    [
                        "",
                        "Setup run scope rule:",
                        "Only patch architect blueprint paths or an existing docs/change-requests companion file created by planner.",
                        "Never patch dependency directories such as node_modules during setup.",
                    ]
                )
        ui_design = self._latest_artifact(db, run_id, "ui_design")
        if ui_design:
            sections.extend(
                [
                    "",
                    "UI design summary:",
                    self._truncate(ui_design.get("layout_description") or "", self._REVIEW_ARTIFACT_LIMIT),
                    self._truncate(
                        json.dumps(ui_design.get("components") or [], ensure_ascii=True),
                        self._REVIEW_ARTIFACT_LIMIT,
                    ),
                ]
            )
        if protected_files:
            sections.extend(
                [
                    "",
                    "Protected files (never patch):",
                    "\n".join(f"- {path}" for path in protected_files),
                ]
            )
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
        if blueprint_paths and self._blueprint_files_exist(fs, blueprint_paths):
            sections.extend(
                [
                    "",
                    "Blueprint status:",
                    "All architect blueprint files already exist in the workspace.",
                    "If the line-numbered snapshots above already satisfy acceptance criteria, return CoderOutput with an empty file_changes list.",
                ]
            )
        return "\n".join(sections)

    def _is_dependency_path(self, rel_path: str) -> bool:
        normalized = str(rel_path or "").strip().replace("\\", "/")
        if not normalized:
            return False
        parts = tuple(part for part in normalized.split("/") if part)
        return "node_modules" in parts or normalized.startswith(".venv/") or normalized == ".venv"

    def _is_allowed_setup_companion_path(self, workspace: Path, rel_path: str) -> bool:
        normalized = str(rel_path or "").strip().replace("\\", "/")
        if not normalized:
            return False
        if any(normalized.startswith(prefix) for prefix in _ALLOWED_SETUP_COMPANION_PREFIXES):
            return (workspace / normalized).exists()
        return False

    def _validate_setup_coder_scope(
        self,
        run: RunModel | None,
        workspace: Path,
        changes: list[dict],
        blueprint_paths: list[str],
    ) -> None:
        if not run or run.task_kind != "setup":
            return
        allowed = {path.replace("\\", "/") for path in blueprint_paths if path}
        for change in changes:
            rel_path = str(change.get("path") or "").strip().replace("\\", "/")
            if not rel_path:
                continue
            if self._is_dependency_path(rel_path):
                raise PatchGuardError(rel_path, "Coder output targeted dependency path during setup")
            if rel_path in allowed:
                continue
            if self._is_allowed_setup_companion_path(workspace, rel_path):
                continue
            raise PatchGuardError(rel_path, "Coder output targeted non-blueprint path during setup")

    def _run_frontend_patch_check(self, workspace: Path, changed_files: list[dict]) -> None:
        if not any(
            is_frontend_code_path(str(change.get("path") or ""))
            and not self._is_dependency_path(str(change.get("path") or ""))
            for change in changed_files
        ):
            return
        frontend_dir = workspace / "frontend"
        node_modules = frontend_dir / "node_modules"
        if not node_modules.exists():
            raise PatchGuardError("frontend/node_modules", "frontend toolchain missing in run workspace")
        tsc = frontend_dir / "node_modules" / "typescript" / "lib" / "tsc.js"
        if not tsc.is_file():
            raise PatchGuardError("frontend", "typescript compiler missing in run workspace")
        code, stdout, stderr = run_command(f"node {tsc} -b --noEmit", frontend_dir)
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
    ) -> tuple[str, list[str], list[dict], list[dict]]:
        plan = self._latest_artifact(db, run_id, "plan") or {}
        architect = self._latest_artifact(db, run_id, "architect") or {}
        coder = self._latest_artifact(db, run_id, "coder") or {}
        ui_design = self._latest_artifact(db, run_id, "ui_design")
        protected_files = self._protected_files_for_run(db, run_id)
        blueprint_paths = self._blueprint_paths(architect)

        changed_files: list[str] = []
        file_sections: list[str] = []
        structural_summaries: list[dict] = []
        file_details: list[dict] = []
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
            after_text = file_snapshot if isinstance(file_snapshot, str) else ""
            file_details.append({"path": rel_path, "before": before_snapshot, "after": after_text})
            structural_summary = summarize_structure(
                rel_path,
                before_snapshot,
                after_text,
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

        criteria_lines = self._plan_acceptance_criteria_lines(plan)
        sections = [
            "Task acceptance context:",
            context,
            "",
            "Planner summary:",
            self._truncate(plan.get("summary") or "", self._REVIEW_ARTIFACT_LIMIT),
        ]
        if criteria_lines:
            sections.extend(["", "Planner acceptance criteria:", *criteria_lines])
        sections.extend(
            [
                "",
                "Architect overview:",
                self._truncate(architect.get("overview") or "", self._REVIEW_ARTIFACT_LIMIT),
            ]
        )
        if blueprint_paths:
            sections.extend(["", "Architect blueprint paths:", "\n".join(f"- {path}" for path in blueprint_paths)])
        if ui_design:
            sections.extend(
                [
                    "",
                    "UI design summary:",
                    self._truncate(ui_design.get("layout_description") or "", self._REVIEW_ARTIFACT_LIMIT),
                    self._truncate(json.dumps(ui_design.get("components") or [], ensure_ascii=True), self._REVIEW_ARTIFACT_LIMIT),
                ]
            )
        if protected_files:
            sections.extend(
                [
                    "",
                    "Protected files:",
                    "\n".join(f"- {path}" for path in protected_files),
                ]
            )
        sections.extend(
            [
                "",
                "Coder summary:",
                self._truncate(coder.get("summary") or "", self._REVIEW_ARTIFACT_LIMIT),
                "",
                "Changed files:",
                "\n".join(changed_files) if changed_files else "[none recorded]",
            ]
        )
        if file_sections:
            sections.extend(["", "Changed file details:", "\n\n".join(file_sections)])
        return "\n".join(sections), changed_files, structural_summaries, file_details

    def _deterministic_review_issues(
        self,
        db: Session,
        run_id: str,
        summaries: list[dict],
        file_details: list[dict],
        changed_files: list[str],
        task_kind: str | None,
    ) -> list[dict]:
        issues: list[dict] = []
        for summary in summaries:
            for message in reviewer_guard_issues(summary):
                issues.append(
                    {
                        "severity": "important",
                        "file_path": summary["path"],
                        "message": message,
                        "source": "deterministic_guard",
                    }
                )
        for detail in file_details:
            path = str(detail.get("path") or "")
            before = str(detail.get("before") or "")
            after = str(detail.get("after") or "")
            for item in frontend_structure_issues(path, before, after):
                issues.append(
                    {
                        "severity": "important",
                        "file_path": path,
                        "message": str(item.get("message") or ""),
                        "source": "deterministic_guard",
                    }
                )
        architect = self._latest_artifact(db, run_id, "architect") or {}
        blueprint_paths = self._blueprint_paths(architect)
        for scope_issue in scope_issues(blueprint_paths, changed_files, task_kind):
            issues.append(dict(scope_issue))
        run = db.get(RunModel, run_id)
        project = ProjectService(db).get(run.project_id) if run else None
        source_root = Path(project.source_repo_spec) if project else Path(".")
        workspace = Path(run.workspace_path) if run and run.workspace_path else source_root
        coder = self._latest_artifact(db, run_id, "coder") or {}
        coder_changed_paths = [
            str(change.get("path") or "").strip()
            for change in (coder.get("file_changes") or [])
            if isinstance(change, dict) and str(change.get("path") or "").strip()
        ]
        scoped_changed = sorted(set(coder_changed_paths))
        if scoped_changed:
            for issue in integration_guard_issues(workspace, changed_files=scoped_changed):
                issues.append(
                    {
                        "severity": issue.get("severity") or "critical",
                        "file_path": issue.get("path") or "",
                        "message": str(issue.get("message") or ""),
                        "source": "integration_guard",
                    }
                )
        if scoped_changed:
            for issue in contract_guard_issues(workspace, scoped_changed):
                issues.append(
                    {
                        "severity": issue.get("severity") or "critical",
                        "file_path": issue.get("path") or "",
                        "message": str(issue.get("message") or ""),
                        "source": "contract_guard",
                    }
                )
        ui_design = self._latest_artifact(db, run_id, "ui_design")
        if any(is_frontend_code_path(path) for path in scoped_changed) and not ui_design:
            issues.append(
                {
                    "severity": "important",
                    "file_path": changed_files[0] if changed_files else "",
                    "message": (
                        "Frontend files changed but no ui_design artifact exists. "
                        "Add a UI design spec or justify the edit as a non-UI tweak in the coder summary."
                    ),
                    "source": "deterministic_guard",
                }
            )
        if (
            run
            and run.task_kind == "implementation"
            and run.deliverable_kind != "report"
            and scoped_changed
            and all(path.startswith(".ai-copilot/reports/") or path.endswith((".md", ".txt", ".rst")) for path in scoped_changed)
        ):
            issues.append(
                {
                    "severity": "critical",
                    "file_path": scoped_changed[0],
                    "message": "Implementation task drifted into report-only output instead of changing the requested product surface.",
                    "source": "intent_guard",
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

    def _build_coder_retry_context(self, db: Session, run_id: str, context: str, review: dict) -> str:
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
        retired_guidance = LearningService(db).get_retired_block_guidance(run_id, max_entries=2)
        if retired_guidance:
            feedback_lines.extend(["", "Resolved block guidance for this retry:"])
            for guidance in retired_guidance:
                feedback_lines.append(f"- {guidance}")
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
        persist_run_truth(db, run_id)
        self._record_event(db, run_id, event_type, "reviewer", "warning", summary, payload)
        self._emit(run_id, event_type, "reviewer", summary, payload)
        self._record_event(db, run_id, "run_changes_requested", "reviewer", "warning", summary, payload)
        self._emit(run_id, "run_changes_requested", "reviewer", summary, payload)

    def _coder_noop_completed(self, db: Session, run_id: str) -> bool:
        return coder_noop_completed(db, run_id)

    def _coder_has_file_changes(self, db: Session, run_id: str) -> bool:
        return coder_has_file_changes(db, run_id)

    def _auto_approve_empty_coder_review(self, db: Session, run_id: str) -> bool:
        coder = self._latest_artifact(db, run_id, "coder") or {}
        summary = str(coder.get("summary") or "No code changes required.").strip()
        review_payload = {
            "approved": True,
            "summary": f"Auto-approved: {summary}",
            "issues": [],
            "suggestions": [],
        }
        self._save_artifact(db, run_id, "review_1", review_payload)
        self._resolve_pipeline_blocks(db, run_id, resolved_by_stage="reviewer", stage="reviewer")
        self._record_event(
            db,
            run_id,
            "reviewer_approved",
            "reviewer",
            "info",
            review_payload["summary"],
            {"attempt": 1, "auto_approved": True},
        )
        self._emit(run_id, "reviewer_approved", "reviewer", review_payload["summary"], {"auto_approved": True})
        persist_run_truth(db, run_id)
        return True

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
        agent = self._make_stage_agent(ReviewerAgent, provider, self._build_stage_tool_runtime(db, run_id, "reviewer"))
        if self._coder_noop_completed(db, run_id):
            return self._auto_approve_empty_coder_review(db, run_id)
        for attempt in range(1, max_retries + 1):
            run = db.get(RunModel, run_id)
            if not run:
                return False
            run.review_attempts = attempt
            db.commit()
            review_context, changed_files, structural_summaries, file_details = self._build_reviewer_context(
                db,
                run_id,
                context,
                fs,
                source_root,
            )
            task_kind = run.task_kind if run else None
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
            deterministic_issues = self._deterministic_review_issues(
                db,
                run_id,
                structural_summaries,
                file_details,
                changed_files,
                task_kind,
            )
            blocking_issues = [
                issue
                for issue in deterministic_issues
                if str(issue.get("severity") or "") in {"critical", "important"}
            ]
            if blocking_issues:
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
                issue_guidance = "; ".join(
                    str(issue.get("message") or "") for issue in blocking_issues[:3] if isinstance(issue, dict)
                )
                self._record_pipeline_block(
                    db,
                    run_id,
                    block_type="review_rejection",
                    stage="reviewer",
                    source=str(blocking_issues[0].get("source") or "deterministic_guard"),
                    message=summary,
                    guidance=issue_guidance or summary,
                    target_stages=["coder", "architect"],
                )
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
                    retry_context = self._build_coder_retry_context(db, run_id, context, review_payload)
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
            if deterministic_issues:
                review_context = (
                    f"{review_context}\n\nScope advisory notes:\n"
                    + "\n".join(
                        f"- [{issue.get('severity')}] {issue.get('file_path')}: {issue.get('message')}"
                        for issue in deterministic_issues
                    )
                )
            review_context = (
                f"{review_context}\n\nTwo-stage review (Hermes-style): first verify spec/acceptance "
                "criteria compliance, then code quality. Approve only if both pass."
            )
            output = agent.review(review_context)
            self._record_stage_output(output)
            review_payload = output.model_dump()
            self._save_artifact(db, run_id, f"review_{attempt}", review_payload)
            if output.approved:
                self._resolve_pipeline_blocks(db, run_id, resolved_by_stage="reviewer", stage="reviewer")
                issues = review_payload.get("issues")
                issue_list = issues if isinstance(issues, list) else []
                self._record_event(
                    db,
                    run_id,
                    "reviewer_approved",
                    "reviewer",
                    "info",
                    output.summary,
                    {"attempt": attempt, "issues": issue_list},
                )
                self._emit(
                    run_id,
                    "reviewer_approved",
                    "reviewer",
                    output.summary,
                    {"attempt": attempt, "issues": issue_list},
                )
                persist_run_truth(db, run_id)
                return True
            issues = review_payload.get("issues")
            issue_list = issues if isinstance(issues, list) else []
            issue_guidance = "; ".join(
                str(issue.get("message") or "")
                for issue in issue_list[:3]
                if isinstance(issue, dict)
            )
            self._record_pipeline_block(
                db,
                run_id,
                block_type="review_rejection",
                stage="reviewer",
                source="reviewer",
                message=str(output.summary or "Reviewer requested changes"),
                guidance=issue_guidance or str(output.summary or ""),
                target_stages=["coder"],
            )
            self._record_event(
                db,
                run_id,
                "reviewer_requested_changes",
                "reviewer",
                "warning",
                output.summary,
                {"attempt": attempt, "issues": issue_list},
            )
            self._emit(
                run_id,
                "reviewer_requested_changes",
                "reviewer",
                output.summary,
                {"attempt": attempt, "issues": issue_list},
            )
            if self._review_failed_for_missing_context(
                output.summary,
                cast(list[dict[str, Any]], issue_list),
                changed_files,
            ):
                self._mark_changes_requested(
                    db,
                    run_id,
                    f"Reviewer could not validate the patch with the available context: {output.summary}",
                    "reviewer_failed_fast",
                    {"attempt": attempt, "issues": issue_list, "changed_files": changed_files},
                )
                return False
            if attempt < max_retries:
                retry_context = self._build_coder_retry_context(db, run_id, context, review_payload)
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

    def _block_frontend_scaffold(
        self,
        db: Session,
        run_id: str,
        blocked_commands: list[str],
    ) -> bool:
        self._record_pipeline_block(
            db,
            run_id,
            block_type="frontend_scaffold_missing",
            stage="tester",
            source="validation_profile",
            message=FRONTEND_SCAFFOLD_MESSAGE,
            guidance=(
                "Add frontend/package.json and install the frontend toolchain in the run workspace "
                "before retrying fullstack or react validation."
            ),
            target_stages=["coder", "tester"],
        )
        for command in blocked_commands:
            self._record_event(
                db,
                run_id,
                "frontend_scaffold_missing",
                "tester",
                "error",
                FRONTEND_SCAFFOLD_MESSAGE,
                {"command": command, "required": True},
            )
        run = db.get(RunModel, run_id)
        if not run:
            return False
        run.status = RunStatus.BLOCKED.value
        run.error_message = FRONTEND_SCAFFOLD_MESSAGE
        db.commit()
        self._emit(run_id, "run_blocked", "tester", FRONTEND_SCAFFOLD_MESSAGE)
        return False

    def _record_optional_frontend_scaffold_skips(
        self,
        db: Session,
        run_id: str,
        blocked_commands: list[str],
    ) -> None:
        for command in blocked_commands:
            self._record_event(
                db,
                run_id,
                "validation_skipped",
                "tester",
                "info",
                FRONTEND_SCAFFOLD_MESSAGE,
                {"command": command, "required": False, "reason": "frontend_scaffold_missing"},
            )

    def _execute_tester_command_batch(
        self,
        db: Session,
        run_id: str,
        workspace,
        commands: list[str],
        *,
        event_prefix: str,
        required: bool,
    ) -> bool:
        if not commands:
            return True
        workspace_path = Path(workspace)
        runnable, blocked = partition_frontend_commands(commands, workspace_path)
        if blocked and required:
            for command in blocked:
                self._record_event(
                    db,
                    run_id,
                    "frontend_scaffold_missing",
                    "tester",
                    "error",
                    FRONTEND_SCAFFOLD_MESSAGE,
                    {"command": command, "required": required},
                )
            return False
        if blocked and not required:
            self._record_optional_frontend_scaffold_skips(db, run_id, blocked)
        commands = runnable
        if not commands:
            return not required
        started_event = f"{event_prefix}_started"
        result_event = f"{event_prefix}_result"
        rejected_event = f"{event_prefix}_rejected"
        all_passed = True
        executed = 0
        for command in commands:
            try:
                validate_command(command)
            except CommandRejectedError as exc:
                self._record_event(
                    db,
                    run_id,
                    rejected_event,
                    "tester",
                    "warning",
                    str(exc),
                    {"required": required},
                )
                self._emit(run_id, rejected_event, "tester", str(exc))
                if required:
                    all_passed = False
                continue

            self._record_event(db, run_id, started_event, "tester", "info", command, {"required": required})
            self._emit(run_id, started_event, "tester", command, {"required": required})
            try:
                code, stdout, stderr = run_command(command, workspace)
                passed = code == 0
                if required:
                    executed += 1
                    all_passed = all_passed and passed
                result_payload = {
                    "stdout": stdout[:2000],
                    "stderr": stderr[:2000],
                    "required": required,
                    "command": command,
                    "exit_code": code,
                }
                self._record_event(
                    db,
                    run_id,
                    result_event,
                    "tester",
                    "info" if passed else "error",
                    f"exit={code}",
                    result_payload,
                )
                self._emit(
                    run_id,
                    result_event,
                    "tester",
                    f"exit={code}",
                    result_payload,
                    severity="info" if passed else "error",
                )
                if event_prefix == "validation":
                    if passed:
                        self._emit(
                            run_id,
                            "validation_passed",
                            "tester",
                            f"exit={code}",
                            result_payload,
                        )
                    elif required:
                        self._emit(
                            run_id,
                            "validation_rejected",
                            "tester",
                            f"exit={code}",
                            result_payload,
                            severity="error",
                        )
            except Exception as exc:
                if required:
                    all_passed = False
                self._record_event(
                    db,
                    run_id,
                    rejected_event,
                    "tester",
                    "error",
                    str(exc),
                    {"required": required},
                )
                self._emit(
                    run_id,
                    rejected_event,
                    "tester",
                    str(exc),
                    {"required": required},
                    severity="error",
                )
        if required and executed == 0:
            return False
        return all_passed

        persist_run_truth(db, run_id)
        return True

    def _auto_pass_tester_for_noop_coder(
        self,
        db: Session,
        run_id: str,
        workspace: Path,
        source_root: Path,
    ) -> bool:
        architect = self._latest_artifact(db, run_id, "architect") or {}
        test_paths = self._blueprint_test_paths(self._blueprint_paths(architect))
        if test_paths and not self._blueprint_tests_pass(workspace, test_paths, source_root=source_root):
            run = db.get(RunModel, run_id)
            if run:
                run.status = RunStatus.BLOCKED.value
                run.error_message = "Blueprint tests failed for no-change coder run"
                db.commit()
            self._record_event(
                db,
                run_id,
                "validation_rejected",
                "tester",
                "error",
                "Blueprint tests failed for no-change coder run",
                {"test_paths": test_paths},
            )
            self._emit(
                run_id,
                "validation_rejected",
                "tester",
                "Blueprint tests failed for no-change coder run",
                {"test_paths": test_paths},
                severity="error",
            )
            self._emit(run_id, "run_blocked", "tester", "Blueprint tests failed for no-change coder run")
            return False
        summary = (
            "Auto-passed: coder made no changes"
            + (" and blueprint tests pass." if test_paths else ".")
        )
        self._save_artifact(
            db,
            run_id,
            "test_plan",
            {
                "passed": True,
                "summary": summary,
                "dry_run_steps": [],
                "visual_checks": [],
                "commands": [],
                "notes": ["Tester validation skipped because coder produced no file changes."],
            },
        )
        self._record_event(db, run_id, "tester_validation_skipped", "tester", "info", summary, {})
        self._emit(run_id, "tester_validation_skipped", "tester", summary, {})
        persist_run_truth(db, run_id)
        return True

    def _stage_tester(self, db: Session, run_id: str, context: str, workspace):
        run = db.get(RunModel, run_id)
        project = ProjectService(db).get(run.project_id) if run else None
        source_root = Path(project.source_repo_spec) if project else Path(workspace)
        if self._coder_noop_completed(db, run_id):
            return self._auto_pass_tester_for_noop_coder(db, run_id, Path(workspace), source_root)
        task_kind = run.task_kind if run else None
        profiles_json = str(ConfigService(db).get_all().get("validation_profiles_json", "{}"))
        profile = run.task.validation_profile if run and run.task else "python"
        changed_files = self._latest_changed_files(db, run_id, workspace)
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
        dry_run_commands: list[str] = []

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
                    "dry_run_steps": [],
                    "visual_checks": [],
                    "commands": [{"command": command, "description": "Validation profile command"} for command in profile_commands],
                    "notes": ["Tester LLM planning skipped for validation-only task."],
                },
            )
        else:
            provider = ProviderRegistry.get().resolve_stage(PipelineStage.TESTER)
            self._log_provider(db, run_id, "tester", provider)
            agent = self._make_stage_agent(TesterAgent, provider, self._build_stage_tool_runtime(db, run_id, "tester"))
            output = agent.test_plan(context)
            self._record_stage_output(output)
            if self._tester_requires_visual_plan(db, run_id, changed_files):
                skip_reason = (output.visual_checks_skip_reason or "").strip()
                if not output.visual_checks and not skip_reason:
                    run = db.get(RunModel, run_id)
                    if not run:
                        return False
                    run.status = RunStatus.BLOCKED.value
                    run.error_message = (
                        "Frontend/UI work requires visual_checks[] or visual_checks_skip_reason"
                    )
                    db.commit()
                    self._record_event(
                        db,
                        run_id,
                        "visual_checks_missing",
                        "tester",
                        "error",
                        run.error_message,
                        {"changed_files": changed_files},
                    )
                    self._emit(run_id, "run_blocked", "tester", run.error_message)
                    return False
                if skip_reason and not output.visual_checks:
                    self._record_event(
                        db,
                        run_id,
                        "visual_checks_skipped",
                        "tester",
                        "info",
                        skip_reason,
                        {"changed_files": changed_files},
                    )
                    self._emit(run_id, "visual_checks_skipped", "tester", skip_reason)
            self._save_artifact(db, run_id, "test_plan", output.model_dump())
            llm_commands = [cmd.command for cmd in output.commands]
            dry_run_commands = normalize_tester_dry_run_commands(
                [cmd.command for cmd in output.dry_run_steps],
                changed_files,
                workspace,
            )
            for check in output.visual_checks:
                payload = check.model_dump()
                self._record_event(
                    db,
                    run_id,
                    "visual_check_required",
                    "tester",
                    "info",
                    check.description,
                    payload,
                )
                self._emit(run_id, "visual_check_required", "tester", check.description, payload)

        if any(is_frontend_code_path(path) for path in changed_files) and not dry_run_commands:
            dry_run_commands = normalize_tester_dry_run_commands([], changed_files, workspace)
        test_plan_for_gate = self._latest_artifact(db, run_id, "test_plan") or {}
        visual_skip_reason = str(test_plan_for_gate.get("visual_checks_skip_reason") or "").strip()
        if self._tester_requires_visual_plan(db, run_id, changed_files) and not visual_skip_reason:
            gate_changed = (
                changed_files
                if any(path.startswith("frontend/") for path in changed_files)
                else ["frontend/src/workbench/builtins.tsx"]
            )
            dry_run_commands = normalize_tester_dry_run_commands(
                dry_run_commands, gate_changed, workspace
            )

        workspace_path = Path(workspace)
        dry_run_runnable, dry_run_blocked = partition_frontend_commands(dry_run_commands, workspace_path)
        if dry_run_blocked:
            return self._block_frontend_scaffold(db, run_id, dry_run_blocked)

        dry_run_passed = self._execute_tester_command_batch(
            db,
            run_id,
            workspace,
            dry_run_runnable,
            event_prefix="dry_run",
            required=True,
        )
        if not dry_run_passed:
            run = db.get(RunModel, run_id)
            if not run:
                return False
            if run.error_message == FRONTEND_SCAFFOLD_MESSAGE:
                return False
            run.status = RunStatus.BLOCKED.value
            run.error_message = "Dry-run verification failed"
            db.commit()
            self._emit(run_id, "run_blocked", "tester", "Dry-run verification failed")
            return False

        required_commands: list[str] = []
        optional_commands: list[str] = []
        seen_required: set[str] = set()
        seen_optional: set[str] = set()
        frontend_build_required = any(is_frontend_code_path(path) for path in changed_files)
        if frontend_build_required:
            profile_commands = canonical_frontend_required_commands(
                profile_commands, changed_files, workspace_path
            )
        for command in profile_commands:
            if command not in seen_required:
                seen_required.add(command)
                required_commands.append(command)
        for command in llm_commands:
            if command in seen_required or command in seen_optional:
                continue
            seen_optional.add(command)
            optional_commands.append(command)

        required_runnable, required_blocked = partition_frontend_commands(required_commands, workspace_path)
        optional_runnable, optional_blocked = partition_frontend_commands(optional_commands, workspace_path)
        if required_blocked:
            return self._block_frontend_scaffold(db, run_id, required_blocked)
        if optional_blocked:
            self._record_optional_frontend_scaffold_skips(db, run_id, optional_blocked)

        required_passed = self._execute_tester_command_batch(
            db,
            run_id,
            workspace,
            required_runnable,
            event_prefix="validation",
            required=True,
        )
        if required_passed:
            for command in optional_runnable:
                self._execute_tester_command_batch(
                    db,
                    run_id,
                    workspace,
                    [command],
                    event_prefix="validation",
                    required=False,
                )

        if required_commands and not required_runnable:
            required_passed = False
            self._record_event(
                db,
                run_id,
                "validation_rejected",
                "tester",
                "error",
                "No required validation commands could be executed",
            )
            self._emit(
                run_id,
                "validation_rejected",
                "tester",
                "No required validation commands could be executed",
                severity="error",
            )

        if not required_passed:
            run = db.get(RunModel, run_id)
            self._record_pipeline_block(
                db,
                run_id,
                block_type="validation_failure",
                stage="tester",
                source="validation_profile",
                message="Validation failed",
                guidance="Fix failing validation profile commands before retrying; check stderr from validation_result events.",
                target_stages=["coder", "tester"],
            )
            run = db.get(RunModel, run_id)
            if not run:
                return False
            run.status = RunStatus.BLOCKED.value
            run.error_message = "Validation failed"
            db.commit()
            self._emit(run_id, "run_blocked", "tester", "Validation failed")
            return False

        test_plan = self._latest_artifact(db, run_id, "test_plan") or {}
        visual_checks = list(test_plan.get("visual_checks") or [])
        skip_reason = str(test_plan.get("visual_checks_skip_reason") or "").strip()
        needs_visual = (
            bool(visual_checks)
            or (
                not skip_reason
                and (
                    integration_requires_visual_evidence(changed_files)
                    or any(is_frontend_code_path(path) for path in changed_files)
                )
            )
        )
        if needs_visual:
            run = db.get(RunModel, run_id)
            project_id = run.project_id if run else ""
            if not visual_checks and not skip_reason:
                visual_checks = build_default_visual_checks(workspace, changed_files)
            if visual_checks:
                self._emit(
                    run_id,
                    "browser_visual_check_started",
                    "tester",
                    "Starting IDE browser visual verification",
                    {"checks": len(visual_checks)},
                )
            evidence = execute_visual_checks(
                db,
                run_id,
                workspace,
                visual_checks,
                project_id=project_id,
            )
            if not evidence.get("passed"):
                run = db.get(RunModel, run_id)
                if not run:
                    return False
                run.status = RunStatus.BLOCKED.value
                if evidence.get("browser_client_required"):
                    run.error_message = "Open AI Copilot IDE with this project loaded to complete visual verification"
                    self._record_event(
                        db,
                        run_id,
                        "browser_client_required",
                        "tester",
                        "warn",
                        run.error_message,
                        evidence,
                    )
                    self._emit(run_id, "browser_client_required", "tester", run.error_message, evidence)
                else:
                    run.error_message = "Visual evidence capture failed"
                    self._record_event(
                        db,
                        run_id,
                        "visual_evidence_failed",
                        "tester",
                        "error",
                        run.error_message,
                        evidence,
                    )
                    self._emit(run_id, "visual_evidence_failed", "tester", run.error_message, evidence)
                db.commit()
                self._emit(run_id, "run_blocked", "tester", run.error_message)
                return False
            self._record_event(
                db,
                run_id,
                "visual_evidence_passed",
                "tester",
                "info",
                "Visual evidence captured",
                evidence,
            )
            self._emit(run_id, "browser_visual_check_passed", "tester", "Visual evidence captured", evidence)
            self._emit(run_id, "visual_evidence_passed", "tester", "Visual evidence captured", evidence)
        persist_run_truth(db, run_id)
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
    service = OrchestrationService()
    runs = list(
        db.query(RunModel)
        .filter(RunModel.status.in_([RunStatus.RUNNING.value, RunStatus.PENDING.value]))
        .all()
    )
    active_runs: list[RunModel] = []
    for run in runs:
        if service._finalize_stale_inflight_run(db, run):
            continue
        active_runs.append(run)
    active_runs.sort(
        key=lambda run: (
            _RESUME_STAGE_PRIORITY.get(str(run.current_stage or ""), 0),
            run.updated_at,
            run.created_at,
        ),
        reverse=True,
    )
    resumed_ids: list[str] = []
    selected = active_runs if limit is None else active_runs[: max(0, int(limit))]
    for run in selected:
        run_engine.enqueue(run.id)
        resumed_ids.append(run.id)
    return resumed_ids


def _ensure_project_setup_scheduled(db: Session, project, *, task_kind: str) -> None:
    """Enqueue a setup run when the project has no completed setup yet."""
    if task_kind == "setup":
        return
    from app.services.setup_run_service import has_active_setup_run, has_completed_setup, trigger_setup_run

    repo_mode = str(getattr(project, "repo_mode", None) or "").strip()
    needs_setup = not has_completed_setup(db, project.id) and not has_active_setup_run(db, project.id)
    if not repo_mode:
        needs_setup = True
    if needs_setup:
        trigger_setup_run(db, project.id)


def create_task_and_run(db: Session, data: dict):
    svc = ProjectService(db)
    project = svc.get(data["project_id"])
    profile = data.get("validation_profile") or project.validation_profile
    task_kind = data.get("task_kind") or infer_task_kind(data["description"])
    _ensure_project_setup_scheduled(db, project, task_kind=task_kind)
    allow_web_search = infer_allow_web_search(
        data["description"],
        bool(data["allow_web_search"]) if "allow_web_search" in data else None,
    )
    task = TaskModel(
        project_id=project.id,
        description=data["description"],
        validation_profile=profile,
        task_kind=task_kind,
        use_scout=bool(data.get("use_scout", False)),
        allow_web_search=allow_web_search,
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
        chat_session_id=data.get("session_id"),
        allow_web_search=allow_web_search,
        deliverable_kind=infer_deliverable_kind(data["description"], task_kind),
        expected_targets_json=json.dumps(
            expected_targets_for_kind(infer_deliverable_kind(data["description"], task_kind))
        ),
        expected_validation_family=expected_validation_family(profile, infer_deliverable_kind(data["description"], task_kind)),
    )
    db.add(run)
    db.commit()
    db.refresh(task)
    db.refresh(run)
    persist_run_truth(db, run.id)
    run_engine.enqueue(run.id)
    return task, run


run_engine = orchestration_service = OrchestrationService()
