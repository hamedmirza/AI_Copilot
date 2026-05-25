from __future__ import annotations

import httpx

from app.providers.lmstudio import LMStudioProvider
from app.services.lmstudio_catalog import LMStudioCatalog, LMStudioModelRecord


class LoadTrackingClient:
    def __init__(self, *, chat_fail_unloaded: bool = False) -> None:
        self.load_calls: list[str] = []
        self.unload_calls: list[str] = []
        self.chat_fail_unloaded = chat_fail_unloaded
        self._chat_attempts = 0

    def get(self, url: str, headers=None):
        request = httpx.Request("GET", url)
        if url.endswith("/api/v1/models"):
            return httpx.Response(
                200,
                request=request,
                json={
                    "models": [
                        {
                            "key": "qwen/qwen3-coder-30b",
                            "size_bytes": 20_000_000_000,
                            "capabilities": {"trained_for_tool_use": True},
                            "loaded_instances": [],
                        },
                        {
                            "key": "qwen3.6-27b",
                            "size_bytes": 14_000_000_000,
                            "capabilities": {"trained_for_tool_use": True},
                            "loaded_instances": [{"id": "qwen3.6-27b"}],
                        },
                    ]
                },
            )
        return httpx.Response(
            200,
            request=request,
            json={
                "data": [
                    {"id": "qwen/qwen3-coder-30b", "state": "not-loaded"},
                    {"id": "qwen3.6-27b", "state": "loaded"},
                ]
            },
        )

    def post(self, url: str, headers=None, json=None, **_kwargs):
        request = httpx.Request("POST", url)
        payload = json or {}
        if url.endswith("/api/v1/models/load"):
            model = str(payload.get("model") or "")
            self.load_calls.append(model)
            return httpx.Response(
                200,
                request=request,
                json={"status": "loaded", "instance_id": model},
            )
        if url.endswith("/api/v1/models/unload"):
            self.unload_calls.append(str(payload.get("instance_id") or ""))
            return httpx.Response(200, request=request, json={"status": "unloaded"})
        if url.endswith("/chat/completions"):
            self._chat_attempts += 1
            if self.chat_fail_unloaded and self._chat_attempts == 1:
                response = httpx.Response(
                    400,
                    request=request,
                    json={"error": {"message": "Model unloaded."}},
                )
                raise httpx.HTTPStatusError("model unloaded", request=request, response=response)
            return httpx.Response(
                200,
                request=request,
                json={"choices": [{"message": {"content": '{"ok": true}'}}]},
            )
        return httpx.Response(404, request=request)


def test_prepare_model_loads_unloaded_target(monkeypatch):
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "qwen/qwen3-coder-30b")
    client = LoadTrackingClient()
    provider._client = client  # type: ignore[assignment]

    prepared = provider.prepare_model("qwen/qwen3-coder-30b", "planner")

    assert prepared == "qwen/qwen3-coder-30b"
    assert client.load_calls == ["qwen/qwen3-coder-30b"]


def test_prepare_model_falls_back_when_load_fails(monkeypatch):
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "qwen/qwen3-coder-30b")
    client = LoadTrackingClient()
    provider._client = client  # type: ignore[assignment]
    monkeypatch.setattr(provider, "load_model", lambda _model: False)

    prepared = provider.prepare_model("qwen/qwen3-coder-30b", "planner")

    assert prepared == "qwen3.6-27b"


def test_invoke_json_retries_after_model_unloaded():
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "qwen/qwen3-coder-30b")
    client = LoadTrackingClient(chat_fail_unloaded=True)
    provider._client = client  # type: ignore[assignment]

    content = provider.invoke_json("system", "user")

    assert content == '{"ok": true}'
    assert client.load_calls == ["qwen/qwen3-coder-30b"]


def test_prepare_model_skips_load_when_already_loaded():
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "qwen3.6-27b")
    catalog = LMStudioCatalog(
        models=[
            LMStudioModelRecord(
                id="qwen3.6-27b",
                state="loaded",
                loaded_instances=["qwen3.6-27b"],
                tool_use=True,
            )
        ]
    )
    monkeypatch_load = []
    provider.fetch_catalog = lambda: catalog  # type: ignore[method-assign]
    provider.load_model = lambda model: monkeypatch_load.append(model) or True  # type: ignore[method-assign]

    prepared = provider.prepare_model("qwen3.6-27b", "planner")

    assert prepared == "qwen3.6-27b"
    assert monkeypatch_load == []
