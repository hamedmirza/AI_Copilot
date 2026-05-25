from __future__ import annotations

import asyncio
import json
import threading

from sqlalchemy.orm import Session

from app.db.models import ArtifactModel, RunModel
from app.db.session import SessionLocal
from app.services.chat_service import ChatService
from app.services.orchestration_service import create_task_and_run
from app.services.run_engine.event_bus import event_bus


class PipelineBridge:
    TERMINAL_EVENTS = {"run_completed", "run_blocked", "run_failed", "run_changes_requested"}

    def __init__(self) -> None:
        self._subscriptions: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    def spawn(
        self,
        db: Session,
        *,
        session_id: str,
        project_id: str,
        description: str,
        validation_profile: str | None = None,
    ) -> dict[str, str]:
        task, run = create_task_and_run(
            db,
            {
                "project_id": project_id,
                "description": description,
                "validation_profile": validation_profile,
                "session_id": session_id,
            },
        )
        self.forward_run(session_id, run.id)
        return {"run_id": run.id, "task_id": task.id}

    def forward_run(self, session_id: str, run_id: str) -> None:
        key = (session_id, run_id)
        with self._lock:
            if key in self._subscriptions:
                return
            self._subscriptions.add(key)
        loop = event_bus.loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._forward_events(session_id, run_id), loop)

    async def _forward_events(self, session_id: str, run_id: str) -> None:
        queue = event_bus.subscribe_run(run_id)
        try:
            while True:
                event = await queue.get()
                summary_message = self._create_summary_message(session_id, run_id, event)
                event_bus.emit_chat(
                    session_id,
                    {
                        "type": "run_event",
                        "run_id": run_id,
                        "event": event,
                        "message": summary_message,
                    },
                )
                if summary_message is not None:
                    event_bus.emit_chat(
                        session_id,
                        {"type": "run_summary", "run_id": run_id, "message": summary_message},
                    )
                if str(event.get("type") or "") in self.TERMINAL_EVENTS:
                    break
        finally:
            event_bus.unsubscribe_run(run_id, queue)
            with self._lock:
                self._subscriptions.discard((session_id, run_id))

    def _create_summary_message(
        self,
        session_id: str,
        run_id: str,
        event: dict[str, object],
    ) -> dict[str, object] | None:
        event_type = str(event.get("type") or "")
        if event_type not in self.TERMINAL_EVENTS:
            return None
        db = SessionLocal()
        try:
            chat_service = ChatService(db)
            existing = [
                message
                for message in chat_service.list_messages(session_id, limit=500)
                if message.message_metadata.get("type") == "run_summary"
                and str(message.message_metadata.get("run_id") or "") == run_id
                and str(message.message_metadata.get("status") or "") == event_type
            ]
            if existing:
                message = existing[-1]
                return {
                    "id": message.id,
                    "session_id": message.session_id,
                    "role": message.role,
                    "content": message.content,
                    "tool_calls": message.tool_calls,
                    "tool_call_id": message.tool_call_id,
                    "metadata": message.message_metadata,
                    "created_at": message.created_at.isoformat(),
                }

            run = db.get(RunModel, run_id)
            if run is None:
                return None
            if getattr(run, "chat_session_id", None):
                return None
            content = self._build_summary_text(run, event)
            metadata = {
                "type": "run_summary",
                "run_id": run_id,
                "task_id": run.task_id,
                "status": event_type,
                "run_status": run.status,
                "stage": run.current_stage,
                "error": run.error_message,
            }
            message = chat_service.append_message(
                session_id,
                role="assistant",
                content=content,
                metadata=metadata,
            )
            return {
                "id": message.id,
                "session_id": message.session_id,
                "role": message.role,
                "content": message.content,
                "tool_calls": message.tool_calls,
                "tool_call_id": message.tool_call_id,
                "metadata": message.message_metadata,
                "created_at": message.created_at.isoformat(),
            }
        finally:
            db.close()

    def _latest_review_suggestions(self, db: Session, run_id: str) -> list[str]:
        artifact = (
            db.query(ArtifactModel)
            .filter(ArtifactModel.run_id == run_id, ArtifactModel.artifact_type.like("review_%"))
            .order_by(ArtifactModel.id.desc())
            .first()
        )
        if not artifact:
            return []
        try:
            content = json.loads(artifact.content_json)
        except Exception:
            return []
        suggestions = content.get("suggestions") or []
        return [str(s) for s in suggestions if str(s).strip()][:3]

    def _build_summary_text(self, run: RunModel, event: dict[str, object]) -> str:
        status_map = {
            "run_completed": "completed",
            "run_blocked": "blocked",
            "run_failed": "failed",
            "run_changes_requested": "changes requested",
        }
        status = status_map.get(str(event.get("type") or ""), run.status)
        parts = [f"Pipeline run {status}."]
        if run.current_stage:
            parts.append(f"Last stage: {run.current_stage}.")
        error_text = (run.error_message or str(event.get("message") or "")).strip()
        if error_text and error_text.lower() not in {"run completed", "validation failed"}:
            parts.append(f"Error: {error_text}.")
        elif error_text:
            parts.append(f"Detail: {error_text}.")
        if str(event.get("type") or "") == "run_changes_requested" or run.status == "changes_requested":
            db = SessionLocal()
            try:
                suggestions = self._latest_review_suggestions(db, run.id)
            finally:
                db.close()
            if suggestions:
                parts.append("Suggested next steps:")
                parts.extend(f"- {item}" for item in suggestions)
        return " ".join(parts)


pipeline_bridge = PipelineBridge()
