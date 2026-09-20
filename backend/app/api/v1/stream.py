import asyncio
import json
from datetime import datetime
from uuid import UUID
from typing import Any, Dict, Iterable, List
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from app.core.database import async_session_maker
from app.core.events import event_bus
from app.models.investigation import Investigation
from app.models.investigation_trace_event import InvestigationTraceEvent
from app.models.tool_execution import ToolExecution

router = APIRouter()


def _timestamp(value: datetime | None) -> float:
    """Timestamp para el contrato SSE, sin inventar una hora si no existe."""
    return value.timestamp() if value else 0.0


def _layer(engine: str, engine_layer: str | None) -> str | None:
    """Mantiene la terminología de la consola sin crear una capa nueva."""
    return engine_layer or ("agentic" if engine == "agentic" else None)


def _pivot_message(data: Dict[str, Any]) -> str:
    additions = data.get("additions")
    if not isinstance(additions, dict):
        return "Pivote incorporado al contexto."
    parts = [
        f"+{count} {kind}"
        for kind, count in additions.items()
        if isinstance(kind, str) and isinstance(count, int) and count > 0
    ]
    return "Pivote incorporado al contexto: " + " · ".join(parts) if parts else "Pivote incorporado al contexto."


def _trace_event_log(event: InvestigationTraceEvent) -> Dict[str, Any] | None:
    """Proyecta un evento estructural durable a una línea de consola legible.

    Solo se usan campos presentes en el evento. Los detalles de progreso y los
    argumentos de herramientas son deliberadamente efímeros y no se recrean.
    """
    data = event.data if isinstance(event.data, dict) else {}
    common: Dict[str, Any] = {
        "type": "log",
        "timestamp": _timestamp(event.created_at),
        "layer": _layer(event.engine, event.engine_layer),
    }
    if event.event_type == "engine_start":
        return {**common, "phase": "init", "message": f"Motor {event.engine} iniciado."}
    if event.event_type == "round_start" and event.round_index is not None:
        scheduled = data.get("tools_scheduled")
        suffix = f" · {scheduled} herramientas programadas" if isinstance(scheduled, int) else ""
        return {**common, "phase": f"round_{event.round_index}", "message": f"Ronda {event.round_index} iniciada{suffix}."}
    if event.event_type == "round_complete" and event.round_index is not None:
        count = data.get("findings_count")
        suffix = f" · {count} observaciones" if isinstance(count, int) else ""
        return {**common, "phase": "round_complete", "message": f"Ronda {event.round_index} completada{suffix}."}
    if event.event_type == "pivot":
        return {**common, "phase": "pivot", "message": _pivot_message(data)}
    if event.event_type == "refinement_start":
        return {**common, "phase": "hybrid_refine_start", "message": "Capa de refinamiento IA iniciada."}
    if event.event_type == "turn_start" and event.turn_index is not None:
        return {**common, "phase": "turn_start", "message": f"Turno IA {event.turn_index} iniciado."}
    if event.event_type == "turn_complete" and event.turn_index is not None:
        return {**common, "phase": "turn_complete", "message": f"Turno IA {event.turn_index} completado."}
    if event.event_type == "skipped_call":
        tool = data.get("tool_name")
        reason = data.get("reason")
        if isinstance(tool, str) and reason == "already_executed":
            message = f"Llamada omitida: {tool} ya fue cubierta por el barrido heurístico."
        elif isinstance(tool, str):
            message = f"Llamada omitida: {tool}."
        else:
            message = "Llamada omitida por el motor."
        return {**common, "phase": "hybrid_refine_skipped", "tool": tool if isinstance(tool, str) else None, "message": message}
    return None


def reconstruct_trace_logs(
    investigation: Investigation,
    executions: Iterable[ToolExecution],
    events: Iterable[InvestigationTraceEvent],
) -> List[Dict[str, Any]]:
    """Reconstruye una vista histórica desde la traza, no desde texto de logs."""
    entries: List[tuple[float, int, Dict[str, Any]]] = []

    for event in events:
        log = _trace_event_log(event)
        if log:
            entries.append((float(log["timestamp"]), 1, log))

    for execution in executions:
        layer = _layer(execution.engine, execution.engine_layer)
        execution_id = str(execution.id)
        entries.append((_timestamp(execution.started_at), 0, {
            "type": "tool_start",
            "tool": execution.tool_name,
            "layer": layer,
            "engine": execution.engine,
            "round_index": execution.round_index,
            "turn_index": execution.turn_index,
            "tool_execution_id": execution_id,
            "message": "Ejecución iniciada.",
            "timestamp": _timestamp(execution.started_at),
        }))
        if execution.completed_at:
            duration_seconds = max(0.0, (execution.completed_at - execution.started_at).total_seconds())
            is_error = execution.status == "failed"
            message = (
                f"Error · {execution.error_summary}"
                if is_error and execution.error_summary
                else "Error durante la ejecución."
                if is_error
                else f"Completado · {execution.findings_count} observaciones · {duration_seconds:.1f} s"
            )
            entries.append((_timestamp(execution.completed_at), 2, {
                "type": "tool_error" if is_error else "tool_complete",
                "tool": execution.tool_name,
                "layer": layer,
                "engine": execution.engine,
                "round_index": execution.round_index,
                "turn_index": execution.turn_index,
                "tool_execution_id": execution_id,
                "findings_count": execution.findings_count,
                "duration_seconds": duration_seconds,
                "error": execution.error_summary if is_error else None,
                "message": message,
                "timestamp": _timestamp(execution.completed_at),
            }))

    entries.sort(key=lambda item: (item[0], item[1]))
    logs = [entry for _, _, entry in entries]
    if investigation.completed_at:
        logs.append({
            "type": "investigation_complete" if investigation.status == "completed" else "investigation_error",
            "phase": "complete",
            "status": investigation.status,
            "message": "Investigación finalizada." if investigation.status == "completed" else "Investigación finalizada con errores.",
            "timestamp": _timestamp(investigation.completed_at),
        })
    return logs


@router.get("/investigations/{id}/logs")
async def get_investigation_logs(id: UUID):
    """Returns all historical execution and orchestration logs for an investigation."""
    str_id = str(id)
    history = event_bus.get_history(str_id)
    if history:
        return {"mode": "original", "logs": history}

    # El EventBus es efímero. Tras un reinicio, la proyección histórica sale de
    # la traza persistida y no pretende reproducir el progreso transitorio.
    async with async_session_maker() as db:
        inv = await db.get(Investigation, id)
        if inv:
            executions = list((await db.scalars(
                select(ToolExecution).where(ToolExecution.investigation_id == id)
            )).all())
            events = list((await db.scalars(
                select(InvestigationTraceEvent).where(InvestigationTraceEvent.investigation_id == id)
            )).all())
            if executions or events:
                return {"mode": "reconstructed", "logs": reconstruct_trace_logs(inv, executions, events)}

        if inv and inv.status in ["completed", "failed"]:
            metrics = inv.metrics or {}
            exec_time = metrics.get("execution_time_seconds", 0)
            entities_count = metrics.get("entities_discovered", 0)
            strategy = inv.strategy

            return {"mode": "legacy", "logs": [
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
            ]}

    return {"mode": "legacy", "logs": []}


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
                # Sin historial EventBus no se inyecta una línea genérica: la
                # consola ya obtuvo su proyección completa desde Trace DB.
                # Este marcador no tiene `message`, así que el cliente solo
                # cierra el stream sin alterar ese historial reconstruido.
                yield f"data: {json.dumps({'type': 'stream_complete', 'status': status_in_db})}\n\n"
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
