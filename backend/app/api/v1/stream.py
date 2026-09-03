import asyncio
import json
from uuid import UUID
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.core.events import event_bus

router = APIRouter()


@router.get("/investigations/{id}/stream")
async def stream_investigation_events(id: UUID):
    """
    Server-Sent Events (SSE) endpoint providing real-time streaming updates
    of tool executions, discoveries, and agent logs.
    """
    str_id = str(id)
    queue = await event_bus.subscribe(str_id)

    async def event_generator():
        try:
            # Yield initial connection confirmation
            yield f"data: {json.dumps({'type': 'connected', 'investigation_id': str_id})}\n\n"

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=120.0)
                    yield f"data: {json.dumps(event)}\n\n"

                    # Close stream gracefully once completed or failed
                    if event.get("type") in ["investigation_complete", "investigation_error"]:
                        break
                except asyncio.TimeoutError:
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
