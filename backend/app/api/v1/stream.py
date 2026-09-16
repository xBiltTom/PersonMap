import asyncio
import json
from uuid import UUID
from typing import Any, Dict, List
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from app.core.database import async_session_maker
from app.core.events import event_bus
from app.models.investigation import Investigation

router = APIRouter()


@router.get("/investigations/{id}/logs", response_model=List[Dict[str, Any]])
async def get_investigation_logs(id: UUID):
    """Returns all historical execution and orchestration logs for an investigation."""
    str_id = str(id)
    history = event_bus.get_history(str_id)
    if history:
        return history

    # If in-memory history was cleared (e.g. after restart), rebuild summary logs from DB
    async with async_session_maker() as db:
        inv = await db.get(Investigation, id)
        if inv and inv.status in ["completed", "failed"]:
            metrics = inv.metrics or {}
            exec_time = metrics.get("execution_time_seconds", 0)
            entities_count = metrics.get("entities_discovered", 0)
            strategy = inv.strategy

            return [
                {
                    "type": "log",
                    "phase": "init",
                    "message": f"Investigación ejecutada con estrategia [{strategy}].",
                    "timestamp": inv.created_at.timestamp() if inv.created_at else 0,
                },
                {
                    "type": "log",
                    "phase": "complete",
                    "message": f"Extracción completada: {entities_count} entidades descubiertas en {exec_time}s.",
                    "timestamp": inv.completed_at.timestamp() if inv.completed_at else 0,
                },
                {
                    "type": "investigation_complete",
                    "status": inv.status,
                    "message": "Investigación y mapa digital finalizados con éxito.",
                    "timestamp": inv.completed_at.timestamp() if inv.completed_at else 0,
                },
            ]

    return []


@router.get("/investigations/{id}/stream")
async def stream_investigation_events(id: UUID):
    """
    Server-Sent Events (SSE) endpoint providing real-time streaming updates
    with automatic history replay and graceful completion closure.
    """
    str_id = str(id)
    queue = await event_bus.subscribe(str_id)

    # Check if investigation is already finished in DB
    is_already_finished = False
    status_in_db = "pending"

    async with async_session_maker() as db:
        inv = await db.get(Investigation, id)
        if inv and inv.status in ["completed", "failed"]:
            is_already_finished = True
            status_in_db = inv.status

    async def event_generator():
        try:
            # Yield initial connection confirmation
            yield f"data: {json.dumps({'type': 'connected', 'investigation_id': str_id})}\n\n"

            # Drain queue of all past events and stream them
            while not queue.empty():
                past_event = queue.get_nowait()
                yield f"data: {json.dumps(past_event)}\n\n"
                if past_event.get("type") in ["investigation_complete", "investigation_error"]:
                    return

            if is_already_finished:
                # If investigation was already done and completion event wasn't in history
                yield f"data: {json.dumps({'type': 'investigation_complete', 'status': status_in_db, 'message': 'Investigación ya completada.'})}\n\n"
                return

            # Wait for future events
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=60.0)
                    yield f"data: {json.dumps(event)}\n\n"

                    # Close stream gracefully once completed or failed
                    if event.get("type") in ["investigation_complete", "investigation_error"]:
                        break
                except asyncio.TimeoutError:
                    # Check DB in case completion wasn't received
                    async with async_session_maker() as db:
                        check_inv = await db.get(Investigation, id)
                        if check_inv and check_inv.status in ["completed", "failed"]:
                            yield f"data: {json.dumps({'type': 'investigation_complete', 'status': check_inv.status, 'message': 'Investigación finalizada.'})}\n\n"
                            break
                    # Keep-alive ping
                    yield f": keep-alive\n\n"
        finally:
            await event_bus.unsubscribe(str_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
