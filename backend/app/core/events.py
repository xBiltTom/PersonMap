import asyncio
from typing import Any, Dict, List


class EventBus:
    """In-memory event bus for SSE streaming of real-time investigation events."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, investigation_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(investigation_id, []).append(queue)
        return queue

    async def unsubscribe(self, investigation_id: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            if investigation_id in self._subscribers:
                if queue in self._subscribers[investigation_id]:
                    self._subscribers[investigation_id].remove(queue)
                if not self._subscribers[investigation_id]:
                    del self._subscribers[investigation_id]

    async def publish(self, investigation_id: str, event: Dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(investigation_id, []))
        for q in queues:
            await q.put(event)


event_bus = EventBus()
