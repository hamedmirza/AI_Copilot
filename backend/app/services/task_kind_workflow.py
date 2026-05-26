"""Per-task-kind pipeline stage graphs and transition gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from sqlalchemy.orm import Session

from app.core.enums import PipelineStage, RepoMode
from app.services.run_truth_service import infer_deliverable_kind, should_run_ui_designer

if TYPE_CHECKING:
    from app.services.file_service import FileService
    from app.services.orchestration_service import OrchestrationService
    from app.services.reconnaissance_service import ReconSnapshot
    from app.db.models import RunModel


@dataclass(frozen=True)
class WorkflowContext:
    task_kind: str
    repo_mode: str
    deliverable_kind: str | None
    description: str
    has_app_design: bool


@dataclass(frozen=True)
class RunContext:
    db: Session
    run_id: str
    run: RunModel
    snapshot: ReconSnapshot
    fs: FileService
    workspace_path: str
    source_path: str


@dataclass(frozen=True)
class StageSpec:
    stage: PipelineStage
    required_artifacts: tuple[str, ...] = ()
    skip_if: Callable[[WorkflowContext], bool] | None = None


def _skip_ui_designer(ctx: WorkflowContext) -> bool:
    return not should_run_ui_designer(ctx.description, ctx.task_kind, ctx.deliverable_kind)


def _implementation_stages(*, include_app_designer: bool) -> tuple[StageSpec, ...]:
    specs: list[StageSpec] = []
    if include_app_designer:
        specs.append(StageSpec(PipelineStage.APP_DESIGNER))
    specs.extend(
        [
            StageSpec(PipelineStage.PLANNER),
            StageSpec(PipelineStage.ARCHITECT, required_artifacts=("plan",)),
            StageSpec(
                PipelineStage.UI_DESIGNER,
                required_artifacts=("architect",),
                skip_if=_skip_ui_designer,
            ),
            StageSpec(PipelineStage.CODER, required_artifacts=("architect",)),
            StageSpec(PipelineStage.REVIEWER, required_artifacts=("coder",)),
            StageSpec(PipelineStage.TESTER, required_artifacts=("coder",)),
            StageSpec(PipelineStage.DOCUMENTATION, required_artifacts=("coder",)),
        ]
    )
    return tuple(specs)


TASK_KIND_WORKFLOWS: dict[str, tuple[StageSpec, ...]] = {
    "setup": (
        StageSpec(PipelineStage.PLANNER),
        StageSpec(PipelineStage.ARCHITECT, required_artifacts=("plan",)),
        StageSpec(PipelineStage.CODER, required_artifacts=("architect",)),
    ),
    "implementation": _implementation_stages(include_app_designer=False),
    "mixed": _implementation_stages(include_app_designer=False),
    "analysis": (
        StageSpec(PipelineStage.PLANNER),
        StageSpec(PipelineStage.ARCHITECT, required_artifacts=("plan",)),
        StageSpec(PipelineStage.CODER, required_artifacts=("architect",)),
        StageSpec(PipelineStage.REVIEWER, required_artifacts=("coder",)),
        StageSpec(PipelineStage.DOCUMENTATION, required_artifacts=("coder",)),
    ),
    "validation": (
        StageSpec(PipelineStage.PLANNER),
        StageSpec(PipelineStage.TESTER, required_artifacts=("plan",)),
    ),
    "debug": (
        StageSpec(PipelineStage.PLANNER),
        StageSpec(PipelineStage.ARCHITECT, required_artifacts=("plan",)),
        StageSpec(PipelineStage.CODER, required_artifacts=("architect",)),
        StageSpec(PipelineStage.REVIEWER, required_artifacts=("coder",)),
        StageSpec(PipelineStage.TESTER, required_artifacts=("coder",)),
    ),
    "playbook": (
        StageSpec(PipelineStage.PLANNER),
        StageSpec(PipelineStage.PLAYBOOK_SUPERVISOR, required_artifacts=("plan",)),
    ),
}


def workflow_for_task_kind(task_kind: str | None) -> tuple[StageSpec, ...]:
    kind = (task_kind or "implementation").strip() or "implementation"
    return TASK_KIND_WORKFLOWS.get(kind, TASK_KIND_WORKFLOWS["implementation"])


def workflow_context_for_run(
    run: RunModel,
    *,
    repo_mode: str,
    has_app_design: bool,
    description: str,
) -> WorkflowContext:
    return WorkflowContext(
        task_kind=run.task_kind or "implementation",
        repo_mode=repo_mode,
        deliverable_kind=run.deliverable_kind,
        description=description,
        has_app_design=has_app_design,
    )


def workflow_stage_specs(ctx: WorkflowContext) -> tuple[StageSpec, ...]:
    specs = list(workflow_for_task_kind(ctx.task_kind))
    if (
        ctx.task_kind in {"implementation", "mixed"}
        and ctx.repo_mode == RepoMode.GREENFIELD.value
        and not ctx.has_app_design
    ):
        specs.insert(0, StageSpec(PipelineStage.APP_DESIGNER))
    return tuple(specs)


def missing_required_artifacts(
    spec: StageSpec,
    *,
    has_artifact: Callable[[str], bool],
) -> list[str]:
    return [name for name in spec.required_artifacts if not has_artifact(name)]


def resolve_workflow_stage_values(ctx: WorkflowContext) -> list[str]:
    stages: list[str] = []
    for spec in workflow_stage_specs(ctx):
        if spec.skip_if and spec.skip_if(ctx):
            continue
        stages.append(spec.stage.value)
    return stages


def workflow_stage_values(
    task_kind: str | None,
    *,
    description: str = "",
    deliverable_kind: str | None = None,
) -> list[str]:
    ctx = WorkflowContext(
        task_kind=(task_kind or "implementation"),
        repo_mode=RepoMode.EXISTING.value,
        deliverable_kind=deliverable_kind or infer_deliverable_kind(description, task_kind),
        description=description,
        has_app_design=True,
    )
    return resolve_workflow_stage_values(ctx)


def skips_deployment_gates(task_kind: str | None) -> bool:
    return (task_kind or "").strip().lower() in {"playbook", "validation"}


def check_stage_gate(
    db: Session,
    run_id: str,
    run: RunModel,
    spec: StageSpec,
    *,
    latest_artifact: Callable[[Session, str, str], dict | None],
    workflow_ctx: WorkflowContext | None = None,
) -> str | None:
    """Return why_blocked message when gate fails, else None."""
    if spec.skip_if and workflow_ctx and spec.skip_if(workflow_ctx):
        return None
    for artifact_type in spec.required_artifacts:
        if not latest_artifact(db, run_id, artifact_type):
            return f"Missing required artifact '{artifact_type}' before stage '{spec.stage.value}'"
    if (run.task_kind or "") == "debug" and spec.stage == PipelineStage.ARCHITECT:
        plan = latest_artifact(db, run_id, "plan") or {}
        if not str(plan.get("hypothesis") or "").strip():
            return "Debug tasks require planner output with non-empty hypothesis"
        repro = plan.get("repro_steps") or []
        if isinstance(repro, list):
            if not [str(step).strip() for step in repro if str(step).strip()]:
                return "Debug tasks require planner output with non-empty repro_steps"
        elif not str(repro).strip():
            return "Debug tasks require planner output with non-empty repro_steps"
    if (run.task_kind or "") == "analysis" and spec.stage == PipelineStage.CODER:
        architect = latest_artifact(db, run_id, "architect") or {}
        paths = [
            str(item.get("path") or "")
            for item in (architect.get("file_changes") or [])
            if isinstance(item, dict)
        ]
        if not any(p.startswith(".ai-copilot/reports/") for p in paths):
            return "Analysis architect blueprint must include a .ai-copilot/reports/ path"
    return None


def build_pipeline_stages(
    svc: OrchestrationService,
    ctx: RunContext,
) -> list[tuple[PipelineStage, Callable[[str], object]]]:
    """Materialize stage handlers for the run's task_kind workflow."""
    from pathlib import Path

    db = ctx.db
    run_id = ctx.run_id
    run = ctx.run
    fs = ctx.fs
    workspace = Path(ctx.workspace_path)
    source = Path(ctx.source_path)
    task = run.task
    description = task.description if task else ""
    wf_ctx = workflow_context_for_run(
        run,
        repo_mode=ctx.snapshot.repo_mode,
        has_app_design=bool(svc._latest_artifact(db, run_id, "app_design")),
        description=description,
    )
    stages: list[tuple[PipelineStage, Callable[[str], object]]] = []
    for spec in workflow_stage_specs(wf_ctx):
        if spec.skip_if and spec.skip_if(wf_ctx):
            continue
        stage = spec.stage
        if stage == PipelineStage.APP_DESIGNER:
            stages.append((stage, lambda c, s=svc, d=db, r=run_id: s._stage_app_designer(d, r, c)))
        elif stage == PipelineStage.PLANNER:
            stages.append((stage, lambda c, s=svc, d=db, r=run_id, f=fs: s._stage_planner(d, r, c, f)))
        elif stage == PipelineStage.ARCHITECT:
            stages.append((stage, lambda c, s=svc, d=db, r=run_id: s._stage_architect(d, r, c)))
        elif stage == PipelineStage.UI_DESIGNER:
            stages.append((stage, lambda c, s=svc, d=db, r=run_id: s._stage_ui(d, r, c)))
        elif stage == PipelineStage.CODER:
            stages.append((stage, lambda c, s=svc, d=db, r=run_id, f=fs: s._stage_coder(d, r, c, f)))
        elif stage == PipelineStage.REVIEWER:
            stages.append(
                (
                    stage,
                    lambda c, s=svc, d=db, r=run_id, f=fs, w=workspace, src=source: s._stage_reviewer_loop(
                        d, r, c, f, w, src
                    ),
                )
            )
        elif stage == PipelineStage.TESTER:
            stages.append(
                (stage, lambda c, s=svc, d=db, r=run_id, w=workspace: s._stage_tester(d, r, c, w))
            )
        elif stage == PipelineStage.DOCUMENTATION:
            stages.append(
                (stage, lambda c, s=svc, d=db, r=run_id, f=fs: s._stage_documentation(d, r, c, f))
            )
        elif stage == PipelineStage.PLAYBOOK_SUPERVISOR:
            stages.append(
                (stage, lambda c, s=svc, d=db, r=run_id: s._stage_playbook_supervisor(d, r, c))
            )
    return stages
