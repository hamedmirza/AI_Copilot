from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ArtifactModel, RunModel, TaskModel
from app.services.project_service import ProjectService
from app.services.workspace_changed_files import workspace_changed_files


_FRONTEND_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx", ".css", ".scss", ".html")
_BACKEND_EXTENSIONS = (".py", ".pyi")
_REPORT_EXTENSIONS = (".md", ".txt", ".rst")
_FRONTEND_UI_TOKENS = ("page", "dashboard", "kanban", "ui", "frontend", "screen", "view")


def description_implies_frontend_ui(text: str) -> bool:
    lowered = (text or "").strip().lower()
    for token in _FRONTEND_UI_TOKENS:
        if len(token) <= 3:
            if re.search(rf"\b{re.escape(token)}\b", lowered):
                return True
        elif token in lowered:
            return True
    return False


def should_run_ui_designer(
    description: str,
    task_kind: str | None,
    deliverable_kind: str | None = None,
) -> bool:
    if task_kind == "analysis":
        return False
    kind = deliverable_kind or infer_deliverable_kind(description, task_kind)
    if kind == "frontend":
        return True
    if kind in {"report", "backend"}:
        return False
    if kind == "mixed":
        return description_implies_frontend_ui(description)
    return description_implies_frontend_ui(description)


def infer_deliverable_kind(description: str, task_kind: str | None) -> str:
    text = (description or "").strip().lower()
    if task_kind == "analysis":
        return "report"
    if description_implies_frontend_ui(text):
        return "frontend"
    if any(token in text for token in ("api", "backend", "route", "service", "endpoint", "database")):
        return "backend"
    if any(token in text for token in ("report", "summary", "analysis", "document", "write up", "write-up")):
        return "report"
    return "mixed"


def expected_targets_for_kind(deliverable_kind: str) -> list[str]:
    return {
        "frontend": ["frontend/src"],
        "backend": ["backend/app"],
        "report": [".ai-copilot/reports"],
        "mixed": ["frontend/src", "backend/app"],
    }.get(deliverable_kind, [])


def expected_validation_family(profile: str, deliverable_kind: str) -> str:
    if profile:
        return profile
    return {
        "frontend": "react",
        "backend": "python",
        "report": "report-only",
        "mixed": "fullstack",
    }.get(deliverable_kind, "fullstack")


def _load_artifact(db: Session, run_id: str, artifact_type: str) -> dict[str, Any] | None:
    row = (
        db.query(ArtifactModel)
        .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == artifact_type)
        .order_by(ArtifactModel.id.desc())
        .first()
    )
    if not row:
        return None
    try:
        parsed = json.loads(row.content_json)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).replace("\\", "/") for item in value if str(item).strip()]


def _load_coder_paths(db: Session, run_id: str) -> list[str]:
    artifact = _load_artifact(db, run_id, "coder") or {}
    paths: list[str] = []
    for change in artifact.get("file_changes") or []:
        if not isinstance(change, dict):
            continue
        path = str(change.get("path") or change.get("file_path") or "").strip()
        if path:
            paths.append(path.replace("\\", "/"))
    return paths


def _load_changed_files(db: Session, run: RunModel) -> list[str]:
    project = ProjectService(db).get(run.project_id)
    source_root = Path(project.source_repo_spec)
    workspace = Path(run.workspace_path) if run.workspace_path else source_root
    merged = set(workspace_changed_files(workspace, source_root))
    merged.update(_load_coder_paths(db, run.id))
    return sorted(merged)


def _is_report_like(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith(".ai-copilot/reports/") or normalized.endswith(_REPORT_EXTENSIONS)


def _matches_expected(path: str, expected_targets: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(normalized.startswith(target.rstrip("/")) for target in expected_targets)


def _validation_matches_files(changed_files: list[str], family: str) -> bool:
    if not changed_files or family == "report-only":
        return True
    if family == "python":
        return any(path.endswith(_BACKEND_EXTENSIONS) for path in changed_files)
    if family in {"react", "node"}:
        return any(path.endswith(_FRONTEND_EXTENSIONS) for path in changed_files)
    if family == "fullstack":
        return any(path.endswith(_FRONTEND_EXTENSIONS + _BACKEND_EXTENSIONS) for path in changed_files)
    return True


def _reviewer_aligned(review: dict[str, Any] | None, mismatch_classes: list[str]) -> bool:
    if not review:
        return False
    if not bool(review.get("approved")):
        return False
    if any(item in mismatch_classes for item in ("intent_drift", "report_substitution")):
        return False
    return True


def _tester_summary(run: RunModel, test_plan: dict[str, Any] | None, validation_matches: bool) -> tuple[bool, bool]:
    dry_run_failed = (
        int(getattr(run, "tester_failure_count", 0) or 0) > 0
        or bool(run.error_message and run.current_stage == "tester" and run.status in {"failed", "blocked"})
    )
    if test_plan is not None and test_plan.get("passed") is False:
        dry_run_failed = True
    return (not dry_run_failed), validation_matches and not dry_run_failed


def compute_run_truth(db: Session, run_id: str) -> dict[str, Any]:
    run = db.get(RunModel, run_id)
    if not run:
        return {}
    task = db.get(TaskModel, run.task_id)
    description = task.description if task else ""
    validation_profile = task.validation_profile if task else "python"
    deliverable_kind = run.deliverable_kind or infer_deliverable_kind(description, run.task_kind)
    expected_targets = run.expected_targets or expected_targets_for_kind(deliverable_kind)
    validation_family = run.expected_validation_family or expected_validation_family(validation_profile, deliverable_kind)
    changed_files = _load_changed_files(db, run)
    review = None
    review_rows = (
        db.query(ArtifactModel)
        .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type.like("review_%"))
        .order_by(ArtifactModel.id.desc())
        .all()
    )
    for row in review_rows:
        try:
            parsed = json.loads(row.content_json)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            review = parsed
            break
    test_plan = _load_artifact(db, run_id, "test_plan")
    coder = _load_artifact(db, run_id, "coder")
    mismatch_classes: list[str] = []
    warnings: list[str] = []

    if deliverable_kind != "report" and changed_files and all(_is_report_like(path) for path in changed_files):
        mismatch_classes.append("report_substitution")
        warnings.append("Implementation task ended with report or documentation file changes only.")
    if expected_targets and changed_files and not any(_matches_expected(path, expected_targets) for path in changed_files):
        mismatch_classes.append("intent_drift")
        warnings.append("Changed files do not touch the expected product surface for this task.")
    validation_matches = _validation_matches_files(changed_files, validation_family)
    if changed_files and not validation_matches:
        mismatch_classes.append("validation_mismatch")
        warnings.append("Changed files do not match the expected validation family for this task.")
    if run.clarification_question:
        mismatch_classes.append("clarification_required")
        warnings.append("Run is waiting for clarification before it can continue safely.")
    if run.approval_override:
        mismatch_classes.append("approval_override")
        warnings.append("Run was manually approved despite readiness warnings.")

    reviewer_aligned = _reviewer_aligned(review, mismatch_classes)
    tester_dry_runs_ok, tester_aligned = _tester_summary(run, test_plan, validation_matches)
    intent_matched = "intent_drift" not in mismatch_classes and "report_substitution" not in mismatch_classes
    files_matched = not expected_targets or not changed_files or any(
        _matches_expected(path, expected_targets) for path in changed_files
    )
    readiness = {
        "deliverable_kind": deliverable_kind,
        "expected_targets": expected_targets,
        "expected_validation_family": validation_family,
        "changed_files": changed_files,
        "intent_matched": intent_matched,
        "files_matched": files_matched,
        "validation_matched": validation_matches,
        "reviewer_aligned": reviewer_aligned,
        "tester_aligned": tester_aligned,
        "tester_dry_runs_ok": tester_dry_runs_ok,
        "approval_override": bool(run.approval_override),
        "warning_count": len(warnings),
        "warnings": warnings,
        "mismatch_classes": mismatch_classes,
        "coder_summary": str((coder or {}).get("summary") or "").strip() if coder else "",
    }
    return readiness


def persist_run_truth(db: Session, run_id: str) -> dict[str, Any]:
    run = db.get(RunModel, run_id)
    if not run:
        return {}
    readiness = compute_run_truth(db, run_id)
    if not readiness:
        return {}
    run.deliverable_kind = str(readiness.get("deliverable_kind") or run.deliverable_kind or "")
    run.expected_targets_json = json.dumps(readiness.get("expected_targets") or [])
    run.expected_validation_family = str(
        readiness.get("expected_validation_family") or run.expected_validation_family or ""
    )
    run.readiness_json = json.dumps(readiness)
    run.mismatch_classes_json = json.dumps(readiness.get("mismatch_classes") or [])
    db.commit()
    return readiness
