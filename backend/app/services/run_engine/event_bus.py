import asyncio
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self.ws_connections = 0
        self._run_queues: dict[str, list[asyncio.Queue]] = {}
        self._global_queues: list[asyncio.Queue] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

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
        if self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._dispatch(run_id, payload), self._loop)

    async def _dispatch(self, run_id: str, event: dict[str, Any]) -> None:
        for queue in list(self._run_queues.get(run_id, [])):
            await queue.put(event)
        for queue in list(self._global_queues):
            await queue.put(event)


event_bus = EventBus()
