from __future__ import annotations

from unittest.mock import MagicMock

from app.providers.base import ChatStreamChunk
from app.providers.lmstudio import LMStudioProvider


def test_stream_tool_calls_ignores_reasoning_content_delta():
    """reasoning_content must not be forwarded as user-visible chat tokens."""
    provider = LMStudioProvider("http://example.test/v1", "lm-studio", "qwen3.6-27b")
    sse_payloads = [
        {
            "choices": [
                {
                    "delta": {"reasoning_content": "/Documents"},
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"reasoning_content": "/AI Apps"},
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {"content": "Hello"},
                    "finish_reason": None,
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {},
                    "finish_reason": "stop",
                }
            ]
        },
    ]

    provider._iter_sse_json = lambda _response: iter(sse_payloads)  # type: ignore[method-assign]

    chunks = list(provider._stream_tool_calls(MagicMock()))
    text_deltas = [chunk.delta for chunk in chunks if isinstance(chunk, ChatStreamChunk) and chunk.delta]

    assert text_deltas == ["Hello"]
    assert chunks[-1].done is True
