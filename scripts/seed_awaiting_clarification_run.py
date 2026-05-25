#!/usr/bin/env python3
"""Seed a dev run in awaiting_clarification for manual RunDetailDrawer E2E.

Usage (from repo root, backend venv active or via .venv/bin/python):
  backend/.venv/bin/python scripts/seed_awaiting_clarification_run.py [project_id]

Prints run_id. Open IDE → Runs → Open run details → Conversation → Send answer.
Uses backend/app.db (or DB_URL from environment), not test_app.db.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.db.models import ProjectModel, RunModel, TaskModel  # noqa: E402
from app.db.session import SessionLocal, run_migrations  # noqa: E402
from app.services.run_thread_service import RunThreadService  # noqa: E402


def main() -> int:
    run_migrations()
    db = SessionLocal()
    try:
        project_id = sys.argv[1] if len(sys.argv) > 1 else None
        project = None
        if project_id:
            project = db.get(ProjectModel, project_id)
        if project is None:
            project = db.query(ProjectModel).order_by(ProjectModel.created_at.desc()).first()
        if project is None:
            print("No project in app.db. Add a project in the IDE first.", file=sys.stderr)
            return 1

        workspace = Path(project.source_repo_spec or REPO_ROOT)
        if not workspace.is_dir():
            workspace = REPO_ROOT

        task = TaskModel(
            project_id=project.id,
            description="[seed] Clarification drawer E2E — implement UI page",
            validation_profile=project.validation_profile or "python",
        )
        db.add(task)
        db.flush()

        question = "Where should the new page be wired in the IDE shell?"
        assumption = "Default: workbench center panel via getContribution('center', …)."
        run = RunModel(
            project_id=project.id,
            task_id=task.id,
            status="awaiting_clarification",
            current_stage="architect",
            task_kind="implementation",
            clarification_question=question,
            clarification_stage="architect",
            clarification_context_json=json.dumps(
                {
                    "question": question,
                    "recommended_assumption": assumption,
                }
            ),
            workspace_path=str(workspace),
        )
        db.add(run)
        db.flush()
        run_id = run.id
        db.commit()

        RunThreadService(db).append_entry(
            run_id,
            entry_type="run_clarification_requested",
            stage="architect",
            severity="warning",
            message=question,
            payload={
                "question": question,
                "recommended_assumption": assumption,
                "clarification_pending": True,
            },
            role="assistant",
        )
        print(run_id)
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
