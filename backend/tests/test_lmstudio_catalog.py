from __future__ import annotations

from app.services.lmstudio_catalog import (
    LMStudioCatalog,
    LMStudioModelRecord,
    merge_catalog_payload,
)


def test_merge_catalog_payload_combines_v0_and_v1_fields():
    catalog = merge_catalog_payload(
        [
            {
                "id": "qwen3.6-27b",
                "state": "loaded",
                "capabilities": ["tool_use"],
            }
        ],
        [
            {
                "key": "qwen3.6-27b",
                "size_bytes": 16_000_000_000,
                "params_string": "27B",
                "capabilities": {"trained_for_tool_use": True},
                "loaded_instances": [{"id": "qwen3.6-27b"}],
                "quantization": {"name": "4bit"},
            },
            {
                "key": "qwen/qwen3-coder-next",
                "size_bytes": 50_000_000_000,
                "params_string": "80B",
                "capabilities": {"trained_for_tool_use": True},
                "loaded_instances": [],
                "quantization": {"name": "Q4_K_M"},
            },
        ],
    )

    assert catalog.ids() == ["qwen/qwen3-coder-next", "qwen3.6-27b"]
    loaded = catalog.by_id()["qwen3.6-27b"]
    assert loaded.is_loaded
    assert loaded.size_gb == 14.9


def test_resolve_runnable_prefers_smaller_fallback_for_oversized_model():
    catalog = LMStudioCatalog(
        models=[
            LMStudioModelRecord(
                id="qwen3.6-27b",
                state="loaded",
                size_bytes=16_000_000_000,
                loaded_instances=["qwen3.6-27b"],
                tool_use=True,
            ),
            LMStudioModelRecord(
                id="qwen/qwen3-coder-next",
                state="not-loaded",
                size_bytes=50_000_000_000,
                tool_use=True,
            ),
        ]
    )

    selected, unload = catalog.resolve_runnable("qwen/qwen3-coder-next", "agent")

    assert selected == "qwen3.6-27b"
    assert unload == []


def test_pick_best_prefers_loaded_coder_for_agent_mode():
    catalog = LMStudioCatalog(
        models=[
            LMStudioModelRecord(id="openai/gpt-oss-20b", state="not-loaded", size_bytes=12_000_000_000, tool_use=True),
            LMStudioModelRecord(
                id="qwen/qwen3-coder-next",
                state="loaded",
                size_bytes=20_000_000_000,
                loaded_instances=["qwen/qwen3-coder-next"],
                tool_use=True,
            ),
        ]
    )

    assert catalog.pick_best("agent") == "qwen/qwen3-coder-next"
