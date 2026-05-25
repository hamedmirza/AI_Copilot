from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.db.models import ChatMessageModel, ChatSessionModel, MCPServerModel
from app.schemas.chat import MCPServerCreate, MCPServerImportEntry, MCPServerUpdate

UNSET = object()
DEFAULT_CHAT_TITLE = "New Chat"


def _now() -> datetime:
    return datetime.now(UTC)


def _json_dumps(value: Any, default: str) -> str:
    if value is None:
        return default
    return json.dumps(value)


def _normalize_model_override(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or normalized.lower() == "auto":
        return None
    return normalized


def _normalize_session_title(value: str | None) -> str:
    normalized = (value or "").strip()
    if not normalized or normalized.lower() == DEFAULT_CHAT_TITLE.lower():
        return DEFAULT_CHAT_TITLE
    return normalized


def _is_default_session_title(value: str | None) -> bool:
    return _normalize_session_title(value) == DEFAULT_CHAT_TITLE


def _truncate_text(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip()


class ChatService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _session_summary_query(self):
        message_count = (
            select(func.count(ChatMessageModel.id))
            .where(ChatMessageModel.session_id == ChatSessionModel.id)
            .scalar_subquery()
        )
        last_message_preview = (
            select(ChatMessageModel.content)
            .where(
                ChatMessageModel.session_id == ChatSessionModel.id,
                ChatMessageModel.role != "tool",
            )
            .order_by(ChatMessageModel.created_at.desc(), ChatMessageModel.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        last_message_at = (
            select(ChatMessageModel.created_at)
            .where(
                ChatMessageModel.session_id == ChatSessionModel.id,
                ChatMessageModel.role != "tool",
            )
            .order_by(ChatMessageModel.created_at.desc(), ChatMessageModel.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        return self.db.query(
            ChatSessionModel,
            func.coalesce(message_count, 0).label("message_count"),
            last_message_preview.label("last_message_preview"),
            last_message_at.label("last_message_at"),
        )

    def _apply_session_summary(
        self,
        session: ChatSessionModel,
        *,
        message_count: int | None,
        last_message_preview: str | None,
        last_message_at: datetime | None,
    ) -> ChatSessionModel:
        summary = cast(Any, session)
        summary.message_count = int(message_count or 0)
        summary.last_message_preview = (
            _truncate_text(last_message_preview, 120) if last_message_preview and last_message_preview.strip() else None
        )
        summary.last_message_at = last_message_at
        return cast(ChatSessionModel, summary)

    def list_sessions(self, project_id: str, q: str | None = None) -> list[ChatSessionModel]:
        query = self._session_summary_query().filter(ChatSessionModel.project_id == project_id)
        if q:
            search = f"%{q.strip().lower()}%"
            if search != "%%":
                query = query.filter(
                    or_(
                        func.lower(ChatSessionModel.title).like(search),
                        exists(
                            select(ChatMessageModel.id).where(
                                ChatMessageModel.session_id == ChatSessionModel.id,
                                func.lower(ChatMessageModel.content).like(search),
                            )
                        ),
                    )
                )
        rows = query.order_by(ChatSessionModel.updated_at.desc()).all()
        return [
            self._apply_session_summary(
                session,
                message_count=message_count,
                last_message_preview=last_message_preview,
                last_message_at=last_message_at,
            )
            for session, message_count, last_message_preview, last_message_at in rows
        ]

    def get_session(self, session_id: str) -> ChatSessionModel:
        session = self.db.get(ChatSessionModel, session_id)
        if not session:
            raise NotFoundError(f"Chat session not found: {session_id}")
        return session

    def get_session_with_summary(self, session_id: str) -> ChatSessionModel:
        row = self._session_summary_query().filter(ChatSessionModel.id == session_id).one_or_none()
        if not row:
            raise NotFoundError(f"Chat session not found: {session_id}")
        session, message_count, last_message_preview, last_message_at = row
        return self._apply_session_summary(
            session,
            message_count=message_count,
            last_message_preview=last_message_preview,
            last_message_at=last_message_at,
        )

    def create_session(
        self,
        project_id: str,
        title: str | None = None,
        mode: str = "general",
        model_override: str | None = None,
        nothink: bool | None = None,
        allow_web_search: bool = False,
    ) -> ChatSessionModel:
        session = ChatSessionModel(
            project_id=project_id,
            title=_normalize_session_title(title),
            mode=mode,
            model_override=_normalize_model_override(model_override),
            nothink=nothink,
            allow_web_search=bool(allow_web_search),
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def update_session(
        self,
        session_id: str,
        *,
        title: str | None = None,
        mode: str | None = None,
        model_override: str | None | object = UNSET,
        nothink: bool | None | object = UNSET,
        allow_web_search: bool | None | object = UNSET,
    ) -> ChatSessionModel:
        session = self.get_session(session_id)
        if title is not None:
            session.title = _normalize_session_title(title)
        if mode is not None:
            session.mode = mode
        if model_override is not UNSET:
            session.model_override = _normalize_model_override(
                model_override if isinstance(model_override, str) or model_override is None else None
            )
        if nothink is not UNSET:
            session.nothink = nothink if isinstance(nothink, bool) or nothink is None else None
        if allow_web_search is not UNSET:
            session.allow_web_search = bool(allow_web_search)
        session.updated_at = _now()
        self.db.commit()
        self.db.refresh(session)
        return session

    def delete_session(self, session_id: str) -> None:
        session = self.get_session(session_id)
        self.db.delete(session)
        self.db.commit()

    def list_messages(self, session_id: str, limit: int = 200, offset: int = 0) -> list[ChatMessageModel]:
        self.get_session(session_id)
        return (
            self.db.query(ChatMessageModel)
            .filter(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def list_recent_messages(self, session_id: str, limit: int = 50) -> list[ChatMessageModel]:
        """Return the newest ``limit`` messages in chronological order."""
        self.get_session(session_id)
        rows = (
            self.db.query(ChatMessageModel)
            .filter(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at.desc(), ChatMessageModel.id.desc())
            .limit(max(1, limit))
            .all()
        )
        return list(reversed(rows))

    def _touch_session(self, session: ChatSessionModel) -> None:
        session.updated_at = _now()

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str = "",
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChatMessageModel:
        session = self.get_session(session_id)
        message = ChatMessageModel(
            session_id=session_id,
            role=role,
            content=content,
            tool_calls_json=_json_dumps(tool_calls, "[]"),
            tool_call_id=tool_call_id,
            metadata_json=_json_dumps(metadata, "{}"),
        )
        if role == "user" and _is_default_session_title(session.title) and content.strip():
            session.title = _truncate_text(content.strip().splitlines()[0], 60)
        self._touch_session(session)
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def list_mcp_servers(self) -> list[MCPServerModel]:
        return self.db.query(MCPServerModel).order_by(MCPServerModel.name.asc()).all()

    def get_mcp_server(self, server_id: str) -> MCPServerModel:
        server = self.db.get(MCPServerModel, server_id)
        if not server:
            raise NotFoundError(f"MCP server not found: {server_id}")
        return server

    def create_mcp_server(self, data: MCPServerCreate) -> MCPServerModel:
        server = MCPServerModel(
            name=data.name.strip(),
            command=data.command.strip(),
            args_json=json.dumps(data.args),
            env_json=json.dumps(data.env),
            enabled=data.enabled,
        )
        self.db.add(server)
        self.db.commit()
        self.db.refresh(server)
        return server

    def update_mcp_server(self, server_id: str, data: MCPServerUpdate) -> MCPServerModel:
        server = self.get_mcp_server(server_id)
        payload = data.model_dump(exclude_none=True)
        if "name" in payload:
            server.name = str(payload["name"]).strip()
        if "command" in payload:
            server.command = str(payload["command"]).strip()
        if "args" in payload:
            server.args_json = json.dumps(payload["args"])
        if "env" in payload:
            server.env_json = json.dumps(payload["env"])
        if "enabled" in payload:
            server.enabled = bool(payload["enabled"])
        server.updated_at = _now()
        self.db.commit()
        self.db.refresh(server)
        return server

    def delete_mcp_server(self, server_id: str) -> None:
        server = self.get_mcp_server(server_id)
        self.db.delete(server)
        self.db.commit()

    def export_mcp_servers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": server.name,
                "command": server.command,
                "args": server.args,
                "env": server.env,
                "enabled": server.enabled,
            }
            for server in self.list_mcp_servers()
        ]

    def import_mcp_servers(
        self,
        servers: list[MCPServerImportEntry],
        *,
        replace_existing: bool = False,
    ) -> list[MCPServerModel]:
        if replace_existing:
            self.db.query(MCPServerModel).delete()
            self.db.commit()
        existing = {server.name: server for server in self.list_mcp_servers()}
        for item in servers:
            server = existing.get(item.name)
            if server:
                server.command = item.command.strip()
                server.args_json = json.dumps(item.args)
                server.env_json = json.dumps(item.env)
                server.enabled = item.enabled
                server.updated_at = _now()
            else:
                self.db.add(
                    MCPServerModel(
                        name=item.name.strip(),
                        command=item.command.strip(),
                        args_json=json.dumps(item.args),
                        env_json=json.dumps(item.env),
                        enabled=item.enabled,
                    )
                )
        self.db.commit()
        return self.list_mcp_servers()

    def record_mcp_test(
        self,
        server_id: str,
        *,
        ok: bool,
        tools: list[dict[str, Any]] | None = None,
        error: str | None = None,
    ) -> MCPServerModel:
        server = self.get_mcp_server(server_id)
        server.last_status = "healthy" if ok else "error"
        server.last_error = error
        server.tool_count = len(tools or [])
        server.updated_at = _now()
        self.db.commit()
        self.db.refresh(server)
        return server
