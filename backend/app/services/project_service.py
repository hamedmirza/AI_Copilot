from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.enums import RunStatus
from app.core.exceptions import NotFoundError, ValidationError
from app.db.models import LessonModel, PlaybookModel, ProjectModel, RunModel
from app.schemas.api import ProjectCreate, ProjectUpdate


class ProjectService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_projects(self) -> list[ProjectModel]:
        return self.db.query(ProjectModel).order_by(ProjectModel.updated_at.desc()).all()

    def get(self, project_id: str) -> ProjectModel:
        project = self.db.query(ProjectModel).filter(ProjectModel.id == project_id).first()
        if not project:
            raise NotFoundError(f"Project not found: {project_id}")
        return project

    def _resolve_source_repo_spec(self, spec: str, project_name: str) -> str:
        spec = spec.strip()
        if spec.startswith("https://"):
            parsed = urlparse(spec)
            allowed = ["github.com", "gitlab.com"]
            if parsed.hostname not in allowed:
                raise ValidationError(f"Git host not allowed: {parsed.hostname}")
            dest = Path(__file__).resolve().parents[2] / "repos" / project_name.replace(" ", "-")
            dest.mkdir(parents=True, exist_ok=True)
            if not any(dest.iterdir()):
                import subprocess

                subprocess.run(["git", "clone", spec, str(dest)], check=True)
            spec = str(dest)

        path = Path(spec)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        return str(path.resolve())

    def create(self, data: ProjectCreate) -> ProjectModel:
        resolved_spec = self._resolve_source_repo_spec(data.source_repo_spec, data.name)

        project = ProjectModel(
            name=data.name,
            description=data.description,
            source_repo_spec=resolved_spec,
            validation_profile=data.validation_profile,
            protected_files_json=json.dumps(data.protected_files),
        )
        self.db.add(project)
        self.db.commit()
        self.db.refresh(project)
        return project

    def update(self, project_id: str, data: ProjectUpdate) -> ProjectModel:
        project = self.get(project_id)
        updates = data.model_dump(exclude_none=True)

        if "source_repo_spec" in updates:
            name = updates.get("name", project.name)
            updates["source_repo_spec"] = self._resolve_source_repo_spec(
                updates["source_repo_spec"], name
            )

        for key, value in updates.items():
            if key == "protected_files":
                project.protected_files_json = json.dumps(value)
            else:
                setattr(project, key, value)
        project.updated_at = datetime.now(UTC)
        self.db.commit()
        self.db.refresh(project)
        return project

    def delete(self, project_id: str) -> None:
        project = self.get(project_id)
        self.db.delete(project)
        self.db.commit()

    def get_blockers(self, project_id: str) -> list[RunModel]:
        return (
            self.db.query(RunModel)
            .filter(RunModel.project_id == project_id, RunModel.status == RunStatus.BLOCKED)
            .all()
        )

    def release_readiness(self, project_id: str) -> dict:
        runs = self.db.query(RunModel).filter(RunModel.project_id == project_id).all()
        blocked = [r for r in runs if r.status in (RunStatus.BLOCKED, RunStatus.FAILED)]
        return {
            "ready": len(blocked) == 0,
            "blocked_count": len(blocked),
            "blocked_run_ids": [r.id for r in blocked],
        }

    def list_lessons(self, project_id: str) -> list[LessonModel]:
        return (
            self.db.query(LessonModel)
            .filter(LessonModel.project_id == project_id)
            .order_by(LessonModel.created_at.desc())
            .all()
        )

    def add_lesson(self, project_id: str, title: str, content: str, run_id: str | None = None) -> LessonModel:
        lesson = LessonModel(project_id=project_id, title=title, content=content, run_id=run_id)
        self.db.add(lesson)
        self.db.commit()
        self.db.refresh(lesson)
        return lesson

    def list_playbooks(self, project_id: str) -> list[PlaybookModel]:
        return self.db.query(PlaybookModel).filter(PlaybookModel.project_id == project_id).all()

    def create_playbook(self, project_id: str, name: str, content: str) -> PlaybookModel:
        pb = PlaybookModel(project_id=project_id, name=name, content=content)
        self.db.add(pb)
        self.db.commit()
        self.db.refresh(pb)
        return pb
