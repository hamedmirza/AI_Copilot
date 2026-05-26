import logging
import json
from typing import Any
from uuid import uuid4

import httpx

from app.core.enums import ProviderStatus
from app.core.exceptions import ProviderError
from app.providers.base import BaseProvider, ChatCompletionResult, ChatStreamChunk, ChatToolCall
from app.schemas.provider import ProviderHealthResponse
from app.services.lmstudio_catalog import (
    LMStudioCatalog,
    LMStudioResourceSnapshot,
    merge_catalog_payload,
)

logger = logging.getLogger(__name__)


class LMStudioProvider(BaseProvider):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 120,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = int(timeout_seconds)
        self._client = httpx.Client(
            timeout=httpx.Timeout(
                connect=5.0,
                read=float(self.timeout_seconds),
                write=30.0,
                pool=5.0,
            ),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    @property
    def _rest_base(self) -> str:
        if self.base_url.endswith("/v1"):
            return self.base_url[:-3]
        return self.base_url.rsplit("/", 1)[0]

    def with_overrides(
        self,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> "LMStudioProvider":
        if provider_name and provider_name != "lmstudio":
            raise ProviderError(f"Unsupported provider: {provider_name}")
        return LMStudioProvider(
            self.base_url,
            self.api_key,
            model_name or self.model,
            timeout_seconds=self.timeout_seconds,
        )

    def invoke_json(self, system_prompt: str, user_prompt: str) -> str:
        model = (self.model or "").strip()
        if not model:
            raise ProviderError("LM Studio model is not configured")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": f"{user_prompt}\n\nReturn valid JSON only. No markdown fences.",
                },
            ],
        }
        try:
            return self._invoke_json_once(url, payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(self._timeout_error_message(exc)) from exc
        except httpx.HTTPError as exc:
            if self._is_model_unloaded_error(exc) and self.load_model(model):
                try:
                    return self._invoke_json_once(url, payload)
                except httpx.HTTPError as retry_exc:
                    exc = retry_exc
            raise ProviderError(self._provider_error_message(exc)) from exc

    def _invoke_json_once(self, url: str, payload: dict[str, Any]) -> str:
        response = self._client.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return (content or "").strip()

    def _post_chat_completion(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._client.post(url, headers=self._headers(), json=payload)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ProviderError("LM Studio returned an unexpected chat completion payload")
        return data

    def _apply_max_tokens(self, payload: dict[str, Any], max_tokens: int | None) -> None:
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = int(max_tokens)

    def _conversation_has_tool_history(self, messages: list[dict[str, Any]]) -> bool:
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "")
            if role == "tool":
                return True
            if role == "assistant" and message.get("tool_calls"):
                return True
        return False

    def _normalize_tool_call_entry(self, call: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(call, dict):
            return None
        if isinstance(call.get("function"), dict):
            function = dict(call["function"])
            args = function.get("arguments")
            if isinstance(args, dict):
                function["arguments"] = json.dumps(args)
            elif args is None:
                function["arguments"] = "{}"
            else:
                function["arguments"] = str(args)
            return {
                "id": str(call.get("id") or ""),
                "type": str(call.get("type") or "function"),
                "function": function,
            }
        name = str(call.get("name") or "")
        if not name:
            return None
        args = call.get("arguments")
        if isinstance(args, str):
            args_str = args
        elif isinstance(args, dict):
            args_str = json.dumps(args)
        else:
            args_str = "{}"
        return {
            "id": str(call.get("id") or ""),
            "type": "function",
            "function": {"name": name, "arguments": args_str},
        }

    def _normalize_messages_for_lmstudio(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """LM Studio OpenAI-compatible API rejects role=tool in multi-turn history."""
        normalized: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "user")
            if role == "tool":
                name = str(message.get("name") or "tool")
                call_id = str(message.get("tool_call_id") or "")
                content = str(message.get("content") or "")
                header = f"[Tool result: {name}"
                if call_id:
                    header += f" ({call_id})"
                header += "]\n"
                normalized.append({"role": "user", "content": header + content})
                continue
            if role == "assistant" and isinstance(message.get("tool_calls"), list):
                fixed_calls = [
                    entry
                    for entry in (
                        self._normalize_tool_call_entry(call)
                        for call in message.get("tool_calls") or []
                    )
                    if entry is not None
                ]
                if fixed_calls:
                    normalized.append(
                        {
                            "role": "assistant",
                            "content": str(message.get("content") or ""),
                            "tool_calls": fixed_calls,
                        }
                    )
                    continue
            normalized.append(dict(message))
        return normalized

    def _apply_tooling(
        self,
        payload: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        tool_choice: dict[str, Any] | str | None = None,
    ) -> None:
        if not tools:
            return
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice if tool_choice is not None else "auto"

    def invoke_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        stream: bool = False,
        max_tokens: int | None = None,
        tool_choice: dict[str, Any] | str | None = None,
    ) -> ChatCompletionResult:
        model = (self.model or "").strip()
        if not model:
            raise ProviderError("LM Studio model is not configured")
        if tools and self._conversation_has_tool_history(messages):
            logger.info("LM Studio tool follow-up: using JSON ReAct instead of native chat messages")
            return super().invoke_chat(messages, tools=tools, stream=stream, max_tokens=max_tokens)
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._normalize_messages_for_lmstudio(messages),
            "stream": False,
        }
        self._apply_tooling(payload, tools, tool_choice)
        self._apply_max_tokens(payload, max_tokens)
        try:
            data = self._post_chat_completion(url, payload)
        except httpx.TimeoutException as exc:
            raise ProviderError(self._timeout_error_message(exc)) from exc
        except httpx.HTTPError as exc:
            if self._is_model_unloaded_error(exc) and self.load_model(model):
                try:
                    data = self._post_chat_completion(url, payload)
                except httpx.HTTPError as retry_exc:
                    exc = retry_exc
                else:
                    exc = None
            if exc is not None:
                if self._is_model_request_error(exc):
                    raise ProviderError(f"LM Studio model error: {self._http_error_message(exc)}") from exc
                if self._is_context_request_error(exc):
                    raise ProviderError(f"LM Studio context error: {self._http_error_message(exc)}") from exc
                if tools and self._should_fallback_to_react(exc):
                    logger.warning(
                        "LM Studio rejected native tool calling, falling back to JSON ReAct: %s",
                        self._http_error_message(exc),
                    )
                    return super().invoke_chat(messages, tools=tools, stream=stream, max_tokens=max_tokens)
                raise ProviderError(self._provider_error_message(exc)) from exc
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            logger.warning("LM Studio returned unexpected chat payload, using JSON ReAct fallback")
            return super().invoke_chat(messages, tools=tools, stream=stream)
        return ChatCompletionResult(
            content=str(message.get("content") or ""),
            tool_calls=self._tool_calls_from_message(message),
            finish_reason=str(data.get("choices", [{}])[0].get("finish_reason") or "stop"),
            raw=data,
        )

    def invoke_chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        tool_choice: dict[str, Any] | str | None = None,
    ):
        model = (self.model or "").strip()
        if not model:
            raise ProviderError("LM Studio model is not configured")
        if tools and self._conversation_has_tool_history(messages):
            logger.info("LM Studio streaming tool follow-up: using JSON ReAct")
            yield from super().invoke_chat_stream(messages, tools=tools, max_tokens=max_tokens)
            return
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": self._normalize_messages_for_lmstudio(messages),
            "stream": True,
        }
        self._apply_tooling(payload, tools, tool_choice)
        self._apply_max_tokens(payload, max_tokens)
        try:
            with self._client.stream(
                "POST",
                url,
                headers=self._headers(),
                json=payload,
            ) as response:
                response.raise_for_status()
                aggregated = self._stream_tool_calls(response)
                for chunk in aggregated:
                    yield chunk
                return
        except httpx.TimeoutException as exc:
            raise ProviderError(self._timeout_error_message(exc)) from exc
        except httpx.HTTPError as exc:
            if self._is_model_request_error(exc):
                raise ProviderError(f"LM Studio model error: {self._http_error_message(exc)}") from exc
            if self._is_context_request_error(exc):
                raise ProviderError(f"LM Studio context error: {self._http_error_message(exc)}") from exc
            if tools and self._should_fallback_to_react(exc):
                logger.warning(
                    "LM Studio streaming rejected native tool calling, falling back to JSON ReAct: %s",
                    self._http_error_message(exc),
                )
                yield from super().invoke_chat_stream(
                    messages, tools=tools, max_tokens=max_tokens, tool_choice=tool_choice
                )
                return
            raise ProviderError(self._provider_error_message(exc)) from exc

    def healthcheck(self) -> ProviderHealthResponse:
        url = f"{self.base_url}/models"
        try:
            response = self._client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            models = [item.get("id") for item in data.get("data", []) if isinstance(item, dict)]
            configured = (self.model or "").strip()
            if configured and configured in models:
                status = ProviderStatus.HEALTHY
                detail = "LM Studio reachable and configured model is listed."
            elif models:
                status = ProviderStatus.DEGRADED
                detail = "LM Studio reachable, configured model not listed."
            else:
                status = ProviderStatus.DEGRADED
                detail = "LM Studio reachable but no models returned."
            return ProviderHealthResponse(
                provider="lmstudio",
                status=status,
                detail=detail,
                model=self.model,
            )
        except httpx.HTTPError as exc:
            return ProviderHealthResponse(
                provider="lmstudio",
                status=ProviderStatus.UNREACHABLE,
                detail=f"LM Studio unreachable: {exc}",
                model=self.model,
            )

    def fetch_catalog(self) -> LMStudioCatalog | None:
        try:
            v0_response = self._client.get(f"{self._rest_base}/api/v0/models", headers=self._headers())
            v0_response.raise_for_status()
            v0_data = v0_response.json()
            v0_models = [item for item in v0_data.get("data", []) if isinstance(item, dict)]
        except httpx.HTTPError:
            v0_models = []
        try:
            v1_response = self._client.get(f"{self._rest_base}/api/v1/models", headers=self._headers())
            v1_response.raise_for_status()
            v1_data = v1_response.json()
            v1_models = [item for item in v1_data.get("models", []) if isinstance(item, dict)]
        except httpx.HTTPError:
            v1_models = []
        if not v0_models and not v1_models:
            return None
        return merge_catalog_payload(v0_models, v1_models)

    def resource_snapshot(self) -> LMStudioResourceSnapshot | None:
        catalog = self.fetch_catalog()
        return catalog.resources() if catalog else None

    def unload_instances(self, instance_ids: list[str]) -> list[str]:
        unloaded: list[str] = []
        for instance_id in instance_ids:
            normalized = (instance_id or "").strip()
            if not normalized:
                continue
            try:
                response = self._client.post(
                    f"{self._rest_base}/api/v1/models/unload",
                    headers=self._headers(),
                    json={"instance_id": normalized},
                )
                response.raise_for_status()
                unloaded.append(normalized)
            except httpx.HTTPError as exc:
                logger.warning("LM Studio failed to unload %s: %s", normalized, exc)
        return unloaded

    def _load_timeout(self) -> httpx.Timeout:
        read_seconds = max(float(self.timeout_seconds), 300.0)
        return httpx.Timeout(connect=5.0, read=read_seconds, write=30.0, pool=5.0)

    def load_model(self, model_id: str) -> bool:
        normalized = (model_id or "").strip()
        if not normalized:
            return False
        try:
            response = self._client.post(
                f"{self._rest_base}/api/v1/models/load",
                headers=self._headers(),
                json={"model": normalized},
                timeout=self._load_timeout(),
            )
            response.raise_for_status()
            logger.info("Loaded LM Studio model %r", normalized)
            return True
        except httpx.HTTPError as exc:
            logger.warning("LM Studio failed to load %s: %s", normalized, self._http_error_message(exc))
            return False

    def prepare_model(
        self,
        model_id: str,
        mode: str = "general",
        *,
        catalog: LMStudioCatalog | None = None,
        allow_unload: bool = True,
    ) -> str:
        catalog = catalog or self.fetch_catalog()
        if catalog is None:
            return model_id
        selected, unload = catalog.resolve_runnable(model_id, mode)
        if unload and allow_unload:
            freed = self.unload_instances(unload)
            if freed:
                logger.info(
                    "Unloaded %d LM Studio model instance(s) to free memory before using %r",
                    len(freed),
                    selected or model_id,
                )
        target = selected or model_id
        record = catalog.by_id().get(target)
        if record is not None and not record.is_loaded:
            if not self.load_model(target):
                fallback = catalog.pick_best(mode)
                if fallback and fallback != target:
                    logger.warning(
                        "LM Studio could not load %r; falling back to %r for mode %r",
                        target,
                        fallback,
                        mode,
                    )
                    fallback_record = catalog.by_id().get(fallback)
                    if fallback_record is not None and not fallback_record.is_loaded:
                        self.load_model(fallback)
                    return fallback
        return target

    def list_models(self) -> list[str]:
        catalog = self.fetch_catalog()
        if catalog is not None:
            return catalog.ids()
        url = f"{self.base_url}/models"
        try:
            response = self._client.get(url, headers=self._headers())
            response.raise_for_status()
            data = response.json()
            return sorted(
                str(item.get("id")) for item in data.get("data", []) if isinstance(item, dict)
            )
        except httpx.HTTPError:
            return []

    def _stream_tool_calls(self, response: httpx.Response):
        tool_fragments: dict[int, dict[str, Any]] = {}
        finish_reason = "stop"
        for data in self._iter_sse_json(response):
            choices = data.get("choices") or []
            if not choices:
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            content = delta.get("content") or ""
            if content:
                yield ChatStreamChunk(delta=str(content))
            for item in delta.get("tool_calls") or []:
                index = int(item.get("index", 0))
                entry = tool_fragments.setdefault(
                    index,
                    {
                        "id": item.get("id") or f"tool_{uuid4().hex[:8]}",
                        "name": "",
                        "arguments": "",
                    },
                )
                function = item.get("function") or {}
                if item.get("id"):
                    entry["id"] = item["id"]
                if function.get("name"):
                    entry["name"] = function["name"]
                if function.get("arguments"):
                    entry["arguments"] += function["arguments"]
            if choice.get("finish_reason"):
                finish_reason = str(choice["finish_reason"])
        if tool_fragments:
            yield ChatStreamChunk(
                tool_calls=[
                    ChatToolCall(
                        id=str(item["id"]),
                        name=str(item["name"]),
                        arguments=self._parse_arguments(str(item["arguments"])),
                    )
                    for _, item in sorted(tool_fragments.items())
                    if item.get("name")
                ],
                finish_reason=finish_reason,
            )
        yield ChatStreamChunk(done=True, finish_reason=finish_reason)

    def _iter_sse_json(self, response: httpx.Response):
        for raw_line in response.iter_lines():
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
            line = (line or "").strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                yield httpx.Response(200, content=payload).json()
            except ValueError:
                continue

    def _tool_calls_from_message(self, message: dict[str, Any]) -> list[ChatToolCall]:
        calls: list[ChatToolCall] = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            name = str(function.get("name") or "")
            if not name:
                continue
            calls.append(
                ChatToolCall(
                    id=str(item.get("id") or f"tool_{uuid4().hex[:8]}"),
                    name=name,
                    arguments=self._parse_arguments(str(function.get("arguments") or "{}")),
                )
            )
        return calls

    def _parse_arguments(self, raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _timeout_error_message(self, exc: httpx.TimeoutException) -> str:
        detail = self._http_error_message(exc)
        return (
            f"LM Studio timed out after {self.timeout_seconds}s ({detail}). "
            "Increase Provider timeout in Settings (⌘,) if the model is still loading or generating."
        )

    def _http_error_message(self, exc: httpx.HTTPError) -> str:
        response = getattr(exc, "response", None)
        if response is None:
            return str(exc)
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or "").strip()
                    if message:
                        return message
                elif error is not None:
                    return str(error)
                message = str(body.get("message") or "").strip()
                if message:
                    return message
        except ValueError:
            pass
        text = (response.text or "").strip()
        return text or str(exc)

    def _is_model_request_error(self, exc: httpx.HTTPError) -> bool:
        response = getattr(exc, "response", None)
        if response is None:
            return False
        if response.status_code not in {400, 404, 422}:
            return False
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict) and str(error.get("param") or "") == "model":
                return True
        lowered = self._http_error_message(exc).lower()
        hints = (
            "failed to load model",
            "model loading",
            "model unloaded",
            "insufficient system resources",
            "model not found",
            "unknown model",
            "does not exist",
            "no model",
        )
        return any(hint in lowered for hint in hints)

    def _is_model_unloaded_error(self, exc: httpx.HTTPError) -> bool:
        return "model unloaded" in self._http_error_message(exc).lower()

    def _is_context_request_error(self, exc: httpx.HTTPError) -> bool:
        lowered = self._http_error_message(exc).lower()
        hints = (
            "context length",
            "number of tokens to keep",
            "prompt is too long",
            "too many tokens",
            "context window",
        )
        return any(hint in lowered for hint in hints)

    def _provider_error_message(self, exc: httpx.HTTPError) -> str:
        if self._is_context_request_error(exc):
            return f"LM Studio context error: {self._http_error_message(exc)}"
        return f"LM Studio request failed: {self._http_error_message(exc)}"

    def _should_fallback_to_react(self, exc: httpx.HTTPError) -> bool:
        if self._is_model_request_error(exc):
            return False
        response = getattr(exc, "response", None)
        if response is None:
            return True
        if response.status_code not in {400, 422}:
            return False
        lowered = self._http_error_message(exc).lower()
        if not lowered:
            return False
        hints = (
            "tool",
            "function",
            "tool_choice",
            "tool_calls",
            "messages[",
            "invalid 'messages'",
            'invalid "messages"',
            "messages in payload",
            "unsupported",
        )
        return any(hint in lowered for hint in hints)
