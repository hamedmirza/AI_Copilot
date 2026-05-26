import json

import pytest

from app.agents.payload_normalize import (
    loads_agent_json,
    normalize_agent_payload,
    preprocess_agent_json_text,
    repair_agent_json_text,
)


def test_strip_markdown_json_fence():
    raw = '```json\n{"summary": "ok", "file_changes": []}\n```'
    assert json.loads(preprocess_agent_json_text(raw))["summary"] == "ok"


def test_remove_trailing_commas():
    raw = '{"summary": "ok", "file_changes": [],}'
    assert json.loads(repair_agent_json_text(raw))["summary"] == "ok"


def test_escape_literal_newlines_inside_strings():
    raw = (
        '{"summary": "patch", "file_changes": [{"path": "a.py", "line_changes": '
        '[{"start_line": 1, "end_line": 1, "new_content": "line one\nline two"}]}], '
        '"requires_operator_approval": false}'
    )
    payload = loads_agent_json(raw)
    content = payload["file_changes"][0]["line_changes"][0]["new_content"]
    assert content == "line one\nline two"


def test_extract_outer_json_object_from_noise():
    raw = 'Here is the patch:\n{"summary": "ok", "file_changes": []}\nThanks.'
    payload = loads_agent_json(raw)
    assert payload["summary"] == "ok"


def test_normalize_coder_aliases():
    payload = normalize_agent_payload(
        "CoderOutput",
        {
            "status": "done",
            "patches": [{"file": "x.py", "line_changes": [{"start_line": 1, "end_line": 1, "new_content": "a"}]}],
        },
    )
    assert payload["summary"] == "done"
    assert payload["file_changes"][0]["path"] == "x.py"


def test_loads_agent_json_raises_on_garbage():
    with pytest.raises(json.JSONDecodeError):
        loads_agent_json("not json at all")
