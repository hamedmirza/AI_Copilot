from __future__ import annotations

import shutil
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
from app.services.workspace_service import cleanup_run_workspace, runs_root

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
            active_run_ids = {row[0] for row in self.db.query(RunModel.id).all()}
            orphan_workspaces_removed = self._purge_orphan_workspaces(active_run_ids)
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

        for run in runs:
            by_project[run.project_id] = by_project.get(run.project_id, 0) + 1
            workspace = runs_root() / run.id
            if workspace.exists():
                cleanup_run_workspace(run.id)
                workspaces_removed += 1
            snapshot_dir = SNAPSHOTS_ROOT / run.id
            if snapshot_dir.exists():
                delete_snapshot(run.id)
                snapshots_removed += 1
            self.db.delete(run)

        self.db.commit()

        active_run_ids = {
            row[0]
            for row in self.db.query(RunModel.id).all()
        }
        orphan_workspaces_removed = self._purge_orphan_workspaces(active_run_ids)

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

    def _purge_orphan_workspaces(self, active_run_ids: set[str]) -> int:
        removed = 0
        for child in runs_root().iterdir():
            if not child.is_dir() or child.name in active_run_ids:
                continue
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
        return removed
