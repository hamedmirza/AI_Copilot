from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import RunStatus
from app.db.models import (
    GlobalSkillModel,
    ImprovementModel,
    LessonModel,
    RunModel,
)
from app.services.snapshot_service import SNAPSHOTS_ROOT, delete_snapshot
from app.services.workspace_service import (
    active_workspace_dir_names,
    cleanup_run_workspace_for_run,
    runs_root,
)
from app.services.project_service import ProjectService

TERMINAL_FAILED_STATUSES = frozenset({
    RunStatus.FAILED.value,
    RunStatus.BLOCKED.value,
    RunStatus.CHANGES_REQUESTED.value,
    RunStatus.CANCELLED.value,
})

class RunCleanupService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def purge_terminal_failed_runs(self, project_id: str | None = None) -> dict[str, Any]:
        """Delete failed/blocked/changes_requested/cancelled runs and their runtime artifacts."""
        query = self.db.query(RunModel).filter(RunModel.status.in_(TERMINAL_FAILED_STATUSES))
        if project_id:
            query = query.filter(RunModel.project_id == project_id)
        runs = query.order_by(RunModel.created_at.asc()).all()
        if not runs:
            active_names = self._active_workspace_names()
            orphan_workspaces_removed = self._purge_orphan_workspaces(active_names)
            return {
                "deleted_count": 0,
                "deleted_run_ids": [],
                "workspaces_removed": 0,
                "snapshots_removed": 0,
                "orphan_workspaces_removed": orphan_workspaces_removed,
                "by_project": {},
            }

        run_ids = [run.id for run in runs]
        self._clear_run_references(run_ids)

        workspaces_removed = 0
        snapshots_removed = 0
        by_project: dict[str, int] = {}

        project_svc = ProjectService(self.db)
        for run in runs:
            by_project[run.project_id] = by_project.get(run.project_id, 0) + 1
            project = project_svc.get(run.project_id)
            workspace = Path(run.workspace_path) if run.workspace_path else runs_root() / run.id
            if workspace.exists():
                cleanup_run_workspace_for_run(
                    run,
                    project_name=project.name,
                    source_repo_spec=project.source_repo_spec,
                )
                workspaces_removed += 1
            snapshot_dir = SNAPSHOTS_ROOT / run.id
            if snapshot_dir.exists():
                delete_snapshot(run.id)
                snapshots_removed += 1
            self.db.delete(run)

        self.db.commit()

        active_names = self._active_workspace_names()
        orphan_workspaces_removed = self._purge_orphan_workspaces(active_names)

        return {
            "deleted_count": len(run_ids),
            "deleted_run_ids": run_ids,
            "workspaces_removed": workspaces_removed,
            "snapshots_removed": snapshots_removed,
            "orphan_workspaces_removed": orphan_workspaces_removed,
            "by_project": by_project,
        }

    def _clear_run_references(self, run_ids: list[str]) -> None:
        if not run_ids:
            return
        (
            self.db.query(RunModel)
            .filter(RunModel.superseded_by_run_id.in_(run_ids))
            .update({RunModel.superseded_by_run_id: None}, synchronize_session=False)
        )
        (
            self.db.query(LessonModel)
            .filter(LessonModel.run_id.in_(run_ids))
            .update({LessonModel.run_id: None}, synchronize_session=False)
        )
        (
            self.db.query(ImprovementModel)
            .filter(ImprovementModel.source_run_id.in_(run_ids))
            .update({ImprovementModel.source_run_id: None}, synchronize_session=False)
        )
        (
            self.db.query(GlobalSkillModel)
            .filter(GlobalSkillModel.source_run_id.in_(run_ids))
            .update({GlobalSkillModel.source_run_id: None}, synchronize_session=False)
        )

    def _active_workspace_names(self) -> set[str]:
        from app.db.models import ProjectModel

        runs = self.db.query(RunModel).all()
        project_ids = {r.project_id for r in runs}
        projects = {
            p.id: p
            for p in self.db.query(ProjectModel).filter(ProjectModel.id.in_(project_ids)).all()
        }
        for run in runs:
            run.project = projects.get(run.project_id)
        return active_workspace_dir_names(runs)

    def _purge_orphan_workspaces(self, active_workspace_names: set[str]) -> int:
        removed = 0
        for child in runs_root().iterdir():
            if not child.is_dir() or child.name in active_workspace_names:
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        return removed
