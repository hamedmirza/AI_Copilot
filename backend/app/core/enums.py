from enum import StrEnum


class ProviderStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    UNAVAILABLE = "unavailable"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    CHANGES_REQUESTED = "changes_requested"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineStage(StrEnum):
    PLANNER = "planner"
    ARCHITECT = "architect"
    UI_DESIGNER = "ui_designer"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    SUPERVISOR = "supervisor"


class ValidationProfile(StrEnum):
    PYTHON = "python"
    REACT = "react"
    FULLSTACK = "fullstack"
    NODE = "node"
    CUSTOM = "custom"
