from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from app.agents.tool_runtime import PipelineToolExecutionContext, PipelineToolRuntime


def test_read_file_missing_path_returns_recoverable_error(tmp_path: Path):
    project = MagicMock()
    project.protected_files = []
    run = MagicMock()
    context = PipelineToolExecutionContext(
        db=MagicMock(),
        project=project,
        run=run,
        workspace=tmp_path,
    )
    runtime = PipelineToolRuntime(context, allow_web_search=False)

    payload = json.loads(
        runtime.execute("read_file", {"path": "backend/app/tools/web_search.py"})
    )

    assert payload["ok"] is False
    assert "web_search.py" in payload["error"]
    assert payload["tool"] == "read_file"
