from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import RunStatus
from app.db.models import (
    ArtifactModel,
    GlobalSkillModel,
    ImprovementExposureModel,
    ImprovementModel,
    LessonModel,
    RunEventModel,
    RunModel,
    TaskModel,
)
from app.services.config_service import ConfigService
from app.services.run_engine.event_bus import event_bus


FAILURE_CLASSES = {
    "schema_contract",
    "provider_route",
    "provider_timeout",
    "provider_context",
    "repo_grounding",
    "review_loop",
    "validation_profile",
    "promotion_workflow",
    "workspace_isolation",
    "unknown",
}
RECOVERY_STATUSES = {"none", "candidate", "superseded", "manually_ignored"}
TASK_KINDS = {"analysis", "implementation", "debug", "validation", "playbook", "mixed"}
IMPROVEMENT_STATUSES = {"candidate", "trialing", "approved", "deprecated", "rejected"}
AUTO_PROMOTABLE_FAILURES = FAILURE_CLASSES - {"unknown"}
AUTO_PROMOTABLE_LESSON_KINDS = frozenset({"repo_convention", "failure_avoidance", "task_intent_hint"})
# In-run orchestration stages (OrchestrationService._pipeline).
PIPELINE_STAGE_ORDER = ("planner", "architect", "ui_designer", "coder", "reviewer", "tester")
# Post-deploy only: runs in approve_run_sync after promotion — not in _pipeline loop.
POST_DEPLOY_STAGE_ORDER = ("supervisor",)
FULL_PIPELINE_STAGE_ORDER = PIPELINE_STAGE_ORDER + POST_DEPLOY_STAGE_ORDER

_ANALYSIS_HINTS = ("review", "audit", "analyze", "analyse", "inspect", "assess", "trace", "surface", "map")
_IMPLEMENTATION_HINTS = ("implement", "build", "fix", "change", "update", "create", "add", "replace", "refactor", "extend")
_DEBUG_HINTS = ("debug", "diagnose", "investigate", "why", "failing", "fails", "broken")
_VALIDATION_HINTS = ("validate", "verification", "verify", "test", "tests", "quality gate")
_PLAYBOOK_HINTS = ("playbook", "runbook", "procedure", "operational")
_STOPWORDS = {
    "the", "and", "that", "with", "from", "into", "this", "these", "those", "task", "repo",
    "application", "project", "agent", "run", "issue", "issues", "current", "future", "failed",
}
_JSON_SCHEMA_ERROR_HINTS = (
    "jsondecodeerror",
    "expecting value",
    "expecting ',' delimiter",
    "expecting property name enclosed in double quotes",
    "unterminated string",
    "extra data",
    "invalid control character",
    "invalid \\escape",
)


@dataclass
class ImprovementMatch:
    source_scope: str
    source_id: str
    title: str
    summary: str
    guidance: str
    score: float
    kind: str
    status: str
    exposure_kind: str


def _task_kind_hint_matches(lower: str, hint: str) -> bool:
    return re.search(rf"\b{re.escape(hint)}\b", lower) is not None


def infer_task_kind(description: str) -> str:
    lower = (description or "").lower()
    scores = {
        "analysis": sum(1 for hint in _ANALYSIS_HINTS if _task_kind_hint_matches(lower, hint)),
        "implementation": sum(1 for hint in _IMPLEMENTATION_HINTS if _task_kind_hint_matches(lower, hint)),
        "debug": sum(1 for hint in _DEBUG_HINTS if _task_kind_hint_matches(lower, hint)),
        "validation": sum(1 for hint in _VALIDATION_HINTS if _task_kind_hint_matches(lower, hint)),
        "playbook": sum(1 for hint in _PLAYBOOK_HINTS if _task_kind_hint_matches(lower, hint)),
    }
    best_kind = max(scores, key=lambda kind: scores[kind])
    best_score = scores[best_kind]
    if best_score <= 0:
        return "implementation"
    competing = [kind for kind, score in scores.items() if score == best_score]
    if len(competing) == 1:
        return best_kind
    for preferred in ("implementation", "debug", "analysis", "validation", "playbook"):
        if preferred in competing:
            return preferred
    return "mixed"


def normalize_task_signature(description: str) -> str:
    words = re.findall(r"[a-z0-9_]{4,}", (description or "").lower())
    selected: list[str] = []
    for word in words:
        if word in _STOPWORDS:
            continue
        if word not in selected:
            selected.append(word)
        if len(selected) >= 10:
            break
    return "-".join(selected) or "general-task"


def build_cohort_key(project_id: str | None, task_signature: str, task_kind: str, stage: str | None = None) -> str:
    parts = [project_id or "global", task_kind or "implementation", task_signature or "general-task"]
    if stage:
        parts.append(stage)
    return ":".join(parts)


def _loads_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _loads_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


class LearningService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _config(self) -> dict[str, Any]:
        return ConfigService(self.db).get_all()

    def _emit_learning_event(self, run_id: str, event_type: str, message: str, payload: dict[str, Any]) -> None:
        event_bus.emit(
            run_id,
            {
                "type": event_type,
                "run_id": run_id,
                "message": message,
                "payload": payload,
            },
        )

    def ensure_run_task_kind(self, run: RunModel) -> None:
        task = run.task or self.db.get(TaskModel, run.task_id)
        if not task:
            return
        task_kind = task.task_kind or infer_task_kind(task.description)
        changed = False
        if task.task_kind != task_kind:
            task.task_kind = task_kind
            changed = True
        if run.task_kind != task_kind:
            run.task_kind = task_kind
            changed = True
        if changed:
            self.db.commit()

    def terminal_artifact(self, run_id: str, artifact_type: str) -> dict[str, Any] | None:
        artifact = (
            self.db.query(ArtifactModel)
            .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == artifact_type)
            .order_by(ArtifactModel.id.desc())
            .first()
        )
        if not artifact:
            return None
        return _loads_dict(artifact.content_json)

    def run_events(self, run_id: str) -> list[RunEventModel]:
        return (
            self.db.query(RunEventModel)
            .filter(RunEventModel.run_id == run_id)
            .order_by(RunEventModel.id.asc())
            .all()
        )

    def run_artifacts(self, run_id: str) -> list[ArtifactModel]:
        return (
            self.db.query(ArtifactModel)
            .filter(ArtifactModel.run_id == run_id)
            .order_by(ArtifactModel.id.asc())
            .all()
        )

    def classify_run(self, run: RunModel) -> dict[str, str]:
        task = run.task or self.db.get(TaskModel, run.task_id)
        description = task.description if task else ""
        error = (run.error_message or "").lower()
        stage = str(run.current_stage or "")
        task_kind = run.task_kind or infer_task_kind(description)
        events = self.run_events(run.id)
        event_text = " ".join((event.message or "").lower() for event in events[-8:])

        failure_class = "unknown"
        failure_subclass = "general"
        recovery_status = "candidate" if run.status in {
            RunStatus.FAILED.value,
            RunStatus.BLOCKED.value,
            RunStatus.CHANGES_REQUESTED.value,
        } else "none"

        if "validation error" in error or "field required" in error or "pydantic" in error:
            failure_class = "schema_contract"
            failure_subclass = "missing_required_fields"
        elif any(token in error for token in _JSON_SCHEMA_ERROR_HINTS):
            failure_class = "schema_contract"
            failure_subclass = "invalid_json"
        elif "404 not found" in error or "/chat/completions" in error:
            failure_class = "provider_route"
            failure_subclass = "bad_provider_endpoint"
        elif "timed out" in error or "timeout" in error:
            failure_class = "provider_timeout"
            failure_subclass = "stage_timeout"
        elif "context error" in error or "context length" in error or "insufficient system resources" in error:
            failure_class = "provider_context"
            failure_subclass = "context_or_memory_pressure"
        elif "validation failed" in error:
            failure_class = "validation_profile"
            failure_subclass = "profile_command_failure"
        elif "promoted changes rolled back" in error:
            failure_class = "promotion_workflow"
            failure_subclass = "user_rollback"
            recovery_status = "manually_ignored"
        elif "workspace reset" in error:
            failure_class = "workspace_isolation"
            failure_subclass = "workspace_recreated"
            recovery_status = "manually_ignored"
        elif "diff not provided" in event_text or "unable to review" in event_text:
            failure_class = "review_loop"
            failure_subclass = "missing_review_context"
        elif task_kind == "analysis" and any(token in event_text for token in ("placeholder", "todo comment", "invent", "missing implementation")):
            failure_class = "repo_grounding"
            failure_subclass = "analysis_task_codegen_drift"
        elif any(token in error for token in ("runtime/workspaces", "copytree", "workspace")):
            failure_class = "workspace_isolation"
            failure_subclass = "workspace_clone_or_copy"
        elif any(event.event_type == "coder_guard_rejected" for event in events):
            failure_class = "repo_grounding"
            failure_subclass = "integrity_structural"
        elif any(
            event.event_type == "reviewer_requested_changes"
            and (
                "deterministic_guard" in str(_loads_dict(event.payload_json).get("source") or "")
                or "scope_guard" in str(_loads_dict(event.payload_json).get("source") or "")
            )
            for event in events
        ):
            failure_class = "review_loop"
            failure_subclass = "deterministic_guard"

        signature = f"{failure_class}:{stage or 'none'}:{task_kind}:{normalize_task_signature(description)}"
        return {
            "failure_class": failure_class,
            "failure_subclass": failure_subclass,
            "failure_signature": signature,
            "recovery_status": recovery_status if failure_class != "unknown" or run.status != RunStatus.COMPLETED.value else "none",
        }

    _RUN_OUTCOME_FIELDS = (
        "terminal_success",
        "terminal_status",
        "retry_count",
        "schema_failure_count",
        "reviewer_failure_count",
        "tester_failure_count",
        "operator_feedback_present",
        "approval_reached",
        "promote_rolled_back",
        "primary_failure_class",
    )

    def ensure_run_learning_state(self, run: RunModel) -> dict[str, str]:
        self.ensure_run_task_kind(run)
        classification = self.classify_run(run)
        changed = False
        for key, value in classification.items():
            if getattr(run, key) != value:
                setattr(run, key, value)
                changed = True
        needs_outcome_backfill = any(getattr(run, field, None) is None for field in self._RUN_OUTCOME_FIELDS)
        if changed or needs_outcome_backfill:
            outcomes = self._compute_run_outcomes(run, classification)
            for key, value in outcomes.items():
                setattr(run, key, value)
            self.db.commit()
            self.db.refresh(run)
        return classification

    def _save_artifact(self, run_id: str, artifact_type: str, content: dict[str, Any]) -> None:
        existing = (
            self.db.query(ArtifactModel)
            .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type == artifact_type)
            .order_by(ArtifactModel.id.desc())
            .first()
        )
        payload = json.dumps(content, ensure_ascii=True)
        if existing:
            existing.content_json = payload
        else:
            self.db.add(ArtifactModel(run_id=run_id, artifact_type=artifact_type, content_json=payload))
        self.db.commit()

    def build_postmortem(self, run: RunModel) -> dict[str, Any]:
        task = run.task or self.db.get(TaskModel, run.task_id)
        description = task.description if task else ""
        classification = self.classify_run(run)
        artifacts = self.run_artifacts(run.id)
        events = self.run_events(run.id)
        evidence_events = [
            {
                "id": event.id,
                "event_type": event.event_type,
                "stage": event.stage,
                "severity": event.severity,
                "message": event.message,
            }
            for event in events
            if event.severity in {"warning", "error"} or event.event_type.endswith("_failed")
        ][-6:]
        artifact_types = [artifact.artifact_type for artifact in artifacts]
        failure_class = classification["failure_class"]
        root_summary_map = {
            "schema_contract": "The model returned JSON that did not satisfy the required stage schema.",
            "provider_route": "The configured model provider endpoint or route was invalid for the selected provider.",
            "provider_timeout": "The selected model/provider did not respond within the configured stage timeout.",
            "provider_context": "The model failed under context or memory pressure.",
            "repo_grounding": "The stage drifted away from the actual repository structure or task intent.",
            "review_loop": "Reviewer feedback or review context caused an ineffective retry loop.",
            "validation_profile": "Deterministic validation commands failed for the selected validation profile.",
            "promotion_workflow": "A user-driven promotion or rollback action ended the run in a non-success state.",
            "workspace_isolation": "Workspace creation, reset, or promotion mechanics caused the run to stop or reset.",
            "unknown": "The run failed for an unclassified reason.",
        }
        recommendation_map = {
            "schema_contract": "Tighten stage prompt contracts or normalization so the provider output matches required schema fields.",
            "provider_route": "Verify provider selection, base URL, and stage model routing before retrying the run.",
            "provider_timeout": "Use provider fallback, lower-context prompts, or a faster stage model before retrying.",
            "provider_context": "Reduce context size or switch to a model that fits available memory.",
            "repo_grounding": "Increase repo-grounded context and constrain file targets to real workspace paths.",
            "review_loop": "Improve reviewer evidence and ensure coder retries receive concrete reviewer feedback.",
            "validation_profile": "Fix repo baseline issues or adjust deterministic validation commands to the actual repo layout.",
            "promotion_workflow": "Review operator action and restore or replay the run only if the change should be reattempted.",
            "workspace_isolation": "Inspect workspace clone, reset, or promotion path handling before replaying the run.",
            "unknown": "Inspect the final stage events and artifacts to derive a more specific recovery action.",
        }
        return {
            "run_id": run.id,
            "project_id": run.project_id,
            "terminal_status": run.status,
            "stage": run.current_stage,
            "task_kind": run.task_kind or infer_task_kind(description),
            "failure_class": failure_class,
            "failure_subclass": classification["failure_subclass"],
            "failure_signature": classification["failure_signature"],
            "root_cause_summary": root_summary_map[failure_class],
            "operator_visible_symptom": run.error_message or (
                evidence_events[-1]["message"] if evidence_events else "No explicit error message"
            ),
            "fix_recommendation": recommendation_map[failure_class],
            "confidence": 0.8 if failure_class != "unknown" else 0.4,
            "evidence": {
                "event_ids": [event["id"] for event in evidence_events],
                "artifact_types": artifact_types,
                "key_error_lines": [event["message"] for event in evidence_events[-3:]],
            },
        }

    def _count_failures(self, events: list[RunEventModel], stage: str) -> int:
        return sum(1 for event in events if event.stage == stage and event.event_type.endswith("_failed"))

    def _compute_run_outcomes(self, run: RunModel, classification: dict[str, str]) -> dict[str, Any]:
        events = self.run_events(run.id)
        return {
            "terminal_success": run.status in {RunStatus.COMPLETED.value, RunStatus.AWAITING_APPROVAL.value},
            "terminal_status": run.status,
            "retry_count": max(0, len([event for event in events if event.event_type == "run_retry_requested"]) + (1 if run.operator_feedback else 0)),
            "schema_failure_count": sum(
                1 for event in events if "validation errors for" in (event.message or "").lower()
            ),
            "reviewer_failure_count": self._count_failures(events, "reviewer"),
            "tester_failure_count": self._count_failures(events, "tester"),
            "operator_feedback_present": bool((run.operator_feedback or "").strip()),
            "approval_reached": any(event.event_type == "awaiting_approval" for event in events) or run.status in {
                RunStatus.AWAITING_APPROVAL.value,
                RunStatus.COMPLETED.value,
            },
            "promote_rolled_back": any(event.event_type == "run_changes_requested" and "rolled back" in (event.message or "").lower() for event in events),
            "primary_failure_class": classification["failure_class"] if run.status not in {
                RunStatus.COMPLETED.value,
                RunStatus.AWAITING_APPROVAL.value,
            } else None,
        }

    def _apply_run_outcomes(self, run: RunModel, outcomes: dict[str, Any]) -> None:
        for key, value in outcomes.items():
            setattr(run, key, value)
        self.db.commit()

    def _legacy_lesson_payload(
        self,
        run: RunModel,
        *,
        title: str,
        kind: str,
        summary: str,
        guidance: str,
        trigger_pattern: str,
        stages: list[str],
        confidence: float,
    ) -> dict[str, Any]:
        return {
            "title": title,
            "scope": "project",
            "source_run_id": run.id,
            "stages": stages,
            "kind": kind,
            "summary": summary,
            "trigger_pattern": trigger_pattern,
            "guidance": guidance,
            "confidence": round(max(0.0, min(confidence, 1.0)), 2),
            "applies_to_paths": [],
            "applies_to_task_kinds": [run.task_kind] if run.task_kind else [],
            "superseded": False,
            "created_at": datetime.now(UTC).isoformat(),
        }

    def _upsert_project_lesson(self, run: RunModel, payload: dict[str, Any]) -> LessonModel:
        lesson = (
            self.db.query(LessonModel)
            .filter(LessonModel.project_id == run.project_id, LessonModel.run_id == run.id, LessonModel.title == payload["title"])
            .first()
        )
        content = json.dumps(payload, indent=2, ensure_ascii=True)
        if lesson:
            lesson.content = content
        else:
            lesson = LessonModel(
                project_id=run.project_id,
                run_id=run.id,
                title=payload["title"],
                content=content,
            )
            self.db.add(lesson)
        self.db.commit()
        self.db.refresh(lesson)
        return lesson

    def _machine_guidance(self, run: RunModel, classification: dict[str, str], postmortem: dict[str, Any]) -> dict[str, Any]:
        task = run.task or self.db.get(TaskModel, run.task_id)
        task_signature = normalize_task_signature(task.description if task else "")
        return {
            "summary": postmortem["root_cause_summary"],
            "guidance": postmortem["fix_recommendation"],
            "task_signature": task_signature,
            "failure_signature": classification["failure_signature"],
            "failure_class": classification["failure_class"],
            "failure_subclass": classification["failure_subclass"],
        }

    def _derive_improvement_kind(self, run: RunModel, classification: dict[str, str]) -> str:
        failure_class = classification["failure_class"]
        if failure_class == "provider_context":
            return "provider_fallback_hint"
        if failure_class == "validation_profile":
            return "validation_hint"
        if failure_class == "review_loop":
            return "reviewer_hint"
        if failure_class in {"schema_contract", "repo_grounding", "workspace_isolation"}:
            return "routing_hint"
        return "failure_avoidance" if run.status != RunStatus.COMPLETED.value else "repo_convention"

    def _build_improvement_payload(self, run: RunModel, classification: dict[str, str], postmortem: dict[str, Any]) -> dict[str, Any]:
        task = run.task or self.db.get(TaskModel, run.task_id)
        description = task.description if task else ""
        task_kind = run.task_kind or infer_task_kind(description)
        task_signature = normalize_task_signature(description)
        stage = run.current_stage or "none"
        if run.status == RunStatus.COMPLETED.value:
            title = "Successful run path" if task_kind != "analysis" else "Analysis tasks should stay report-oriented"
            hypothesis = (
                "Reusing the successful repo-grounded planning and review flow should improve completion rate on comparable tasks."
            )
            summary = (
                "This run completed successfully with the current stage routing and validation behavior."
                if task_kind != "analysis"
                else "Analysis-style tasks succeeded when the pipeline stayed repo-grounded and produced report artifacts."
            )
            guidance = (
                "Reuse the same repo-grounded planning and reviewer feedback flow for similar tasks in this project."
                if task_kind != "analysis"
                else "Prefer report artifacts over speculative code changes for analysis tasks."
            )
            failure_class = None
            failure_subclass = None
            confidence = 0.82
        else:
            title = f"Avoid {postmortem['failure_class']} failures"
            hypothesis = f"Applying targeted guidance for {postmortem['failure_class']} should improve comparable task success rate."
            summary = postmortem["root_cause_summary"]
            guidance = postmortem["fix_recommendation"]
            failure_class = classification["failure_class"]
            failure_subclass = classification["failure_subclass"]
            confidence = float(postmortem["confidence"])
        cohort_key = build_cohort_key(run.project_id, task_signature, task_kind, stage)
        if run.status == RunStatus.COMPLETED.value:
            stages = self._derive_stages_from_artifacts(run.id) or ([stage] if stage and stage != "none" else [])
        else:
            stages = [stage] if stage and stage != "none" else []
        return {
            "title": title,
            "status": "candidate",
            "scope": "project",
            "kind": self._derive_improvement_kind(run, classification),
            "hypothesis": hypothesis,
            "summary": summary,
            "guidance": guidance,
            "failure_class": failure_class,
            "failure_subclass": failure_subclass,
            "task_kind": task_kind,
            "comparable_task_signature": task_signature,
            "cohort_key": cohort_key,
            "confidence": confidence,
            "stages": stages,
            "tags": [task_kind, task_signature],
            "machine_guidance": self._machine_guidance(run, classification, postmortem),
            "decision_metadata": {
                "source": "terminal_run",
                "trigger_pattern": classification["failure_signature"],
                "created_from_status": run.status,
            },
        }

    def _canonical_block_title(
        self,
        *,
        block_type: str,
        source: str,
        failure_class: str,
        failure_subclass: str,
    ) -> str:
        if block_type == "frontend_tsc":
            return "Avoid repeat frontend validation block"
        if source in {"reviewer", "deterministic_guard", "scope_guard"} or failure_class == "review_loop":
            return "Avoid repeat reviewer guard rejection"
        if source in {"validation", "validation_profile"} or failure_class == "validation_profile":
            return "Avoid repeat validation profile blockage"
        if source == "change_guard" or failure_subclass == "protected_path_block":
            return "Avoid repeat repository safety block"
        if block_type == "structural_guard" or failure_subclass == "integrity_structural":
            return "Avoid repeat structural integrity block"
        label = (failure_class or "workflow").replace("_", " ")
        return f"Avoid repeat {label} block"

    def _display_improvement_title(self, improvement: ImprovementModel) -> str:
        metadata = _loads_dict(improvement.decision_metadata_json)
        if metadata.get("source") == "block_resolution":
            return self._canonical_block_title(
                block_type=str(metadata.get("block_type") or ""),
                source=str(metadata.get("source_system") or ""),
                failure_class=str(improvement.failure_class or ""),
                failure_subclass=str(improvement.failure_subclass or ""),
            )
        return improvement.title

    def _derive_stages_from_artifacts(self, run_id: str) -> list[str]:
        found: set[str] = set()
        for artifact in self.run_artifacts(run_id):
            artifact_type = artifact.artifact_type
            if artifact_type == "plan":
                found.add("planner")
            elif artifact_type == "architect":
                found.add("architect")
            elif artifact_type == "ui_design":
                found.add("ui_designer")
            elif artifact_type == "coder":
                found.add("coder")
            elif artifact_type.startswith("review_"):
                found.add("reviewer")
            elif artifact_type == "test_plan":
                found.add("tester")
            elif artifact_type == "supervisor":
                found.add("supervisor")
        stages = [stage for stage in PIPELINE_STAGE_ORDER if stage in found]
        if "supervisor" in found:
            stages.append("supervisor")
        return stages

    def _count_project_failure_signature(self, project_id: str, failure_signature: str) -> int:
        if not failure_signature:
            return 0
        return (
            self.db.query(RunModel)
            .filter(
                RunModel.project_id == project_id,
                RunModel.failure_signature == failure_signature,
                RunModel.status.in_(
                    {
                        RunStatus.FAILED.value,
                        RunStatus.BLOCKED.value,
                        RunStatus.CHANGES_REQUESTED.value,
                    }
                ),
            )
            .count()
        )

    def _has_duplicate_approved_global_skill(self, trigger_pattern: str, stages: list[str]) -> bool:
        if not trigger_pattern or not stages:
            return False
        stage_set = set(stages)
        improvements = (
            self.db.query(ImprovementModel)
            .filter(ImprovementModel.scope == "global", ImprovementModel.status == "approved")
            .all()
        )
        for improvement in improvements:
            metadata = _loads_dict(improvement.decision_metadata_json)
            existing_trigger = str(metadata.get("trigger_pattern") or "")
            if existing_trigger != trigger_pattern:
                continue
            if stage_set.intersection(improvement.stages):
                return True
        return False

    def auto_promote_lesson_if_eligible(self, lesson: LessonModel, run: RunModel) -> dict[str, Any] | None:
        if run.status != RunStatus.COMPLETED.value:
            return None
        config = self._config()
        if not bool(config.get("learning_auto_promote_enabled", True)):
            return None

        parsed = _loads_dict(lesson.content)
        if bool(parsed.get("superseded")):
            return None

        kind = str(parsed.get("kind") or "")
        if kind not in AUTO_PROMOTABLE_LESSON_KINDS:
            return None

        confidence = float(parsed.get("confidence") or 0.0)
        if confidence < float(config.get("learning_min_confidence", 0.65)):
            return None

        stages = [str(stage) for stage in (parsed.get("stages") or []) if str(stage)]
        if kind in {"repo_convention", "task_intent_hint"}:
            artifact_stages = self._derive_stages_from_artifacts(run.id)
            if artifact_stages:
                stages = artifact_stages
                parsed["stages"] = stages
                lesson.content = json.dumps(parsed, indent=2, ensure_ascii=True)
                self.db.commit()

        if not stages:
            return None

        if self.db.query(GlobalSkillModel).filter(GlobalSkillModel.source_lesson_id == lesson.id).first():
            return None
        if (
            self.db.query(ImprovementModel)
            .filter(
                ImprovementModel.source_lesson_id == lesson.id,
                ImprovementModel.scope == "global",
                ImprovementModel.status == "approved",
            )
            .first()
        ):
            return None

        trigger_pattern = str(parsed.get("trigger_pattern") or run.failure_signature or "")
        if self._has_duplicate_approved_global_skill(trigger_pattern, stages):
            return None

        failure_class = str(parsed.get("failure_class") or run.failure_class or "")
        if kind == "failure_avoidance":
            failure_signature = str(parsed.get("failure_signature") or run.failure_signature or trigger_pattern)
            min_trials = int(config.get("learning_min_trial_runs", 3))
            if self._count_project_failure_signature(run.project_id, failure_signature) < min_trials:
                return None
            if failure_class == "unknown" and not bool(config.get("learning_unknown_failure_autopromote_enabled", False)):
                return None

        promoted = self.promote_lesson_to_global(lesson.id)
        self._emit_learning_event(
            run.id,
            "auto_promoted",
            f"Auto-promoted lesson to global skill: {lesson.title}",
            {"lesson_id": lesson.id, "improvement_id": promoted["id"], "kind": kind, "stages": stages},
        )
        return promoted

    def _update_global_skill_counters(self, run: RunModel) -> None:
        exposures = (
            self.db.query(ImprovementExposureModel)
            .filter(ImprovementExposureModel.run_id == run.id)
            .all()
        )
        if not exposures:
            return
        helpful = run.status == RunStatus.COMPLETED.value
        changed = False
        for exposure in exposures:
            improvement = self.db.get(ImprovementModel, exposure.improvement_id)
            if not improvement or improvement.scope != "global" or improvement.status != "approved":
                continue
            skill = self.db.get(GlobalSkillModel, improvement.id)
            if not skill:
                continue
            skill.times_applied += 1
            if helpful:
                skill.times_helpful += 1
            else:
                skill.times_harmful += 1
            changed = True
        if changed:
            self.db.commit()

    def _auto_deprecate_harmful_global_skills(self) -> None:
        config = self._config()
        max_rate = float(config.get("learning_max_harmful_rate_pct", 34.0))
        now = datetime.now(UTC)
        changed = False
        for skill in self.db.query(GlobalSkillModel).filter(GlobalSkillModel.promotion_state == "approved").all():
            if skill.times_applied <= 0:
                continue
            harmful_rate = (skill.times_harmful / skill.times_applied) * 100.0
            if harmful_rate <= max_rate:
                continue
            skill.promotion_state = "deprecated"
            improvement = self.db.get(ImprovementModel, skill.id)
            if improvement and improvement.status == "approved":
                improvement.status = "deprecated"
                improvement.deprecated_at = now
            changed = True
        if changed:
            self.db.commit()

    def _eligible_for_auto_trial(self, payload: dict[str, Any]) -> bool:
        config = self._config()
        if not bool(config.get("learning_auto_trial_enabled", True)):
            return False
        if float(payload.get("confidence") or 0.0) < float(config.get("learning_min_confidence", 0.65)):
            return False
        failure_class = str(payload.get("failure_class") or "")
        if failure_class == "unknown" and not bool(config.get("learning_unknown_failure_autopromote_enabled", False)):
            return False
        if failure_class and failure_class not in AUTO_PROMOTABLE_FAILURES:
            return False
        return True

    def _upsert_improvement(self, run: RunModel, payload: dict[str, Any], lesson_id: int | None = None) -> ImprovementModel:
        improvement = (
            self.db.query(ImprovementModel)
            .filter(ImprovementModel.project_id == run.project_id, ImprovementModel.source_run_id == run.id, ImprovementModel.title == payload["title"])
            .first()
        )
        now = datetime.now(UTC)
        initial_status = "trialing" if self._eligible_for_auto_trial(payload) else "candidate"
        if not improvement:
            improvement = ImprovementModel(
                project_id=run.project_id,
                source_run_id=run.id,
                source_lesson_id=lesson_id,
                title=payload["title"],
                status=initial_status,
                scope=str(payload["scope"]),
                kind=str(payload["kind"]),
                hypothesis=str(payload["hypothesis"]),
                failure_class=str(payload.get("failure_class") or "") or None,
                failure_subclass=str(payload.get("failure_subclass") or "") or None,
                task_kind=str(payload["task_kind"]),
                comparable_task_signature=str(payload["comparable_task_signature"]),
                cohort_key=str(payload["cohort_key"]),
                confidence=float(payload["confidence"]),
                machine_guidance_json=json.dumps(
                    {
                        "summary": payload["summary"],
                        "guidance": payload["guidance"],
                        **dict(payload["machine_guidance"]),
                    },
                    ensure_ascii=True,
                ),
                stages_json=json.dumps(payload["stages"]),
                tags_json=json.dumps(payload["tags"]),
                baseline_metrics_json="{}",
                trial_metrics_json="{}",
                decision_metadata_json=json.dumps(dict(payload["decision_metadata"]), ensure_ascii=True),
                trial_started_at=now if initial_status == "trialing" else None,
            )
            self.db.add(improvement)
            self.db.commit()
            self.db.refresh(improvement)
            self._emit_learning_event(
                run.id,
                "candidate_created",
                f"Created improvement candidate: {improvement.title}",
                {"improvement_id": improvement.id, "status": improvement.status, "scope": improvement.scope},
            )
            if improvement.status == "trialing":
                self._emit_learning_event(
                    run.id,
                    "trial_started",
                    f"Started trial for improvement: {improvement.title}",
                    {"improvement_id": improvement.id, "status": improvement.status},
                )
            return improvement

        improvement.source_lesson_id = lesson_id or improvement.source_lesson_id
        improvement.scope = str(payload["scope"])
        improvement.kind = str(payload["kind"])
        improvement.hypothesis = str(payload["hypothesis"])
        improvement.failure_class = str(payload.get("failure_class") or "") or None
        improvement.failure_subclass = str(payload.get("failure_subclass") or "") or None
        improvement.task_kind = str(payload["task_kind"])
        improvement.comparable_task_signature = str(payload["comparable_task_signature"])
        improvement.cohort_key = str(payload["cohort_key"])
        improvement.confidence = float(payload["confidence"])
        improvement.machine_guidance_json = json.dumps(
            {
                "summary": payload["summary"],
                "guidance": payload["guidance"],
                **dict(payload["machine_guidance"]),
            },
            ensure_ascii=True,
        )
        improvement.stages_json = json.dumps(payload["stages"])
        improvement.tags_json = json.dumps(payload["tags"])
        existing_meta = _loads_dict(improvement.decision_metadata_json)
        improvement.decision_metadata_json = json.dumps({**existing_meta, **dict(payload["decision_metadata"])}, ensure_ascii=True)
        if improvement.status == "candidate" and self._eligible_for_auto_trial(payload):
            improvement.status = "trialing"
            improvement.trial_started_at = improvement.trial_started_at or now
        self.db.commit()
        self.db.refresh(improvement)
        return improvement

    def _serialize_improvement(self, improvement: ImprovementModel) -> dict[str, Any]:
        guidance = _loads_dict(improvement.machine_guidance_json)
        baseline = _loads_dict(improvement.baseline_metrics_json)
        trial = _loads_dict(improvement.trial_metrics_json)
        decision = _loads_dict(improvement.decision_metadata_json)
        exposure_count = (
            self.db.query(ImprovementExposureModel)
            .filter(ImprovementExposureModel.improvement_id == improvement.id)
            .count()
        )
        display_title = self._display_improvement_title(improvement)
        return {
            "id": improvement.id,
            "project_id": improvement.project_id,
            "source_run_id": improvement.source_run_id,
            "source_lesson_id": improvement.source_lesson_id,
            "source_skill_id": improvement.source_skill_id,
            "title": improvement.title,
            "display_title": display_title,
            "status": improvement.status,
            "scope": improvement.scope,
            "kind": improvement.kind,
            "hypothesis": improvement.hypothesis,
            "failure_class": improvement.failure_class,
            "failure_subclass": improvement.failure_subclass,
            "task_kind": improvement.task_kind,
            "comparable_task_signature": improvement.comparable_task_signature,
            "cohort_key": improvement.cohort_key,
            "confidence": improvement.confidence,
            "content": {
                "summary": guidance.get("summary", ""),
                "guidance": guidance.get("guidance", ""),
                "stages": improvement.stages,
                "tags": improvement.tags,
                "machine_guidance": guidance,
            },
            "baseline_metrics": baseline,
            "trial_metrics": trial,
            "decision_metadata": decision,
            "exposure_count": exposure_count,
            "created_at": improvement.created_at.isoformat(),
            "updated_at": improvement.updated_at.isoformat(),
            "trial_started_at": improvement.trial_started_at.isoformat() if improvement.trial_started_at else None,
            "approved_at": improvement.approved_at.isoformat() if improvement.approved_at else None,
            "deprecated_at": improvement.deprecated_at.isoformat() if improvement.deprecated_at else None,
            "rejected_at": improvement.rejected_at.isoformat() if improvement.rejected_at else None,
        }

    def list_improvements(self, project_id: str | None = None, status: str | None = None, scope: str | None = None) -> list[dict[str, Any]]:
        query = self.db.query(ImprovementModel)
        if project_id:
            query = query.filter((ImprovementModel.project_id == project_id) | (ImprovementModel.scope == "global"))
        if status:
            query = query.filter(ImprovementModel.status == status)
        if scope:
            query = query.filter(ImprovementModel.scope == scope)
        improvements = query.order_by(ImprovementModel.updated_at.desc()).all()
        return [self._serialize_improvement(item) for item in improvements]

    def get_improvement(self, improvement_id: str) -> dict[str, Any]:
        improvement = self.db.get(ImprovementModel, improvement_id)
        if not improvement:
            raise ValueError("Improvement not found")
        return self._serialize_improvement(improvement)

    def list_improvement_exposures(self, improvement_id: str) -> list[dict[str, Any]]:
        rows = (
            self.db.query(ImprovementExposureModel)
            .filter(ImprovementExposureModel.improvement_id == improvement_id)
            .order_by(ImprovementExposureModel.created_at.desc())
            .all()
        )
        return [
            {
                "id": row.id,
                "improvement_id": row.improvement_id,
                "run_id": row.run_id,
                "stage": row.stage,
                "status_at_application": row.status_at_application,
                "scope": row.scope,
                "cohort_key": row.cohort_key,
                "task_signature": row.task_signature,
                "task_kind": row.task_kind,
                "exposure_kind": row.exposure_kind,
                "applied_context": _loads_dict(row.applied_context_json),
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    def _sync_legacy_global_skill(self, improvement: ImprovementModel) -> None:
        if improvement.scope != "global":
            return
        content = _loads_dict(improvement.machine_guidance_json)
        baseline = _loads_dict(improvement.baseline_metrics_json)
        trial = _loads_dict(improvement.trial_metrics_json)
        decision = _loads_dict(improvement.decision_metadata_json)
        existing = self.db.get(GlobalSkillModel, improvement.id)
        payload = {
            "title": improvement.title,
            "summary": content.get("summary", ""),
            "guidance": content.get("guidance", ""),
            "baseline_metrics": baseline,
            "trial_metrics": trial,
            "decision_metadata": decision,
        }
        if not existing:
            existing = GlobalSkillModel(
                id=improvement.id,
                name=improvement.title,
                summary=content.get("summary", ""),
                content=json.dumps(payload, ensure_ascii=True),
                source_lesson_id=improvement.source_lesson_id,
                source_run_id=improvement.source_run_id,
                origin_project_id=improvement.project_id,
                kind=improvement.kind,
                stages_json=json.dumps(improvement.stages),
                tags_json=json.dumps(improvement.tags),
                confidence=improvement.confidence,
                promotion_state=improvement.status,
            )
            self.db.add(existing)
        else:
            existing.name = improvement.title
            existing.summary = content.get("summary", "")
            existing.content = json.dumps(payload, ensure_ascii=True)
            existing.source_lesson_id = improvement.source_lesson_id
            existing.source_run_id = improvement.source_run_id
            existing.origin_project_id = improvement.project_id
            existing.kind = improvement.kind
            existing.stages_json = json.dumps(improvement.stages)
            existing.tags_json = json.dumps(improvement.tags)
            existing.confidence = improvement.confidence
            existing.promotion_state = improvement.status
        exposures = self.list_improvement_exposures(improvement.id)
        existing.times_applied = len(exposures)
        trial = _loads_dict(improvement.trial_metrics_json)
        existing.times_helpful = int(trial.get("successful_runs", 0))
        existing.times_harmful = int(trial.get("harmful_runs", 0))
        self.db.commit()

    def _record_exposure(
        self,
        run: RunModel,
        stage: str,
        improvement: ImprovementModel,
        task_signature: str,
        task_kind: str,
        exposure_kind: str,
    ) -> None:
        existing = (
            self.db.query(ImprovementExposureModel)
            .filter(
                ImprovementExposureModel.run_id == run.id,
                ImprovementExposureModel.improvement_id == improvement.id,
                ImprovementExposureModel.stage == stage,
            )
            .first()
        )
        payload = {
            "summary": _loads_dict(improvement.machine_guidance_json).get("summary", ""),
            "guidance": _loads_dict(improvement.machine_guidance_json).get("guidance", ""),
            "status": improvement.status,
        }
        if existing:
            existing.status_at_application = improvement.status
            existing.scope = improvement.scope
            existing.cohort_key = improvement.cohort_key
            existing.task_signature = task_signature
            existing.task_kind = task_kind
            existing.exposure_kind = exposure_kind
            existing.applied_context_json = json.dumps(payload, ensure_ascii=True)
        else:
            self.db.add(
                ImprovementExposureModel(
                    improvement_id=improvement.id,
                    run_id=run.id,
                    stage=stage,
                    status_at_application=improvement.status,
                    scope=improvement.scope,
                    cohort_key=improvement.cohort_key,
                    task_signature=task_signature,
                    task_kind=task_kind,
                    exposure_kind=exposure_kind,
                    applied_context_json=json.dumps(payload, ensure_ascii=True),
                )
            )
        self.db.commit()
        self._emit_learning_event(
            run.id,
            "improvement_exposed",
            f"Applied improvement: {improvement.title}",
            {"improvement_id": improvement.id, "stage": stage, "status": improvement.status, "exposure_kind": exposure_kind},
        )

    def _matching_improvements(self, run: RunModel, stage: str) -> list[ImprovementModel]:
        task = run.task or self.db.get(TaskModel, run.task_id)
        description = task.description if task else ""
        task_kind = run.task_kind or infer_task_kind(description)
        task_signature = normalize_task_signature(description)
        query = self.db.query(ImprovementModel).filter(
            ImprovementModel.status.in_(["trialing", "approved"]),
        )
        query = query.filter(
            (ImprovementModel.scope == "global")
            | ((ImprovementModel.scope == "project") & (ImprovementModel.project_id == run.project_id))
        )
        items = query.order_by(ImprovementModel.updated_at.desc()).all()
        matched: list[ImprovementModel] = []
        for improvement in items:
            if improvement.task_kind and improvement.task_kind not in {task_kind, "mixed"}:
                continue
            if improvement.comparable_task_signature and improvement.comparable_task_signature != task_signature:
                continue
            stages = improvement.stages
            if stages and stage not in stages:
                continue
            matched.append(improvement)
        return matched[:4]

    _BLOCK_GUIDANCE_MAX = 500
    _ENV_TOKEN = re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[=:]\s*\S+")

    def _sanitize_block_text(self, text: str, max_len: int | None = None) -> str:
        limit = max_len or self._BLOCK_GUIDANCE_MAX
        cleaned = self._ENV_TOKEN.sub(r"\1=[REDACTED]", str(text or ""))
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if len(cleaned) <= limit:
            return cleaned
        return f"{cleaned[: limit - 15]}...[truncated]"

    def _block_signature(self, stage: str, message: str) -> str:
        prefix = re.sub(r"\s+", " ", (message or "").strip())[:80].lower()
        return f"{stage}:{prefix}"

    def _load_block_artifact(self, run_id: str) -> dict[str, Any]:
        return self.terminal_artifact(run_id, "block_pending") or {"blocks": {}}

    def record_block(
        self,
        run_id: str,
        *,
        block_type: str,
        stage: str,
        source: str,
        message: str,
        guidance: str,
        target_stages: list[str],
    ) -> str:
        signature = self._block_signature(stage, message)
        artifact = self._load_block_artifact(run_id)
        blocks = artifact.setdefault("blocks", {})
        blocks[signature] = {
            "block_type": block_type,
            "stage": stage,
            "source": source,
            "message": self._sanitize_block_text(message),
            "guidance": self._sanitize_block_text(guidance),
            "target_stages": list(target_stages),
            "status": "pending",
            "signature": signature,
        }
        self._save_artifact(run_id, "block_pending", artifact)
        self._emit_learning_event(
            run_id,
            "block_recorded",
            f"Recorded block at {stage}: {self._sanitize_block_text(message, 120)}",
            {"signature": signature, "stage": stage, "source": source, "block_type": block_type},
        )
        return signature

    def _block_improvement_kind(self, block_type: str, source: str) -> str:
        if source in {"validation", "validation_profile"} or block_type == "validation_failure":
            return "validation_hint"
        if source in {"reviewer", "deterministic_guard", "scope_guard"} or block_type == "review_rejection":
            return "reviewer_hint"
        return "failure_avoidance"

    def _block_failure_class(self, block_type: str, source: str) -> tuple[str, str]:
        if source == "change_guard" or block_type == "structural_guard":
            return "repo_grounding", "integrity_structural"
        if source in {"deterministic_guard", "scope_guard", "reviewer"}:
            return "review_loop", "deterministic_guard"
        if source in {"validation", "validation_profile"}:
            return "validation_profile", "profile_command_failure"
        if source == "protected_path":
            return "repo_grounding", "protected_path_block"
        return "unknown", "block_resolution"

    def _upsert_block_lesson(self, run: RunModel, block: dict[str, Any], signature: str) -> LessonModel:
        failure_class, failure_subclass = self._block_failure_class(
            str(block.get("block_type") or ""),
            str(block.get("source") or ""),
        )
        title = self._canonical_block_title(
            block_type=str(block.get("block_type") or ""),
            source=str(block.get("source") or ""),
            failure_class=failure_class,
            failure_subclass=failure_subclass,
        )
        existing = (
            self.db.query(LessonModel)
            .filter(LessonModel.project_id == run.project_id, LessonModel.title == title)
            .first()
        )
        if existing:
            parsed = _loads_dict(existing.content)
            if parsed.get("failure_signature") == signature:
                return existing
        payload = self._legacy_lesson_payload(
            run,
            title=title,
            kind=self._block_improvement_kind(str(block.get("block_type") or ""), str(block.get("source") or "")),
            summary=str(block.get("message") or ""),
            guidance=str(block.get("guidance") or ""),
            trigger_pattern=signature,
            stages=[str(stage) for stage in (block.get("target_stages") or []) if str(stage)],
            confidence=0.78,
        )
        payload["failure_class"] = failure_class
        payload["failure_signature"] = signature
        payload["failure_subclass"] = failure_subclass
        return self._upsert_project_lesson(run, payload)

    def _upsert_block_improvement(
        self,
        run: RunModel,
        block: dict[str, Any],
        signature: str,
        lesson_id: int,
    ) -> ImprovementModel:
        task = run.task or self.db.get(TaskModel, run.task_id)
        description = task.description if task else ""
        task_kind = run.task_kind or infer_task_kind(description)
        task_signature = normalize_task_signature(description)
        failure_class, failure_subclass = self._block_failure_class(
            str(block.get("block_type") or ""),
            str(block.get("source") or ""),
        )
        title = self._canonical_block_title(
            block_type=str(block.get("block_type") or ""),
            source=str(block.get("source") or ""),
            failure_class=failure_class,
            failure_subclass=failure_subclass,
        )
        existing = (
            self.db.query(ImprovementModel)
            .filter(ImprovementModel.project_id == run.project_id, ImprovementModel.title == title)
            .first()
        )
        if existing:
            metadata = _loads_dict(existing.decision_metadata_json)
            if metadata.get("trigger_pattern") == signature:
                return existing
        stage = str(block.get("stage") or run.current_stage or "none")
        payload = {
            "title": title,
            "status": "candidate",
            "scope": "project",
            "kind": self._block_improvement_kind(str(block.get("block_type") or ""), str(block.get("source") or "")),
            "hypothesis": f"Avoiding repeat of block {signature} should improve success on comparable tasks.",
            "summary": str(block.get("message") or ""),
            "guidance": str(block.get("guidance") or ""),
            "failure_class": failure_class,
            "failure_subclass": failure_subclass,
            "task_kind": task_kind,
            "comparable_task_signature": task_signature,
            "cohort_key": build_cohort_key(run.project_id, task_signature, task_kind, stage),
            "confidence": 0.78,
            "stages": [str(item) for item in (block.get("target_stages") or []) if str(item)],
            "tags": [task_kind, task_signature, "block_resolution"],
            "machine_guidance": {
                "summary": str(block.get("message") or ""),
                "guidance": str(block.get("guidance") or ""),
                "task_signature": task_signature,
                "failure_signature": signature,
                "failure_class": failure_class,
                "failure_subclass": failure_subclass,
            },
            "decision_metadata": {
                "source": "block_resolution",
                "source_system": block.get("source"),
                "trigger_pattern": signature,
                "block_type": block.get("block_type"),
                "resolved_by_stage": block.get("retired_by_stage"),
            },
        }
        return self._upsert_improvement(run, payload, lesson_id)

    def retire_block_on_resolution(
        self,
        run_id: str,
        block_signature: str,
        *,
        resolved_by_stage: str,
    ) -> dict[str, Any] | None:
        artifact = self._load_block_artifact(run_id)
        blocks = artifact.get("blocks") or {}
        block = blocks.get(block_signature)
        if not block or block.get("status") == "retired":
            return None
        block["status"] = "retired"
        block["retired_by_stage"] = resolved_by_stage
        block["retired_at"] = datetime.now(UTC).isoformat()
        blocks[block_signature] = block
        artifact["blocks"] = blocks
        self._save_artifact(run_id, "block_pending", artifact)

        run = self.db.get(RunModel, run_id)
        if not run:
            return None
        lesson = self._upsert_block_lesson(run, block, block_signature)
        improvement = self._upsert_block_improvement(run, block, block_signature, lesson.id)
        self._emit_learning_event(
            run_id,
            "block_resolved",
            f"Retired block {block_signature} via {resolved_by_stage}",
            {
                "signature": block_signature,
                "resolved_by_stage": resolved_by_stage,
                "lesson_id": lesson.id,
                "improvement_id": improvement.id,
            },
        )
        return {
            "signature": block_signature,
            "guidance": block.get("guidance") or "",
            "message": block.get("message") or "",
            "target_stages": block.get("target_stages") or [],
        }

    def retire_pending_blocks(
        self,
        run_id: str,
        *,
        resolved_by_stage: str,
        stage: str | None = None,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        artifact = self._load_block_artifact(run_id)
        blocks = artifact.get("blocks") or {}
        retired: list[dict[str, Any]] = []
        for signature, block in list(blocks.items()):
            if block.get("status") != "pending":
                continue
            if stage and block.get("stage") != stage:
                continue
            if source and block.get("source") != source:
                continue
            result = self.retire_block_on_resolution(run_id, signature, resolved_by_stage=resolved_by_stage)
            if result:
                retired.append(result)
        return retired

    def get_retired_block_guidance(self, run_id: str, *, max_entries: int = 2) -> list[str]:
        artifact = self._load_block_artifact(run_id)
        blocks = artifact.get("blocks") or {}
        guidance: list[str] = []
        for block in blocks.values():
            if block.get("status") != "retired":
                continue
            text = str(block.get("guidance") or "").strip()
            if text and text not in guidance:
                guidance.append(text)
            if len(guidance) >= max_entries:
                break
        return guidance[:max_entries]

    def flush_unresolved_blocks(self, run: RunModel) -> None:
        artifact = self._load_block_artifact(run.id)
        blocks = artifact.get("blocks") or {}
        for signature, block in list(blocks.items()):
            if block.get("status") != "pending":
                continue
            self.retire_block_on_resolution(run.id, signature, resolved_by_stage="terminal_finalize")

    def build_learning_context(self, run: RunModel, stage: str, base_context: str) -> dict[str, Any]:
        task = run.task or self.db.get(TaskModel, run.task_id)
        description = task.description if task else ""
        task_kind = run.task_kind or infer_task_kind(description)
        task_signature = normalize_task_signature(description)
        matches: list[ImprovementMatch] = []
        project_improvements: list[dict[str, Any]] = []
        global_improvements: list[dict[str, Any]] = []
        for improvement in self._matching_improvements(run, stage):
            content = _loads_dict(improvement.machine_guidance_json)
            score = float(improvement.confidence or 0.5)
            if improvement.task_kind == task_kind:
                score += 4.0
            if stage in improvement.stages:
                score += 5.0
            if improvement.comparable_task_signature == task_signature:
                score += 3.0
            exposure_kind = "approved" if improvement.status == "approved" else "trial"
            self._record_exposure(run, stage, improvement, task_signature, task_kind, exposure_kind)
            matches.append(
                ImprovementMatch(
                    source_scope=improvement.scope,
                    source_id=improvement.id,
                    title=improvement.title,
                    summary=str(content.get("summary") or ""),
                    guidance=str(content.get("guidance") or ""),
                    score=score,
                    kind=improvement.kind,
                    status=improvement.status,
                    exposure_kind=exposure_kind,
                )
            )
        matches.sort(key=lambda item: item.score, reverse=True)
        top = matches[:4]
        block_top: list[ImprovementMatch] = []
        for item in matches:
            improvement_row = self.db.get(ImprovementModel, item.source_id)
            metadata = _loads_dict(improvement_row.decision_metadata_json) if improvement_row else {}
            if metadata.get("source") == "block_resolution":
                block_top.append(item)
            if len(block_top) >= 2:
                break
        if not top and not block_top:
            return {"context": base_context, "project_lessons": [], "global_skills": [], "improvements": []}
        lines: list[str] = []
        if block_top:
            lines.append("Resolved blocks to avoid (integrity charter overrides conflicting trial learnings):")
            for item in block_top:
                lines.append(f"- {item.title}: {item.guidance}")
        if top:
            if lines:
                lines.append("")
            lines.append("Relevant prior improvements:")
            for item in top:
                lines.append(
                    f"- [{item.source_scope}/{item.status}] {item.title}: {item.summary} Guidance: {item.guidance}"
                )
                payload = {
                    "id": item.source_id,
                    "title": item.title,
                    "score": round(item.score, 2),
                    "kind": item.kind,
                    "status": item.status,
                    "exposure_kind": item.exposure_kind,
                }
                if item.source_scope == "global":
                    global_improvements.append(payload)
                else:
                    project_improvements.append(payload)
        return {
            "context": f"{base_context}\n\n" + "\n".join(lines),
            "project_lessons": project_improvements,
            "global_skills": global_improvements,
            "improvements": project_improvements + global_improvements,
        }

    def _cohort_runs(
        self,
        improvement: ImprovementModel,
        *,
        before: bool | None = None,
    ) -> list[RunModel]:
        query = self.db.query(RunModel).filter(
            RunModel.project_id == improvement.project_id,
            RunModel.task_kind == improvement.task_kind,
        )
        runs = query.order_by(RunModel.created_at.asc()).all()
        cohort: list[RunModel] = []
        for run in runs:
            task = run.task or self.db.get(TaskModel, run.task_id)
            if not task:
                continue
            if normalize_task_signature(task.description) != improvement.comparable_task_signature:
                continue
            if before is True and run.created_at >= improvement.created_at:
                continue
            if before is False and run.created_at < (improvement.trial_started_at or improvement.created_at):
                continue
            cohort.append(run)
        return cohort

    def _rate_from_runs(self, runs: list[RunModel]) -> dict[str, Any]:
        for run in runs:
            self.ensure_run_learning_state(run)
        if not runs:
            return {
                "sample_size": 0,
                "success_rate": 0.0,
                "avg_retry_count": 0.0,
                "schema_failure_rate": 0.0,
                "reviewer_failure_rate": 0.0,
                "tester_failure_rate": 0.0,
                "rollback_rate": 0.0,
                "successful_runs": 0,
                "harmful_runs": 0,
            }
        success_values = [1.0 if bool(run.terminal_success) else 0.0 for run in runs]
        return {
            "sample_size": len(runs),
            "success_rate": round(mean(success_values) * 100.0, 2),
            "avg_retry_count": round(mean([int(run.retry_count or 0) for run in runs]), 2),
            "schema_failure_rate": round(mean([1.0 if int(run.schema_failure_count or 0) > 0 else 0.0 for run in runs]) * 100.0, 2),
            "reviewer_failure_rate": round(mean([1.0 if int(run.reviewer_failure_count or 0) > 0 else 0.0 for run in runs]) * 100.0, 2),
            "tester_failure_rate": round(mean([1.0 if int(run.tester_failure_count or 0) > 0 else 0.0 for run in runs]) * 100.0, 2),
            "rollback_rate": round(mean([1.0 if bool(run.promote_rolled_back) else 0.0 for run in runs]) * 100.0, 2),
            "successful_runs": sum(1 for run in runs if bool(run.terminal_success)),
            "harmful_runs": sum(1 for run in runs if not bool(run.terminal_success)),
        }

    def _trial_runs_for_improvement(self, improvement: ImprovementModel) -> list[RunModel]:
        exposures = (
            self.db.query(ImprovementExposureModel)
            .filter(ImprovementExposureModel.improvement_id == improvement.id)
            .all()
        )
        run_ids = {row.run_id for row in exposures}
        if not run_ids:
            return []
        return self.db.query(RunModel).filter(RunModel.id.in_(run_ids)).order_by(RunModel.created_at.asc()).all()

    def evaluate_improvement(self, improvement_id: str) -> dict[str, Any]:
        improvement = self.db.get(ImprovementModel, improvement_id)
        if not improvement:
            raise ValueError("Improvement not found")
        baseline_runs = self._cohort_runs(improvement, before=True)
        trial_runs = self._trial_runs_for_improvement(improvement)
        baseline = self._rate_from_runs(baseline_runs)
        trial = self._rate_from_runs(trial_runs)
        config = self._config()
        delta = round(float(trial["success_rate"]) - float(baseline["success_rate"]), 2)
        harmful_rate = float(trial["harmful_runs"]) / max(1, int(trial["sample_size"])) * 100.0 if trial["sample_size"] else 0.0
        eligible_samples = int(trial["sample_size"]) >= int(config.get("learning_min_trial_runs", 3))
        success_gate = delta >= float(config.get("learning_min_success_rate_delta_pct", 10.0))
        retry_gate = float(trial["avg_retry_count"]) <= float(baseline["avg_retry_count"] or 0.0)
        schema_gate = float(trial["schema_failure_rate"]) <= float(baseline["schema_failure_rate"] or 0.0)
        reviewer_gate = float(trial["reviewer_failure_rate"]) <= float(baseline["reviewer_failure_rate"] or 0.0)
        tester_gate = float(trial["tester_failure_rate"]) <= float(baseline["tester_failure_rate"] or 0.0)
        rollback_gate = float(trial["rollback_rate"]) <= 0.0
        harmful_gate = harmful_rate <= float(config.get("learning_max_harmful_rate_pct", 34.0))
        guardrails_ok = retry_gate and schema_gate and reviewer_gate and tester_gate and rollback_gate and harmful_gate

        decision = {
            "evaluated_at": datetime.now(UTC).isoformat(),
            "success_rate_delta_pct": delta,
            "sample_size": int(trial["sample_size"]),
            "eligible_samples": eligible_samples,
            "guardrails_ok": guardrails_ok,
            "success_gate": success_gate,
            "retry_gate": retry_gate,
            "schema_gate": schema_gate,
            "reviewer_gate": reviewer_gate,
            "tester_gate": tester_gate,
            "rollback_gate": rollback_gate,
            "harmful_rate_pct": round(harmful_rate, 2),
            "harmful_gate": harmful_gate,
            "decision_reason": "Awaiting more evidence",
        }

        if improvement.status == "trialing" and eligible_samples and guardrails_ok and success_gate and bool(
            config.get("learning_auto_promote_enabled", True)
        ):
            improvement.status = "approved"
            improvement.scope = "global" if improvement.scope == "global" else improvement.scope
            improvement.approved_at = datetime.now(UTC)
            decision["decision_reason"] = "Auto-promoted after meeting trial sample and success gates."
        elif improvement.status == "approved" and eligible_samples and (not guardrails_ok or delta < 0):
            improvement.status = "deprecated"
            improvement.deprecated_at = datetime.now(UTC)
            decision["decision_reason"] = "Auto-deprecated after harmful trend or guardrail regression."
        elif improvement.status == "trialing" and eligible_samples and (not harmful_gate or float(trial["rollback_rate"]) > 0.0):
            improvement.status = "rejected"
            improvement.rejected_at = datetime.now(UTC)
            decision["decision_reason"] = "Rejected trial after harmful or rollback regression."

        improvement.baseline_metrics_json = json.dumps(baseline, ensure_ascii=True)
        improvement.trial_metrics_json = json.dumps(trial, ensure_ascii=True)
        prior_meta = _loads_dict(improvement.decision_metadata_json)
        prior_meta.update(decision)
        improvement.decision_metadata_json = json.dumps(prior_meta, ensure_ascii=True)
        self.db.commit()
        self.db.refresh(improvement)
        if improvement.scope == "global":
            self._sync_legacy_global_skill(improvement)
        return self._serialize_improvement(improvement)

    def _evaluate_related_improvements(self, run: RunModel) -> None:
        improvement_ids = {
            row.improvement_id
            for row in self.db.query(ImprovementExposureModel).filter(ImprovementExposureModel.run_id == run.id).all()
        }
        created = self.db.query(ImprovementModel).filter(ImprovementModel.source_run_id == run.id).all()
        improvement_ids.update(item.id for item in created)
        for improvement_id in sorted(improvement_ids):
            before = self.db.get(ImprovementModel, improvement_id)
            if not before:
                continue
            previous_status = before.status
            result = self.evaluate_improvement(improvement_id)
            next_status = str(result["status"])
            if previous_status != next_status:
                event_type = "auto_promoted" if next_status == "approved" else "auto_deprecated"
                self._emit_learning_event(
                    run.id,
                    event_type,
                    f"Improvement {result['title']} is now {next_status}",
                    {"improvement_id": result["id"], "status": next_status, "decision_metadata": result["decision_metadata"]},
                )

    def finalize_terminal_run(self, run_id: str) -> None:
        run = self.db.get(RunModel, run_id)
        if not run:
            return
        classification = self.ensure_run_learning_state(run)

        if run.status in {RunStatus.FAILED.value, RunStatus.BLOCKED.value, RunStatus.CHANGES_REQUESTED.value}:
            self._save_artifact(run.id, "postmortem", self.build_postmortem(run))

        lesson: LessonModel | None = None
        improvement: ImprovementModel | None = None
        auto_promoted: dict[str, Any] | None = None

        if run.status != RunStatus.AWAITING_APPROVAL.value:
            postmortem = self.build_postmortem(run)
            payload = self._build_improvement_payload(run, classification, postmortem)
            lesson_payload = self._legacy_lesson_payload(
                run,
                title=payload["title"],
                kind=payload["kind"],
                summary=payload["summary"],
                guidance=payload["guidance"],
                trigger_pattern=classification["failure_signature"],
                stages=list(payload["stages"]),
                confidence=float(payload["confidence"]),
            )
            if classification.get("failure_class"):
                lesson_payload["failure_class"] = classification["failure_class"]
                lesson_payload["failure_signature"] = classification["failure_signature"]
            lesson = self._upsert_project_lesson(run, lesson_payload)
            improvement = self._upsert_improvement(run, payload, lesson.id)
            if run.status == RunStatus.COMPLETED.value:
                auto_promoted = self.auto_promote_lesson_if_eligible(lesson, run)

        if run.status == RunStatus.COMPLETED.value:
            self._mark_superseded_failures(run)
        if not run.superseded_by_run_id and run.recovery_status not in RECOVERY_STATUSES:
            run.recovery_status = "none"
            self.db.commit()
        if lesson and improvement:
            summary: dict[str, Any] = {
                "lesson_id": lesson.id,
                "improvement_id": improvement.id,
                "title": lesson.title,
                "scope": improvement.scope,
                "status": improvement.status,
                "failure_class": run.failure_class,
                "recovery_status": run.recovery_status,
            }
            if auto_promoted:
                summary["auto_promoted_improvement_id"] = auto_promoted["id"]
            self._save_artifact(run.id, "learning_summary", summary)
        self._update_global_skill_counters(run)
        self._auto_deprecate_harmful_global_skills()
        self._evaluate_related_improvements(run)
        if run.status in {
            RunStatus.FAILED.value,
            RunStatus.BLOCKED.value,
            RunStatus.CHANGES_REQUESTED.value,
        }:
            self.flush_unresolved_blocks(run)

    def _mark_superseded_failures(self, successful_run: RunModel) -> None:
        task = successful_run.task or self.db.get(TaskModel, successful_run.task_id)
        if not task:
            return
        signature = normalize_task_signature(task.description)
        failures = (
            self.db.query(RunModel)
            .filter(
                RunModel.project_id == successful_run.project_id,
                RunModel.id != successful_run.id,
                RunModel.status.in_([RunStatus.FAILED.value, RunStatus.BLOCKED.value, RunStatus.CHANGES_REQUESTED.value]),
            )
            .all()
        )
        for run in failures:
            task_row = run.task or self.db.get(TaskModel, run.task_id)
            if not task_row:
                continue
            if normalize_task_signature(task_row.description) != signature:
                continue
            if run.failure_class:
                run.recovery_status = "superseded"
                run.superseded_by_run_id = successful_run.id
        self.db.commit()

    def failure_summary(self, project_id: str | None = None) -> dict[str, Any]:
        query = self.db.query(RunModel).filter(
            RunModel.status.in_([RunStatus.FAILED.value, RunStatus.BLOCKED.value, RunStatus.CHANGES_REQUESTED.value])
        )
        if project_id:
            query = query.filter(RunModel.project_id == project_id)
        runs = query.order_by(RunModel.created_at.desc()).all()
        for run in runs:
            self.ensure_run_learning_state(run)
        grouped: dict[str, dict[str, Any]] = {}
        for run in runs:
            key = run.failure_class or "unknown"
            bucket = grouped.setdefault(key, {"count": 0, "actionable": 0, "runs": []})
            bucket["count"] += 1
            if run.recovery_status not in {"superseded", "manually_ignored"}:
                bucket["actionable"] += 1
            bucket["runs"].append(
                {
                    "id": run.id,
                    "status": run.status,
                    "current_stage": run.current_stage,
                    "error_message": run.error_message,
                    "failure_subclass": run.failure_subclass,
                    "recovery_status": run.recovery_status,
                    "superseded_by_run_id": run.superseded_by_run_id,
                    "created_at": run.created_at.isoformat(),
                }
            )
        return {"groups": grouped, "total_runs": len(runs)}

    def list_project_lessons(self, project_id: str) -> list[dict[str, Any]]:
        improvements = (
            self.db.query(ImprovementModel)
            .filter(ImprovementModel.project_id == project_id, ImprovementModel.scope == "project")
            .order_by(ImprovementModel.updated_at.desc())
            .all()
        )
        items: list[dict[str, Any]] = []
        for improvement in improvements:
            content = _loads_dict(improvement.machine_guidance_json)
            display_title = self._display_improvement_title(improvement)
            items.append(
                {
                    "id": improvement.source_lesson_id or 0,
                    "project_id": project_id,
                    "run_id": improvement.source_run_id,
                    "title": display_title,
                    "content": {
                        "title": display_title,
                        "scope": improvement.scope,
                        "source_run_id": improvement.source_run_id,
                        "stages": improvement.stages,
                        "kind": improvement.kind,
                        "summary": content.get("summary", ""),
                        "trigger_pattern": _loads_dict(improvement.decision_metadata_json).get("trigger_pattern", ""),
                        "guidance": content.get("guidance", ""),
                        "confidence": improvement.confidence,
                        "applies_to_paths": [],
                        "applies_to_task_kinds": [improvement.task_kind] if improvement.task_kind else [],
                        "superseded": improvement.status in {"deprecated", "rejected"},
                        "improvement_id": improvement.id,
                        "status": improvement.status,
                        "baseline_metrics": _loads_dict(improvement.baseline_metrics_json),
                        "trial_metrics": _loads_dict(improvement.trial_metrics_json),
                        "decision_metadata": _loads_dict(improvement.decision_metadata_json),
                    },
                    "created_at": improvement.created_at.isoformat(),
                }
            )
        return items

    def list_global_skills(self) -> list[dict[str, Any]]:
        improvements = (
            self.db.query(ImprovementModel)
            .filter(ImprovementModel.scope == "global")
            .order_by(ImprovementModel.updated_at.desc())
            .all()
        )
        rows: list[dict[str, Any]] = []
        for improvement in improvements:
            content = _loads_dict(improvement.machine_guidance_json)
            trial = _loads_dict(improvement.trial_metrics_json)
            display_title = self._display_improvement_title(improvement)
            rows.append(
                {
                    "id": improvement.id,
                    "name": display_title,
                    "summary": content.get("summary", ""),
                    "content": {
                        "summary": content.get("summary", ""),
                        "guidance": content.get("guidance", ""),
                        "baseline_metrics": _loads_dict(improvement.baseline_metrics_json),
                        "trial_metrics": trial,
                        "decision_metadata": _loads_dict(improvement.decision_metadata_json),
                    },
                    "source_lesson_id": improvement.source_lesson_id,
                    "source_run_id": improvement.source_run_id,
                    "origin_project_id": improvement.project_id,
                    "kind": improvement.kind,
                    "stages": improvement.stages,
                    "tags": improvement.tags,
                    "confidence": improvement.confidence,
                    "promotion_state": improvement.status,
                    "times_applied": len(self.list_improvement_exposures(improvement.id)),
                    "times_helpful": int(trial.get("successful_runs", 0)),
                    "times_harmful": int(trial.get("harmful_runs", 0)),
                    "created_at": improvement.created_at.isoformat(),
                    "updated_at": improvement.updated_at.isoformat(),
                }
            )
        return rows

    def promote_lesson_to_global(self, lesson_id: int) -> dict[str, Any]:
        lesson = self.db.get(LessonModel, lesson_id)
        if not lesson:
            raise ValueError("Lesson not found")
        parsed = _loads_dict(lesson.content)
        improvement = (
            self.db.query(ImprovementModel)
            .filter(
                (ImprovementModel.source_lesson_id == lesson_id)
                | ((ImprovementModel.source_run_id == lesson.run_id) & (ImprovementModel.title == lesson.title))
            )
            .first()
        )
        if not improvement:
            task_kind = str((parsed.get("applies_to_task_kinds") or ["implementation"])[0])
            signature = str(parsed.get("trigger_pattern") or normalize_task_signature(parsed.get("summary") or lesson.title))
            improvement = ImprovementModel(
                project_id=lesson.project_id,
                source_run_id=lesson.run_id,
                source_lesson_id=lesson.id,
                title=str(parsed.get("title") or lesson.title),
                status="approved",
                scope="global",
                kind=str(parsed.get("kind") or "repo_convention"),
                hypothesis=f"Promoted legacy lesson {lesson.title} for global reuse.",
                failure_class=None,
                failure_subclass=None,
                task_kind=task_kind,
                comparable_task_signature=signature.split(":")[-1],
                cohort_key=build_cohort_key(lesson.project_id, signature.split(":")[-1], task_kind),
                confidence=float(parsed.get("confidence") or 0.5),
                machine_guidance_json=json.dumps(
                    {
                        "summary": str(parsed.get("summary") or ""),
                        "guidance": str(parsed.get("guidance") or ""),
                    },
                    ensure_ascii=True,
                ),
                stages_json=json.dumps(parsed.get("stages") or []),
                tags_json=json.dumps(list(parsed.get("applies_to_task_kinds") or [])),
                approved_at=datetime.now(UTC),
                decision_metadata_json=json.dumps(
                    {
                        "source": "legacy_promotion",
                        "trigger_pattern": str(parsed.get("trigger_pattern") or ""),
                    },
                    ensure_ascii=True,
                ),
            )
            self.db.add(improvement)
        else:
            improvement.scope = "global"
            improvement.status = "approved"
            improvement.approved_at = datetime.now(UTC)
            lesson_stages = parsed.get("stages") or improvement.stages
            if lesson_stages:
                improvement.stages_json = json.dumps(lesson_stages)
            prior_meta = _loads_dict(improvement.decision_metadata_json)
            prior_meta.setdefault("trigger_pattern", str(parsed.get("trigger_pattern") or ""))
            improvement.decision_metadata_json = json.dumps(prior_meta, ensure_ascii=True)
        self.db.commit()
        self.db.refresh(improvement)
        self._sync_legacy_global_skill(improvement)
        return self.get_improvement(improvement.id)

    def override_improvement_status(self, improvement_id: str, status: str, scope: str | None = None) -> dict[str, Any]:
        if status not in IMPROVEMENT_STATUSES:
            raise ValueError("Invalid improvement status")
        improvement = self.db.get(ImprovementModel, improvement_id)
        if not improvement:
            raise ValueError("Improvement not found")
        improvement.status = status
        if scope:
            improvement.scope = scope
        now = datetime.now(UTC)
        if status == "approved":
            improvement.approved_at = now
        elif status == "deprecated":
            improvement.deprecated_at = now
        elif status == "rejected":
            improvement.rejected_at = now
        prior_meta = _loads_dict(improvement.decision_metadata_json)
        prior_meta["override_applied_at"] = now.isoformat()
        prior_meta["override_status"] = status
        improvement.decision_metadata_json = json.dumps(prior_meta, ensure_ascii=True)
        self.db.commit()
        self.db.refresh(improvement)
        if improvement.scope == "global":
            self._sync_legacy_global_skill(improvement)
        self._emit_learning_event(
            improvement.source_run_id or improvement.id,
            "override_applied",
            f"Improvement {improvement.title} overridden to {status}",
            {"improvement_id": improvement.id, "status": status, "scope": improvement.scope},
        )
        return self.get_improvement(improvement.id)

    def deprecate_global_skill(self, skill_id: str) -> dict[str, Any]:
        improvement = self.db.get(ImprovementModel, skill_id)
        if improvement:
            return self.override_improvement_status(skill_id, "deprecated", scope="global")
        skill = self.db.get(GlobalSkillModel, skill_id)
        if not skill:
            raise ValueError("Global skill not found")
        skill.promotion_state = "deprecated"
        self.db.commit()
        return {"ok": True, "id": skill.id, "promotion_state": skill.promotion_state}
