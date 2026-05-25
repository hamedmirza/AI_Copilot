from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ChatSessionModel, RunModel, RunThreadEntryModel, TaskModel
from app.services.chat_service import ChatService
from app.services.run_engine.event_bus import event_bus


class RunThreadService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.chat_service = ChatService(db)

    def ensure_session(self, run_id: str, preferred_session_id: str | None = None) -> str | None:
        run = self.db.get(RunModel, run_id)
        if not run:
            return None
        if preferred_session_id:
            run.chat_session_id = preferred_session_id
            self.db.commit()
            return preferred_session_id
        if run.chat_session_id:
            return run.chat_session_id

        task = self.db.get(TaskModel, run.task_id)
        title_base = (task.description if task else "Pipeline run").strip().splitlines()[0][:80]
        session = ChatSessionModel(
            project_id=run.project_id,
            title=f"Run: {title_base or run.id[:8]}",
            mode="agent",
        )
        self.db.add(session)
        self.db.flush()
        run.chat_session_id = session.id
        self.db.commit()
        return session.id

    def append_entry(
        self,
        run_id: str,
        *,
        entry_type: str,
        stage: str | None,
        severity: str,
        message: str,
        payload: dict[str, Any] | None = None,
        role: str = "assistant",
        emit_chat_message: bool = True,
    ) -> RunThreadEntryModel | None:
        run = self.db.get(RunModel, run_id)
        if not run:
            return None
        session_id = self.ensure_session(run_id, run.chat_session_id)
        payload = payload or {}
        entry = RunThreadEntryModel(
            run_id=run_id,
            session_id=session_id,
            role=role,
            entry_type=entry_type,
            stage=stage,
            severity=severity,
            message=message,
            payload_json=json.dumps(payload),
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        if session_id and emit_chat_message:
            chat_message = self.chat_service.append_message(
                session_id,
                role=role,
                content=message,
                metadata={
                    "type": "run_thread",
                    "run_id": run_id,
                    "entry_type": entry_type,
                    "stage": stage,
                    "severity": severity,
                    **payload,
                },
            )
            event_bus.emit_chat(
                session_id,
                {
                    "type": "run_thread_message",
                    "run_id": run_id,
                    "message": {
                        "id": chat_message.id,
                        "session_id": chat_message.session_id,
                        "role": chat_message.role,
                        "content": chat_message.content,
                        "tool_calls": chat_message.tool_calls,
                        "tool_call_id": chat_message.tool_call_id,
                        "metadata": chat_message.message_metadata,
                        "created_at": chat_message.created_at.isoformat(),
                    },
                },
            )
        return entry

    def list_entries(self, run_id: str) -> list[dict[str, Any]]:
        rows = (
            self.db.query(RunThreadEntryModel)
            .filter(RunThreadEntryModel.run_id == run_id)
            .order_by(RunThreadEntryModel.created_at.asc(), RunThreadEntryModel.id.asc())
            .all()
        )
        return [
            {
                "id": row.id,
                "run_id": row.run_id,
                "session_id": row.session_id,
                "role": row.role,
                "entry_type": row.entry_type,
                "stage": row.stage,
                "severity": row.severity,
                "message": row.message,
                "payload": row.payload,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]
