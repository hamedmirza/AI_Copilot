"""Stage progress heartbeats during long blocking LLM calls."""

from __future__ import annotations

import time
from unittest.mock import patch

from app.services.orchestration_service import OrchestrationService


def test_run_with_stage_heartbeat_emits_stage_progress():
    service = OrchestrationService()
    captured: list[dict] = []

    def capture_emit(run_id: str, event_type: str, stage: str, message: str, payload=None, **kwargs):
        captured.append(
            {
                "run_id": run_id,
                "type": event_type,
                "stage": stage,
                "message": message,
                "payload": payload or {},
            }
        )

    with patch.object(service, "_emit", side_effect=capture_emit):
        service._run_with_stage_heartbeat("run-hb", "coder", lambda: time.sleep(21))

    progress = [e for e in captured if e["type"] == "stage_progress"]
    assert progress, "expected at least one stage_progress heartbeat"
    assert progress[0]["stage"] == "coder"
    assert "Still working" in progress[0]["message"]
