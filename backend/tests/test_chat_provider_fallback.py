from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core.exceptions import ProviderError
from app.db.session import SessionLocal, run_migrations, seed_app_config
from app.providers.lmstudio import LMStudioProvider
from app.providers.ollama import OllamaProvider

HEADERS = {"X-Api-Token": "dev-token"}


class RejectsNativeToolsClient:
    def __init__(self, fallback_content: str) -> None:
        self.fallback_content = fallback_content

    def post(self, url: str, headers=None, json=None):
        request = httpx.Request("POST", url)
        if json and "tools" in json:
            response = httpx.Response(
                400,
                request=request,
                json={"error": {"message": "This model does not support tools"}},
            )
            raise httpx.HTTPStatusError("tool calling rejected", request=request, response=response)
        return httpx.Response(
            200,
            request=request,
            json={
                "choices": [
                    {
                        "message": {
                            "content": self.fallback_content,
                        }
                    }
                ]
            },
        )

    def stream(self, method: str, url: str, headers=None, json=None):
        request = httpx.Request(method, url)
        response = httpx.Response(
            400,
            request=request,
            json={"error": {"message": "tools are unsupported"}},
        )
        raise httpx.HTTPStatusError("tool calling rejected", request=request, response=response)


def test_lmstudio_falls_back_when_native_tools_are_rejected():
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "chat-model")
    provider._client = RejectsNativeToolsClient(
        '{"content":"fallback reply","tool_calls":[],"finish_reason":"stop"}'
    )

    result = provider.invoke_chat(
        [{"role": "user", "content": "Hello"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert result.content == "fallback reply"
    assert result.tool_calls == []

    streamed = list(
        provider.invoke_chat_stream(
            [{"role": "user", "content": "Hello"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        )
    )
    assert any(chunk.delta == "fallback reply" for chunk in streamed)
    assert streamed[-1].done is True


class RejectsModelLoadClient:
    def __init__(self) -> None:
        self.request = httpx.Request("POST", "http://example.test/v1/chat/completions")
        self.response = httpx.Response(
            400,
            request=self.request,
            json={
                "error": {
                    "message": 'Failed to load model "heavy-model". insufficient system resources',
                    "type": "invalid_request_error",
                    "param": "model",
                }
            },
        )

    def _raise(self, *_args, **_kwargs):
        raise httpx.HTTPStatusError("model load failed", request=self.request, response=self.response)

    def post(self, *_args, **_kwargs):
        self._raise()

    def stream(self, *_args, **_kwargs):
        self._raise()


def test_lmstudio_raises_on_model_load_error_without_react_retry():
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "heavy-model")
    provider._client = RejectsModelLoadClient()  # type: ignore[assignment]

    with pytest.raises(ProviderError, match="insufficient system resources"):
        provider.invoke_chat([{"role": "user", "content": "Hello"}], tools=[])

    with pytest.raises(ProviderError, match="insufficient system resources"):
        list(provider.invoke_chat_stream([{"role": "user", "content": "Hello"}], tools=[]))


class RejectsContextLengthClient:
    def __init__(self) -> None:
        self.request = httpx.Request("POST", "http://example.test/v1/chat/completions")
        self.response = httpx.Response(
            400,
            request=self.request,
            json={
                "error": {
                    "message": "The number of tokens to keep from the initial prompt is greater than the context length.",
                    "type": "invalid_request_error",
                }
            },
        )

    def post(self, *_args, **_kwargs):
        raise httpx.HTTPStatusError("context too large", request=self.request, response=self.response)

    def stream(self, *_args, **_kwargs):
        raise httpx.HTTPStatusError("context too large", request=self.request, response=self.response)


def test_lmstudio_raises_specific_context_error():
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "chat-model")
    provider._client = RejectsContextLengthClient()  # type: ignore[assignment]

    with pytest.raises(ProviderError, match="LM Studio context error"):
        provider.invoke_chat([{"role": "user", "content": "Hello"}], tools=[])


def test_ollama_falls_back_when_native_tools_are_rejected():
    provider = OllamaProvider("http://example.test/v1", "chat-model")
    provider._client = RejectsNativeToolsClient(
        '{"content":"ollama fallback","tool_calls":[],"finish_reason":"stop"}'
    )

    result = provider.invoke_chat(
        [{"role": "user", "content": "Hello"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )

    assert result.content == "ollama fallback"
    assert result.tool_calls == []


def test_mcp_export_and_import_round_trip(tmp_path: Path):
    test_db = Path(__file__).resolve().parents[1] / "test_app.db"
    if test_db.exists():
        test_db.unlink()
    run_migrations()
    db = SessionLocal()
    seed_app_config(db)
    db.close()
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/mcp/servers",
                json={
                    "name": "Filesystem MCP",
                    "command": "python3",
                    "args": ["-m", "server"],
                    "env": {"API_KEY": "secret", "ROOT": str(tmp_path)},
                    "enabled": True,
                },
                headers=HEADERS,
            )
            assert created.status_code == 200

            exported = client.get("/api/mcp/servers/export", headers=HEADERS)
            assert exported.status_code == 200
            payload = exported.json()
            assert len(payload["servers"]) == 1
            assert payload["servers"][0]["env"]["API_KEY"] == "secret"

            imported = client.post(
                "/api/mcp/servers/import",
                json={"servers": payload["servers"], "replace_existing": True},
                headers=HEADERS,
            )
            assert imported.status_code == 200
            assert imported.json()["count"] == 1

            listed = client.get("/api/mcp/servers", headers=HEADERS)
            assert listed.status_code == 200
            assert len(listed.json()) == 1
            assert listed.json()[0]["env"]["ROOT"] == str(tmp_path)
    finally:
        if test_db.exists():
            test_db.unlink()
