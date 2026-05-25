"""Stub Kanban / reporting data APIs used by the frontend pages.

Not persisted — see docs/KANBAN_STUB_DATA.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.db.session import get_db
from app.services.project_service import ProjectService

router = APIRouter(tags=["kanban"])


class TaskPatch(BaseModel):
    status: str = Field(min_length=1)


@router.get("/projects/{project_id}/tasks")
def list_project_tasks(project_id: str, db=Depends(get_db)):
    ProjectService(db).get(project_id)
    return [
        {
            "id": f"{project_id}-task-1",
            "title": "Sample task",
            "description": "Pipeline stub task for Kanban UI",
            "status": "todo",
        },
        {
            "id": f"{project_id}-task-2",
            "title": "In progress item",
            "description": "Drag-and-drop updates PATCH /api/tasks/{id}",
            "status": "in-progress",
        },
    ]


@router.patch("/tasks/{task_id}")
def patch_task(task_id: str, body: TaskPatch, db=Depends(get_db)):
    if not task_id:
        raise HTTPException(400, "task_id required")
    return {
        "id": task_id,
        "title": "Updated task",
        "description": "Status updated",
        "status": body.status,
    }


@router.get("/projects/{project_id}/metrics")
def project_metrics(project_id: str, db=Depends(get_db)):
    ProjectService(db).get(project_id)
    return {
        "successRate": 72,
        "failureRate": 28,
        "skillImprovements": [
            {"date": "2026-05-01", "score": 40},
            {"date": "2026-05-15", "score": 55},
            {"date": "2026-05-25", "score": 68},
        ],
    }
