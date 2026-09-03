import asyncio
from typing import Any, Dict, List


class EventBus:
    """
    In-memory event bus with history retention for SSE streaming
    and real-time log playback.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._history: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, investigation_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(investigation_id, []).append(queue)
            # Replay all past events for this investigation into the new queue
            past_events = list(self._history.get(investigation_id, []))

        for event in past_events:
            await queue.put(event)

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
            self._history.setdefault(investigation_id, []).append(event)
            queues = list(self._subscribers.get(investigation_id, []))

        for q in queues:
            await q.put(event)

    def get_history(self, investigation_id: str) -> List[Dict[str, Any]]:
        return list(self._history.get(investigation_id, []))


event_bus = EventBus()
