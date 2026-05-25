from __future__ import annotations

from app.services.chat_optimization import (
    effective_max_output_tokens,
    format_runtime_settings_answer,
    is_runtime_settings_question,
    should_offer_tools,
)


def test_is_runtime_settings_question_detects_lm_studio_ip():
    assert is_runtime_settings_question("what is the LM studio serve IP?")
    assert is_runtime_settings_question("which IP you use for LM connections in the chat?")
    assert not is_runtime_settings_question("how does chat_orchestrator build messages?")


def test_format_runtime_settings_answer_lmstudio():
    text = format_runtime_settings_answer(
        {
            "active_provider": "lmstudio",
            "lmstudio_base_url": "http://172.10.1.2:1234/v1",
            "ollama_base_url": "http://172.10.1.2:11434/v1",
            "lmstudio_model_default": "qwen3.6-27b",
            "ollama_model_default": "",
        }
    )
    assert "172.10.1.2:1234" in text
    assert "192.168.128.70" not in text


def test_should_offer_tools_skips_for_runtime_question_in_general():
    assert should_offer_tools("general", "LM studio IP?", read_only=True) is False
    assert should_offer_tools("general", "explain chat_orchestrator.py", read_only=True) is True


def test_effective_max_output_tokens_caps_general_and_runtime():
    config = {"chat_max_output_tokens": 4096}
    assert effective_max_output_tokens("general", config, "hello") == 1536
    assert effective_max_output_tokens("general", config, "lm studio ip?") == 512
    assert effective_max_output_tokens("agent", config, "hello") == 4096
