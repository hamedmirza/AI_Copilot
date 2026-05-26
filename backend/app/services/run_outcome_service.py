"""Unified run outcome: coder change set, blueprint satisfaction, and gate scoping."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import ArtifactModel
from app.services.file_service import FileService
from app.tools.command_runner import run_command


class RunOutcomeKind(str, Enum):
    PENDING = "pending"
    ALREADY_SATISFIED = "already_satisfied"
    PATCHED = "patched"


@dataclass(frozen=True)
class BlueprintSatisfaction:
    kind: RunOutcomeKind
    blueprint_paths: tuple[str, ...]
    test_paths: tuple[str, ...]
    message: str


def load_artifact(db: Session, run_id: str, artifact_type: str) -> dict | None:
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


def coder_artifact_exists(db: Session, run_id: str) -> bool:
    return (
        db.query(ArtifactModel)
        .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == "coder")
        .first()
        is not None
    )


def coder_changed_paths(db: Session, run_id: str) -> list[str]:
    artifact = load_artifact(db, run_id, "coder") or {}
    paths: list[str] = []
    for change in artifact.get("file_changes") or []:
        if not isinstance(change, dict):
            continue
        path = str(change.get("path") or change.get("file_path") or "").strip()
        if path:
            paths.append(path.replace("\\", "/"))
    return paths


def coder_has_file_changes(db: Session, run_id: str) -> bool:
    return bool(coder_changed_paths(db, run_id))


def coder_noop_completed(db: Session, run_id: str) -> bool:
    """True when coder stage finished and produced no file changes."""
    return coder_artifact_exists(db, run_id) and not coder_has_file_changes(db, run_id)


def blueprint_paths(architect: dict) -> list[str]:
    paths: list[str] = []
    for raw_change in architect.get("file_changes") or []:
        if not isinstance(raw_change, dict):
            continue
        rel_path = str(raw_change.get("path") or "").strip()
        if rel_path:
            paths.append(rel_path.replace("\\", "/"))
    return paths


def blueprint_test_paths(paths: list[str]) -> list[str]:
    test_paths: list[str] = []
    for rel_path in paths:
        norm = rel_path.replace("\\", "/")
        name = Path(norm).name
        if "/tests/" in norm or norm.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py"):
            test_paths.append(rel_path)
    return test_paths


def blueprint_files_exist(fs: FileService, paths: list[str]) -> bool:
    if not paths:
        return False
    for rel_path in paths:
        try:
            fs.read_file(rel_path)
        except Exception:
            return False
    return True


def blueprint_tests_pass(workspace: Path, test_paths: list[str], *, source_root: Path) -> bool:
    if not test_paths:
        return True
    backend_root = workspace / "backend"
    cwd = backend_root if backend_root.is_dir() else workspace
    pytest_bin = cwd / ".venv" / "bin" / "pytest"
    if not pytest_bin.is_file():
        source_backend = source_root / "backend"
        source_cwd = source_backend if source_backend.is_dir() else source_root
        pytest_bin = source_cwd / ".venv" / "bin" / "pytest"
    if not pytest_bin.is_file():
        return False
    pytest_cmd = str(pytest_bin.resolve())
    for rel_path in test_paths:
        norm = rel_path.replace("\\", "/")
        test_target = norm.removeprefix("backend/") if norm.startswith("backend/") else norm
        code, _, _ = run_command(f'"{pytest_cmd}" {test_target} -q', cwd, timeout=120)
        if code != 0:
            return False
    return True


def evaluate_blueprint_satisfaction(
    architect: dict,
    fs: FileService,
    workspace: Path,
    source_root: Path,
) -> BlueprintSatisfaction:
    paths = blueprint_paths(architect)
    tests = blueprint_test_paths(paths)
    if not paths or not blueprint_files_exist(fs, paths):
        return BlueprintSatisfaction(
            kind=RunOutcomeKind.PENDING,
            blueprint_paths=tuple(paths),
            test_paths=tuple(tests),
            message="Blueprint files missing or not yet verified.",
        )
    if tests and not blueprint_tests_pass(workspace, tests, source_root=source_root):
        return BlueprintSatisfaction(
            kind=RunOutcomeKind.PENDING,
            blueprint_paths=tuple(paths),
            test_paths=tuple(tests),
            message="Blueprint tests did not pass.",
        )
    message = (
        "Blueprint files already exist in the workspace"
        + (" and targeted tests pass" if tests else "")
        + "; no code changes required."
    )
    return BlueprintSatisfaction(
        kind=RunOutcomeKind.ALREADY_SATISFIED,
        blueprint_paths=tuple(paths),
        test_paths=tuple(tests),
        message=message,
    )


def run_changed_paths(
    db: Session,
    run_id: str,
    workspace: Path,
    source_root: Path,
) -> list[str]:
    """Paths this run owns: coder artifact paths after coder; otherwise workspace drift + coder."""
    if coder_artifact_exists(db, run_id):
        return sorted(set(coder_changed_paths(db, run_id)))
    from app.services.workspace_changed_files import workspace_changed_files

    merged = set(workspace_changed_files(workspace, source_root))
    merged.update(coder_changed_paths(db, run_id))
    return sorted(merged)


def save_run_outcome_artifact(db: Session, run_id: str, satisfaction: BlueprintSatisfaction) -> None:
    payload = {
        "kind": satisfaction.kind.value,
        "blueprint_paths": list(satisfaction.blueprint_paths),
        "test_paths": list(satisfaction.test_paths),
        "message": satisfaction.message,
    }
    db.add(
        ArtifactModel(
            run_id=run_id,
            artifact_type="run_outcome",
            content_json=json.dumps(payload),
        )
    )
