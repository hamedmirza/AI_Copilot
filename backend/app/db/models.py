import json
from datetime import UTC, datetime
from typing import Any, ClassVar, Optional
from uuid import uuid4

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.datetime_types import UtcDateTime
from app.db.session import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class AppConfigModel(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class ProjectModel(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    source_repo_spec: Mapped[str] = mapped_column(Text)
    validation_profile: Mapped[str] = mapped_column(String(64), default="python")
    repo_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    stack_profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    protected_files_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utc_now, onupdate=utc_now
    )

    tasks: Mapped[list["TaskModel"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    runs: Mapped[list["RunModel"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    lessons: Mapped[list["LessonModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    playbooks: Mapped[list["PlaybookModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    chat_sessions: Mapped[list["ChatSessionModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    improvements: Mapped[list["ImprovementModel"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )

    @property
    def protected_files(self) -> list[str]:
        try:
            return json.loads(self.protected_files_json)
        except json.JSONDecodeError:
            return []


class TaskModel(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    description: Mapped[str] = mapped_column(Text)
    validation_profile: Mapped[str] = mapped_column(String(64), default="python")
    task_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    use_scout: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)

    project: Mapped[ProjectModel] = relationship(back_populates="tasks")
    runs: Mapped[list["RunModel"]] = relationship(back_populates="task", cascade="all, delete-orphan")


class RunModel(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    status: Mapped[str] = mapped_column(String(64), index=True, default="pending")
    current_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workspace_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    review_attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    operator_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    promote_snapshot_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_subclass: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recovery_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    superseded_by_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    terminal_success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    terminal_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    schema_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    reviewer_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    tester_failure_count: Mapped[int] = mapped_column(Integer, default=0)
    operator_feedback_present: Mapped[bool] = mapped_column(Boolean, default=False)
    approval_reached: Mapped[bool] = mapped_column(Boolean, default=False)
    promote_rolled_back: Mapped[bool] = mapped_column(Boolean, default=False)
    primary_failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chat_session_id: Mapped[str | None] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True, index=True)
    deliverable_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected_targets_json: Mapped[str] = mapped_column(Text, default="[]")
    expected_validation_family: Mapped[str | None] = mapped_column(String(32), nullable=True)
    readiness_json: Mapped[str] = mapped_column(Text, default="{}")
    mismatch_classes_json: Mapped[str] = mapped_column(Text, default="[]")
    approval_override: Mapped[bool] = mapped_column(Boolean, default=False)
    allow_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    clarification_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    clarification_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    clarification_context_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utc_now, onupdate=utc_now
    )

    project: Mapped[ProjectModel] = relationship(back_populates="runs")
    task: Mapped[TaskModel] = relationship(back_populates="runs")
    events: Mapped[list["RunEventModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunEventModel.created_at"
    )
    artifacts: Mapped[list["ArtifactModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    improvement_exposures: Mapped[list["ImprovementExposureModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    chat_session: Mapped["ChatSessionModel | None"] = relationship("ChatSessionModel", foreign_keys=[chat_session_id])
    thread_entries: Mapped[list["RunThreadEntryModel"]] = relationship(
        back_populates="run", cascade="all, delete-orphan", order_by="RunThreadEntryModel.created_at"
    )

    @property
    def expected_targets(self) -> list[str]:
        try:
            parsed = json.loads(self.expected_targets_json)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @property
    def readiness(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.readiness_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @property
    def mismatch_classes(self) -> list[str]:
        try:
            parsed = json.loads(self.mismatch_classes_json)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @property
    def clarification_context(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.clarification_context_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


class RunEventModel(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)

    run: Mapped[RunModel] = relationship(back_populates="events")


class ArtifactModel(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)
    content_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)

    run: Mapped[RunModel] = relationship(back_populates="artifacts")


class LessonModel(Base):
    __tablename__ = "lessons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)

    project: Mapped[ProjectModel] = relationship(back_populates="lessons")


class GlobalSkillModel(Base):
    __tablename__ = "global_skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="{}")
    source_lesson_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    origin_project_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), default="repo_convention")
    stages_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[float] = mapped_column(default=0.5)
    promotion_state: Mapped[str] = mapped_column(String(32), default="candidate")
    times_applied: Mapped[int] = mapped_column(Integer, default=0)
    times_helpful: Mapped[int] = mapped_column(Integer, default=0)
    times_harmful: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utc_now, onupdate=utc_now
    )

    @property
    def stages(self) -> list[str]:
        try:
            parsed = json.loads(self.stages_json)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []


class ImprovementModel(Base):
    __tablename__ = "improvements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True, nullable=True)
    source_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_lesson_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_skill_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="candidate", index=True)
    scope: Mapped[str] = mapped_column(String(32), default="project", index=True)
    kind: Mapped[str] = mapped_column(String(64), default="repo_convention")
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    failure_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_subclass: Mapped[str | None] = mapped_column(String(128), nullable=True)
    task_kind: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    comparable_task_signature: Mapped[str] = mapped_column(String(255), index=True)
    cohort_key: Mapped[str] = mapped_column(String(255), index=True)
    confidence: Mapped[float] = mapped_column(default=0.5)
    machine_guidance_json: Mapped[str] = mapped_column(Text, default="{}")
    stages_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    baseline_metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    trial_metrics_json: Mapped[str] = mapped_column(Text, default="{}")
    decision_metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    trial_started_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utc_now, onupdate=utc_now
    )

    project: Mapped[ProjectModel | None] = relationship(back_populates="improvements")
    exposures: Mapped[list["ImprovementExposureModel"]] = relationship(
        back_populates="improvement", cascade="all, delete-orphan"
    )

    @property
    def stages(self) -> list[str]:
        try:
            parsed = json.loads(self.stages_json)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @property
    def tags(self) -> list[str]:
        try:
            parsed = json.loads(self.tags_json)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []


class ImprovementExposureModel(Base):
    __tablename__ = "improvement_exposures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    improvement_id: Mapped[str] = mapped_column(ForeignKey("improvements.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String(64), index=True)
    status_at_application: Mapped[str] = mapped_column(String(32))
    scope: Mapped[str] = mapped_column(String(32), default="project")
    cohort_key: Mapped[str] = mapped_column(String(255), index=True)
    task_signature: Mapped[str] = mapped_column(String(255), index=True)
    task_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exposure_kind: Mapped[str] = mapped_column(String(32), default="trial")
    applied_context_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)

    improvement: Mapped[ImprovementModel] = relationship(back_populates="exposures")
    run: Mapped[RunModel] = relationship(back_populates="improvement_exposures")

    @property
    def tags(self) -> list[str]:
        return self.improvement.tags if self.improvement else []


class PlaybookModel(Base):
    __tablename__ = "playbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)

    project: Mapped[ProjectModel] = relationship(back_populates="playbooks")


class ChatSessionModel(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(255), default="New Chat")
    mode: Mapped[str] = mapped_column(String(64), default="general")
    model_override: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nothink: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=None)
    allow_web_search: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utc_now, onupdate=utc_now
    )
    message_count: ClassVar[int]
    last_message_preview: ClassVar[str | None]
    last_message_at: ClassVar[datetime | None]

    project: Mapped[ProjectModel] = relationship(back_populates="chat_sessions")
    messages: Mapped[list["ChatMessageModel"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessageModel.created_at",
    )


class ChatMessageModel(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    session_id: Mapped[str] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    tool_calls_json: Mapped[str] = mapped_column(Text, default="[]")
    tool_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)

    session: Mapped[ChatSessionModel] = relationship(back_populates="messages")

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(self.tool_calls_json)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []

    @property
    def message_metadata(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.metadata_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


class RunThreadEntryModel(Base):
    __tablename__ = "run_thread_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32), default="assistant")
    entry_type: Mapped[str] = mapped_column(String(64), index=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)

    run: Mapped[RunModel] = relationship(back_populates="thread_entries")
    session: Mapped["ChatSessionModel | None"] = relationship("ChatSessionModel")

    @property
    def payload(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.payload_json)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


class MCPServerModel(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    command: Mapped[str] = mapped_column(Text)
    args_json: Mapped[str] = mapped_column(Text, default="[]")
    env_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_status: Mapped[str] = mapped_column(String(64), default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime(), default=utc_now, onupdate=utc_now
    )

    @property
    def args(self) -> list[str]:
        try:
            parsed = json.loads(self.args_json)
        except json.JSONDecodeError:
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    @property
    def env(self) -> dict[str, str]:
        try:
            parsed = json.loads(self.env_json)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        return {str(key): str(value) for key, value in parsed.items()}
