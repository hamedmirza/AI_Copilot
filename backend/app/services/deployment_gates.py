"""Workspace-scoped changed files and gate evaluation (delegates to deployment_readiness_service)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.services.run_outcome_service import run_changed_paths


def effective_changed_files(
    db: Session,
    run_id: str,
    workspace: Path,
    source_root: Path,
) -> list[str]:
    return run_changed_paths(db, run_id, workspace, source_root)


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
