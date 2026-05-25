from __future__ import annotations

from app.services.chat_orchestrator import ChatOrchestrator


def test_provider_runtime_context_uses_live_config():
    runtime = ChatOrchestrator._provider_runtime_context(
        {
            "ollama_enabled": False,
            "lmstudio_base_url": "http://172.10.1.2:1234/v1",
            "ollama_base_url": "http://172.10.1.2:11434/v1",
            "lmstudio_model": "qwen3.6-27b",
            "ollama_model": "qwen3.6:latest",
        },
    )
    assert runtime["active_provider"] == "lmstudio"
    assert runtime["lmstudio_base_url"] == "http://172.10.1.2:1234/v1"


def test_build_provider_messages_includes_runtime_settings():
    orchestrator = ChatOrchestrator()
    messages = orchestrator._build_provider_messages(
        [],
        project_path="/tmp/project",
        mode_prompt="You are helpful.",
        context={"open_files": []},
        provider_runtime={
            "active_provider": "lmstudio",
            "lmstudio_base_url": "http://172.10.1.2:1234/v1",
            "ollama_base_url": "http://172.10.1.2:11434/v1",
            "lmstudio_model_default": "qwen3.6-27b",
            "ollama_model_default": "qwen3.6:latest",
            "note": "live settings",
        },
        use_nothink=False,
    )
    content = messages[0]["content"]
    assert "runtime_settings" in content
    assert "http://172.10.1.2:1234/v1" in content
    assert "192.168.128.70" not in content
