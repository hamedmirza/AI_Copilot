from __future__ import annotations

import json
import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from pathlib import Path
from threading import Lock
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ProviderError
from app.db.models import ChatMessageModel
from app.db.session import SessionLocal
from app.providers.base import ChatCompletionResult, ChatStreamChunk, ChatToolCall
from app.providers.registry import ProviderRegistry
from app.agents.skill_loader import (
    chat_mode_skill_key,
    load_integrity_charter,
    load_pipeline_framework,
    load_role_skill,
)
from app.services.chat_mode_registry import ChatModeDefinition, ChatModeRegistry
from app.services.chat_optimization import (
    effective_max_output_tokens,
    format_runtime_settings_answer,
    is_runtime_settings_question,
    should_offer_tools,
)
from app.services.chat_service import ChatService
from app.services.config_service import ConfigService
from app.services.project_service import ProjectService
from app.services.run_engine.event_bus import event_bus
from app.services.token_estimator import fit_messages_to_token_budget
from app.tools.chat_tools import ToolExecutionContext
from app.tools.tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class ChatCancelled(Exception):
    """Cooperative stop: partial streamed content may be attached."""

    def __init__(self, content: str = "") -> None:
        self.content = content
        super().__init__()


_MAX_CONTEXT_ITEMS = 20
_MAX_CONTEXT_DEPTH = 3
_MAX_CONTEXT_TEXT = 500
_MAX_MESSAGE_TEXT = 4000
_MAX_SYSTEM_CONTEXT_TEXT = 4000


class ChatOrchestrator:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=2)
        self._futures: set[Future[Any]] = set()
        self._lock = Lock()
        self._cancel_flags: dict[str, bool] = {}
        self._active_sessions: set[str] = set()

    def _mode_registry_for(self, db: Session) -> ChatModeRegistry:
        return ChatModeRegistry(ConfigService(db).get_all())

    def enqueue(self, session_id: str, user_message_id: str, context: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._cancel_flags.pop(session_id, None)
        future = self._executor.submit(self._run_session, session_id, user_message_id, context or {})
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._discard_future)

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            self._cancel_flags[session_id] = True
            return session_id in self._active_sessions

    def _is_cancelled(self, session_id: str) -> bool:
        with self._lock:
            return bool(self._cancel_flags.get(session_id))

    def _discard_future(self, future: Future[Any]) -> None:
        with self._lock:
            self._futures.discard(future)

    def wait_for_idle(self, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                pending = list(self._futures)
            if not pending:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            wait(pending, timeout=remaining)

    def _run_session(self, session_id: str, user_message_id: str, context: dict[str, Any]) -> None:
        with self._lock:
            self._active_sessions.add(session_id)
        db = SessionLocal()
        try:
            self._process(db, session_id, user_message_id, context)
        except ChatCancelled:
            pass
        except Exception as exc:
            logger.exception("Chat orchestration failed for session %s: %s", session_id, exc)
            event_bus.emit_chat(session_id, {"type": "error", "message": str(exc)})
        finally:
            db.close()
            with self._lock:
                self._active_sessions.discard(session_id)
                self._cancel_flags.pop(session_id, None)

    def _process(self, db: Session, session_id: str, user_message_id: str, context: dict[str, Any]) -> None:
        chat_service = ChatService(db)
        session = chat_service.get_session(session_id)
        project = ProjectService(db).get(session.project_id)
        config = ConfigService(db).get_all()
        git_branch: str | None = None
        try:
            from app.services.git_service import GitService

            git_branch = GitService(Path(project.source_repo_spec)).current_branch()
        except Exception:
            git_branch = None
        mode = self._mode_registry_for(db).get_mode(session.mode)
        registry = ProviderRegistry.get()
        provider = registry.resolve_chat_provider(mode.key, session.model_override)
        provider_name = "Ollama" if registry.active_provider() == "ollama" else "LM Studio"
        resolved_model = str(getattr(provider, "model", "") or "auto")
        event_bus.emit_chat(
            session_id,
            {
                "type": "meta",
                "provider": provider_name,
                "model": resolved_model,
                "mode": mode.key,
            },
        )
        logger.info(
            "chat resolved provider=%s model=%s mode=%s session=%s",
            provider_name,
            resolved_model,
            mode.key,
            session_id,
        )
        user_message = db.get(ChatMessageModel, user_message_id)
        user_text = str(user_message.content or "") if user_message else ""
        provider_runtime = self._provider_runtime_context(config)

        if is_runtime_settings_question(user_text):
            turn_started = time.monotonic()
            answer = format_runtime_settings_answer(provider_runtime)
            assistant = chat_service.append_message(
                session_id,
                role="assistant",
                content=answer,
                metadata=self._assistant_metadata(
                    user_message_id,
                    duration_ms=int((time.monotonic() - turn_started) * 1000),
                ),
            )
            event_bus.emit_chat(
                session_id,
                {
                    "type": "done",
                    "message_id": assistant.id,
                    "message": self._message_payload(assistant),
                },
            )
            logger.info("chat session=%s answered runtime_settings without LLM", session_id)
            return

        tool_registry = ToolRegistry(db)
        available_tools = tool_registry.resolve_tools(mode, session=session)
        use_tools = should_offer_tools(mode.key, user_text, read_only=mode.read_only)
        tool_schemas = (
            [tool.openai_schema for tool in available_tools.values()] if use_tools else []
        )
        tool_context = ToolExecutionContext(db=db, project=project, session=session)
        history_limit = max(1, min(int(config.get("chat_history_limit", 50) or 50), 500))
        max_context_tokens = max(2048, min(int(config.get("chat_max_context_tokens", 32768) or 32768), 200_000))
        max_output_tokens = effective_max_output_tokens(mode.key, config, user_text)

        use_nothink = self._resolve_use_nothink(session.nothink, config)
        mode_prompt = self._mode_prompt_with_skill(mode)
        messages = self._build_provider_messages(
            chat_service.list_recent_messages(session_id, limit=history_limit),
            project_path=project.source_repo_spec,
            mode_prompt=mode_prompt,
            context={**context, "git_branch": git_branch},
            provider_runtime=provider_runtime,
            use_nothink=use_nothink,
        )
        model_name = str(getattr(provider, "model", "") or "")
        messages, prompt_tokens, dropped_messages = fit_messages_to_token_budget(
            messages,
            max_context_tokens=max_context_tokens,
            reserve_output_tokens=max_output_tokens,
            tool_schemas=tool_schemas,
            model=model_name,
        )
        if dropped_messages > 0:
            event_bus.emit_chat(
                session_id,
                {
                    "type": "info",
                    "message": (
                        f"Context trimmed to ~{prompt_tokens:,} tokens "
                        f"({dropped_messages} older message(s) omitted)."
                    ),
                },
            )

        event_bus.emit_chat(session_id, {"type": "status", "message": "Thinking…"})
        turn_started = time.monotonic()
        for _ in range(max(1, mode.max_tool_rounds)):
            if self._is_cancelled(session_id):
                self._finalize_cancelled(
                    db,
                    session_id,
                    user_message_id,
                    "",
                    turn_started=turn_started,
                )
                return
            try:
                result = self._invoke_provider(
                    session_id,
                    provider,
                    messages,
                    tool_schemas,
                    mode=session.mode,
                    max_output_tokens=max_output_tokens,
                )
            except ChatCancelled as exc:
                self._finalize_cancelled(
                    db,
                    session_id,
                    user_message_id,
                    exc.content,
                    turn_started=turn_started,
                )
                return
            tool_calls = result.tool_calls or self._parse_react_fallback(result.content)
            if tool_calls:
                assistant_message = chat_service.append_message(
                    session_id,
                    role="assistant",
                    content="",
                    tool_calls=[self._tool_call_to_message_payload(call) for call in tool_calls],
                    metadata=self._assistant_metadata(user_message_id),
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [self._tool_call_to_provider_payload(call) for call in tool_calls],
                    }
                )
                event_bus.emit_chat(session_id, {"type": "status", "message": "Running tools…"})
                for call in tool_calls:
                    if self._is_cancelled(session_id):
                        self._finalize_cancelled(
                            db,
                            session_id,
                            user_message_id,
                            "",
                            turn_started=turn_started,
                        )
                        return
                    event_bus.emit_chat(
                        session_id,
                        {
                            "type": "tool_start",
                            "tool": call.name,
                            "args": call.arguments,
                            "call_id": call.id,
                        },
                    )
                    try:
                        tool_output = tool_registry.execute_tool(
                            call.name,
                            call.arguments,
                            tool_context,
                            available_tools,
                        )
                        chat_service.append_message(
                            session_id,
                            role="tool",
                            content=tool_output,
                            tool_call_id=call.id,
                            metadata={"assistant_message_id": assistant_message.id, "tool": call.name},
                        )
                        event_bus.emit_chat(
                            session_id,
                            {
                                "type": "tool_end",
                                "call_id": call.id,
                                "result": tool_output,
                                "ok": True,
                            },
                        )
                        messages.append({"role": "tool", "tool_call_id": call.id, "content": tool_output})
                        self._emit_run_spawned_if_present(chat_service, session_id, call.name, tool_output)
                    except Exception as exc:
                        error_text = f"Tool {call.name} failed: {exc}"
                        chat_service.append_message(
                            session_id,
                            role="tool",
                            content=error_text,
                            tool_call_id=call.id,
                            metadata={
                                "assistant_message_id": assistant_message.id,
                                "tool": call.name,
                                "error": True,
                            },
                        )
                        event_bus.emit_chat(
                            session_id,
                            {
                                "type": "tool_end",
                                "call_id": call.id,
                                "result": error_text,
                                "ok": False,
                            },
                        )
                        messages.append({"role": "tool", "tool_call_id": call.id, "content": error_text})
                if self._is_cancelled(session_id):
                    self._finalize_cancelled(
                        db,
                        session_id,
                        user_message_id,
                        "",
                        turn_started=turn_started,
                    )
                    return
                continue

            turn_duration_ms = int((time.monotonic() - turn_started) * 1000)
            assistant = chat_service.append_message(
                session_id,
                role="assistant",
                content=result.content,
                metadata=self._assistant_metadata(user_message_id, duration_ms=turn_duration_ms),
            )
            event_bus.emit_chat(
                session_id,
                {
                    "type": "done",
                    "message_id": assistant.id,
                    "message": self._message_payload(assistant),
                },
            )
            return

        fallback = chat_service.append_message(
            session_id,
            role="assistant",
            content="I hit the maximum tool round limit before reaching a final answer.",
            metadata={"source": "chat_orchestrator", "user_message_id": user_message_id},
        )
        event_bus.emit_chat(
            session_id,
            {
                "type": "done",
                "message_id": fallback.id,
                "message": self._message_payload(fallback),
            },
        )

    @staticmethod
    def _mode_prompt_with_skill(mode: ChatModeDefinition) -> str:
        parts = [mode.system_prompt]
        skill_key = chat_mode_skill_key(mode.key, getattr(mode, "skill_key", None))
        skill_text = load_role_skill(skill_key) if skill_key else ""
        if skill_text:
            parts.append(skill_text)
        if mode.key != "general":
            framework = load_pipeline_framework()
            if framework:
                parts.append(framework)
        integrity = load_integrity_charter()
        if integrity:
            parts.append(integrity)
        return "\n\n".join(parts)

    @staticmethod
    def _resolve_use_nothink(session_nothink: bool | None, config: dict[str, Any]) -> bool:
        if session_nothink is not None:
            return bool(session_nothink)
        return bool(config.get("nothink_default", True))

    @staticmethod
    def _provider_runtime_context(config: dict[str, Any]) -> dict[str, str]:
        active = "ollama" if config.get("ollama_enabled") else "lmstudio"
        return {
            "active_provider": active,
            "lmstudio_base_url": str(config.get("lmstudio_base_url") or "").strip(),
            "ollama_base_url": str(config.get("ollama_base_url") or "").strip(),
            "lmstudio_model_default": str(config.get("lmstudio_model") or "").strip(),
            "ollama_model_default": str(config.get("ollama_model") or "").strip(),
            "note": (
                "Authoritative live values from AI Copilot Settings (SQLite). "
                "For LM Studio/Ollama host or URL questions, answer from runtime_settings only; "
                "do not cite .env, config_service._DEFAULTS, or source-file defaults."
            ),
        }

    def _build_provider_messages(
        self,
        history: list[ChatMessageModel],
        *,
        project_path: str,
        mode_prompt: str,
        context: dict[str, Any],
        provider_runtime: dict[str, str] | None = None,
        use_nothink: bool = True,
    ) -> list[dict[str, Any]]:
        system_context = {
            "workspace_path": project_path,
            "runtime_settings": provider_runtime or {},
            "editor_context": self._truncate_value(context),
        }
        system_context_json = json.dumps(system_context, separators=(",", ":"), default=str)
        if len(system_context_json) > _MAX_SYSTEM_CONTEXT_TEXT:
            system_context["editor_context"] = {"notice": "editor context truncated for size"}
            system_context_json = json.dumps(system_context, separators=(",", ":"), default=str)
        page_element_hint = ""
        page_element = context.get("page_element") if isinstance(context, dict) else None
        if isinstance(page_element, dict) and page_element.get("selector"):
            page_element_hint = (
                "\n\nThe user selected a DOM element in the browser preview (see editor_context.page_element). "
                "Use search_files to locate matching components by class names, ids, or visible text before editing. "
                "Prefer the project's component/source files over editing raw HTML snippets. "
                "Use browser_navigate / browser_snapshot / browser_click / browser_screenshot to verify UI behavior when helpful."
            )
        system_content = f"{mode_prompt}{page_element_hint}\n\nCurrent context:\n{system_context_json}"
        if use_nothink:
            system_content = f"{mode_prompt}{page_element_hint}\n/nothink\n\nCurrent context:\n{system_context_json}"
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": system_content,
            }
        ]
        for item in history:
            if item.role == "assistant" and item.tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": item.content,
                        "tool_calls": [
                            {
                                "id": str(call.get("id") or ""),
                                "type": "function",
                                "function": {
                                    "name": str(call.get("name") or ""),
                                    "arguments": json.dumps(call.get("arguments") or {}),
                                },
                            }
                            for call in item.tool_calls
                        ],
                    }
                )
                continue
            if item.role == "tool":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.tool_call_id,
                        "content": self._truncate_text(item.content, _MAX_MESSAGE_TEXT),
                    }
                )
                continue
            messages.append({"role": item.role, "content": self._truncate_text(item.content, _MAX_MESSAGE_TEXT)})
        return messages

    def _truncate_text(self, value: Any, limit: int) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return f"{text[:limit]}...[truncated]"

    def _truncate_value(self, value: Any, depth: int = 0) -> Any:
        if depth >= _MAX_CONTEXT_DEPTH:
            return "[truncated]"
        if isinstance(value, dict):
            dict_items = list(value.items())[:_MAX_CONTEXT_ITEMS]
            result = {str(key): self._truncate_value(item, depth + 1) for key, item in dict_items}
            if len(value) > len(dict_items):
                result["_truncated"] = f"{len(value) - len(dict_items)} additional item(s)"
            return result
        if isinstance(value, list):
            list_items: list[Any] = [self._truncate_value(item, depth + 1) for item in value[:_MAX_CONTEXT_ITEMS]]
            if len(value) > len(list_items):
                list_items.append(f"...{len(value) - len(list_items)} more item(s)")
            return list_items
        if isinstance(value, tuple):
            return [self._truncate_value(item, depth + 1) for item in value[:_MAX_CONTEXT_ITEMS]]
        return self._truncate_text(value, _MAX_CONTEXT_TEXT)

    def _invoke_provider(
        self,
        session_id: str,
        provider,
        messages: list[dict[str, Any]],
        tool_schemas: list[dict[str, Any]],
        *,
        mode: str = "general",
        max_output_tokens: int = 4096,
        retried: bool = False,
    ) -> ChatCompletionResult:
        if self._is_cancelled(session_id):
            raise ChatCancelled()
        accumulated = ""
        tool_calls: list[ChatToolCall] = []
        finish_reason = "stop"
        event_bus.emit_chat(session_id, {"type": "status", "message": "Thinking…"})
        try:
            for chunk in provider.invoke_chat_stream(
                messages,
                tools=tool_schemas,
                max_tokens=max_output_tokens,
            ):
                if self._is_cancelled(session_id):
                    raise ChatCancelled(accumulated)
                if isinstance(chunk, ChatStreamChunk) and chunk.delta:
                    accumulated += chunk.delta
                    event_bus.emit_chat(session_id, {"type": "token", "content": chunk.delta})
                if isinstance(chunk, ChatStreamChunk) and chunk.tool_calls:
                    tool_calls = chunk.tool_calls
                if isinstance(chunk, ChatStreamChunk) and chunk.finish_reason:
                    finish_reason = chunk.finish_reason
            if self._is_cancelled(session_id):
                raise ChatCancelled(accumulated)
            return ChatCompletionResult(content=accumulated, tool_calls=tool_calls, finish_reason=finish_reason)
        except ChatCancelled:
            raise
        except ProviderError as exc:
            if not retried and self._is_memory_pressure_error(exc):
                fallback_provider = self._provider_after_memory_fallback(provider, mode)
                if fallback_provider is not None:
                    event_bus.emit_chat(
                        session_id,
                        {
                            "type": "info",
                            "message": (
                                f"Switching to {getattr(fallback_provider, 'model', 'a smaller model')} "
                                "because LM Studio could not load the selected model."
                            ),
                        },
                    )
                    return self._invoke_provider(
                        session_id,
                        fallback_provider,
                        messages,
                        tool_schemas,
                        mode=mode,
                        max_output_tokens=max_output_tokens,
                        retried=True,
                    )
            raise
        except ChatCancelled:
            raise
        except Exception:
            if self._is_cancelled(session_id):
                raise ChatCancelled(accumulated)
            try:
                result = provider.invoke_chat(
                    messages,
                    tools=tool_schemas,
                    max_tokens=max_output_tokens,
                )
            except ProviderError as exc:
                if not retried and self._is_memory_pressure_error(exc):
                    fallback_provider = self._provider_after_memory_fallback(provider, mode)
                    if fallback_provider is not None:
                        return self._invoke_provider(
                            session_id,
                            fallback_provider,
                            messages,
                            tool_schemas,
                            mode=mode,
                            max_output_tokens=max_output_tokens,
                            retried=True,
                        )
                raise
            if self._is_cancelled(session_id):
                raise ChatCancelled(result.content or "")
            if result.content:
                event_bus.emit_chat(session_id, {"type": "token", "content": result.content})
            return result

    def _finalize_cancelled(
        self,
        db: Session,
        session_id: str,
        user_message_id: str,
        content: str,
        *,
        turn_started: float | None = None,
    ) -> None:
        chat_service = ChatService(db)
        duration_ms: int | None = None
        if turn_started is not None:
            duration_ms = int((time.monotonic() - turn_started) * 1000)
        metadata = self._assistant_metadata(user_message_id, duration_ms=duration_ms)
        metadata["cancelled"] = True
        final_content = content.strip() or "Stopped"
        assistant = chat_service.append_message(
            session_id,
            role="assistant",
            content=final_content,
            metadata=metadata,
        )
        event_bus.emit_chat(
            session_id,
            {
                "type": "cancelled",
                "message_id": assistant.id,
                "message": self._message_payload(assistant),
            },
        )

    def _is_memory_pressure_error(self, exc: ProviderError) -> bool:
        lowered = str(exc).lower()
        return any(
            hint in lowered
            for hint in (
                "insufficient system resources",
                "failed to load model",
                "model unloaded",
                "memory pressure",
            )
        )

    def _provider_after_memory_fallback(self, provider, mode: str):
        current_model = str(getattr(provider, "model", "") or "")
        fallback_model = ProviderRegistry.get().resolve_memory_fallback_model(mode, current_model)
        if not fallback_model:
            return None
        if hasattr(provider, "prepare_model"):
            fallback_model = provider.prepare_model(fallback_model, mode)
        if hasattr(provider, "with_overrides"):
            return provider.with_overrides(model_name=fallback_model)
        return None

    @staticmethod
    def _assistant_metadata(user_message_id: str, *, duration_ms: int | None = None) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "source": "chat_orchestrator",
            "user_message_id": user_message_id,
        }
        if duration_ms is not None:
            metadata["duration_ms"] = max(0, int(duration_ms))
        return metadata

    def _parse_react_fallback(self, content: str) -> list[ChatToolCall]:
        text = (content or "").strip()
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        raw_calls = []
        if isinstance(data, dict) and isinstance(data.get("tool_calls"), list):
            raw_calls = data["tool_calls"]
        elif isinstance(data, dict) and data.get("tool") and isinstance(data.get("arguments"), dict):
            raw_calls = [data]
        calls: list[ChatToolCall] = []
        for item in raw_calls:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or item.get("tool") or "")
            if not name:
                continue
            arguments = item.get("arguments") or {}
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append(
                ChatToolCall(
                    id=str(item.get("id") or f"react_{len(calls) + 1}"),
                    name=name,
                    arguments=arguments,
                )
            )
        return calls

    def _tool_call_to_provider_payload(self, call: ChatToolCall) -> dict[str, Any]:
        return {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments),
            },
        }

    def _tool_call_to_message_payload(self, call: ChatToolCall) -> dict[str, Any]:
        return {
            "id": call.id,
            "name": call.name,
            "arguments": call.arguments,
        }

    def _message_payload(self, message: ChatMessageModel) -> dict[str, Any]:
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

    def _emit_run_spawned_if_present(
        self,
        chat_service: ChatService,
        session_id: str,
        tool_name: str,
        tool_output: str,
    ) -> None:
        if tool_name != "spawn_pipeline_task":
            return
        try:
            payload = json.loads(tool_output)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        run_id = str(payload.get("run_id") or "")
        task_id = str(payload.get("task_id") or "")
        if not run_id:
            return
        message = chat_service.append_message(
            session_id,
            role="assistant",
            content="Spawned pipeline task",
            metadata={"type": "run_spawned", "run_id": run_id, "task_id": task_id or None},
        )
        event_bus.emit_chat(
            session_id,
            {
                "type": "run_spawned",
                "run_id": run_id,
                "task_id": task_id or None,
                "message_id": message.id,
                "message": {
                    "id": message.id,
                    "session_id": message.session_id,
                    "role": message.role,
                    "content": message.content,
                    "tool_calls": message.tool_calls,
                    "tool_call_id": message.tool_call_id,
                    "metadata": message.message_metadata,
                    "created_at": message.created_at.isoformat(),
                },
            },
        )


chat_orchestrator = ChatOrchestrator()
