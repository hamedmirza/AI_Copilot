"""IDE browser control via WebSocket command channel."""

from __future__ import annotations

import asyncio
import base64
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.services.browser_preview_service import BrowserPreviewService
from app.services.run_engine.event_bus import event_bus

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30.0
BROWSER_WAIT_POLL_S = 45.0
BROWSER_WAIT_INTERVAL_S = 1.0


@dataclass
class _PendingCommand:
    future: asyncio.Future[dict[str, Any]]
    project_id: str
    run_id: str | None = None


@dataclass
class BrowserControlService:
    _pending: dict[str, _PendingCommand] = field(default_factory=dict)
    _clients: dict[str, asyncio.Queue] = field(default_factory=dict)
    _pipeline_lock: dict[str, str | None] = field(default_factory=dict)
    _cancelled: set[str] = field(default_factory=set)

    def has_client(self, project_id: str) -> bool:
        return project_id in self._clients

    async def wait_for_client(self, project_id: str, timeout: float = BROWSER_WAIT_POLL_S) -> bool:
        if self.has_client(project_id):
            return True
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self.has_client(project_id):
                return True
            await asyncio.sleep(BROWSER_WAIT_INTERVAL_S)
        return self.has_client(project_id)

    def register_client(self, project_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._clients[project_id] = queue
        return queue

    def unregister_client(self, project_id: str) -> None:
        self._clients.pop(project_id, None)

    def resolve_result(
        self,
        project_id: str,
        request_id: str,
        ok: bool,
        result: dict | None,
        error: str | None,
    ) -> None:
        pending = self._pending.pop(request_id, None)
        if not pending or pending.project_id != project_id:
            return
        if pending.future.done():
            return
        payload = {"ok": ok, "result": result or {}, "error": error}
        pending.future.set_result(payload)

    def cancel_request(self, request_id: str) -> None:
        self._cancelled.add(request_id)
        pending = self._pending.pop(request_id, None)
        if pending and not pending.future.done():
            pending.future.set_result({"ok": False, "result": {}, "error": "cancelled"})

    def acquire_pipeline_lock(self, project_id: str, run_id: str) -> bool:
        current = self._pipeline_lock.get(project_id)
        if current and current != run_id:
            return False
        self._pipeline_lock[project_id] = run_id
        return True

    def release_pipeline_lock(self, project_id: str, run_id: str | None = None) -> None:
        if run_id is None or self._pipeline_lock.get(project_id) == run_id:
            self._pipeline_lock.pop(project_id, None)

    async def execute(
        self,
        project_id: str,
        action: str,
        args: dict[str, Any] | None = None,
        *,
        run_id: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        require_client: bool = True,
    ) -> dict[str, Any]:
        if require_client and not self.has_client(project_id):
            return {"ok": False, "error": "browser_client_required", "result": {}}

        if run_id and not self.acquire_pipeline_lock(project_id, run_id):
            return {"ok": False, "error": "browser_busy", "result": {}}

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[request_id] = _PendingCommand(future=future, project_id=project_id, run_id=run_id)

        command = {
            "type": "browser_command",
            "request_id": request_id,
            "action": action,
            "args": args or {},
            "run_id": run_id,
            "highlight": action in {"click", "type", "scroll_into_view"},
        }
        client_queue = self._clients.get(project_id)
        if not client_queue:
            self._pending.pop(request_id, None)
            if run_id:
                self.release_pipeline_lock(project_id, run_id)
            return {"ok": False, "error": "browser_client_required", "result": {}}

        await client_queue.put(command)

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            return {"ok": False, "error": "browser_command_timeout", "result": {}}
        finally:
            if run_id:
                self.release_pipeline_lock(project_id, run_id)

    def execute_sync(
        self,
        project_id: str,
        action: str,
        args: dict[str, Any] | None = None,
        *,
        run_id: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_S,
        require_client: bool = True,
    ) -> dict[str, Any]:
        loop = event_bus.loop
        if loop is None or loop.is_closed():
            return {"ok": False, "error": "event_loop_unavailable", "result": {}}
        coro = self.execute(
            project_id,
            action,
            args,
            run_id=run_id,
            timeout=timeout,
            require_client=require_client,
        )
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout=timeout + 5)
        except Exception as exc:
            logger.warning("browser execute_sync failed: %s", exc)
            return {"ok": False, "error": str(exc), "result": {}}

    def validate_loopback_url(self, url: str) -> str:
        return BrowserPreviewService()._normalize_loopback_url(url)  # noqa: SLF001

    @staticmethod
    def save_screenshot_data_url(data_url: str, dest: Path) -> None:
        if not data_url.startswith("data:"):
            raise ValueError("Invalid screenshot data URL")
        _, encoded = data_url.split(",", 1)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(encoded))


browser_control = BrowserControlService()
