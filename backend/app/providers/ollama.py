import json
import logging

import httpx
from typing import Any
from uuid import uuid4

from app.core.enums import ProviderStatus
from app.core.exceptions import ProviderError
from app.providers.base import BaseProvider, ChatCompletionResult, ChatStreamChunk, ChatToolCall
from app.schemas.provider import ProviderHealthResponse

logger = logging.getLogger(__name__)

# Settings/model-picker listing should fail fast when the host is down.
_SETTINGS_LIST_TIMEOUT = httpx.Timeout(connect=2.0, read=8.0, write=5.0, pool=2.0)


def normalize_ollama_base_url(base_url: str) -> str:
    """Ensure OpenAI-compatible paths (/v1/chat/completions, /v1/models)."""
    url = (base_url or "").strip().rstrip("/")
    if not url:
        return "http://127.0.0.1:11434/v1"
    if not url.endswith("/v1"):
        url = f"{url}/v1"
    return url


def ollama_native_root(openai_base_url: str) -> str:
    """Strip /v1 suffix for native Ollama HTTP API (/api/tags)."""
    url = normalize_ollama_base_url(openai_base_url)
    if url.endswith("/v1"):
        return url[:-3]
    return url.rstrip("/")


def probe_ollama_endpoints(configured_base_url: str, timeout_seconds: float = 5.0) -> tuple[str | None, list[str]]:
    """Return the first reachable Ollama OpenAI base URL and every candidate tried."""
    candidates: list[str] = []
    for raw in (
        configured_base_url,
        "http://127.0.0.1:11434",
        "http://localhost:11434",
        "http://172.10.1.2:11434",
    ):
        normalized = normalize_ollama_base_url(raw)
        if normalized not in candidates:
            candidates.append(normalized)
    client = httpx.Client(
        timeout=httpx.Timeout(
            connect=timeout_seconds,
            read=timeout_seconds,
            write=timeout_seconds,
            pool=timeout_seconds,
        )
    )
    try:
        for base_url in candidates:
            try:
                response = client.get(f"{ollama_native_root(base_url)}/api/tags")
                response.raise_for_status()
                return base_url, candidates
            except httpx.HTTPError:
                continue
    finally:
        client.close()
    return None, candidates


class OllamaProvider(BaseProvider):
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout_seconds: int = 120,
    ) -> None:
        self.base_url = normalize_ollama_base_url(base_url)
        self.model = model
        self._client = httpx.Client(
            timeout=httpx.Timeout(connect=5.0, read=float(timeout_seconds), write=30.0, pool=5.0),
        )

    def with_overrides(
        self,
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> "OllamaProvider":
        if provider_name and provider_name != "ollama":
            raise ProviderError(f"Unsupported provider: {provider_name}")
        return OllamaProvider(
            self.base_url,
            model_name or self.model,
            timeout_seconds=int(self._client.timeout.read or 120),
        )

    def invoke_json(self, system_prompt: str, user_prompt: str) -> str:
        model = (self.model or "").strip()
        if not model:
            raise ProviderError("Ollama model is not configured")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{user_prompt}\n\nReturn valid JSON only."},
            ],
        }
        response = self._client.post(url, json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    def _apply_max_tokens(self, payload: dict[str, Any], max_tokens: int | None) -> None:
        if max_tokens is not None and max_tokens > 0:
            payload["max_tokens"] = int(max_tokens)

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

    def _uses_reasoning_as_output(self) -> bool:
        """Some Ollama models (e.g. gpt-oss) emit the user-visible reply in `reasoning`."""
        return "gpt-oss" in (self.model or "").lower()

    def _message_visible_text(self, message: dict[str, Any]) -> str:
        content = str(message.get("content") or "").strip()
        if content:
            return content
        if self._uses_reasoning_as_output():
            return str(message.get("reasoning") or "").strip()
        return ""

    def _delta_visible_text(self, delta: dict[str, Any]) -> str:
        content = str(delta.get("content") or "")
        if content:
            return content
        if self._uses_reasoning_as_output():
            return str(delta.get("reasoning") or "")
        return ""

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
            raise ProviderError("Ollama model is not configured")
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        self._apply_tooling(payload, tools, tool_choice)
        self._apply_max_tokens(payload, max_tokens)
        try:
            response = self._client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return super().invoke_chat(
                messages, tools=tools, stream=stream, max_tokens=max_tokens, tool_choice=tool_choice
            )
        except httpx.HTTPError as exc:
            if tools and self._should_fallback_to_react(exc):
                logger.warning("Ollama rejected native tool calling, falling back to JSON ReAct: %s", exc)
            else:
                logger.warning("Ollama native chat failed, falling back to JSON ReAct: %s", exc)
            return super().invoke_chat(
                messages, tools=tools, stream=stream, max_tokens=max_tokens, tool_choice=tool_choice
            )
        return ChatCompletionResult(
            content=self._message_visible_text(message),
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
            raise ProviderError("Ollama model is not configured")
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
        }
        self._apply_tooling(payload, tools, tool_choice)
        self._apply_max_tokens(payload, max_tokens)
        try:
            with self._client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                tool_fragments: dict[int, dict[str, Any]] = {}
                finish_reason = "stop"
                for raw_line in response.iter_lines():
                    line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
                    line = (line or "").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload_text = line[5:].strip()
                    if payload_text == "[DONE]":
                        break
                    try:
                        data = httpx.Response(200, content=payload_text).json()
                    except ValueError:
                        continue
                    choices = data.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    visible = self._delta_visible_text(delta)
                    if visible:
                        yield ChatStreamChunk(delta=visible)
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
                return
        except httpx.HTTPError as exc:
            if tools and self._should_fallback_to_react(exc):
                logger.warning("Ollama streaming rejected native tool calling, falling back to JSON ReAct: %s", exc)
            else:
                logger.warning("Ollama streaming failed, falling back to JSON ReAct: %s", exc)
        yield from super().invoke_chat_stream(messages, tools=tools, tool_choice=tool_choice)

    def _list_models_openai(self) -> list[str]:
        response = self._client.get(f"{self.base_url}/models")
        response.raise_for_status()
        data = response.json()
        return sorted(
            str(item.get("id")) for item in data.get("data", []) if isinstance(item, dict) and item.get("id")
        )

    def _list_models_native(self) -> list[str]:
        response = self._client.get(f"{ollama_native_root(self.base_url)}/api/tags")
        response.raise_for_status()
        data = response.json()
        names: list[str] = []
        for item in data.get("models") or []:
            if isinstance(item, dict) and item.get("name"):
                names.append(str(item["name"]))
        return sorted(names)

    def healthcheck(self) -> ProviderHealthResponse:
        try:
            models = self.list_models()
            status = ProviderStatus.HEALTHY if models else ProviderStatus.DEGRADED
            return ProviderHealthResponse(
                provider="ollama",
                status=status,
                detail="Ollama reachable.",
                model=self.model,
            )
        except httpx.HTTPError as exc:
            return ProviderHealthResponse(
                provider="ollama",
                status=ProviderStatus.UNREACHABLE,
                detail=f"Ollama unreachable: {exc}",
                model=self.model,
            )

    def list_models(self) -> list[str]:
        try:
            return self._list_models_openai()
        except httpx.HTTPError:
            try:
                return self._list_models_native()
            except httpx.HTTPError:
                return []

    def list_models_for_settings(self) -> list[str]:
        """List models using a short timeout (settings UI / model picker)."""
        client = httpx.Client(timeout=_SETTINGS_LIST_TIMEOUT)
        headers: dict[str, str] = {}
        try:
            response = client.get(f"{self.base_url}/models")
            response.raise_for_status()
            data = response.json()
            models = sorted(
                str(item.get("id"))
                for item in data.get("data", [])
                if isinstance(item, dict) and item.get("id")
            )
            if models:
                return models
        except httpx.HTTPError:
            pass
        try:
            response = client.get(f"{ollama_native_root(self.base_url)}/api/tags")
            response.raise_for_status()
            data = response.json()
            names: list[str] = []
            for item in data.get("models") or []:
                if isinstance(item, dict) and item.get("name"):
                    names.append(str(item["name"]))
            return sorted(names)
        except httpx.HTTPError:
            return []
        finally:
            client.close()

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

    def _should_fallback_to_react(self, exc: httpx.HTTPError) -> bool:
        response = getattr(exc, "response", None)
        if response is None:
            return True
        if response.status_code != 400:
            return True
        error_text = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    error_text = str(error.get("message") or "")
                elif error is not None:
                    error_text = str(error)
                else:
                    error_text = str(body.get("message") or "")
        except ValueError:
            error_text = response.text
        lowered = error_text.lower()
        if not lowered:
            return True
        hints = ("tool", "function", "tool_choice", "tool_calls", "messages[", "unsupported")
        return any(hint in lowered for hint in hints)
