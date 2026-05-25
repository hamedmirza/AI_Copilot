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
