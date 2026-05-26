from enum import StrEnum


class ProviderStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    UNAVAILABLE = "unavailable"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    AWAITING_DESIGN_REVIEW = "awaiting_design_review"
    AWAITING_APPROVAL = "awaiting_approval"
    CHANGES_REQUESTED = "changes_requested"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RepoMode(StrEnum):
    GREENFIELD = "greenfield"
    PARTIAL = "partial"
    EXISTING = "existing"


class PipelineStage(StrEnum):
    SETUP = "setup"
    APP_DESIGNER = "app_designer"
    PLANNER = "planner"
    ARCHITECT = "architect"
    UI_DESIGNER = "ui_designer"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    DOCUMENTATION = "documentation"
    PLAYBOOK_SUPERVISOR = "playbook_supervisor"
    SUPERVISOR = "supervisor"


class ValidationProfile(StrEnum):
    PYTHON = "python"
    REACT = "react"
    FULLSTACK = "fullstack"
    NODE = "node"
    CUSTOM = "custom"
