import asyncio
import time
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self.started_at = time.time()
        self.ws_connections = 0
        self._run_queues: dict[str, list[asyncio.Queue]] = {}
        self._chat_queues: dict[str, list[asyncio.Queue]] = {}
        self._browser_queues: dict[str, list[asyncio.Queue]] = {}
        self._global_queues: list[asyncio.Queue] = []
        self.browser_clients: set[str] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop | None) -> None:
        self._loop = loop

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def subscribe_run(self, run_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._run_queues.setdefault(run_id, []).append(queue)
        return queue

    def unsubscribe_run(self, run_id: str, queue: asyncio.Queue) -> None:
        queues = self._run_queues.get(run_id, [])
        if queue in queues:
            queues.remove(queue)

    def subscribe_global(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._global_queues.append(queue)
        return queue

    def unsubscribe_global(self, queue: asyncio.Queue) -> None:
        if queue in self._global_queues:
            self._global_queues.remove(queue)

    def emit(self, run_id: str, event: dict[str, Any]) -> None:
        payload = {"run_id": run_id, **event}
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        coroutine = self._dispatch(run_id, payload)
        try:
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        except RuntimeError:
            coroutine.close()

    def subscribe_chat(self, session_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._chat_queues.setdefault(session_id, []).append(queue)
        return queue

    def unsubscribe_chat(self, session_id: str, queue: asyncio.Queue) -> None:
        queues = self._chat_queues.get(session_id, [])
        if queue in queues:
            queues.remove(queue)

    def emit_chat(self, session_id: str, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        coroutine = self._dispatch_chat(session_id, event)
        try:
            asyncio.run_coroutine_threadsafe(coroutine, loop)
        except RuntimeError:
            coroutine.close()

    async def _dispatch(self, run_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._run_queues.get(run_id, [])):
            await queue.put(event)
        for queue in list(self._global_queues):
            await queue.put(event)

    async def _dispatch_chat(self, session_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._chat_queues.get(session_id, [])):
            await queue.put(event)

    def subscribe_browser(self, project_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._browser_queues.setdefault(project_id, []).append(queue)
        self.browser_clients.add(project_id)
        return queue

    def unsubscribe_browser(self, project_id: str, queue: asyncio.Queue) -> None:
        queues = self._browser_queues.get(project_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._browser_queues.pop(project_id, None)
            self.browser_clients.discard(project_id)


event_bus = EventBus()
