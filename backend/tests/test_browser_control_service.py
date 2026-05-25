"""Tests for browser control service."""

import asyncio

import pytest

from app.services.browser_control_service import BrowserControlService


@pytest.mark.asyncio
async def test_browser_control_execute_resolves_on_result():
    service = BrowserControlService()
    queue = service.register_client("proj-1")
    assert service.has_client("proj-1")

    execute_task = asyncio.create_task(
        service.execute("proj-1", "navigate", {"url": "http://localhost:5173/"}, timeout=5),
    )
    command = await asyncio.wait_for(queue.get(), timeout=2)
    service.resolve_result("proj-1", command["request_id"], True, {"navigated": True}, None)
    result = await asyncio.wait_for(execute_task, timeout=5)
    assert result["ok"] is True
    assert result["result"]["navigated"] is True
    service.unregister_client("proj-1")


@pytest.mark.asyncio
async def test_browser_control_requires_client():
    service = BrowserControlService()
    result = await service.execute("missing", "snapshot", {}, timeout=1)
    assert result["ok"] is False
    assert result["error"] == "browser_client_required"
