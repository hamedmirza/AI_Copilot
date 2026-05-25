"""Workspace-scoped changed files and gate evaluation (delegates to deployment_readiness_service)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ArtifactModel
from app.services.workspace_changed_files import workspace_changed_files


def _load_coder_paths(db: Session, run_id: str) -> list[str]:
    row = (
        db.query(ArtifactModel)
        .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == "coder")
        .order_by(ArtifactModel.id.desc())
        .first()
    )
    if not row:
        return []
    try:
        coder = json.loads(row.content_json)
    except json.JSONDecodeError:
        return []
    paths: list[str] = []
    for change in coder.get("file_changes") or []:
        if isinstance(change, dict):
            path = str(change.get("path") or change.get("file_path") or "").strip()
            if path:
                paths.append(path.replace("\\", "/"))
    return paths


def effective_changed_files(
    db: Session,
    run_id: str,
    workspace: Path,
    source_root: Path,
) -> list[str]:
    merged = set(workspace_changed_files(workspace, source_root))
    merged.update(_load_coder_paths(db, run_id))
    return sorted(merged)


def evaluate_deployment_readiness(
    db: Session,
    run_id: str,
    *,
    workspace: Path | None = None,
) -> dict[str, Any]:
    from app.services.deployment_readiness_service import build_deployment_readiness

    payload = build_deployment_readiness(db, run_id, require_awaiting_approval=True)
    gates = payload.get("gates") or []
    blocking = payload.get("blocking") or []
    return {
        "ready": bool(payload.get("ready")),
        "run_id": run_id,
        "status": payload.get("status"),
        "changed_files": payload.get("changed_files") or [],
        "checks": gates,
        "gates": gates,
        "blocking": blocking,
        "visual_evidence": payload.get("visual_evidence"),
    }


def assert_ready_for_approval(db: Session, run_id: str) -> None:
    from app.services.deployment_readiness_service import validate_approval_allowed

    validate_approval_allowed(db, run_id)
