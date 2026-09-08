import asyncio
from collections import deque
from typing import Any, Deque, Dict, List

# Eventos retenidos por investigación para el replay de la consola en vivo.
# El historial vivía sin tope y no se purgaba nunca: una investigación con miles
# de plataformas emite un evento de progreso cada 40 comprobaciones, y el proceso
# acumulaba todo indefinidamente. Un deque acotado conserva el tramo reciente
# (que es el que interesa reproducir al reconectar) con memoria constante.
MAX_HISTORY_PER_INVESTIGATION = 500

# Investigaciones distintas cuyo historial se mantiene simultáneamente. Evita que
# un proceso de larga vida retenga el historial de cada investigación jamás
# ejecutada; se descarta el más antiguo cuando se supera el tope.
MAX_TRACKED_INVESTIGATIONS = 100


class EventBus:
    """
    Bus de eventos en memoria con retención acotada, para el streaming SSE y la
    reproducción de logs de la consola en vivo.

    Vive dentro de un único proceso: si el servidor se arranca con más de un
    worker, el worker que sirve el stream puede no ser el que publica, y el SSE
    deja de recibir eventos en silencio. `app.main` avisa de ello en el arranque.
    """

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        self._history: Dict[str, Deque[Dict[str, Any]]] = {}
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
            history = self._history.get(investigation_id)
            if history is None:
                self._evict_if_needed()
                history = deque(maxlen=MAX_HISTORY_PER_INVESTIGATION)
                self._history[investigation_id] = history
            history.append(event)
            queues = list(self._subscribers.get(investigation_id, []))

        for q in queues:
            await q.put(event)

    def _evict_if_needed(self) -> None:
        """Descarta el historial más antiguo si se supera el tope de investigaciones.

        Debe llamarse con el lock tomado. Los dicts de Python conservan el orden
        de inserción, así que las primeras claves son las más antiguas. Nunca se
        descarta el historial de una investigación que alguien está siguiendo por
        SSE en ese momento; si todas están siendo seguidas no se expulsa nada,
        antes que romper el replay de un stream activo.
        """
        evictable = [
            inv_id for inv_id in self._history
            if inv_id not in self._subscribers
        ]
        excess = len(self._history) - MAX_TRACKED_INVESTIGATIONS + 1
        for inv_id in evictable[:max(0, excess)]:
            del self._history[inv_id]

    def get_history(self, investigation_id: str) -> List[Dict[str, Any]]:
        return list(self._history.get(investigation_id, []))

    async def clear(self, investigation_id: str) -> None:
        """Libera el historial de una investigación (al borrarla, por ejemplo)."""
        async with self._lock:
            self._history.pop(investigation_id, None)


event_bus = EventBus()
