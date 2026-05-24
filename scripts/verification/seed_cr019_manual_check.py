#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.enums import RunStatus  # noqa: E402
from app.db.models import ArtifactModel, ProjectModel, RunEventModel, RunModel, TaskModel  # noqa: E402
from app.db.session import SessionLocal, run_migrations, seed_app_config  # noqa: E402


SEED_ROOT = REPO_ROOT / "runtime" / "verification" / "cr019_manual_check"
SOURCE_ROOT = SEED_ROOT / "source_repo"
MANIFEST_PATH = SEED_ROOT / "manifest.json"


def reset_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    run_migrations()
    db = SessionLocal()
    try:
        seed_app_config(db)
        if MANIFEST_PATH.exists():
            try:
                manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
                prior = db.query(ProjectModel).filter(ProjectModel.id == manifest.get("project_id")).first()
                if prior:
                    db.delete(prior)
                    db.commit()
            except Exception:
                db.rollback()
    finally:
        db.close()

    reset_directory(SEED_ROOT)
    reset_directory(SOURCE_ROOT)

    source_package = '{\n  "name": "cr019-source",\n  "version": "1.0.0"\n}\n'
    promoted_package = '{\n  "name": "cr019-promoted",\n  "version": "1.1.0"\n}\n'
    source_npmrc = "fund=false\n"
    promoted_npmrc = "legacy-peer-deps=true\n"

    write_text(SOURCE_ROOT / "package.json", source_package)
    write_text(SOURCE_ROOT / ".npmrc", source_npmrc)
    write_text(SOURCE_ROOT / "README.md", "# CR019 verification source\n")

    db = SessionLocal()
    try:
        project = ProjectModel(
            name="CR019 Manual Verification",
            description="Seeded fixtures for CR-019 manual verification",
            source_repo_spec=str(SOURCE_ROOT),
            validation_profile="react",
            protected_files_json="[]",
        )
        db.add(project)
        db.flush()

        review_task = TaskModel(
            project_id=project.id,
            description="CR019 review seed",
            validation_profile="react",
        )
        resume_task = TaskModel(
            project_id=project.id,
            description="CR019 resume seed",
            validation_profile="react",
        )
        db.add_all([review_task, resume_task])
        db.flush()

        review_run = RunModel(
            project_id=project.id,
            task_id=review_task.id,
            status=RunStatus.AWAITING_APPROVAL.value,
            current_stage="tester",
        )
        resume_run = RunModel(
            project_id=project.id,
            task_id=resume_task.id,
            status=RunStatus.PENDING.value,
            current_stage="reviewer",
        )
        db.add_all([review_run, resume_run])
        db.flush()

        review_workspace = REPO_ROOT / "runtime" / "workspaces" / review_run.id
        resume_workspace = REPO_ROOT / "runtime" / "workspaces" / resume_run.id
        reset_directory(review_workspace)
        reset_directory(resume_workspace)

        write_text(review_workspace / "package.json", promoted_package)
        write_text(review_workspace / ".npmrc", promoted_npmrc)
        write_text(review_workspace / "README.md", "# CR019 verification workspace\n")
        write_text(resume_workspace / "README.md", "# Resumable run workspace\n")

        review_run.workspace_path = str(review_workspace)
        resume_run.workspace_path = str(resume_workspace)

        coder_artifact = ArtifactModel(
            run_id=review_run.id,
            artifact_type="coder",
            content_json=json.dumps(
                {
                    "summary": "Seeded coder artifact for CR-019 manual verification",
                    "requires_operator_approval": True,
                    "file_changes": [
                        {
                            "path": "package.json",
                            "full_content": promoted_package,
                        }
                    ],
                }
            ),
        )
        review_artifact = ArtifactModel(
            run_id=review_run.id,
            artifact_type="review_1",
            content_json=json.dumps(
                {
                    "approved": False,
                    "summary": "Seeded review artifact for CR-019 manual verification.",
                    "issues": [
                        {
                            "severity": "medium",
                            "file_path": "package.json",
                            "message": "Open this path before approval to verify run-context resolution.",
                        },
                        {
                            "severity": "info",
                            "file_path": ".npmrc",
                            "message": "Open this path before and after approval to verify workspace then project-source fallback.",
                        },
                    ],
                    "suggestions": [
                        "Open package.json and .npmrc from the Review tab.",
                    ],
                }
            ),
        )
        db.add_all([coder_artifact, review_artifact])
        db.add_all(
            [
                RunEventModel(
                    run_id=review_run.id,
                    event_type="awaiting_approval",
                    stage="tester",
                    severity="info",
                    message="Seeded awaiting approval run for CR-019 manual verification",
                    payload_json="{}",
                ),
                RunEventModel(
                    run_id=resume_run.id,
                    event_type="run_created",
                    stage="reviewer",
                    severity="info",
                    message="Seeded pending run for CR-019 manual verification",
                    payload_json="{}",
                ),
            ]
        )
        db.commit()

        manifest = {
            "project_id": project.id,
            "review_run_id": review_run.id,
            "resume_run_id": resume_run.id,
            "source_repo": str(SOURCE_ROOT),
            "review_workspace": str(review_workspace),
            "resume_workspace": str(resume_workspace),
            "source_files": {
                "package.json": source_package,
                ".npmrc": source_npmrc,
            },
            "workspace_files": {
                "package.json": promoted_package,
                ".npmrc": promoted_npmrc,
            },
        }
        MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    finally:
        db.close()

    print("CR-019 manual verification seed created")
    print(f"project_id={manifest['project_id']}")
    print(f"review_run_id={manifest['review_run_id']}")
    print(f"resume_run_id={manifest['resume_run_id']}")
    print(f"source_repo={manifest['source_repo']}")
    print(f"review_workspace={manifest['review_workspace']}")
    print("paths:")
    print("  package.json")
    print("  .npmrc")
    print("cleanup:")
    print("  python3 scripts/verification/cleanup_cr019_manual_check.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
