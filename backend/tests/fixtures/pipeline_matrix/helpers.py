"""Helpers for pipeline matrix E2E runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import RunStatus
from app.db.models import AppConfigModel, ProjectModel, RunModel
from app.db.session import SessionLocal
from app.providers.fake import FakeProvider
from app.providers.registry import ProviderRegistry
from app.services.config_service import ConfigService
from app.services.orchestration_service import create_task_and_run, run_engine
from app.services.setup_run_service import has_completed_setup


@dataclass(frozen=True)
class MatrixRunResult:
    run_id: str
    terminal_status: str
    blocking_event: str | None


def resolve_clarification_if_pending(
    db: Session,
    run_id: str,
    *,
    answer: str = "frontend",
) -> bool:
    run = db.get(RunModel, run_id)
    if not run or run.status != RunStatus.AWAITING_CLARIFICATION.value:
        return False
    ctx = dict(run.clarification_context or {})
    ctx["answer"] = answer
    pending = str(ctx.get("pending_gate") or "").strip()
    if pending:
        resolved = list(ctx.get("resolved_gates") or [])
        if pending not in resolved:
            resolved.append(pending)
        ctx["resolved_gates"] = resolved
        ctx.pop("pending_gate", None)
    run.clarification_context_json = json.dumps(ctx)
    run.status = RunStatus.RUNNING.value
    run.clarification_question = None
    run.clarification_stage = None
    db.commit()
    run_engine.enqueue(run_id)
    return True


def _ensure_setup_complete(db: Session, project_id: str) -> None:
    if has_completed_setup(db, project_id):
        return
    from app.core.enums import PipelineStage
    from app.db.models import RunModel, TaskModel

    task = TaskModel(
        project_id=project_id,
        description="Matrix setup seed",
        validation_profile="python",
        task_kind="setup",
    )
    db.add(task)
    db.flush()
    run = RunModel(
        project_id=project_id,
        task_id=task.id,
        status=RunStatus.COMPLETED.value,
        current_stage=PipelineStage.CODER.value,
        task_kind="setup",
    )
    db.add(run)
    db.commit()


def configure_matrix_settings(db: Session) -> None:
    updates = {
        "max_review_retries": "1",
        "auto_assume_clarifications": "true",
        "require_supervisor_llm": "false",
        "stop_on_first_failure": "true",
        "validation_profiles_json": json.dumps(
            {
                "python": ["cd backend && .venv/bin/pytest -q"],
                "fullstack": [
                    "cd backend && .venv/bin/pytest -q",
                    "npm --prefix frontend run build",
                ],
            }
        ),
    }
    for key, value in updates.items():
        row = db.query(AppConfigModel).filter(AppConfigModel.key == key).first()
        if row:
            row.value = value
        else:
            db.add(AppConfigModel(key=key, value=value))
    db.commit()
    ConfigService(db).reload_registry()


class MatrixFakeProvider(FakeProvider):
    """FakeProvider tuned for matrix: fast reviewer approval and path-aware architect."""

    def __init__(self, *, architect_paths: list[str], playbook_approved: bool = True, debug_plan: bool = False) -> None:
        super().__init__(
            default_response='{"summary":"matrix","steps":[{"step_id":"1","title":"Step","description":"Work","acceptance_criteria":["done"]}],"risks":[]}'
        )
        self._architect_paths = architect_paths
        self._playbook_approved = playbook_approved
        self._debug_plan = debug_plan
        self._review_attempt = 2

    def _planner_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "summary": "Matrix plan",
            "steps": [
                {
                    "step_id": "1",
                    "title": "Execute",
                    "description": "Complete matrix scenario",
                    "acceptance_criteria": ["Scenario completes"],
                }
            ],
            "risks": [],
        }
        if self._debug_plan:
            payload["hypothesis"] = "Broken assertion in test"
            payload["repro_steps"] = "Run pytest on broken test module"
        return payload

    def _default_payload_for_schema(self, schema_name: str, user_prompt: str) -> str | None:
        if schema_name == "PlannerOutput":
            return json.dumps(self._planner_payload())
        if schema_name == "ArchitectOutput":
            changes = [
                {"path": p, "action": "modify", "rationale": "matrix"}
                for p in self._architect_paths
            ] or [{"path": "backend/app/demo.py", "action": "create", "rationale": "matrix"}]
            return json.dumps(
                {
                    "overview": "Matrix architect",
                    "modules": ["core"],
                    "file_changes": changes,
                    "dependencies": [],
                }
            )
        if schema_name == "PlaybookSupervisorOutput":
            return json.dumps(
                {
                    "approved": self._playbook_approved,
                    "summary": "Playbook reviewed",
                    "safety_concerns": [] if self._playbook_approved else ["Missing rollback"],
                    "required_changes": [] if self._playbook_approved else ["Add rollback steps"],
                }
            )
        if schema_name == "ReviewerOutput":
            return json.dumps(
                {
                    "approved": True,
                    "summary": "Matrix review approved",
                    "issues": [],
                    "suggestions": [],
                }
            )
        if schema_name == "TesterOutput":
            lower = user_prompt.lower()
            visual = []
            if "frontend" in lower or "app.tsx" in lower:
                visual = [
                    {
                        "url": "http://localhost:5177/",
                        "description": "Smoke check dashboard",
                        "expected": "Page loads",
                        "steps": [{"action": "open", "selector": "body"}],
                    }
                ]
            return json.dumps(
                {
                    "passed": True,
                    "summary": "Matrix validation",
                    "dry_run_steps": [],
                    "visual_checks": visual,
                    "visual_checks_skip_reason": None if visual else "No UI surface",
                    "commands": [{"command": "true", "description": "noop"}],
                    "notes": [],
                }
            )
        if schema_name == "CoderOutput":
            file_changes = []
            for path in self._architect_paths or ["backend/app/demo.py"]:
                if path.endswith(".py"):
                    file_changes.append(
                        {
                            "path": path,
                            "line_changes": [
                                {"start_line": 1, "end_line": 1, "new_content": "# matrix\n"}
                            ],
                        }
                    )
                elif path.endswith((".tsx", ".jsx")):
                    file_changes.append(
                        {
                            "path": path,
                            "line_changes": [
                                {
                                    "start_line": 1,
                                    "end_line": 1,
                                    "new_content": "export default function App(){return null}\n",
                                }
                            ],
                        }
                    )
                elif path.endswith(".md"):
                    file_changes.append(
                        {
                            "path": path,
                            "line_changes": [
                                {"start_line": 1, "end_line": 1, "new_content": "# Matrix doc update\n"}
                            ],
                        }
                    )
                else:
                    file_changes.append({"path": path, "full_content": "matrix\n"})
            return json.dumps(
                {
                    "summary": "Matrix coder",
                    "file_changes": file_changes,
                    "requires_operator_approval": False,
                }
            )
        if schema_name == "DocumentationOutput":
            return json.dumps(
                {
                    "summary": "Matrix documentation complete",
                    "changelog_entry": "Matrix documentation",
                    "change_request_status": "implemented",
                    "readme_updated": False,
                    "architecture_notes": "Matrix run",
                }
            )
        if schema_name == "UIDesignerOutput":
            return json.dumps(
                {
                    "layout_description": "Matrix layout",
                    "components": [{"name": "App", "component_type": "page", "props": {}}],
                    "styling_notes": "tailwind",
                    "accessibility_notes": [],
                }
            )
        if schema_name == "AppDesignOutput":
            return json.dumps(
                {
                    "app_summary": "Matrix app",
                    "entities": [],
                    "api_endpoints": [],
                    "stack": {
                        "language": "python",
                        "framework": "fastapi",
                        "database": "sqlite",
                        "auth_method": "token",
                        "ui_framework": "react",
                    },
                    "file_structure": ["frontend/src/App.tsx"],
                    "open_questions": [],
                    "assumptions": [],
                    "clarification_needed": False,
                    "question": "",
                }
            )
        return super()._default_payload_for_schema(schema_name, user_prompt)

    def invoke_json(self, system_prompt: str, user_prompt: str) -> str:
        schema_name = self._schema_name_from_user_prompt(user_prompt) or self._schema_name_from_user_prompt(
            system_prompt
        )
        if not schema_name:
            return super().invoke_json(system_prompt, user_prompt)
        payload = self._default_payload_for_schema(schema_name, user_prompt)
        if payload is not None:
            return payload
        return super().invoke_json(system_prompt, user_prompt)


def blocking_event_for_run(db: Session, run_id: str) -> str | None:
    from app.db.models import RunEventModel

    run = db.get(RunModel, run_id)
    if not run:
        return "run_missing"
    if run.status in {RunStatus.AWAITING_APPROVAL.value, RunStatus.COMPLETED.value}:
        return None
    events = (
        db.query(RunEventModel)
        .filter(RunEventModel.run_id == run_id)
        .order_by(RunEventModel.id.desc())
        .limit(20)
        .all()
    )
    for event in events:
        et = str(event.event_type or "")
        if et in {
            "stage_gate_failed",
            "run_blocked",
            "playbook_supervisor_rejected",
            "frontend_scaffold_missing",
            "visual_checks_missing",
            "run_clarification_requested",
        }:
            return et
    return run.error_message or run.status


def run_matrix_case(
    *,
    repo_path: str,
    description: str,
    task_kind: str,
    validation_profile: str,
    architect_paths: list[str],
    playbook_approved: bool = True,
    debug_plan: bool = False,
    approve_after: bool = False,
    resolve_clarification: bool = True,
    monkeypatch=None,
    setup_patches: bool = True,
) -> MatrixRunResult:
    import app.services.orchestration_service as orch_mod

    run_engine.wait_for_idle(timeout=10.0)
    db = SessionLocal()
    try:
        if setup_patches:
            configure_matrix_settings(db)
            from app.services import setup_run_service

            monkeypatch.setattr(setup_run_service, "has_completed_setup", lambda db, pid: True)
            monkeypatch.setattr(setup_run_service, "has_active_setup_run", lambda db, pid: False)
            monkeypatch.setattr(setup_run_service, "trigger_setup_run", lambda *a, **k: None)
            monkeypatch.setattr(orch_mod.run_engine, "enqueue", lambda run_id: orch_mod.run_engine._execute_run(run_id))
            monkeypatch.setattr(
                "app.services.setup_run_service.run_engine.enqueue",
                lambda run_id: orch_mod.run_engine._execute_run(run_id),
            )
            monkeypatch.setattr(orch_mod, "validate_command", lambda command: None)
            monkeypatch.setattr(orch_mod, "run_command", lambda command, workspace_path: (0, "ok", ""))
            monkeypatch.setattr(
                orch_mod,
                "execute_visual_checks",
                lambda *args, **kwargs: {"passed": True, "checks": [], "summary": "ok"},
            )
            monkeypatch.setattr(orch_mod, "integration_guard_issues", lambda *args, **kwargs: [])
            monkeypatch.setattr(orch_mod, "contract_guard_issues", lambda *args, **kwargs: [])
            monkeypatch.setattr(
                orch_mod.OrchestrationService,
                "_finalize_deployment_gates",
                lambda self, db, run_id, workspace, source_root: True,
            )
            monkeypatch.setattr(
                orch_mod.OrchestrationService,
                "_verify_dependencies",
                lambda self, db, run_id, workspace, source: True,
            )

        project = ProjectModel(
            name=f"Matrix-{task_kind}-{hash(description) % 100000}",
            source_repo_spec=repo_path,
            validation_profile=validation_profile,
            protected_files_json="[]",
            repo_mode="existing",
        )
        db.add(project)
        db.flush()
        _ensure_setup_complete(db, project.id)

        registry = ProviderRegistry.get()
        registry.fake_provider = MatrixFakeProvider(
            architect_paths=architect_paths,
            playbook_approved=playbook_approved,
            debug_plan=debug_plan,
        )
        registry.reload({})

        if setup_patches:
            monkeypatch.setattr(
                orch_mod.OrchestrationService,
                "_build_stage_tool_runtime",
                lambda self, db, run_id, stage: None,
            )

        task, run = create_task_and_run(
            db,
            {
                "project_id": project.id,
                "description": description,
                "validation_profile": validation_profile,
                "task_kind": task_kind,
            },
        )
        run_id = run.id
        db.commit()

        for _ in range(30):
            run_engine.wait_for_idle(timeout=2.0)
            db.expire_all()
            run = db.get(RunModel, run_id)
            if not run:
                break
            if run.status not in {RunStatus.PENDING.value, RunStatus.RUNNING.value}:
                break
            if resolve_clarification and run.status == RunStatus.AWAITING_CLARIFICATION.value:
                resolve_clarification_if_pending(db, run_id, answer="frontend")
                continue

        run = db.get(RunModel, run_id)
        assert run is not None
        if approve_after and run.status == RunStatus.AWAITING_APPROVAL.value:
            run.status = RunStatus.COMPLETED.value
            run.approval_reached = True
            db.commit()
            db.expire_all()
            run = db.get(RunModel, run_id)
            assert run is not None
        return MatrixRunResult(
            run_id=run_id,
            terminal_status=run.status,
            blocking_event=blocking_event_for_run(db, run_id),
        )
    finally:
        db.close()
        run_engine.wait_for_idle(timeout=10.0)
