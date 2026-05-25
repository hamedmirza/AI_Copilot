"""Post-deploy supervisor: plan reconciliation and documentation updates."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.agents import SupervisorAgent
from app.core.enums import PipelineStage
from app.db.models import ArtifactModel, RunModel
from app.providers.registry import ProviderRegistry
from app.services.file_service import FileService
from app.services.project_service import ProjectService


def _load_artifact(db: Session, run_id: str, artifact_type: str) -> dict | None:
    row = (
        db.query(ArtifactModel)
        .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == artifact_type)
        .order_by(ArtifactModel.id.desc())
        .first()
    )
    if not row:
        return None
    try:
        payload = json.loads(row.content_json)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def build_post_deploy_context(
    db: Session,
    run: RunModel,
    promoted_paths: list[str],
) -> str:
    plan = _load_artifact(db, run.id, "plan") or {}
    architect = _load_artifact(db, run.id, "architect") or {}
    coder = _load_artifact(db, run.id, "coder") or {}
    test_plan = _load_artifact(db, run.id, "test_plan") or {}
    ui_design = _load_artifact(db, run.id, "ui_design") or {}

    path_lines = [f"- {path}" for path in promoted_paths] if promoted_paths else ["- (none)"]
    sections = [
        "Post-deployment supervisor attestation.",
        f"Task kind: {run.task_kind or 'implementation'}.",
        f"Promoted paths ({len(promoted_paths)}):",
        *path_lines,
        "",
        "Planner artifact:",
        json.dumps(plan, indent=2),
        "",
        "Architect artifact:",
        json.dumps(architect, indent=2),
    ]
    if ui_design:
        sections.extend(["", "UI design artifact:", json.dumps(ui_design, indent=2)])
    sections.extend(
        [
            "",
            "Coder artifact:",
            json.dumps(coder, indent=2),
            "",
            "Tester artifact (dry-run, visual, validation):",
            json.dumps(test_plan, indent=2),
            "",
            "Reconcile plan acceptance criteria against promoted files and emit doc_updates for "
            ".ai-copilot/designs/, .ai-copilot/plans/, .ai-copilot/reports/, and docs/ as needed.",
        ]
    )
    return "\n".join(sections)


def apply_doc_updates(fs: FileService, doc_updates: list[dict]) -> list[str]:
    written: list[str] = []
    for item in doc_updates:
        path = str(item.get("path") or "").strip()
        content = str(item.get("content") or "")
        if not path:
            continue
        fs.write_file(path, content)
        written.append(path)
    return written


def run_pre_deploy_supervisor(
    db: Session,
    run_id: str,
    workspace_paths: list[str],
    workspace: Path,
) -> dict | None:
    """Attest plan vs workspace before operator approval (no promotion yet)."""
    if not workspace_paths:
        return None

    run = db.get(RunModel, run_id)
    if not run:
        return None

    project = ProjectService(db).get(run.project_id)
    context = build_post_deploy_context(db, run, workspace_paths)
    provider = ProviderRegistry.get().resolve_stage(PipelineStage.SUPERVISOR)
    agent = SupervisorAgent(provider)
    output = agent.attest(context)

    fs = FileService(workspace, project.protected_files)
    written_paths = apply_doc_updates(fs, [item.model_dump() for item in output.doc_updates])

    payload = output.model_dump()
    payload["written_paths"] = written_paths
    db.add(
        ArtifactModel(
            run_id=run_id,
            artifact_type="pre_deploy_supervisor",
            content_json=json.dumps(payload),
        )
    )
    db.commit()
    return payload


def run_post_deploy_supervisor(
    db: Session,
    run_id: str,
    promoted_paths: list[str],
) -> dict | None:
    """Run supervisor after promotion; apply doc updates to the project source repo."""
    if not promoted_paths:
        return None

    run = db.get(RunModel, run_id)
    if not run:
        return None

    project = ProjectService(db).get(run.project_id)
    source = Path(project.source_repo_spec)
    context = build_post_deploy_context(db, run, promoted_paths)
    provider = ProviderRegistry.get().resolve_stage(PipelineStage.SUPERVISOR)
    agent = SupervisorAgent(provider)
    output = agent.attest(context)

    fs = FileService(source, project.protected_files)
    written_paths = apply_doc_updates(fs, [item.model_dump() for item in output.doc_updates])

    payload = output.model_dump()
    payload["written_paths"] = written_paths
    db.add(
        ArtifactModel(
            run_id=run_id,
            artifact_type="supervisor",
            content_json=json.dumps(payload),
        )
    )
    db.commit()
    return payload


def run_pre_deploy_supervisor(
    db: Session,
    run_id: str,
    changed_files: list[str],
    workspace: Path,
) -> dict:
    """Deterministic pre-deploy attestation before awaiting_approval."""
    from app.services.acceptance_criteria_enforcer import evaluate_acceptance_criteria
    from app.services.contract_guard import contract_guard_issues
    from app.services.integration_guard import integration_guard_issues
    from app.services.visual_evidence_service import visual_evidence_passed

    run = db.get(RunModel, run_id)
    plan = _load_artifact(db, run_id, "plan") or {}
    criteria_lines: list[str] = []
    for step in plan.get("steps") or []:
        if isinstance(step, dict):
            for c in step.get("acceptance_criteria") or []:
                if str(c or "").strip():
                    criteria_lines.append(str(c).strip())

    integration_issues = integration_guard_issues(workspace, changed_files=changed_files)
    contract_issues = contract_guard_issues(workspace, changed_files)
    integration_ok = not any(i.get("severity") == "critical" for i in integration_issues)
    contract_ok = not any(i.get("severity") == "critical" for i in contract_issues)
    frontend_work = any(p.replace("\\", "/").startswith("frontend/") for p in changed_files)
    visual_ok = visual_evidence_passed(db, run_id) if frontend_work else True

    gate_results = {
        "integration_guard": integration_ok,
        "contract_guard": contract_ok,
        "visual_evidence": visual_ok,
        "test_plan": True,
        "pre_deploy_supervisor": True,
    }
    criteria_failures = evaluate_acceptance_criteria(criteria_lines, gate_results=gate_results)

    plan_gaps = []
    if not integration_ok:
        for issue in integration_issues:
            if issue.get("severity") == "critical":
                plan_gaps.append({"step_id": "integration", "message": f"critical: {issue.get('message')}"})
    if not contract_ok:
        for issue in contract_issues:
            if issue.get("severity") == "critical":
                plan_gaps.append({"step_id": "contract", "message": f"critical: {issue.get('message')}"})
    if not visual_ok and any(p.startswith("frontend/") for p in changed_files):
        plan_gaps.append({"step_id": "visual", "message": "critical: visual_evidence missing or failed"})
    for failure in criteria_failures:
        plan_gaps.append({"step_id": "acceptance", "message": failure.get("message", "critical: criterion failed")})

    approved = not plan_gaps
    summary = "Pre-deploy gates satisfied" if approved else f"{len(plan_gaps)} critical gap(s) before approval"

    llm_gaps: list[dict] = []
    if approved:
        try:
            context = build_post_deploy_context(db, run, changed_files)
            provider = ProviderRegistry.get().resolve_stage(PipelineStage.SUPERVISOR)
            agent = SupervisorAgent(provider)
            output = agent.attest(context)
            if not output.approved:
                approved = False
                for gap in output.plan_gaps:
                    plan_gaps.append(gap.model_dump())
            llm_gaps = [g.model_dump() for g in output.plan_gaps]
            summary = output.summary or summary
        except Exception:
            pass

    payload = {
        "approved": approved,
        "summary": summary,
        "plan_gaps": plan_gaps,
        "deterministic": {
            "integration_ok": integration_ok,
            "contract_ok": contract_ok,
            "visual_ok": visual_ok,
            "criteria_failures": criteria_failures,
        },
        "llm_plan_gaps": llm_gaps,
    }
    db.add(
        ArtifactModel(
            run_id=run_id,
            artifact_type="pre_deploy_supervisor",
            content_json=json.dumps(payload),
        )
    )
    db.commit()
    return payload
