"""Per-run deployment gate checklist for operator approval."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import ArtifactModel, RunModel
from app.services.acceptance_criteria_enforcer import evaluate_acceptance_criteria
from app.services.contract_guard import contract_guard_issues
from app.services.integration_guard import integration_guard_issues, integration_requires_visual_evidence
from app.services.project_service import ProjectService
from app.services.visual_evidence_service import load_visual_evidence, visual_evidence_passed
from app.services.workspace_changed_files import workspace_changed_files


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
        data = json.loads(row.content_json)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _plan_criteria_lines(plan: dict) -> list[str]:
    lines: list[str] = []
    for step in plan.get("steps") or []:
        if not isinstance(step, dict):
            continue
        for criterion in step.get("acceptance_criteria") or []:
            text = str(criterion or "").strip()
            if text:
                lines.append(text)
    return lines


def _dry_run_passed(db: Session, run_id: str, changed_files: list[str]) -> bool:
    from app.db.models import RunEventModel
    from app.services.change_guard import is_frontend_code_path

    if not any(is_frontend_code_path(p) for p in changed_files):
        test_plan = _load_artifact(db, run_id, "test_plan")
        if test_plan is not None:
            return bool(test_plan.get("passed", True))
    events = (
        db.query(RunEventModel)
        .filter(RunEventModel.run_id == run_id, RunEventModel.event_type == "dry_run_result")
        .all()
    )
    if not events:
        return False
    return all("exit=0" in (event.message or "") for event in events)


def build_deployment_readiness(
    db: Session,
    run_id: str,
    *,
    require_awaiting_approval: bool = True,
) -> dict:
    run = db.get(RunModel, run_id)
    if not run:
        return {"ready": False, "gates": [], "message": "Run not found"}
    from app.services.run_truth_service import persist_run_truth

    truth = persist_run_truth(db, run_id)

    project = ProjectService(db).get(run.project_id)
    source = Path(project.source_repo_spec)
    workspace = Path(run.workspace_path) if run.workspace_path else source
    changed = workspace_changed_files(workspace, source) if workspace.is_dir() else []

    integration_issues = integration_guard_issues(workspace, changed_files=changed)
    integration_critical = [i for i in integration_issues if i.get("severity") == "critical"]
    contract_issues = contract_guard_issues(workspace, changed)
    contract_critical = [i for i in contract_issues if i.get("severity") == "critical"]

    test_plan = _load_artifact(db, run_id, "test_plan") or {}
    if not changed:
        dry_runs_ok = True
    else:
        dry_runs_ok = _dry_run_passed(db, run_id, changed)

    needs_visual = integration_requires_visual_evidence(changed) or any(
        p.startswith("frontend/") for p in changed
    )
    visual_data = load_visual_evidence(db, run_id)
    visual_ok = visual_evidence_passed(db, run_id) if needs_visual else True

    pre_supervisor = _load_artifact(db, run_id, "pre_deploy_supervisor") or {}
    supervisor_ok = bool(pre_supervisor.get("approved", True)) if pre_supervisor else True
    critical_gaps = [
        g
        for g in (pre_supervisor.get("plan_gaps") or [])
        if isinstance(g, dict) and "critical" in str(g.get("message", "")).lower()
    ]
    if critical_gaps or (pre_supervisor and not pre_supervisor.get("approved", True)):
        supervisor_ok = False

    plan = _load_artifact(db, run_id, "plan") or {}
    criteria_lines = _plan_criteria_lines(plan)
    gate_results = {
        "integration_guard": not integration_critical,
        "contract_guard": not contract_critical,
        "visual_evidence": visual_ok,
        "test_plan": dry_runs_ok,
        "pre_deploy_supervisor": supervisor_ok,
    }
    criteria_failures = evaluate_acceptance_criteria(criteria_lines, gate_results=gate_results)
    acceptance_ok = not criteria_failures

    visual_checks = [c for c in (visual_data.get("checks") or []) if isinstance(c, dict)] if visual_data else []
    visual_shots = sum(1 for c in visual_checks if c.get("screenshot_path"))
    if visual_data and visual_data.get("browser_client_required"):
        visual_detail = "Open AI Copilot IDE with this project loaded"
    elif visual_ok and visual_shots:
        visual_detail = f"{visual_shots} screenshot(s) captured"
    elif visual_ok and visual_data:
        visual_detail = "Evidence on disk"
    elif needs_visual:
        visual_detail = "Required for frontend changes"
    else:
        visual_detail = "Not required"

    gates = [
        {
            "id": "test_plan",
            "label": "Tester dry-run & validation",
            "passed": dry_runs_ok,
            "required": bool(changed),
            "detail": test_plan.get("summary") or ("No test_plan artifact" if not test_plan else ""),
        },
        {
            "id": "integration_guard",
            "label": "UI integration (workbench entry)",
            "passed": not integration_critical,
            "required": bool(integration_issues) or needs_visual,
            "detail": integration_issues[0]["message"] if integration_critical else "Clear",
        },
        {
            "id": "contract_guard",
            "label": "Frontend ↔ API contract",
            "passed": not contract_critical,
            "required": bool(contract_issues),
            "detail": contract_issues[0]["message"] if contract_critical else "Clear",
        },
        {
            "id": "visual_evidence",
            "label": "Visual evidence captured",
            "passed": visual_ok,
            "required": needs_visual,
            "detail": visual_detail,
        },
        {
            "id": "pre_deploy_supervisor",
            "label": "Pre-deploy supervisor",
            "passed": supervisor_ok,
            "required": bool(pre_supervisor),
            "detail": pre_supervisor.get("summary") or "Pending or skipped",
        },
        {
            "id": "acceptance_criteria",
            "label": "Planner acceptance criteria",
            "passed": acceptance_ok,
            "required": bool(criteria_lines),
            "detail": criteria_failures[0]["message"] if criteria_failures else "Satisfied",
        },
    ]

    required_gates = [g for g in gates if g["required"]]
    ready = all(g["passed"] for g in required_gates)
    if require_awaiting_approval:
        ready = ready and run.status == "awaiting_approval"

    return {
        "run_id": run_id,
        "status": run.status,
        "ready": ready,
        "gates": gates,
        "changed_files": changed,
        "visual_evidence": visual_data,
        "warnings": truth.get("warnings") or [],
        "mismatch_classes": truth.get("mismatch_classes") or [],
        "readiness": truth,
    }


def validate_approval_allowed(db: Session, run_id: str) -> None:
    from app.core.exceptions import ValidationError

    readiness = build_deployment_readiness(db, run_id)
    if readiness.get("ready"):
        return
    failed = [g["label"] for g in readiness.get("gates", []) if g.get("required") and not g.get("passed")]
    raise ValidationError(
        "Deployment gates not satisfied: " + (", ".join(failed) if failed else readiness.get("message", "not ready"))
    )
