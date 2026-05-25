"""Chat context includes page_element from browser picker."""

from __future__ import annotations

import json

from app.services.chat_orchestrator import ChatOrchestrator


def test_page_element_survives_context_truncation():
    orchestrator = ChatOrchestrator()
    page_element = {
        "url": "http://localhost:3000/",
        "selector": "div.header > button.primary",
        "tag_name": "button",
        "text_preview": "Save",
        "outer_html_snippet": "<button class=\"primary\">Save</button>",
    }
    context = {
        "open_files": ["frontend/src/App.tsx"],
        "page_element": page_element,
    }
    truncated = orchestrator._truncate_value(context)
    assert isinstance(truncated, dict)
    assert "page_element" in truncated
    pe = truncated["page_element"]
    assert pe.get("selector") == page_element["selector"]


def test_build_provider_messages_includes_page_element_hint():
    orchestrator = ChatOrchestrator()
    messages = orchestrator._build_provider_messages(
        [],
        project_path="/tmp/project",
        mode_prompt="You are a helper.",
        context={
            "page_element": {
                "selector": "#save-btn",
                "tag_name": "button",
            },
        },
        use_nothink=False,
    )
    system = messages[0]["content"]
    assert "page_element" in system
    assert "search_files" in system
    assert "#save-btn" in system or "save-btn" in system
