"""Structured outcome_class and why_blocked fields on pipeline events."""

from __future__ import annotations

from enum import Enum
from typing import Any

from sqlalchemy.orm import Session


class RunOutcomeClass(str, Enum):
    PROGRESSED = "progressed"
    SATISFIED = "satisfied"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    FAILED = "failed"
    AWAITING_APPROVAL = "awaiting_approval"
    CHANGES_REQUESTED = "changes_requested"


_EVENT_OUTCOME: dict[str, RunOutcomeClass] = {
    "run_blocked": RunOutcomeClass.BLOCKED,
    "run_failed": RunOutcomeClass.FAILED,
    "awaiting_approval": RunOutcomeClass.AWAITING_APPROVAL,
    "run_changes_requested": RunOutcomeClass.CHANGES_REQUESTED,
    "run_completed": RunOutcomeClass.PROGRESSED,
    "coder_noop_blueprint_satisfied": RunOutcomeClass.SATISFIED,
    "blueprint_already_satisfied": RunOutcomeClass.SATISFIED,
    "repo_preflight_failed": RunOutcomeClass.BLOCKED,
    "dependency_verify_failed": RunOutcomeClass.BLOCKED,
    "deployment_gates_failed": RunOutcomeClass.BLOCKED,
    "pre_deploy_rejected": RunOutcomeClass.BLOCKED,
    "validation_rejected": RunOutcomeClass.BLOCKED,
    "block_recorded": RunOutcomeClass.BLOCKED,
    "pre_deploy_skipped": RunOutcomeClass.SKIPPED,
    "tester_validation_skipped": RunOutcomeClass.SKIPPED,
    "tester_llm_skipped": RunOutcomeClass.SKIPPED,
    "documentation_skipped": RunOutcomeClass.SKIPPED,
    "ui_designer_skipped": RunOutcomeClass.SKIPPED,
    "deployment_gates_passed": RunOutcomeClass.PROGRESSED,
    "code_patch_applied": RunOutcomeClass.PROGRESSED,
    "reviewer_approved": RunOutcomeClass.PROGRESSED,
    "validation_passed": RunOutcomeClass.PROGRESSED,
}


def infer_outcome_class(event_type: str, severity: str, payload: dict[str, Any]) -> RunOutcomeClass:
    if payload.get("outcome_class"):
        try:
            return RunOutcomeClass(str(payload["outcome_class"]))
        except ValueError:
            pass
    mapped = _EVENT_OUTCOME.get(event_type)
    if mapped:
        return mapped
    if severity == "error":
        return RunOutcomeClass.FAILED
    if event_type.endswith("_skipped"):
        return RunOutcomeClass.SKIPPED
    if event_type.endswith("_failed") or event_type.endswith("_rejected"):
        return RunOutcomeClass.BLOCKED if "blocked" in event_type or "reject" in event_type else RunOutcomeClass.FAILED
    if event_type.endswith("_complete") or event_type.endswith("_passed") or event_type.endswith("_approved"):
        return RunOutcomeClass.PROGRESSED
    return RunOutcomeClass.PROGRESSED


def why_blocked_from_context(
    event_type: str,
    stage: str,
    message: str,
    payload: dict[str, Any],
) -> str:
    if payload.get("why_blocked"):
        return str(payload["why_blocked"]).strip()
    block_type = str(payload.get("block_type") or "").strip()
    source = str(payload.get("source") or "").strip()
    if block_type or source:
        parts = [p for p in (block_type.replace("_", " "), source.replace("_", " ")) if p]
        prefix = " ".join(parts).strip().title() if parts else stage or "pipeline"
        return f"{prefix}: {message}".strip(": ").strip() or message
    if event_type in {"run_blocked", "deployment_gates_failed"}:
        blocking = payload.get("blocking") or []
        if blocking:
            return "; ".join(str(item) for item in blocking[:4])
    if event_type == "dependency_verify_failed":
        missing = payload.get("missing") or []
        if missing:
            return f"Missing dependencies: {', '.join(str(m) for m in missing[:6])}"
    if event_type == "repo_preflight_failed":
        warnings = payload.get("warnings") or []
        if warnings:
            return f"{message} ({'; '.join(str(w) for w in warnings[:3])})"
    if event_type == "pre_deploy_rejected":
        gaps = payload.get("plan_gaps") or []
        if gaps:
            return f"Pre-deploy supervisor: {len(gaps)} plan gap(s)"
    if event_type == "validation_rejected" and payload.get("command"):
        return f"Validation failed: {payload['command']}"
    if stage:
        return f"{message} (stage: {stage})" if message else f"Blocked at {stage}"
    return message or "Run blocked"


def enrich_event_payload(
    event_type: str,
    stage: str,
    severity: str,
    payload: dict[str, Any] | None = None,
    *,
    message: str = "",
) -> dict[str, Any]:
    base = dict(payload or {})
    outcome = infer_outcome_class(event_type, severity, base)
    base.setdefault("outcome_class", outcome.value)
    if outcome == RunOutcomeClass.BLOCKED:
        base.setdefault("why_blocked", why_blocked_from_context(event_type, stage, message, base))
    return base


def outcome_class_for_awaiting_approval(db: Session, run_id: str) -> str:
    from app.services.run_outcome_service import coder_noop_completed, load_artifact

    if coder_noop_completed(db, run_id):
        return RunOutcomeClass.SATISFIED.value
    outcome = load_artifact(db, run_id, "run_outcome") or {}
    if str(outcome.get("kind") or "") == "already_satisfied":
        return RunOutcomeClass.SATISFIED.value
    return RunOutcomeClass.AWAITING_APPROVAL.value


def why_blocked_for_awaiting_satisfied(db: Session, run_id: str) -> str | None:
    from app.services.run_outcome_service import load_artifact

    outcome = load_artifact(db, run_id, "run_outcome") or {}
    message = str(outcome.get("message") or "").strip()
    return message or None
