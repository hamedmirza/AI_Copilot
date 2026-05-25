from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatSessionCreate(BaseModel):
    project_id: str
    title: str | None = None
    mode: str = "general"
    model_override: str | None = None
    nothink: bool | None = None


class ChatSessionUpdate(BaseModel):
    title: str | None = None
    mode: str | None = None
    model_override: str | None = None
    nothink: bool | None = None


class ChatSessionResponse(BaseModel):
    id: str
    project_id: str
    title: str
    mode: str
    model_override: str | None
    nothink: bool | None = None
    message_count: int = 0
    last_message_preview: str | None = None
    last_message_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ChatMessageCreate(BaseModel):
    content: str = Field(min_length=1)
    context: dict[str, Any] = Field(default_factory=dict)
    mode: str | None = None
    model_override: str | None = None


class ChatMessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_call_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ChatMessageEnqueueResponse(BaseModel):
    ok: bool = True
    message_id: str
    session: ChatSessionResponse | None = None
    user_message: ChatMessageResponse | None = None


class ChatCancelResponse(BaseModel):
    ok: bool = True
    cancelled: bool


class ChatSpawnTaskRequest(BaseModel):
    description: str = Field(min_length=1)
    validation_profile: str | None = None


class ChatSpawnTaskResponse(BaseModel):
    ok: bool = True
    run_id: str
    task_id: str
    message_id: str | None = None
    chat_session_id: str | None = None


class MCPServerCreate(BaseModel):
    name: str = Field(min_length=1)
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class MCPServerUpdate(BaseModel):
    name: str | None = None
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    enabled: bool | None = None


class MCPServerImportEntry(BaseModel):
    name: str = Field(min_length=1)
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class MCPServerResponse(BaseModel):
    id: str
    name: str
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool
    last_status: str
    last_error: str | None = None
    tool_count: int
    created_at: datetime
    updated_at: datetime


class MCPServerTestResponse(BaseModel):
    ok: bool
    tools: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None


class MCPServerImportRequest(BaseModel):
    servers: list[MCPServerImportEntry] = Field(default_factory=list)
    replace_existing: bool = False
