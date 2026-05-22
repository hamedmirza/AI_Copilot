from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import RunStatus
from app.db.models import (
    ArtifactModel,
    GlobalSkillModel,
    LessonModel,
    RunEventModel,
    RunModel,
    TaskModel,
)


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

_ANALYSIS_HINTS = ("review", "audit", "analyze", "analyse", "inspect", "assess", "trace", "surface", "map")
_IMPLEMENTATION_HINTS = ("implement", "build", "fix", "change", "update", "create", "add", "replace", "refactor")
_DEBUG_HINTS = ("debug", "diagnose", "investigate", "why", "failing", "fails", "broken")
_VALIDATION_HINTS = ("validate", "verification", "verify", "test", "tests", "quality gate")
_PLAYBOOK_HINTS = ("playbook", "runbook", "procedure", "operational")
_STOPWORDS = {
    "the", "and", "that", "with", "from", "into", "this", "these", "those", "task", "repo",
    "application", "project", "agent", "run", "issue", "issues", "current", "future", "failed",
}


@dataclass
class LessonMatch:
    source_scope: str
    source_id: str
    title: str
    summary: str
    guidance: str
    score: float
    kind: str


def infer_task_kind(description: str) -> str:
    lower = (description or "").lower()
    scores = {
        "analysis": sum(1 for hint in _ANALYSIS_HINTS if hint in lower),
        "implementation": sum(1 for hint in _IMPLEMENTATION_HINTS if hint in lower),
        "debug": sum(1 for hint in _DEBUG_HINTS if hint in lower),
        "validation": sum(1 for hint in _VALIDATION_HINTS if hint in lower),
        "playbook": sum(1 for hint in _PLAYBOOK_HINTS if hint in lower),
    }
    best_kind = max(scores, key=scores.get)
    best_score = scores[best_kind]
    if best_score <= 0:
        return "implementation"
    competing = [kind for kind, score in scores.items() if score == best_score]
    return best_kind if len(competing) == 1 else "mixed"


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
        recovery_status = "candidate" if run.status in {RunStatus.FAILED.value, RunStatus.BLOCKED.value, RunStatus.CHANGES_REQUESTED.value} else "none"

        if "validation error" in error or "field required" in error or "pydantic" in error:
            failure_class = "schema_contract"
            failure_subclass = "missing_required_fields"
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

        signature = f"{failure_class}:{stage or 'none'}:{task_kind}:{normalize_task_signature(description)}"
        return {
            "failure_class": failure_class,
            "failure_subclass": failure_subclass,
            "failure_signature": signature,
            "recovery_status": recovery_status if failure_class != "unknown" or run.status != RunStatus.COMPLETED.value else "none",
        }

    def _lesson_payload(
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
        applies_to_paths: list[str] | None = None,
        applies_to_task_kinds: list[str] | None = None,
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
            "applies_to_paths": applies_to_paths or [],
            "applies_to_task_kinds": applies_to_task_kinds or ([run.task_kind] if run.task_kind else []),
            "superseded": False,
            "created_at": datetime.now(UTC).isoformat(),
        }

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
            "operator_visible_symptom": run.error_message or (evidence_events[-1]["message"] if evidence_events else "No explicit error message"),
            "fix_recommendation": recommendation_map[failure_class],
            "confidence": 0.8 if failure_class != "unknown" else 0.4,
            "evidence": {
                "event_ids": [event["id"] for event in evidence_events],
                "artifact_types": artifact_types,
                "key_error_lines": [event["message"] for event in evidence_events[-3:]],
            },
        }

    def build_lesson_candidate(self, run: RunModel) -> dict[str, Any]:
        task = run.task or self.db.get(TaskModel, run.task_id)
        description = task.description if task else ""
        task_kind = run.task_kind or infer_task_kind(description)
        artifacts = [artifact.artifact_type for artifact in self.run_artifacts(run.id)]

        if run.status == RunStatus.COMPLETED.value:
            if task_kind == "analysis":
                title = "Analysis tasks should stay report-oriented"
                summary = "Analysis-style tasks succeeded when the pipeline stayed repo-grounded and produced report artifacts instead of speculative code changes."
                guidance = "Prefer `.ai-copilot/reports/` outputs for audit/review tasks and skip deterministic validation when only report artifacts changed."
                trigger = "task_kind=analysis and coder targets documentation/report artifacts"
                kind = "task_intent_hint"
            else:
                title = "Successful run path"
                summary = "This run completed successfully with the current stage routing and validation behavior."
                guidance = "Reuse the same repo-grounded planning and reviewer feedback flow for similar tasks in this project."
                trigger = "similar task signature and stage flow"
                kind = "repo_convention"
            return self._lesson_payload(
                run,
                title=title,
                kind=kind,
                summary=summary,
                guidance=guidance,
                trigger_pattern=trigger,
                stages=[stage for stage in [run.current_stage] if stage],
                confidence=0.82,
            )

        postmortem = self.build_postmortem(run)
        return self._lesson_payload(
            run,
            title=f"Avoid {postmortem['failure_class']} failures",
            kind="failure_avoidance",
            summary=postmortem["root_cause_summary"],
            guidance=postmortem["fix_recommendation"],
            trigger_pattern=postmortem["failure_signature"],
            stages=[stage for stage in [run.current_stage] if stage],
            confidence=float(postmortem["confidence"]),
        )

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

    def finalize_terminal_run(self, run_id: str) -> None:
        run = self.db.get(RunModel, run_id)
        if not run:
            return
        self.ensure_run_task_kind(run)
        classification = self.classify_run(run)
        changed = False
        for key, value in classification.items():
            if getattr(run, key) != value:
                setattr(run, key, value)
                changed = True
        if changed:
            self.db.commit()

        if run.status in {RunStatus.FAILED.value, RunStatus.BLOCKED.value, RunStatus.CHANGES_REQUESTED.value}:
            self._save_artifact(run.id, "postmortem", self.build_postmortem(run))
        lesson_candidate = self.build_lesson_candidate(run)
        self._save_artifact(run.id, "run_lesson_candidate", lesson_candidate)
        lesson = self._upsert_project_lesson(run, lesson_candidate)
        if run.status == RunStatus.COMPLETED.value:
            self._mark_superseded_failures(run)
        self._update_global_skill_counters(run)
        if not run.superseded_by_run_id and run.recovery_status not in RECOVERY_STATUSES:
            run.recovery_status = "none"
            self.db.commit()
        self._save_artifact(
            run.id,
            "learning_summary",
            {
                "lesson_id": lesson.id,
                "title": lesson.title,
                "scope": "project",
                "failure_class": run.failure_class,
                "recovery_status": run.recovery_status,
            },
        )

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

    def _update_global_skill_counters(self, run: RunModel) -> None:
        events = self.run_events(run.id)
        applied_ids: set[str] = set()
        for event in events:
            if event.event_type != "lessons_applied":
                continue
            payload = _loads_dict(event.payload_json)
            for item in payload.get("global_skills", []) or []:
                skill_id = str(item.get("id") or "")
                if skill_id:
                    applied_ids.add(skill_id)
        if not applied_ids:
            return
        terminal_success = run.status == RunStatus.COMPLETED.value
        for skill_id in applied_ids:
            skill = self.db.get(GlobalSkillModel, skill_id)
            if not skill:
                continue
            skill.times_applied += 1
            if terminal_success:
                skill.times_helpful += 1
            else:
                skill.times_harmful += 1
        self.db.commit()

    def list_project_lessons(self, project_id: str) -> list[dict[str, Any]]:
        lessons = (
            self.db.query(LessonModel)
            .filter(LessonModel.project_id == project_id)
            .order_by(LessonModel.created_at.desc())
            .all()
        )
        items: list[dict[str, Any]] = []
        for lesson in lessons:
            parsed = _loads_dict(lesson.content)
            items.append(
                {
                    "id": lesson.id,
                    "project_id": lesson.project_id,
                    "run_id": lesson.run_id,
                    "title": lesson.title,
                    "content": parsed or {"body": lesson.content},
                    "created_at": lesson.created_at.isoformat(),
                }
            )
        return items

    def list_global_skills(self) -> list[dict[str, Any]]:
        skills = self.db.query(GlobalSkillModel).order_by(GlobalSkillModel.updated_at.desc()).all()
        return [
            {
                "id": skill.id,
                "name": skill.name,
                "summary": skill.summary,
                "content": _loads_dict(skill.content) or {"body": skill.content},
                "source_lesson_id": skill.source_lesson_id,
                "source_run_id": skill.source_run_id,
                "origin_project_id": skill.origin_project_id,
                "kind": skill.kind,
                "stages": skill.stages,
                "tags": skill.tags,
                "confidence": skill.confidence,
                "promotion_state": skill.promotion_state,
                "times_applied": skill.times_applied,
                "times_helpful": skill.times_helpful,
                "times_harmful": skill.times_harmful,
                "created_at": skill.created_at.isoformat(),
                "updated_at": skill.updated_at.isoformat(),
            }
            for skill in skills
        ]

    def promote_lesson_to_global(self, lesson_id: int) -> dict[str, Any]:
        lesson = self.db.get(LessonModel, lesson_id)
        if not lesson:
            raise ValueError("Lesson not found")
        parsed = _loads_dict(lesson.content)
        title = str(parsed.get("title") or lesson.title)
        existing = (
            self.db.query(GlobalSkillModel)
            .filter(GlobalSkillModel.source_lesson_id == lesson.id)
            .first()
        )
        if existing:
            existing.name = title
            existing.summary = str(parsed.get("summary") or "")
            existing.content = json.dumps(parsed, ensure_ascii=True)
            existing.kind = str(parsed.get("kind") or "repo_convention")
            existing.stages_json = json.dumps(parsed.get("stages") or [])
            tags = list(parsed.get("applies_to_task_kinds") or []) + list(parsed.get("applies_to_paths") or [])
            existing.tags_json = json.dumps(tags)
            existing.confidence = float(parsed.get("confidence") or 0.5)
            existing.promotion_state = "approved"
            self.db.commit()
            return self.list_global_skills()[0]

        skill = GlobalSkillModel(
            name=title,
            summary=str(parsed.get("summary") or ""),
            content=json.dumps(parsed, ensure_ascii=True),
            source_lesson_id=lesson.id,
            source_run_id=lesson.run_id,
            origin_project_id=lesson.project_id,
            kind=str(parsed.get("kind") or "repo_convention"),
            stages_json=json.dumps(parsed.get("stages") or []),
            tags_json=json.dumps(list(parsed.get("applies_to_task_kinds") or []) + list(parsed.get("applies_to_paths") or [])),
            confidence=float(parsed.get("confidence") or 0.5),
            promotion_state="approved",
        )
        self.db.add(skill)
        self.db.commit()
        self.db.refresh(skill)
        return {
            "id": skill.id,
            "name": skill.name,
            "summary": skill.summary,
            "content": _loads_dict(skill.content) or {"body": skill.content},
            "source_lesson_id": skill.source_lesson_id,
            "source_run_id": skill.source_run_id,
            "origin_project_id": skill.origin_project_id,
            "kind": skill.kind,
            "stages": skill.stages,
            "tags": skill.tags,
            "confidence": skill.confidence,
            "promotion_state": skill.promotion_state,
            "times_applied": skill.times_applied,
            "times_helpful": skill.times_helpful,
            "times_harmful": skill.times_harmful,
            "created_at": skill.created_at.isoformat(),
            "updated_at": skill.updated_at.isoformat(),
        }

    def deprecate_global_skill(self, skill_id: str) -> dict[str, Any]:
        skill = self.db.get(GlobalSkillModel, skill_id)
        if not skill:
            raise ValueError("Global skill not found")
        skill.promotion_state = "deprecated"
        self.db.commit()
        return {"ok": True, "id": skill.id, "promotion_state": skill.promotion_state}

    def failure_summary(self, project_id: str | None = None) -> dict[str, Any]:
        query = self.db.query(RunModel).filter(
            RunModel.status.in_([RunStatus.FAILED.value, RunStatus.BLOCKED.value, RunStatus.CHANGES_REQUESTED.value])
        )
        if project_id:
            query = query.filter(RunModel.project_id == project_id)
        runs = query.order_by(RunModel.created_at.desc()).all()
        for run in runs:
            self.ensure_run_task_kind(run)
            if not run.failure_class:
                data = self.classify_run(run)
                run.failure_class = data["failure_class"]
                run.failure_subclass = data["failure_subclass"]
                run.failure_signature = data["failure_signature"]
                run.recovery_status = data["recovery_status"]
        self.db.commit()
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

    def build_learning_context(self, run: RunModel, stage: str, base_context: str) -> dict[str, Any]:
        task = run.task or self.db.get(TaskModel, run.task_id)
        description = task.description if task else ""
        task_kind = run.task_kind or infer_task_kind(description)
        task_signature = normalize_task_signature(description)
        candidates: list[LessonMatch] = []
        lessons = self.list_project_lessons(run.project_id)
        for lesson in lessons:
            content = lesson["content"] if isinstance(lesson["content"], dict) else {}
            if content.get("superseded"):
                continue
            applies_task_kinds = [str(item) for item in content.get("applies_to_task_kinds") or []]
            stages = [str(item) for item in content.get("stages") or []]
            score = 3.0
            if task_kind in applies_task_kinds:
                score += 4.0
            if stage in stages:
                score += 5.0
            elif stages:
                score += 1.5
            if task_signature and task_signature in str(content.get("trigger_pattern") or ""):
                score += 1.0
            candidates.append(
                LessonMatch(
                    source_scope="project",
                    source_id=str(lesson["id"]),
                    title=str(content.get("title") or lesson["title"]),
                    summary=str(content.get("summary") or ""),
                    guidance=str(content.get("guidance") or ""),
                    score=score + float(content.get("confidence") or 0.5),
                    kind=str(content.get("kind") or "repo_convention"),
                )
            )

        skills = self.db.query(GlobalSkillModel).filter(GlobalSkillModel.promotion_state == "approved").all()
        for skill in skills:
            content = _loads_dict(skill.content)
            stages = skill.stages
            tags = skill.tags
            score = 1.0 + skill.confidence
            if stage in stages:
                score += 4.0
            elif stages:
                score += 1.0
            if task_kind in tags:
                score += 3.0
            if any(token in task_signature for token in tags):
                score += 1.0
            candidates.append(
                LessonMatch(
                    source_scope="global",
                    source_id=skill.id,
                    title=skill.name,
                    summary=skill.summary,
                    guidance=str(content.get("guidance") or skill.summary),
                    score=score,
                    kind=skill.kind,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        top = candidates[:4]
        if not top:
            return {"context": base_context, "project_lessons": [], "global_skills": []}
        lines = ["Relevant prior lessons:"]
        project_lessons: list[dict[str, Any]] = []
        global_skills: list[dict[str, Any]] = []
        for item in top:
            lines.append(f"- [{item.source_scope}] {item.title}: {item.summary} Guidance: {item.guidance}")
            payload = {"id": item.source_id, "title": item.title, "score": round(item.score, 2), "kind": item.kind}
            if item.source_scope == "project":
                project_lessons.append(payload)
            else:
                global_skills.append(payload)
        return {
            "context": f"{base_context}\n\n" + "\n".join(lines),
            "project_lessons": project_lessons,
            "global_skills": global_skills,
        }
