from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.api.deps import verify_websocket_token
from app.core.exceptions import NotFoundError
from app.db.session import get_db
from app.mcp.client_manager import MCPClientManager
from app.schemas.chat import (
    ChatCancelResponse,
    ChatMessageCreate,
    ChatMessageEnqueueResponse,
    ChatMessageResponse,
    ChatSessionCreate,
    ChatSessionResponse,
    ChatSessionUpdate,
    ChatSpawnTaskRequest,
    ChatSpawnTaskResponse,
    MCPServerCreate,
    MCPServerImportRequest,
    MCPServerResponse,
    MCPServerTestResponse,
    MCPServerUpdate,
)
from app.services.chat_mode_registry import ChatModeRegistry
from app.services.chat_orchestrator import chat_orchestrator
from app.services.chat_service import UNSET, ChatService
from app.services.config_service import ConfigService
from app.services.pipeline_bridge import pipeline_bridge
from app.services.run_engine.event_bus import event_bus

router = APIRouter()


def _session_response(session) -> ChatSessionResponse:
    return ChatSessionResponse(
        id=session.id,
        project_id=session.project_id,
        title=session.title,
        mode=session.mode,
        model_override=session.model_override,
        nothink=session.nothink,
        allow_web_search=bool(getattr(session, "allow_web_search", False)),
        message_count=int(getattr(session, "message_count", 0) or 0),
        last_message_preview=getattr(session, "last_message_preview", None),
        last_message_at=getattr(session, "last_message_at", None),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _message_response(message) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        tool_calls=message.tool_calls,
        tool_call_id=message.tool_call_id,
        metadata=message.message_metadata,
        created_at=message.created_at,
    )


def _mcp_response(server) -> MCPServerResponse:
    return MCPServerResponse(
        id=server.id,
        name=server.name,
        command=server.command,
        args=server.args,
        env=server.env,
        enabled=server.enabled,
        last_status=server.last_status,
        last_error=server.last_error,
        tool_count=server.tool_count,
        created_at=server.created_at,
        updated_at=server.updated_at,
    )


@router.get("/chat/sessions")
def list_chat_sessions(
    project_id: str = Query(...),
    q: str | None = Query(None),
    db: Session = Depends(get_db),
):
    service = ChatService(db)
    return [_session_response(item) for item in service.list_sessions(project_id, q=q)]


@router.get("/chat/modes")
def list_chat_modes(db: Session = Depends(get_db)):
    registry = ChatModeRegistry(ConfigService(db).get_all())
    return [
        {
            "key": mode.key,
            "label": mode.label,
            "description": mode.description,
            "allowed_tools": mode.allowed_tools,
            "max_tool_rounds": mode.max_tool_rounds,
            "allow_mcp": mode.allow_mcp,
            "read_only": mode.read_only,
        }
        for mode in registry.list_modes()
    ]


@router.post("/chat/sessions")
def create_chat_session(body: ChatSessionCreate, db: Session = Depends(get_db)):
    service = ChatService(db)
    return _session_response(
        service.get_session_with_summary(
            service.create_session(
                project_id=body.project_id,
                title=body.title,
                mode=body.mode,
                model_override=body.model_override,
                nothink=body.nothink,
                allow_web_search=body.allow_web_search,
            ).id
        )
    )


@router.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str, db: Session = Depends(get_db)):
    service = ChatService(db)
    try:
        return _session_response(service.get_session_with_summary(session_id))
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/chat/sessions/{session_id}")
def update_chat_session(session_id: str, body: ChatSessionUpdate, db: Session = Depends(get_db)):
    service = ChatService(db)
    try:
        return _session_response(
            service.get_session_with_summary(
                service.update_session(
                    session_id,
                    title=body.title,
                    mode=body.mode,
                    model_override=body.model_override if "model_override" in body.model_fields_set else UNSET,
                    nothink=body.nothink if "nothink" in body.model_fields_set else UNSET,
                    allow_web_search=body.allow_web_search if "allow_web_search" in body.model_fields_set else UNSET,
                ).id
            )
        )
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/chat/sessions/{session_id}")
def delete_chat_session(session_id: str, db: Session = Depends(get_db)):
    service = ChatService(db)
    try:
        service.delete_session(session_id)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@router.get("/chat/sessions/{session_id}/messages")
def list_chat_messages(
    session_id: str,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    service = ChatService(db)
    try:
        return [_message_response(item) for item in service.list_messages(session_id, limit=limit, offset=offset)]
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/chat/sessions/{session_id}/cancel", response_model=ChatCancelResponse)
def cancel_chat_session(session_id: str, db: Session = Depends(get_db)):
    service = ChatService(db)
    try:
        service.get_session(session_id)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    was_active = chat_orchestrator.cancel(session_id)
    return ChatCancelResponse(cancelled=was_active)


@router.post("/chat/sessions/{session_id}/messages", response_model=ChatMessageEnqueueResponse)
def create_chat_message(session_id: str, body: ChatMessageCreate, db: Session = Depends(get_db)):
    service = ChatService(db)
    try:
        service.update_session(
            session_id,
            mode=body.mode,
            model_override=body.model_override if "model_override" in body.model_fields_set else UNSET,
        )
        message = service.append_message(
            session_id,
            role="user",
            content=body.content,
            metadata={"context": body.context},
        )
        session = service.get_session_with_summary(session_id)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    chat_orchestrator.enqueue(session_id, message.id, body.context)
    return ChatMessageEnqueueResponse(
        message_id=message.id,
        session=_session_response(session),
        user_message=_message_response(message),
    )


@router.post("/chat/sessions/{session_id}/spawn-task", response_model=ChatSpawnTaskResponse)
def spawn_chat_task(session_id: str, body: ChatSpawnTaskRequest, db: Session = Depends(get_db)):
    service = ChatService(db)
    try:
        session = service.get_session(session_id)
        result = pipeline_bridge.spawn(
            db,
            session_id=session_id,
            project_id=session.project_id,
            description=body.description,
            validation_profile=body.validation_profile,
            allow_web_search=session.allow_web_search if body.allow_web_search is None else body.allow_web_search,
        )
        assistant_message = service.append_message(
            session_id,
            role="assistant",
            content=f"Spawned pipeline task: {body.description}",
            metadata={"type": "run_spawned", **result},
        )
        event_bus.emit_chat(
            session_id,
            {
                "type": "run_spawned",
                "message_id": assistant_message.id,
                "message": _message_response(assistant_message).model_dump(mode="json"),
                **result,
            },
        )
        return ChatSpawnTaskResponse(
            ok=bool(result.get("ok", True)),
            run_id=str(result.get("run_id") or ""),
            task_id=str(result.get("task_id") or ""),
            message_id=assistant_message.id,
            chat_session_id=session_id,
        )
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/mcp/servers")
def list_mcp_servers(db: Session = Depends(get_db)):
    service = ChatService(db)
    return [_mcp_response(item) for item in service.list_mcp_servers()]


@router.post("/mcp/servers")
def create_mcp_server(body: MCPServerCreate, db: Session = Depends(get_db)):
    service = ChatService(db)
    return _mcp_response(service.create_mcp_server(body))


@router.put("/mcp/servers/{server_id}")
def update_mcp_server(server_id: str, body: MCPServerUpdate, db: Session = Depends(get_db)):
    service = ChatService(db)
    try:
        return _mcp_response(service.update_mcp_server(server_id, body))
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/mcp/servers/{server_id}")
def delete_mcp_server(server_id: str, db: Session = Depends(get_db)):
    service = ChatService(db)
    try:
        service.delete_mcp_server(server_id)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@router.post("/mcp/servers/{server_id}/test", response_model=MCPServerTestResponse)
def test_mcp_server(server_id: str, db: Session = Depends(get_db)):
    service = ChatService(db)
    try:
        server = service.get_mcp_server(server_id)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    ok, tools, error = MCPClientManager().test_server(server)
    service.record_mcp_test(server_id, ok=ok, tools=tools, error=error)
    return MCPServerTestResponse(ok=ok, tools=tools, error=error)


@router.get("/mcp/servers/export")
def export_mcp_servers(db: Session = Depends(get_db)):
    service = ChatService(db)
    return {"servers": service.export_mcp_servers()}


@router.post("/mcp/servers/import")
def import_mcp_servers(body: MCPServerImportRequest, db: Session = Depends(get_db)):
    service = ChatService(db)
    imported = service.import_mcp_servers(body.servers, replace_existing=body.replace_existing)
    return {
        "ok": True,
        "count": len(imported),
        "servers": [_mcp_response(item) for item in imported],
    }


@router.websocket("/ws/chat/{session_id}")
async def chat_ws(websocket: WebSocket, session_id: str):
    verify_websocket_token(websocket)
    await websocket.accept()
    event_bus.ws_connections += 1
    queue = event_bus.subscribe_chat(session_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe_chat(session_id, queue)
        event_bus.ws_connections -= 1
